# -*- coding: utf-8 -*-
"""Md2docs 启动入口。"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser

DEFAULT_PORT = 8756


def _log_path() -> str:
    base = os.path.join(os.path.expanduser("~"), "Documents", "Md2docs")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "md2docs.log")


def _attach_console():
    """--windowed 打包后 stdout 不可用，CLI 模式下附着到父控制台输出。"""
    if not getattr(sys, "frozen", False):
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        if not kernel32.AttachConsole(-1):
            return
        try:
            sys.stdout = open("CONOUT$", "w", buffering=1)
        except Exception:
            pass
        try:
            sys.stderr = open("CONOUT$", "w", buffering=1)
        except Exception:
            pass
    except Exception:
        pass


def _say(msg: str):
    """--windowed 模式下 stdout 为 None，直接 print 会崩。"""
    try:
        if sys.stdout:
            print(msg)
    except Exception:
        pass


def _parent_pid() -> int:
    """当前进程的父 PID（Windows Toolhelp 快照）。失败返回 0。"""
    try:
        import ctypes
        import ctypes.wintypes as wt

        class PE(ctypes.Structure):
            _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                        ("pid", wt.DWORD),
                        ("heap", ctypes.POINTER(ctypes.c_ulong)),
                        ("mod", wt.DWORD), ("threads", wt.DWORD),
                        ("ppid", wt.DWORD), ("pri", ctypes.c_long),
                        ("flags", wt.DWORD), ("exe", wt.WCHAR * 260)]
        h = ctypes.windll.kernel32.CreateToolhelp32Snapshot(2, 0)
        e = PE(); e.dwSize = ctypes.sizeof(PE)
        mine = os.getpid()
        ppid = 0
        ok = ctypes.windll.kernel32.Process32FirstW(h, ctypes.byref(e))
        while ok:
            if e.pid == mine:
                ppid = e.ppid
                break
            ok = ctypes.windll.kernel32.Process32NextW(h, ctypes.byref(e))
        ctypes.windll.kernel32.CloseHandle(h)
        return ppid
    except Exception:
        return 0


def _cleanup_frozen_exit():
    """onefile 打包时，bootloader 父进程在部分 Windows 环境下
    于子进程退出后挂死（卡在消息等待），导致进程与 _MEI 临时目录残留。
    这里在退出前主动结束父引导进程，并用一个分离的小任务延时清理临时目录。"""
    if not getattr(sys, "frozen", False):
        return
    try:
        import ctypes
        import subprocess as _sp

        my_name = os.path.basename(sys.executable).lower()
        ppid = _parent_pid()

        # 确认父进程确实是同名的 bootloader（防止误杀）
        kill = False
        if ppid and ppid != os.getpid():
            try:
                import ctypes.wintypes as wt

                class PE(ctypes.Structure):
                    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                                ("pid", wt.DWORD),
                                ("heap", ctypes.POINTER(ctypes.c_ulong)),
                                ("mod", wt.DWORD), ("threads", wt.DWORD),
                                ("ppid", wt.DWORD), ("pri", ctypes.c_long),
                                ("flags", wt.DWORD), ("exe", wt.WCHAR * 260)]
                h = ctypes.windll.kernel32.CreateToolhelp32Snapshot(2, 0)
                e = PE(); e.dwSize = ctypes.sizeof(PE)
                ok = ctypes.windll.kernel32.Process32FirstW(h, ctypes.byref(e))
                while ok:
                    if e.pid == ppid:
                        kill = e.exe.lower() == my_name
                        break
                    ok = ctypes.windll.kernel32.Process32NextW(h, ctypes.byref(e))
                ctypes.windll.kernel32.CloseHandle(h)
            except Exception:
                pass

        if kill:
            try:
                PROCESS_TERMINATE = 0x0001
                kernel32 = ctypes.windll.kernel32
                h = kernel32.OpenProcess(PROCESS_TERMINATE, False, ppid)
                if h:
                    kernel32.TerminateProcess(h, 0)
                    kernel32.CloseHandle(h)
            except Exception:
                pass

        # 清理 onefile 解包目录（本进程退出后由分离任务删除）
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass and os.path.isdir(meipass):
            try:
                cmd = 'ping -n 4 127.0.0.1 > nul & rd /s /q "%s"' % meipass
                _sp.Popen(["cmd", "/c", cmd],
                          creationflags=0x00000008 | 0x08000000,
                          close_fds=True)
            except Exception:
                pass
    except Exception:
        pass


def _fail(msg: str):
    try:
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write("\n==== %s ====\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def already_running(port: int) -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/ping" % port,
                                    timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def run_cli(args) -> int:
    _attach_console()
    import convert
    files = []
    for f in args.cli:
        if os.path.isdir(f):
            for name in sorted(os.listdir(f)):
                if name.lower().endswith((".md", ".markdown")):
                    files.append(os.path.join(f, name))
        else:
            files.append(f)
    if not files:
        _say("没有找到待转换的 Markdown 文件")
        return 1
    fmts = [x.strip().lower() for x in (args.format or "docx").split(",") if x.strip()]
    bad = [f for f in fmts if f not in convert.FORMATS]
    if bad:
        _say("不支持的格式：%s" % ", ".join(bad))
        return 1
    total = ok = 0
    for fp in files:
        for r in convert.convert_file(fp, fmts, args.out or None,
                                      native=args.native,
                                      txt_mode=args.txt_mode,
                                      txt_encoding=args.txt_encoding):
            total += 1
            if r.ok:
                ok += 1
                _say("[OK]   %s -> %s (%s)" % (r.name, r.target, r.engine))
            else:
                _say("[FAIL] %s : %s" % (r.name, r.message))
            for w in r.warnings:
                _say("       ! %s" % w)
    _say("\n完成 %d/%d" % (ok, total))
    _cleanup_frozen_exit()
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Markdown 转 Word / WPS / TXT")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true",
                        help="不打开窗口，仅运行 HTTP 服务（测试用）")
    parser.add_argument("--web", action="store_true",
                        help="使用系统浏览器打开界面（默认是独立桌面窗口）")
    parser.add_argument("--cli", nargs="*", metavar="FILE",
                        help="命令行模式：直接转换，不启动界面")
    parser.add_argument("-f", "--format", default="docx")
    parser.add_argument("-o", "--out", default="")
    parser.add_argument("--native", action="store_true",
                        help="调用本机 Word/WPS 生成原生 .doc/.wps")
    parser.add_argument("--txt-mode", default="plain", choices=["plain", "raw"])
    parser.add_argument("--txt-encoding", default="utf-8")
    args = parser.parse_args()

    if args.cli is not None:
        return run_cli(args)

    try:
        import server

        port = args.port
        if already_running(port):
            webbrowser.open("http://127.0.0.1:%d/" % port)
            return 0

        if port:
            # 端口被别的程序占用时退让到随机端口
            import socket
            s = socket.socket()
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                port = 0
            finally:
                s.close()

        httpd, real_port = server.start_server(port)
        url = "http://127.0.0.1:%d/" % real_port
        _say("Md2docs 已启动：%s" % url)
        _fail("started %s" % url)

        if args.no_browser:
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                pass
            _cleanup_frozen_exit()
            return 0

        if args.web:
            # 强制系统浏览器模式
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                pass
            _cleanup_frozen_exit()
            return 0

        # 默认：独立桌面窗口（WebView2）
        try:
            return _run_desktop(httpd, url)
        except Exception:
            # pywebview/WebView2 不可用时回退到系统浏览器
            _fail(traceback.format_exc())
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                pass
            _cleanup_frozen_exit()
            return 0
    except Exception:
        _fail(traceback.format_exc())
        raise


def _run_desktop(httpd, url: str) -> int:
    """用 WebView2 创建独立桌面窗口（pywebview），关闭窗口即退出程序。"""
    import webview

    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    window = webview.create_window(
        "Md2docs · Markdown 转 Word / WPS / TXT",
        url,
        width=1140, height=800,
        min_size=(980, 660),
        background_color="#0f1117",
    )
    try:
        webview.start()
    except KeyboardInterrupt:
        pass
    # 窗口全部关闭：结束程序
    try:
        window.destroy()
    except Exception:
        pass
    _cleanup_frozen_exit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
