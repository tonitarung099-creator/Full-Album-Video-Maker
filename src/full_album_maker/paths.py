from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "Full Album Maker"


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def asset_path(name: str) -> Path:
    return app_root() / "assets" / name


def data_dir() -> Path:
    path = app_root() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def secure_dir() -> Path:
    path = data_dir() / "secure"
    path.mkdir(parents=True, exist_ok=True)
    return path


def temp_dir() -> Path:
    path = app_root() / "temp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def output_dir() -> Path:
    path = app_root() / "output"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _find_tool(name: str) -> str:
    exe = f"{name}.exe" if os.name == "nt" else name
    bundled = app_root() / "tools" / "ffmpeg" / exe
    if bundled.exists():
        return str(bundled)
    return shutil.which(name) or ""


def ffmpeg_path() -> str:
    return _find_tool("ffmpeg")


def ffprobe_path() -> str:
    return _find_tool("ffprobe")
