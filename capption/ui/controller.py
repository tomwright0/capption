"""Owns one captioning session: model, capture source, ASR worker, transcript.

All public methods run on the GUI thread. Callbacks from capture/ASR threads are
re-emitted as Qt signals, which Qt delivers on the GUI thread.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from ..asr import models
from ..asr.engine import EngineInfo, WhisperEngine
from ..asr.streamer import StreamUpdate
from ..asr.vad import SileroVad, VadSegmenter
from ..asr.worker import AsrWorker, Metrics
from ..capture.base import AudioSource, SourceEnd, SourceInfo
from ..config import AppConfig, data_dir
from ..platform import Platform
from ..transcript.writer import TranscriptWriter

log = logging.getLogger(__name__)

REATTACH_MS = 2000


@dataclass(frozen=True)
class EngineKey:
    model: str
    device: str
    compute_type: str
    translate: bool
    beam_size: int


class CaptionController(QObject):
    update = Signal(object)  # StreamUpdate
    metrics = Signal(object)  # Metrics
    status = Signal(str, str)  # level ("info" | "warning" | "error"), message
    state_changed = Signal(str)  # "idle" | "loading" | "running" | "waiting"
    engine_changed = Signal(object)  # EngineInfo
    model_missing = Signal(str)

    # Cross-thread plumbing (emitted from worker/capture threads).
    _engine_loaded = Signal(object, object)  # engine | None, error str | None
    _source_ended = Signal(object, str)
    _worker_failed = Signal(str)

    def __init__(self, config: AppConfig, platform: Platform) -> None:
        super().__init__()
        self.config = config
        self.platform = platform
        self.state = "idle"
        self.source_info: SourceInfo | None = None
        self._engine: WhisperEngine | None = None
        self._engine_key: EngineKey | None = None
        self._source: AudioSource | None = None
        self._worker: AsrWorker | None = None
        self._writer: TranscriptWriter | None = None
        self._load_token = 0
        self._reattach = QTimer(self, interval=REATTACH_MS)
        self._reattach.timeout.connect(self._try_reattach)
        self._engine_loaded.connect(self._on_engine_loaded)
        self._source_ended.connect(self._on_source_ended)
        self._worker_failed.connect(self._on_worker_failed)
        self.update.connect(self._write_transcript)

    @property
    def engine_info(self) -> EngineInfo | None:
        return self._engine.info if self._engine else None

    # -- lifecycle ---------------------------------------------------------------
    def start(self, source: SourceInfo) -> None:
        self.stop()
        self.source_info = source
        if source.kind == "process":
            self.config.capture.last_exe = source.key
        asr = self.config.asr
        if not models.is_downloaded(asr.model):
            self.model_missing.emit(asr.model)
            self.status.emit("error", f"Model “{asr.model}” isn't downloaded yet. Download it under Models.")
            return
        key = EngineKey(asr.model, asr.device, asr.compute_type, asr.translate, asr.beam_size)
        if self._engine is not None and self._engine_key == key:
            self._begin_capture()
            return
        self._set_state("loading")
        self.status.emit("info", f"Loading {asr.model}…")
        self._load_token += 1
        token = self._load_token
        self._engine, self._engine_key = None, key

        def load() -> None:
            try:
                engine = WhisperEngine(
                    models.local_path(asr.model) or asr.model,
                    device=asr.device,
                    compute_type=asr.compute_type,
                    download_root=str(models.models_dir()),
                    translate=asr.translate,
                    beam_size=asr.beam_size,
                )
                self._engine_loaded.emit((token, engine), None)
            except Exception as exc:
                log.exception("Model load failed")
                self._engine_loaded.emit((token, None), str(exc))

        threading.Thread(target=load, name="model-load", daemon=True).start()

    def _on_engine_loaded(self, payload, error: str | None) -> None:
        token, engine = payload
        if token != self._load_token or self.state != "loading":
            return  # superseded by stop() or a newer start()
        if engine is None:
            self._engine_key = None
            self._set_state("idle")
            self.status.emit("error", f"Couldn't load model: {error}")
            return
        self._engine = engine
        self.engine_changed.emit(engine.info)
        if engine.info.fallback_reason:
            self.status.emit("warning", f"Running on CPU — {engine.info.fallback_reason}")
        self._begin_capture()

    def _begin_capture(self) -> None:
        assert self._engine is not None and self.source_info is not None
        asr = self.config.asr
        self._worker = AsrWorker(
            self._engine,
            VadSegmenter(SileroVad(), threshold=asr.vad_threshold, min_silence_ms=asr.min_silence_ms),
            on_update=self.update.emit,
            on_metrics=self.metrics.emit,
            on_error=self._worker_failed.emit,
            language=asr.language,
            step_s=asr.step_s,
            max_buffer_s=asr.max_buffer_s,
            on_oom=self._on_oom,
        )
        self._worker.start()
        self._open_writer()
        if self._attach(self.source_info):
            self._set_state("running")
            self.status.emit("info", f"Captioning {self.source_info.label}")
        else:
            self._wait_for_source()

    def _attach(self, info: SourceInfo) -> bool:
        try:
            source = self.platform.create_source(info, self.config)
            source.start(self._worker.push, lambda reason, detail: self._source_ended.emit(reason, detail))
        except Exception as exc:
            log.warning("Could not start capture for %s: %s", info.label, exc)
            return False
        self._source = source
        return True

    def stop(self) -> None:
        self._load_token += 1
        self._reattach.stop()
        source, self._source = self._source, None
        if source is not None:
            source.stop()
        worker, self._worker = self._worker, None
        if worker is not None:
            # Let the last segment flush in the background so Stop is instant.
            threading.Thread(target=worker.stop, name="asr-stop", daemon=True).start()
        if self._writer is not None:
            self._writer.close()
            self._writer = None
        if self.state != "idle":
            self._set_state("idle")
            self.status.emit("info", "Stopped")

    # -- transcript ------------------------------------------------------------------
    def _open_writer(self) -> None:
        t = self.config.transcript
        if not t.enabled or not (t.txt or t.srt):
            return
        directory = Path(t.directory) if t.directory else data_dir() / "transcripts"
        try:
            self._writer = TranscriptWriter(directory, self.source_info.key if self.source_info else "capture", t.txt, t.srt)
        except OSError as exc:
            self.status.emit("warning", f"Transcript disabled: {exc}")
            return

    def _write_transcript(self, update: StreamUpdate) -> None:
        if self._writer is not None:
            self._writer.add(update.committed, update.segment_end)

    # -- failure handling ------------------------------------------------------------
    def _on_source_ended(self, reason: SourceEnd, detail: str) -> None:
        if self._worker is None or reason is SourceEnd.STOPPED:
            return
        self._source = None
        if reason is SourceEnd.EOF:
            self.stop()
            return
        if reason is SourceEnd.UNSUPPORTED:
            self.stop()
            self.status.emit("error", f"Capture unsupported: {detail}")
            return
        log.info("Source lost (%s): %s", reason.value, detail)
        self._wait_for_source()

    def _wait_for_source(self) -> None:
        self._set_state("waiting")
        label = self.source_info.label if self.source_info else "source"
        self.status.emit("warning", f"Waiting for {label}… captions resume automatically.")
        self._reattach.start()

    def _try_reattach(self) -> None:
        info = self.source_info
        if info is None or self._worker is None:
            self._reattach.stop()
            return
        current = self.platform.find_app(info.key) if info.kind == "process" else info
        if current is not None and self._attach(current):
            self.source_info = current
            self._reattach.stop()
            self._set_state("running")
            self.status.emit("info", f"Reattached to {current.label}")

    def _on_worker_failed(self, message: str) -> None:
        self.stop()
        self.status.emit("error", f"Transcription stopped: {message}")

    def _on_oom(self, reason: str) -> bool:
        """Worker thread. Out of GPU memory: continue on CPU rather than stop."""
        if self._engine is None or self._engine.info.device != "cuda":
            return False
        self._engine.fall_back_to_cpu("GPU out of memory")
        self.status.emit("warning", "GPU ran out of memory — continuing on CPU (slower). Try a smaller model.")
        self.engine_changed.emit(self._engine.info)
        return True

    def _set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self.state_changed.emit(state)

    @staticmethod
    def describe_metrics(m: Metrics) -> str:
        return (
            f"queue {m.queue_s:.2f}s · window {m.buffer_s:.1f}s · infer {m.last_infer_s * 1000:.0f}ms · "
            f"RTF {m.rtf:.2f} · dropped {m.dropped_s:.1f}s · {'speech' if m.in_speech else 'silence'}"
        )
