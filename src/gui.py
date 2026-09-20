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
OK = "#34d399"
WARN = "#fbbf24"
ERR = "#f87171"

FMT_ORDER = ["docx", "doc", "wps", "txt"]
FMT_TAG = {"docx": "DOCX", "doc": "DOC", "wps": "WPS", "txt": "TXT"}
FMT_DESC = {"docx": "Word 2007+ 原生", "doc": "Word 97-2003",
            "wps": "WPS 文字", "txt": "纯文本"}

MD_EXTS = (".md", ".markdown", ".mdown", ".mkd", ".mdtext", ".mdtxt", ".txt")

WINDOW_TITLE = "Md2docs · Markdown 转 Word / WPS / TXT"

# 窗口设计宽度（客户区）。必须为常量，不可由内容宽度反推——原因见
# Md2docsApp._window_width()：表格可伸缩列会与窗口宽度互相抬高，
# 形成自增循环，表现为每点击一次格式卡片窗口就变宽一点。
WIN_W = 988


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


def open_path(path: str) -> tuple[bool, str]:
    if not path:
        return False, "空路径"
    if not os.path.exists(path):
        return False, "路径不存在"
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
# 折叠区
# --------------------------------------------------------------------------- #
class Fold(tk.Frame):
    """点标题栏展开 / 收起的区块，右侧可显示状态摘要。"""

    def __init__(self, parent, title: str, on_toggle=None, fonts=None):
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
        self.title = tk.Label(self.head, text=title, bg=PANEL, fg=TEXT,
                              font=self.fonts.get("small"))
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
        self.var_caps = tk.StringVar(value="正在检测本机 Office…")

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
    def _btn(self, parent, text, cmd, kind="soft", font=None, width=None):
        colors = {
            "primary": (ACCENT, "#ffffff", ACCENT_HI),
            "soft": (PANEL2, TEXT, LINE),
            "ghost": (PANEL, DIM, PANEL2),
        }[kind]
        bg, fg, hover = colors
        b = tk.Button(parent, text=text, command=cmd, relief="flat", bd=0,
                      highlightthickness=0, padx=13, pady=5, bg=bg, fg=fg,
                      activebackground=hover,
                      activeforeground="#ffffff" if kind == "primary" else TEXT,
                      font=font or self.fonts["small"], cursor="hand2",
                      disabledforeground=MUTE)
        if width:
            b.configure(width=width)
        if kind != "primary":
            b.bind("<Enter>", lambda _e: b.configure(bg=hover))
            b.bind("<Leave>", lambda _e: b.configure(bg=bg))
        return b

    def _panel(self, parent):
        f = tk.Frame(parent, bg=PANEL, highlightbackground=LINE,
                     highlightthickness=1, bd=0)
        f.pack(fill="x", pady=(0, 8))
        return f

    def _panel_head(self, panel, step: str, text: str):
        head = tk.Frame(panel, bg=PANEL)
        head.pack(fill="x", padx=16, pady=(7, 5))
        tk.Label(head, text=step, bg=ACCENT, fg="#ffffff",
                 font=self.fonts["tiny"], width=2).pack(side="left", padx=(0, 8))
        tk.Label(head, text=text, bg=PANEL, fg=TEXT,
                 font=self.fonts["bold"]).pack(side="left")
        right = tk.Frame(head, bg=PANEL)
        right.pack(side="right")
        return head, right

    def _radio(self, parent, text, value, var):
        return tk.Radiobutton(parent, text=text, value=value, variable=var,
                              bg=PANEL, fg=TEXT, selectcolor=PANEL2,
                              activebackground=PANEL, activeforeground=TEXT,
                              font=self.fonts["small"], relief="flat", bd=0,
                              highlightthickness=0, cursor="hand2",
                              command=self._on_option_change)

    # ------------------------------------------------------------------ #
    # 界面搭建
    # ------------------------------------------------------------------ #
    def _build(self):
        self.root.title(WINDOW_TITLE)
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
        logo.create_text(19, 20, text="M", fill="#ffffff", font=self.fonts["logo"])

        txt = tk.Frame(bar, bg=BG)
        txt.pack(side="left")
        tk.Label(txt, text="Md2docs", bg=BG, fg=TEXT,
                 font=self.fonts["title"]).pack(anchor="w")
        tk.Label(txt, text="Markdown 一键转成 Word / WPS / 纯文本", bg=BG,
                 fg=MUTE, font=self.fonts["sub"]).pack(anchor="w")

        right = tk.Frame(bar, bg=BG)
        right.pack(side="right")
        self.lbl_caps = tk.Label(right, textvariable=self.var_caps, bg=PANEL2,
                                 fg=DIM, font=self.fonts["tiny"], padx=10, pady=4)
        self.lbl_caps.pack()

    # -- 第 1 步：文件 --------------------------------------------------- #
    def _build_files(self):
        panel = self._panel(self.main)
        _head, right = self._panel_head(panel, "1", "选择 Markdown 文件")
        self._btn(right, "浏览本机文件", self.pick_files, "soft").pack(side="right")
        self._btn(right, "清空", self.clear_files, "ghost").pack(side="right",
                                                                  padx=(0, 8))

        drop = tk.Frame(panel, bg=PANEL2, highlightbackground=LINE,
                        highlightthickness=1, cursor="hand2")
        drop.pack(fill="x", padx=16, pady=(0, 8))
        drop.bind("<Button-1>", lambda _e: self.pick_files())
        inner = tk.Frame(drop, bg=PANEL2)
        inner.pack(pady=7)
        t1 = tk.Label(inner, text="把 .md 文件拖到这里，或点击「浏览本机文件」"
                                  "（也可直接拖到 Md2docs.exe 图标上）",
                      bg=PANEL2, fg=TEXT, font=self.fonts["small"])
        t1.pack()
        t2 = tk.Label(inner, text="支持多选，自动保留相对图片引用", bg=PANEL2,
                      fg=MUTE, font=self.fonts["tiny"])
        t2.pack(pady=(2, 0))
        for w in (inner, t1, t2):
            w.bind("<Button-1>", lambda _e: self.pick_files())

        wrap = tk.Frame(panel, bg=PANEL)
        wrap.pack(fill="x", padx=16, pady=(0, 12))
        self.file_tree = ttk.Treeview(wrap, columns=("name", "src"),
                                      show="headings", height=3,
                                      style="Md.Treeview", selectmode="extended")
        self.file_tree.heading("name", text="文件名", anchor="w")
        self.file_tree.heading("src", text="位置", anchor="w")
        self.file_tree.column("name", width=200, anchor="w", stretch=False)
        self.file_tree.column("src", width=380, anchor="w", stretch=True)
        sb = ttk.Scrollbar(wrap, orient="vertical", style="Md.Vertical.TScrollbar",
                           command=self.file_tree.yview)
        self.file_tree.configure(yscrollcommand=sb.set)
        self.file_tree.pack(side="left", fill="x", expand=True)
        sb.pack(side="right", fill="y")
        self.file_tree.bind("<Delete>", lambda _e: self.remove_selected())
        self.file_tree.bind("<Double-1>", lambda _e: self.open_selected())

        self.lbl_file_empty = tk.Label(panel, text="还没有添加文件（支持 .md / "
                                                   ".markdown）", bg=PANEL,
                                       fg=MUTE, font=self.fonts["tiny"])
        self.lbl_file_empty.pack(anchor="w", padx=16, pady=(0, 12))
        if self.files:
            self.lbl_file_empty.pack_forget()

    # -- 第 2 步：输出设置 ----------------------------------------------- #
    def _build_output(self):
        panel = self._panel(self.main)
        self._panel_head(panel, "2", "输出设置")

        row = tk.Frame(panel, bg=PANEL)
        row.pack(fill="x", padx=16)
        for i, fid in enumerate(FMT_ORDER):
            row.columnconfigure(i, weight=1, uniform="fmt")
            self._fmt_cards[fid] = self._make_fmt_card(row, fid, i)

        body = tk.Frame(panel, bg=PANEL)
        body.pack(fill="x", padx=16, pady=(4, 7))

        # 输出位置
        self.fold_out = Fold(body, "输出位置", on_toggle=self._autosize,
                             fonts=self.fonts)
        self.fold_out.pack(fill="x")
        r1 = tk.Frame(self.fold_out.body, bg=PANEL)
        r1.pack(fill="x")
        self._radio(r1, "与源文件相同", "same", self.var_out_mode).pack(side="left")
        self._radio(r1, "指定目录", "custom",
                    self.var_out_mode).pack(side="left", padx=(14, 10))
        self.ent_out = tk.Entry(r1, textvariable=self.var_out_dir, bg=PANEL2,
                                fg=TEXT, insertbackground=TEXT, relief="flat",
                                highlightthickness=1, highlightbackground=LINE,
                                highlightcolor=ACCENT, font=self.fonts["small"],
                                disabledbackground=PANEL, disabledforeground=MUTE)
        self.ent_out.pack(side="left", fill="x", expand=True, ipady=3)
        self.btn_pick_dir = self._btn(r1, "浏览", self.pick_out_dir, "soft")
        self.btn_pick_dir.pack(side="left", padx=(8, 0))

        # TXT 选项
        self.fold_txt = Fold(body, "TXT 选项", on_toggle=self._autosize,
                             fonts=self.fonts)
        self.fold_txt.pack(fill="x")
        t1 = tk.Frame(self.fold_txt.body, bg=PANEL)
        t1.pack(fill="x")
        self._radio(t1, "去掉 Markdown 符号", "plain",
                    self.var_txt_mode).pack(side="left")
        self._radio(t1, "保留原始 Markdown", "raw",
                    self.var_txt_mode).pack(side="left", padx=(14, 16))
        tk.Label(t1, text="编码", bg=PANEL, fg=DIM,
                 font=self.fonts["small"]).pack(side="left", padx=(0, 6))
        self.cmb_enc = ttk.Combobox(t1, textvariable=self.var_txt_enc,
                                    values=convert.ENCODINGS, state="readonly",
                                    width=20, style="Md.TCombobox",
                                    font=self.fonts["small"])
        self.cmb_enc.pack(side="left")

        # 高质量模式
        self.fold_native = Fold(body, ".doc / .wps 高质量模式",
                                on_toggle=self._autosize, fonts=self.fonts)
        self.fold_native.pack(fill="x")
        self.sw_native = tk.Checkbutton(
            self.fold_native.right, text="启用", variable=self.var_native,
            command=self._on_native_switch, bg=PANEL2, fg=DIM,
            selectcolor=CARD_ON, activebackground=PANEL2,
            activeforeground=TEXT, font=self.fonts["tiny"], relief="flat",
            bd=0, highlightthickness=0, padx=8, pady=2, cursor="hand2",
            indicatoron=False)
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
        desc = tk.Label(inner, text=FMT_DESC.get(fid, ""), bg=PANEL2, fg=MUTE,
                        font=self.fonts["tiny"])
        desc.pack(anchor="w")

        widgets = [card, inner, tag, desc]
        for w in widgets:
            w.bind("<Button-1>", lambda _e, f=fid: self.toggle_format(f))
        self._paint_fmt_card(fid, widgets)
        return {"widgets": widgets}

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
        _head, _right = self._panel_head(panel, "3", "开始转换")

        bar = tk.Frame(panel, bg=PANEL)
        bar.pack(fill="x", padx=16)
        self.btn_run = self._btn(bar, "开始转换", self.start_convert, "primary",
                                 font=self.fonts["base"])
        self.btn_run.configure(padx=20, pady=5)
        self.btn_run.pack(side="left")
        self.btn_open_out = self._btn(bar, "打开输出文件夹", self.open_out_dirs,
                                      "soft")
        self.btn_open_out.pack(side="left", padx=(10, 0))
        self.btn_open_out.configure(state="disabled")

        self.prog = ttk.Progressbar(bar, variable=self.var_progress, maximum=1.0,
                                    style="Md.Horizontal.TProgressbar",
                                    length=180)
        self.prog.pack(side="left", padx=(16, 10), pady=(6, 0))
        tk.Label(bar, textvariable=self.var_progress_text, bg=PANEL, fg=DIM,
                 font=self.fonts["tiny"]).pack(side="left")

        wrap = tk.Frame(panel, bg=PANEL)
        wrap.pack(fill="x", padx=16, pady=(6, 9))
        self.res_tree = ttk.Treeview(wrap, columns=("state", "file", "fmt", "info"),
                                     show="headings", height=5, style="Md.Treeview",
                                     selectmode="browse")
        for cid, txt, w, anchor, stretch in (
                ("state", "状态", 62, "center", False),
                ("file", "文件", 178, "w", False),
                ("fmt", "格式", 62, "center", False),
                ("info", "说明", 390, "w", True)):
            self.res_tree.heading(cid, text=txt, anchor=anchor)
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
        tk.Label(foot, text="作者：王冠", bg=BG, fg=MUTE,
                 font=self.fonts["tiny"]).pack()

    def _bind_keys(self):
        self.root.bind("<Control-o>", lambda _e: self.pick_files())
        self.root.bind("<F5>", lambda _e: self.start_convert())
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _enable_drop(self):
        ok = enable_file_drop(self.root, self.on_drop_files)
        self._dnd_ok = ok

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
            self.toast("没有可添加的 Markdown 文件", "err")
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
            self.toast("已添加 %d 个文件" % added)
        elif skipped:
            self.toast("这些文件已在列表中", "warn")

    def on_drop_files(self, paths):
        self.add_paths(paths)

    def pick_files(self):
        paths = filedialog.askopenfilenames(
            title="选择 Markdown 文件",
            filetypes=[("Markdown 文件", "*.md *.markdown *.mdown *.mkd"),
                       ("文本文件", "*.txt"),
                       ("所有文件", "*.*")])
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
        self._res_dirs.clear()
        self._last_out_dirs = []
        self.btn_open_out.configure(state="disabled")
        self.var_progress.set(0)
        self.var_progress_text.set("")

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
        self.fold_txt.set_summary("已选 TXT" if on else "未选 TXT",
                                  OK if on else MUTE)
        self._autosize()

    def _sync_outdir_widgets(self):
        custom = self.var_out_mode.get() == "custom"
        state = "normal" if custom else "disabled"
        self.ent_out.configure(state=state)
        self.btn_pick_dir.configure(state=state,
                                    fg=(TEXT if custom else MUTE))
        self.fold_out.set_summary(("指定目录" if custom else "与源文件相同"),
                                  TEXT if custom else MUTE)

    def refresh_outdir(self):
        mode = self.var_out_mode.get()
        if mode == "custom":
            self.ent_out.configure(state="normal")
            self.btn_pick_dir.configure(state="normal", fg=TEXT)
            val = self.var_out_dir.get()
            self.fold_out.set_summary(
                ("指定目录：" + os.path.basename(val.rstrip("\\/")) if val
                 else "指定目录（未选择）"), TEXT if val else MUTE)
        else:
            dirs = {os.path.dirname(f["path"]) for f in self.files}
            if not dirs:
                txt, color = "与源文件相同", MUTE
            elif len(dirs) == 1:
                d = next(iter(dirs))
                txt, color = "与源文件相同：" + d, TEXT
            else:
                txt, color = "与源文件相同（多个目录）", TEXT
            self.fold_out.set_summary(txt, color)

    def pick_out_dir(self):
        d = filedialog.askdirectory(title="选择输出目录")
        if d:
            self.var_out_dir.set(os.path.normpath(d))
            self.var_out_mode.set("custom")
            self._sync_outdir_widgets()
            self.refresh_outdir()

    def _on_native_switch(self):
        on = bool(self.var_native.get()) and self._native_enabled()
        self.sw_native.configure(fg=OK if on else DIM, bg=CARD_ON if on else PANEL2)
        self.fold_native.set_summary("本机 Office 原生格式" if on else "RTF 兼容格式",
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
            self.var_caps.set("● " + " / ".join(names) + " 已就绪")
            self.lbl_caps.configure(fg=OK, bg="#143026")
            hint = ("开启后调用本机 Office 另存为原生格式（稍慢）；关闭则用内置 "
                    "RTF 引擎，秒出且格式同样完整。")
        else:
            self.var_caps.set("○ 未检测到 Word / WPS")
            self.lbl_caps.configure(fg=DIM, bg=PANEL2)
            hint = ("本机未检测到 Word / WPS，此项不可用；.doc / .wps 由内置 RTF "
                    "引擎生成，Word、WPS 均可直接打开。")
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
            self.toast("请先添加 Markdown 文件", "err")
            return
        if not self.formats:
            self.toast("请至少选择一种输出格式", "err")
            return

        mode = self.var_out_mode.get()
        out_dir = ""
        if mode == "custom":
            out_dir = self.var_out_dir.get().strip()
            if not out_dir:
                self.toast("请选择输出目录", "err")
                return
            try:
                os.makedirs(out_dir, exist_ok=True)
            except OSError as exc:
                self.toast("输出目录不可用：%s" % exc, "err")
                return

        self.running = True
        self.btn_run.configure(state="disabled", bg=MUTE, text="转换中…")
        self.clear_results()
        self.var_progress.set(0.02)
        self.var_progress_text.set("转换中…")

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
                    message="文件不存在")))
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
                    self.var_progress_text.set("已完成 %d / %d" % (done, total))
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

    def add_result(self, r: convert.Result):
        if r.ok:
            state, tag = "✓ 成功", "ok"
            info = "%s · %s · %s" % (r.target, fmt_size(r.size), r.engine)
            if r.warnings:
                tag = "warn"
                info += "  ⚠ " + "；".join(r.warnings)
            self._res_dirs[str(r.target)] = os.path.dirname(r.target)
        else:
            state, tag = "✕ 失败", "bad"
            info = r.message or "转换失败"
        fmt = ("." + r.fmt) if r.fmt else "-"
        self.res_tree.insert("", "end", tags=(tag,),
                             values=(state, r.name, fmt, info))

    def finish_convert(self):
        self.running = False
        self.btn_run.configure(state="normal", bg=ACCENT, text="开始转换")
        rows = self.res_tree.get_children()
        n_total = len(rows)
        n_ok = 0
        for i in rows:
            tags = self.res_tree.item(i, "tags") or ()
            if tags and tags[0] in ("ok", "warn"):
                n_ok += 1
        self.var_progress.set(1.0)
        self.var_progress_text.set("完成 %d / %d" % (n_ok, n_total))
        dirs = sorted({d for d in self._res_dirs.values() if d})
        self._last_out_dirs = dirs
        self.btn_open_out.configure(state="normal" if dirs else "disabled",
                                    fg=(TEXT if dirs else MUTE))
        self.toast("转换完成：%d 个文件" % n_ok, "ok" if n_ok else "err")

    def open_out_dirs(self):
        if not self._last_out_dirs:
            return
        ok, err = open_path(self._last_out_dirs[0])
        if not ok:
            self.toast(err, "err")

    def open_result_folder(self):
        sel = self.res_tree.selection()
        if not sel:
            return
        vals = self.res_tree.item(sel[0], "values")
        if not str(vals[0]).endswith("成功"):
            return
        target = str(vals[3]).split(" · ")[0]
        ok, err = open_path(os.path.dirname(target))
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
            print("   [%s] %s %s %s" % (tags[0], vals[0], vals[2], vals[3][:110]))
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
