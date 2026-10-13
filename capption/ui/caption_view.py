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
    New lines slide up; text fades out after a period of silence. The mouse wheel scrolls
    back through the kept history (``style.scrollback``); it returns to live at the bottom or
    after ``style.scrollback_resume_s`` without scrolling."""

    def __init__(self, style: OverlayConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._style = style
        self._confirmed = ""
        self._partial = ""
        self._line_count = 0
        self._scroll = 0.0  # pixels still to scroll (animates to 0)
        self._back = 0  # lines scrolled back from the newest (0 = live)
        self._text_alpha = 1.0
        self.highlight_edges = False  # set by the overlay while hovering resize edges

        self._scroll_anim = QVariantAnimation(self, duration=220, easingCurve=QEasingCurve.Type.OutCubic)
        self._scroll_anim.valueChanged.connect(self._set_scroll)
        self._fade_anim = QVariantAnimation(self, duration=600, easingCurve=QEasingCurve.Type.InOutQuad)
        self._fade_anim.valueChanged.connect(self._set_alpha)
        self._idle = QTimer(self, singleShot=True)
        self._idle.timeout.connect(self._fade_out)
        self._resume = QTimer(self, singleShot=True)
        self._resume.timeout.connect(self.go_live)
        self._layout_cache: tuple[tuple, tuple[QTextLayout, list]] | None = None
        self.apply_style(style)

    # -- public API ------------------------------------------------------------
    def apply_style(self, style: OverlayConfig) -> None:
        self._style = style
        self._font = QFont(style.font_family)
        self._font.setPixelSize(max(8, style.font_size))
        self._font.setWeight(QFont.Weight.DemiBold)
        self._metrics = QFontMetricsF(self._font)
        self._layout_cache = None
        self._line_count = len(self._layout_lines()[1])
        if not style.scrollback:
            self.go_live()
        elif self._resume.isActive():
            self._restart_resume_timer()
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
        if not (confirmed or partial):
            self._back = 0
        elif self._back:
            # Stay on the same text while new lines arrive below.
            self._back = max(0, min(self._back + grew, lines - self._style.max_lines))
        elif 0 < grew <= self._style.max_lines and self.isVisible():
            self._scroll_anim.stop()
            self._scroll_anim.setStartValue(self._scroll + grew * self._line_height())
            self._scroll_anim.setEndValue(0.0)
            self._scroll_anim.start()
        if confirmed or partial:
            self._fade_in()
        self.update()

    @property
    def scrolled_back(self) -> int:
        return self._back

    def go_live(self) -> None:
        self._resume.stop()
        if self._back:
            self._back = 0
            self._fade_in()
            self.update()

    def wheelEvent(self, e) -> None:
        dy = e.angleDelta().y()
        if not self._style.scrollback:
            e.ignore()
            return
        e.accept()
        if not dy:
            return
        steps = round(dy / 120) or (1 if dy > 0 else -1)  # touchpads send small deltas
        max_back = max(0, self._line_count - self._style.max_lines)
        back = max(0, min(max_back, self._back + steps))
        if back == self._back:
            return
        self._back = back
        self._scroll_anim.stop()
        self._scroll = 0.0
        if back:
            self._idle.stop()  # don't fade while reading history
            self._fade_anim.stop()
            self._text_alpha = 1.0
            self._restart_resume_timer()
        else:
            self.go_live()
        self.update()

    def _restart_resume_timer(self) -> None:
        if self._style.scrollback_resume_s > 0:
            self._resume.start(int(self._style.scrollback_resume_s * 1000))
        else:
            self._resume.stop()  # stay scrolled back until the user scrolls down

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
        if not self._back:
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
        """Wrapped lines for the whole history. Cached: paints (every animation frame) reuse
        it, and it is rebuilt only when the text, width or style changes."""
        key = (self._confirmed, self._partial, self.width(), self._style.partial_color)
        if self._layout_cache is not None and self._layout_cache[0] == key:
            return self._layout_cache[1]
        result = self._build_layout()
        self._layout_cache = (key, result)
        return result

    def _build_layout(self) -> tuple[QTextLayout, list]:
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
        back = min(self._back, max(0, len(lines) - visible))
        end = len(lines) - back
        first = max(0, end - visible)
        top_of_first = lines[first].position().y()
        # Bottom-align so a single line sits where the last line of a full box would.
        shown = end - first
        y0 = PAD_Y + (visible - shown) * self._line_height() - top_of_first + self._scroll
        # Draw one extra line above while scrolling so it slides out instead of popping.
        start = max(0, first - (1 if self._scroll > 0 else 0))
        for line in lines[start:end]:
            line.draw(p, QPointF(PAD_X, y0))
        if back:
            self._paint_live_pill(p, back)

    def _paint_live_pill(self, p: QPainter, back: int) -> None:
        """Marker while scrolled back: how far up, and that scrolling down returns to live."""
        p.setOpacity(1.0)
        font = QFont(self._font)
        font.setPixelSize(max(10, int(self._font.pixelSize() * 0.45)))
        p.setFont(font)
        text = f"↓ live  ({back} up)"
        fm = QFontMetricsF(font)
        w, h = fm.horizontalAdvance(text) + 16, fm.height() + 6
        r = QRectF(self.width() - w - 10, self.height() - h - 8, w, h)
        pill = QColor(self._style.text_color)
        pill.setAlphaF(0.18)
        path = QPainterPath()
        path.addRoundedRect(r, h / 2, h / 2)
        p.fillPath(path, pill)
        p.setPen(QColor(self._style.text_color))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
