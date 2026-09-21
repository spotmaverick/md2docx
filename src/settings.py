# -*- coding: utf-8 -*-
"""用户配置的持久化（极简 JSON）。

位置：``%APPDATA%\\Md2docs\\settings.json``（拿不到 APPDATA 时退回用户主目录）。
只存少量界面偏好，例如界面语言。**任何写失败都静默忽略**——
配置读不出来不应该让程序起不来。
"""
from __future__ import annotations

import json
import os

APP_DIR_NAME = "Md2docs"
FILE_NAME = "settings.json"

_cache: dict | None = None


def config_dir() -> str:
    base = os.environ.get("APPDATA")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, APP_DIR_NAME)


def config_path() -> str:
    return os.path.join(config_dir(), FILE_NAME)


def load(force: bool = False) -> dict:
    """读取配置；失败返回空字典（不抛异常）。"""
    global _cache
    if _cache is not None and not force:
        return dict(_cache)
    data: dict = {}
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            got = json.load(f)
        if isinstance(got, dict):
            data = got
    except Exception:
        data = {}
    _cache = data
    return dict(data)


def get(key: str, default=None):
    return load().get(key, default)


def put(key: str, value) -> None:
    """写入单项配置（读改写，失败静默）。"""
    data = load()
    if data.get(key) == value:
        return
    data[key] = value
    save(data)


def save(data: dict) -> bool:
    global _cache
    _cache = dict(data or {})
    try:
        d = config_dir()
        os.makedirs(d, exist_ok=True)
        tmp = config_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_cache, f, ensure_ascii=False, indent=2)
        os.replace(tmp, config_path())
        return True
    except Exception:
        return False
