# -*- coding: utf-8 -*-
"""语言入口回归：标识必须是自绘地球矢量图，入口不得依赖任何文字。

为什么需要它
------------
界面语言未必等于用户的母语：判定规则只认"中文系统 → 中文、其余 → 英文"，
用户也随时可能手切错档位。此时"语言 / Language"这段提示本身也是用当前界面
语言写的——**用户要找的正是改语言的地方，却先被这段读不懂的提示挡住**。
所以入口的标识改成了自绘地球图标（``gui.GlobeIcon``）。

这条回归盯三件事：

1. **图标是画出来的，不是写出来的**：必须是 Canvas 且含椭圆图元，
   **不得含任何 text 图元**。一旦有人改回 ``create_text("🌐")``，
   字形缺失与 GBK 编码风险就回来了（🌐 U+1F310 两条都不满足，见 i18n 用字约束）。
2. **入口里没有静态文字**：整棵子树不允许出现 ``cget("text")`` 非空的控件，
   也就是不许把 "lang.label" 那样的文字标签加回来。
3. **端到端真的能切**：在图标上投递一次真实点击 → 列表展开 → 点中某一行 →
   界面语言（含窗口标题）确实切过去了。两轮覆盖正反方向（zh→English、en→中文）。

正控（探针自检）
----------------
先造两个"坏样本"——带文字的 Label、用 ``create_text`` 画的假图标——断言两段
采集器**都能检出**。检不出就直接判"探针失效"：看不见缺陷的探针给出的假通过，
比没有探针更危险（V-14 的教训）。

另外，本工具**不得改动主人的真实配置**：语言切换会落盘到 settings.json，
运行时把 ``settings.put`` 拦下来，只记录它本来会写什么。

用法：
    python tools/check_lang_entry.py

退出码：0 = 通过；1 = 发现问题或探针失效。
"""
from __future__ import annotations

import os
import sys
import tkinter as tk
import tkinter.font as tkfont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

import gui        # noqa: E402
import i18n       # noqa: E402
import settings   # noqa: E402

# 假图标用的太阳系地球符号（U+1F310）。用转义写，源码里不留难认的字面量。
FAKE_GLOBE = "\U0001F310"


def _make_output_safe() -> None:
    """把标准输出/错误设成有损模式。

    ⚠️ 踩过（写这个工具时）：失败提示里直接写了一个**字面的 🌐**，于是
    "缺陷被成功检出、却在打印失败原因时自己抛 UnicodeEncodeError"——
    报错信息本身就打不出来。中文控制台是 GBK，任何面向控制台的输出都必须
    有损兜底，**错误路径尤其**（与 ``app._make_output_safe`` 同一套做法）。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass


def _ascii_safe(text: str) -> str:
    """把字符串渲染成"任何控制台编码都打得出来"的形式。

    本工具要回显采集到的图标文字，其中可能含 🌐 这类 GBK 打不出的字符——
    直接 print 会在中文控制台上抛 UnicodeEncodeError，让"检查工具"变成"崩溃源"。
    宁可输出有损，也不要崩（V-14）。
    """
    out = []
    for ch in text:
        out.append(ch if 32 <= ord(ch) < 127 else "<U+%04X>" % ord(ch))
    return "".join(out)


# --------------------------------------------------------------------------- #
# 采集器（同一段代码既用于正控，也用于真实界面）
# --------------------------------------------------------------------------- #
def _visible_texts(widget) -> list:
    """采集一棵控件子树里所有**会显示出来的静态文字**。"""
    found = []
    for w in gui.walk_widgets(widget):
        try:
            text = w.cget("text")
        except Exception:
            continue
        if isinstance(text, str) and text.strip():
            found.append("%s(%s)" % (w.winfo_class(), _ascii_safe(text.strip())))
    return found


def _glyph_items(widget) -> list:
    """采集 Canvas 上用**字符**画出来的图元。

    矢量图元（oval / line / polygon）不会命中它；有人把图标写成
    ``create_text("🌐")`` 时，这里就会报出来。
    """
    items = []
    try:
        for i in widget.find_all():
            if widget.type(i) == "text":
                items.append(_ascii_safe(str(widget.itemcget(i, "text"))))
    except Exception:
        pass
    return items


def positive_control(root) -> list[str]:
    """探针自检：两段采集器必须各自检出"坏样本"，否则判探针失效。"""
    problems: list[str] = []
    scratch = tk.Frame(root)        # 不 pack：不进布局，免得扰动窗口几何
    tk.Label(scratch, text="语言").pack()
    fake = tk.Canvas(scratch, width=18, height=18)
    fake.pack()
    fake.create_text(9, 9, text=FAKE_GLOBE)
    try:
        got_text = _visible_texts(scratch)
        got_glyph = _glyph_items(fake)
        print("[lang] 正控 文字采集器 → %s" % (got_text or "什么都没采到"))
        print("[lang] 正控 字形采集器 → %s" % (got_glyph or "什么都没采到"))
        if not got_text:
            problems.append("正控失效：文字采集器看不见带文字的 Label")
        if not got_glyph:
            problems.append("正控失效：字形采集器看不见用 create_text 画的图标")
    finally:
        scratch.destroy()
    return problems


# --------------------------------------------------------------------------- #
# 静态检查：标识与档位名
# --------------------------------------------------------------------------- #
def check_static(app, root, lang: str) -> list[str]:
    problems: list[str] = []
    ico, cb = app.ico_lang, app.cmb_lang
    if ico.master is not cb.master:
        problems.append("%s：地球图标与语言下拉框不在同一个容器里" % lang)
    entry = ico.master

    texts = _visible_texts(entry)
    print("[lang] %s 入口子树可见文字 = %s" % (lang, texts or "无"))
    if texts:
        problems.append("%s：语言入口里还有文字标识 %s——标识必须是地球图标"
                        % (lang, texts))

    shapes = ico.shapes()
    print("[lang] %s 地球图标图元 = %s" % (lang, shapes))
    if not isinstance(ico, tk.Canvas):
        problems.append("%s：地球标识不是 Canvas 自绘的" % lang)
    if shapes.count("oval") < 3:
        problems.append("%s：地球标识只有 %d 个椭圆图元，不像经纬线地球"
                        % (lang, shapes.count("oval")))
    glyphs = _glyph_items(ico)
    if glyphs:
        problems.append("%s：地球标识里含字符图元 %s——标识必须画出来，"
                        "不能用字形（U+1F310 一类字符在 GBK 与 UI 字体上都不可靠）"
                        % (lang, glyphs))

    raw = cb.cget("values")
    labels = ([str(x) for x in raw] if isinstance(raw, (tuple, list))
              else [str(x) for x in root.tk.splitlist(raw)])
    want = [i18n.choice_label(c) for c in i18n.LANG_CHOICES]
    print("[lang] %s 语言档位 = %s" % (lang, [_ascii_safe(x) for x in labels]))
    if labels != want:
        problems.append("%s：档位名不符，期望 %r 实到 %r" % (lang, want, labels))

    # 语言名必须"以本名书写"：看不懂界面语言的人，至少认得自己那一条
    for choice, name in i18n.LANG_NAME.items():
        idx = i18n.LANG_CHOICES.index(choice)
        if idx < len(labels) and labels[idx] != name:
            problems.append("%s：%s 档位没有用本名书写（实为 %r）"
                            % (lang, choice, labels[idx]))

    # 宽度必须容得下最长档位，否则换语言后会静默裁字
    f = tkfont.Font(root=root, font=app.fonts["tiny"])
    need = max(f.measure(x) for x in labels) if labels else 0
    if cb.winfo_reqwidth() < need:
        problems.append("%s：下拉框请求宽度 %dpx < 最长档位文字 %dpx，会裁字"
                        % (lang, cb.winfo_reqwidth(), need))
    return problems


# --------------------------------------------------------------------------- #
# 端到端：点地球 → 展开 → 选中 → 真的切换
# --------------------------------------------------------------------------- #
def _click(widget, x: int, y: int):
    widget.event_generate("<Button-1>", x=x, y=y)
    widget.event_generate("<ButtonRelease-1>", x=x, y=y)


def pick_from_dropdown(app, root, idx: int) -> list[str]:
    """在图标上真实点一下，再在展开的列表里点中第 idx 行。"""
    ico, cb = app.ico_lang, app.cmb_lang
    size = ico.winfo_width()
    if size <= 1:
        return ["地球图标宽度异常（%d），窗口可能未映射" % size]

    _click(ico, size // 2, size // 2)
    root.update()

    pd = root.tk.eval("ttk::combobox::PopdownWindow %s" % cb)
    if not int(root.tk.eval("winfo ismapped %s" % pd)):
        return ["点地球图标之后，语言列表没有展开"]

    # popdown 的 listbox 不在 tkinter 的 children 表里（路径里的 ! 是 Tk 对
    # "." 的转义），只能走 Tcl 侧投递事件
    lb = pd + ".f.l"
    bbox = str(root.tk.eval("%s bbox %d" % (lb, idx))).strip()
    if not bbox:
        return ["语言列表第 %d 行取不到位置（列表未就绪）" % idx]
    parts = [int(float(v)) for v in bbox.split()]
    y = parts[1] + parts[3] // 2
    root.tk.eval("event generate {%s} <Button-1> -x 8 -y %d" % (lb, y))
    root.tk.eval("event generate {%s} <ButtonRelease-1> -x 8 -y %d" % (lb, y))
    root.update()
    return []


def main() -> int:
    _make_output_safe()
    gui.enable_hi_dpi()
    root = tk.Tk()
    app = gui.Md2docsApp(root)

    problems: list[str] = []
    origin = i18n.current_choice()
    # 回归不得改动主人的真实配置：把落盘拦下，只记录"本来会写什么"
    real_put = settings.put
    wrote: list = []
    settings.put = lambda key, value: wrote.append((key, value))
    try:
        root.deiconify()
        root.update()
        for _ in range(6):
            root.update()
            root.after(30)
        if not root.winfo_ismapped():
            print("[lang] 失败：窗口未能映射，点击类结论不可信")
            return 1

        problems += positive_control(root)
        root.update()

        # 两轮，覆盖正反方向，也顺带确认"英文界面下入口同样可辨认"
        for lang, target in (("zh", "en"), ("en", "zh")):
            app.set_language(lang, persist=False)
            root.update()
            problems += check_static(app, root, lang)

            idx = i18n.LANG_CHOICES.index(target)
            problems += pick_from_dropdown(app, root, idx)
            got = i18n.current_choice()
            title_ok = root.title() == gui.window_title()
            print("[lang] %s 界面点选「%s」→ 档位=%s  标题随语言=%s"
                  % (lang, _ascii_safe(i18n.choice_label(target)), got, title_ok))
            if got != target:
                problems.append("%s 界面点选后档位是 %r，应为 %r"
                                % (lang, got, target))
            if not title_ok:
                problems.append("%s 界面点选后窗口标题未随语言更新" % lang)
        if not wrote:
            problems.append("语言切换没有走配置持久化（settings.put 未被调用）")
        else:
            print("[lang] 持久化调用 = %s（已拦截，未写入磁盘）" % wrote)
    finally:
        settings.put = real_put
        try:
            app.set_language(origin, persist=False)
        except Exception:
            pass
        app.shutdown()
        try:
            root.destroy()
        except Exception:
            pass

    if problems:
        print("\n[lang] 失败，共 %d 项：" % len(problems))
        for p in problems:
            print("   -", p)
        return 1
    print("\n[lang] 通过：标识为自绘矢量地球（无文字、无字形），"
          "点图标可展开并真的切换语言，中英两种界面下均成立")
    return 0


if __name__ == "__main__":
    sys.exit(main())
