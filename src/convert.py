# -*- coding: utf-8 -*-
"""转换调度：Markdown 文件 -> docx / doc / wps / txt。"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field

import com_helper
import docx_writer
import i18n
import rtf_writer
import txt_writer
from mdparse import parse_markdown

# 只保留与语言无关的信息；显示名称一律经 format_label() 取当前语言文案
FORMATS = {
    "docx": {"ext": ".docx"},
    "doc": {"ext": ".doc"},
    "wps": {"ext": ".wps"},
    "txt": {"ext": ".txt"},
}
FORMAT_ORDER = ["docx", "doc", "wps", "txt"]


def format_label(fmt: str) -> str:
    """输出格式的显示名称（随界面语言）。"""
    return i18n.t("fmt.label." + fmt)

# RTF 载体：Word / WPS / LibreOffice 均可原生打开
RTF_BACKED = {"doc", "wps"}

ENCODINGS = ["utf-8", "utf-8-bom", "gbk"]


@dataclass
class Result:
    source: str
    name: str
    fmt: str
    target: str = ""
    ok: bool = False
    message: str = ""
    engine: str = ""
    size: int = 0
    warnings: list[str] = field(default_factory=list)


def read_text(path: str) -> tuple[str, str]:
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "utf-16", "gb18030", "big5"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8(replace)"


def capabilities() -> dict:
    return {"word": com_helper.has_word(), "wps": com_helper.has_wps()}


def convert_file(md_path: str, formats: list[str], out_dir: str | None = None,
                 native: bool = False, txt_mode: str = "plain",
                 txt_encoding: str = "utf-8", overwrite: bool = True) -> list[Result]:
    md_path = os.path.abspath(md_path)
    base_dir = os.path.dirname(md_path)
    stem = os.path.splitext(os.path.basename(md_path))[0]
    out_dir = os.path.abspath(out_dir) if out_dir else base_dir
    os.makedirs(out_dir, exist_ok=True)

    source, _enc = read_text(md_path)
    blocks = parse_markdown(source)

    results: list[Result] = []
    tmp_files: list[str] = []

    try:
        # docx 先生成，供原生模式复用
        native_docx = ""
        if native and any(f in ("doc", "wps") for f in formats):
            native_docx = os.path.join(tempfile.gettempdir(),
                                       "md2docs_%s.docx" % os.getpid())
            tmp_files.append(native_docx)

        for fmt in FORMAT_ORDER:
            if fmt not in formats:
                continue
            res = Result(source=md_path, name=os.path.basename(md_path), fmt=fmt)
            ext = FORMATS[fmt]["ext"]
            target = _unique(os.path.join(out_dir, stem + ext), overwrite)
            try:
                if fmt == "docx":
                    docx_writer.write_docx(blocks, target, base_dir, title=stem)
                    res.engine = i18n.t("engine.docx")

                elif fmt == "txt":
                    txt_writer.write_txt(blocks, target, mode=txt_mode,
                                         encoding=txt_encoding,
                                         raw_source=source)
                    res.engine = i18n.t("engine.builtin")

                else:  # doc / wps
                    done = False
                    if native:
                        if not native_docx or not os.path.isfile(native_docx):
                            docx_writer.write_docx(blocks, native_docx, base_dir,
                                                   title=stem)
                        ok, msg = com_helper.save_as(native_docx, target)
                        if ok:
                            res.engine = i18n.t("engine.office")
                            done = True
                        else:
                            res.warnings.append(
                                i18n.t("warn.native_failed", msg=msg))
                    if not done:
                        rtf_writer.write_rtf(blocks, target, base_dir)
                        res.engine = i18n.t("engine.rtf")

                res.target = target
                res.ok = os.path.isfile(target)
                res.size = os.path.getsize(target) if res.ok else 0
                if not res.ok:
                    res.message = i18n.t("convert.no_output")
            except Exception as exc:
                res.ok = False
                res.message = "%s: %s" % (type(exc).__name__, exc)
            results.append(res)
    finally:
        for p in tmp_files:
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except OSError:
                pass

    return results


def _unique(path: str, overwrite: bool) -> str:
    if overwrite or not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    i = 1
    while os.path.exists("%s(%d)%s" % (stem, i, ext)):
        i += 1
    return "%s(%d)%s" % (stem, i, ext)
