"""Pick the platform implementation. Windows modules are only imported on Windows."""

from __future__ import annotations

import sys
from functools import cache

from .base import CaptureSupport, HotkeyManager, Platform


@cache
def current() -> Platform:
    if sys.platform == "win32":
        from .windows import WindowsPlatform

        return WindowsPlatform()
    from .mac import MacPlatform  # also fine for Linux dev boxes

    return MacPlatform()


__all__ = ["CaptureSupport", "HotkeyManager", "Platform", "current"]
