"""Updates card (Advanced page): check GitHub Releases, download the installer, hand off."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from .. import __version__, updater
from ..asr.models import TransferRate
from ..config import AppConfig
from . import theme

log = logging.getLogger(__name__)


class UpdateJobs(QObject):
    """Runs the network work off the GUI thread; results come back as signals."""

    checked = Signal(object, str)  # Release | None, error ("" on success)
    progress = Signal(int, int)
    downloaded = Signal(object, str)  # Path | None, error

    def __init__(self) -> None:
        super().__init__()
        self.cancel = threading.Event()

    def check(self) -> None:
        def run() -> None:
            try:
                self.checked.emit(updater.newer_release(), "")
            except Exception as exc:  # offline is normal
                log.info("Update check failed: %s", exc)
                self.checked.emit(None, str(exc))

        threading.Thread(target=run, name="update-check", daemon=True).start()

    def download(self, release: updater.Release) -> None:
        self.cancel.clear()

        def run() -> None:
            try:
                path = updater.download_installer(release, self.progress.emit, self.cancel)
                self.downloaded.emit(path, "")
            except updater.UpdateCancelled:
                self.downloaded.emit(None, "cancelled")
            except Exception as exc:
                log.exception("Update download failed")
                self.downloaded.emit(None, str(exc))

        threading.Thread(target=run, name="update-download", daemon=True).start()


class UpdatesCard(QFrame):
    install_ready = Signal(object)  # Path to the downloaded installer; app runs it and quits
    update_found = Signal(object)  # Release

    def __init__(self, config: AppConfig, on_changed) -> None:
        super().__init__(objectName="Card")
        self.config = config
        self._on_changed = on_changed
        self._release: updater.Release | None = None
        self._downloading = False
        self._rate = TransferRate()
        self.jobs = UpdateJobs()
        self.jobs.checked.connect(self._on_checked)
        self.jobs.progress.connect(self._on_progress)
        self.jobs.downloaded.connect(self._on_downloaded)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)
        lay.addWidget(QLabel("UPDATES", objectName="SectionLabel"))

        row = QHBoxLayout()
        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(QLabel(f"Capption {__version__}"))
        self.status = QLabel("Not checked yet", objectName="Muted")
        self.status.setWordWrap(True)
        texts.addWidget(self.status)
        row.addLayout(texts, 1)
        self.button = QPushButton("Check now")
        self.button.setFixedWidth(150)
        self.button.clicked.connect(self._on_button)
        row.addWidget(self.button)
        lay.addLayout(row)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1000)
        self.progress.setVisible(False)
        lay.addWidget(self.progress)

        auto = QHBoxLayout()
        auto_text = QVBoxLayout()
        auto_text.setSpacing(2)
        auto_text.addWidget(QLabel("Check for updates on startup"))
        hint = QLabel("One request to GitHub; nothing is installed without asking", objectName="Muted")
        auto_text.addWidget(hint)
        auto.addLayout(auto_text, 1)
        self.auto_box = QCheckBox()
        self.auto_box.setChecked(config.check_updates)
        self.auto_box.toggled.connect(self._on_auto)
        auto.addWidget(self.auto_box)
        lay.addLayout(auto)

    # -- actions -----------------------------------------------------------------------
    def check(self) -> None:
        self.status.setText("Checking…")
        self.button.setEnabled(False)
        self.jobs.check()

    def _on_button(self) -> None:
        if self._downloading:
            self.jobs.cancel.set()
        elif self._release is None:
            self.check()
        elif updater.can_self_update() and self._release.installer_url:
            self._start_download()
        else:
            QDesktopServices.openUrl(QUrl(self._release.page_url))

    def _start_download(self) -> None:
        assert self._release is not None
        self._downloading = True
        self._rate = TransferRate()
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.button.setText("Cancel")
        self.status.setText("Downloading…")
        self.jobs.download(self._release)

    def _on_auto(self, on: bool) -> None:
        self.config.check_updates = on
        self._on_changed()

    # -- results -----------------------------------------------------------------------
    def _on_checked(self, release: updater.Release | None, error: str) -> None:
        self.button.setEnabled(True)
        self._release = release
        self.status.setStyleSheet("")
        if error:
            self.status.setText("Couldn't reach GitHub. Try again later.")
            self.button.setText("Check now")
        elif release is None:
            self.status.setText("You're up to date.")
            self.button.setText("Check now")
        else:
            self.status.setText(f"Version {release.tag.lstrip('v')} is available.")
            self.status.setStyleSheet(f"color: {theme.SUCCESS};")
            can = updater.can_self_update() and release.installer_url
            self.button.setText(f"Update to {release.tag}" if can else "Open download page")
            self.update_found.emit(release)

    def _on_progress(self, done: int, total: int) -> None:
        if not total:
            return
        self.progress.setValue(int(1000 * done / total))
        text = f"Downloading… {100 * done / total:.0f}%"
        rate = self._rate.add(time.monotonic(), done)
        if rate:
            text += f" · {rate / 1e6:.1f} MB/s"
        self.status.setText(text)

    def _on_downloaded(self, path: Path | None, error: str) -> None:
        self._downloading = False
        self.progress.setVisible(False)
        if path is None:
            self.status.setText("Update cancelled." if error == "cancelled" else f"Download failed: {error}")
            self.button.setText(f"Update to {self._release.tag}" if self._release else "Check now")
            return
        self.status.setText("Installing… Capption will restart.")
        self.button.setEnabled(False)
        self.install_ready.emit(path)
