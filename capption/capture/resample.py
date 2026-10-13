"""Streaming conversion of arbitrary PCM to mono float32 at the target rate."""

from __future__ import annotations

import numpy as np
import soxr


class Resampler:
    """Stateful, so chunk boundaries don't produce clicks or drift."""

    def __init__(self, in_rate: int, channels: int, out_rate: int) -> None:
        self.key = (in_rate, channels)
        self._channels = channels
        self._stream = (
            None if in_rate == out_rate else soxr.ResampleStream(in_rate, out_rate, 1, dtype="float32", quality="HQ")
        )

    def process(self, frames: np.ndarray) -> np.ndarray:
        """``frames``: shape (n,) or (n, channels); int16 or float."""
        data = np.asarray(frames)
        if data.dtype == np.int16:
            data = data.astype(np.float32) / 32768.0
        else:
            data = data.astype(np.float32, copy=False)
        if data.ndim == 2:
            data = data.mean(axis=1) if data.shape[1] > 1 else data[:, 0]
        elif self._channels > 1:
            # Interleaved 1-D buffer, e.g. from the loopback helper pipe.
            usable = data.size - data.size % self._channels
            data = data[:usable].reshape(-1, self._channels).mean(axis=1)
        data = np.ascontiguousarray(data, dtype=np.float32)
        if self._stream is None:
            return data
        return self._stream.resample_chunk(data)
