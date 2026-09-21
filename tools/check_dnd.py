# -*- coding: utf-8 -*-
"""拖放回归探针（V-11）：向窗口投递真实 WM_DROPFILES，验证进程不崩溃且能收下文件。

历史缺陷：在窗口过程回调里调用 root.after() 重入 Tcl，导致
    Fatal Python error: PyEval_RestoreThread ... thread state is NULL
进程当场消失，表现为"把文件拖进程序，程序就退出了"。

为什么投递消息而不是用鼠标模拟真实拖拽：
    窗口用 DragAcceptFiles 注册的是 Shell 拖放，真实拖拽（无论来自资源管理器
    还是 OLE DoDragDrop）最终都由 Shell 转成 WM_DROPFILES 投递到本窗口——
    这里投递的正是同一条消息、进入同一段窗口过程。中间的 OLE 拖放源、鼠标
    捕获、Shell 解析都在 Md2docs 进程之外，不属于被测代码。
    浏览器自动化工具（Playwright 等）无法参与：它们只能驱动自带的浏览器实例，
    看不见原生 Win32 窗口。

用法：
    python tools/check_dnd.py              源码模式（进程内构建界面）
    python tools/check_dnd.py --exe        打包后的 dist/Md2docs.exe
    python tools/check_dnd.py --argv       「把文件拖到 EXE 图标上」的命令行入口

覆盖面：单/多文件、重复去重、连续冲击、目录展开、不存在路径、非 Markdown
文件、大写扩展名、空 HDROP、非法句柄、一次 150 个文件。

退出码：0 = 通过；非 0 = 失败或进程被拖放消息打死。
"""
from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import sys
import time
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

import i18n       # noqa: E402  （界面语言决定窗口标题，不能再硬编码）

WM_DROPFILES = 0x0233
GMEM_MOVEABLE = 0x0002

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32

kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]

user32.PostMessageW.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                wintypes.WPARAM, wintypes.LPARAM]

kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


class DROPFILES(ctypes.Structure):
    _fields_ = [("pFiles", wintypes.DWORD), ("pt", wintypes.POINT),
                ("fNC", wintypes.BOOL), ("fWide", wintypes.BOOL)]


def make_hdrop(paths: list[str]):
    """按 shell 的 HDROP 内存布局构造句柄（DragQueryFileW 可直接解析）。"""
    head = DROPFILES()
    head.pFiles = ctypes.sizeof(DROPFILES)
    head.fWide = True
    blob = bytes(head) + ("\0".join(paths) + "\0\0").encode("utf-16-le")
    h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(blob))
    p = kernel32.GlobalLock(h)
    ctypes.memmove(p, blob, len(blob))
    kernel32.GlobalUnlock(h)
    return h


def post_hdrop(hwnd: int, paths: list[str]) -> bool:
    h = make_hdrop(paths)
    return bool(user32.PostMessageW(wintypes.HWND(hwnd), WM_DROPFILES,
                                    wintypes.WPARAM(h), 0))


def top_hwnd(root) -> int:
    root.update_idletasks()
    child = int(root.winfo_id())
    return int(user32.GetParent(child) or child)


def make_fixtures(tmp: str, n: int) -> list[str]:
    if os.path.isdir(tmp):
        shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    out = []
    for i in range(n):
        p = os.path.join(tmp, "drop_%d.md" % i)
        with open(p, "w", encoding="utf-8") as f:
            f.write("# 拖放测试 %d\n\n内容段落。\n" % i)
        out.append(p)
    return out


# --------------------------------------------------------------------------- #
def run_source_mode(fixtures: list[str]) -> int:
    import tkinter as tk

    import gui

    gui.enable_hi_dpi()
    root = tk.Tk()
    root.withdraw()
    app = gui.Md2docsApp(root)
    hwnd = top_hwnd(root)
    print("[dnd] 拖放功能启用 =", app._dnd_ok, " hwnd =", hwnd)
    if not app._dnd_ok:
        print("[dnd] 失败：拖放未启用")
        return 1

    def pump(seconds: float, want: int | None = None):
        end = time.time() + seconds
        while time.time() < end:
            root.update()
            time.sleep(0.03)
            if want is not None and len(app.files) >= want:
                root.update()
                return

    fails = []

    # 1) 拖入 1 个文件
    post_hdrop(hwnd, fixtures[:1])
    pump(3.0, want=1)
    print("[dnd] 单文件  -> %d 个文件 %s" % (len(app.files),
                                             [f["name"] for f in app.files]))
    if len(app.files) != 1:
        fails.append("单文件拖入未生效")

    # 2) 一次拖入另外 2 个文件 -> 合计 3
    post_hdrop(hwnd, fixtures[1:3])
    pump(3.0, want=3)
    print("[dnd] 多文件  -> %d 个文件" % len(app.files))
    if len(app.files) != 3:
        fails.append("多文件拖入未生效")

    # 3) 重复拖入已存在的文件，应被去重
    post_hdrop(hwnd, fixtures[:1])
    pump(2.0)
    print("[dnd] 重复拖入 -> %d 个文件（应保持 3，去重）" % len(app.files))
    if len(app.files) != 3:
        fails.append("重复拖入未去重")

    # 4) 连续快速拖入 5 次，压一下队列
    for _ in range(5):
        post_hdrop(hwnd, fixtures[:2])
        time.sleep(0.05)
    pump(3.0)
    print("[dnd] 连续拖放 5 次后仍存活，文件数 =", len(app.files))
    if len(app.files) != 3:
        fails.append("连续拖放导致状态异常")

    # ---------------- 边界 / 压力用例（压窗口过程与消费端） ----------------
    tail = os.path.join(ROOT, "tests", "_dnd_out")

    # 5) 目录拖入：只展开目录内的 Markdown/文本
    nested = os.path.join(tail, "nested")
    os.makedirs(nested, exist_ok=True)
    for nm in ("a.md", "b.markdown", "note.txt", "pic.png"):
        with open(os.path.join(nested, nm), "w", encoding="utf-8") as f:
            f.write("# %s\n" % nm)
    base = len(app.files)
    post_hdrop(hwnd, [nested])
    pump(4.0, want=base + 3)
    got = len(app.files) - base
    print("[dnd] 目录展开 -> +%d（期望 +3：a.md / b.markdown / note.txt）" % got)
    if got != 3:
        fails.append("目录展开数量不符（期望 3，实得 %d）" % got)

    # 6) 不存在的路径
    base = len(app.files)
    post_hdrop(hwnd, [os.path.join(tail, "zzz_不存在_404.md")])
    pump(2.0)
    print("[dnd] 不存在的路径 -> +%d（期望 +0）" % (len(app.files) - base))
    if len(app.files) != base:
        fails.append("不存在的路径被计入列表")

    # 7) 非 Markdown 文件直投（观察项：直接文件当前不做扩展名过滤）
    base = len(app.files)
    post_hdrop(hwnd, [os.path.join(nested, "pic.png")])
    pump(2.0)
    print("[dnd] 非 Markdown 直投 -> +%d（直接放行，属当前实现行为）"
          % (len(app.files) - base))

    # 8) 大写扩展名
    up = os.path.join(tail, "UPPER.MD")
    with open(up, "w", encoding="utf-8") as f:
        f.write("# 大写扩展名\n")
    base = len(app.files)
    post_hdrop(hwnd, [up])
    pump(2.0, want=base + 1)
    print("[dnd] 大写 .MD -> +%d（期望 +1）" % (len(app.files) - base))
    if len(app.files) != base + 1:
        fails.append("大写扩展名未被接受")

    # 9) 空 HDROP（0 个路径）
    base = len(app.files)
    post_hdrop(hwnd, [])
    pump(2.0)
    print("[dnd] 空 HDROP -> 仍存活，文件数 =", len(app.files))
    if len(app.files) != base:
        fails.append("空 HDROP 改变了状态")

    # 10) 非法 HDROP 句柄：解析失败须被安静丢弃
    base = len(app.files)
    user32.PostMessageW(wintypes.HWND(hwnd), WM_DROPFILES,
                        wintypes.WPARAM(0xDEADBEEF), 0)
    pump(2.0)
    print("[dnd] 非法句柄 -> 仍存活，文件数 =", len(app.files))
    if len(app.files) != base:
        fails.append("非法句柄改变了状态")

    # 11) 一次性拖入 150 个文件
    bulk = os.path.join(tail, "bulk")
    os.makedirs(bulk, exist_ok=True)
    many = []
    for i in range(150):
        p = os.path.join(bulk, "bulk_%03d.md" % i)
        with open(p, "w", encoding="utf-8") as f:
            f.write("# 批量 %d\n" % i)
        many.append(p)
    base = len(app.files)
    post_hdrop(hwnd, many)
    pump(12.0, want=base + 150)
    got = len(app.files) - base
    print("[dnd] 批量 150 个 -> +%d（期望 +150）" % got)
    if got != 150:
        fails.append("批量拖入数量不符（期望 150，实得 %d）" % got)

    print("[dnd] 全部边界用例跑完后进程存活，累计文件数 =", len(app.files))

    try:
        app.shutdown()
        root.destroy()
    except Exception as exc:
        fails.append("退出时异常：%s" % exc)

    if fails:
        print("[dnd] 失败：")
        for f in fails:
            print("   -", f)
        return 1
    print("[dnd] 通过")
    return 0


def window_titles() -> set:
    """所有可能的窗口标题。

    界面支持中英双语，标题随语言而变，不能再写死一个常量——
    否则在英文环境下会永远找不到窗口，误判成"程序没起来"。
    """
    return {i18n.STRINGS[lang]["app.window_title"] for lang in i18n.LANGS}


def _proc_image(pid: int) -> str:
    """取进程映像全路径（onefile 引导进程会另起子进程，PID 对不上）。"""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(h)


def find_app_window(exe: str, timeout: float = 40.0) -> int:
    """按窗口标题 + 映像路径找到真实 GUI 窗口（兼容 onefile 子进程）。"""
    want_titles = window_titles()
    want_exe = os.path.normcase(os.path.abspath(exe))
    end = time.time() + timeout
    while time.time() < end:
        found: list[int] = []
        CB = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def cb(h, _l):
            if not user32.IsWindowVisible(h):
                return True
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(h, buf, 512)
            if buf.value.strip() not in want_titles:
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            img = _proc_image(pid.value)
            if img and os.path.normcase(img) == want_exe:
                found.append(int(h))
            return True

        user32.EnumWindows(CB(cb), 0)
        if found:
            return found[0]
        time.sleep(0.4)
    return 0


def run_exe_mode(exe: str, fixtures: list[str]) -> int:
    import subprocess

    if not os.path.isfile(exe):
        print("[dnd] 失败：找不到可执行文件", exe)
        return 2
    p = subprocess.Popen([exe])
    try:
        hwnd = find_app_window(exe)
        if not hwnd:
            print("[dnd] 失败：未找到窗口（进程 code = %s）" % p.poll())
            return 1
        print("[dnd] 窗口 hwnd =", hwnd)
        time.sleep(1.2)

        for round_no in range(1, 4):
            post_hdrop(hwnd, fixtures[:2])
            time.sleep(1.2)
            code = p.poll()
            if code is not None:
                print("[dnd] 失败：第 %d 次拖放后进程退出，code = %s"
                      % (round_no, code))
                return 1
            print("[dnd] 第 %d 次拖放后进程存活" % round_no)

        print("[dnd] 通过：进程存活")
        return 0
    finally:
        try:
            if p.poll() is None:
                p.terminate()
                time.sleep(0.5)
                if p.poll() is None:
                    p.kill()
        except Exception:
            pass


def run_argv_mode(exe: str, fixtures: list[str]) -> int:
    """带文件路径启动 EXE —— 等价于把文件拖到 EXE 图标上（命令行入口）。"""
    import subprocess

    if not os.path.isfile(exe):
        print("[dnd] 失败：找不到可执行文件", exe)
        return 2
    p = subprocess.Popen([exe] + fixtures[:2])
    try:
        hwnd = find_app_window(exe)
        if not hwnd:
            print("[dnd] 失败：未找到窗口（进程 code = %s）" % p.poll())
            return 1
        print("[dnd] 窗口 hwnd =", hwnd)
        time.sleep(2.5)
        code = p.poll()
        if code is not None:
            print("[dnd] 失败：带文件参数启动后进程退出，code = %s" % code)
            return 1
        print("[dnd] 通过：带文件参数启动，进程存活")
        return 0
    finally:
        try:
            if p.poll() is None:
                p.terminate()
                time.sleep(0.5)
                if p.poll() is None:
                    p.kill()
        except Exception:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", action="store_true", help="测试打包后的 EXE 拖放")
    ap.add_argument("--argv", action="store_true",
                    help="测试「把文件拖到 EXE 图标上」的命令行入口")
    ap.add_argument("--exe-path", default=os.path.join(ROOT, "dist", "Md2docs.exe"))
    args = ap.parse_args()

    fixtures = make_fixtures(os.path.join(ROOT, "tests", "_dnd_out"), 3)
    print("[dnd] 测试文件 =", fixtures)
    if args.argv:
        return run_argv_mode(args.exe_path, fixtures)
    if args.exe:
        return run_exe_mode(args.exe_path, fixtures)
    return run_source_mode(fixtures)


if __name__ == "__main__":
    sys.exit(main())
