# -*- coding: utf-8 -*-
"""可选的「高质量模式」：调用本机 Word / WPS 的 COM 接口导出原生 .doc / .wps。

未安装 Word / WPS、或未勾选该选项时，全部回退到内置 RTF 渲染器，不影响可用性。
"""
from __future__ import annotations

import os
import threading

# Word 另存为格式常量
WD_FORMAT_DOC = 0        # .doc（Word 97-2003）
WD_FORMAT_DOCX = 16      # .docx
WD_FORMAT_RTF = 6

# WPS 各版本注册名不同，多留几个候选项
WORD_PROGIDS = ("Word.Application", "Word.Application.16",
                "Word.Application.15", "Word.Application.14")
WPS_PROGIDS = ("KWPS.Application", "KWPS.Application.9",
               "WPS.Application", "Kingsoft.WPS.Application")

_COM_TIMEOUT = 120


def _com_available() -> bool:
    try:
        import pythoncom  # noqa: F401
        import win32com.client  # noqa: F401
    except Exception:
        return False
    return True


def _local_server_exe(progid: str) -> str:
    """解析 ProgID 对应的 COM 本地服务程序路径。

    只读注册表不启动任何进程。拿不到 CLSID 或 LocalServer32 时返回空串。
    WPS 安装时会“劫持”标准 Word.Application ProgID，把它的 LocalServer32
    指向自己的 wps.exe——因此必须靠实际 exe 归属来判定，而不是 ProgID。
    """
    import winreg
    # 1) ProgID -> CLSID（HKCR\<ProgID>\CLSID 默认值；pywin32 没有现成 API）
    clsid = ""
    for view in (0, winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid + r"\CLSID",
                                0, winreg.KEY_READ | view) as k:
                clsid, _ = winreg.QueryValueEx(k, "")
        except OSError:
            continue
        if clsid:
            break
    clsid = str(clsid or "").strip("{}")
    if not clsid:
        return ""
    # 2) CLSID -> LocalServer32（多视图）
    for view in (0, winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Classes\CLSID\{%s}\LocalServer32" % clsid,
                0, winreg.KEY_READ | view)
        except OSError:
            continue
        try:
            exe, _ = winreg.QueryValueEx(key, "")
        finally:
            winreg.CloseKey(key)
        if exe:
            return exe
    return ""


def _classify(exe: str) -> str:
    """按实际程序路径判断归属：'word' / 'wps' / ''（未知）。"""
    low = (exe or "").lower().replace("/", "\\")
    base = low.split("\\")[-1] or ""
    if base == "winword.exe":
        return "word"
    if "kingsoft" in low or "wps" in low or base in ("wps.exe", "et.exe", "wpp.exe"):
        return "wps"
    return ""


def detect_all() -> dict:
    """检测 Word / WPS 是否真实可用，并给出依据。

    关键：WPS 会注册 Word.Application 兼容 ProgID，只看 ProgID 会把 WPS
    误报成 Word。这里逐个解析 LocalServer32 的实际程序归属来判定。
    """
    if not _com_available():
        return {"word": False, "wps": False, "word_id": "", "wps_id": "",
                "reason": "未安装 pywin32"}

    word_ids, wps_ids = [], []
    for progid in WORD_PROGIDS:
        kind = _classify(_local_server_exe(progid))
        if kind == "word":
            word_ids.append(progid)
        elif kind == "wps":
            wps_ids.append(progid)
    # WPS 原生 ProgID 优先，再算上被 WPS 劫持的 Word.Application
    for progid in WPS_PROGIDS:
        if _classify(_local_server_exe(progid)) == "wps":
            wps_ids.insert(0, progid)

    return {
        "word": bool(word_ids),
        "wps": bool(wps_ids),
        "word_id": word_ids[0] if word_ids else "",
        "wps_id": wps_ids[0] if wps_ids else "",
        "reason": "",
    }


def has_word() -> bool:
    return detect_all()["word"]


def has_wps() -> bool:
    return detect_all()["wps"]


def save_as(src_path: str, out_path: str, progids=None) -> tuple[bool, str]:
    """把 src_path（docx）用本机 Office 另存为 out_path。

    返回 (是否成功, 说明)。失败时调用方回退到 RTF。
    """
    ext = os.path.splitext(out_path)[1].lower()
    if progids is None:
        if ext == ".wps":
            progids = WPS_PROGIDS + WORD_PROGIDS
        else:
            progids = WORD_PROGIDS + WPS_PROGIDS
    else:
        progids = tuple(progids)

    result: dict = {"ok": False, "msg": "未执行"}

    def worker():
        try:
            result.update(_do_save(src_path, out_path, progids))
        except Exception as exc:  # pragma: no cover
            result.update({"ok": False, "msg": "%s: %s" % (type(exc).__name__, exc)})

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout=_COM_TIMEOUT)
    if t.is_alive():
        return False, "转换超时（本机 Office 无响应）"
    return bool(result.get("ok")), str(result.get("msg", ""))


def _do_save(src_path: str, out_path: str, progids) -> dict:
    import os as _os
    import pythoncom
    import win32com.client as wc

    pythoncom.CoInitialize()
    app = None
    doc = None
    errors = []
    try:
        # 逐个尝试候选 ProgID，第一个能启动的就用来转换
        used = ""
        for progid in progids:
            try:
                app = wc.DispatchEx(progid)
                used = progid
                break
            except Exception as exc:
                errors.append("%s: %s" % (progid, exc))
                app = None
        if app is None:
            return {"ok": False, "msg": "；".join(errors[:2]) or "未找到可用的 Office"}

        try:
            app.Visible = False
        except Exception:
            pass
        try:
            app.DisplayAlerts = 0
        except Exception:
            pass

        doc = app.Documents.Open(_os.path.abspath(src_path),
                                 ReadOnly=True,
                                 AddToRecentFiles=False)
        ext = _os.path.splitext(out_path)[1].lower()
        target = _os.path.abspath(out_path)
        if ext == ".wps":
            # WPS 依据扩展名自行选择格式
            try:
                doc.SaveAs2(target)
            except Exception:
                doc.SaveAs(target)
        else:
            fmt = {".doc": WD_FORMAT_DOC, ".docx": WD_FORMAT_DOCX}.get(ext)
            try:
                if fmt is None:
                    doc.SaveAs2(target)
                else:
                    doc.SaveAs2(target, FileFormat=fmt)
            except Exception:
                doc.SaveAs(target)
        ok = _os.path.isfile(target) and _os.path.getsize(target) > 0
        return {"ok": ok, "msg": used}
    except Exception as exc:
        return {"ok": False, "msg": "%s: %s" % (type(exc).__name__, exc)}
    finally:
        try:
            if doc is not None:
                doc.Close(False)
        except Exception:
            pass
        try:
            if app is not None:
                app.Quit()
        except Exception:
            pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass
