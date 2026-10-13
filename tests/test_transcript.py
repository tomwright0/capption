from capption.asr.agreement import Word
from capption.transcript.writer import TranscriptWriter, srt_time


def test_srt_time():
    assert srt_time(0) == "00:00:00,000"
    assert srt_time(3723.4567) == "01:02:03,457"


def test_writes_cues_per_segment_and_splits_long_ones(tmp_path):
    w = TranscriptWriter(tmp_path, "chrome.exe")
    w.add([Word(1.0, 1.4, " Hello"), Word(1.5, 1.9, " world.")], segment_end=False)
    w.add([], segment_end=True)
    long = [Word(10 + i, 10.8 + i, f" w{i}") for i in range(10)]
    w.add(long, segment_end=True)
    w.close()
    srt = w.srt_path.read_text()
    assert srt.startswith("1\n00:00:01,000 --> 00:00:01,900\nHello world.\n")
    assert srt.count("-->") == 3  # 1 short cue + long segment split in two
    assert w.txt_path.read_text().splitlines()[0] == "Hello world."
    assert "chrome.exe" in w.srt_path.name
