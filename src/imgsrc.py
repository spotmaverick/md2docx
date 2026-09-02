# -*- coding: utf-8 -*-
"""图片资源解析：把 md 里的图片引用统一解析为可嵌入的图片字节。

支持来源：
  - http(s)://…           网络图片（先下载到内存）
  - //host/path.png       协议相对地址（按 https 补全）
  - data:image/…;base64,.. 内嵌图片
  - file:///C:/a/b.png     本地 URI
  - C:\\a\\b.png / 相对路径   本地文件

docx / doc / wps 三种可嵌入图片的格式共用本模块：下载成功后再由渲染器
把图片真正嵌入文档（而不是写一个指向图片的链接或占位文本）。

同时返回格式与像素尺寸，供渲染器按“96dpi 基准、不超过版心宽度/高度、
保持纵横比”计算实际排版尺寸。解析失败返回 None，由渲染器自行降级。
"""
from __future__ import annotations

import base64
import os
import struct
import urllib.request
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

UA = {"User-Agent": "Mozilla/5.0 Md2docs"}
# 单张图片上限（RTF 会把图片以 hex 内联进文本，必须设上限防内存爆炸）
MAX_BYTES = 40 * 1024 * 1024


@dataclass
class Image:
    data: bytes            # 原始图片字节（PNG / JPEG / GIF / BMP / TIFF / WebP…）
    fmt: str               # png / jpeg / gif / bmp / tiff / webp / svg / unknown
    width: int             # 像素宽（识别失败为 0）
    height: int            # 像素高（识别失败为 0）


# --------------------------------------------------------------------------- #
# 格式 / 像素识别（按文件魔数，不依赖 URL 扩展名）
# --------------------------------------------------------------------------- #
def sniff(data: bytes) -> tuple[str, int, int]:
    """返回 (格式名, 像素宽, 像素高)。识别不了时格式为 unknown、尺寸为 0。"""
    if not data:
        return "unknown", 0, 0
    head = data[:16]
    # PNG：8 字节签名 + IHDR（大端 w/h 在偏移 16/20）
    if head[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        try:
            w, h = struct.unpack(">II", data[16:24])
            return "png", int(w), int(h)
        except struct.error:
            return "png", 0, 0
    # JPEG：扫描 SOF0~SOF15 段
    if head[:2] == b"\xff\xd8":
        i, n = 2, len(data)
        while i < n - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                          0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                try:
                    h, w = struct.unpack(">HH", data[i + 5:i + 9])
                    return "jpeg", int(w), int(h)
                except struct.error:
                    return "jpeg", 0, 0
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            try:
                seglen = struct.unpack(">H", data[i + 2:i + 4])[0]
            except struct.error:
                return "jpeg", 0, 0
            i += 2 + seglen
        return "jpeg", 0, 0
    # GIF：GIF8x + 小端 w/h 在偏移 6/8
    if head[:4] in (b"GIF8", b"GIF9") and len(data) >= 10:
        w, h = struct.unpack("<HH", data[6:10])
        return "gif", int(w), int(h)
    # BMP：BM + 小端 w/h 在偏移 18/22
    if head[:2] == b"BM" and len(data) >= 26:
        w, h = struct.unpack("<ii", data[18:26])
        return "bmp", int(max(w, 0)), int(max(h, 0))
    # WebP：RIFF....WEBP
    if head[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", 0, 0
    # SVG：文本形式 <svg
    if data.lstrip()[:4].lower() in (b"<svg", b"<?xm"):
        return "svg", 0, 0
    return "unknown", 0, 0


# --------------------------------------------------------------------------- #
# 下载 / 读取
# --------------------------------------------------------------------------- #
def _download(url: str) -> bytes | None:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as f:
        # 只读有限字节，避免异常服务器返回超大数据
        chunk = f.read(MAX_BYTES + 1)
    if len(chunk) > MAX_BYTES:
        return None
    return chunk


def fetch(src: str, base_dir: str = "") -> Image | None:
    """解析一张图片引用。src 为空、下载/读取失败、无法识别格式时返回 None。

    只要字节能安全交给渲染器（哪怕识别不出宽高）都会返回 Image，
    仅当拿不到任何字节时返回 None。
    """
    src = (src or "").strip()
    if not src:
        return None
    try:
        # 1) http(s) / 协议相对地址：先下载
        if src.startswith(("http://", "https://", "//")):
            url = ("https:" + src) if src.startswith("//") else src
            data = _download(url)
            if data is None:
                return None
            fmt, w, h = sniff(data)
            return Image(data=data, fmt=fmt, width=w, height=h)

        # 2) data URI：base64 内嵌
        if src.startswith("data:"):
            head, payload = src.split(",", 1)
            if "base64" not in head:
                return None
            data = base64.b64decode(payload)
            fmt, w, h = sniff(data)
            return Image(data=data, fmt=fmt, width=w, height=h)

        # 3) file:// URI
        if src.lower().startswith("file:"):
            p = urlparse(src)
            path = unquote(p.path)
            if os.name == "nt" and path.startswith("/") and len(path) > 2 \
                    and path[2] == ":":
                path = path[1:]
            return _from_path(path)

        # 4) 本地路径：绝对路径或相对 base_dir
        path = unquote(src.replace("/", os.sep))
        if not os.path.isabs(path):
            path = os.path.join(base_dir or "", path)
        return _from_path(path)
    except Exception:
        return None


def _from_path(path: str) -> Image | None:
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        data = f.read()
    fmt, w, h = sniff(data)
    return Image(data=data, fmt=fmt, width=w, height=h)
