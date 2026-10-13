"""App icon drawn in code (speech bubble with caption lines), so there is no binary to maintain."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPixmap

from . import theme


def render(size: int, active: bool = True) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 64
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0, QColor(theme.ACCENT if active else "#6B7280"))
    grad.setColorAt(1, QColor("#5B6BF0" if active else "#4B5563"))
    bubble = QPainterPath()
    bubble.addRoundedRect(QRectF(4 * s, 6 * s, 56 * s, 42 * s), 12 * s, 12 * s)
    tail = QPainterPath()
    tail.moveTo(16 * s, 46 * s)
    tail.lineTo(14 * s, 58 * s)
    tail.lineTo(28 * s, 46 * s)
    tail.closeSubpath()
    p.fillPath(bubble.united(tail), grad)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#0B0D12"))
    for y, w in ((18, 36), (30, 24)):
        p.drawRoundedRect(QRectF(14 * s, y * s, w * s, 6 * s), 3 * s, 3 * s)
    p.end()
    return pix


def app_icon(active: bool = True) -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(render(size, active))
    return icon
