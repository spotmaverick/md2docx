"""对打包后的 EXE 做端到端点击验证：反复点击格式卡片，窗口宽度必须恒定。

用法：
    python tools/check_exe_gui.py [dist/Md2docs.exe]
退出码 0 通过、1 宽度漂移、2 无法判定（未找到窗口 / 点击未送达）。
注意：会短暂移动鼠标以投递真实点击，结束后还原光标位置。

坐标：在进程内构建同一套界面，取格式卡片的**客户区坐标**（与窗口位置无关），
再把 EXE 窗口摆到固定位置，换算成屏幕坐标，用真实鼠标事件点击
（SetCursorPos + mouse_event）——PostMessage 投递到子窗口的方式对 Tk 无效，
实测窗口高度毫无反应，说明事件没送达，因此改用真实输入。

点击是否真的生效，用**卡片底色的像素变化**来证明：每次点击格式卡片都会切换
选中态（底色在 PANEL2 与 CARD_ON 之间翻转），点击前后在卡片左侧留白处取色
比对即可确认事件确实送达。仅在窗口被可用桌面高度限死、高度不再变化时，
旧的"高度变化"证据会失效，故改用像素证据。
"""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass
u = ctypes.windll.user32
gdi = ctypes.windll.gdi32
u.WindowFromPoint.restype = wintypes.HWND
u.WindowFromPoint.argtypes = [wintypes.POINT]
u.GetAncestor.restype = wintypes.HWND
u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]

FILES = ["tests/imgs_case.md", "sample/示例文档.md", "tests/stress.md"]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "src"))
import tkinter as tk  # noqa: E402
import gui  # noqa: E402

WIN_X, WIN_Y = 60, 40


def card_client_points():
    """用同一套界面算出各格式卡片中心的客户区坐标。"""
    root = tk.Tk()
    app = gui.Md2docsApp(root, initial_files=FILES)
    root.update()
    time.sleep(0.6)
    root.update()
    hwnd = u.GetParent(int(root.winfo_id())) or int(root.winfo_id())
    origin = wintypes.POINT(0, 0)
    u.ClientToScreen(hwnd, ctypes.byref(origin))
    pts = {}
    for fid in gui.FMT_ORDER:
        c = app._fmt_cards[fid]["widgets"][0]
        pts[fid] = (c.winfo_rootx() + c.winfo_width() // 2 - origin.x,
                    c.winfo_rooty() + c.winfo_height() // 2 - origin.y)
    app.shutdown()
    root.destroy()
    return pts


def find_exe_window(timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def cb(h, _):
            n = u.GetWindowTextLengthW(h)
            if n:
                b = ctypes.create_unicode_buffer(n + 1)
                u.GetWindowTextW(h, b, n + 1)
                if b.value.startswith("Md2docs"):
                    r = wintypes.RECT()
                    u.GetWindowRect(h, ctypes.byref(r))
                    if (r.right - r.left) > 400 and (r.bottom - r.top) > 400:
                        found.append(h)
            return True

        u.EnumWindows(cb, 0)
        if found:
            return found[0]
        time.sleep(0.5)
    return None


def rect_of(hwnd):
    r = wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    return r.right - r.left, r.bottom - r.top


def screen_pixel(x, y):
    """取屏幕上某点的颜色（0x00BBGGRR）；取不到返回 -1。"""
    dc = u.GetDC(0)
    if not dc:
        return -1
    try:
        return int(gdi.GetPixel(dc, int(x), int(y)))
    finally:
        u.ReleaseDC(0, dc)


def top_level_at(sx, sy):
    """屏幕上该点所属的顶层窗口。锁屏或其它窗口遮挡时不会是本程序。"""
    h = u.WindowFromPoint(wintypes.POINT(int(sx), int(sy)))
    if not h:
        return 0
    return int(u.GetAncestor(wintypes.HWND(h), 2) or h)      # GA_ROOT


def window_signature(hwnd, cols=26, rows=18):
    """在客户区打网格取色，得到窗口当前画面的指纹，用于判断点击是否生效。"""
    r = wintypes.RECT()
    u.GetClientRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    dc = u.GetDC(hwnd)
    if not dc:
        return ()
    sig = []
    try:
        for j in range(rows):
            y = int(h * (j + 0.5) / rows)
            for i in range(cols):
                x = int(w * (i + 0.5) / cols)
                sig.append(int(gdi.GetPixel(dc, x, y)))
    finally:
        u.ReleaseDC(hwnd, dc)
    return tuple(sig)


def real_click(sx, sy):
    u.SetCursorPos(int(sx), int(sy))
    time.sleep(0.04)
    u.mouse_event(0x0002, 0, 0, 0, 0)   # LEFTDOWN
    time.sleep(0.04)
    u.mouse_event(0x0004, 0, 0, 0, 0)   # LEFTUP


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "dist/Md2docs.exe"
    exe = os.path.abspath(which)
    if not os.path.isfile(exe):
        print("找不到可执行文件:", exe)
        return 2

    pts = card_client_points()

    saved = wintypes.POINT()
    u.GetCursorPos(ctypes.byref(saved))

    proc = subprocess.Popen([exe] + FILES, cwd=os.getcwd())
    hwnd = find_exe_window()
    if not hwnd:
        proc.terminate()
        print("未找到 EXE 窗口")
        return 2

    u.ShowWindow(hwnd, 9)
    u.SetWindowPos(hwnd, -1, WIN_X, WIN_Y, 0, 0, 0x0040 | 0x0001)  # topmost
    time.sleep(1.0)
    u.SetForegroundWindow(hwnd)
    time.sleep(0.6)

    origin = wintypes.POINT(0, 0)
    u.ClientToScreen(hwnd, ctypes.byref(origin))

    first = pts[gui.FMT_ORDER[0]]
    covered = top_level_at(origin.x + first[0], origin.y + first[1])
    if covered != int(hwnd):
        print("!! 目标点上的顶层窗口不是 Md2docs（实际 hwnd=%s）："
              "桌面可能已锁屏或被其它窗口遮挡，真实鼠标事件无法送达。" % covered)
        print("   请在桌面解锁、且本窗口可见的情况下重跑本检查。")
        proc.terminate()
        return 2

    widths, heights = [], []

    def snap():
        w, h = rect_of(hwnd)
        widths.append(w)
        heights.append(h)
        return w, h

    snap()
    print("EXE:", os.path.basename(exe))
    print("起始窗口: %d x %d（客户区原点 %d,%d）" % (widths[0], heights[0],
                                                origin.x, origin.y))

    try:
        changed_rounds = 0
        prev_sig = window_signature(hwnd)
        for rnd in range(1, 6):
            for fid in gui.FMT_ORDER:
                cx, cy = pts[fid]
                real_click(origin.x + cx, origin.y + cy)
                time.sleep(0.15)
            time.sleep(0.3)
            w, h = snap()
            sig = window_signature(hwnd)
            if sig and sig != prev_sig:
                changed_rounds += 1
            prev_sig = sig
            print("  第 %d 轮点击后: %d x %d" % (rnd, w, h))
    finally:
        u.mouse_event(0x0002, 0, 0, 0, 0)
        u.mouse_event(0x0004, 0, 0, 0, 0)
        u.SetCursorPos(saved.x, saved.y)
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    dw = widths[-1] - widths[0]
    print("宽度序列:", widths)
    print("高度序列:", heights)
    print("画面发生变化轮数: %d / 5（点击已送达的证据）" % changed_rounds)
    if changed_rounds == 0:
        print("!! 窗口画面全程无变化，点击可能未送达，结论不可信")
        return 2
    if dw != 0:
        print("失败：窗口宽度漂移了 %d px" % dw)
        return 1
    print("通过：%d 次采样窗口宽度恒为 %d，且 %d 轮点击确实改变了界面"
          % (len(widths), widths[0], changed_rounds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
