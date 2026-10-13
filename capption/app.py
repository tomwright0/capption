"""GUI entry point: wires config, platform services, controller, windows and tray."""

from __future__ import annotations

import logging
import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from . import __version__
from .captions import CaptionBuffer
from .config import ConfigStore
from .logging_setup import setup_logging
from .platform import current as current_platform
from .ui.controller import CaptionController
from .ui.icon import app_icon
from .ui.main_window import MainWindow, debounce
from .ui.overlay import OverlayWindow
from .ui.theme import apply_theme
from .ui.tray import Tray

log = logging.getLogger(__name__)

AUTO_REATTACH_POLL_MS = 3000


class CapptionApp:
    def __init__(self, app: QApplication) -> None:
        self.app = app
        self.store = ConfigStore()
        self.config = self.store.load()
        self.platform = current_platform()
        self.controller = CaptionController(self.config, self.platform)
        self.captions = CaptionBuffer()

        self.overlay = OverlayWindow(self.config.overlay)
        self.window = MainWindow(self.config, self.platform, self.controller)
        self.window.setWindowIcon(app_icon())
        self.save_soon = debounce(self.window, 500, self._save)

        self.controller.update.connect(self._on_update)
        self.controller.state_changed.connect(self._on_state)
        self.window.config_changed.connect(self.save_soon)
        self.window.style_changed.connect(lambda: self.overlay.apply_style(self.config.overlay))
        self.window.hotkeys_changed.connect(self._register_hotkeys)
        self.window.toggle_overlay_requested.connect(self.toggle_overlay)
        self.overlay.geometry_committed.connect(self._on_overlay_moved)

        self.hotkeys = self.platform.create_hotkeys(self.window)
        self.hotkeys.activated.connect(self._on_hotkey)
        self._register_hotkeys()

        self.tray: Tray | None = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = Tray(self.window, self.controller, self.toggle_overlay,
                             lambda: self.overlay.isVisible(), self.quit)
            self.tray.show()
        else:
            app.setQuitOnLastWindowClosed(True)

        self.overlay.restore_position()
        if self.config.overlay.visible:
            self.overlay.show()
        if self.config.overlay.click_through:
            self.platform.set_click_through(self.overlay, True)
        self.window.show()

        # Auto-start when the remembered app is (or becomes) available.
        self._auto = QTimer(self.window, interval=AUTO_REATTACH_POLL_MS)
        self._auto.timeout.connect(self._auto_attach)
        if self.config.capture.last_exe:
            self._auto.start()
            QTimer.singleShot(0, self._auto_attach)

    # -- behaviour -----------------------------------------------------------------
    def _on_update(self, update) -> None:
        self.captions.apply(update)
        self.overlay.set_text(*self.captions.display())

    def _on_state(self, state: str) -> None:
        if state == "idle":
            self.captions.clear()
            self.overlay.set_text("", "")
        # A manual stop shouldn't be undone by auto-attach.
        if state == "idle" and self._auto.isActive():
            self._auto.stop()

    def _auto_attach(self) -> None:
        exe = self.config.capture.last_exe
        if not exe or self.controller.state != "idle":
            self._auto.stop()
            return
        if not self.platform.capture_support().process_loopback:
            self._auto.stop()  # dev builds have no real processes; don't auto-play demo audio
            return
        info = self.platform.find_app(exe)
        if info is None:
            return
        self._auto.stop()
        self.window.refresh_sources()
        self.window.select_source(info.key)
        self.controller.start(info)

    def toggle_overlay(self) -> None:
        visible = not self.overlay.isVisible()
        self.overlay.setVisible(visible)
        self.config.overlay.visible = visible
        self.save_soon()

    def toggle_click_through(self) -> None:
        o = self.config.overlay
        o.click_through = not o.click_through
        self.platform.set_click_through(self.overlay, o.click_through)
        if self.tray:
            self.tray.showMessage("Capption", f"Click-through {'on' if o.click_through else 'off'}",
                                  app_icon(), 1500)
        self.save_soon()

    def _on_hotkey(self, action: str) -> None:
        log.info("Hotkey: %s", action)
        if action == "toggle_captions":
            self.tray._toggle_running() if self.tray else self.window._toggle_running()
        elif action == "toggle_click_through":
            self.toggle_click_through()
        elif action == "hide_overlay":
            self.toggle_overlay()

    def _register_hotkeys(self) -> None:
        self.hotkeys.unregister_all()
        hk = self.config.hotkeys
        failed = [
            seq for action, seq in (
                ("toggle_captions", hk.toggle_captions),
                ("toggle_click_through", hk.toggle_click_through),
                ("hide_overlay", hk.hide_overlay),
            ) if seq and not self.hotkeys.register(action, seq)
        ]
        self.window.set_hotkey_status(failed)

    def _on_overlay_moved(self) -> None:
        self.window.sync_overlay_width()
        self.save_soon()

    def _save(self) -> None:
        try:
            self.store.save(self.config)
        except OSError:
            log.exception("Saving config failed")

    def quit(self) -> None:
        self.controller.stop()
        self.hotkeys.unregister_all()
        self._save()
        self.app.quit()


def main() -> int:
    setup_logging()
    log.info("Capption %s starting on %s", __version__, sys.platform)
    app = QApplication(sys.argv)
    app.setApplicationName("Capption")
    app.setApplicationDisplayName("Capption")
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)
    apply_theme(app)
    capp = CapptionApp(app)
    # Let Ctrl+C in a terminal quit cleanly during development.
    signal.signal(signal.SIGINT, lambda *_: capp.quit())
    keepalive = QTimer(interval=200)
    keepalive.timeout.connect(lambda: None)
    keepalive.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
