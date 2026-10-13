"""Render the in-code app icon (capption/ui/icon.py) to a multi-size .ico for the exe/installer.

    python tools/make_icon.py build/capption.ico
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from capption.ui.icon import render  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256)


def png_bytes(size: int) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    render(size).save(buf, "PNG")
    return bytes(buf.data())


def write_ico(path: Path) -> None:
    images = [png_bytes(s) for s in SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    for size, data in zip(SIZES, images):
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO directory
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + entries + b"".join(images))


if __name__ == "__main__":
    app = QGuiApplication(sys.argv[:1])
    write_ico(Path(sys.argv[1] if len(sys.argv) > 1 else "build/capption.ico"))
