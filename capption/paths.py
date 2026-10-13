"""Locate bundled resources both from source and inside a PyInstaller bundle."""

from __future__ import annotations

import sys
from pathlib import Path


def resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "capption"
    return Path(__file__).resolve().parent


def asset_path(name: str) -> Path:
    return resource_root() / "assets" / name
