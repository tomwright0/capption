"""Rolling-buffer streaming transcription on top of any batch transcriber."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from .agreement import HypothesisBuffer, Word, join_words

SAMPLE_RATE = 16_000
PROMPT_CHARS = 200
HISTORY_WORDS = 100
LANGUAGE_LOCK_PROB = 0.7
LANGUAGE_LOCK_MIN_S = 2.0


@dataclass
class TranscribeResult:
    words: list[Word]  # times relative to the start of the audio passed in
    language: str | None = None
    language_prob: float = 0.0


class Transcriber(Protocol):
    def transcribe(self, audio: np.ndarray, prompt: str, language: str | None) -> TranscribeResult: ...


@dataclass
class StreamUpdate:
    committed: list[Word] = field(default_factory=list)  # newly locked words, in order
    partial: list[Word] = field(default_factory=list)  # replaces the previous partial
    segment_end: bool = False
    language: str | None = None


class OnlineStreamer:
    """Accumulates one speech segment and re-transcribes it as it grows.

    Words confirmed by LocalAgreement are emitted once and never change. The audio
    buffer is trimmed behind confirmed words so each pass stays short.
    """

    def __init__(self, transcriber: Transcriber, language: str | None = None, max_buffer_s: float = 15.0) -> None:
        self.transcriber = transcriber
        self.fixed_language = language
        self.max_buffer_s = max_buffer_s
        self._history: list[Word] = []  # all committed words, for the prompt
        self._reset_segment(0.0)

    def _reset_segment(self, start: float) -> None:
        self._audio = np.zeros(0, dtype=np.float32)
        self._offset = start  # stream time of self._audio[0]
        self._hyp = HypothesisBuffer()
        self._hyp.last_committed_time = start
        self._segment_language: str | None = None

    @property
    def buffer_seconds(self) -> float:
        return self._audio.size / SAMPLE_RATE

    def start_segment(self, audio: np.ndarray, time: float) -> None:
        self._reset_segment(time)
        self._audio = audio.astype(np.float32, copy=True)

    def append(self, audio: np.ndarray) -> None:
        self._audio = np.concatenate([self._audio, audio])

    def process(self) -> StreamUpdate:
        if self._audio.size == 0:
            return StreamUpdate()
        result = self._run()
        self._hyp.insert(result.words, self._offset)
        committed = self._hyp.flush()
        self._remember(committed)
        if self.buffer_seconds > self.max_buffer_s:
            committed += self._trim()
        return StreamUpdate(committed, self._hyp.partial(), language=self._language())

    def end_segment(self) -> StreamUpdate:
        """Final pass over the segment; everything left becomes confirmed."""
        committed: list[Word] = []
        if self._audio.size:
            result = self._run()
            self._hyp.insert(result.words, self._offset)
            committed = self._hyp.flush()
            committed += self._hyp.force_commit()
        self._remember(committed)
        language = self._language()
        self._reset_segment(self._offset + self.buffer_seconds)
        return StreamUpdate(committed, [], segment_end=True, language=language)

    def _run(self) -> TranscribeResult:
        result = self.transcriber.transcribe(self._audio, self._prompt(), self._language())
        if (
            self.fixed_language is None
            and self._segment_language is None
            and result.language
            and result.language_prob >= LANGUAGE_LOCK_PROB
            and self.buffer_seconds >= LANGUAGE_LOCK_MIN_S
        ):
            # Detection on a fraction of a second is noisy; lock once it's confident.
            self._segment_language = result.language
        return result

    def _language(self) -> str | None:
        return self.fixed_language or self._segment_language

    def _remember(self, words: list[Word]) -> None:
        self._history.extend(words)
        del self._history[:-HISTORY_WORDS]

    def _prompt(self) -> str:
        before = [w for w in self._history if w.end <= self._offset]
        return join_words(before)[-PROMPT_CHARS:]

    def _trim(self) -> list[Word]:
        """Drop audio behind the last confirmed word. If nothing is confirmed in a
        full buffer, lock the partial rather than let the buffer grow unbounded."""
        forced: list[Word] = []
        cut = self._hyp.last_committed_time
        if cut - self._offset < 1.0:
            forced = self._hyp.force_commit()
            self._remember(forced)
            cut = max(self._hyp.last_committed_time, self._offset + self.buffer_seconds - 1.0)
        drop = int((cut - self._offset) * SAMPLE_RATE)
        drop = max(0, min(drop, self._audio.size))
        self._audio = self._audio[drop:]
        self._offset += drop / SAMPLE_RATE
        self._hyp.pop_committed(self._offset)
        return forced
