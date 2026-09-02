# -*- coding: utf-8 -*-
"""Markdown 文本 -> 中间语义模型（AST）。

策略：先用 CommonMark 兼容的 `markdown-it-py` 把 md 渲染成 HTML，再用
BeautifulSoup 解析成 AST。这样表格、围栏代码块、任意缩进的嵌套列表等语法都能
被正确覆盖，不用自己造 Markdown 解析器。
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup, NavigableString, Tag
from markdown_it import MarkdownIt
from mdit_py_plugins.tasklists import tasklists_plugin

from mdmodel import Block, Run, runs_to_text

# 代码块语言：`language-python` / `lang-python`
_LANG_RE = re.compile(r"(?:language|lang)-([A-Za-z0-9_+#.-]+)")

DONE, TODO = "\u2611 ", "\u2610 "          # ☑ / ☐


def _engine() -> MarkdownIt:
    md = (MarkdownIt("commonmark")
          .enable("table")
          .enable("strikethrough")
          .use(tasklists_plugin))
    md.options["html"] = True
    return md


def parse_markdown(text: str) -> list[Block]:
    if text.startswith("\ufeff"):
        text = text[1:]
    html = _engine().render(text or "")
    soup = BeautifulSoup(html, "html.parser")
    return _compact(_convert_children(soup.children))


# --------------------------------------------------------------------------- #
# 块级
# --------------------------------------------------------------------------- #
_BLOCK_TAGS = {
    "h1", "h2", "h3", "h4", "h5", "h6", "p", "pre", "blockquote",
    "ul", "ol", "table", "hr", "div", "section", "article", "main",
    "figure", "dl", "dd", "dt", "body",
}
_SKIP_TAGS = {"script", "style", "head", "title", "meta", "link", "input"}


def _convert_children(children) -> list[Block]:
    out: list[Block] = []
    for child in children:
        if isinstance(child, NavigableString):
            s = str(child)
            if s.strip():
                out.append(Block("para", runs=[Run(text=" ".join(s.split()))]))
            continue
        if not isinstance(child, Tag):
            continue

        name = child.name.lower()
        if name in _SKIP_TAGS:
            continue

        if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            out.append(Block("heading", level=int(name[1]), runs=_inline(child)))

        elif name == "p":
            imgs = child.find_all("img", recursive=False)
            rest = "".join(
                c.get_text() for c in child.children
                if not (isinstance(c, Tag) and c.name == "img")
            ).strip()
            if imgs and not rest:
                for img in imgs:
                    out.append(Block("image", src=img.get("src") or "",
                                     alt=img.get("alt") or ""))
            else:
                out.append(Block("para", runs=_inline(child)))

        elif name == "pre":
            code = child.find("code")
            body = code if code is not None else child
            lang = ""
            m = _LANG_RE.search(" ".join(body.get("class") or []))
            if m:
                lang = m.group(1)
            out.append(Block("code", text=_code_text(body), lang=lang))

        elif name == "blockquote":
            out.append(Block("quote", items=_convert_children(child.children)))

        elif name in ("ul", "ol"):
            out.append(_convert_list(child))

        elif name == "table":
            out.append(_convert_table(child))

        elif name == "hr":
            out.append(Block("hr"))

        else:
            # div / section / dd / figure 等容器：递归展开
            out.extend(_convert_children(child.children))
    return out


def _code_text(node: Tag) -> str:
    txt = "".join(str(c) if isinstance(c, NavigableString) else c.get_text()
                  for c in node.children)
    return txt.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")


def _convert_list(ul: Tag) -> Block:
    ordered = ul.name.lower() == "ol"
    start = 1
    if ordered:
        try:
            start = int(ul.get("start", 1))
        except (TypeError, ValueError):
            start = 1
    items = []
    for li in ul.find_all("li", recursive=False):
        items.append(_li_content(li))
    return Block("list", ordered=ordered, start=start, items=items)


def _li_content(li: Tag) -> list[Block]:
    prefix = ""
    cb = None
    for inp in li.find_all("input", attrs={"type": "checkbox"}):
        if inp.parent is li:
            cb = inp
            break
    if cb is not None:
        prefix = DONE if cb.has_attr("checked") else TODO
        cb.decompose()

    blocks: list[Block] = []
    pending: list[Run] = []

    def flush():
        if pending:
            blocks.append(Block("para", runs=list(pending)))
            pending.clear()

    for child in list(li.children):
        if isinstance(child, NavigableString):
            s = str(child)
            if s.strip():
                pending.extend(_inline(child))
            continue
        if not isinstance(child, Tag):
            continue
        name = child.name.lower()
        if name in _SKIP_TAGS:
            continue
        if name in _BLOCK_TAGS:
            flush()
            blocks.extend(_convert_children([child]))
        else:
            pending.extend(_inline(child))
    flush()

    if prefix:
        if blocks and blocks[0].kind == "para":
            blocks[0].runs.insert(0, Run(text=prefix))
        else:
            blocks.insert(0, Block("para", runs=[Run(text=prefix)]))
    if not blocks:
        blocks = [Block("para", runs=[])]
    return blocks


def _convert_table(table: Tag) -> Block:
    rows: list[list[list[Block]]] = []

    def collect(container):
        for tr in container.find_all("tr", recursive=False):
            cells: list[list[Block]] = []
            for td in tr.find_all(["th", "td"], recursive=False):
                inner = _convert_children(td.children)
                cells.append(inner or [Block("para", runs=[])])
            if cells:
                rows.append(cells)

    thead = table.find("thead")
    tbody = table.find("tbody")
    if thead:
        collect(thead)
    if tbody:
        collect(tbody)
    if not thead and not tbody:
        collect(table)

    width = max((len(r) for r in rows), default=0)
    for r in rows:
        while len(r) < width:
            r.append([Block("para", runs=[])])

    return Block("table", rows=rows, header=bool(table.find("th")))


# --------------------------------------------------------------------------- #
# 行内
# --------------------------------------------------------------------------- #
def _inline(node, bold=False, italic=False, code=False, strike=False,
            sup=False, sub=False, link=None) -> list[Run]:
    if isinstance(node, NavigableString):
        text = str(node)
        if not text:
            return []
        if code:
            return [Run(text=text, bold=bold, italic=italic, code=True,
                        strike=strike, sup=sup, sub=sub, link=link)]
        collapsed = re.sub(r"\s+", " ", text)
        if collapsed.startswith(" ") and not _need_leading_space(node):
            collapsed = collapsed.lstrip(" ")
        return [Run(text=collapsed, bold=bold, italic=italic, strike=strike,
                    sup=sup, sub=sub, link=link)]

    if not isinstance(node, Tag):
        return []

    name = node.name.lower()
    if name in _SKIP_TAGS:
        return []
    if name == "br":
        return [Run(brk=True)]
    if name == "img":
        return [Run(image=node.get("src") or "", text=node.get("alt") or "")]

    n_bold = bold or name in ("strong", "b")
    n_italic = italic or name in ("em", "i")
    n_code = code or name in ("code", "kbd", "samp", "tt")
    n_strike = strike or name in ("del", "s", "strike")
    n_sup = sup or name == "sup"
    n_sub = sub or name == "sub"
    n_link = link
    if name == "a":
        href = node.get("href") or ""
        if href and not href.startswith("#"):
            n_link = href

    if name == "a" and n_link and not node.get_text().strip():
        return [Run(text=n_link, link=n_link)]

    runs: list[Run] = []
    for child in node.children:
        runs.extend(_inline(child, n_bold, n_italic, n_code, n_strike,
                            n_sup, n_sub, n_link))
    return runs


def _need_leading_space(node: NavigableString) -> bool:
    prev = node.previous_sibling
    if prev is None:
        return False
    if isinstance(prev, Tag):
        return True
    return not str(prev).endswith(" ")


# --------------------------------------------------------------------------- #
def _compact(blocks: list[Block]) -> list[Block]:
    out: list[Block] = []
    for b in blocks:
        if b.kind == "para" and not runs_to_text(b.runs).strip():
            continue
        if b.kind == "quote" and not b.items:
            continue
        out.append(b)
    return out
