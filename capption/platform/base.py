"""OS-specific services behind one interface. Implementations: windows.py, mac.py."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget

from ..capture.base import AudioSource, SourceInfo
from ..config import AppConfig


@dataclass(frozen=True)
class CaptureSupport:
    process_loopback: bool
    message: str  # shown in the UI when loopback is unavailable


class HotkeyManager(QObject):
    """Global (or best-effort) hotkeys. ``activated`` carries the action name."""

    activated = Signal(str)

    @abstractmethod
    def register(self, action: str, sequence: str) -> bool:
        """Bind ``sequence`` (QKeySequence text, e.g. "Ctrl+Alt+C"). False if unavailable."""

    @abstractmethod
    def unregister_all(self) -> None: ...


class Platform(ABC):
    name: str

    @abstractmethod
    def capture_support(self) -> CaptureSupport: ...

    @abstractmethod
    def list_sources(self, config: AppConfig) -> list[SourceInfo]:
        """Everything the picker should offer: audio-producing apps first, then devices."""

    @abstractmethod
    def find_app(self, key: str) -> SourceInfo | None:
        """Locate a running app by its stable key (e.g. "chrome.exe") for auto-reattach."""

    @abstractmethod
    def create_source(self, info: SourceInfo, config: AppConfig) -> AudioSource: ...

    @abstractmethod
    def set_click_through(self, widget: QWidget, enabled: bool) -> None: ...

    @abstractmethod
    def create_hotkeys(self, parent: QObject) -> HotkeyManager: ...
