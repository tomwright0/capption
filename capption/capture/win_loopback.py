"""Windows process loopback via the native helper (native/loopback, capption-loopback.exe).

The helper captures one process tree with WASAPI process loopback and writes interleaved
float32 PCM to stdout. Its exit code says why the stream ended. Closing its stdin asks it
to stop.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from functools import cache
from pathlib import Path

import numpy as np

from .base import AudioSource, SourceEnd

log = logging.getLogger(__name__)

HELPER_NAME = "capption-loopback.exe"
RATE = 48_000
CHANNELS = 2
_CHUNK_FRAMES = RATE // 50  # 20 ms

# Helper exit codes (see native/loopback/main.cpp).
_EXIT_REASONS = {
    0: SourceEnd.STOPPED,
    2: SourceEnd.ERROR,
    3: SourceEnd.UNSUPPORTED,
    4: SourceEnd.TARGET_EXITED,
    5: SourceEnd.DEVICE_LOST,
    6: SourceEnd.ERROR,
}


def helper_path() -> Path | None:
    """Locate the helper: env override, next to the frozen app, or the CMake build dir."""
    override = os.environ.get("CAPPTION_LOOPBACK_EXE")
    candidates = [Path(override)] if override else []
    if getattr(sys, "frozen", False):
        candidates += [Path(getattr(sys, "_MEIPASS", "")) / HELPER_NAME, Path(sys.executable).parent / HELPER_NAME]
    else:
        build = Path(__file__).resolve().parents[2] / "native" / "loopback" / "build"
        candidates += [build / "Release" / HELPER_NAME, build / HELPER_NAME]
    return next((p for p in candidates if p.is_file()), None)


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


@cache
def probe() -> tuple[bool, str]:
    """Can process loopback be activated on this machine? Cached for the session."""
    exe = helper_path()
    if exe is None:
        return False, f"{HELPER_NAME} not found; build native/loopback first."
    try:
        r = subprocess.run([str(exe), "--probe"], capture_output=True, text=True, timeout=10,
                           creationflags=_no_window())
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Loopback helper failed to run: {exc}"
    if r.returncode == 0:
        return True, ""
    detail = r.stderr.strip() or f"exit code {r.returncode}"
    return False, f"Process loopback unavailable on this Windows build ({detail})."


class LoopbackSource(AudioSource):
    def __init__(self, pid: int) -> None:
        super().__init__()
        self.pid = pid
        self._proc: subprocess.Popen[bytes] | None = None
        self._reader: threading.Thread | None = None
        self._stopping = False

    def _start(self) -> None:
        exe = helper_path()
        if exe is None:
            raise FileNotFoundError(f"{HELPER_NAME} not found")
        self._stopping = False
        self._proc = subprocess.Popen(
            [str(exe), "--pid", str(self.pid), "--rate", str(RATE), "--channels", str(CHANNELS)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            creationflags=_no_window(),
        )
        self._reader = threading.Thread(target=self._read, args=(self._proc,), name=f"loopback-{self.pid}",
                                        daemon=True)
        self._reader.start()

    def _read(self, proc: subprocess.Popen[bytes]) -> None:
        assert proc.stdout is not None
        frame_bytes = 4 * CHANNELS
        chunk_bytes = _CHUNK_FRAMES * frame_bytes
        pending = b""
        while True:
            data = proc.stdout.read(chunk_bytes)
            if not data:
                break
            pending += data
            usable = len(pending) - len(pending) % frame_bytes
            if usable:
                frames = np.frombuffer(pending[:usable], dtype=np.float32).reshape(-1, CHANNELS)
                pending = pending[usable:]
                self._emit(frames, RATE, CHANNELS)
        code = proc.wait()
        stderr = proc.stderr.read().decode(errors="replace").strip() if proc.stderr else ""
        if self._stopping:
            return  # stop() reports STOPPED itself
        reason = _EXIT_REASONS.get(code, SourceEnd.ERROR)
        if reason is SourceEnd.STOPPED:
            reason = SourceEnd.ERROR  # the helper never stops on its own while we read
        last = stderr.splitlines()[-1] if stderr else f"exit code {code}"
        self._finish(reason, f"pid {self.pid}: {last}")

    def _stop(self) -> None:
        self._stopping = True
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                proc.stdin.close()  # helper exits on stdin EOF
            proc.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()
        reader = self._reader
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=2)
