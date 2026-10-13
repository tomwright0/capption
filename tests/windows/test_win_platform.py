"""Real Windows API checks. Capture tests need the built helper and an audio output device."""

import subprocess
import sys
import threading
import time

import numpy as np
import pytest

if sys.platform != "win32":
    pytest.skip("Windows-only", allow_module_level=True)

from capption.capture.base import SourceEnd
from capption.capture.win_loopback import LoopbackSource, helper_path, probe
from capption.platform import windows

pytestmark = pytest.mark.windows

needs_helper = pytest.mark.skipif(helper_path() is None, reason="capption-loopback.exe not built")


def test_sequence_to_vk():
    ctrl_alt = windows.MOD_NOREPEAT | windows.MOD_CONTROL | windows.MOD_ALT
    assert windows.sequence_to_vk("Ctrl+Alt+C") == (ctrl_alt, ord("C"))
    assert windows.sequence_to_vk("Shift+F9") == (windows.MOD_NOREPEAT | windows.MOD_SHIFT, 0x78)
    assert windows.sequence_to_vk("Ctrl+Space") == (windows.MOD_NOREPEAT | windows.MOD_CONTROL, 0x20)
    assert windows.sequence_to_vk("") is None


def test_enumerate_sessions_runs():
    sessions = windows.enumerate_sessions()
    assert all(s.pid > 0 for s in sessions)


@needs_helper
def test_probe():
    ok, message = probe()
    assert ok, message


def _has_output_device() -> bool:
    import sounddevice as sd

    try:
        sd.query_devices(kind="output")
        return True
    except Exception:
        return False


@needs_helper
@pytest.mark.slow
def test_capture_child_process(speech_wav):
    if not _has_output_device():
        pytest.skip("no audio output device")
    # Child process that loops the fixture on the default output at zero risk of
    # being heard loudly (loopback captures before the endpoint volume).
    code = (
        "import sys, wave, numpy as np, sounddevice as sd\n"
        "w = wave.open(sys.argv[1]); a = np.frombuffer(w.readframes(w.getnframes()), np.int16)\n"
        "a = (a.astype(np.float32) / 32768 * 0.2).reshape(-1, w.getnchannels())\n"
        "sd.play(a, w.getframerate(), loop=True); sd.sleep(60000)\n"
    )
    player = subprocess.Popen([sys.executable, "-c", code, str(speech_wav)])
    try:
        time.sleep(1.5)
        chunks: list[np.ndarray] = []
        ended = threading.Event()
        result: list[SourceEnd] = []
        source = LoopbackSource(player.pid)
        source.start(chunks.append, lambda reason, detail: (result.append(reason), ended.set()))
        time.sleep(3)
        player.kill()
        assert ended.wait(5)
        assert result == [SourceEnd.TARGET_EXITED]
        audio = np.concatenate(chunks)
        assert audio.size > 16_000 * 2  # roughly real time
        assert np.sqrt(np.mean(audio**2)) > 1e-3
    finally:
        player.kill()


@needs_helper
def test_stop_is_quick():
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        source = LoopbackSource(sleeper.pid)
        result: list[SourceEnd] = []
        source.start(lambda a: None, lambda reason, detail: result.append(reason))
        time.sleep(0.5)
        t0 = time.perf_counter()
        source.stop()
        assert time.perf_counter() - t0 < 2
        assert result == [SourceEnd.STOPPED]
    finally:
        sleeper.kill()
