from capption.asr.agreement import HypothesisBuffer, Word, join_words


def words(*items, start=0.0, step=0.5):
    return [Word(start + i * step, start + (i + 1) * step - 0.05, f" {t}") for i, t in enumerate(items)]


def test_commits_only_agreed_prefix():
    h = HypothesisBuffer()
    h.insert(words("hello", "world"), 0.0)
    assert h.flush() == []  # first hypothesis never commits
    assert join_words(h.partial()) == "hello world"

    h.insert(words("hello", "world", "again"), 0.0)
    assert join_words(h.flush()) == "hello world"
    assert join_words(h.partial()) == "again"


def test_disagreement_stops_commit():
    h = HypothesisBuffer()
    h.insert(words("I", "scream"), 0.0)
    h.flush()
    h.insert(words("ice", "cream"), 0.0)
    assert h.flush() == []
    assert join_words(h.partial()) == "ice cream"


def test_case_and_punctuation_insensitive_but_keeps_new_text():
    h = HypothesisBuffer()
    h.insert(words("hello"), 0.0)
    h.flush()
    h.insert(words("Hello,", "there"), 0.0)
    assert [w.text for w in h.flush()] == [" Hello,"]


def test_committed_words_not_reemitted_after_overlap():
    h = HypothesisBuffer()
    h.insert(words("one", "two", "three"), 0.0)
    h.flush()
    h.insert(words("one", "two", "three", "four"), 0.0)
    assert join_words(h.flush()) == "one two three"
    # Buffer trimmed: new pass starts at 1.0 s but Whisper repeats "two three".
    h.pop_committed(1.0)
    h.insert(words("two", "three", "four", "five", start=0.5), 0.5)
    assert join_words(h.flush()) == "four"
    assert join_words(h.partial()) == "five"


def test_force_commit_locks_partial():
    h = HypothesisBuffer()
    h.insert(words("a", "b"), 0.0)
    h.flush()
    assert join_words(h.force_commit()) == "a b"
    assert h.partial() == []
    assert h.last_committed_time == words("a", "b")[-1].end
