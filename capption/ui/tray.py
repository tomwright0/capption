"""System tray icon: start/stop, overlay visibility, source switching, quit."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .controller import CaptionController
from .icon import app_icon
from .main_window import MainWindow


class Tray(QSystemTrayIcon):
    def __init__(
        self,
        window: MainWindow,
        controller: CaptionController,
        toggle_overlay: Callable[[], None],
        overlay_visible: Callable[[], bool],
        quit_app: Callable[[], None],
    ) -> None:
        super().__init__(app_icon(active=False))
        self.window = window
        self.controller = controller
        self.setToolTip("Capption")
        menu = QMenu()
        self.start_action = menu.addAction("Start captions", self._toggle_running)
        self.overlay_action = menu.addAction("Show overlay", toggle_overlay)
        self.sources_menu = menu.addMenu("Source")
        self.sources_menu.aboutToShow.connect(self._fill_sources)
        menu.addSeparator()
        menu.addAction("Settings…", self.show_window)
        menu.addSeparator()
        menu.addAction("Quit Capption", quit_app)
        menu.aboutToShow.connect(lambda: self.overlay_action.setText(
            "Hide overlay" if overlay_visible() else "Show overlay"))
        self.setContextMenu(menu)
        self._menu = menu  # keep a reference; the tray doesn't own it
        self.activated.connect(self._on_activated)
        controller.state_changed.connect(self._on_state)

    def show_window(self) -> None:
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_window()

    def _toggle_running(self) -> None:
        if self.controller.state == "idle":
            if source := self.window.selected_source():
                self.controller.start(source)
            else:
                self.show_window()
        else:
            self.controller.stop()

    def _fill_sources(self) -> None:
        self.sources_menu.clear()
        self.window.refresh_sources()
        group = QActionGroup(self.sources_menu)
        current = self.window.selected_source()
        for info in self.window._sources:
            act = QAction(info.label, self.sources_menu, checkable=True)
            act.setChecked(current is not None and current.key == info.key)
            act.triggered.connect(lambda _=False, i=info: self._switch(i))
            group.addAction(act)
            self.sources_menu.addAction(act)
        if not self.window._sources:
            self.sources_menu.addAction("No apps playing audio").setEnabled(False)

    def _switch(self, info) -> None:
        self.window.select_source(info.key)
        if self.controller.state != "idle":
            self.controller.start(info)

    def _on_state(self, state: str) -> None:
        running = state != "idle"
        self.start_action.setText("Stop captions" if running else "Start captions")
        self.setIcon(app_icon(active=running))
        self.setToolTip(f"Capption — {state}")
