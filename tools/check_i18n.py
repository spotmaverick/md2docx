# -*- coding: utf-8 -*-
"""国际化回归检查。

四件事，缺一不可：

1. **词条自洽**：中英两份词条键集完全一致；代码里引用的词条键都存在；
   没有引用不到的闲置键。
2. **静态文案不外漏**：用 ast 扫描 ``src/*.py`` 的字符串常量，报告没有走 i18n
   的中文硬编码（注释与文档字符串天然不算；自检 / 诊断这类开发期输出豁免）。
   这一条是防"以后新加按钮忘了接 i18n"的关键。
3. **语言判定规则**：用打桩的 LANGID 表逐条核对"中文 → zh、其余一律 en"。
   这条规则是需求的原文（"中国以外的地区一律用英文"），但只在特定语种的系统上
   才显现差异——本机是中文系统，光看运行结果永远是 zh，规则写错也发现不了。
   故必须把 LANGID 灌进去测，而不是信任当前环境的表现。
4. **运行时双语快照**：分别在 zh / en 下构建真实界面，采集每一个会显示文字的
   控件、表头与窗口标题；英文界面下不允许残留任何中文字符，也不允许出现
   "文案没取到、直接把词条键显示出来"的情况。

用法：
    python tools/check_i18n.py
    python tools/check_i18n.py -v        额外打印全部采集到的文案

退出码：0 = 通过；1 = 有问题；2 = 无法运行（环境问题）。
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import sys
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import gui        # noqa: E402
import i18n       # noqa: E402

# 中日韩字符 + 全角标点
CJK = re.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff"
                 r"\uf900-\ufaff\uff00-\uffef]")

# 词条表本身不算"硬编码文案"；server.py 是 Web 时代的死代码，不在分发包内
SKIP_FILES = {"i18n.py", "server.py"}

# 开发期输出（自检 / 诊断），永远不会出现在界面上，豁免
EXEMPT_FUNCS = {"selftest", "diagnose"}

# 落进**输出文档正文**的中文，不是界面文案。
# 文档语言应由源 Markdown 决定，不该跟着界面语言跑；故此处显式豁免。
# 是否改为跟随界面语言属产品决策，见 Md2docs.spec 待办 G-07。
OUTPUT_CONTENT = {
    ("docx_writer.py", "[图片]"),
    ("rtf_writer.py", "[图片%s]"),
    ("rtf_writer.py", "："),
    ("txt_writer.py", "[图片%s]"),
    ("txt_writer.py", "："),
    ("txt_writer.py", "%s（%s）"),
}

# 会以「第 N 个位置参数作为词条键」的调用：函数名 → 参数下标
KEY_ARG_POS = {
    "t": 0,
    "mark_text": 1,
    "choice_label": 0,
    "_btn": 1,
    "_radio": 1,
    "Fold": 1,
    "_panel_head": 2,
}

# 由 i18n.py 自身内部引用（该文件不参与扫描，否则词条表里每个键都会被算成"被引用"）
INTERNAL_KEYS = {"lang.auto"}

# 运行时动态拼出来的键，静态扫描看不到，这里显式校验
DYNAMIC_PREFIXES = {
    "fmt.desc.": ["docx", "doc", "wps", "txt"],
    "fmt.label.": ["docx", "doc", "wps", "txt"],
}


# --------------------------------------------------------------------------- #
# 源码扫描
# --------------------------------------------------------------------------- #
def _parse(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return ast.parse(f.read(), filename=path)
    except Exception as exc:
        print("!! 解析失败 %s：%s" % (path, exc))
        return None


def _docstring_ids(tree) -> set:
    ids = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None) or []
        if body and isinstance(body[0], ast.Expr) and \
                isinstance(body[0].value, ast.Constant) and \
                isinstance(body[0].value.value, str):
            ids.add(id(body[0].value))
    return ids


def _exempt_ids(tree) -> set:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in EXEMPT_FUNCS:
            for sub in ast.walk(node):
                ids.add(id(sub))
    return ids


def _is_i18n_t(node) -> bool:
    """识别 ``i18n.t(...)`` 这种调用（避免把同名的其他函数当词条取用）。"""
    return (isinstance(node, ast.Attribute) and node.attr == "t"
            and isinstance(node.value, ast.Name) and node.value.id == "i18n")


def _call_name(func) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def scan_sources():
    """返回 (全部字符串常量, 显式作为词条键传入的字符串, 逐文件的 CJK 硬编码)。"""
    all_strings: set[str] = set()
    key_args: set[str] = set()
    hardcoded: list[tuple[str, int, str]] = []

    for name in sorted(os.listdir(SRC)):
        if not name.endswith(".py") or name in SKIP_FILES:
            continue
        tree = _parse(os.path.join(SRC, name))
        if tree is None:
            continue
        skip = _docstring_ids(tree) | _exempt_ids(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and id(node) not in skip \
                    and isinstance(node.value, str):
                all_strings.add(node.value)
                if CJK.search(node.value):
                    hardcoded.append((name, getattr(node, "lineno", 0),
                                      node.value))
            if not isinstance(node, ast.Call):
                continue
            fname = _call_name(node.func)
            if fname == "t" and not _is_i18n_t(node.func):
                continue
            pos = KEY_ARG_POS.get(fname)
            if pos is None or len(node.args) <= pos:
                continue
            arg = node.args[pos]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                key_args.add(arg.value)
    return all_strings, key_args, hardcoded


# --------------------------------------------------------------------------- #
# 1. 词条自洽
# --------------------------------------------------------------------------- #
def check_table(all_strings, key_args, verbose: bool) -> list[str]:
    problems: list[str] = []
    zh, en = i18n.STRINGS["zh"], i18n.STRINGS["en"]
    zh_keys = set(zh)

    only_zh = sorted(zh_keys - set(en))
    only_en = sorted(set(en) - zh_keys)
    if only_zh:
        problems.append("英文词条缺失：%s" % ", ".join(only_zh))
    if only_en:
        problems.append("中文词条缺失：%s" % ", ".join(only_en))
    print("[i18n] 词条数：zh %d / en %d" % (len(zh), len(en)))

    for prefix, suffixes in DYNAMIC_PREFIXES.items():
        for suf in suffixes:
            key = prefix + suf
            if key not in zh or key not in en:
                problems.append("动态拼接的词条不存在：%s" % key)

    unknown = sorted(k for k in key_args if k not in zh_keys)
    if unknown:
        problems.append("代码引用了不存在的词条：%s" % ", ".join(unknown))

    # 引用到的键 = 源码里出现、且确实是词条的字符串
    # （键可能写在元组里、写在条件表达式里，不能只看 i18n.t 的实参）
    used = all_strings & zh_keys
    dyn = {p + s for p, ss in DYNAMIC_PREFIXES.items() for s in ss}
    idle = sorted(zh_keys - used - dyn - INTERNAL_KEYS)
    if idle:
        problems.append("没有被任何地方引用的闲置词条：%s" % ", ".join(idle))
    if verbose:
        print("[i18n] 静态引用到的词条：%d 个" % len(used))
    return problems


# --------------------------------------------------------------------------- #
# 2. 静态文案不外漏
# --------------------------------------------------------------------------- #
def check_hardcoded(hardcoded, verbose: bool) -> list[str]:
    problems: list[str] = []
    exempted = 0
    for name, lineno, val in sorted(hardcoded):
        if (name, val) in OUTPUT_CONTENT:
            exempted += 1
            continue
        show = val if len(val) <= 46 else val[:43] + "..."
        problems.append("中文硬编码 %s:%d  %s" % (name, lineno, show))
    print("[i18n] 静态扫描：%d 处中文硬编码（另豁免 %d 处输出文档内容；跳过 %s）"
          % (len(hardcoded) - exempted, exempted, "、".join(sorted(SKIP_FILES))))
    if verbose and exempted:
        for name, val in sorted(OUTPUT_CONTENT):
            print("[i18n]   豁免 %-16s %s" % (name, val))
    return problems


# --------------------------------------------------------------------------- #
# 3. 语言判定规则
# --------------------------------------------------------------------------- #
# (LANGID, 期望语言, 说明)。LANGID 取自 Windows 的 LCID 定义：
#   zh-CN 0x0804 / zh-TW 0x0404 / zh-HK 0x0C04 / zh-SG 0x1004 → 主语言字段均为 0x04
#   其余语种主语言字段各不相同，一律应落到 en
LANGID_CASES = [
    (0x0804, "zh", "zh-CN 简体"),
    (0x0404, "zh", "zh-TW 繁体（中国台湾）"),
    (0x0C04, "zh", "zh-HK 繁体（中国香港）"),
    (0x1404, "zh", "zh-MO 繁体（中国澳门）"),
    (0x1004, "zh", "zh-SG 简体"),
    (0x0409, "en", "en-US"),
    (0x0809, "en", "en-GB"),
    (0x0411, "en", "ja-JP 日语"),
    (0x0412, "en", "ko-KR 韩语"),
    (0x0407, "en", "de-DE 德语"),
    (0x040C, "en", "fr-FR 法语"),
    (0x0419, "en", "ru-RU 俄语"),
    (0x0416, "en", "pt-BR 葡萄牙语"),
]


def _fake_ctypes(langid):
    """伪造 ctypes.windll.kernel32.GetUserDefaultUILanguage() 的返回值。

    i18n._detect_windows 在函数内部 ``import ctypes``，拿到的是 sys.modules 里的
    对象，所以替换 sys.modules['ctypes'] 即可打桩，无需改动被测代码。
    """
    import types as _types

    class _Kernel32:
        @staticmethod
        def GetUserDefaultUILanguage():
            return langid

    return _types.SimpleNamespace(
        windll=_types.SimpleNamespace(kernel32=_Kernel32))


def check_detection(verbose: bool) -> list[str]:
    problems: list[str] = []
    real_ctypes = sys.modules.get("ctypes")
    origin_env = os.environ.pop("MD2DOCS_LANG", None)
    got_lines = []
    try:
        for langid, want, label in LANGID_CASES:
            sys.modules["ctypes"] = _fake_ctypes(langid)
            got = i18n._detect_windows()
            got_lines.append("%s→%s" % (label, got))
            if got != want:
                problems.append("LANGID 0x%04X（%s）判定为 %r，应为 %r"
                                % (langid, label, got, want))
        # 探测失败（无 LANGID / 抛异常）须兜底为 en，不能崩
        sys.modules["ctypes"] = _fake_ctypes(0)
        if i18n._detect_windows() is not None:
            problems.append("LANGID 为 0 时应返回 None（转交下一级探测）")
    finally:
        if real_ctypes is not None:
            sys.modules["ctypes"] = real_ctypes
        else:
            sys.modules.pop("ctypes", None)

    # resolve()：显式档位 > MD2DOCS_LANG 环境变量 > 系统探测
    try:
        if i18n.resolve("en") != "en" or i18n.resolve("zh") != "zh":
            problems.append("显式档位未被优先采用")
        os.environ["MD2DOCS_LANG"] = "en"
        if i18n.resolve("auto") != "en":
            problems.append("MD2DOCS_LANG 未覆盖自动探测")
        os.environ["MD2DOCS_LANG"] = "zh"
        if i18n.resolve("zh") != "zh":
            problems.append("显式档位被 MD2DOCS_LANG 覆盖（优先级颠倒）")
    finally:
        os.environ.pop("MD2DOCS_LANG", None)
        if origin_env is not None:
            os.environ["MD2DOCS_LANG"] = origin_env

    print("[i18n] 语言判定：%d 条 LANGID 用例，%s"
          % (len(LANGID_CASES), "全部符合" if not problems else "有偏差"))
    if verbose:
        print("[i18n]   " + "  ".join(got_lines))
    return problems


# --------------------------------------------------------------------------- #
# 4. 运行时双语快照
# --------------------------------------------------------------------------- #
def _widget_text(w):
    """取控件的静态文字与其 textvariable 名。

    注意：Tk 的 ``cget`` 会做选项前缀匹配，Entry / Combobox 上问 ``-text``
    会命中 ``-textvariable``，返回的是变量名（PY_VAR1 之类）。这里显式排除，
    否则会把变量名当成界面文案，既误导也容易误报。
    """
    var = ""
    try:
        got = w.cget("textvariable")
        var = got if isinstance(got, str) else ""
    except Exception:
        pass
    try:
        text = w.cget("text")
    except Exception:
        return None, var
    if not isinstance(text, str) or not text:
        return None, var
    if var and text == var:
        return None, var
    return text, var


def collect_texts(root, app) -> list[tuple[str, str]]:
    """采集界面上所有会显示文字的来源。"""
    out: list[tuple[str, str]] = []
    for w in gui.walk_widgets(root):
        text, var = _widget_text(w)
        if text:
            out.append((str(w), text))
        if var:
            try:
                val = root.getvar(var)
            except Exception:
                val = ""
            if isinstance(val, str) and val:
                out.append(("%s:textvariable" % w, val))
    for tree, cols in ((app.file_tree, ("name", "src")),
                       (app.res_tree, ("state", "file", "fmt", "info"))):
        for cid in cols:
            try:
                out.append(("%s:heading:%s" % (tree, cid),
                            tree.heading(cid, "text")))
            except Exception:
                pass
    for tag, fold in (("fold_out", app.fold_out), ("fold_txt", app.fold_txt),
                      ("fold_native", app.fold_native)):
        try:
            out.append(("%s:title" % tag, fold.title.cget("text")))
        except Exception:
            pass
    out.append(("root:title", root.title()))
    return out


def check_runtime(verbose: bool) -> list[str]:
    problems: list[str] = []
    keys = set(i18n.STRINGS["zh"])

    gui.enable_hi_dpi()
    root = tk.Tk()
    root.withdraw()
    app = gui.Md2docsApp(root)

    origin = i18n.current_choice()
    try:
        for lang in ("en", "zh"):
            app.set_language(lang, persist=False)
            root.update_idletasks()
            items = collect_texts(root, app)
            print("[i18n] %s 界面采集到 %d 条文案" % (lang, len(items)))

            # 文案没取到时 t() 会把词条键原样返回——这条最容易被忽略
            leaked = [t for _, t in items if t in keys]
            if leaked:
                problems.append("%s 界面把词条键当文案显示了：%s"
                                % (lang, ", ".join(sorted(set(leaked)))))

            if lang == "en":
                dirty = [(src, t) for src, t in items if CJK.search(t)]
                if dirty:
                    for src, t in dirty[:20]:
                        problems.append("英文界面残留中文 %s → %s" % (src, t))
                elif verbose:
                    print("[i18n] 英文界面无中文字符（通过）")
            else:
                if root.title() != i18n.t("app.window_title"):
                    problems.append("中文窗口标题不符：%r" % root.title())
                if app.btn_run.cget("text") != i18n.t("run.button"):
                    problems.append("中文主按钮文案不符：%r"
                                    % app.btn_run.cget("text"))
            if verbose:
                for src, t in items[:200]:
                    print("        %-22s %s" % (src, t))
    finally:
        app.set_language(origin, persist=False)
        app.shutdown()
        try:
            root.destroy()
        except Exception:
            pass
    return problems


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    all_strings, key_args, hardcoded = scan_sources()

    problems: list[str] = []
    problems += check_table(all_strings, key_args, args.verbose)
    problems += check_hardcoded(hardcoded, args.verbose)
    problems += check_detection(args.verbose)
    try:
        problems += check_runtime(args.verbose)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        problems.append("运行时检查无法执行：%s" % exc)

    if problems:
        print("\n[i18n] 失败，共 %d 项：" % len(problems))
        for p in problems:
            print("   -", p)
        return 1
    print("\n[i18n] 通过：词条自洽、无硬编码残留、语言判定正确、双语界面正确")
    return 0


if __name__ == "__main__":
    sys.exit(main())
