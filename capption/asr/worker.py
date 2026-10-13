"""Inference thread: VAD gating + streaming transcription, decoupled from capture."""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .engine import is_oom
from .streamer import SAMPLE_RATE, OnlineStreamer, StreamUpdate, Transcriber
from .vad import VadSegmenter

log = logging.getLogger(__name__)

MAX_BACKLOG_S = 10.0  # beyond this we drop old audio: stale captions are useless


@dataclass
class Metrics:
    queue_s: float = 0.0  # captured audio waiting for the worker
    buffer_s: float = 0.0  # current streaming window length
    last_infer_s: float = 0.0
    rtf: float = 0.0  # inference time / window length (lower is better)
    dropped_s: float = 0.0
    in_speech: bool = False


class AsrWorker:
    """Consumes 16 kHz mono chunks via :meth:`push`; reports via callbacks (worker thread)."""

    def __init__(
        self,
        transcriber: Transcriber,
        segmenter: VadSegmenter,
        on_update: Callable[[StreamUpdate], None],
        on_metrics: Callable[[Metrics], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        language: str | None = None,
        step_s: float = 0.5,
        max_buffer_s: float = 15.0,
        on_oom: Callable[[str], bool] | None = None,
    ) -> None:
        self.streamer = OnlineStreamer(transcriber, language, max_buffer_s)
        self.segmenter = segmenter
        self.on_update = on_update
        self.on_metrics = on_metrics
        self.on_error = on_error
        self.on_oom = on_oom
        self.step_s = step_s
        self.metrics = Metrics()
        self._queue: queue.Queue[np.ndarray | None] = queue.Queue()
        self._queued_samples = 0
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._since_step = 0  # speech samples appended since the last pass

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="asr-worker", daemon=True)
        self._thread.start()

    def push(self, audio: np.ndarray) -> None:
        """Thread-safe; called from the capture thread. Never blocks."""
        with self._lock:
            self._queued_samples += audio.size
        self._queue.put(audio)

    def stop(self, timeout: float = 5.0) -> None:
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout)

    def _run(self) -> None:
        try:
            while True:
                chunk = self._queue.get()
                chunks = [chunk]
                while True:  # drain everything that's waiting
                    try:
                        chunks.append(self._queue.get_nowait())
                    except queue.Empty:
                        break
                stopping = any(c is None for c in chunks)
                audio = [c for c in chunks if c is not None]
                if audio:
                    data = np.concatenate(audio)
                    with self._lock:
                        self._queued_samples -= data.size
                    self._feed(self._drop_backlog(data))
                if stopping:
                    self._handle_events(self.segmenter.flush())
                    return
        except Exception as exc:
            log.exception("ASR worker crashed")
            if self.on_error:
                self.on_error(str(exc))

    def _drop_backlog(self, data: np.ndarray) -> np.ndarray:
        limit = int(MAX_BACKLOG_S * SAMPLE_RATE)
        if data.size <= limit:
            return data
        dropped = data.size - limit
        self.metrics.dropped_s += dropped / SAMPLE_RATE
        log.warning("ASR falling behind; dropped %.1fs of audio", dropped / SAMPLE_RATE)
        # Keep the VAD clock honest so subtitle times stay aligned.
        self.segmenter.skip(dropped)
        return data[dropped:]

    def _feed(self, data: np.ndarray) -> None:
        self._handle_events(self.segmenter.feed(data))
        if self.segmenter.in_speech and self._since_step >= self.step_s * SAMPLE_RATE:
            self._since_step = 0
            self._infer(self.streamer.process)
        self._publish_metrics()

    def _handle_events(self, events) -> None:
        for ev in events:
            if ev.kind == "start":
                self.streamer.start_segment(ev.audio, ev.time)
                self._since_step = ev.audio.size
            elif ev.kind == "audio":
                self.streamer.append(ev.audio)
                self._since_step += ev.audio.size
            elif ev.kind == "end":
                self._since_step = 0
                self._infer(self.streamer.end_segment)

    def _infer(self, step: Callable[[], StreamUpdate]) -> None:
        window = self.streamer.buffer_seconds
        t0 = time.perf_counter()
        try:
            update = step()
        except Exception as exc:
            if is_oom(exc) and self.on_oom and self.on_oom(str(exc)):
                log.warning("Recovered from GPU OOM; retrying on fallback device")
                update = step()
            else:
                raise
        elapsed = time.perf_counter() - t0
        self.metrics.last_infer_s = elapsed
        self.metrics.rtf = elapsed / window if window else 0.0
        if update.committed or update.partial or update.segment_end:
            self.on_update(update)

    def _publish_metrics(self) -> None:
        with self._lock:
            self.metrics.queue_s = self._queued_samples / SAMPLE_RATE
        self.metrics.buffer_s = self.streamer.buffer_seconds
        self.metrics.in_speech = self.segmenter.in_speech
        if self.on_metrics:
            self.on_metrics(self.metrics)
