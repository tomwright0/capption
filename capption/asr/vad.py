"""Streaming Silero VAD and speech segmentation.

Uses the Silero v6 ONNX model that faster-whisper already ships, run through
onnxruntime, so no torch dependency is needed.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 16_000
WINDOW = 512  # samples per VAD decision (32 ms)
CONTEXT = 64  # samples of previous window prepended, as the v6 model expects


def silero_model_path() -> str:
    import faster_whisper

    return os.path.join(os.path.dirname(faster_whisper.__file__), "assets", "silero_vad_v6.onnx")


class SileroVad:
    """Stateful speech probability per 512-sample window."""

    def __init__(self, path: str | None = None) -> None:
        import onnxruntime

        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 4
        self._session = onnxruntime.InferenceSession(
            path or silero_model_path(), providers=["CPUExecutionProvider"], sess_options=opts
        )
        self.reset()

    def reset(self) -> None:
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._context = np.zeros(CONTEXT, dtype=np.float32)

    def __call__(self, window: np.ndarray) -> float:
        x = np.concatenate([self._context, window]).reshape(1, CONTEXT + WINDOW)
        prob, self._h, self._c = self._session.run(None, {"input": x, "h": self._h, "c": self._c})
        self._context = window[-CONTEXT:].copy()
        return float(prob.reshape(-1)[0])


@dataclass
class VadEvent:
    kind: str  # "start" | "audio" | "end"
    audio: np.ndarray | None = None
    time: float = 0.0  # stream time (s) of the first sample in `audio`, or of the event


class VadSegmenter:
    """Turns a continuous stream into speech segments.

    Emits ``start`` (with pre-roll audio), ``audio`` while speaking and ``end`` after
    ``min_silence_ms`` of silence. Silence between segments is dropped so the ASR
    never spends time on it. Stream time keeps advancing through silence so
    timestamps stay correct for subtitles.
    """

    def __init__(
        self,
        prob_fn: Callable[[np.ndarray], float],
        threshold: float = 0.5,
        min_silence_ms: int = 500,
        preroll_ms: int = 300,
        max_segment_s: float = 30.0,
    ) -> None:
        self._prob = prob_fn
        self.threshold = threshold
        self.neg_threshold = max(threshold - 0.15, 0.01)
        self._silence_windows = max(1, int(min_silence_ms * SAMPLE_RATE / 1000 / WINDOW))
        self._preroll_windows = max(0, int(preroll_ms * SAMPLE_RATE / 1000 / WINDOW))
        self._max_segment_windows = int(max_segment_s * SAMPLE_RATE / WINDOW)
        self._pending = np.zeros(0, dtype=np.float32)
        self._preroll: list[np.ndarray] = []
        self._in_speech = False
        self._silent_run = 0
        self._segment_windows = 0
        self._windows_seen = 0

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    @property
    def time(self) -> float:
        return self._windows_seen * WINDOW / SAMPLE_RATE

    def feed(self, audio: np.ndarray) -> list[VadEvent]:
        self._pending = np.concatenate([self._pending, audio.astype(np.float32, copy=False)])
        n = self._pending.size // WINDOW
        if n == 0:
            return []
        windows = self._pending[: n * WINDOW].reshape(n, WINDOW)
        self._pending = self._pending[n * WINDOW :]

        events: list[VadEvent] = []
        run: list[np.ndarray] = []  # consecutive speech-segment windows to emit as one chunk
        run_start = 0.0

        def flush_run() -> None:
            if run:
                events.append(VadEvent("audio", np.concatenate(run), run_start))
                run.clear()

        for w in windows:
            t = self.time
            p = self._prob(w)
            self._windows_seen += 1
            if not self._in_speech:
                if p >= self.threshold:
                    self._in_speech = True
                    self._silent_run = 0
                    self._segment_windows = 1
                    pre = self._preroll
                    start_t = t - len(pre) * WINDOW / SAMPLE_RATE
                    events.append(VadEvent("start", np.concatenate([*pre, w]), start_t))
                    self._preroll = []
                else:
                    self._preroll.append(w)
                    if len(self._preroll) > self._preroll_windows:
                        self._preroll.pop(0)
                continue

            if not run:
                run_start = t
            run.append(w)
            self._segment_windows += 1
            self._silent_run = self._silent_run + 1 if p < self.neg_threshold else 0
            if self._silent_run >= self._silence_windows or self._segment_windows >= self._max_segment_windows:
                flush_run()
                events.append(VadEvent("end", time=self.time))
                self._in_speech = False
                self._silent_run = 0
        flush_run()
        return events

    def skip(self, samples: int) -> None:
        """Advance stream time over audio that was dropped without analysing it."""
        self._windows_seen += samples // WINDOW

    def flush(self) -> list[VadEvent]:
        """Close an open segment (e.g. when the source stops)."""
        if not self._in_speech:
            return []
        self._in_speech = False
        return [VadEvent("end", time=self.time)]
