# -*- coding: utf-8 -*-
"""退出残留窗口探针（V-16）：验证后台清理子进程不会弹出控制台黑框。

历史缺陷
--------
退出时用
    creationflags = DETACHED_PROCESS(0x00000008) | CREATE_NO_WINDOW(0x08000000)
创建 cmd.exe 去延时删除 onefile 解包目录（先 ping 拖 3 秒再 rd）。
MSDN 在 CREATE_NO_WINDOW 条目里明写：

    This flag is ignored ... if it is used with either CREATE_NEW_CONSOLE
    or DETACHED_PROCESS.

于是"不显示窗口"这条指令被系统丢掉，cmd.exe 在没有任何控制台可继承的情况下
自己分配一个新控制台 —— 用户看到的就是：关掉程序之后凭空冒出一个黑框，
还得干等 ping -n 4 跑满约 3 秒才消失。

探针做法
--------
枚举顶层窗口里 class 属于控制台窗口类的窗口，在 spawn 前后取差集。
差集非空 = 期间弹出过控制台窗口。

自带正 / 反双控（默认都跑）
  * 正控：故意用 buggy 组合（DETACHED_PROCESS | CREATE_NO_WINDOW），
    **必须检出** ≥1 个新窗口 —— 用来证明探针真的看得见这个缺陷。
    正控若检不出，直接判探针失效，而不是判通过。
  * 反控：生产实际使用的组合，必须检出 0 个。
这条"正控必须阳性"的规矩是 V-14 的教训：一个看不见缺陷的探针会给出假通过，
比没有探针更危险。

顺带校验清理没有为了消窗口而被改坏：解包目录必须在超时内真的被删掉。

用法：
    python tools/check_no_console_window.py                正反双控 + 生产路径（默认）
    python tools/check_no_console_window.py --quick        只测生产路径
    python tools/check_no_console_window.py --exe          额外跑真机端到端
        （启动 dist/Md2docs.exe 走两条出路：`--cli` 跑一次转换、以及
          启动图形界面后投递 WM_CLOSE 关窗——即用户实际报的那条路径。
          全程盯新出现的控制台窗口，并在退出后核对 %TEMP% 下没有
          多出 _MEI* 残留目录）

退出码：0 = 通过；非 0 = 检出控制台窗口 / 清理失效 / 探针失效。
"""
from __future__ import annotations

import argparse
import ctypes
import glob
import os
import shutil
import subprocess as sp
import sys
import time
import uuid
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

import app  # noqa: E402  （被测对象：生产用的 spawn 实现与标志）

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.EnumWindows.restype = wintypes.BOOL
user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                            ctypes.POINTER(wintypes.DWORD)]
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

WM_CLOSE = 0x0010
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# 控制台窗口的窗口类。经典 conhost / Windows Terminal / 伪终端各一个。
CONSOLE_CLASSES = {
    "ConsoleWindowClass",
    "CASCADIA_HOSTING_WINDOW_CLASS",
    "PseudoConsoleWindow",
}

ENUM_CB = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

# 与生产保持一致的 buggy 组合，仅作正控
BUGGY_FLAGS = 0x00000008 | 0x08000000   # DETACHED_PROCESS | CREATE_NO_WINDOW


def _text(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


def list_console_windows() -> dict:
    """当前所有可见的控制台窗口 -> (类名, 归属 PID, 标题)。"""
    found: dict = {}

    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(256)
        if user32.GetClassNameW(hwnd, buf, 256) and buf.value in CONSOLE_CLASSES:
            pid = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            found[int(hwnd)] = (buf.value, pid.value, _text(hwnd))
        return True

    user32.EnumWindows(ENUM_CB(cb), 0)
    return found


def _scratch_dir() -> str:
    d = os.path.join(ROOT, "tests", "_cleanup_%s" % uuid.uuid4().hex[:8])
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "payload.txt"), "w", encoding="utf-8") as f:
        f.write("x")
    return d


def probe(flags: int | None, label: str, watch: float = 2.0,
          wait_cleanup: float = 12.0):
    """跑一轮：spawn 一个后台清理子进程，看期间有没有新控制台窗口冒出来。

    flags=None 表示走生产默认（app._spawn_cleanup 的缺省参数）。
    返回 (新窗口 dict, 清理是否成功)。
    """
    target = _scratch_dir()
    before = list_console_windows()

    if flags is None:
        proc = app._spawn_cleanup(target)
    else:
        proc = app._spawn_cleanup(target, flags)

    new: dict = {}
    end = time.time() + watch
    while time.time() < end:
        for h, v in list_console_windows().items():
            if h not in before:
                new[h] = v
        time.sleep(0.04)

    # 等子进程收工并把目录删掉（正常 ping -n 4 约 3 秒）
    try:
        if proc is not None:
            proc.wait(timeout=wait_cleanup)
    except Exception:
        pass

    cleaned = False
    deadline = time.time() + wait_cleanup
    while time.time() < deadline:
        if not os.path.isdir(target):
            cleaned = True
            break
        time.sleep(0.2)

    if os.path.isdir(target):
        shutil.rmtree(target, ignore_errors=True)

    print("[console] %-28s 新窗口=%d %s  目录已清理=%s"
          % (label, len(new), sorted(new.values()) if new else "", cleaned))
    return new, cleaned


def _mei_dirs() -> set:
    """临时目录下现存的 _MEI* 解包目录（onefile 每次运行解一个）。"""
    out = set()
    for key in ("TEMP", "TMP"):
        base = os.environ.get(key)
        if not base:
            continue
        for d in glob.glob(os.path.join(base, "_MEI*")):
            if os.path.isdir(d):
                out.add(os.path.normcase(os.path.abspath(d)))
    return out


def probe_exe(exe: str) -> tuple[dict, set]:
    """端到端：真跑一次 EXE，看它退出前后有没有冒出控制台窗口、留没留垃圾。

    这是探针里唯一覆盖 ``sys.frozen`` 真实分支的一环 —— 源码模式下
    ``_cleanup_frozen_exit`` 会直接 return，只有打包后的 EXE 才会真正
    spawn 后台清理子进程、也才会用上真实的 ``_MEIPASS``。
    用 txt 输出：转换格式与本探针无关，取最不依赖外部组件的链路。
    """
    work = os.path.join(ROOT, "tests", "_exe_console")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    md = os.path.join(work, "sample.md")
    with open(md, "w", encoding="utf-8") as f:
        f.write("# 控制台窗口回归\n\n正文段落。\n")
    out = os.path.join(work, "out")
    os.makedirs(out, exist_ok=True)

    before_win = list_console_windows()
    before_mei = _mei_dirs()

    p = sp.Popen([exe, "--cli", md, "-o", out, "-f", "txt"],
                 stdin=sp.DEVNULL, stdout=sp.DEVNULL, stderr=sp.DEVNULL)

    new_win: dict = {}
    deadline = time.time() + 40.0
    exited_at = None
    while time.time() < deadline:
        for h, v in list_console_windows().items():
            if h not in before_win:
                new_win[h] = v
        if p.poll() is not None:
            if exited_at is None:
                exited_at = time.time()
            elif time.time() - exited_at > 8.0:
                break        # 清理子进程 ping 约 3 秒，再留点余量
        time.sleep(0.05)

    left = _mei_dirs() - before_mei
    # 万一没删干净，别把垃圾留给下一次运行
    for d in left:
        shutil.rmtree(d, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)

    print("[console] 真机 EXE (%s)  rc=%s"
          % (os.path.basename(exe), p.returncode))
    print("[console] %-28s 新窗口=%d %s  _MEI 残留=%d %s"
          % ("end-to-end", len(new_win),
             sorted(new_win.values()) if new_win else "",
             len(left), sorted(os.path.basename(d) for d in left) if left else ""))
    return new_win, left


def _pid_exe(pid: int) -> str:
    """进程 PID -> 可执行文件名（拿不到返回空串）。"""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(512)
        n = wintypes.DWORD(512)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return os.path.basename(buf.value)
        return ""
    finally:
        kernel32.CloseHandle(h)


def windows_of(exe_name: str) -> dict:
    """某可执行文件拥有的全部顶层窗口 -> (类名, 标题)。"""
    want = os.path.basename(exe_name).lower()
    res: dict = {}

    def cb(hwnd, _lparam):
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value and _pid_exe(pid.value).lower() == want:
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            res[int(hwnd)] = (cls.value, _text(hwnd))
        return True

    user32.EnumWindows(ENUM_CB(cb), 0)
    return res


def probe_gui_exe(exe: str, startup: float = 30.0,
                  grace: float = 8.0) -> tuple[dict, set, bool]:
    """端到端（图形界面出口）：启动 EXE，等它的 Tk 窗口出来，投递 WM_CLOSE 退出。

    这是**用户实际报的那条路径**：双击启动 → 关窗口 → 程序退出。
    单独测它而不是靠"--cli 走的是同一段代码"推断，是因为一旦将来有人
    在退出路径里塞进 os._exit()，main 的 finally 就再也不会执行，
    只有真去关一次窗口才能发现。

    返回 (新控制台窗口, 残留 _MEI, 是否成功关掉)。
    """
    before_win = list_console_windows()
    before_mei = _mei_dirs()

    p = sp.Popen([exe], stdin=sp.DEVNULL, stdout=sp.DEVNULL, stderr=sp.DEVNULL)

    # 1) 等 Tk 顶层窗口出现
    hwnd = None
    deadline = time.time() + startup
    while time.time() < deadline and hwnd is None:
        for h, (cls, title) in windows_of(exe).items():
            if cls.lower().startswith("tk"):
                hwnd = h
                break
        if hwnd is None:
            if p.poll() is not None:
                break
            time.sleep(0.2)

    if hwnd is None:
        p.kill()
        print("[console] %-28s 没等到窗口，无法验证退出路径" % "gui-exit")
        return {}, set(), False

    # 2) 关窗口，然后一直盯到进程退出后再等 grace 秒
    user32.PostMessageW(wintypes.HWND(hwnd), WM_CLOSE, 0, 0)

    new_win: dict = {}
    deadline = time.time() + 60.0
    exited_at = None
    while time.time() < deadline:
        for h, v in list_console_windows().items():
            if h not in before_win:
                new_win[h] = v
        if p.poll() is not None:
            if exited_at is None:
                exited_at = time.time()
            elif time.time() - exited_at > grace:
                break
        time.sleep(0.05)

    closed = p.poll() is not None
    left = _mei_dirs() - before_mei
    for d in left:
        shutil.rmtree(d, ignore_errors=True)

    print("[console] 真机 EXE (%s)  rc=%s" % (os.path.basename(exe), p.returncode))
    print("[console] %-28s 新窗口=%d %s  _MEI 残留=%d %s"
          % ("gui-exit", len(new_win),
             sorted(new_win.values()) if new_win else "",
             len(left), sorted(os.path.basename(d) for d in left) if left else ""))
    return new_win, left, closed


def main() -> int:
    exe_default = os.path.join(ROOT, "dist", "Md2docs.exe")
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true",
                    help="跳过正反双控，只测生产路径")
    ap.add_argument("--exe", nargs="?", const=exe_default, default=None,
                    metavar="PATH",
                    help="额外做真机端到端：--cli 出口 + 图形界面关窗出口"
                         "（默认 dist/Md2docs.exe）")
    args = ap.parse_args()

    fails = []

    if not args.quick:
        # 正控：用旧的 buggy 标志组合，探针必须能看见窗口
        new, _ = probe(BUGGY_FLAGS, "正控 DETACHED|NO_WINDOW")
        if not new:
            fails.append("正控未检出控制台窗口 —— 探针失效，本轮结论不可信")
            print("[console] 正控失灵：探针看不见该缺陷，直接判失败")

    # 生产路径：默认标志必须干净，且清理仍然生效
    new, cleaned = probe(None, "生产路径（默认标志）")
    if new:
        fails.append("生产路径仍弹出控制台窗口：%s" % sorted(new.values()))
    if not cleaned:
        fails.append("生产路径未删除 onefile 解包目录（清理被改坏）")

    if args.exe:
        if not os.path.isfile(args.exe):
            fails.append("找不到 EXE：%s" % args.exe)
        else:
            new, left = probe_exe(args.exe)
            if new:
                fails.append("真机 EXE 弹出控制台窗口：%s" % sorted(new.values()))
            if left:
                fails.append("真机 EXE 退出后 %d 个 _MEI 目录未清理：%s"
                             % (len(left), sorted(os.path.basename(d)
                                                  for d in left)))
            new, left, closed = probe_gui_exe(args.exe)
            if not closed:
                fails.append("图形界面入口没能正常关窗退出（退出路径可能没走到）")
            if new:
                fails.append("关闭图形界面时弹出控制台窗口：%s"
                             % sorted(new.values()))
            if left:
                fails.append("关闭图形界面后 %d 个 _MEI 目录未清理：%s"
                             % (len(left), sorted(os.path.basename(d)
                                                  for d in left)))

    print("")
    if fails:
        for f in fails:
            print("[console] 失败：%s" % f)
        return 1
    print("[console] 通过：无控制台窗口弹出，且解包目录清理正常")
    return 0


if __name__ == "__main__":
    sys.exit(main())
