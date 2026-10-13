"""Input-device capture via PortAudio (sounddevice).

Used for the macOS dev mic and as the Windows fallback (e.g. VB-Cable "CABLE Output")
when process loopback is unavailable.
"""

from __future__ import annotations

import logging
import sys

import numpy as np
import sounddevice as sd

from .base import AudioSource, SourceEnd, SourceInfo

log = logging.getLogger(__name__)


def list_input_devices() -> list[SourceInfo]:
    try:
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
    except Exception:
        log.exception("Could not query audio devices")
        return []
    preferred = _preferred_hostapi(hostapis)
    out: list[SourceInfo] = []
    for dev in devices:
        if dev["max_input_channels"] <= 0:
            continue
        if preferred is not None and dev["hostapi"] != preferred:
            continue
        out.append(SourceInfo(key=f"device:{dev['name']}", label=f"Input: {dev['name']}", kind="device"))
    return out


def _preferred_hostapi(hostapis) -> int | None:
    # On Windows the same device appears under MME/DirectSound/WASAPI; list WASAPI only.
    if sys.platform != "win32":
        return None
    for i, api in enumerate(hostapis):
        if "WASAPI" in api["name"]:
            return i
    return None


def _find_device(name: str) -> int:
    preferred = _preferred_hostapi(sd.query_hostapis())
    candidates = [
        (i, d)
        for i, d in enumerate(sd.query_devices())
        if d["max_input_channels"] > 0 and d["name"] == name
    ]
    for i, d in candidates:
        if preferred is None or d["hostapi"] == preferred:
            return i
    if candidates:
        return candidates[0][0]
    raise LookupError(f"Input device not found: {name}")


class DeviceSource(AudioSource):
    def __init__(self, device_name: str | None) -> None:
        super().__init__()
        self.device_name = device_name
        self._stream: sd.InputStream | None = None

    def _start(self) -> None:
        index = _find_device(self.device_name) if self.device_name else None
        info = sd.query_devices(index, "input")
        rate = int(info["default_samplerate"])
        channels = min(2, int(info["max_input_channels"]))

        def callback(indata: np.ndarray, frames: int, _time, status: sd.CallbackFlags) -> None:
            if status.input_overflow:
                log.debug("Input overflow")
            self._emit(indata.copy(), rate, channels)

        def finished() -> None:
            # PortAudio stops the stream itself when the device disappears.
            if self._stream is not None:
                self._finish(SourceEnd.DEVICE_LOST, self.device_name or "default input")

        self._stream = sd.InputStream(
            device=index,
            samplerate=rate,
            channels=channels,
            dtype="float32",
            blocksize=int(rate * 0.02),
            callback=callback,
            finished_callback=finished,
        )
        self._stream.start()
        log.info("Capturing input device %r at %d Hz x%d", info["name"], rate, channels)

    def _stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()
