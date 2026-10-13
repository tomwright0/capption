"""macOS development implementation.

Process loopback doesn't exist here, so "apps" in the picker are dummies that play a
looping audio/video file through the real pipeline. Input devices (mic, BlackHole,
...) are listed too.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget

from ..capture.base import AudioSource, SourceInfo
from ..capture.device_source import DeviceSource, list_input_devices
from ..capture.file_source import FileSource
from ..config import AppConfig
from ..paths import asset_path
from .base import CaptureSupport, HotkeyManager, Platform

DUMMY_APPS = [("chrome.exe", "Google Chrome (demo)"), ("spotify.exe", "Spotify (demo)"), ("vlc.exe", "VLC (demo)")]


class ShortcutHotkeys(HotkeyManager):
    """App-wide shortcuts: work while a Capption window is focused (macOS global
    hotkeys would need Accessibility permission, which isn't worth it for dev)."""

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self._host = parent if isinstance(parent, QWidget) else None
        self._shortcuts: list[QShortcut] = []

    def register(self, action: str, sequence: str) -> bool:
        if self._host is None or not sequence:
            return False
        sc = QShortcut(QKeySequence(sequence), self._host)
        sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc.activated.connect(lambda a=action: self.activated.emit(a))
        self._shortcuts.append(sc)
        return True

    def unregister_all(self) -> None:
        for sc in self._shortcuts:
            sc.setEnabled(False)
            sc.deleteLater()
        self._shortcuts.clear()


class MacPlatform(Platform):
    name = "macos"

    def capture_support(self) -> CaptureSupport:
        return CaptureSupport(
            False, "macOS dev build: demo apps play a looping file; or pick an input device."
        )

    def _demo_file(self, config: AppConfig) -> Path:
        custom = config.capture.dev_file
        if custom and Path(custom).is_file():
            return Path(custom)
        return asset_path("sample_speech.wav")

    def list_sources(self, config: AppConfig) -> list[SourceInfo]:
        apps = [SourceInfo(key=k, label=label, kind="process", pid=None) for k, label in DUMMY_APPS]
        return apps + list_input_devices()

    def find_app(self, key: str) -> SourceInfo | None:
        return next((SourceInfo(k, label, "process") for k, label in DUMMY_APPS if k == key), None)

    def create_source(self, info: SourceInfo, config: AppConfig) -> AudioSource:
        if info.kind == "device":
            return DeviceSource(info.key.removeprefix("device:"))
        if info.kind == "file":
            return FileSource(info.key.removeprefix("file:"), loop=True)
        return FileSource(self._demo_file(config), loop=True)

    def set_click_through(self, widget: QWidget, enabled: bool) -> None:
        visible = widget.isVisible()
        widget.setWindowFlag(Qt.WindowType.WindowTransparentForInput, enabled)
        if visible:
            widget.show()  # changing window flags hides the window

    def create_hotkeys(self, parent: QObject) -> HotkeyManager:
        return ShortcutHotkeys(parent)
