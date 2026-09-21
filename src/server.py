# -*- coding: utf-8 -*-
"""内置 HTTP 服务：为前端界面提供文件浏览与转换能力。"""
from __future__ import annotations

import json
import os
import string
import sys
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

import convert

IDLE_TIMEOUT = 600          # 无心跳 10 分钟后自动退出，避免残留后台进程
MD_EXTS = (".md", ".markdown", ".mdown", ".mkd", ".mdtext", ".mdtxt", ".txt")

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".png": "image/png",
}


def resource_path(rel: str) -> str:
    """兼容 PyInstaller 单文件打包后的资源路径。"""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, rel)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), rel)


def default_workdir() -> str:
    try:
        docs = os.path.join(os.path.expanduser("~"), "Documents")
        if not os.path.isdir(docs):
            docs = os.path.expanduser("~")
    except Exception:
        docs = os.path.expanduser("~")
    path = os.path.join(docs, "Md2docs")
    os.makedirs(path, exist_ok=True)
    return path


class AppState:
    def __init__(self):
        self.workdir = default_workdir()
        # 纯本地应用：不设上传缓存目录，拖拽的 .md 直接在内存读取转换
        self.default_out = os.path.join(self.workdir, "转换结果")
        self.last_seen = time.time()
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.closing = False      # 收到「页面已关闭」信号，等待缓冲期结束

    def default_out_dir(self) -> str:
        """默认输出目录（供界面预填，用户可改）。"""
        os.makedirs(self.default_out, exist_ok=True)
        return self.default_out


class Handler(BaseHTTPRequestHandler):
    server_version = "Md2docs/1.0"
    state: AppState
    httpd: ThreadingHTTPServer

    # ------------------------------------------------------------------ #
    def log_message(self, fmt, *args):          # 静音
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _read_body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    # ------------------------------------------------------------------ #
    def do_GET(self):
        u = urlparse(self.path)
        path = unquote(u.path)
        self.state.last_seen = time.time()

        try:
            if path in ("/", "/index.html"):
                self._serve_file(resource_path(os.path.join("web", "index.html")))
            elif path.startswith("/assets/"):
                rel = path[len("/assets/"):].replace("/", os.sep)
                self._serve_file(resource_path(os.path.join("web", "assets", rel)))
            elif path == "/api/ping":
                self._json({"ok": True, "workdir": self.state.workdir})
            elif path == "/api/config":
                self._json(self._config())
            elif path == "/api/drives":
                self._json({"drives": list_drives()})
            elif path == "/api/browse":
                self._browse(u.query)
            else:
                self._json({"ok": False, "error": "not found"}, 404)
        except Exception:
            self._json({"ok": False, "error": traceback.format_exc()[-2000:]}, 500)

    def do_POST(self):
        u = urlparse(self.path)
        path = unquote(u.path)
        self.state.last_seen = time.time()

        try:
            body = self._read_body()
            data = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            data = {}

        try:
            if path == "/api/convert":
                self._convert(data)
            elif path == "/api/locate":
                self._locate(data)
            elif path == "/api/mkdir":
                self._mkdir(data)
            elif path == "/api/open":
                self._open(data)
            elif path == "/api/heartbeat":
                self.state.closing = False   # 页面仍活着（含刷新后的新页面）
                self._json({"ok": True})
            elif path == "/api/page-closed":
                self._page_closed()
            elif path == "/api/quit":
                self._json({"ok": True})
                threading.Thread(target=self._shutdown, daemon=True).start()
            else:
                self._json({"ok": False, "error": "not found"}, 404)
        except Exception:
            self._json({"ok": False, "error": traceback.format_exc()[-2000:]}, 500)

    # ------------------------------------------------------------------ #
    def _serve_file(self, fp: str):
        if not os.path.isfile(fp):
            self._json({"ok": False, "error": "missing " + fp}, 404)
            return
        ext = os.path.splitext(fp)[1].lower()
        with open(fp, "rb") as f:
            self._send(200, f.read(), MIME.get(ext, "application/octet-stream"))

    def _config(self):
        caps = convert.capabilities()
        return {
            "ok": True,
            "workdir": self.state.workdir,
            "default_out": self.state.default_out_dir(),
            "formats": [{"id": k, "ext": v["ext"],
                         "label": convert.format_label(k)}
                        for k, v in convert.FORMATS.items()],
            "caps": caps,
            "encodings": convert.ENCODINGS,
        }

    def _browse(self, query: str):
        from urllib.parse import parse_qs
        q = parse_qs(query)
        target = (q.get("path") or [""])[0].strip()
        kind = (q.get("kind") or ["files"])[0]

        if not target:
            self._json({"ok": True, "path": "", "parent": "",
                        "entries": [], "drives": list_drives()})
            return

        target = os.path.abspath(target)
        if not os.path.isdir(target):
            self._json({"ok": False, "error": "目录不存在"}, 400)
            return

        dirs, files = [], []
        try:
            for name in sorted(os.listdir(target), key=lambda s: s.lower()):
                full = os.path.join(target, name)
                if os.path.isdir(full):
                    dirs.append({"name": name, "path": full, "is_dir": True,
                                 "size": 0, "mtime": 0})
                elif kind == "files":
                    ext = os.path.splitext(name)[1].lower()
                    if ext in MD_EXTS:
                        try:
                            st = os.stat(full)
                            size, mtime = st.st_size, int(st.st_mtime)
                        except OSError:
                            size, mtime = 0, 0
                        files.append({"name": name, "path": full, "is_dir": False,
                                      "size": size, "mtime": mtime})
        except PermissionError:
            self._json({"ok": False, "error": "没有访问权限"}, 403)
            return

        parent = os.path.dirname(target)
        if not parent or parent == target:
            parent = ""
        self._json({"ok": True, "path": target, "parent": parent,
                    "entries": dirs + files,
                    "drives": list_drives()})

    def _rename_like(self, target: str, stem: str) -> str:
        """把输出文件重命名为指定 stem，重名时追加 (1)(2)..."""
        d = os.path.dirname(target)
        ext = os.path.splitext(target)[1]
        new = os.path.join(d, stem + ext)
        if os.path.abspath(new) == os.path.abspath(target):
            return target
        i = 1
        while os.path.exists(new):
            new = os.path.join(d, "%s(%d)%s" % (stem, i, ext))
            i += 1
        try:
            os.rename(target, new)
        except OSError:
            return target
        return new

    def _page_closed(self):
        """浏览器页面关闭：留 20 秒缓冲，期间若有新页面心跳则取消退出。

        界面已移除「退出程序」按钮，关闭标签页即视为使用结束；
        刷新页面会在 20 秒内重新心跳，不会误退出。
        """
        self.state.closing = True
        state = self.state

        def check():
            if state.closing:
                try:
                    self._cleanup_and_exit()
                except Exception:
                    os._exit(0)

        t = threading.Timer(20.0, check)
        t.daemon = True
        t.start()
        self._json({"ok": True})

    def _cleanup_and_exit(self):
        """退出前清理（onefile 引导父进程在本机会挂死，需主动结束）。"""
        try:
            import app as _app
            _app._cleanup_frozen_exit()
        except Exception:
            pass
        os._exit(0)

    def _locate(self, data: dict):
        """拖入的 .md 自动定位源目录。

        浏览器不给拖放文件的磁盘路径，但文件通常来自某个已打开的资源管理器窗口，
        因此遍历这些窗口的当前目录，找到同名且真实存在的文件即视为源文件。
        找不到时返回空路径，前端降级为"内存文件"。
        """
        name = os.path.basename((data.get("name") or "").strip())
        if not name:
            self._json({"ok": True, "path": ""})
            return
        result: dict = {"path": ""}
        err: list = []

        def worker():
            try:
                import pythoncom
                import win32com.client as wc
                pythoncom.CoInitialize()
                try:
                    # 1) 优先「最近激活」的资源管理器目录：用户刚操作过的窗口
                    #    就是拖出文件的窗口，同名文件必须匹配它而不是旧目录
                    recent = _ACTIVE_EXPLORER_DIR[0]
                    if recent:
                        fp = os.path.join(recent, name)
                        if os.path.isfile(fp):
                            result["path"] = os.path.abspath(fp)
                            return
                    # 2) 兜底：遍历所有窗口目录，命中即返回
                    shell = wc.Dispatch("Shell.Application")
                    for w in shell.Windows():
                        try:
                            if not _is_explorer(w):
                                continue
                            d = _url_to_path(w.LocationURL)
                            if not d:
                                continue
                            fp = os.path.join(d, name)
                            if os.path.isfile(fp):
                                result["path"] = os.path.abspath(fp)
                                return
                        except Exception:
                            continue
                finally:
                    try:
                        pythoncom.CoUninitialize()
                    except Exception:
                        pass
            except Exception as exc:
                err.append("%s: %s" % (type(exc).__name__, exc))

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        t.join(timeout=5)
        self._json({"ok": True, "path": result.get("path", ""),
                    "reason": err[0] if err and not result.get("path") else ""})

    def _mkdir(self, data: dict):
        parent = os.path.abspath(data.get("path") or self.state.workdir)
        name = _safe_name(data.get("name") or "新建文件夹")
        fp = os.path.join(parent, name)
        i = 1
        while os.path.exists(fp):
            fp = os.path.join(parent, "%s(%d)" % (name, i))
            i += 1
        os.makedirs(fp, exist_ok=True)
        self._json({"ok": True, "path": fp})

    def _open(self, data: dict):
        fp = data.get("path") or ""
        if not fp:
            self._json({"ok": False, "error": "空路径"})
            return
        try:
            if os.path.isdir(fp):
                os.startfile(fp)                     # noqa: S606
            elif os.path.isfile(fp):
                os.startfile(fp)                     # noqa: S606
            else:
                self._json({"ok": False, "error": "路径不存在"})
                return
            self._json({"ok": True})
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)})

    def _convert(self, data: dict):
        raw_files = data.get("files") or []
        fmts = [f for f in (data.get("formats") or []) if f in convert.FORMATS]
        out_dir = (data.get("out_dir") or "").strip()
        native = bool(data.get("native"))

        # files 支持两种形态：
        #   "C:\\x\\a.md" 或 {"path": "..."}   —— 浏览选择的真实文件
        #   {"name": "a.md", "content": "..."} —— 拖拽的 .md（内存内容，不落盘）
        items = []
        for f in raw_files:
            if isinstance(f, dict):
                items.append(f)
            elif isinstance(f, str) and f:
                items.append({"path": f})

        if not items:
            self._json({"ok": False, "error": "没有待转换的文件"})
            return
        if not fmts:
            self._json({"ok": False, "error": "未选择输出格式"})
            return

        results = []
        for item in items:
            path = item.get("path") or ""
            name = item.get("name") or os.path.basename(path) or "未命名.md"
            tmp_md = ""
            try:
                if path:
                    if not os.path.isfile(path):
                        results.append({"source": path, "name": os.path.basename(path),
                                        "fmt": "", "ok": False,
                                        "message": "文件不存在", "engine": "",
                                        "target": "", "size": 0, "warnings": []})
                        continue
                    fp = path
                else:
                    # 拖拽的 .md：内容写入一次性临时文件，转换后立即删除
                    content = item.get("content") or ""
                    if content.startswith("\ufeff"):
                        content = content[1:]
                    fd, tmp_md = tempfile.mkstemp(suffix=".md", prefix="md2docs_")
                    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                        f.write(content)
                    fp = tmp_md

                rs = convert.convert_file(
                    fp, fmts, out_dir or None,
                    native=native,
                    txt_mode=data.get("txt_mode") or "plain",
                    txt_encoding=data.get("txt_encoding") or "utf-8",
                    overwrite=bool(data.get("overwrite", True)),
                )
                if not path:
                    # 拖入的文件：输出文件名以用户提供的 name 为准，
                    # 而不是临时 .md 的文件名
                    out_stem = os.path.splitext(os.path.basename(name))[0]
                    for r in rs:
                        if r.ok and r.target:
                            r.target = self._rename_like(r.target, out_stem)
                for r in rs:
                    results.append({
                        "source": r.source, "name": r.name, "fmt": r.fmt,
                        "target": r.target, "ok": r.ok, "message": r.message,
                        "engine": r.engine, "size": r.size,
                        "warnings": r.warnings,
                    })
            except Exception as exc:
                results.append({"source": path or name, "name": name,
                                "fmt": "", "ok": False,
                                "message": "%s: %s" % (type(exc).__name__, exc),
                                "engine": "", "target": "", "size": 0,
                                "warnings": []})
            finally:
                if tmp_md:
                    try:
                        if os.path.isfile(tmp_md):
                            os.remove(tmp_md)
                    except OSError:
                        pass

        dirs = sorted({os.path.dirname(r["target"]) for r in results
                       if r.get("target")})
        self._json({"ok": True, "results": results, "out_dirs": dirs})

    def _shutdown(self):
        """优雅退出：先停 HTTP 循环让主线程自然返回，
        解释器正常收尾（PyInstaller onefile 的父引导进程只有在
        子进程正常退出后才会清理临时目录并退出）。"""
        try:
            self.state.stop.set()
        except Exception:
            pass
        try:
            self.httpd.shutdown()
        except Exception:
            pass
        # 兜底：万一 5 秒后仍未退出，强制结束
        threading.Timer(5.0, os._exit, args=[0]).start()


# --------------------------------------------------------------------------- #
# 最近激活的资源管理器目录（用于拖入文件的自动定位：用户最后操作的窗口
# 通常就是拖出文件的窗口，同名文件应优先匹配它，避免定位到旧目录）
_ACTIVE_EXPLORER_DIR: list[str] = [""]


def _watch_active_explorer(stop: threading.Event):
    """后台监视：每 1.5 秒记录前台资源管理器窗口的当前目录。

    用户从资源管理器拖出文件前必然先激活过该窗口，据此可得最准确的源目录。
    """
    try:
        import ctypes
        import pythoncom
        import win32com.client as wc
        user32 = ctypes.windll.user32
        get_fg = user32.GetForegroundWindow
        get_class = user32.GetClassNameW
        buf = ctypes.create_unicode_buffer(128)
        pythoncom.CoInitialize()
        shell = wc.Dispatch("Shell.Application")
        while not stop.is_set():
            try:
                hwnd = get_fg()
                if hwnd and get_class(hwnd, buf, 128) and buf.value == "CabinetWClass":
                    for w in shell.Windows():
                        try:
                            if int(w.HWND) == int(hwnd):
                                d = _url_to_path(w.LocationURL)
                                if d:
                                    _ACTIVE_EXPLORER_DIR[0] = d
                                break
                        except Exception:
                            continue
            except Exception:
                pass
            stop.wait(1.5)
    except Exception:
        pass
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def _is_explorer(window) -> bool:
    """判断 Shell 窗口是不是文件资源管理器。"""
    try:
        name = str(window.Name or "")
    except Exception:
        return False
    if "explorer" in name.lower() or "资源管理器" in name:
        return True
    try:
        # 部分版本 Name 为空，退而判断进程
        return "explorer.exe" in str(window.FullName or "").lower()
    except Exception:
        return False


def _url_to_path(url: str) -> str:
    """file:///C:/a/b -> C:\\a\\b；非本地路径返回空串。"""
    if not url or not str(url).lower().startswith("file:"):
        return ""
    from urllib.parse import unquote
    p = str(url)[5:].lstrip("/")
    p = unquote(p).replace("/", os.sep)
    try:
        p = os.path.abspath(p)
    except Exception:
        return ""
    return p if os.path.isdir(p) else ""


def list_drives() -> list[str]:
    drives = []
    if os.name == "nt":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(256)
            n = ctypes.windll.kernel32.GetLogicalDriveStringsW(256, buf)
            raw = buf[:n].split("\x00")
            drives = [d for d in raw if d]
        except Exception:
            drives = []
    if not drives:
        drives = [d + ":\\" for d in string.ascii_uppercase
                  if os.path.isdir(d + ":\\")]
    return drives


def _safe_name(name: str) -> str:
    bad = '<>:"/\\|?*'
    for ch in bad:
        name = name.replace(ch, "_")
    return name.strip().strip(".") or "未命名"


def _urlquote(s: str) -> str:
    from urllib.parse import quote
    return quote(s)


# --------------------------------------------------------------------------- #
def idle_watchdog(httpd: ThreadingHTTPServer, state: AppState, stop: threading.Event):
    while not stop.is_set():
        stop.wait(30)
        if stop.is_set():
            break
        if time.time() - state.last_seen > IDLE_TIMEOUT:
            try:
                httpd.shutdown()
            except Exception:
                pass
            os._exit(0)
            return


def start_server(port: int = 0) -> tuple[ThreadingHTTPServer, int]:
    state = AppState()

    class _Handler(Handler):
        pass

    _Handler.state = state
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    _Handler.httpd = httpd
    httpd.daemon_threads = True

    threading.Thread(target=idle_watchdog, args=(httpd, state, state.stop),
                     daemon=True).start()
    threading.Thread(target=_watch_active_explorer, args=(state.stop,),
                     daemon=True).start()
    return httpd, httpd.server_address[1]
