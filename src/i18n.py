# -*- coding: utf-8 -*-
"""界面语言与文案。

语言判定规则
------------
* 首选「操作系统界面语言」：主语言为中文（含简繁、港澳台）→ 中文界面；
  **其余一律英文**（对应"中国以外的地区一律用英文"）。
* 用户在界面上手动选择后写入配置（见 settings.py），下次启动优先采用；
  选「自动」则回到跟随系统。
* 环境变量 ``MD2DOCS_LANG`` 优先级最高，便于回归测试强制指定语言。

使用约定
--------
界面上**不允许**出现硬编码的可见文案，一律走 :func:`t`。
``tools/check_i18n.py`` 会用 ast 扫描源码强制执行这一约束。

文案用字约束
------------
词条里只允许使用「UI 字体**有字形** 且 **GBK 可编码**」的字符：

* 微软雅黑（含 YaHei UI）与 Segoe UI 都**没有** U+2713 / U+2715 的字形，
  而 Windows 上的 Tk 走 GDI 绘制、GDI 不做字体回退，界面上会显示成方框；
* 控制台与管道默认 GBK，打不出的字符会让 ``--selftest`` 的 ``print`` 抛
  ``UnicodeEncodeError``，把"跑个自检"放大成"程序启动失败"。

GB2312 符号区是安全来源（√ × ● ○ ■ □ ☆ ★ ※）。
``tools/check_font_glyphs.py`` 会逐字符核验全部词条。
"""
from __future__ import annotations

import os

# 语言代码 → 语言自身名称（下拉框里始终以该语言书写，不随界面语言翻译）
LANGS = ("zh", "en")
LANG_NAME = {"zh": "中文", "en": "English"}

# 下拉框的三个档位：自动跟随系统 / 强制中文 / 强制英文
LANG_CHOICES = ("auto", "zh", "en")

FALLBACK = "en"          # 探测失败时的兜底语言
FALLBACK_CHAIN = ("zh",)  # 词条缺失时回退到的语言

# Windows LANGID 的主语言字段：LANG_CHINESE
_WIN_LANG_CHINESE = 0x04


# --------------------------------------------------------------------------- #
# 词条表
# --------------------------------------------------------------------------- #
STRINGS: dict[str, dict[str, str]] = {
    "zh": {
        # 应用
        "app.name": "Md2docs",
        "app.window_title": "Md2docs · Markdown 转 Word / WPS / TXT",
        "app.tagline": "Markdown 转 Word / WPS / TXT",
        "app.subtitle": "Markdown 一键转成 Word / WPS / 纯文本",
        "app.footer": "作者：王冠",
        "app.fatal_title": "Md2docs 启动失败",
        "app.logo_letter": "M",

        # 格式
        "fmt.desc.docx": "Word 2007+ 原生",
        "fmt.desc.doc": "Word 97-2003",
        "fmt.desc.wps": "WPS 文字",
        "fmt.desc.txt": "纯文本",
        "fmt.label.docx": "Word 文档 (.docx)",
        "fmt.label.doc": "Word 97-2003 (.doc)",
        "fmt.label.wps": "WPS 文字 (.wps)",
        "fmt.label.txt": "纯文本 (.txt)",

        # 步骤标题
        "step.files": "选择 Markdown 文件",
        "step.output": "输出设置",
        "step.run": "开始转换",

        # 第 1 步：文件
        "file.browse": "浏览本机文件",
        "file.clear": "清空",
        "file.drop_hint": "把 .md 文件拖到这里，或点击「浏览本机文件」"
                          "（也可直接拖到 Md2docs.exe 图标上）",
        "file.drop_sub": "支持多选，自动保留相对图片引用",
        "file.col_name": "文件名",
        "file.col_path": "位置",
        "file.empty": "还没有添加文件（支持 .md / .markdown）",
        "file.dialog_title": "选择 Markdown 文件",
        "file.ft_md": "Markdown 文件",
        "file.ft_txt": "文本文件",
        "file.ft_all": "所有文件",

        # 第 2 步：输出
        "out.fold": "输出位置",
        "out.same": "与源文件相同",
        "out.custom": "指定目录",
        "out.browse": "浏览",
        "out.dialog_title": "选择输出目录",
        "txt.fold": "TXT 选项",
        "txt.plain": "去掉 Markdown 符号",
        "txt.raw": "保留原始 Markdown",
        "txt.encoding": "编码",
        "native.fold": ".doc / .wps 高质量模式",
        "native.enable": "启用",

        # 第 3 步：运行
        "run.button": "开始转换",
        "run.running": "转换中…",
        "run.open_out": "打开输出文件夹",
        "res.col_state": "状态",
        "res.col_file": "文件",
        "res.col_fmt": "格式",
        "res.col_info": "说明",
        "res.state_ok": "√ 成功",
        "res.state_fail": "× 失败",
        "res.failed": "转换失败",
        "res.file_missing": "文件不存在",

        # 折叠区摘要
        "sum.txt_on": "已选 TXT",
        "sum.txt_off": "未选 TXT",
        "sum.out_custom": "指定目录",
        "sum.out_custom_empty": "指定目录（未选择）",
        "sum.out_custom_dir": "指定目录：{path}",
        "sum.out_same": "与源文件相同",
        "sum.out_same_dir": "与源文件相同：{path}",
        "sum.out_same_many": "与源文件相同（多个目录）",
        "sum.native_on": "本机 Office 原生格式",
        "sum.native_off": "RTF 兼容格式",

        # 能力检测
        "caps.detecting": "正在检测本机 Office…",
        "caps.ready": "● {names} 已就绪",
        "caps.none": "○ 未检测到 Word / WPS",
        "caps.hint_ready": "开启后调用本机 Office 另存为原生格式（稍慢）；"
                           "关闭则用内置 RTF 引擎，秒出且格式同样完整。",
        "caps.hint_none": "本机未检测到 Word / WPS，此项不可用；"
                          ".doc / .wps 由内置 RTF 引擎生成，Word、WPS 均可直接打开。",

        # 进度
        "prog.running": "转换中…",
        "prog.progress": "已完成 {done} / {total}",
        "prog.finished": "完成 {ok} / {total}",

        # 提示条
        "toast.no_files": "没有可添加的 Markdown 文件",
        "toast.added": "已添加 {n} 个文件",
        "toast.duplicated": "这些文件已在列表中",
        "toast.need_files": "请先添加 Markdown 文件",
        "toast.need_formats": "请至少选择一种输出格式",
        "toast.need_outdir": "请选择输出目录",
        "toast.outdir_bad": "输出目录不可用：{err}",
        "toast.finished": "转换完成：{n} 个文件",

        # 路径错误
        "err.empty_path": "空路径",
        "err.path_missing": "路径不存在",

        # 本机 Office（COM）相关
        "com.no_pywin32": "未安装 pywin32",
        "com.not_run": "未执行",
        "com.timeout": "转换超时（本机 Office 无响应）",
        "com.no_office": "未找到可用的 Office",
        "list_sep": "；",

        # 转换引擎（结果表「说明」列）
        "engine.docx": "python-docx",
        "engine.builtin": "内置",
        "engine.office": "本机 Office",
        "engine.rtf": "RTF 兼容格式",
        "warn.native_failed": "原生模式失败（{msg}），已改用兼容格式",
        "convert.no_output": "输出文件未生成",

        # 语言选择
        # 这里**没有** lang.label：语言入口的标识是自绘地球图标，不写文字。
        # 界面语言未必是用户的母语，此时"语言 / Language"这种提示本身就是
        # 用户看不懂的文字，恰好会挡住他要找的那个入口（V-19）。
        # 档位名的取法：语言一律用其**本名**（中文 / English，见 LANG_NAME），
        # 所以两种界面下都认得出来；auto 是唯一随界面语言翻译的一档，
        # 但它只影响"要不要跟随系统"这一个选择，不影响用户找到并切到自己的语言。
        "lang.auto": "自动",

        # 命令行
        "cli.desc": "Md2docs - {title}（原生桌面程序，无 Web 依赖）",
        "cli.files_help": "启动时直接载入的 Markdown 文件（可把文件拖到 EXE 图标上）",
        "cli.cli_help": "命令行模式：直接转换，不启动界面",
        "cli.format_help": "命令行模式的输出格式，逗号分隔，默认 docx",
        "cli.out_help": "命令行模式的输出目录",
        "cli.native_help": "调用本机 Word/WPS 生成原生 .doc/.wps",
        "cli.selftest_help": "内部自检：创建界面与控件后立即退出，不显示窗口",
        "cli.diag_help": "内部诊断：输出 DPI 与窗口度量后退出",
        "cli.lang_help": "界面语言：auto / zh / en（默认 auto，跟随系统）",
        "cli.no_files": "没有找到待转换的 Markdown 文件",
        "cli.bad_format": "不支持的格式：{list}",
        "cli.done": "完成 {ok}/{total}",
    },
    "en": {
        # App
        "app.name": "Md2docs",
        "app.window_title": "Md2docs · Markdown to Word / WPS / TXT",
        "app.tagline": "Markdown to Word / WPS / TXT",
        "app.subtitle": "Convert Markdown to Word / WPS / plain text in one click",
        "app.footer": "Author: Wang Guan",
        "app.fatal_title": "Md2docs failed to start",
        "app.logo_letter": "M",

        # Formats
        "fmt.desc.docx": "Word 2007+ native",
        "fmt.desc.doc": "Word 97-2003",
        "fmt.desc.wps": "WPS Writer",
        "fmt.desc.txt": "Plain text",
        "fmt.label.docx": "Word Document (.docx)",
        "fmt.label.doc": "Word 97-2003 (.doc)",
        "fmt.label.wps": "WPS Writer (.wps)",
        "fmt.label.txt": "Plain Text (.txt)",

        # Step titles
        "step.files": "Select Markdown Files",
        "step.output": "Output Settings",
        "step.run": "Convert",

        # Step 1: files
        "file.browse": "Browse Files",
        "file.clear": "Clear",
        "file.drop_hint": "Drop .md files here, or click “Browse Files” "
                          "(you can also drop them onto the Md2docs.exe icon)",
        "file.drop_sub": "Multi-select supported; relative image references are kept",
        "file.col_name": "Name",
        "file.col_path": "Location",
        "file.empty": "No files added yet (.md / .markdown supported)",
        "file.dialog_title": "Select Markdown Files",
        "file.ft_md": "Markdown Files",
        "file.ft_txt": "Text Files",
        "file.ft_all": "All Files",

        # Step 2: output
        "out.fold": "Output Location",
        "out.same": "Same as source",
        "out.custom": "Custom folder",
        "out.browse": "Browse",
        "out.dialog_title": "Select Output Folder",
        "txt.fold": "TXT Options",
        "txt.plain": "Strip Markdown syntax",
        "txt.raw": "Keep raw Markdown",
        "txt.encoding": "Encoding",
        "native.fold": ".doc / .wps high-quality mode",
        "native.enable": "Enable",

        # Step 3: run
        "run.button": "Start Conversion",
        "run.running": "Converting…",
        "run.open_out": "Open Output Folder",
        "res.col_state": "Status",
        "res.col_file": "File",
        "res.col_fmt": "Format",
        "res.col_info": "Details",
        "res.state_ok": "√ Done",
        "res.state_fail": "× Failed",
        "res.failed": "Conversion failed",
        "res.file_missing": "File not found",

        # Fold summaries
        "sum.txt_on": "TXT selected",
        "sum.txt_off": "TXT not selected",
        "sum.out_custom": "Custom folder",
        "sum.out_custom_empty": "Custom folder (not set)",
        "sum.out_custom_dir": "Custom folder: {path}",
        "sum.out_same": "Same as source",
        "sum.out_same_dir": "Same as source: {path}",
        "sum.out_same_many": "Same as source (multiple folders)",
        "sum.native_on": "Native Office format",
        "sum.native_off": "RTF-compatible format",

        # Capability detection
        "caps.detecting": "Detecting local Office…",
        "caps.ready": "● {names} ready",
        "caps.none": "○ Word / WPS not found",
        "caps.hint_ready": "When enabled, the local Office is used to save native "
                           "formats (slower); when disabled, the built-in RTF "
                           "engine produces equally complete output instantly.",
        "caps.hint_none": "Word / WPS was not found on this machine, so this "
                          "option is unavailable; .doc / .wps are produced by the "
                          "built-in RTF engine and open directly in Word or WPS.",

        # Progress
        "prog.running": "Converting…",
        "prog.progress": "{done} / {total} done",
        "prog.finished": "Finished {ok} / {total}",

        # Toasts
        "toast.no_files": "No Markdown files to add",
        "toast.added": "Added {n} file(s)",
        "toast.duplicated": "Those files are already in the list",
        "toast.need_files": "Add Markdown files first",
        "toast.need_formats": "Select at least one output format",
        "toast.need_outdir": "Choose an output folder",
        "toast.outdir_bad": "Output folder unavailable: {err}",
        "toast.finished": "Conversion finished: {n} file(s)",

        # Path errors
        "err.empty_path": "Empty path",
        "err.path_missing": "Path does not exist",

        # Local Office (COM)
        "com.no_pywin32": "pywin32 is not installed",
        "com.not_run": "not executed",
        "com.timeout": "Conversion timed out (local Office not responding)",
        "com.no_office": "No usable Office found",
        "list_sep": "; ",

        # Engines (result table "Details" column)
        "engine.docx": "python-docx",
        "engine.builtin": "built-in",
        "engine.office": "local Office",
        "engine.rtf": "RTF-compatible",
        "warn.native_failed": "Native mode failed ({msg}); fell back to the "
                              "compatible format",
        "convert.no_output": "Output file was not created",

        # Language picker
        # No "lang.label" here: the picker is flagged by a vector-drawn globe
        # icon instead of text, so a user who cannot read the current UI
        # language can still find it (V-19). Language names are written in
        # their own script (see LANG_NAME), so every entry is readable by
        # whoever needs it; only the "auto" entry follows the UI language,
        # and that one decides nothing about *which* language to pick.
        "lang.auto": "Auto",

        # Command line
        "cli.desc": "Md2docs - {title} (native desktop app, no web dependency)",
        "cli.files_help": "Markdown files to load at startup (or drop files onto "
                          "the EXE icon)",
        "cli.cli_help": "Command-line mode: convert directly, no window",
        "cli.format_help": "Output formats for command-line mode, comma-separated, "
                           "default docx",
        "cli.out_help": "Output folder for command-line mode",
        "cli.native_help": "Use the local Word/WPS to produce native .doc/.wps",
        "cli.selftest_help": "Self-test: build the UI and exit without showing it",
        "cli.diag_help": "Diagnostics: print DPI and window metrics, then exit",
        "cli.lang_help": "UI language: auto / zh / en (default auto, follow system)",
        "cli.no_files": "No Markdown files found to convert",
        "cli.bad_format": "Unsupported format: {list}",
        "cli.done": "Done {ok}/{total}",
    },
}

# 完整性护栏：两份词条必须键集完全一致（导入时即暴露，避免线上缺词条）
_missing = {k for k in STRINGS["zh"] if k not in STRINGS["en"]}
_extra = {k for k in STRINGS["en"] if k not in STRINGS["zh"]}
if _missing or _extra:
    raise RuntimeError(
        "i18n 词条不一致：中文多出 %s，英文多出 %s" % (sorted(_missing),
                                                     sorted(_extra)))

_lang = FALLBACK
_choice = "auto"


# --------------------------------------------------------------------------- #
# 系统语言探测
# --------------------------------------------------------------------------- #
def _detect_windows() -> str | None:
    """Windows：读「用户界面语言」LANGID，主语言为中文则 zh，否则 en。"""
    try:
        import ctypes
        langid = int(ctypes.windll.kernel32.GetUserDefaultUILanguage())
    except Exception:
        return None
    if not langid:
        return None
    primary = langid & 0x3FF
    return "zh" if primary == _WIN_LANG_CHINESE else "en"


def _detect_locale() -> str | None:
    """跨平台兜底：locale / 环境变量里的语言标签。"""
    tags = []
    try:
        import locale
        tags.append(locale.getlocale()[0] or "")
        try:
            tags.append(locale.getdefaultlocale()[0] or "")
        except Exception:
            pass
    except Exception:
        pass
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        tags.append(os.environ.get(var) or "")
    for tag in tags:
        if tag:
            head = str(tag).replace("-", "_").split("_")[0].lower()
            if head == "zh":
                return "zh"
            if head:
                return "en"
    return None


def detect_system_lang() -> str:
    """按操作系统语言判定界面语言：中文 → zh，其余一律 en。"""
    if os.name == "nt":
        got = _detect_windows()
        if got:
            return got
    got = _detect_locale()
    return got or FALLBACK


# --------------------------------------------------------------------------- #
# 运行时
# --------------------------------------------------------------------------- #
def normalize(lang) -> str:
    """把任意输入归一成 'auto' / 'zh' / 'en'。"""
    value = str(lang or "").strip().lower()
    if value in LANG_CHOICES:
        return value
    return "auto"


def resolve(choice: str) -> str:
    """把档位解析成实际语言：auto → 跟随系统。"""
    choice = normalize(choice)
    if choice in LANGS:
        return choice
    env = os.environ.get("MD2DOCS_LANG")
    if env and normalize(env) in LANGS:
        return normalize(env)
    return detect_system_lang()


def setup(choice: str = "auto") -> str:
    """设定语言档位并返回实际生效的语言。"""
    global _lang, _choice
    _choice = normalize(choice)
    _lang = resolve(_choice)
    return _lang


def current() -> str:
    """当前生效的语言（'zh' / 'en'）。"""
    return _lang


def current_choice() -> str:
    """当前语言档位（'auto' / 'zh' / 'en'），用于回填界面下拉框。"""
    return _choice


def choice_label(choice: str) -> str:
    """语言下拉框里某一档位的显示文字（auto 随界面语言翻译，语言名用其本名）。"""
    choice = normalize(choice)
    if choice == "auto":
        return t("lang.auto")
    return LANG_NAME.get(choice, choice)


def t(key: str, **kw) -> str:
    """取当前语言文案；缺失则回退，仍缺则返回键名本身（便于暴露问题）。"""
    text = STRINGS.get(_lang, {}).get(key)
    if text is None:
        for alt in FALLBACK_CHAIN:
            text = STRINGS.get(alt, {}).get(key)
            if text is not None:
                break
    if text is None:
        return key
    if kw:
        try:
            return text.format(**kw)
        except Exception:
            return text
    return text


# 模块导入即按系统语言就位；app.py 随后会用 setup() 覆盖为「记忆的选择」。
# 这样即便有人绕过 app.py 直接 import gui，界面语言也是对的。
_lang = detect_system_lang()
