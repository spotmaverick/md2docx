# -*- coding: utf-8 -*-
"""统一的排版主题（DOCX / RTF 共用）。

配色与字号刻意对齐主流 Markdown 渲染效果（GitHub 风格）：
标题不加颜色，只靠字号与字重区分层级；正文、链接、代码块的观感与网页渲染一致。
"""
from __future__ import annotations

BODY_FONT = "Microsoft YaHei"   # 正文西文（默认微软雅黑）
BODY_FONT_EA = "Microsoft YaHei"  # 正文中日韩
HEAD_FONT = BODY_FONT       # 标题与正文同族，仅靠字号/字重区分
HEAD_FONT_EA = BODY_FONT_EA
MONO_FONT = "Consolas"      # 行内代码与代码块（中西文同用）

# RTF 里字体名只能安全使用 ASCII，故单独一套
RTF_FONTS = ["Microsoft YaHei", "Consolas", "Times New Roman"]

# GitHub 风格 Markdown 渲染配色
TEXT = "24292F"
HEADING_TEXT = TEXT         # 标题不额外着色
MUTED = "57606A"
CODE_FG = "1F2328"
CODE_BG = "F6F8FA"
QUOTE_FG = "57606A"
QUOTE_BG = "F6F8FA"
QUOTE_BAR = "D0D7DE"
LINK = "0969DA"
TABLE_BORDER = "D0D7DE"
TABLE_HEAD_BG = "F6F8FA"
TABLE_ALT_BG = "FCFCFD"
HR = "D8DEE4"

BODY_SIZE = 11.0
# h1~h6：相对正文的倍率，参照 GitHub 的 2 / 1.5 / 1.25 / 1.1 / 1 / 1 em
HEADING_SIZES = {1: 22.0, 2: 17.0, 3: 14.0, 4: 12.0, 5: 11.0, 6: 11.0}

LIST_BULLETS = ["•", "◦", "▪", "·"]


def heading_size(level: int) -> float:
    return HEADING_SIZES.get(max(1, min(level, 6)), BODY_SIZE)


def heading_color(level: int) -> str:
    """标题沿用正文颜色——Markdown 渲染里标题并不着色。"""
    return HEADING_TEXT
