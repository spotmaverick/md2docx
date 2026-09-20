# -*- coding: utf-8 -*-
"""抓取指定进程标题前缀的窗口截图（开发期工具，不参与打包）。

用法：python grab.py <输出png> <标题前缀>
先置顶该窗口再抓屏，避免 PrintWindow 对非前台窗口漏绘。
"""
import ctypes
import sys
import time
from ctypes import wintypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

from PIL import ImageGrab  # noqa: E402

u = ctypes.windll.user32
out_path = sys.argv[1]
prefix = sys.argv[2] if len(sys.argv) > 2 else "Md2docs"

cands = []
EP = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def cb(h, _):
    n = u.GetWindowTextLengthW(h)
    if n:
        b = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(h, b, n + 1)
        if b.value.startswith(prefix):
            r = wintypes.RECT()
            u.GetWindowRect(h, ctypes.byref(r))
            cands.append((h, r.right - r.left, r.bottom - r.top, b.value))
    return True


u.EnumWindows(EP(cb), 0)
if not cands:
    print("NO-WINDOW")
    raise SystemExit(1)

big = [c for c in cands if c[1] > 400 and c[2] > 400]
picked = (big or cands)[0]
h = picked[0]
u.ShowWindow(h, 9)                       # SW_RESTORE
u.SetWindowPos(h, -1, 30, 16, 0, 0, 0x0040 | 0x0001)   # topmost + show
time.sleep(1.0)

r = wintypes.RECT()
u.GetWindowRect(h, ctypes.byref(r))
print("rect", r.left, r.top, r.right - r.left, r.bottom - r.top,
      "| candidates:", [(c[0], c[1], c[2]) for c in cands])
img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom))
img.save(out_path)
print("saved", out_path, img.size)
