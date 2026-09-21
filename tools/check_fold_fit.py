# -*- coding: utf-8 -*-
"""高度余量回归：折叠区全展开时，窗口是否仍然放得下。

为什么需要它
------------
界面「单页无滚动」，内容再高也不能出现滚动条。``gui.Md2docsApp._autosize()``
在内容过高时会把两张表逐步压缩来腾空间（下限各 2 行），所以**默认态测不出问题**——
必须把三个折叠区全部展开，才能看到真实的高度峰值。

这个断言不是假想出来的：把「开始转换」和次级控件拆成两行时，默认态只从 911 涨到
952（看着还够），但折叠区全展开后 main_req 冲到 971(zh)/992(en)，
而两张表早已压到 2 行下限、再也腾不出空间——**内容直接顶破可用高度**。

判据：默认态与"折叠区全展开"态的 main_req 都必须 ≤ avail，且页脚完整可见。
额外：若结果表在展开态已被压到 2 行下限，说明余量已用尽，输出一行提醒（不算失败）。

硬约束：必须使用**已映射**的窗口（未映射时尺寸全部不成立）。

用法：
    python tools/check_fold_fit.py

退出码：0 = 通过；1 = 失败。
"""
from __future__ import annotations

import os
import sys
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

import gui      # noqa: E402
import i18n     # noqa: E402

# 三个可折叠区域；全部展开即高度峰值
FOLDS = ("fold_out", "fold_txt", "fold_native")

# 两张表的行数下限（见 gui.Md2docsApp._autosize 的压缩循环）
ROW_FLOOR = 2


def _settle(root, n: int = 10):
    for _ in range(n):
        root.update()
        root.after(30)


def _measure(app, root, tag: str):
    """返回 (是否放得下, 需求高, 可用高, 行数, 页脚可见)。"""
    _settle(root)
    d = app.diag_info()
    req_h = int(d["main_req"].split("x")[1])
    avail = d["avail"]
    foot = d.get("foot_fully_visible") is True
    ok = req_h <= avail and foot
    print("[fold] %-20s main_req=%s  avail=%s  余量=%+d  rows=%s  页脚可见=%s  -> %s"
          % (tag, d["main_req"], avail, avail - req_h,
             d["res_rows/file_rows"], foot, "OK" if ok else "顶破"))
    return ok, req_h, avail, d["res_rows/file_rows"]


def main() -> int:
    gui.enable_hi_dpi()
    root = tk.Tk()
    app = gui.Md2docsApp(root)
    origin = i18n.current_choice()
    problems: list[str] = []
    notes: list[str] = []
    try:
        root.deiconify()
        _settle(root)
        if not root.winfo_ismapped():
            print("[fold] 失败：窗口未能映射，尺寸结论不可信")
            return 1

        for lang in ("zh", "en"):
            app.set_language(lang, persist=False)
            _settle(root)

            ok, req_h, avail, _rows = _measure(app, root, "%s 默认（折叠闭）" % lang)
            if not ok:
                problems.append("%s 默认态就放不下（main_req %d > avail %d）"
                                % (lang, req_h, avail))

            for name in FOLDS:
                getattr(app, name).set(True, notify=False)
            app._autosize()
            ok, req_h, avail, rows = _measure(app, root, "%s 折叠全展开" % lang)
            if not ok:
                problems.append("%s 折叠全展开后放不下（main_req %d > avail %d）"
                                % (lang, req_h, avail))
            if rows.split("/")[0] == str(ROW_FLOOR):
                notes.append("%s 展开态的结果表已到 %d 行下限，高度余量用尽"
                             % (lang, ROW_FLOOR))

            for name in FOLDS:
                getattr(app, name).set(False, notify=False)
            app._autosize()
    finally:
        app.set_language(origin, persist=False)
        app.shutdown()
        try:
            root.destroy()
        except Exception:
            pass

    print("")
    for n in notes:
        print("[fold] 提醒：%s" % n)
    if problems:
        for p in problems:
            print("[fold] 失败：%s" % p)
        return 1
    print("[fold] 通过：默认态与折叠区全展开态都放得下，页脚完整可见")
    return 0


if __name__ == "__main__":
    sys.exit(main())
