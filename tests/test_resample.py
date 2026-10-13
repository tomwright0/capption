import numpy as np

from capption.capture.resample import Resampler


def _tone(rate, seconds, freq=440.0):
    t = np.arange(int(rate * seconds)) / rate
    return np.sin(2 * np.pi * freq * t).astype(np.float32)


def test_stereo_48k_to_mono_16k_chunked():
    tone = _tone(48_000, 1.0)
    stereo = np.stack([tone, tone], axis=1)
    r = Resampler(48_000, 2, 16_000)
    out = np.concatenate([r.process(stereo[i:i + 480]) for i in range(0, len(stereo), 480)])
    assert out.dtype == np.float32
    # Streaming resampler holds back a few ms of filter delay.
    assert 15_500 <= out.size <= 16_000
    assert 0.6 < np.abs(out[2000:14000]).max() <= 1.01


def test_interleaved_1d_input():
    tone = _tone(16_000, 0.1)
    interleaved = np.stack([tone, tone], axis=1).reshape(-1)
    out = Resampler(16_000, 2, 16_000).process(interleaved)
    np.testing.assert_allclose(out, tone, atol=1e-6)


def test_int16_input_scaled():
    out = Resampler(16_000, 1, 16_000).process(np.array([16384, -32768], dtype=np.int16))
    np.testing.assert_allclose(out, [0.5, -1.0])
