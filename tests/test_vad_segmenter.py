import numpy as np

from capption.asr.vad import SAMPLE_RATE, WINDOW, VadSegmenter


def scripted(probs):
    """prob_fn returning a scripted value per window."""
    it = iter(probs)
    return lambda _w: next(it)


def windows(n):
    return np.ones(n * WINDOW, dtype=np.float32)


def test_segment_start_audio_end_with_preroll():
    # 10 silent, 20 speech, 20 silent windows; min silence 500 ms = 15 windows
    probs = [0.0] * 10 + [0.9] * 20 + [0.0] * 20
    seg = VadSegmenter(scripted(probs), min_silence_ms=500, preroll_ms=96)  # 3 windows preroll
    events = seg.feed(windows(len(probs)))
    kinds = [e.kind for e in events]
    assert kinds == ["start", "audio", "end"]
    start = events[0]
    assert start.audio.size == 4 * WINDOW  # 3 preroll + first speech window
    assert start.time == 7 * WINDOW / SAMPLE_RATE
    assert not seg.in_speech


def test_split_feeds_match_single_feed():
    probs = [0.0] * 5 + [0.9] * 10 + [0.0] * 30
    a = VadSegmenter(scripted(probs), min_silence_ms=200)
    whole = a.feed(windows(len(probs)))
    b = VadSegmenter(scripted(probs), min_silence_ms=200)
    data = windows(len(probs))
    parts = []
    for i in range(0, data.size, 700):  # chunks not aligned to windows
        parts += b.feed(data[i:i + 700])
    boundaries = lambda evs: [e.kind for e in evs if e.kind != "audio"]
    assert boundaries(whole) == boundaries(parts) == ["start", "end"]
    total = lambda evs: sum(e.audio.size for e in evs if e.audio is not None)
    assert total(whole) == total(parts)


def test_short_dips_do_not_end_segment():
    probs = [0.9] * 5 + [0.0] * 5 + [0.9] * 5 + [0.0] * 3
    seg = VadSegmenter(scripted(probs), min_silence_ms=500)
    events = seg.feed(windows(len(probs)))
    assert [e.kind for e in events].count("end") == 0
    assert seg.in_speech
    assert [e.kind for e in seg.flush()] == ["end"]


def test_hysteresis_keeps_speech_between_thresholds():
    probs = [0.9] + [0.4] * 30  # 0.4 is above neg_threshold (0.35)
    seg = VadSegmenter(scripted(probs), threshold=0.5, min_silence_ms=100)
    seg.feed(windows(len(probs)))
    assert seg.in_speech


def test_skip_advances_clock():
    seg = VadSegmenter(lambda _w: 0.0)
    seg.skip(SAMPLE_RATE)
    assert abs(seg.time - SAMPLE_RATE // WINDOW * WINDOW / SAMPLE_RATE) < 1e-9
