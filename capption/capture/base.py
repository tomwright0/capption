"""Audio source interface shared by every capture backend."""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

import numpy as np

from .resample import Resampler

log = logging.getLogger(__name__)

TARGET_RATE = 16_000

AudioCallback = Callable[[np.ndarray], None]
"""Receives float32 mono 16 kHz samples. Called from a capture thread."""


class SourceEnd(Enum):
    STOPPED = "stopped"  # stop() was called
    EOF = "eof"  # file source finished (non-looping)
    TARGET_EXITED = "target_exited"  # captured app closed
    DEVICE_LOST = "device_lost"  # device removed / default changed
    UNSUPPORTED = "unsupported"  # backend unavailable on this OS build
    ERROR = "error"


EndCallback = Callable[[SourceEnd, str], None]


@dataclass(frozen=True)
class SourceInfo:
    """Something the user can pick in the source dropdown."""

    key: str  # stable identity used for config/reattach, e.g. "chrome.exe"
    label: str  # friendly name
    kind: str  # "process" | "device" | "file"
    pid: int | None = None
    exe_path: str | None = None


class AudioSource(ABC):
    """Base class: subclasses deliver native-format frames to :meth:`_emit`,
    which resamples to 16 kHz mono and forwards to the consumer."""

    def __init__(self) -> None:
        self._on_audio: AudioCallback | None = None
        self._on_end: EndCallback | None = None
        self._resampler: Resampler | None = None
        self._ended = threading.Event()

    def start(self, on_audio: AudioCallback, on_end: EndCallback) -> None:
        self._on_audio = on_audio
        self._on_end = on_end
        self._ended.clear()
        self._start()

    def stop(self) -> None:
        self._stop()
        self._finish(SourceEnd.STOPPED, "")

    @abstractmethod
    def _start(self) -> None: ...

    @abstractmethod
    def _stop(self) -> None: ...

    def _emit(self, frames: np.ndarray, rate: int, channels: int) -> None:
        if self._resampler is None or self._resampler.key != (rate, channels):
            self._resampler = Resampler(rate, channels, TARGET_RATE)
        out = self._resampler.process(frames)
        if out.size and self._on_audio is not None:
            self._on_audio(out)

    def _finish(self, reason: SourceEnd, detail: str) -> None:
        """Report the end of the stream exactly once."""
        if self._ended.is_set():
            return
        self._ended.set()
        log.info("Source ended: %s %s", reason.value, detail)
        if self._on_end is not None:
            self._on_end(reason, detail)
