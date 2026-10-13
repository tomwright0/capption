"""Per-session transcript files (.txt and/or .srt), one cue per speech segment."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TextIO

from ..asr.agreement import Word, join_words

log = logging.getLogger(__name__)

MAX_CUE_S = 7.0  # long monologues are split into readable subtitle cues


def srt_time(seconds: float) -> str:
    ms = max(0, round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


class TranscriptWriter:
    def __init__(self, directory: Path, source_label: str, txt: bool = True, srt: bool = True) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in source_label)[:40]
        base = directory / f"{stamp}_{safe}"
        self.txt_path = Path(f"{base}.txt") if txt else None
        self.srt_path = Path(f"{base}.srt") if srt else None
        self._txt: TextIO | None = open(self.txt_path, "w", encoding="utf-8") if self.txt_path else None
        self._srt: TextIO | None = open(self.srt_path, "w", encoding="utf-8") if self.srt_path else None
        self._cue: list[Word] = []
        self._index = 0

    def add(self, committed: list[Word], segment_end: bool) -> None:
        for word in committed:
            if self._cue and word.end - self._cue[0].start > MAX_CUE_S:
                self._write_cue()
            self._cue.append(word)
        if segment_end:
            self._write_cue()

    def _write_cue(self) -> None:
        if not self._cue:
            return
        text = join_words(self._cue)
        if self._txt:
            self._txt.write(text + "\n")
            self._txt.flush()
        if self._srt:
            self._index += 1
            self._srt.write(
                f"{self._index}\n{srt_time(self._cue[0].start)} --> {srt_time(self._cue[-1].end)}\n{text}\n\n"
            )
            self._srt.flush()
        self._cue = []

    def close(self) -> None:
        self._write_cue()
        for fh in (self._txt, self._srt):
            if fh:
                fh.close()
        self._txt = self._srt = None
