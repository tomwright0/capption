import numpy as np

from capption.asr.agreement import Word, join_words
from capption.asr.streamer import SAMPLE_RATE, OnlineStreamer, TranscribeResult

SCRIPT = "the quick brown fox jumps over the lazy dog".split()
WORD_S = 0.4


class FakeTranscriber:
    """Pretends each word occupies WORD_S seconds of audio of a continuous script,
    and returns the words fully inside the given buffer. The last word is garbled
    to mimic an unstable hypothesis tail."""

    def __init__(self):
        self.calls = []
        self.offset = 0.0  # set by test to the buffer's stream offset

    def transcribe(self, audio, prompt, language):
        self.calls.append((audio.size / SAMPLE_RATE, prompt, language))
        dur = audio.size / SAMPLE_RATE
        out = []
        for i, w in enumerate(SCRIPT):
            s, e = i * WORD_S - self.offset, (i + 1) * WORD_S - self.offset
            if s >= -1e-6 and e <= dur + 1e-6:
                out.append(Word(s, e, f" {w}"))
        if out and len(self.calls) % 2:
            last = out[-1]
            out[-1] = Word(last.start, last.end, last.text + "x")
        return TranscribeResult(out, "en", 0.99)


def chunk(seconds):
    return np.zeros(int(seconds * SAMPLE_RATE), dtype=np.float32)


def test_partial_then_locked_and_final_flush():
    t = FakeTranscriber()
    s = OnlineStreamer(t)
    s.start_segment(chunk(0.5), 0.0)
    committed = []
    partials = []
    for _ in range(7):
        s.append(chunk(0.5))
        u = s.process()
        committed += u.committed
        partials.append(join_words(u.partial))
    end = s.end_segment()
    committed += end.committed
    assert end.segment_end and end.partial == []
    assert join_words(committed) == " ".join(SCRIPT[: int(4.0 / WORD_S)])
    # Times are monotonic and never re-emitted.
    starts = [w.start for w in committed]
    assert starts == sorted(starts) and len(set(starts)) == len(starts)
    assert any(partials)


def test_buffer_trimmed_and_prompt_uses_history():
    t = FakeTranscriber()
    s = OnlineStreamer(t, max_buffer_s=2.0)
    s.start_segment(chunk(0.5), 0.0)
    out = []
    for _ in range(6):
        s.append(chunk(0.5))
        t.offset = s._offset
        out += s.process().committed
        assert s.buffer_seconds <= 2.5
    assert s._offset > 0
    assert t.calls[-1][1]  # prompt contains earlier confirmed words
    assert join_words(out).startswith("the quick")


def test_language_locks_after_confident_detection():
    t = FakeTranscriber()
    s = OnlineStreamer(t)
    s.start_segment(chunk(2.5), 0.0)
    s.process()
    s.process()
    assert t.calls[0][2] is None
    assert t.calls[1][2] == "en"


def test_fixed_language_passed_through():
    t = FakeTranscriber()
    s = OnlineStreamer(t, language="de")
    s.start_segment(chunk(1.0), 0.0)
    s.process()
    assert t.calls[0][2] == "de"


def test_next_segment_starts_at_stream_time():
    t = FakeTranscriber()
    s = OnlineStreamer(t)
    s.start_segment(chunk(1.0), 5.0)
    s.end_segment()
    s.start_segment(chunk(1.0), 9.0)
    assert s._offset == 9.0
