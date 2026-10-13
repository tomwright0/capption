from capption.asr.agreement import Word
from capption.asr.streamer import StreamUpdate
from capption.captions import MAX_CHARS, CaptionBuffer


def w(text, t=0.0):
    return Word(t, t + 0.1, text)


def test_partial_replaced_and_confirmed_appends():
    b = CaptionBuffer()
    b.apply(StreamUpdate([], [w(" Hello"), w(" wor")]))
    assert b.display() == ("", "Hello wor")
    b.apply(StreamUpdate([w(" Hello")], [w(" world")]))
    assert b.display() == ("Hello", " world")
    b.apply(StreamUpdate([w(" world.")], [], segment_end=True))
    assert b.display() == ("Hello world.", "")


def test_segments_start_new_lines():
    b = CaptionBuffer()
    b.apply(StreamUpdate([w(" One.")], [], segment_end=True))
    b.apply(StreamUpdate([w(" Two")], [w(" three")]))
    assert b.display() == ("One.\nTwo", " three")
    b.apply(StreamUpdate([], [], segment_end=True))
    b.apply(StreamUpdate([], [w(" Four")]))
    assert b.display() == ("One.\nTwo\n", "Four")


def test_history_trimmed_at_line_boundary():
    b = CaptionBuffer()
    for i in range(400):
        b.apply(StreamUpdate([w(f" line{i}")], [], segment_end=True))
    assert len(b.confirmed) <= MAX_CHARS
    assert b.confirmed.startswith("line")
    assert b.confirmed.rstrip().endswith("line399")
