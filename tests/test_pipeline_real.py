"""Real Silero VAD and (optionally) a real Whisper model on a speech fixture."""

import os

import pytest

from capption.asr.vad import SileroVad, VadSegmenter
from capption.capture.file_source import load_audio

pytestmark = pytest.mark.slow


def test_silero_finds_both_utterances(speech_wav):
    audio = load_audio(speech_wav)
    seg = VadSegmenter(SileroVad(), min_silence_ms=500)
    events = []
    for i in range(0, audio.size, 1600):
        events += seg.feed(audio[i:i + 1600])
    events += seg.flush()
    starts = [e.time for e in events if e.kind == "start"]
    assert len(starts) == 2
    assert 0.5 < starts[0] < 1.2  # fixture has 1 s of leading silence (minus pre-roll)


@pytest.mark.skipif(not os.environ.get("CAPPTION_TEST_MODEL"), reason="set CAPPTION_TEST_MODEL=tiny (and optionally CAPPTION_TEST_MODEL_DIR) to run")
def test_whisper_streaming_transcript(speech_wav):
    from capption.asr.agreement import join_words
    from capption.asr.engine import WhisperEngine
    from capption.asr.worker import AsrWorker

    engine = WhisperEngine(
        os.environ["CAPPTION_TEST_MODEL"], device="cpu", download_root=os.environ.get("CAPPTION_TEST_MODEL_DIR")
    )
    updates = []
    worker = AsrWorker(engine, VadSegmenter(SileroVad()), updates.append, language="en")
    worker.start()
    audio = load_audio(speech_wav)
    for i in range(0, audio.size, 1600):
        worker.push(audio[i:i + 1600])
    worker.stop(timeout=120)
    text = join_words([w for u in updates for w in u.committed]).lower()
    assert "quick brown fox" in text
    assert "real time" in text or "real-time" in text
    assert sum(u.segment_end for u in updates) == 2
