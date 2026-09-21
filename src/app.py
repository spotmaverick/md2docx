# -*- coding: utf-8 -*-
"""Md2docs 启动入口。

两种运行方式：
* 图形界面（默认）：原生 Tkinter 窗口，不使用任何 Web 技术；
  支持把 .md 文件直接拖到 EXE 图标上或「发送到」，路径经命令行传入。
* 命令行（--cli）：批量转换，便于脚本调用。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback

import i18n
import settings


def _log_path() -> str:
    base = os.path.join(os.path.expanduser("~"), "Documents", "Md2docs")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "md2docs.log")


def _make_output_safe():
    """把标准输出/错误流调成"有损"模式：宁可少几个字符，也不能让程序倒在这儿。

    为什么必须做
    ------------
    Windows 中文环境的控制台与管道默认用 GBK(936)。一旦输出的字符 GBK 打不出，
    ``print`` 就抛 ``UnicodeEncodeError``，异常一路冒到 main 的兜底分支，弹出
    "启动失败"模态框——``--selftest`` 只是跑个自检，却被一个符号带崩，报错信息
    与真实原因毫无关联。

    只放宽 ``errors``、**不动 encoding**：中文仍按控制台自身的编码正确显示，
    只有确实打不出的字符退化成 ``?``。

    ⚠️ 不能依赖 ``PYTHONUTF8`` / ``PYTHONIOENCODING``：实测这两个变量对本机
    打包出的 EXE 不生效（同样一份环境，venv 里的 python 是 ``utf8_mode=1``，
    而 ``dist/Md2docs.exe`` 仍按 GBK 输出并崩溃），所以必须由程序自己兜底。
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass


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
            sys.stdout = open("CONOUT$", "w", buffering=1, errors="replace")
        except Exception:
            pass
        try:
            sys.stderr = open("CONOUT$", "w", buffering=1, errors="replace")
        except Exception:
            pass
    except Exception:
        pass
    _make_output_safe()


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


def _cleanup_frozen_exit(code: int = 0):
    """onefile 打包时，bootloader 父进程在部分 Windows 环境下
    于子进程退出后挂死（卡在消息等待），导致进程与 _MEI 临时目录残留。
    这里在退出前主动结束父引导进程，并用一个分离的小任务延时清理临时目录。

    ``code`` 必须传本进程的退出码：调用方（脚本 / 命令行）等到的是**引导父进程**
    的退出码，而我们是用 ``TerminateProcess`` 强杀它的——不给码就等于把退出码
    抹成 0，"转换失败"从此不可被发现。
    """
    # 先冲缓冲：重定向到文件/管道时标准输出是块缓冲的，而这里之后会强杀父进程
    # 并让进程很快结束，不冲的话最后几行会丢在缓冲区里。
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        try:
            stream.flush()
        except Exception:
            pass

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
                    # 带上本进程的退出码，别让强杀把失败码抹成 0
                    kernel32.TerminateProcess(h, int(code) & 0xFFFFFFFF)
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


def _fatal(msg: str, headless: bool = False) -> int:
    """出错兜底：日志必写；**模态框只在图形界面模式下弹**，返回统一的失败码。

    ``--cli`` / ``--selftest`` / ``--diag`` 是给脚本与回归工具用的入口，弹一个
    要人点"确定"的模态框会把调用方直接卡死（CI、自动化脚本都吃这一套）。
    这类入口只写日志与控制台。

    注意返回值：调用方直接 ``return _fatal(...)``，所以这里必须给出失败码，
    否则 exit code 会变成 0——脚本就再也判断不出转换到底成没成。
    """
    _fail(msg)
    if headless:
        _say(msg)
        return 1
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None, msg[-1500:], i18n.t("app.fatal_title"), 0x10)
    except Exception:
        pass
    return 1


# --------------------------------------------------------------------------- #
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
        _say(i18n.t("cli.no_files"))
        return 1
    fmts = [x.strip().lower() for x in (args.format or "docx").split(",") if x.strip()]
    bad = [f for f in fmts if f not in convert.FORMATS]
    if bad:
        _say(i18n.t("cli.bad_format", list=", ".join(bad)))
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
    _say("\n" + i18n.t("cli.done", ok=ok, total=total))
    # 收尾（含冲缓冲与 onefile 清理）统一由 main 的 finally 负责，这里不再重复
    return 0 if ok else 1


def _existing_files(paths) -> list[str]:
    """命令行 /「发送到」传入的文件，过滤出真实存在的路径。"""
    out = []
    for p in paths or []:
        try:
            ap = os.path.abspath(p)
        except Exception:
            continue
        if os.path.isfile(ap) or os.path.isdir(ap):
            out.append(ap)
    return out


def _peek_lang(argv) -> str | None:
    """在 argparse 之前嗅探 --lang。

    帮助文本本身就是按当前语言生成的，所以必须先定语言再建解析器。
    返回 None 表示命令行没有显式指定。
    """
    for i, a in enumerate(argv):
        if a == "--lang":
            return argv[i + 1] if i + 1 < len(argv) else ""
        if a.startswith("--lang="):
            return a.split("=", 1)[1]
    return None


def main() -> int:
    _make_output_safe()

    # 命令行显式指定 > 上次手动选择 > 跟随系统
    raw = _peek_lang(sys.argv[1:])
    i18n.setup(raw if raw is not None else settings.get("lang", "auto"))

    parser = argparse.ArgumentParser(
        description=i18n.t("cli.desc", title=i18n.t("app.tagline")))
    parser.add_argument("files", nargs="*", metavar="FILE",
                        help=i18n.t("cli.files_help"))
    parser.add_argument("--cli", nargs="*", metavar="FILE",
                        help=i18n.t("cli.cli_help"))
    parser.add_argument("-f", "--format", default="docx",
                        help=i18n.t("cli.format_help"))
    parser.add_argument("-o", "--out", default="",
                        help=i18n.t("cli.out_help"))
    parser.add_argument("--native", action="store_true",
                        help=i18n.t("cli.native_help"))
    parser.add_argument("--txt-mode", default="plain", choices=["plain", "raw"])
    parser.add_argument("--txt-encoding", default="utf-8")
    parser.add_argument("--lang", default=None, choices=["auto", "zh", "en"],
                        help=i18n.t("cli.lang_help"))
    parser.add_argument("--selftest", action="store_true",
                        help=i18n.t("cli.selftest_help"))
    parser.add_argument("--diag", action="store_true",
                        help=i18n.t("cli.diag_help"))
    args = parser.parse_args()

    # 给脚本 / 回归工具用的三个入口：出错只写日志与控制台，不弹模态框
    headless = args.cli is not None or args.selftest or args.diag

    rc = 0
    try:
        if args.cli is not None:
            rc = run_cli(args)
        else:
            import gui
            if args.diag:
                _attach_console()
                rc = gui.diagnose()
            elif args.selftest:
                _attach_console()
                # 带文件参数时顺带跑一次真实转换，用于验证转换线程与结果表
                files = _existing_files(args.files)
                rc = gui.selftest(files[0] if files else None,
                                  args.out or None)
            else:
                rc = gui.run(initial_files=_existing_files(args.files))
    except Exception:
        rc = _fatal(traceback.format_exc(), headless=headless)
    finally:
        # 退出码要显式交给引导父进程带出去（见 _cleanup_frozen_exit）
        _cleanup_frozen_exit(rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
