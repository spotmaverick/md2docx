# -*- coding: utf-8 -*-
"""AST -> TXT（纯文本）。

两种模式：
  plain - 去掉 Markdown 标记，排版成易读的纯文本（默认）
  raw   - 原样输出 Markdown 源文本，仅做换行规范化
"""
from __future__ import annotations

import os
import re

from mdmodel import Block, Run, runs_to_text


def plain_runs(runs: list[Run]) -> str:
    """行内片段 -> 纯文本（链接保留地址，图片退化为占位）。"""
    out = []
    for r in runs or []:
        if r.brk:
            out.append("\n")
            continue
        if r.image:
            out.append("[图片%s]" % ("：" + r.text if r.text else ""))
            continue
        t = r.text or ""
        if r.link and r.link != t:
            t = "%s（%s）" % (t, r.link)
        out.append(t)
    return "".join(out)


def write_txt(blocks: list[Block], out_path: str, mode: str = "plain",
              encoding: str = "utf-8", raw_source: str = "",
              wrap: int = 0) -> None:
    if mode == "raw" and raw_source is not None:
        text = raw_source.replace("\r\n", "\n").replace("\r", "\n")
    else:
        text = "\n".join(_render(blocks, wrap))
        text = re.sub(r"\n{3,}", "\n\n", text).rstrip() + "\n"

    if os.name == "nt":
        text = text.replace("\n", "\r\n")

    enc = (encoding or "utf-8").lower()
    if enc in ("utf-8-bom", "utf8-bom", "utf-8-sig"):
        with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
            f.write(text)
    elif enc in ("gbk", "gb2312", "gb18030"):
        with open(out_path, "w", encoding="gb18030", errors="replace",
                  newline="") as f:
            f.write(text)
    else:
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            f.write(text)


# --------------------------------------------------------------------------- #
def _render(blocks: list[Block], wrap: int = 0, indent: int = 0,
            depth: int = 0) -> list[str]:
    out: list[str] = []
    for b in blocks:
        pad = " " * indent
        if b.kind == "heading":
            lvl = max(1, min(b.level, 6))
            out.append("")
            out.append(pad + "#" * lvl + " " + plain_runs(b.runs).strip())
            out.append("")
        elif b.kind == "para":
            out.append(_wrap(pad + plain_runs(b.runs).strip(), wrap, pad))
        elif b.kind == "code":
            out.append("")
            for line in b.text.split("\n"):
                out.append(pad + "    " + line)
            out.append("")
        elif b.kind == "quote":
            inner = _render(b.items, wrap, 0, depth + 1)
            for line in inner:
                out.append(pad + ("> " if line else ">") + line)
        elif b.kind == "list":
            for i, item in enumerate(b.items):
                marker = ("%d. " % (b.start + i)) if b.ordered else "- "
                out.extend(_render_list_item(item, wrap, indent, marker, depth))
        elif b.kind == "table":
            out.extend(_render_table(b.rows, wrap, indent))
        elif b.kind == "hr":
            out.append("")
            out.append(pad + "-" * 40)
            out.append("")
        elif b.kind == "image":
            out.append(pad + "[图片%s]" % ("：" + b.alt if b.alt else ""))
    return out


def _render_list_item(item: list[Block], wrap: int, indent: int,
                      marker: str, depth: int) -> list[str]:
    """列表项：首行带标记，后续内容缩进对齐。"""
    lines: list[str] = []
    pad = " " * indent
    head_pad = pad + marker
    cont_pad = " " * len(head_pad)
    first = True
    for sub in item:
        if sub.kind == "list":
            lines.extend(_render([sub], wrap, indent + 2, depth + 1))
            continue
        if sub.kind == "table":
            lines.extend(_render_table(sub.rows, wrap, indent + 2))
            continue
        if sub.kind == "code":
            lines.append("")
            for line in sub.text.split("\n"):
                lines.append(cont_pad + "    " + line)
            lines.append("")
            continue
        if sub.kind == "hr":
            lines.append(cont_pad + "-" * 40)
            continue
        if sub.kind == "image":
            lines.append(head_pad if first else cont_pad)
            continue
        text = plain_runs(sub.runs or []).strip()
        if not text:
            continue
        chunk = _wrap(text, wrap, cont_pad if not first else head_pad)
        if first:
            chunk = head_pad + chunk[len(head_pad):] if chunk.startswith(head_pad) \
                else head_pad + chunk
            first = False
        else:
            chunk = cont_pad + chunk
        lines.append(chunk)
    if not lines:
        lines.append(head_pad.rstrip())
    return lines


def _render_table(rows: list[list[list[Block]]], wrap: int = 0,
                  indent: int = 0) -> list[str]:
    if not rows:
        return []
    n_cols = max(len(r) for r in rows)
    cells: list[list[str]] = []
    for r in rows:
        row = []
        for ci in range(n_cols):
            blocks = r[ci] if ci < len(r) else []
            txt = " ".join(plain_runs(b.runs or []).strip() for b in blocks).strip()
            txt = txt.replace("\n", " ")
            row.append(txt)
        cells.append(row)

    widths = [max(_disp_w(row[ci]) for row in cells) for ci in range(n_cols)]
    widths = [min(max(w, 3), 48) for w in widths]

    def line(row):
        parts = []
        for ci, txt in enumerate(row):
            gap = widths[ci] - _disp_w(txt)
            parts.append(txt + " " * max(gap, 0))
        return (" " * indent) + "| " + " | ".join(parts) + " |"

    sep = (" " * indent) + "|-" + "-|-".join("-" * w for w in widths) + "-|"
    out = ["", line(cells[0]), sep]
    out.extend(line(r) for r in cells[1:])
    out.append("")
    return out


def _disp_w(s: str) -> int:
    """按中文字宽 2 计算显示宽度。"""
    w = 0
    for ch in s:
        w += 2 if unicodedata_east_asian(ch) else 1
    return w


def unicodedata_east_asian(ch: str) -> bool:
    import unicodedata
    return unicodedata.east_asian_width(ch) in ("W", "F")


def _wrap(text: str, wrap: int, pad: str) -> str:
    if not wrap or wrap < 20:
        return text
    limit = max(wrap - len(pad), 20)
    out, cur, width = [], "", 0
    for ch in text:
        w = 2 if unicodedata_east_asian(ch) else 1
        if width + w > limit and cur:
            out.append(cur)
            cur, width = "", 0
        cur += ch
        width += w
    out.append(cur)
    return ("\n" + pad).join(out)
