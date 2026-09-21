# -*- coding: utf-8 -*-
"""界面版式回归：圆角按钮 + 第 3 步「开始转换」按钮水平居中。

为什么需要它
------------
* 「圆角」在 Tk 里不是原生能力，是靠 Canvas 自绘实现的（``gui.RoundButton``）。
  一旦有人把 `_btn` 改回 ``tk.Button``，圆角会无声消失——外观缺陷不会被任何
  功能测试发现，所以这里把"确实是圆角多边形"变成断言。
* 「按钮居中」依赖 ``pack`` 的居中行为，很容易被后续改动悄悄破坏。
  尤其要盯住 **V-17**：把主按钮和次级控件放进同一个 ``pack`` 行时，被居中的
  只是"整行"，而按钮排在行首必然落在行的最左边——视觉上就是"按钮靠左对齐"。
  所以这里量的是**按钮自身的中心**，不是父容器的居中状态。

硬约束：必须使用**已映射**的窗口。未映射时 winfo_width() 恒为 1，
与尺寸相关的结论全都不成立（本项目踩过这个坑）。

用法：
    python tools/check_ui_layout.py

退出码：0 = 通过；1 = 失败。
"""
from __future__ import annotations

import os
import sys
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

import gui        # noqa: E402
import i18n       # noqa: E402

# 允许的居中误差（像素）。pack 居中应当是 0，留 1px 给奇数宽度的取整。
CENTER_TOL = 1


def _round_buttons(root) -> list:
    return [w for w in gui.walk_widgets(root) if isinstance(w, gui.RoundButton)]


def _margins(inner_x: int, inner_w: int, outer_w: int):
    """inner 相对 outer 的左余 / 右余 / 两者之差。"""
    left = inner_x
    right = outer_w - (inner_x + inner_w)
    return left, right, abs(left - right)


def check_rounding(app, root) -> list[str]:
    problems: list[str] = []
    buttons = _round_buttons(root)
    print("[layout] 圆角按钮数量 =", len(buttons))
    # 浏览本机文件 / 清空 / 浏览 / 开始转换 / 打开输出文件夹 / 启用 = 6 个
    if len(buttons) < 6:
        problems.append("圆角按钮少于 6 个（实际 %d），可能有按钮没走 _btn"
                        % len(buttons))

    for b in buttons:
        label = b.cget("text") or "<无文字>"
        if getattr(b, "_radius", 0) <= 0:
            problems.append("按钮「%s」圆角半径为 0" % label)
            continue
        polys = [i for i in b.find_all() if b.type(i) == "polygon"]
        if not polys:
            problems.append("按钮「%s」没有画出圆角多边形" % label)
            continue
        if not b.itemcget(polys[0], "smooth"):
            problems.append("按钮「%s」的多边形未启用平滑（不是圆角）" % label)
        if not label or label == "<无文字>":
            problems.append("按钮缺少文案")
        # 圆角矩形的点位签名：smooth 多边形靠「控制点」把四个角切掉，点位明显
        # 多于直角的 4 个。若有人换成 create_rectangle / 直角多边形，点数会塌回 4。
        raw = b.coords(polys[0])
        coords = ([float(v) for v in raw.split()] if isinstance(raw, str)
                  else [float(v) for v in raw])
        n_points = len(coords) // 2
        if n_points < 12:
            problems.append("按钮「%s」的多边形只有 %d 个点，不像圆角矩形"
                            % (label, n_points))
    return problems


def check_centering(app, root, lang: str) -> list[str]:
    """第 3 步：主按钮自身居中，且次级控件不得与按钮重叠。"""
    root.update_idletasks()
    row = app.btn_run.master                     # btn_run -> row
    bar = row.master                             # row -> bar（fill="x"）
    bw = bar.winfo_width()
    if bw <= 1:
        return ["%s：bar 宽度异常（%d），窗口可能未映射" % (lang, bw)]

    problems: list[str] = []

    # ① 主按钮居中：btn_run 的 x 是相对 row 的，须叠加 row 在 bar 里的偏移。
    px = row.winfo_x() + app.btn_run.winfo_x()
    pw = app.btn_run.winfo_width()
    left, right, delta = _margins(px, pw, bw)
    print("[layout] %s：bar=%d  按钮宽=%d  左%d 右%d  偏差=%d"
          % (lang, bw, pw, left, right, delta))
    if pw <= 1:
        problems.append("%s：按钮宽度异常（%d）" % (lang, pw))
    elif delta > CENTER_TOL:
        problems.append("%s：「开始转换」按钮未水平居中，左余 %d 右余 %d（偏差 %dpx）"
                        % (lang, left, right, delta))

    # ② 次级控件由 place 摆放，不参与 pack 布局，所以不会把按钮挤偏；
    #    但要防它们与按钮重叠——重叠了界面就看不清。
    btn_l, btn_r = px, px + pw
    out = app.btn_open_out
    out_r = row.winfo_x() + out.winfo_x() + out.winfo_width()
    prog_l = row.winfo_x() + app.prog.master.winfo_x()
    print("[layout] %s：按钮[%d,%d]  打开输出文件夹右缘=%d  进度左缘=%d"
          % (lang, btn_l, btn_r, out_r, prog_l))
    if out_r > btn_l:
        problems.append("%s：「打开输出文件夹」与「开始转换」重叠"
                        "（右缘 %d > 按钮左缘 %d）" % (lang, out_r, btn_l))
    if prog_l < btn_r:
        problems.append("%s：进度区与「开始转换」重叠"
                        "（左缘 %d < 按钮右缘 %d）" % (lang, prog_l, btn_r))
    return problems


def main() -> int:
    gui.enable_hi_dpi()
    root = tk.Tk()
    app = gui.Md2docsApp(root)
    problems: list[str] = []
    origin = i18n.current_choice()
    try:
        # 必须映射：未映射的窗口 winfo_width() 恒为 1，测不出任何版式问题
        root.deiconify()
        root.update()
        for _ in range(6):
            root.update()
            root.after(30)
        if not root.winfo_ismapped():
            print("[layout] 失败：窗口未能映射，版式结论不可信")
            return 1

        problems += check_rounding(app, root)
        for lang in ("zh", "en"):
            app.set_language(lang, persist=False)
            root.update()
            problems += check_centering(app, root, lang)
    finally:
        app.set_language(origin, persist=False)
        app.shutdown()
        try:
            root.destroy()
        except Exception:
            pass

    if problems:
        print("\n[layout] 失败，共 %d 项：" % len(problems))
        for p in problems:
            print("   -", p)
        return 1
    print("\n[layout] 通过：按钮均为圆角，「开始转换」按钮在中英两种语言下"
          "都精确居中，且与次级控件无重叠")
    return 0


if __name__ == "__main__":
    sys.exit(main())
