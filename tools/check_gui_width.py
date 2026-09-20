"""界面回归检查：反复点击格式卡片，窗口尺寸必须保持不变。

背景（缺陷 V-10）：`_autosize()` 曾用「内容宽度 + 44」反推窗口宽度。
ttk.Treeview 的可伸缩列会随控件变宽而变宽，而 Treeview 的请求宽度又按
列宽计算，于是形成自增循环：

    窗口变宽 → 拉伸列变宽 → reqwidth 变大 → 窗口再变宽 → …

格式卡片每次点击都会触发一次 `_autosize()`（经 `_sync_txt_fold()`），
因此表现为「每点击一次文件类型图标，窗口就变宽一点」（实测 +44px/次）。

本脚本用真实映射的窗口 + 真实点击事件复现该场景，断言窗口宽高恒定。
必须在**已映射**的窗口下运行——窗口未映射时拉伸列不参与布局，缺陷不显现。

用法：
    python tools/check_gui_width.py [--rounds 6] [--verbose]
退出码 0 表示通过，1 表示存在尺寸漂移。
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "src"))

import tkinter as tk  # noqa: E402

import gui  # noqa: E402


def _sample_files() -> list[str]:
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
    cands = ["tests/imgs_case.md", "sample/示例文档.md", "tests/stress.md"]
    return [os.path.join(root, c) for c in cands
            if os.path.isfile(os.path.join(root, c))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=6,
                    help="每个格式卡片的点击次数（默认 6）")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    gui.enable_hi_dpi()
    root = tk.Tk()
    app = gui.Md2docsApp(root, initial_files=_sample_files())

    samples: list[tuple[int, int, str]] = []
    fatal: list[str] = []

    def record(tag: str):
        root.update_idletasks()
        samples.append((root.winfo_width(), root.winfo_height(), tag))

    def click(fid: str):
        """对卡片本体发真实点击事件，走完整绑定链路。"""
        card = app._fmt_cards[fid]["widgets"][0]
        card.event_generate("<Button-1>", x=4, y=4)
        root.update_idletasks()

    def run():
        try:
            record("启动")
            for _ in range(args.rounds):
                for fid in gui.FMT_ORDER:
                    click(fid)
                    record("点击 " + fid)
                # 折叠区开关联动同样会触发 _autosize，一并覆盖
                for fold in (app.fold_out, app.fold_txt, app.fold_native):
                    fold.toggle()
                    record("折叠 " + str(fold))
        except Exception as exc:  # pragma: no cover - 兜底
            fatal.append("%s: %s" % (type(exc).__name__, exc))
        finally:
            root.after(120, done)

    def done():
        # 只断言宽度：高度会随折叠区展开/收起合法变化
        # （选中 TXT 会自动展开「TXT 选项」，点开折叠区同理），不是缺陷。
        widths = {s[0] for s in samples}
        if args.verbose:
            for w, h, tag in samples:
                print("   %-18s %d x %d" % (tag, w, h))
        if len(widths) > 1:
            first, last = samples[0][0], samples[-1][0]
            print("[check_gui_width] 失败：窗口宽度漂移 %d -> %d（共 %d 种宽度 %s）"
                  % (first, last, len(widths), sorted(widths)))
            print("   最常见原因：窗口宽度由内容宽度反推，与表格拉伸列形成自增循环。")
            fatal.append("宽度漂移")
        else:
            print("[check_gui_width] 通过：%d 次采样，窗口宽度恒为 %d（高度 %d~%d）"
                  % (len(samples), samples[0][0],
                     min(s[1] for s in samples), max(s[1] for s in samples)))
            print("   预期宽度 = %d（WIN_W）" % gui.WIN_W)
            if samples[0][0] != gui.WIN_W:
                print("   提示：当前工作区比设计宽度窄，已按工作区让步，属正常。")
        try:
            app.shutdown()
            root.destroy()
        except Exception:
            pass

    root.after(900, run)
    root.mainloop()

    for f in fatal:
        print("[check_gui_width] 问题：", f)
    return 1 if fatal else 0


if __name__ == "__main__":
    raise SystemExit(main())
