# -*- coding: utf-8 -*-
"""Md2docs 原生桌面界面（Tkinter + ttk）。

设计要点
--------
* 纯本地：不使用 WebView / Electron / 内置 HTTP 服务，界面完全由系统原生 Tk
  控件绘制；打包后 Tcl/Tk 运行时内嵌在 EXE 里，目标机器无需安装任何额外组件。
* 单页无滚动：所有内容自适应窗口高度，只有列表区域自带滚动条。
* 严格遵守用户显式选择：输出位置、输出格式、TXT 选项一律以界面选择为准，
  程序绝不擅自替用户切换输出模式。
* 所有输入文件都来自磁盘真实路径（浏览选择、命令行 /「发送到」、窗口拖放），
  因此不存在"内存文件"，输出位置始终可靠。
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, ttk

import convert
import i18n
import settings

# --------------------------------------------------------------------------- #
# 配色（对齐原界面视觉）
# --------------------------------------------------------------------------- #
BG = "#0f1117"
PANEL = "#171b26"
PANEL2 = "#1d2230"
CARD_ON = "#2b3155"
LINE = "#262c3b"
TEXT = "#e6e9f0"
DIM = "#9aa3b8"
MUTE = "#6b7488"
ACCENT = "#6366f1"
ACCENT_HI = "#7c7ff5"
CARD_ON_HI = "#343a66"
OK = "#34d399"
WARN = "#fbbf24"
ERR = "#f87171"

FMT_ORDER = ["docx", "doc", "wps", "txt"]
FMT_TAG = {"docx": "DOCX", "doc": "DOC", "wps": "WPS", "txt": "TXT"}

MD_EXTS = (".md", ".markdown", ".mdown", ".mkd", ".mdtext", ".mdtxt", ".txt")


def fmt_desc(fid: str) -> str:
    """格式卡片上的说明文字（随界面语言）。"""
    return i18n.t("fmt.desc." + fid)


def window_title() -> str:
    """窗口标题（随界面语言；回归脚本据此定位窗口）。"""
    return i18n.t("app.window_title")

# 窗口设计宽度（客户区）。必须为常量，不可由内容宽度反推——原因见
# Md2docsApp._window_width()：表格可伸缩列会与窗口宽度互相抬高，
# 形成自增循环，表现为每点击一次格式卡片窗口就变宽一点。
WIN_W = 988

# 结果行的 ASCII 状态标记，**只用于控制台输出**（--selftest 逐行打印）。
# 不打印结果表里的状态文案：那是界面用词，可能带控制台编码打不出的字符。
STATE_MARKS = {"ok": "OK", "warn": "WARN", "bad": "FAIL"}


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def fmt_size(n: int) -> str:
    if not n:
        return "0 B"
    units = ["B", "KB", "MB", "GB"]
    i, val = 0, float(n)
    while val >= 1024 and i < len(units) - 1:
        val /= 1024.0
        i += 1
    return ("%d %s" if i == 0 else "%.1f %s") % (val, units[i])


def resource_path(name: str) -> str:
    """兼容 PyInstaller 单文件打包后的资源路径。"""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, name)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        os.pardir, name)


def mark_text(widget, key: str):
    """给控件挂上词条键：语言切换时 retranslate() 会顺着控件树就地重设。

    这是界面文案的统一入口——凡出现在界面上的静态文字都必须经过这里，
    否则切换语言时会残留旧语言。``tools/check_i18n.py`` 负责强制这条约束。
    """
    try:
        widget._tr_key = key
        widget.configure(text=i18n.t(key))
    except Exception:
        pass
    return widget


def walk_widgets(widget):
    """深度遍历控件树（语言切换时就地重译用）。"""
    yield widget
    try:
        children = widget.winfo_children()
    except Exception:
        return
    for child in children:
        yield from walk_widgets(child)


def open_path(path: str) -> tuple[bool, str]:
    if not path:
        return False, i18n.t("err.empty_path")
    if not os.path.exists(path):
        return False, i18n.t("err.path_missing")
    try:
        os.startfile(path)          # noqa: S606 - Windows 原生打开
        return True, ""
    except Exception as exc:
        return False, "%s: %s" % (type(exc).__name__, exc)


def enable_hi_dpi() -> None:
    """让窗口在 125% / 150% 缩放下保持清晰（必须在创建 Tk 之前调用）。"""
    if os.name != "nt":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PER_MONITOR
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Win32 原生文件拖放（WM_DROPFILES，零第三方依赖）
# --------------------------------------------------------------------------- #
# 关键约束（V-11，改动前务必看懂）：
# 窗口过程是在 Tk 消息泵内部被调用的，而 Tk 在泵消息时是**释放了 GIL** 的
# （C 层 Py_BEGIN_ALLOW_THREADS）。此时只要回调里碰到一丁点 Tcl/Tk
# （root.after / event_generate / 操作控件），就会破坏主线程状态，抛出
#     Fatal Python error: PyEval_RestoreThread: ... the current Python
#     thread state is NULL
# 并让进程当场消失，既没有异常也没有弹窗——表现就是"把文件拖进去程序就退了"。
# 因此窗口过程只做一件事：把 HDROP 句柄压进队列后立刻返回；解析路径、更新
# 界面统统交给 Tk 定时器在主线程正常上下文里完成。
DROP_POLL_MS = 120


def _read_hdrop(wintypes, hdrop: int) -> list:
    """解析 HDROP 句柄中的文件路径，并释放该句柄。"""
    import ctypes

    shell32 = ctypes.windll.shell32
    shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT,
                                       wintypes.LPWSTR, wintypes.UINT]
    shell32.DragQueryFileW.restype = wintypes.UINT
    shell32.DragFinish.argtypes = [wintypes.HANDLE]

    paths: list = []
    try:
        count = shell32.DragQueryFileW(wintypes.HANDLE(hdrop), 0xFFFFFFFF,
                                       None, 0)
        for i in range(int(count or 0)):
            buf = ctypes.create_unicode_buffer(32768)
            if shell32.DragQueryFileW(wintypes.HANDLE(hdrop), i, buf, 32768):
                if buf.value:
                    paths.append(buf.value)
    except Exception:
        pass
    try:
        shell32.DragFinish(wintypes.HANDLE(hdrop))
    except Exception:
        pass
    return paths


def enable_file_drop(root: tk.Misc, on_drop) -> bool:
    """把文件拖进窗口即触发 on_drop(paths)。

    直接使用 Win32 的消息机制；任何环节失败都安静放弃（浏览按钮与
    「拖到 EXE 图标上」两条路径始终可用），不影响程序其余功能。
    """
    if os.name != "nt" or os.environ.get("MD2DOCS_NO_DND") == "1":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32

        root.update_idletasks()
        child = root.winfo_id()
        # Tk 顶层窗口的实际 HWND 是子窗口的父级，拖放消息发往它
        hwnd = user32.GetParent(child) or child

        shell32.DragAcceptFiles(wintypes.HWND(hwnd), True)

        WNDPROC = ctypes.WINFUNCTYPE(
            ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
            wintypes.WPARAM, wintypes.LPARAM)

        is64 = ctypes.sizeof(ctypes.c_void_p) == 8
        if is64:
            set_long = user32.SetWindowLongPtrW
            set_long.restype = ctypes.c_void_p
            set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            get_long = user32.GetWindowLongPtrW
            get_long.restype = ctypes.c_void_p
            get_long.argtypes = [wintypes.HWND, ctypes.c_int]
        else:
            set_long = user32.SetWindowLongW
            set_long.restype = ctypes.c_void_p
            set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            get_long = user32.GetWindowLongW
            get_long.restype = ctypes.c_void_p
            get_long.argtypes = [wintypes.HWND, ctypes.c_int]

        call_proc = user32.CallWindowProcW
        call_proc.restype = ctypes.c_longlong
        call_proc.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                              wintypes.WPARAM, wintypes.LPARAM]

        GWLP_WNDPROC = -4
        WM_DROPFILES = 0x0233

        old_proc = get_long(wintypes.HWND(hwnd), GWLP_WNDPROC)
        pending: list = []                      # 已收到、待处理的 HDROP 句柄

        def handler(h, msg, wparam, lparam):
            # 只入队便返回：这里绝不能触碰 Tk（见本节顶部 V-11 说明）
            if msg == WM_DROPFILES:
                try:
                    pending.append(int(wparam))
                except Exception:
                    pass
                return 0
            return call_proc(old_proc, h, msg, wparam, lparam)

        proc = WNDPROC(handler)
        set_long(wintypes.HWND(hwnd), GWLP_WNDPROC,
                 ctypes.cast(proc, ctypes.c_void_p))
        # 必须保留引用，否则回调被回收会导致进程崩溃
        root._md2docs_dnd = (proc, old_proc, hwnd, set_long, pending)  # noqa: SLF001

        def drain():
            """由 Tk 定时器驱动，在正常上下文里消费拖放句柄。"""
            while pending:
                paths = _read_hdrop(wintypes, pending.pop(0))
                if not paths:
                    continue
                try:
                    on_drop(paths)
                except Exception:
                    pass
            try:
                if root.winfo_exists():
                    root._md2docs_dnd_timer = root.after(DROP_POLL_MS, drain)  # noqa: SLF001
            except Exception:
                pass

        root._md2docs_dnd_timer = root.after(DROP_POLL_MS, drain)    # noqa: SLF001
        return True
    except Exception:
        return False


def disable_file_drop(root: tk.Misc) -> None:
    """还原窗口过程并停止轮询（退出前调用，避免收尾阶段再进回调）。"""
    ref = getattr(root, "_md2docs_dnd", None)
    try:
        root._md2docs_dnd = None
    except Exception:
        pass
    tid = getattr(root, "_md2docs_dnd_timer", None)
    try:
        root._md2docs_dnd_timer = None
    except Exception:
        pass
    if tid is not None:
        try:
            root.after_cancel(tid)
        except Exception:
            pass
    if not ref:
        return
    try:
        import ctypes
        from ctypes import wintypes

        _proc, old_proc, hwnd, set_long, pending = ref
        while pending:                          # 释放未消费的拖放句柄
            _read_hdrop(wintypes, pending.pop(0))
        if old_proc:
            set_long(wintypes.HWND(hwnd), -4, ctypes.c_void_p(old_proc))
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# 圆角按钮
# --------------------------------------------------------------------------- #
def round_rect(canvas: tk.Canvas, x1, y1, x2, y2, r, **kw):
    """在 Canvas 上画圆角矩形——Tk 没有原生的圆角图元。

    用一圈控制点配 smooth=True 做贝塞尔平滑：比「四条圆弧 + 两个矩形」拼接
    更稳，高 DPI 下也不会出现接缝。
    """
    r = max(0, min(r, (x2 - x1) / 2.0, (y2 - y1) / 2.0))
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1,
        x2, y1 + r, x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2, x1, y2,
        x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


class RoundButton(tk.Canvas):
    """圆角按钮。

    Tk 原生 Button 只能画方角，所以这里用 Canvas 自绘。Canvas 自身底色取
    父容器颜色（``surround``），四角因此与面板融为一体。

    对外暴露 ``configure(text/fill/fg/hover/state)``，用法与 tk.Button 一致
    （``bg`` 作为 ``fill`` 的别名保留，方便旧调用点）。
    """

    KINDS = {
        # kind: (填充色, 文字色, 悬停填充色)
        "primary": (ACCENT, "#ffffff", ACCENT_HI),
        "soft": (PANEL2, TEXT, LINE),
        "ghost": (PANEL, DIM, PANEL2),
    }

    def __init__(self, parent, text="", command=None, kind="soft", font=None,
                 surround=PANEL, radius=8, padx=13, pady=5, min_width=0,
                 fill=None, fg=None, hover=None, state="normal"):
        super().__init__(parent, highlightthickness=0, bd=0, bg=surround,
                         cursor="hand2", takefocus=0)
        base_fill, base_fg, base_hover = self.KINDS.get(kind, self.KINDS["soft"])
        self._fill = fill or base_fill
        self._fg = fg or base_fg
        self._hover = hover or base_hover
        self._surround = surround
        self._radius = int(radius)
        self._padx = int(padx)
        self._pady = int(pady)
        self._min_w = int(min_width)
        self._text = text
        self._font = font
        self._command = command
        self._state = state
        self._hovering = False
        self._pressed = False
        # 命名警告：不要用 self._w / self._h。tkinter.Misc 用 self._w 存控件在
        # Tcl 里的路径名，一旦覆盖，任何 configure 都会炸成
        #     _tkinter.TclError: invalid command name "134"
        self._bw = self._bh = 1
        self._measure()
        self._redraw()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    # -- 尺寸 ------------------------------------------------------------ #
    def _measure(self):
        try:
            f = tkfont.Font(root=self, font=self._font)
        except Exception:
            f = tkfont.nametofont("TkDefaultFont")
        self._bw = max(self._min_w, f.measure(self._text) + 2 * self._padx)
        self._bh = f.metrics("linespace") + 2 * self._pady
        super().configure(width=self._bw, height=self._bh)

    # -- 绘制 ------------------------------------------------------------ #
    def _redraw(self):
        self.delete("all")
        fill, fg = self._fill, self._fg
        if self._state == "disabled":
            fg = MUTE
        elif self._pressed or self._hovering:
            fill = self._hover
        round_rect(self, 0, 0, self._bw - 1, self._bh - 1, self._radius,
                   fill=fill, outline=fill)
        self.create_text(self._bw / 2.0, self._bh / 2.0, text=self._text,
                         fill=fg, font=self._font)

    # -- 兼容 tk.Button 的 configure ------------------------------------- #
    def configure(self, cnf=None, **kw):
        opts = dict(cnf or {})
        opts.update(kw)
        dirty = False
        # bg 是旧调用写法，语义等同填充色
        for key, attr in (("fill", "_fill"), ("bg", "_fill"), ("fg", "_fg"),
                          ("hover", "_hover")):
            if key in opts:
                setattr(self, attr, opts.pop(key))
                dirty = True
        if "text" in opts:
            self._text = opts.pop("text")
            self._measure()
            dirty = True
        if "state" in opts:
            self._state = str(opts.pop("state"))
            try:
                super().configure(
                    cursor="hand2" if self._state != "disabled" else "arrow")
            except Exception:
                pass
            dirty = True
        if opts:
            super().configure(**opts)
        if dirty:
            self._redraw()
        return None

    config = configure

    def cget(self, key):
        if key == "text":
            return self._text
        if key == "state":
            return self._state
        return super().cget(key)

    def invoke(self):
        if self._state != "disabled" and self._command:
            self._command()

    # -- 事件 ------------------------------------------------------------ #
    def _on_enter(self, _e):
        if self._state == "disabled":
            return
        self._hovering = True
        self._redraw()

    def _on_leave(self, _e):
        self._hovering = False
        self._pressed = False
        self._redraw()

    def _on_press(self, _e):
        if self._state == "disabled":
            return
        self._pressed = True
        self._redraw()

    def _on_release(self, e):
        was_pressed = self._pressed
        self._pressed = False
        if self._state == "disabled":
            self._redraw()
            return
        inside = 0 <= e.x < self._bw and 0 <= e.y < self._bh
        self._hovering = inside
        self._redraw()
        if was_pressed and inside and self._command:
            self._command()


# --------------------------------------------------------------------------- #
# 折叠区
# --------------------------------------------------------------------------- #
class Fold(tk.Frame):
    """点标题栏展开 / 收起的区块，右侧可显示状态摘要。"""

    def __init__(self, parent, key: str, on_toggle=None, fonts=None):
        super().__init__(parent, bg=PANEL)
        self.fonts = fonts or {}
        self.on_toggle = on_toggle
        self.open = False

        self.head = tk.Frame(self, bg=PANEL, cursor="hand2")
        self.head.pack(fill="x")
        self.right = tk.Frame(self.head, bg=PANEL)
        self.right.pack(side="right")

        self.arrow = tk.Label(self.head, text="▸", bg=PANEL, fg=MUTE,
                              font=self.fonts.get("small"), width=2)
        self.arrow.pack(side="left")
        # 词条键挂在标题 Label 上（Fold 自身是 Frame，没有 text 选项）
        self.title = mark_text(
            tk.Label(self.head, bg=PANEL, fg=TEXT,
                     font=self.fonts.get("small")), key)
        self.title.pack(side="left")
        self.summary = tk.Label(self.head, text="", bg=PANEL, fg=MUTE,
                                font=self.fonts.get("tiny"), anchor="e")
        self.summary.pack(side="right", padx=(0, 8))

        self.body = tk.Frame(self, bg=PANEL)
        for w in (self.head, self.arrow, self.title, self.summary):
            w.bind("<Button-1>", lambda _e: self.toggle())
            w.bind("<Enter>", lambda _e: self._hover(True))
            w.bind("<Leave>", lambda _e: self._hover(False))

    # -- 交互 ------------------------------------------------------------ #
    def _hover(self, on: bool):
        if not self.open:
            self.title.configure(fg=(TEXT if on else TEXT))
            self.arrow.configure(fg=(TEXT if on else MUTE))

    def toggle(self):
        self.set(not self.open)

    def set(self, open_: bool, notify: bool = True):
        open_ = bool(open_)
        if open_ == self.open:
            return
        self.open = open_
        if open_:
            self.body.pack(fill="x", padx=(22, 2), pady=(2, 4))
            self.arrow.configure(text="▾", fg=ACCENT)
        else:
            self.body.pack_forget()
            self.arrow.configure(text="▸", fg=MUTE)
            self.title.configure(fg=TEXT)
        if notify and self.on_toggle:
            self.on_toggle()

    def set_summary(self, text: str, color: str = MUTE):
        self.summary.configure(text=text, fg=color)


# --------------------------------------------------------------------------- #
# 主界面
# --------------------------------------------------------------------------- #
class Md2docsApp:

    def __init__(self, root: tk.Tk, initial_files=None):
        self.root = root
        self.files: list[dict] = []          # {"path", "name"}
        self.formats: set[str] = {"docx"}
        self.caps: dict = {}
        self.running = False
        self.queue: queue.Queue = queue.Queue()
        self._toast = None
        self._pump_id = None
        self._alive = True
        self._res_dirs: dict[str, str] = {}
        self._fmt_cards: dict[str, dict] = {}
        self._last_out_dirs: list[str] = []
        self._res_rows = 5              # 结果列表默认行数（可按空间压缩）
        self._file_rows = 3             # 文件列表默认行数（可按空间压缩）
        self._placed = False            # 是否已完成首次窗口定位
        self._results: list = []        # 结果原始对象，语言切换时据此重画结果表
        self._prog_kind = ""            # 进度文字的语义状态，便于重译
        self._prog_args: tuple = ()

        self._init_fonts()
        self._init_vars()
        self._apply_ttk_style()
        self._build()
        self._bind_keys()

        if initial_files:
            self.add_paths(initial_files)

        self.refresh_outdir()
        self._autosize()
        # 窗口落地后按实测边框再精算一次，避免页脚被窗口边缘截掉
        self.root.after(180, self._autosize)
        self._pump_id = self.root.after(60, self._pump)
        self.root.after(120, self._detect_caps_async)

    # ------------------------------------------------------------------ #
    # 初始化
    # ------------------------------------------------------------------ #
    def _init_fonts(self):
        fams = set(tkfont.families(self.root))
        ui = "Microsoft YaHei UI" if "Microsoft YaHei UI" in fams else (
            "Microsoft YaHei" if "Microsoft YaHei" in fams else "Segoe UI")
        self.fonts = {
            "base": (ui, 10),
            "bold": (ui, 10, "bold"),
            "small": (ui, 9),
            "tiny": (ui, 8),
            "title": (ui, 13, "bold"),
            "sub": (ui, 9),
            "logo": (ui, 15, "bold"),
            "btn": (ui, 10),
            "mono": ("Consolas", 9),
        }

    def _init_vars(self):
        self.var_out_mode = tk.StringVar(value="same")
        self.var_out_dir = tk.StringVar(value="")
        self.var_txt_mode = tk.StringVar(value="plain")
        self.var_txt_enc = tk.StringVar(value="utf-8")
        self.var_native = tk.IntVar(value=0)
        self.var_progress = tk.DoubleVar(value=0.0)
        self.var_progress_text = tk.StringVar(value="")
        self.var_caps = tk.StringVar(value=i18n.t("caps.detecting"))
        # 语言档位沿用 app 已解析的选择（命令行 --lang 会体现在这里）
        self.var_lang = tk.StringVar(value=i18n.current_choice())

    def _apply_ttk_style(self):
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass

        st.configure("Md.Treeview", background=PANEL2, fieldbackground=PANEL2,
                     foreground=TEXT, bordercolor=LINE, borderwidth=0,
                     lightcolor=PANEL2, darkcolor=PANEL2, rowheight=24,
                     font=self.fonts["small"])
        st.configure("Md.Treeview.Heading", background=PANEL2, foreground=DIM,
                     relief="flat", borderwidth=0, font=self.fonts["tiny"])
        st.map("Md.Treeview",
               background=[("selected", CARD_ON)],
               foreground=[("selected", TEXT)])
        st.map("Md.Treeview.Heading", background=[("active", LINE)])

        st.configure("Md.Horizontal.TProgressbar", troughcolor=PANEL2,
                     background=ACCENT, bordercolor=PANEL2, lightcolor=ACCENT,
                     darkcolor=ACCENT, thickness=8)
        st.configure("Md.Vertical.TScrollbar", background=LINE,
                     troughcolor=PANEL, bordercolor=PANEL, arrowcolor=MUTE,
                     lightcolor=LINE, darkcolor=LINE, width=11)
        st.configure("Md.Horizontal.TScrollbar", background=LINE,
                     troughcolor=PANEL, bordercolor=PANEL, arrowcolor=MUTE,
                     lightcolor=LINE, darkcolor=LINE)
        st.configure("Md.TCombobox", fieldbackground=PANEL2,
                     background=PANEL2, foreground=TEXT, arrowcolor=DIM,
                     bordercolor=LINE, lightcolor=PANEL2, darkcolor=PANEL2,
                     selectbackground=PANEL2, selectforeground=TEXT,
                     padding=3)
        st.map("Md.TCombobox",
               fieldbackground=[("readonly", PANEL2)],
               foreground=[("readonly", TEXT)],
               selectbackground=[("readonly", PANEL2)],
               selectforeground=[("readonly", TEXT)])

        self.root.option_add("*TCombobox*Listbox.background", PANEL2)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        self.root.option_add("*TCombobox*Listbox.font", self.fonts["small"])

    # ------------------------------------------------------------------ #
    # 构件工厂
    # ------------------------------------------------------------------ #
    def _btn(self, parent, key, cmd, kind="soft", font=None, surround=PANEL,
             padx=13, pady=5):
        """建一个圆角按钮。文案走词条键，语言切换时自动重译。"""
        b = RoundButton(parent, text=i18n.t(key), command=cmd, kind=kind,
                        font=font or self.fonts["small"], surround=surround,
                        padx=padx, pady=pady)
        return mark_text(b, key)

    def _panel(self, parent):
        f = tk.Frame(parent, bg=PANEL, highlightbackground=LINE,
                     highlightthickness=1, bd=0)
        f.pack(fill="x", pady=(0, 8))
        return f

    def _panel_head(self, panel, step: str, key: str):
        head = tk.Frame(panel, bg=PANEL)
        head.pack(fill="x", padx=16, pady=(7, 5))
        tk.Label(head, text=step, bg=ACCENT, fg="#ffffff",
                 font=self.fonts["tiny"], width=2).pack(side="left", padx=(0, 8))
        mark_text(tk.Label(head, bg=PANEL, fg=TEXT,
                           font=self.fonts["bold"]), key).pack(side="left")
        right = tk.Frame(head, bg=PANEL)
        right.pack(side="right")
        return head, right

    def _radio(self, parent, key, value, var):
        return mark_text(
            tk.Radiobutton(parent, value=value, variable=var,
                           bg=PANEL, fg=TEXT, selectcolor=PANEL2,
                           activebackground=PANEL, activeforeground=TEXT,
                           font=self.fonts["small"], relief="flat", bd=0,
                           highlightthickness=0, cursor="hand2",
                           command=self._on_option_change), key)

    # ------------------------------------------------------------------ #
    # 界面搭建
    # ------------------------------------------------------------------ #
    def _build(self):
        self.root.title(window_title())
        self.root.configure(bg=BG)
        self.root.minsize(880, 660)
        ico = resource_path(os.path.join("build", "app.ico"))
        if os.path.isfile(ico):
            try:
                self.root.iconbitmap(default=ico)
            except Exception:
                pass

        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill="both", expand=True)
        self.main = tk.Frame(outer, bg=BG, padx=20, pady=0)
        self.main.pack(fill="x")

        self._build_header()
        self._build_files()
        self._build_output()
        self._build_run()
        self._build_footer()

        self._enable_drop()

    # -- 顶部 ----------------------------------------------------------- #
    def _build_header(self):
        bar = tk.Frame(self.main, bg=BG)
        bar.pack(fill="x", pady=(8, 6))

        logo = tk.Canvas(bar, width=38, height=38, bg=BG, highlightthickness=0)
        logo.pack(side="left", padx=(0, 12))
        logo.create_rectangle(0, 0, 38, 38, fill=ACCENT, outline=ACCENT)
        logo.create_text(19, 20, text=i18n.t("app.logo_letter"), fill="#ffffff",
                         font=self.fonts["logo"])

        txt = tk.Frame(bar, bg=BG)
        txt.pack(side="left")
        mark_text(tk.Label(txt, bg=BG, fg=TEXT, font=self.fonts["title"]),
                  "app.name").pack(anchor="w")
        mark_text(tk.Label(txt, bg=BG, fg=MUTE, font=self.fonts["sub"]),
                  "app.subtitle").pack(anchor="w")

        right = tk.Frame(bar, bg=BG)
        right.pack(side="right")
        self.lbl_caps = tk.Label(right, textvariable=self.var_caps, bg=PANEL2,
                                 fg=DIM, font=self.fonts["tiny"], padx=10, pady=4)
        self.lbl_caps.pack(side="right")

        # 语言切换入口：紧邻 Office 状态徽标的左侧
        langbox = tk.Frame(right, bg=BG)
        langbox.pack(side="right", padx=(0, 12))
        mark_text(tk.Label(langbox, bg=BG, fg=MUTE, font=self.fonts["tiny"]),
                  "lang.label").pack(side="left", padx=(0, 5))
        self.cmb_lang = ttk.Combobox(langbox, state="readonly", width=9,
                                     style="Md.TCombobox",
                                     font=self.fonts["tiny"])
        self.cmb_lang.pack(side="left")
        self.cmb_lang.bind("<<ComboboxSelected>>", self._on_lang_pick)
        self._sync_lang_combo()

    # -- 第 1 步：文件 --------------------------------------------------- #
    def _build_files(self):
        panel = self._panel(self.main)
        _head, right = self._panel_head(panel, "1", "step.files")
        self._btn(right, "file.browse", self.pick_files, "soft").pack(side="right")
        self._btn(right, "file.clear", self.clear_files, "ghost").pack(
            side="right", padx=(0, 8))

        drop = tk.Frame(panel, bg=PANEL2, highlightbackground=LINE,
                        highlightthickness=1, cursor="hand2")
        drop.pack(fill="x", padx=16, pady=(0, 8))
        drop.bind("<Button-1>", lambda _e: self.pick_files())
        inner = tk.Frame(drop, bg=PANEL2)
        inner.pack(pady=7)
        t1 = mark_text(tk.Label(inner, bg=PANEL2, fg=TEXT,
                                font=self.fonts["small"]), "file.drop_hint")
        t1.pack()
        t2 = mark_text(tk.Label(inner, bg=PANEL2, fg=MUTE,
                                font=self.fonts["tiny"]), "file.drop_sub")
        t2.pack(pady=(2, 0))
        for w in (inner, t1, t2):
            w.bind("<Button-1>", lambda _e: self.pick_files())

        wrap = tk.Frame(panel, bg=PANEL)
        wrap.pack(fill="x", padx=16, pady=(0, 12))
        self.file_tree = ttk.Treeview(wrap, columns=("name", "src"),
                                      show="headings", height=3,
                                      style="Md.Treeview", selectmode="extended")
        self.file_tree.heading("name", text=i18n.t("file.col_name"), anchor="w")
        self.file_tree.heading("src", text=i18n.t("file.col_path"), anchor="w")
        self.file_tree.column("name", width=200, anchor="w", stretch=False)
        self.file_tree.column("src", width=380, anchor="w", stretch=True)
        sb = ttk.Scrollbar(wrap, orient="vertical", style="Md.Vertical.TScrollbar",
                           command=self.file_tree.yview)
        self.file_tree.configure(yscrollcommand=sb.set)
        self.file_tree.pack(side="left", fill="x", expand=True)
        sb.pack(side="right", fill="y")
        self.file_tree.bind("<Delete>", lambda _e: self.remove_selected())
        self.file_tree.bind("<Double-1>", lambda _e: self.open_selected())

        self.lbl_file_empty = mark_text(
            tk.Label(panel, bg=PANEL, fg=MUTE, font=self.fonts["tiny"]),
            "file.empty")
        self.lbl_file_empty.pack(anchor="w", padx=16, pady=(0, 12))
        if self.files:
            self.lbl_file_empty.pack_forget()

    # -- 第 2 步：输出设置 ----------------------------------------------- #
    def _build_output(self):
        panel = self._panel(self.main)
        self._panel_head(panel, "2", "step.output")

        row = tk.Frame(panel, bg=PANEL)
        row.pack(fill="x", padx=16)
        for i, fid in enumerate(FMT_ORDER):
            row.columnconfigure(i, weight=1, uniform="fmt")
            self._fmt_cards[fid] = self._make_fmt_card(row, fid, i)

        body = tk.Frame(panel, bg=PANEL)
        body.pack(fill="x", padx=16, pady=(4, 7))

        # 输出位置
        self.fold_out = Fold(body, "out.fold", on_toggle=self._autosize,
                             fonts=self.fonts)
        self.fold_out.pack(fill="x")
        r1 = tk.Frame(self.fold_out.body, bg=PANEL)
        r1.pack(fill="x")
        self._radio(r1, "out.same", "same", self.var_out_mode).pack(side="left")
        self._radio(r1, "out.custom", "custom",
                    self.var_out_mode).pack(side="left", padx=(14, 10))
        self.ent_out = tk.Entry(r1, textvariable=self.var_out_dir, bg=PANEL2,
                                fg=TEXT, insertbackground=TEXT, relief="flat",
                                highlightthickness=1, highlightbackground=LINE,
                                highlightcolor=ACCENT, font=self.fonts["small"],
                                disabledbackground=PANEL, disabledforeground=MUTE)
        self.ent_out.pack(side="left", fill="x", expand=True, ipady=3)
        self.btn_pick_dir = self._btn(r1, "out.browse", self.pick_out_dir, "soft")
        self.btn_pick_dir.pack(side="left", padx=(8, 0))

        # TXT 选项
        self.fold_txt = Fold(body, "txt.fold", on_toggle=self._autosize,
                             fonts=self.fonts)
        self.fold_txt.pack(fill="x")
        t1 = tk.Frame(self.fold_txt.body, bg=PANEL)
        t1.pack(fill="x")
        self._radio(t1, "txt.plain", "plain",
                    self.var_txt_mode).pack(side="left")
        self._radio(t1, "txt.raw", "raw",
                    self.var_txt_mode).pack(side="left", padx=(14, 16))
        mark_text(tk.Label(t1, bg=PANEL, fg=DIM, font=self.fonts["small"]),
                  "txt.encoding").pack(side="left", padx=(0, 6))
        self.cmb_enc = ttk.Combobox(t1, textvariable=self.var_txt_enc,
                                    values=convert.ENCODINGS, state="readonly",
                                    width=20, style="Md.TCombobox",
                                    font=self.fonts["small"])
        self.cmb_enc.pack(side="left")

        # 高质量模式
        self.fold_native = Fold(body, "native.fold",
                                on_toggle=self._autosize, fonts=self.fonts)
        self.fold_native.pack(fill="x")
        self.sw_native = RoundButton(
            self.fold_native.right, text=i18n.t("native.enable"),
            command=self._toggle_native, kind="soft", font=self.fonts["tiny"],
            surround=PANEL, radius=6, padx=9, pady=2)
        mark_text(self.sw_native, "native.enable")
        self.sw_native.pack()
        self.lbl_native = tk.Label(self.fold_native.body, text="", bg=PANEL,
                                   fg=DIM, font=self.fonts["tiny"],
                                   justify="left", wraplength=880)
        self.lbl_native.pack(anchor="w")

        self._sync_txt_fold()
        self._sync_outdir_widgets()

    def _make_fmt_card(self, parent, fid: str, col: int) -> dict:
        card = tk.Frame(parent, bg=PANEL2, highlightbackground=LINE,
                        highlightthickness=1, cursor="hand2")
        card.grid(row=0, column=col, sticky="nsew",
                  padx=(0 if col == 0 else 6, 0))
        inner = tk.Frame(card, bg=PANEL2)
        inner.pack(fill="x", padx=11, pady=5)
        tag = tk.Label(inner, text=FMT_TAG[fid], bg=PANEL2, fg=ACCENT,
                       font=self.fonts["bold"])
        tag.pack(anchor="w")
        desc = tk.Label(inner, text=fmt_desc(fid), bg=PANEL2, fg=MUTE,
                        font=self.fonts["tiny"])
        desc.pack(anchor="w")

        widgets = [card, inner, tag, desc]
        for w in widgets:
            w.bind("<Button-1>", lambda _e, f=fid: self.toggle_format(f))
        self._paint_fmt_card(fid, widgets)
        # desc 不挂 _tr_key（键名随格式变化），由 retranslate() 单独重设
        return {"widgets": widgets, "tag": tag, "desc": desc}

    def _paint_fmt_card(self, fid: str, widgets=None):
        widgets = widgets or self._fmt_cards[fid]["widgets"]
        on = fid in self.formats
        bg = CARD_ON if on else PANEL2
        for w in widgets:
            w.configure(bg=bg)
        widgets[0].configure(highlightbackground=ACCENT if on else LINE)
        widgets[2].configure(fg=ACCENT_HI if on else MUTE)

    # -- 第 3 步：转换 --------------------------------------------------- #
    def _build_run(self):
        panel = self._panel(self.main)
        _head, _right = self._panel_head(panel, "3", "step.run")

        bar = tk.Frame(panel, bg=PANEL)
        bar.pack(fill="x", padx=16)
        # 整组控件水平居中：group 只占自身宽度，由 bar 把它居中摆放
        group = tk.Frame(bar, bg=PANEL)
        group.pack()

        self.btn_run = self._btn(group, "run.button", self.start_convert,
                                 "primary", font=self.fonts["base"],
                                 padx=22, pady=6)
        self.btn_run.pack(side="left")
        self.btn_open_out = self._btn(group, "run.open_out", self.open_out_dirs,
                                      "soft")
        self.btn_open_out.pack(side="left", padx=(10, 0))
        self.btn_open_out.configure(state="disabled")

        self.prog = ttk.Progressbar(group, variable=self.var_progress,
                                    maximum=1.0,
                                    style="Md.Horizontal.TProgressbar",
                                    length=180)
        self.prog.pack(side="left", padx=(16, 10))
        # 固定宽度：进度文字长短变化时整组不会左右跳动
        self.lbl_prog = tk.Label(group, textvariable=self.var_progress_text,
                                 bg=PANEL, fg=DIM, font=self.fonts["tiny"],
                                 width=16, anchor="w")
        self.lbl_prog.pack(side="left")

        wrap = tk.Frame(panel, bg=PANEL)
        wrap.pack(fill="x", padx=16, pady=(6, 9))
        self.res_tree = ttk.Treeview(wrap, columns=("state", "file", "fmt", "info"),
                                     show="headings", height=5, style="Md.Treeview",
                                     selectmode="browse")
        for cid, key, w, anchor, stretch in (
                ("state", "res.col_state", 62, "center", False),
                ("file", "res.col_file", 178, "w", False),
                ("fmt", "res.col_fmt", 62, "center", False),
                ("info", "res.col_info", 390, "w", True)):
            self.res_tree.heading(cid, text=i18n.t(key), anchor=anchor)
            self.res_tree.column(cid, width=w, anchor=anchor, stretch=stretch)
        sb = ttk.Scrollbar(wrap, orient="vertical",
                           style="Md.Vertical.TScrollbar",
                           command=self.res_tree.yview)
        self.res_tree.configure(yscrollcommand=sb.set)
        self.res_tree.pack(side="left", fill="x", expand=True)
        sb.pack(side="right", fill="y")
        self.res_tree.tag_configure("ok", foreground=OK)
        self.res_tree.tag_configure("bad", foreground=ERR)
        self.res_tree.tag_configure("warn", foreground=WARN)
        self.res_tree.bind("<Double-1>", lambda _e: self.open_result_folder())

    # -- 页脚 ------------------------------------------------------------ #
    def _build_footer(self):
        foot = tk.Frame(self.main, bg=BG)
        foot.pack(fill="x", pady=(2, 6))
        tk.Frame(foot, bg=LINE, height=1).pack(fill="x", pady=(0, 10))
        mark_text(tk.Label(foot, bg=BG, fg=MUTE, font=self.fonts["tiny"]),
                  "app.footer").pack()

    def _bind_keys(self):
        self.root.bind("<Control-o>", lambda _e: self.pick_files())
        self.root.bind("<F5>", lambda _e: self.start_convert())
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _enable_drop(self):
        ok = enable_file_drop(self.root, self.on_drop_files)
        self._dnd_ok = ok

    # ------------------------------------------------------------------ #
    # 界面语言
    # ------------------------------------------------------------------ #
    def _sync_lang_combo(self):
        """把语言下拉框的档位与显示文字刷新到当前语言。"""
        try:
            self.cmb_lang.configure(values=[i18n.choice_label(c)
                                            for c in i18n.LANG_CHOICES])
            self.cmb_lang.current(i18n.LANG_CHOICES.index(self.var_lang.get()))
        except Exception:
            pass

    def _on_lang_pick(self, _event=None):
        try:
            idx = self.cmb_lang.current()
        except Exception:
            return
        if 0 <= idx < len(i18n.LANG_CHOICES):
            self.set_language(i18n.LANG_CHOICES[idx])

    def set_language(self, choice: str, persist: bool = True):
        """切换界面语言：就地重译，不重建窗口。

        ``persist=False`` 用于自检——不能因为跑一次自检就改掉主人的真实配置。
        """
        choice = i18n.normalize(choice)
        self.var_lang.set(choice)
        if persist:
            settings.put("lang", choice)
        i18n.setup(choice)
        self.retranslate()

    def retranslate(self):
        """按当前语言把所有文案就地重设一遍。

        静态文案靠构建时挂上的 ``_tr_key`` 顺着控件树重设；动态文案（折叠区
        摘要、能力徽标、结果行、进度文字）重新推导一遍——文件列表与转换结果
        全部保留，不会因为切语言而丢失。
        """
        try:
            self.root.title(window_title())
        except Exception:
            pass
        for w in walk_widgets(self.root):
            key = getattr(w, "_tr_key", None)
            if not key:
                continue
            try:
                w.configure(text=i18n.t(key))
            except Exception:
                pass
        try:
            self.file_tree.heading("name", text=i18n.t("file.col_name"))
            self.file_tree.heading("src", text=i18n.t("file.col_path"))
            for cid, key in (("state", "res.col_state"),
                             ("file", "res.col_file"),
                             ("fmt", "res.col_fmt"),
                             ("info", "res.col_info")):
                self.res_tree.heading(cid, text=i18n.t(key))
        except Exception:
            pass
        for fid in FMT_ORDER:
            card = self._fmt_cards.get(fid)
            if card:
                try:
                    card["desc"].configure(text=fmt_desc(fid))
                except Exception:
                    pass
        self._sync_lang_combo()
        self._sync_txt_fold()
        self._sync_outdir_widgets()
        self.refresh_outdir()
        if self.caps:
            self._apply_caps(self.caps)
        else:
            try:
                self.var_caps.set(i18n.t("caps.detecting"))
            except Exception:
                pass
        self._render_results()
        self._apply_progress_text()
        # 转换中「开始转换」显示的是进度文案，别被上面的遍历覆盖回默认值
        if self.running:
            try:
                self.btn_run.configure(text=i18n.t("run.running"))
            except Exception:
                pass
        self._autosize()

    # ------------------------------------------------------------------ #
    # 自适应高度（保证单页无滚动）
    # ------------------------------------------------------------------ #
    def _work_area(self) -> tuple[int, int]:
        """可用桌面区域（物理像素，已排除任务栏）。"""
        try:
            import ctypes
            from ctypes import wintypes
            r = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(
                    0x0030, 0, ctypes.byref(r), 0):           # SPI_GETWORKAREA
                return r.right - r.left, r.bottom - r.top
        except Exception:
            pass
        return self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def _chrome_height(self) -> int:
        """标题栏 + 上下边框占用的高度：优先实测，失败再退回系统度量。"""
        try:
            import ctypes
            from ctypes import wintypes
            u = ctypes.windll.user32
            h = u.GetParent(int(self.root.winfo_id())) or int(self.root.winfo_id())
            if h:
                wr, cr = wintypes.RECT(), wintypes.RECT()
                u.GetWindowRect(h, ctypes.byref(wr))
                u.GetClientRect(h, ctypes.byref(cr))
                delta = (wr.bottom - wr.top) - (cr.bottom - cr.top)
                if delta > 0:
                    return int(delta)
        except Exception:
            pass
        try:
            import ctypes
            u = ctypes.windll.user32
            return int(u.GetSystemMetrics(4) + 2 * u.GetSystemMetrics(32))
        except Exception:
            return 56

    def _autosize(self):
        """把内容精确放进可用桌面：列表按剩余空间伸缩，整页永不滚动。

        折叠区展开后内容变高，此处先压缩结果表、再压缩文件表，
        保证所有控件（含两张表自身的滚动条）始终完整可见——
        窗口本身不出现滚动条，也不会被任务栏遮住。
        """
        try:
            self.root.update_idletasks()
            work_w, work_h = self._work_area()
            avail = max(520, work_h - self._chrome_height())

            res_rows, file_rows = self._res_rows, self._file_rows
            self._apply_list_rows(res_rows, file_rows)
            self.root.update_idletasks()
            while (self.main.winfo_reqheight() > avail
                   and (res_rows > 2 or file_rows > 2)):
                if res_rows > 2:
                    res_rows -= 1
                else:
                    file_rows -= 1
                self._apply_list_rows(res_rows, file_rows)
                self.root.update_idletasks()

            need_h = self.main.winfo_reqheight()
            w = self._window_width(work_w)
            h = int(min(max(need_h, 600), avail))
            self.root.geometry("%dx%d" % (w, h))
            self._place_on_workarea(w, h)
        except Exception:
            pass

    def _window_width(self, work_w: int) -> int:
        """窗口宽度取固定设计值，绝不参与「内容宽度 → 窗口宽度」的反馈。

        ttk.Treeview 的可伸缩列（两张表的最后一列）会随控件变宽而变宽，
        而 Treeview 的请求宽度又按列宽计算——于是 winfo_reqwidth() 会随
        窗口变宽而变大。若用它反推窗口宽度，就形成自增循环：

            窗口变宽 → 拉伸列变宽 → reqwidth 变大 → 窗口再变宽 → …

        格式卡片每次点击都会走 _sync_txt_fold() → _autosize()，所以此前
        表现为「每点一下窗口就宽 44px」。固定宽度后该循环不存在。
        """
        return int(min(WIN_W, work_w))

    def _place_on_workarea(self, w: int, h: int):
        """把窗口完整摆进工作区。

        仅设置尺寸是不够的：Tk 的默认位置可能让窗口底部落到屏幕之外
        （任务栏或屏幕下沿会遮住结果表与页脚）。这里显式定位——
        首次居中于工作区，之后保持横向位置、只保证底部不越界。
        """
        try:
            import ctypes
            from ctypes import wintypes
            u = ctypes.windll.user32
            r = wintypes.RECT()
            if not u.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0):
                return
            wa_w, wa_h = r.right - r.left, r.bottom - r.top

            # 客户区 → 窗口外框
            ow, oh = w + 16, h + 56
            try:
                hwnd = (u.GetParent(int(self.root.winfo_id()))
                        or int(self.root.winfo_id()))
                wr, cr = wintypes.RECT(), wintypes.RECT()
                u.GetWindowRect(hwnd, ctypes.byref(wr))
                u.GetClientRect(hwnd, ctypes.byref(cr))
                ow = w + ((wr.right - wr.left) - (cr.right - cr.left))
                oh = h + ((wr.bottom - wr.top) - (cr.bottom - cr.top))
            except Exception:
                pass

            if self._placed:
                x = self.root.winfo_x()
                y = min(self.root.winfo_y(), r.bottom - oh)
            else:
                x = r.left + max(0, (wa_w - ow) // 2)
                y = r.top + max(0, (wa_h - oh) // 2)
                self._placed = True
            x = max(r.left, min(x, max(r.left, r.right - ow)))
            y = max(r.top, min(y, max(r.top, r.bottom - oh)))
            self.root.geometry("+%d+%d" % (x, y))
        except Exception:
            pass

    def _apply_list_rows(self, res_rows: int, file_rows: int):
        try:
            self.res_tree.configure(height=res_rows)
            self.file_tree.configure(height=file_rows)
        except Exception:
            pass

    def diag_info(self) -> dict:
        """收集 DPI 与几何度量，用于排查打包前后的尺寸差异。"""
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        root = self.root
        d = {}
        d["lang"] = "%s (%s)" % (i18n.current(), i18n.current_choice())
        d["tk"] = root.tk.call("info", "patchlevel")
        d["tk_scaling"] = root.tk.call("tk", "scaling")
        d["fpixels_1i"] = root.winfo_fpixels("1i")
        d["tk_screen"] = "%dx%d" % (root.winfo_screenwidth(),
                                    root.winfo_screenheight())
        d["win_screen"] = "%dx%d" % (u.GetSystemMetrics(0), u.GetSystemMetrics(1))
        d["work_area"] = self._work_area()
        d["chrome"] = self._chrome_height()
        d["avail"] = self._work_area()[1] - self._chrome_height()
        d["main_req"] = "%dx%d" % (self.main.winfo_reqwidth(),
                                   self.main.winfo_reqheight())
        d["geometry"] = root.geometry()
        d["res_rows/file_rows"] = "%s/%s" % (self.res_tree.cget("height"),
                                             self.file_tree.cget("height"))
        d["sections"] = ", ".join(
            "%s:%s" % (c.__class__.__name__, c.winfo_reqheight())
            for c in self.main.winfo_children())
        try:
            h = u.GetParent(int(root.winfo_id())) or int(root.winfo_id())
            wr, cr = wintypes.RECT(), wintypes.RECT()
            u.GetWindowRect(h, ctypes.byref(wr))
            u.GetClientRect(h, ctypes.byref(cr))
            d["window_rect"] = "%dx%d @ (%d,%d)" % (
                wr.right - wr.left, wr.bottom - wr.top, wr.left, wr.top)
            d["client_rect"] = "%dx%d" % (cr.right - cr.left, cr.bottom - cr.top)
            wa = wintypes.RECT()
            if u.SystemParametersInfoW(0x0030, 0, ctypes.byref(wa), 0):
                d["workarea_rect"] = "(%d,%d)-(%d,%d)" % (
                    wa.left, wa.top, wa.right, wa.bottom)
            foot = self.main.winfo_children()[-1]
            fb = foot.winfo_rooty() + foot.winfo_height()
            d["foot_abs_bottom"] = fb
            d["window_bottom_on_screen"] = wr.bottom
            d["foot_fully_visible"] = bool(
                wr.bottom <= wa.bottom and fb <= wa.bottom and wr.top >= wa.top)
        except Exception as exc:
            d["window_rect"] = "ERR %s" % exc
        return d

    # ------------------------------------------------------------------ #
    # 文件管理
    # ------------------------------------------------------------------ #
    def _iter_md(self, paths):
        out = []
        for p in paths:
            try:
                if os.path.isdir(p):
                    for name in sorted(os.listdir(p)):
                        if name.lower().endswith(MD_EXTS):
                            out.append(os.path.join(p, name))
                elif os.path.isfile(p):
                    out.append(p)
            except OSError:
                continue
        return out

    def add_paths(self, paths):
        cands = self._iter_md(paths)
        if not cands:
            self.toast(i18n.t("toast.no_files"), "err")
            return
        added, skipped = 0, 0
        known = {os.path.normcase(f["path"]) for f in self.files}
        for p in cands:
            ap = os.path.abspath(p)
            key = os.path.normcase(ap)
            if key in known:
                skipped += 1
                continue
            known.add(key)
            self.files.append({"path": ap, "name": os.path.basename(ap)})
            added += 1
        self.render_files()
        self.refresh_outdir()
        if added:
            self.toast(i18n.t("toast.added", n=added))
        elif skipped:
            self.toast(i18n.t("toast.duplicated"), "warn")

    def on_drop_files(self, paths):
        self.add_paths(paths)

    def pick_files(self):
        paths = filedialog.askopenfilenames(
            title=i18n.t("file.dialog_title"),
            filetypes=[(i18n.t("file.ft_md"), "*.md *.markdown *.mdown *.mkd"),
                       (i18n.t("file.ft_txt"), "*.txt"),
                       (i18n.t("file.ft_all"), "*.*")])
        if paths:
            self.add_paths(list(paths))

    def remove_selected(self):
        sel = list(self.file_tree.selection())
        if not sel:
            return
        idxs = sorted((int(i) for i in sel), reverse=True)
        for i in idxs:
            if 0 <= i < len(self.files):
                self.files.pop(i)
        self.render_files()
        self.refresh_outdir()

    def open_selected(self):
        sel = self.file_tree.selection()
        if not sel:
            return
        i = int(sel[0])
        if 0 <= i < len(self.files):
            ok, err = open_path(self.files[i]["path"])
            if not ok:
                self.toast(err, "err")

    def clear_files(self):
        self.files.clear()
        self.render_files()
        self.refresh_outdir()
        self.clear_results()

    def render_files(self):
        self.file_tree.delete(*self.file_tree.get_children())
        for i, f in enumerate(self.files):
            self.file_tree.insert("", "end", iid=str(i),
                                  values=(f["name"], f["path"]))
        if self.files:
            self.lbl_file_empty.pack_forget()
        else:
            self.lbl_file_empty.pack(anchor="w", padx=16, pady=(0, 12))

    def clear_results(self):
        self.res_tree.delete(*self.res_tree.get_children())
        self._results.clear()
        self._res_dirs.clear()
        self._last_out_dirs = []
        self.btn_open_out.configure(state="disabled")
        self.var_progress.set(0)
        self._set_progress("")

    # ------------------------------------------------------------------ #
    # 选项联动
    # ------------------------------------------------------------------ #
    def toggle_format(self, fid: str):
        if fid in self.formats:
            self.formats.discard(fid)
        else:
            self.formats.add(fid)
        self._paint_fmt_card(fid)
        self._sync_txt_fold()

    def _on_option_change(self):
        self._sync_outdir_widgets()
        self.refresh_outdir()

    def _sync_txt_fold(self):
        on = "txt" in self.formats
        self.fold_txt.set(on, notify=False)
        self.fold_txt.set_summary(i18n.t("sum.txt_on" if on else "sum.txt_off"),
                                  OK if on else MUTE)
        self._autosize()

    def _sync_outdir_widgets(self):
        custom = self.var_out_mode.get() == "custom"
        state = "normal" if custom else "disabled"
        self.ent_out.configure(state=state)
        self.btn_pick_dir.configure(state=state,
                                    fg=(TEXT if custom else MUTE))
        self.fold_out.set_summary(
            i18n.t("sum.out_custom" if custom else "sum.out_same"),
            TEXT if custom else MUTE)

    def refresh_outdir(self):
        mode = self.var_out_mode.get()
        if mode == "custom":
            self.ent_out.configure(state="normal")
            self.btn_pick_dir.configure(state="normal", fg=TEXT)
            val = self.var_out_dir.get()
            self.fold_out.set_summary(
                i18n.t("sum.out_custom_dir",
                       path=os.path.basename(val.rstrip("\\/"))) if val
                else i18n.t("sum.out_custom_empty"), TEXT if val else MUTE)
        else:
            dirs = {os.path.dirname(f["path"]) for f in self.files}
            if not dirs:
                txt, color = i18n.t("sum.out_same"), MUTE
            elif len(dirs) == 1:
                txt, color = i18n.t("sum.out_same_dir",
                                    path=next(iter(dirs))), TEXT
            else:
                txt, color = i18n.t("sum.out_same_many"), TEXT
            self.fold_out.set_summary(txt, color)

    def pick_out_dir(self):
        d = filedialog.askdirectory(title=i18n.t("out.dialog_title"))
        if d:
            self.var_out_dir.set(os.path.normpath(d))
            self.var_out_mode.set("custom")
            self._sync_outdir_widgets()
            self.refresh_outdir()

    def _toggle_native(self):
        """「启用」开关：圆角按钮形式，点击翻转原生模式。"""
        if not self._native_enabled():
            return
        self.var_native.set(0 if self.var_native.get() else 1)
        self._on_native_switch()

    def _on_native_switch(self):
        on = bool(self.var_native.get()) and self._native_enabled()
        self.sw_native.configure(fill=CARD_ON if on else PANEL2,
                                 fg=OK if on else DIM,
                                 hover=CARD_ON_HI if on else LINE)
        self.fold_native.set_summary(
            i18n.t("sum.native_on" if on else "sum.native_off"),
            OK if on else MUTE)
        self._autosize()

    def _native_enabled(self):
        return bool(self.caps.get("word") or self.caps.get("wps"))

    # ------------------------------------------------------------------ #
    # 能力检测（后台执行，避免拖慢启动）
    # ------------------------------------------------------------------ #
    def _detect_caps_async(self):
        def worker():
            try:
                caps = convert.capabilities()
            except Exception:
                caps = {"word": False, "wps": False}
            self.queue.put(("caps", caps))
        threading.Thread(target=worker, daemon=True).start()

    def _apply_caps(self, caps: dict):
        self.caps = caps or {}
        names = []
        if self.caps.get("word"):
            names.append("Word")
        if self.caps.get("wps"):
            names.append("WPS")
        if names:
            self.var_caps.set(i18n.t("caps.ready", names=" / ".join(names)))
            self.lbl_caps.configure(fg=OK, bg="#143026")
            hint = i18n.t("caps.hint_ready")
        else:
            self.var_caps.set(i18n.t("caps.none"))
            self.lbl_caps.configure(fg=DIM, bg=PANEL2)
            hint = i18n.t("caps.hint_none")
        self.lbl_native.configure(text=hint)
        enabled = self._native_enabled()
        self.sw_native.configure(state="normal" if enabled else "disabled")
        if not enabled:
            self.var_native.set(0)
        self._on_native_switch()

    # ------------------------------------------------------------------ #
    # 转换
    # ------------------------------------------------------------------ #
    def start_convert(self):
        if self.running:
            return
        if not self.files:
            self.toast(i18n.t("toast.need_files"), "err")
            return
        if not self.formats:
            self.toast(i18n.t("toast.need_formats"), "err")
            return

        mode = self.var_out_mode.get()
        out_dir = ""
        if mode == "custom":
            out_dir = self.var_out_dir.get().strip()
            if not out_dir:
                self.toast(i18n.t("toast.need_outdir"), "err")
                return
            try:
                os.makedirs(out_dir, exist_ok=True)
            except OSError as exc:
                self.toast(i18n.t("toast.outdir_bad", err=exc), "err")
                return

        self.running = True
        self.btn_run.configure(state="disabled", bg=MUTE,
                               text=i18n.t("run.running"))
        self.clear_results()
        self.var_progress.set(0.02)
        self._set_progress("running")

        fmts = [f for f in FMT_ORDER if f in self.formats]
        payload = {
            "files": [dict(f) for f in self.files],
            "formats": fmts,
            "out_dir": out_dir,
            "native": bool(self.var_native.get()) and self._native_enabled(),
            "txt_mode": self.var_txt_mode.get(),
            "txt_encoding": self.var_txt_enc.get(),
        }
        threading.Thread(target=self._worker, args=(payload,), daemon=True).start()

    def _worker(self, job: dict):
        total = max(1, len(job["files"]))
        done = 0
        for item in job["files"]:
            path = item["path"]
            if not os.path.isfile(path):
                self.queue.put(("result", convert.Result(
                    source=path, name=item["name"], fmt="", ok=False,
                    message=i18n.t("res.file_missing"))))
                done += 1
                self.queue.put(("progress", (done, total)))
                continue
            try:
                rs = convert.convert_file(
                    path, job["formats"], job["out_dir"] or None,
                    native=job["native"], txt_mode=job["txt_mode"],
                    txt_encoding=job["txt_encoding"], overwrite=True)
                for r in rs:
                    self.queue.put(("result", r))
            except Exception as exc:
                self.queue.put(("result", convert.Result(
                    source=path, name=item["name"], fmt="", ok=False,
                    message="%s: %s" % (type(exc).__name__, exc))))
            done += 1
            self.queue.put(("progress", (done, total)))
        self.queue.put(("done", None))

    def _pump(self):
        """在主线程消费后台消息，保证 Tk 调用线程安全。"""
        self._pump_id = None
        if not self._alive:
            return
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "progress":
                    done, total = payload
                    self.var_progress.set(done / float(total))
                    self._set_progress("progress", done, total)
                elif kind == "result":
                    self.add_result(payload)
                elif kind == "caps":
                    self._apply_caps(payload)
                elif kind == "done":
                    self.finish_convert()
        except queue.Empty:
            pass
        except Exception:
            pass
        finally:
            if self._alive:
                try:
                    self._pump_id = self.root.after(80, self._pump)
                except Exception:
                    self._alive = False

    def shutdown(self):
        """停止内部定时器并销毁窗口（退出前调用，避免悬挂的 after 回调）。"""
        self._alive = False
        if self._pump_id is not None:
            try:
                self.root.after_cancel(self._pump_id)
            except Exception:
                pass
            self._pump_id = None
        disable_file_drop(self.root)

    def _set_progress(self, kind: str, *args):
        """记下进度文字的语义状态，语言切换时据此重译。"""
        self._prog_kind, self._prog_args = kind, args
        self._apply_progress_text()

    def _apply_progress_text(self):
        kind, args = self._prog_kind, self._prog_args
        if kind == "running":
            text = i18n.t("prog.running")
        elif kind == "progress":
            text = i18n.t("prog.progress", done=args[0], total=args[1])
        elif kind == "finished":
            text = i18n.t("prog.finished", ok=args[0], total=args[1])
        else:
            text = ""
        try:
            self.var_progress_text.set(text)
        except Exception:
            pass

    def add_result(self, r: convert.Result):
        self._results.append(r)
        self._insert_result_row(len(self._results) - 1)

    def _insert_result_row(self, idx: int):
        """按 Result 对象画一行；iid 用它在 _results 中的下标，便于反查。"""
        r = self._results[idx]
        if r.ok:
            state, tag = i18n.t("res.state_ok"), "ok"
            info = "%s · %s · %s" % (r.target, fmt_size(r.size), r.engine)
            if r.warnings:
                tag = "warn"
                info += "  ⚠ " + i18n.t("list_sep").join(r.warnings)
            self._res_dirs[str(r.target)] = os.path.dirname(r.target)
        else:
            state, tag = i18n.t("res.state_fail"), "bad"
            info = r.message or i18n.t("res.failed")
        fmt = ("." + r.fmt) if r.fmt else "-"
        self.res_tree.insert("", "end", iid=str(idx), tags=(tag,),
                             values=(state, r.name, fmt, info))

    def _render_results(self):
        """整表重画：语言切换后「状态」列与引擎名都需要重译。"""
        try:
            self.res_tree.delete(*self.res_tree.get_children())
            self._res_dirs.clear()
            for i in range(len(self._results)):
                self._insert_result_row(i)
        except Exception:
            pass

    def finish_convert(self):
        self.running = False
        self.btn_run.configure(state="normal", bg=ACCENT,
                               text=i18n.t("run.button"))
        rows = self.res_tree.get_children()
        n_total = len(rows)
        n_ok = 0
        for i in rows:
            tags = self.res_tree.item(i, "tags") or ()
            if tags and tags[0] in ("ok", "warn"):
                n_ok += 1
        self.var_progress.set(1.0)
        self._set_progress("finished", n_ok, n_total)
        dirs = sorted({d for d in self._res_dirs.values() if d})
        self._last_out_dirs = dirs
        self.btn_open_out.configure(state="normal" if dirs else "disabled",
                                    fg=(TEXT if dirs else MUTE))
        self.toast(i18n.t("toast.finished", n=n_ok), "ok" if n_ok else "err")

    def open_out_dirs(self):
        if not self._last_out_dirs:
            return
        ok, err = open_path(self._last_out_dirs[0])
        if not ok:
            self.toast(err, "err")

    def open_result_folder(self):
        """双击结果行打开所在文件夹。

        原先靠"状态列文字是否以『成功』结尾"判断成败——国际化之后必然失效，
        现改为按 iid 反查 Result 对象，与语言无关。
        """
        sel = self.res_tree.selection()
        if not sel:
            return
        try:
            r = self._results[int(sel[0])]
        except Exception:
            return
        if not r.ok or not r.target:
            return
        ok, err = open_path(os.path.dirname(r.target))
        if not ok:
            self.toast(err, "err")

    # ------------------------------------------------------------------ #
    # 提示条
    # ------------------------------------------------------------------ #
    def toast(self, msg: str, kind: str = ""):
        try:
            if self._toast is not None and self._toast.winfo_exists():
                self._toast.destroy()
        except Exception:
            pass
        color = {"ok": OK, "err": ERR, "warn": WARN}.get(kind, ACCENT)
        try:
            t = tk.Toplevel(self.root)
            t.overrideredirect(True)
            t.configure(bg=color)
            tk.Label(t, text=msg, bg=PANEL2, fg=TEXT, font=self.fonts["small"],
                     padx=16, pady=9, justify="left",
                     wraplength=520).pack(padx=1, pady=1)
            t.update_idletasks()
            rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
            rw, rh = self.root.winfo_width(), self.root.winfo_height()
            tw, th = t.winfo_reqwidth(), t.winfo_reqheight()
            x = max(0, rx + (rw - tw) // 2)
            y = max(0, ry + rh - th - 26)
            t.geometry("+%d+%d" % (x, y))
            try:
                t.attributes("-topmost", True)
            except Exception:
                pass
            self._toast = t

            def _close():
                try:
                    if t.winfo_exists():
                        t.destroy()
                except Exception:
                    pass
            t.after(2600, _close)
        except Exception:
            pass

    def on_close(self):
        try:
            if self._toast is not None and self._toast.winfo_exists():
                self._toast.destroy()
        except Exception:
            pass
        self.shutdown()
        try:
            self.root.destroy()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
def selftest(md_path: str | None = None, out_dir: str | None = None) -> int:
    """内部自检：构建完整界面并（可选）跑一次真实转换，用于自动化验证。"""
    enable_hi_dpi()
    root = tk.Tk()
    root.withdraw()
    app = Md2docsApp(root)
    problems: list[str] = []

    def need(cond, label):
        if not cond:
            problems.append(label)

    need(app.file_tree.winfo_exists(), "文件列表控件缺失")
    need(app.res_tree.winfo_exists(), "结果列表控件缺失")
    need(len(app._fmt_cards) == 4, "格式卡片数量不是 4")
    need(app.var_out_mode.get() == "same", "默认输出位置应为「与源文件相同」")
    need(app.cmb_enc.get() == "utf-8", "默认编码应为 utf-8")
    print("[selftest] 控件就绪；拖放可用 =", app._dnd_ok)
    print("[selftest] 当前语言 = %s（档位 %s）"
          % (i18n.current(), i18n.current_choice()))

    # 语言切换：往返一轮，确认文案真的跟着变（persist=False 不写用户配置）
    orig_choice = i18n.current_choice()
    try:
        app.set_language("en", persist=False)
        need(i18n.current() == "en", "切换到英文失败")
        need(app.btn_run.cget("text") == i18n.t("run.button"),
             "英文下主按钮文案未更新")
        need(app.root.title() == i18n.t("app.window_title"),
             "窗口标题未随语言更新")
        app.set_language("zh", persist=False)
        need(i18n.current() == "zh", "切回中文失败")
        need(app.btn_run.cget("text") == i18n.t("run.button"),
             "中文下主按钮文案未还原")
        need(app.root.title() == i18n.t("app.window_title"),
             "窗口标题未随语言还原")
        print("[selftest] 语言往返切换 OK")
    except Exception as exc:
        problems.append("语言切换异常：%s" % exc)
    finally:
        app.set_language(orig_choice, persist=False)

    if md_path and os.path.isfile(md_path):
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
            app.var_out_mode.set("custom")
            app.var_out_dir.set(out_dir)
        app.formats = {"docx", "doc", "wps", "txt"}
        for fid in FMT_ORDER:
            app._paint_fmt_card(fid)
        app._sync_txt_fold()
        app.add_paths([md_path])
        need(len(app.files) == 1, "未能载入测试文件")
        app.start_convert()
        deadline = time.time() + 180
        while app.running and time.time() < deadline:
            root.update()
            time.sleep(0.05)
        root.update()
        rows = app.res_tree.get_children()
        print("[selftest] 转换结果行数 =", len(rows))
        for i in rows:
            vals = app.res_tree.item(i, "values")
            tags = app.res_tree.item(i, "tags") or ("",)
            # 用 ASCII 状态标记，不打印结果表里的状态文案：那是界面用词，
            # 可能含控制台编码打不出的符号（GBK 下的 √ / × 就是），
            # 打印它会把自检直接带崩。详见 i18n 的"文案用字约束"。
            print("   [%s] %s %s" % (STATE_MARKS.get(tags[0], tags[0]),
                                     vals[2], vals[3][:110]))
        need(len(rows) == 4, "应产出 4 条结果（docx/doc/wps/txt）")
        need(all((app.res_tree.item(i, "tags") or [""])[0] in ("ok", "warn")
                 for i in rows), "存在失败的输出")

    try:
        app.shutdown()
        root.destroy()
    except Exception:
        pass

    if problems:
        print("[selftest] 失败：")
        for p in problems:
            print("   -", p)
        return 1
    print("[selftest] 通过")
    return 0


def diagnose() -> int:
    """内部诊断：显示窗口并输出 DPI / 几何度量后自动退出。"""
    enable_hi_dpi()
    root = tk.Tk()
    app = Md2docsApp(root, initial_files=[])

    def dump():
        try:
            for k, v in app.diag_info().items():
                print("%-22s %s" % (k, v))
        except Exception as exc:
            print("diag error:", exc)
        finally:
            app.shutdown()
            try:
                root.destroy()
            except Exception:
                pass

    root.after(1500, dump)
    root.mainloop()
    return 0


def run(initial_files=None) -> int:
    """启动原生窗口。"""
    enable_hi_dpi()
    root = tk.Tk()
    try:
        Md2docsApp(root, initial_files=initial_files)
        root.mainloop()
    finally:
        try:
            root.destroy()
        except Exception:
            pass
    return 0
