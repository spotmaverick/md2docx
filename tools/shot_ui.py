# -*- coding: utf-8 -*-
"""开发期：把界面渲染成 PNG，用于人眼核对外观。

用 PrintWindow + PW_RENDERFULLCONTENT 直接取窗口位图——不依赖窗口在前台，
桌面被 Windows 聚焦全屏层遮挡时同样有效（ImageGrab 那种抓屏方式会拍到遮挡层）。

用法：python tools/shot_ui.py <输出目录>
"""
from __future__ import annotations

import ctypes
import os
import sys
import tkinter as tk
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

import gui        # noqa: E402
import i18n       # noqa: E402
from PIL import Image  # noqa: E402

u = ctypes.windll.user32
gdi = ctypes.windll.gdi32


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def capture(hwnd: int) -> Image.Image:
    rect = wintypes.RECT()
    if not u.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError("GetWindowRect 失败")
    w, h = rect.right - rect.left, rect.bottom - rect.top
    hdc = u.GetWindowDC(hwnd)
    mem = gdi.CreateCompatibleDC(hdc)
    bmp = gdi.CreateCompatibleBitmap(hdc, w, h)
    gdi.SelectObject(mem, bmp)
    # 2 = PW_RENDERFULLCONTENT：即使窗口被遮挡也能渲染出内容
    if not u.PrintWindow(hwnd, mem, 2):
        u.PrintWindow(hwnd, mem, 0)
    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = w
    info.bmiHeader.biHeight = -h          # 负高度 = 自上而下
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(info), 0)
    gdi.DeleteObject(bmp)
    gdi.DeleteDC(mem)
    u.ReleaseDC(hwnd, hdc)
    return Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)


def main() -> int:
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "tests")
    os.makedirs(out_dir, exist_ok=True)
    samples = [os.path.join(ROOT, "sample", "示例文档.md"),
               os.path.join(ROOT, "tests", "imgs_case.md")]
    files = [p for p in samples if os.path.isfile(p)]

    gui.enable_hi_dpi()
    root = tk.Tk()
    app = gui.Md2docsApp(root, initial_files=files)
    origin = i18n.current_choice()
    try:
        root.update()
        for _ in range(3):
            root.update_idletasks()
            root.update()
        # 展开一个折叠区，顺带展示折叠区里的圆角小按钮
        app.fold_out.set(True)
        root.update()
        hwnd = u.GetParent(int(root.winfo_id())) or int(root.winfo_id())
        for lang in ("zh", "en"):
            app.set_language(lang, persist=False)
            root.update()
            img = capture(hwnd)
            path = os.path.join(out_dir, "ui_%s.png" % lang)
            img.save(path)
            print("[shot] %s  %s  (%dx%d)" % (lang, path, img.width, img.height))
    finally:
        app.set_language(origin, persist=False)
        app.shutdown()
        try:
            root.destroy()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
