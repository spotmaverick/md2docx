# -*- coding: utf-8 -*-
"""AST -> RTF。

.doc（Word 97-2003）与 .wps 都由本渲染器产出：RTF 是 Word / WPS / LibreOffice
都能原生打开且完整保留格式的通用载体，文件扩展名分别为 .doc / .wps。
"""
from __future__ import annotations

import theme
from imgsrc import fetch as fetch_image
from mdmodel import Block, Run, runs_to_text

# 页面尺寸（twips，1cm = 567twips）
PAGE_W = 11907
CONTENT_W = PAGE_W - 2 * 1418
# 版心高度（A4 高 16840 - 上下边距 2*1418）
CONTENT_H = 16840 - 2 * 1418

F_BODY, F_MONO, F_HEAD = 0, 1, 2


# --------------------------------------------------------------------------- #
# 转义
# --------------------------------------------------------------------------- #
def _utf16_units(cp: int):
    if cp < 0x10000:
        return [cp]
    cp -= 0x10000
    return [0xD800 + (cp >> 10), 0xDC00 + (cp & 0x3FF)]


def esc(s: str) -> str:
    """RTF 转义：ASCII 保留原样，非 ASCII 使用 \\uN + 单字节回退（\\uc1）。"""
    out = []
    for ch in s:
        o = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == "{":
            out.append("\\{")
        elif ch == "}":
            out.append("\\}")
        elif ch == "\n":
            out.append("\\line ")
        elif ch == "\t":
            out.append("\\tab ")
        elif o < 0x20:
            out.append(" ")
        elif o < 0x80:
            out.append(ch)
        else:
            for u in _utf16_units(o):
                out.append("\\u%d" % (u if u < 32768 else u - 65536))
                out.append("\\'3f")
    return "".join(out)


# --------------------------------------------------------------------------- #
class RtfWriter:
    def __init__(self, base_dir: str = ""):
        self.base_dir = base_dir
        self.colors: dict[str, int] = {}
        self._color_order: list[str] = []
        self.body: list[str] = []

    # -- 颜色表 ---------------------------------------------------------- #
    def c(self, hex_color: str | None) -> int:
        if not hex_color:
            return 0
        h = hex_color.lstrip("#").upper()
        if h not in self.colors:
            self._color_order.append(h)
            self.colors[h] = len(self._color_order)
        return self.colors[h]

    # -- 文档装配 -------------------------------------------------------- #
    def dumps(self) -> str:
        colortbl = ";".join(
            [""] + ["\\red%d\\green%d\\blue%d" % (int(h[0:2], 16),
                                                  int(h[2:4], 16),
                                                  int(h[4:6], 16))
                    for h in self._color_order]
        )
        head = [
            "{\\rtf1\\ansi\\ansicpg936\\deff0\\deflang1033\\deflangfe2052\\uc1",
            "{\\*\\generator Md2docs;}",
            "{\\fonttbl"
            "{\\f0\\fnil\\charset134 Microsoft YaHei;}"
            "{\\f1\\fmodern\\charset0 Consolas;}"
            "{\\f2\\fnil\\charset134 Microsoft YaHei;}}",
            "{\\colortbl" + colortbl + ";}",
            "\\viewkind4\\uc1\\pard",
            "\\paperw%d\\paperh16840\\margl1418\\margr1418\\margt1418\\margb1418"
            % PAGE_W,
            "\\f0\\fs22\\cf%d" % self.c(theme.TEXT),
        ]
        return "\n".join(head) + "\n" + "".join(self.body) + "\n}\n"

    # -- 行内 ------------------------------------------------------------ #
    def _run(self, r: Run, size: float = theme.BODY_SIZE,
             base_color: str | None = None) -> str:
        if r.brk:
            return "\\line "
        if r.image:
            return self._picture(r.image, r.text)
        text = r.text or ""
        if not text:
            return ""
        if r.link:
            return self._hyperlink(r.link, text, size)

        pre: list[str] = []
        post: list[str] = []
        if r.code:
            pre.append("\\f%d " % F_MONO)
            pre.append("\\fs%d " % int(round(9.5 * 2)))
            pre.append("\\cf%d " % self.c(theme.CODE_FG))
            post.append("\\cf%d " % self.c(base_color or theme.TEXT))
            post.append("\\fs%d " % int(round(size * 2)))
            post.append("\\f%d " % F_BODY)
        elif base_color:
            pre.append("\\cf%d " % self.c(base_color))
        if r.bold:
            pre.append("\\b ")
            post.append("\\b0 ")
        if r.italic:
            pre.append("\\i ")
            post.append("\\i0 ")
        if r.strike:
            pre.append("\\strike ")
            post.append("\\strike0 ")
        if r.sup:
            pre.append("\\super ")
            post.append("\\super0 ")
        if r.sub:
            pre.append("\\sub ")
            post.append("\\sub0 ")
        return "{" + "".join(pre) + esc(text) + "".join(reversed(post)) + "}"

    def _hyperlink(self, url: str, text: str, size: float) -> str:
        inner = ("{\\f%d\\fs%d\\cf%d\\ul %s}"
                 % (F_BODY, int(round(size * 2)), self.c(theme.LINK), esc(text)))
        inst = esc(url).replace('"', "'")
        return ("{\\field{\\*\\fldinst{HYPERLINK \"%s\"}}"
                "{\\fldrslt%s}}" % (inst, inner))

    def _runs(self, runs: list[Run], size: float = theme.BODY_SIZE,
              base_color: str | None = None) -> str:
        return "".join(self._run(r, size, base_color) for r in runs)

    # -- 图片 ------------------------------------------------------------ #
    def _picture(self, src: str, alt: str) -> str:
        """嵌入图片：先下载/读取到内存，PNG/JPEG 以 RTF blip 真正嵌入。

        显示尺寸按 15 twips/px（96dpi）等比计算，不超过版心宽/高。
        """
        got = fetch_image(src, self.base_dir)
        if not got or got.fmt not in ("png", "jpeg"):
            return esc("[图片%s]" % ("：" + alt if alt else ""))
        blip = "\\pngblip" if got.fmt == "png" else "\\jpegblip"
        pw, ph = got.width, got.height
        if pw <= 0 or ph <= 0:          # 识别失败时兜底，仅保证能渲染
            pw, ph = 600, 400
        scale = min(CONTENT_W / (pw * 15.0),
                    CONTENT_H / (ph * 15.0), 1.0)
        goal_w = int(pw * 15 * scale)
        goal_h = int(ph * 15 * scale)
        return ("{\\*\\shppict{\\pict%s\\picw%d\\pich%d"
                "\\picwgoal%d\\pichgoal%d\n%s\n}}"
                % (blip, pw, ph, goal_w, goal_h, got.data.hex()))

    # -- 块级 ------------------------------------------------------------ #
    def add(self, block: Block, **ctx):
        k = block.kind
        if k == "heading":
            self._heading(block)
        elif k == "para":
            self._para(block)
        elif k == "code":
            self._code(block)
        elif k == "quote":
            self._quote(block)
        elif k == "list":
            self._list(block, level=ctx.get("level", 1))
        elif k == "table":
            self._table(block)
        elif k == "hr":
            self._hr()
        elif k == "image":
            self.body.append("\\pard\\qc " + self._picture(block.src, block.alt)
                             + "\\par\n")

    def _heading(self, b: Block):
        lvl = max(1, min(b.level, 6))
        half = int(round(theme.heading_size(lvl) * 2))
        # 与 Markdown 渲染一致：标题不着色，只用字号 + 字重
        props = ("\\pard\\keepn\\sb%d\\sa120\\sl276\\slmult1\\f%d\\fs%d\\b\\cf%d "
                 % (280 if lvl <= 2 else 160, F_BODY, half,
                    self.c(theme.heading_color(lvl))))
        self.body.append(props + self._runs(b.runs, theme.heading_size(lvl),
                                            theme.heading_color(lvl))
                         + "\\b0\\par\n")

    def _para(self, b: Block):
        self.body.append(
            "\\pard\\sa120\\sl336\\slmult1\\f%d\\fs%d\\cf%d %s\\par\n"
            % (F_BODY, int(theme.BODY_SIZE * 2), self.c(theme.TEXT),
               self._runs(b.runs))
        )

    def _code(self, b: Block):
        lines = b.text.split("\n") or [""]
        body = "\\line ".join(esc(l) if l else " " for l in lines)
        self.body.append(
            "\\pard\\sb120\\sa120\\li340\\ri340\\sl260\\slmult1"
            "\\f%d\\fs19\\cf%d\\cbpat%d %s\\par\n"
            % (F_MONO, self.c(theme.CODE_FG), self.c(theme.CODE_BG), body)
        )

    def _quote(self, b: Block, depth: int = 1):
        indent = 567 * depth
        for child in b.items:
            if child.kind == "quote":
                self._quote(child, depth + 1)
                continue
            if child.kind == "list":
                self._list(child, level=1, extra_indent=indent)
                continue
            if child.kind in ("table", "code", "hr", "image"):
                self.add(child)
                continue
            self.body.append(
                "\\pard\\li%d\\ri170\\sa100\\sl300\\slmult1\\i\\cf%d"
                "\\brdrl\\brdrs\\brdrw30\\brsp80 %s\\i0\\par\n"
                % (indent, self.c(theme.QUOTE_FG),
                   self._runs(child.runs or [], 10.5, theme.QUOTE_FG))
            )

    def _list(self, b: Block, level: int = 1, extra_indent: int = 0,
              counter: list[int] | None = None):
        bullet = theme.LIST_BULLETS[min(level - 1, len(theme.LIST_BULLETS) - 1)]
        for i, item in enumerate(b.items):
            li = extra_indent + 720 + (level - 1) * 360
            num = (b.start + i) if b.ordered else 0
            marker = ("%d." % num) if b.ordered else bullet
            head = ("\\pard\\li%d\\fi-360\\tx%d\\sa80\\sl300\\slmult1"
                    % (li, li))
            first = True
            for sub in item:
                if sub.kind == "list":
                    self._list(sub, level + 1, extra_indent)
                    continue
                if sub.kind == "table":
                    self._table(sub)
                    continue
                if sub.kind == "code":
                    self._code(sub)
                    continue
                if sub.kind == "hr":
                    self._hr()
                    continue
                if sub.kind == "image":
                    self.body.append("\\pard\\qc "
                                     + self._picture(sub.src, sub.alt) + "\\par\n")
                    continue
                text = self._runs(sub.runs or [])
                if first:
                    self.body.append(head + esc(marker) + "\\tab " + text + "\\par\n")
                    first = False
                else:
                    self.body.append(
                        "\\pard\\li%d\\sa80\\sl300\\slmult1 %s\\par\n" % (li, text))

    def _table(self, b: Block):
        rows = b.rows
        if not rows:
            return
        n_cols = max(len(r) for r in rows)
        if n_cols == 0:
            return

        # 列宽：按内容长度比例分配
        weights = []
        for ci in range(n_cols):
            w = 0
            for r in rows:
                if ci < len(r):
                    w = max(w, len(runs_to_text(
                        [run for blk in r[ci] for run in (blk.runs or [])])))
            weights.append(max(w, 4))
        total = sum(weights)
        widths = [max(int(CONTENT_W * w / total), 900) for w in weights]
        scale = CONTENT_W / sum(widths)
        widths = [int(w * scale) for w in widths]

        self.body.append("\\pard\\sa60\\par\n")
        for ri, row in enumerate(rows):
            is_head = b.header and ri == 0
            defs = ["\\trowd\\trgaph108\\trleft0\\trbrdrt\\brdrs\\brdrw10"
                    "\\trbrdrl\\brdrs\\brdrw10\\trbrdrb\\brdrs\\brdrw10"
                    "\\trbrdrr\\brdrs\\brdrw10"]
            if is_head:
                defs.append("\\trhdr")
            x = 0
            for ci in range(n_cols):
                x += widths[ci]
                defs.append("\\clbrdrt\\brdrw10\\brdrs\\clbrdrl\\brdrw10\\brdrs"
                            "\\clbrdrb\\brdrw10\\brdrs\\clbrdrr\\brdrw10\\brdrs"
                            "\\clvertalc")
                if is_head:
                    defs.append("\\clcbpat%d" % self.c(theme.TABLE_HEAD_BG))
                elif ri % 2 == 1:
                    defs.append("\\clcbpat%d" % self.c(theme.TABLE_ALT_BG))
                defs.append("\\cellx%d" % x)
            self.body.append("".join(defs) + "\n")

            for ci in range(n_cols):
                blocks = row[ci] if ci < len(row) else []
                buf = []
                for blk in blocks:
                    buf.append(self._runs(blk.runs or [], 10,
                                          theme.QUOTE_FG if is_head else None))
                content = "".join(buf)
                if is_head:
                    content = "{\\b " + content + "\\b0 }"
                self.body.append("\\pard\\intbl\\li57\\ri57\\sa60\\sl276\\slmult1"
                                 + content + "\\cell\n")
            self.body.append("\\row\n")
        self.body.append("\\pard\\sa60\\par\n")

    def _hr(self):
        self.body.append(
            "\\pard\\sb120\\sa120\\brdrb\\brdrs\\brdrw15\\brsp80\\fs2 \\par\n")


def write_rtf(blocks: list[Block], out_path: str, base_dir: str = "") -> None:
    w = RtfWriter(base_dir)
    for b in blocks:
        w.add(b)
    with open(out_path, "w", encoding="ascii", errors="replace", newline="\n") as f:
        f.write(w.dumps())
