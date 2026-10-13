"""Caption renderer shared by the overlay and the settings live preview."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QTextCharFormat, QTextLayout, QTextOption
from PySide6.QtWidgets import QWidget

from ..config import OverlayConfig

PAD_X = 22
PAD_Y = 14
RADIUS = 16
LINE_SEP = " "  # QTextLayout's hard line break


class CaptionView(QWidget):
    """Paints the last ``max_lines`` wrapped lines; confirmed solid, partial dimmed.
    New lines slide up; text fades out after a period of silence."""

    def __init__(self, style: OverlayConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._style = style
        self._confirmed = ""
        self._partial = ""
        self._line_count = 0
        self._scroll = 0.0  # pixels still to scroll (animates to 0)
        self._text_alpha = 1.0
        self.highlight_edges = False  # set by the overlay while hovering resize edges

        self._scroll_anim = QVariantAnimation(self, duration=220, easingCurve=QEasingCurve.Type.OutCubic)
        self._scroll_anim.valueChanged.connect(self._set_scroll)
        self._fade_anim = QVariantAnimation(self, duration=600, easingCurve=QEasingCurve.Type.InOutQuad)
        self._fade_anim.valueChanged.connect(self._set_alpha)
        self._idle = QTimer(self, singleShot=True)
        self._idle.timeout.connect(self._fade_out)
        self.apply_style(style)

    # -- public API ------------------------------------------------------------
    def apply_style(self, style: OverlayConfig) -> None:
        self._style = style
        self._font = QFont(style.font_family)
        self._font.setPixelSize(max(8, style.font_size))
        self._font.setWeight(QFont.Weight.DemiBold)
        self._metrics = QFontMetricsF(self._font)
        self.setFixedHeight(self.preferred_height())
        self.update()

    def preferred_height(self) -> int:
        return int(PAD_Y * 2 + self._line_height() * max(1, self._style.max_lines))

    def set_text(self, confirmed: str, partial: str) -> None:
        if (confirmed, partial) == (self._confirmed, self._partial):
            return
        self._confirmed, self._partial = confirmed, partial
        lines = len(self._layout_lines()[1])
        grew = lines - self._line_count
        self._line_count = lines
        if 0 < grew <= self._style.max_lines and self.isVisible():
            self._scroll_anim.stop()
            self._scroll_anim.setStartValue(self._scroll + grew * self._line_height())
            self._scroll_anim.setEndValue(0.0)
            self._scroll_anim.start()
        if confirmed or partial:
            self._fade_in()
        self.update()

    # -- animation helpers -----------------------------------------------------
    def _set_scroll(self, v: float) -> None:
        self._scroll = float(v)
        self.update()

    def _set_alpha(self, v: float) -> None:
        self._text_alpha = float(v)
        self.update()

    def _fade_in(self) -> None:
        if self._style.fade_after_s > 0:
            self._idle.start(int(self._style.fade_after_s * 1000))
        if self._text_alpha < 1.0 and self._fade_anim.endValue() != 1.0:
            self._animate_alpha(1.0, 180)

    def _fade_out(self) -> None:
        self._animate_alpha(0.0, 600)

    def _animate_alpha(self, target: float, ms: int) -> None:
        self._fade_anim.stop()
        self._fade_anim.setDuration(ms)
        self._fade_anim.setStartValue(self._text_alpha)
        self._fade_anim.setEndValue(target)
        self._fade_anim.start()

    # -- layout & paint ----------------------------------------------------------
    def _line_height(self) -> float:
        return self._metrics.lineSpacing() * 1.12

    def _layout_lines(self) -> tuple[QTextLayout, list]:
        text = (self._confirmed + self._partial).replace("\n", LINE_SEP)
        layout = QTextLayout(text, self._font)
        opt = QTextOption()
        opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        opt.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.setTextOption(opt)
        if self._partial:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(self._style.partial_color))
            rng = QTextLayout.FormatRange()
            rng.start, rng.length, rng.format = len(self._confirmed), len(self._partial), fmt
            layout.setFormats([rng])
        width = max(50.0, self.width() - PAD_X * 2)
        lines = []
        y = 0.0
        layout.beginLayout()
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            line.setPosition(QPointF(0, y))
            y += self._line_height()
            lines.append(line)
        layout.endLayout()
        return layout, lines

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, RADIUS, RADIUS)
        bg = QColor(self._style.background_color)
        bg.setAlphaF(max(0.0, min(1.0, self._style.background_opacity)))
        p.fillPath(path, bg)
        if self.highlight_edges:
            edge = QColor(255, 255, 255, 60)
            p.setPen(edge)
            p.drawPath(path)

        layout, lines = self._layout_lines()
        if not lines or self._text_alpha <= 0.01:
            return
        p.setClipPath(path)
        p.setOpacity(self._text_alpha)
        p.setPen(QColor(self._style.text_color))
        visible = self._style.max_lines
        first = max(0, len(lines) - visible)
        top_of_first = lines[first].position().y()
        # Bottom-align so a single line sits where the last line of a full box would.
        shown = len(lines) - first
        y0 = PAD_Y + (visible - shown) * self._line_height() - top_of_first + self._scroll
        # Draw one extra line above while scrolling so it slides out instead of popping.
        start = max(0, first - (1 if self._scroll > 0 else 0))
        for line in lines[start:]:
            line.draw(p, QPointF(PAD_X, y0))
