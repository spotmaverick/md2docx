# -*- coding: utf-8 -*-
"""生成 Md2docs 图标（纯标准库，输出 256x256 PNG + .ico）。"""
from __future__ import annotations

import os
import struct
import zlib

SIZE = 256


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def _rounded(x: int, y: int, w: int, h: int, r: int) -> bool:
    """点 (x, y) 是否落在圆角矩形内。"""
    if x < 0 or y < 0 or x >= w or y >= h:
        return False
    cx = min(max(x, r), w - 1 - r)
    cy = min(max(y, r), h - 1 - r)
    dx, dy = x - cx, y - cy
    return dx * dx + dy * dy <= r * r


def _blanket(x0, y0, x1, y1, radius=0):
    """返回一个判断函数：矩形（可圆角）内部为 True。"""
    def inside(x, y):
        if not (x0 <= x < x1 and y0 <= y < y1):
            return False
        if radius == 0:
            return True
        cx = min(max(x, x0 + radius), x1 - 1 - radius)
        cy = min(max(y, y0 + radius), y1 - 1 - radius)
        dx, dy = x - cx, y - cy
        return dx * dx + dy * dy <= radius * radius
    return inside


def build_png() -> bytes:
    rows = []
    bg = _blanket(0, 0, SIZE, SIZE, 58)
    paper = _blanket(66, 40, 190, 216, 12)
    fold = _blanket(156, 40, 190, 74, 12)          # 折角
    fold_cut = lambda x, y: (x - 156) + (y - 40) < 0   # noqa: E731  斜切

    lines = [
        _blanket(86, 84, 170, 94, 4),
        _blanket(86, 108, 170, 118, 4),
        _blanket(86, 132, 150, 142, 4),
        _blanket(86, 156, 170, 166, 4),
    ]
    accent = _blanket(86, 180, 134, 190, 4)

    for y in range(SIZE):
        row = bytearray()
        for x in range(SIZE):
            r = g = b = 0
            a = 0
            if bg(x, y):
                t = y / SIZE
                r = int(99 + (139 - 99) * t)
                g = int(102 + (92 - 102) * t)
                b = int(241 + (246 - 241) * t)
                a = 255
            if paper(x, y) and not (fold(x, y) and fold_cut(x, y)):
                r, g, b, a = 255, 255, 255, 255
            elif fold(x, y) and not fold_cut(x, y) and bg(x, y):
                r, g, b, a = 214, 219, 254, 255
            for i, ln in enumerate(lines):
                if ln(x, y):
                    r, g, b, a = (99, 102, 241, 255) if i % 2 == 0 else (148, 163, 232, 255)
            if accent(x, y):
                r, g, b, a = 239, 68, 68, 255
            row += bytes((r, g, b, a))
        rows.append(bytes(row))

    raw = b"".join(b"\x00" + r for r in rows)
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(raw, 9))
            + _chunk(b"IEND", b""))


def build_ico(png: bytes) -> bytes:
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 22)
    return header + entry + png


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    png = build_png()
    ico = build_ico(png)
    out_ico = os.path.join(root, "build", "app.ico")
    os.makedirs(os.path.dirname(out_ico), exist_ok=True)
    with open(out_ico, "wb") as f:
        f.write(ico)
    print("icon ->", out_ico, len(ico), "bytes")


if __name__ == "__main__":
    main()
