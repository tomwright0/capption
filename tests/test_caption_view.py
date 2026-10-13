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


def test_scrollback_toggle(app):
    v = CaptionView(OverlayConfig(max_lines=3, fade_after_s=0, scrollback=False))
    v.resize(500, v.preferred_height())
    v.set_text(SENTENCE * 12, "")
    wheel(v, 2)
    assert v.scrolled_back == 0
    # Turning it off while scrolled back returns to live.
    v.apply_style(OverlayConfig(max_lines=3, fade_after_s=0, scrollback=True))
    wheel(v, 2)
    assert v.scrolled_back == 2
    v.apply_style(OverlayConfig(max_lines=3, fade_after_s=0, scrollback=False))
    assert v.scrolled_back == 0


def test_resume_timer_setting(view):
    view.apply_style(OverlayConfig(max_lines=3, fade_after_s=0, scrollback_resume_s=25))
    wheel(view, 1)
    assert view._resume.isActive() and view._resume.interval() == 25_000
    view.apply_style(OverlayConfig(max_lines=3, fade_after_s=0, scrollback_resume_s=0))
    wheel(view, 1)
    assert not view._resume.isActive()  # 0 = stay until scrolled down
    assert view.scrolled_back == 2


def test_layout_is_cached(view):
    first = view._layout_lines()
    assert view._layout_lines() is first
    view.set_text(SENTENCE * 13, "")
    assert view._layout_lines() is not first


def test_auto_live_off_keeps_view_scrolled_back(view):
    view.apply_style(OverlayConfig(max_lines=3, fade_after_s=0, scrollback_auto_live=False))
    wheel(view, 2)
    assert not view._resume.isActive()
    view.apply_style(OverlayConfig(max_lines=3, fade_after_s=0, scrollback_auto_live=True, scrollback_resume_s=7))
    assert view._resume.isActive() and view._resume.interval() == 7_000


def test_hover_live_switch_toggles_config(app):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent

    from capption.ui.overlay import OverlayWindow

    cfg = OverlayConfig(max_lines=3, fade_after_s=0)
    overlay = OverlayWindow(cfg)
    overlay.show()
    seen = []
    overlay.auto_live_toggled.connect(seen.append)
    center = overlay.view.live_toggle_rect().center()

    def click():
        ev = QMouseEvent(QEvent.Type.MouseButtonPress, center, overlay.mapToGlobal(center),
                         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        overlay.mousePressEvent(ev)

    click()  # not hovered: the switch is hidden, so this is a drag start, not a toggle
    overlay.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease, center, overlay.mapToGlobal(center),
                                          Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                                          Qt.KeyboardModifier.NoModifier))
    assert seen == [] and cfg.scrollback_auto_live
    overlay.view.show_controls = True
    click()
    assert seen == [False] and not cfg.scrollback_auto_live
    click()
    assert seen == [False, True] and cfg.scrollback_auto_live
