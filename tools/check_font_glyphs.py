# -*- coding: utf-8 -*-
"""界面文案的「字形 + 编码」可用性检查。

两类坑，都属于"开发机上看着没事、换个环境就炸"：

1. **字体缺字**。微软雅黑（含 YaHei UI）与 Segoe UI **都没有 U+2713 / U+2715**
   （实测 GDI ``GetGlyphIndicesW`` 返回 ``0xFFFF``＝缺字）。Windows 上的 Tk 走 GDI
   绘制，GDI 不像 DirectWrite 那样自动做字体回退，于是结果表状态列的 ``✓`` / ``✕``
   会变成方框或空白。
2. **编码打不出**。控制台与管道默认是 GBK(936)。``--selftest`` 会把结果表逐行打到
   控制台，``print('✓')`` 直接抛 ``UnicodeEncodeError``，一路冒到 main 的兜底分支，
   把「自检脚本跑一次转换」放大成「程序启动失败」的模态框。

所以判据是两条一起成立：界面用到的每个非 ASCII 字符，**既要在 UI 字体里有字形，
又要能被 GBK 编码**。新增文案时跑一次本工具即可，不必再靠肉眼盯截图。

用法：
    python tools/check_font_glyphs.py
    python tools/check_font_glyphs.py -v      额外列出每个字符的出处

退出码：0 = 通过；1 = 有问题。
"""
from __future__ import annotations

import argparse
import ctypes
import os
import sys
import tkinter as tk
import tkinter.font as tkfont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import i18n        # noqa: E402

# 与 gui._init_fonts 相同的回退链，判据必须与界面实际用到的字体一致
UI_FALLBACK = ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI")

GGI_MARK_NONEXISTING_GLYPHS = 0x0001


class LOGFONTW(ctypes.Structure):
    _fields_ = [("lfHeight", ctypes.c_long), ("lfWidth", ctypes.c_long),
                ("lfEscapement", ctypes.c_long), ("lfOrientation", ctypes.c_long),
                ("lfWeight", ctypes.c_long), ("lfItalic", ctypes.c_byte),
                ("lfUnderline", ctypes.c_byte), ("lfStrikeOut", ctypes.c_byte),
                ("lfCharSet", ctypes.c_byte), ("lfOutPrecision", ctypes.c_byte),
                ("lfClipPrecision", ctypes.c_byte), ("lfQuality", ctypes.c_byte),
                ("lfPitchAndFamily", ctypes.c_byte),
                ("lfFaceName", ctypes.c_wchar * 32)]


def _missing_glyphs(face: str, chars: list[str]) -> set[str]:
    """返回该字体里**没有字形**的字符集合。

    注意必须用 ``CreateFontIndirectW`` + ``LOGFONTW``：早先误用 A 版接口传 UTF-16
    字节串，字体名根本没生效，所有字符都"查不到"，会得出与事实相反的结论。
    """
    gdi = ctypes.windll.gdi32
    user = ctypes.windll.user32

    lf = LOGFONTW()
    lf.lfHeight = -24
    lf.lfWeight = 400
    lf.lfCharSet = 1          # DEFAULT_CHARSET：避免 GDI 悄悄替换字体
    lf.lfFaceName = face

    hdc = gdi.CreateCompatibleDC(user.GetDC(0))
    font = gdi.CreateFontIndirectW(ctypes.byref(lf))
    old = gdi.SelectObject(hdc, font)
    try:
        text = "".join(chars)
        out = (ctypes.c_ushort * len(chars))()
        gdi.GetGlyphIndicesW(hdc, ctypes.c_wchar_p(text), len(chars), out,
                             GGI_MARK_NONEXISTING_GLYPHS)
        return {ch for ch, idx in zip(chars, out) if idx == 0xFFFF}
    finally:
        gdi.SelectObject(hdc, old)
        gdi.DeleteObject(font)
        gdi.DeleteDC(hdc)
        user.ReleaseDC(0, user.GetDC(0))


def _pick_ui_font() -> str:
    root = tk.Tk()
    root.withdraw()
    try:
        fams = set(tkfont.families(root))
    finally:
        root.destroy()
    for name in UI_FALLBACK:
        if name in fams:
            return name
    return UI_FALLBACK[-1]


def _collect_chars() -> tuple[list[str], dict[str, list[str]]]:
    """收集界面文案里用到的全部非 ASCII 字符，并记住每个字符的出处。"""
    chars: set[str] = set()
    origin: dict[str, list[str]] = {}
    for lang, table in i18n.STRINGS.items():
        for key, text in table.items():
            for ch in text:
                if ord(ch) < 128:
                    continue
                chars.add(ch)
                tag = "%s:%s" % (lang, key)
                bucket = origin.setdefault(ch, [])
                if tag not in bucket and len(bucket) < 4:
                    bucket.append(tag)
    return sorted(chars), origin


def _describe(ch: str) -> str:
    """用码位描述字符——直接打印字符本身就会触发本次要防的那个编码错误。"""
    return "U+%04X" % ord(ch)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    face = _pick_ui_font()
    chars, origin = _collect_chars()
    print("[glyph] UI 字体 = %s；界面文案用到 %d 个非 ASCII 字符"
          % (face, len(chars)))

    missing = _missing_glyphs(face, chars)
    unencodable = set()
    for ch in chars:
        try:
            ch.encode("gbk")
        except UnicodeEncodeError:
            unencodable.add(ch)

    problems: list[str] = []
    for ch in sorted(missing | unencodable):
        why = []
        if ch in missing:
            why.append("字体 %s 缺字形" % face)
        if ch in unencodable:
            why.append("GBK 打不出（--selftest 打到控制台会崩）")
        problems.append("%s  %s  出自 %s"
                        % (_describe(ch), "；".join(why),
                           ", ".join(origin.get(ch, ["?"]))))

    print("[glyph] 缺字形 %d 个；GBK 打不出 %d 个"
          % (len(missing), len(unencodable)))
    if args.verbose:
        for ch in chars:
            mark = "缺" if ch in missing else (
                "GBK" if ch in unencodable else "OK")
            print("        %-8s %-4s %s" % (_describe(ch), mark,
                                            ", ".join(origin.get(ch, []))))

    if problems:
        print("\n[glyph] 失败，共 %d 个字符不可用：" % len(problems))
        for p in problems:
            print("   -", p)
        print("\n   界面文案只允许使用「UI 字体有字形 + GBK 可编码」的字符。")
        print("   GB2312 符号区是安全来源：√（U+221A） ×（U+00D7） ● ○ ■ □ ☆ ★ ※")
        print("   不安全示例：U+2713 / U+2715 / U+2705 / U+274C / U+2714 / U+2717")
        return 1
    print("\n[glyph] 通过：界面文案全部有字形且可被 GBK 编码")
    return 0


if __name__ == "__main__":
    sys.exit(main())
