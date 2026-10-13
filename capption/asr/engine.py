"""faster-whisper wrapper: device selection, CUDA->CPU fallback, OOM recovery."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .agreement import Word
from .streamer import TranscribeResult

log = logging.getLogger(__name__)

# Hallucination guards for short streaming windows.
NO_SPEECH_SKIP = 0.6
LOGPROB_SKIP = -1.0


@dataclass(frozen=True)
class EngineInfo:
    model: str
    device: str
    compute_type: str
    fallback_reason: str | None = None  # set when we wanted CUDA but got CPU


def add_cuda_dll_dirs() -> None:
    """On Windows, make the cuBLAS/cudart DLLs from the nvidia-* wheels (or a frozen
    bundle) findable. ctranslate2 loads them lazily, so this is safe without a GPU."""
    if sys.platform != "win32":
        return
    roots: list[Path] = []
    if getattr(sys, "frozen", False):
        bundle = Path(getattr(sys, "_MEIPASS", ""))
        roots += [bundle, bundle / "nvidia"]  # capption.spec keeps the wheels' nvidia/*/bin layout
    try:
        import nvidia  # namespace package from nvidia-*-cu12 wheels

        roots += [Path(p) for p in nvidia.__path__]
    except ImportError:
        pass
    for root in roots:
        for bin_dir in [root, *root.glob("*/bin")]:
            if bin_dir.is_dir() and any(bin_dir.glob("*.dll")):
                try:
                    os.add_dll_directory(str(bin_dir))
                    os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
                except OSError:
                    pass


def cuda_available() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def is_oom(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "out of memory" in msg or "cuda_error_out_of_memory" in msg or "cublas_status_alloc_failed" in msg


class WhisperEngine:
    """Implements the :class:`~capption.asr.streamer.Transcriber` protocol."""

    def __init__(
        self,
        model: str,
        device: str = "auto",
        compute_type: str = "auto",
        download_root: str | None = None,
        translate: bool = False,
        beam_size: int = 1,
    ) -> None:
        self.translate = translate
        self.beam_size = beam_size
        self._model_name = model
        self._download_root = download_root
        add_cuda_dll_dirs()
        self.model, self.info = self._load(model, device, compute_type)

    def _load(self, model: str, device: str, compute_type: str):
        from faster_whisper import WhisperModel

        want_cuda = device in ("auto", "cuda") and cuda_available()
        reason = None
        if want_cuda:
            ct = "float16" if compute_type == "auto" else compute_type
            try:
                m = WhisperModel(model, device="cuda", compute_type=ct, download_root=self._download_root)
                # Run a tiny pass so missing DLLs / unsupported arch fail here, not mid-stream.
                list(m.transcribe(np.zeros(16000, dtype=np.float32), beam_size=1, language="en")[0])
                log.info("Loaded %s on CUDA (%s)", model, ct)
                return m, EngineInfo(model, "cuda", ct)
            except Exception as exc:
                reason = f"CUDA init failed: {exc}"
                log.warning("%s; falling back to CPU int8", reason)
        elif device == "cuda":
            reason = "No CUDA device found"
        ct = "int8" if compute_type in ("auto", "float16") else compute_type
        m = WhisperModel(model, device="cpu", compute_type=ct, download_root=self._download_root)
        log.info("Loaded %s on CPU (%s)", model, ct)
        return m, EngineInfo(model, "cpu", ct, reason)

    def fall_back_to_cpu(self, reason: str) -> None:
        """Called after a GPU OOM: reload the same model on CPU."""
        log.warning("Reloading %s on CPU: %s", self._model_name, reason)
        del self.model
        self.model, info = self._load(self._model_name, "cpu", "int8")
        self.info = EngineInfo(info.model, info.device, info.compute_type, reason)

    def transcribe(self, audio: np.ndarray, prompt: str, language: str | None) -> TranscribeResult:
        segments, info = self.model.transcribe(
            audio,
            language=language,
            task="translate" if self.translate else "transcribe",
            beam_size=self.beam_size,
            initial_prompt=prompt or None,
            condition_on_previous_text=False,
            word_timestamps=True,
            vad_filter=False,  # our own streaming VAD already gated the audio
            without_timestamps=False,
        )
        words: list[Word] = []
        for seg in segments:
            if seg.no_speech_prob > NO_SPEECH_SKIP and seg.avg_logprob < LOGPROB_SKIP:
                continue
            for w in seg.words or []:
                words.append(Word(w.start, w.end, w.word))
        return TranscribeResult(words, info.language, info.language_probability)
