"""Typed configuration model. Persisted as JSON by :mod:`capption.config.store`."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Any, TypeVar

T = TypeVar("T")


@dataclass
class OverlayConfig:
    font_family: str = "Segoe UI"
    font_size: int = 28
    text_color: str = "#FFFFFF"
    partial_color: str = "#9AA4B2"
    background_color: str = "#101418"
    background_opacity: float = 0.72
    max_lines: int = 3
    width: int = 900
    click_through: bool = False
    visible: bool = True
    fade_after_s: float = 8.0  # fade text out after this long without speech (0 = never)
    scrollback: bool = True  # mouse wheel over the overlay scrolls back through recent captions
    scrollback_resume_s: int = 10  # return to live after this long without scrolling (0 = never)
    # Position keyed by monitor identity (QScreen name + geometry) -> [x, y] relative to that screen
    positions: dict[str, list[int]] = field(default_factory=dict)
    last_screen: str | None = None


@dataclass
class HotkeyConfig:
    toggle_captions: str = "Ctrl+Alt+C"
    toggle_click_through: str = "Ctrl+Alt+T"
    hide_overlay: str = "Ctrl+Alt+H"


@dataclass
class AsrConfig:
    model: str = "large-v3-turbo"
    device: str = "auto"  # auto | cuda | cpu
    compute_type: str = "auto"  # auto -> float16 on CUDA, int8 on CPU
    language: str | None = None  # None = auto-detect
    translate: bool = False
    beam_size: int = 1
    # Streaming tuning
    vad_threshold: float = 0.5
    min_silence_ms: int = 500
    max_buffer_s: float = 15.0
    step_s: float = 0.5


@dataclass
class CaptureConfig:
    last_exe: str | None = None  # e.g. "chrome.exe"; used for auto-reattach
    fallback_device: str | None = None  # input device name when loopback is unavailable
    dev_file: str | None = None  # macOS dev: looped audio/video file


@dataclass
class TranscriptConfig:
    enabled: bool = False
    txt: bool = True
    srt: bool = True
    directory: str | None = None  # None = <data dir>/transcripts


@dataclass
class AppConfig:
    asr: AsrConfig = field(default_factory=AsrConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    overlay: OverlayConfig = field(default_factory=OverlayConfig)
    hotkeys: HotkeyConfig = field(default_factory=HotkeyConfig)
    transcript: TranscriptConfig = field(default_factory=TranscriptConfig)
    custom_models: list[str] = field(default_factory=list)
    debug_panel: bool = False
    check_updates: bool = True  # one GitHub API request at startup

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        return _from_dict(cls, data)


def _from_dict(cls: type[T], data: Any) -> T:
    """Build a dataclass from a dict, ignoring unknown keys and keeping defaults for
    missing or wrongly-typed ones, so old or hand-edited configs still load."""
    obj = cls()
    if not isinstance(data, dict):
        return obj
    for f in fields(obj):  # type: ignore[arg-type]
        if f.name not in data:
            continue
        current = getattr(obj, f.name)
        value = data[f.name]
        if is_dataclass(current):
            setattr(obj, f.name, _from_dict(type(current), value))
        elif current is None or value is None or _same_kind(current, value):
            setattr(obj, f.name, value)
    return obj


def _same_kind(default: Any, value: Any) -> bool:
    if isinstance(default, bool) or isinstance(value, bool):
        return isinstance(default, bool) and isinstance(value, bool)
    if isinstance(default, float):
        return isinstance(value, (int, float))
    return isinstance(value, type(default))
