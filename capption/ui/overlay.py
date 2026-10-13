"""Frameless, translucent, always-on-top caption window."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QMouseEvent, QScreen
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..config import OverlayConfig
from .caption_view import CaptionView

EDGE = 10  # px from the left/right edge that starts a width resize
SNAP = 18  # px from a screen edge that snaps to it
MIN_WIDTH = 240


def screen_key(screen: QScreen) -> str:
    g = screen.geometry()
    return f"{screen.name()}@{g.width()}x{g.height()}+{g.x()}+{g.y()}"


class OverlayWindow(QWidget):
    geometry_committed = Signal()  # position/width changed by the user; config updated
    auto_live_toggled = Signal(bool)  # the hover "Live" switch was clicked; config updated

    def __init__(self, style: OverlayConfig) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool  # no taskbar entry
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setWindowTitle("Capption overlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.style_cfg = style
        self.view = CaptionView(style, self)
        self.view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view)
        self._drag_offset: QPoint | None = None
        self._resize_edge: str | None = None
        self._resize_origin: tuple[int, QRect] | None = None
        self.apply_style(style)

    def apply_style(self, style: OverlayConfig) -> None:
        self.style_cfg = style
        self.view.apply_style(style)
        self.resize(max(MIN_WIDTH, style.width), self.view.preferred_height())

    def set_text(self, confirmed: str, partial: str) -> None:
        self.view.set_text(confirmed, partial)

    def wheelEvent(self, e) -> None:
        # The view ignores the mouse (the overlay handles drag/resize), so pass scrolling on.
        self.view.wheelEvent(e)

    # -- placement ---------------------------------------------------------------
    def restore_position(self) -> None:
        screens = {screen_key(s): s for s in QGuiApplication.screens()}
        positions = self.style_cfg.positions
        key = self.style_cfg.last_screen
        if key not in screens or key not in positions:
            key = next((k for k in positions if k in screens), None)
        if key is not None:
            geo = screens[key].geometry()
            x, y = positions[key]
            self.move(self._clamped(QPoint(geo.x() + x, geo.y() + y), screens[key]))
            return
        # Default: bottom centre of the primary screen.
        avail = QGuiApplication.primaryScreen().availableGeometry()
        self.move(avail.center().x() - self.width() // 2, avail.bottom() - self.height() - 60)

    def _clamped(self, pos: QPoint, screen: QScreen) -> QPoint:
        a = screen.availableGeometry()
        x = min(max(pos.x(), a.left()), a.right() - self.width() + 1)
        y = min(max(pos.y(), a.top()), a.bottom() - self.height() + 1)
        return QPoint(x, y)

    def _snapped(self, pos: QPoint) -> QPoint:
        screen = QGuiApplication.screenAt(QCursor.pos()) or self.screen()
        a = screen.availableGeometry()
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        if abs(x - a.left()) < SNAP:
            x = a.left()
        elif abs(x + w - a.right() - 1) < SNAP:
            x = a.right() + 1 - w
        elif abs(x + w / 2 - a.center().x()) < SNAP:
            x = a.center().x() - w // 2
        if abs(y - a.top()) < SNAP:
            y = a.top()
        elif abs(y + h - a.bottom() - 1) < SNAP:
            y = a.bottom() + 1 - h
        return QPoint(x, y)

    def _commit_geometry(self) -> None:
        screen = self.screen()
        geo = screen.geometry()
        key = screen_key(screen)
        self.style_cfg.positions[key] = [self.x() - geo.x(), self.y() - geo.y()]
        self.style_cfg.last_screen = key
        self.style_cfg.width = self.width()
        self.geometry_committed.emit()

    # -- mouse: drag to move, drag side edges to resize width ----------------------
    def _edge_at(self, pos: QPoint) -> str | None:
        if pos.x() <= EDGE:
            return "left"
        if pos.x() >= self.width() - EDGE:
            return "right"
        return None

    def _on_live_toggle(self, pos: QPoint) -> bool:
        return (self.view.show_controls and self.style_cfg.scrollback
                and self.view.live_toggle_rect().contains(QPointF(pos)))

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self._on_live_toggle(e.position().toPoint()):
            self.style_cfg.scrollback_auto_live = not self.style_cfg.scrollback_auto_live
            self.view.apply_style(self.style_cfg)  # starts/stops the return-to-live timer
            self.view.update()
            self.auto_live_toggled.emit(self.style_cfg.scrollback_auto_live)
            return
        self._resize_edge = self._edge_at(e.position().toPoint())
        if self._resize_edge:
            self._resize_origin = (e.globalPosition().toPoint().x(), self.geometry())
        else:
            self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        gp = e.globalPosition().toPoint()
        if self._resize_edge and self._resize_origin:
            start_x, geo = self._resize_origin
            dx = gp.x() - start_x
            if self._resize_edge == "right":
                self.resize(max(MIN_WIDTH, geo.width() + dx), self.height())
            else:
                w = max(MIN_WIDTH, geo.width() - dx)
                self.setGeometry(geo.right() + 1 - w, geo.y(), w, self.height())
            self.view.update()
        elif self._drag_offset is not None:
            self.move(self._snapped(gp - self._drag_offset))
        else:
            pos = e.position().toPoint()
            edge = self._edge_at(pos)
            if self._on_live_toggle(pos):
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.setCursor(Qt.CursorShape.SizeHorCursor if edge else Qt.CursorShape.OpenHandCursor)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if self._drag_offset is not None or self._resize_edge:
            self._commit_geometry()
        self._drag_offset = None
        self._resize_edge = None
        self._resize_origin = None

    def enterEvent(self, _e) -> None:
        self.view.highlight_edges = True
        self.view.show_controls = True
        self.view.update()

    def leaveEvent(self, _e) -> None:
        self.view.highlight_edges = False
        self.view.show_controls = False
        self.view.update()
