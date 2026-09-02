# -*- coding: utf-8 -*-
"""Markdown -> 中间语义模型（AST）

所有渲染器（DOCX / RTF / TXT）都只消费这里的模型，互不关心具体格式细节。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Run:
    """行内片段。"""
    text: str = ""
    bold: bool = False
    italic: bool = False
    strike: bool = False
    code: bool = False
    sup: bool = False
    sub: bool = False
    link: str | None = None     # 超链接目标
    image: str | None = None    # 图片地址（行内图片）
    brk: bool = False           # 硬换行


@dataclass
class Block:
    """块级节点。

    kind 取值：
        heading  - level 1..6，runs
        para     - runs
        code     - text / lang
        quote    - items[0] 为子块列表
        list     - ordered / items: list[list[Block]]
        table    - rows: list[list[list[Block]]]，header: bool
        hr
        image    - src / alt
    """
    kind: str
    level: int = 1
    runs: list[Run] = field(default_factory=list)
    text: str = ""
    lang: str = ""
    ordered: bool = False
    start: int = 1
    items: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    header: bool = False
    src: str = ""
    alt: str = ""


def is_empty(block: Block) -> bool:
    if block.kind == "para":
        return not any(r.text.strip() or r.image for r in block.runs)
    return False


def runs_to_text(runs: list[Run]) -> str:
    out = []
    for r in runs:
        out.append("\n" if r.brk else r.text)
    return "".join(out)
