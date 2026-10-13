"""Audio/video file source, paced in real time. Used for development and testing."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import av
import numpy as np

from .base import TARGET_RATE, AudioSource, SourceEnd, SourceInfo

log = logging.getLogger(__name__)

CHUNK_S = 0.05


class FileSource(AudioSource):
    def __init__(self, path: str | Path, loop: bool = True, realtime: bool = True) -> None:
        super().__init__()
        self.path = Path(path)
        self.loop = loop
        self.realtime = realtime
        self._stop_evt = threading.Event()
        self._thread: threading.Thread | None = None

    @staticmethod
    def info(path: str | Path) -> SourceInfo:
        p = Path(path)
        return SourceInfo(key=f"file:{p}", label=f"File: {p.name}", kind="file")

    def _start(self) -> None:
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._run, name="file-source", daemon=True)
        self._thread.start()

    def _stop(self) -> None:
        self._stop_evt.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)

    def _run(self) -> None:
        try:
            while not self._stop_evt.is_set():
                self._play_once()
                if not self.loop:
                    self._finish(SourceEnd.EOF, str(self.path))
                    return
        except Exception as exc:  # decoding errors must not kill the app
            log.exception("File source failed")
            self._finish(SourceEnd.ERROR, str(exc))

    def _play_once(self) -> None:
        chunk = int(TARGET_RATE * CHUNK_S)
        pending = np.zeros(0, dtype=np.float32)
        start = time.monotonic()
        sent = 0
        for block in decode_mono_16k(self.path):
            pending = np.concatenate([pending, block])
            while pending.size >= chunk:
                if self._stop_evt.is_set():
                    return
                piece, pending = pending[:chunk], pending[chunk:]
                if self.realtime:
                    delay = start + sent / TARGET_RATE - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                self._emit(piece, TARGET_RATE, 1)
                sent += piece.size
        if pending.size and not self._stop_evt.is_set():
            self._emit(pending, TARGET_RATE, 1)


def decode_mono_16k(path: str | Path):
    """Yield float32 mono 16 kHz blocks decoded from any container PyAV can read."""
    with av.open(str(path)) as container:
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            raise ValueError(f"No audio stream in {path}")
        resampler = av.AudioResampler(format="flt", layout="mono", rate=TARGET_RATE)
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                yield out.to_ndarray().reshape(-1).astype(np.float32, copy=False)
        for out in resampler.resample(None):
            yield out.to_ndarray().reshape(-1).astype(np.float32, copy=False)


def load_audio(path: str | Path) -> np.ndarray:
    blocks = list(decode_mono_16k(path))
    return np.concatenate(blocks) if blocks else np.zeros(0, dtype=np.float32)
