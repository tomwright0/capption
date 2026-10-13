import threading

import numpy as np

from capption.asr.agreement import Word, join_words
from capption.asr.streamer import SAMPLE_RATE, TranscribeResult
from capption.asr.vad import WINDOW, VadSegmenter
from capption.asr.worker import AsrWorker


class LoudnessVad:
    def __call__(self, w):
        return 1.0 if np.abs(w).mean() > 0.1 else 0.0


class OneWord:
    def transcribe(self, audio, prompt, language):
        return TranscribeResult([Word(0.0, 0.3, " hi")], "en", 0.9)


class Boom:
    def __init__(self):
        self.calls = 0

    def transcribe(self, audio, prompt, language):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("CUDA failed with error out of memory")
        return TranscribeResult([Word(0.0, 0.3, " ok")], "en", 0.9)


def run(transcriber, audio, **kw):
    updates = []
    done = threading.Event()
    worker = AsrWorker(transcriber, VadSegmenter(LoudnessVad(), min_silence_ms=200), updates.append, **kw)
    worker.start()
    for i in range(0, audio.size, 800):
        worker.push(audio[i:i + 800])
    worker.stop()
    return updates, worker


def speech_then_silence(speech_s=1.5, silence_s=1.0):
    return np.concatenate([np.full(int(speech_s * SAMPLE_RATE), 0.5, np.float32),
                           np.zeros(int(silence_s * SAMPLE_RATE), np.float32)])


def test_segment_end_commits_text():
    updates, worker = run(OneWord(), speech_then_silence())
    text = join_words([w for u in updates for w in u.committed])
    assert text == "hi"
    assert updates[-1].segment_end
    assert worker.metrics.queue_s == 0


def test_silence_never_transcribed():
    class Fail:
        def transcribe(self, *a):
            raise AssertionError("should not run on silence")

    updates, _ = run(Fail(), np.zeros(SAMPLE_RATE * 3, np.float32))
    assert updates == []


def test_oom_triggers_fallback_and_retry():
    reasons = []
    updates, _ = run(Boom(), speech_then_silence(), on_oom=lambda r: reasons.append(r) or True)
    assert reasons and "out of memory" in reasons[0]
    assert any(u.committed for u in updates)
