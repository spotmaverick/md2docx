# -*- coding: utf-8 -*-
"""转换结果自检：DOCX 结构、RTF 语法、TXT 内容。"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "src"))


def check_rtf(path: str) -> list[str]:
    errs = []
    data = open(path, "rb").read()
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as e:
        errs.append("RTF 不是纯 ASCII：%s" % e)
        return errs

    depth = 0
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            if i + 1 < n and text[i + 1] == "'":
                i += 4
                continue
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth < 0:
                errs.append("花括号不匹配：位置 %d 出现多余的 }" % i)
                break
        i += 1
    if depth != 0:
        errs.append("花括号不匹配：结束时仍差 %d 个 }" % depth)

    if not text.startswith("{\\rtf1"):
        errs.append("缺少 \\rtf1 头部")
    if "\\uc1" not in text[:200]:
        errs.append("缺少 \\uc1（Unicode 回退声明）")
    if not text.rstrip().endswith("}"):
        errs.append("文件未以 } 结束")

    # 颜色表索引 must exist
    m = re.search(r"\{\\colortbl([^}]*)\}", text)
    if not m:
        errs.append("缺少 \\colortbl")
        ncolors = 0
    else:
        ncolors = m.group(1).count(";")
    for idx in set(int(x) for x in re.findall(r"\\cf(\d+)", text)):
        if idx >= ncolors + 1:
            errs.append("\\cf%d 超出颜色表范围（共 %d 项）" % (idx, ncolors))
    for idx in set(int(x) for x in re.findall(r"\\cbpat(\d+)", text)):
        if idx >= ncolors + 1:
            errs.append("\\cbpat%d 超出颜色表范围（共 %d 项）" % (idx, ncolors))

    # 表格：每行 \cell 数与 cellx 数一致
    for row in re.findall(r"\\trowd(.*?)\\row", text, re.S):
        ncellx = row.count("\\cellx")
        # \cell 出现在行内容里，需排除 \cellx
        ncell = len(re.findall(r"\\cell(?![a-zA-Z])", row))
        if ncellx and ncell and ncellx != ncell:
            errs.append("表格行列数不一致：cellx=%d cell=%d" % (ncellx, ncell))

    # 每个 \uN 后必须紧跟 \'3f 单字节回退（\uc1）
    total = len(re.findall(r"\\u-?\d+(?!\d)", text))
    paired = len(re.findall(r"\\u-?\d+(?!\d)\\'3f", text))
    if total != paired:
        errs.append("有 %d/%d 处 \\uN 缺少单字节回退" % (total - paired, total))
    return errs


def check_docx(path: str) -> list[str]:
    from docx import Document
    errs = []
    doc = Document(path)
    heads = [p for p in doc.paragraphs if p.style.name.startswith("Heading")]
    if not heads:
        errs.append("没有标题段落")
    if not doc.tables:
        errs.append("没有表格")
    txt = "\n".join(p.text for p in doc.paragraphs)
    if len(txt.strip()) < 20:
        errs.append("正文内容为空")
    body_xml = doc.element.body.xml
    if "w:hyperlink" not in body_xml:
        errs.append("没有生成超链接")
    if "w:shd" not in body_xml:
        errs.append("没有底纹（代码块/表格）")
    return errs


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "_test_out"
    stem = sys.argv[2] if len(sys.argv) > 2 else "示例文档"

    summary = {}
    for ext, checker in ((".docx", check_docx), (".doc", check_rtf),
                         (".wps", check_rtf), (".txt", None)):
        fp = os.path.join(out, stem + ext)
        if not os.path.isfile(fp):
            print("[缺失] %s" % fp)
            continue
        size = os.path.getsize(fp)
        if checker is None:
            print("[OK]   %-6s %8d B" % (ext, size))
            continue
        errs = checker(fp)
        if errs:
            print("[ERR]  %-6s %8d B" % (ext, size))
            for e in errs:
                print("         - %s" % e)
            summary[ext] = errs
        else:
            print("[OK]   %-6s %8d B  结构检查通过" % (ext, size))
    return 1 if summary else 0


if __name__ == "__main__":
    sys.exit(main())
