"""LocalAgreement-2 hypothesis buffer (after Macháček et al., "Turning Whisper into
Real-Time Transcription System", 2023).

A word is confirmed once two consecutive transcriptions of the growing buffer agree
on it; everything after the agreed prefix stays a mutable partial.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_NORMALISE = re.compile(r"[^\w']+", re.UNICODE)


@dataclass(frozen=True)
class Word:
    start: float  # seconds, stream time
    end: float
    text: str  # as produced by Whisper, usually with a leading space

    def shifted(self, offset: float) -> "Word":
        return Word(self.start + offset, self.end + offset, self.text)


def norm(text: str) -> str:
    """Comparison key: case and punctuation differences shouldn't block agreement."""
    return _NORMALISE.sub("", text).lower()


def join_words(words: list[Word]) -> str:
    return "".join(w.text for w in words).strip()


class HypothesisBuffer:
    MAX_NGRAM = 5

    def __init__(self) -> None:
        self.committed_in_buffer: list[Word] = []
        self.buffer: list[Word] = []  # previous unconfirmed hypothesis
        self.new: list[Word] = []
        self.last_committed_time = 0.0

    def insert(self, words: list[Word], offset: float) -> None:
        shifted = [w.shifted(offset) for w in words]
        # Only words after what's already locked can still change.
        self.new = [w for w in shifted if w.start > self.last_committed_time - 0.1]
        if self.new and abs(self.new[0].start - self.last_committed_time) < 1.0 and self.committed_in_buffer:
            # Whisper often re-emits the tail of the committed text; drop that overlap.
            limit = min(len(self.committed_in_buffer), len(self.new), self.MAX_NGRAM)
            for i in range(limit, 0, -1):
                tail = [norm(w.text) for w in self.committed_in_buffer[-i:]]
                head = [norm(w.text) for w in self.new[:i]]
                if tail == head:
                    del self.new[:i]
                    break

    def flush(self) -> list[Word]:
        """Commit the longest prefix shared by the previous and current hypothesis."""
        commit: list[Word] = []
        while self.new and self.buffer and norm(self.new[0].text) == norm(self.buffer[0].text):
            word = self.new.pop(0)
            self.buffer.pop(0)
            commit.append(word)
            self.last_committed_time = word.end
        self.buffer = self.new
        self.new = []
        self.committed_in_buffer.extend(commit)
        return commit

    def force_commit(self) -> list[Word]:
        """Lock whatever is pending, e.g. at the end of a speech segment."""
        commit = [w for w in self.buffer if w.start > self.last_committed_time - 0.1]
        if commit:
            self.last_committed_time = commit[-1].end
        self.committed_in_buffer.extend(commit)
        self.buffer = []
        self.new = []
        return commit

    def pop_committed(self, time: float) -> None:
        """Forget committed words that ended before ``time`` (audio was trimmed)."""
        while self.committed_in_buffer and self.committed_in_buffer[0].end <= time:
            self.committed_in_buffer.pop(0)

    def partial(self) -> list[Word]:
        return list(self.buffer)
