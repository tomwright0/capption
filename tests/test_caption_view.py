import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from capption.config.schema import OverlayConfig  # noqa: E402
from capption.ui.caption_view import CaptionView  # noqa: E402

SENTENCE = "The quick brown fox jumps over the lazy dog. "


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def view(app):
    v = CaptionView(OverlayConfig(max_lines=3, fade_after_s=0))
    v.resize(500, v.preferred_height())
    v.show()
    v.set_text(SENTENCE * 12, "")  # many wrapped lines
    return v


def wheel(view: CaptionView, notches: int) -> None:
    pos = QPointF(view.width() / 2, view.height() / 2)
    ev = QWheelEvent(pos, view.mapToGlobal(pos), QPoint(), QPoint(0, 120 * notches),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(view, ev)


def test_wheel_scrolls_back_and_clamps(view):
    total = view._line_count
    assert total > 6
    wheel(view, 2)
    assert view.scrolled_back == 2
    wheel(view, 1000)
    assert view.scrolled_back == total - 3  # can't scroll past the oldest kept line
    wheel(view, -1000)
    assert view.scrolled_back == 0


def test_new_text_keeps_scrolled_view_anchored(view):
    wheel(view, 2)
    before = view._line_count
    view.set_text(SENTENCE * 16, "")
    grew = view._line_count - before
    assert grew > 0
    assert view.scrolled_back == 2 + grew


def test_clear_and_go_live_reset(view):
    wheel(view, 3)
    view.go_live()
    assert view.scrolled_back == 0
    wheel(view, 3)
    view.set_text("", "")
    assert view.scrolled_back == 0


def test_paints_while_scrolled_back(view):
    wheel(view, 2)
    assert not view.grab().isNull()


def test_overlay_forwards_wheel_to_view(app):
    from capption.ui.overlay import OverlayWindow

    overlay = OverlayWindow(OverlayConfig(max_lines=3, fade_after_s=0))
    overlay.show()
    overlay.set_text(SENTENCE * 12, "")
    wheel(overlay, 2)  # the view itself ignores the mouse; the overlay must pass it on
    assert overlay.view.scrolled_back == 2
