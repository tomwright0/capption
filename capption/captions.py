"""What the overlay shows: confirmed text plus the current partial. Qt-free so it's unit-testable."""

from __future__ import annotations

from .asr.agreement import Word
from .asr.streamer import StreamUpdate

MAX_CHARS = 1500  # history kept for display; old text is dropped from the front


class CaptionBuffer:
    def __init__(self) -> None:
        self.confirmed = ""  # segments separated by "\n"
        self.partial = ""

    def apply(self, update: StreamUpdate) -> None:
        if update.committed:
            self.confirmed += self._joinable(update.committed)
        self.partial = "" if update.segment_end else _text(update.partial).strip()
        if update.segment_end and self.confirmed and not self.confirmed.endswith("\n"):
            self.confirmed += "\n"
        if len(self.confirmed) > MAX_CHARS:
            cut = self.confirmed.find("\n", len(self.confirmed) - MAX_CHARS)
            self.confirmed = self.confirmed[cut + 1 :] if cut >= 0 else self.confirmed[-MAX_CHARS:]

    def _joinable(self, words: list[Word]) -> str:
        text = _text(words)
        if not self.confirmed or self.confirmed.endswith("\n"):
            return text.lstrip()
        return text if text[:1].isspace() else " " + text

    def display(self) -> tuple[str, str]:
        """(confirmed, partial) ready to lay out; partial continues the last line."""
        confirmed = self.confirmed.rstrip("\n") if not self.partial else self.confirmed
        if self.partial and confirmed and not confirmed.endswith("\n"):
            return confirmed, " " + self.partial
        return confirmed, self.partial

    def clear(self) -> None:
        self.confirmed = ""
        self.partial = ""


def _text(words: list[Word]) -> str:
    return "".join(w.text for w in words)
