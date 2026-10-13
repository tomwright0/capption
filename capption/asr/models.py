"""Model catalogue: download (with progress), status, size and deletion.

Models live in the Hugging Face cache layout under ``models_dir()``, which is also
what :class:`~capption.asr.engine.WhisperEngine` passes to faster-whisper as
``download_root``, so a downloaded model is found without any extra mapping.
"""

from __future__ import annotations

import io
import logging
import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tqdm import tqdm

from ..config import models_dir

log = logging.getLogger(__name__)

# Offered in the UI, best first. Values are faster-whisper names.
BUILTIN_MODELS = ["large-v3-turbo", "distil-large-v3", "medium", "small", "tiny"]

# Same files faster-whisper's own download_model() fetches.
ALLOW_PATTERNS = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]

ProgressCallback = Callable[[int, int], None]  # (bytes_done, bytes_total)


@dataclass
class ModelStatus:
    name: str  # faster-whisper name or HF repo id
    repo_id: str
    size_bytes: int | None  # None until known (needs network once)
    downloaded: bool
    builtin: bool


class DownloadCancelled(Exception):
    pass


def repo_id_for(name: str) -> str:
    if "/" in name:
        return name
    from faster_whisper.utils import _MODELS

    try:
        return _MODELS[name]
    except KeyError:
        raise ValueError(f"Unknown model {name!r}; use a Hugging Face repo id like org/name") from None


def _cache_folder(repo_id: str, root: Path) -> Path:
    return root / f"models--{repo_id.replace('/', '--')}"


def is_downloaded(name: str, root: Path | None = None) -> bool:
    root = root or models_dir()
    snapshots = _cache_folder(repo_id_for(name), root) / "snapshots"
    if not snapshots.is_dir():
        return False
    # A complete snapshot has the weights and a tokenizer; partial blobs don't count.
    return any((s / "model.bin").exists() and (s / "config.json").exists() for s in snapshots.iterdir())


def local_path(name: str, root: Path | None = None) -> str | None:
    """Path to load with faster-whisper without touching the network, if present."""
    root = root or models_dir()
    snapshots = _cache_folder(repo_id_for(name), root) / "snapshots"
    if not snapshots.is_dir():
        return None
    for s in sorted(snapshots.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if (s / "model.bin").exists() and (s / "config.json").exists():
            return str(s)
    return None


def remote_size(name: str, root: Path | None = None) -> int:
    """Total download size (bytes), via a dry run against the Hub."""
    from huggingface_hub import snapshot_download

    files = snapshot_download(
        repo_id_for(name), cache_dir=root or models_dir(), allow_patterns=ALLOW_PATTERNS, dry_run=True
    )
    return sum(f.file_size or 0 for f in files)  # type: ignore[union-attr]


def status(name: str, builtin: bool, size_cache: dict[str, int], root: Path | None = None) -> ModelStatus:
    repo = repo_id_for(name)
    return ModelStatus(name, repo, size_cache.get(repo), is_downloaded(name, root), builtin)


def download(
    name: str,
    on_progress: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
    root: Path | None = None,
) -> str:
    """Blocking; run in a worker thread. Resumable: partial files are reused."""
    from huggingface_hub import snapshot_download

    class Progress(tqdm):
        # snapshot_download builds a "Reconstructing" byte bar fed by every file;
        # that's the one that tracks bytes written to disk.
        def __init__(self, *args, **kwargs):
            kwargs["file"] = io.StringIO()
            kwargs["disable"] = False
            self._report = str(kwargs.get("desc", "")).startswith("Reconstructing")
            super().__init__(*args, **kwargs)

        def update(self, n=1):
            if cancel is not None and cancel.is_set():
                raise DownloadCancelled(name)
            result = super().update(n)
            if self._report and on_progress and self.total:
                on_progress(int(self.n), int(self.total))
            return result

    root = root or models_dir()
    root.mkdir(parents=True, exist_ok=True)
    log.info("Downloading %s to %s", name, root)
    path = snapshot_download(
        repo_id_for(name), cache_dir=root, allow_patterns=ALLOW_PATTERNS, tqdm_class=Progress
    )
    return str(path)


def delete(name: str, root: Path | None = None) -> None:
    folder = _cache_folder(repo_id_for(name), root or models_dir())
    if folder.is_dir():
        shutil.rmtree(folder)
        log.info("Deleted model %s", folder)
