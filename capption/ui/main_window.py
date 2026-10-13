"""Main window: sidebar navigation over Captions / Appearance / Models / Hotkeys / Advanced."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from PySide6.QtCore import QFileInfo, QLocale, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontInfo, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFileIconProvider,
    QFontComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..asr import models
from ..capture.base import SourceInfo
from ..config import AppConfig
from ..platform import Platform
from . import theme
from .caption_view import CaptionView
from .controller import CaptionController

log = logging.getLogger(__name__)

PREVIEW_TEXT = ("The quick brown fox jumps over the lazy dog.\nCaptions appear here in real time, ", "and partial words look like this")

# Rough sizes so the Models page is useful before the Hub has been asked.
APPROX_SIZES = {
    "large-v3-turbo": 1_620_000_000,
    "distil-large-v3": 1_510_000_000,
    "medium": 1_530_000_000,
    "small": 484_000_000,
    "tiny": 75_500_000,
}

MODEL_NOTES = {
    "large-v3-turbo": "Best accuracy/speed on GPU. Weak at translation.",
    "distil-large-v3": "English-focused, very fast.",
    "medium": "Multilingual, supports translation well.",
    "small": "Light; fine on CPU.",
    "tiny": "Fastest, lowest accuracy (dev/testing).",
}


def human_size(n: int | None, approx: bool = False) -> str:
    if not n:
        return "—"
    prefix = "~" if approx else ""
    if n >= 1e9:
        return f"{prefix}{n / 1e9:.2f} GB"
    if n >= 1e6:
        return f"{prefix}{n / 1e6:.0f} MB"
    return f"{prefix}{n / 1e3:.0f} KB"


def card(*widgets: QWidget, layout: str = "v") -> QFrame:
    frame = QFrame(objectName="Card")
    lay = QVBoxLayout(frame) if layout == "v" else QHBoxLayout(frame)
    lay.setContentsMargins(18, 16, 18, 16)
    lay.setSpacing(12)
    for w in widgets:
        lay.addWidget(w)
    return frame


def section(text: str) -> QLabel:
    return QLabel(text.upper(), objectName="SectionLabel")


def muted(text: str) -> QLabel:
    lbl = QLabel(text, objectName="Muted")
    lbl.setWordWrap(True)
    return lbl


def form_row(label: str, widget: QWidget, hint: str | None = None) -> QWidget:
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    left = QVBoxLayout()
    left.setSpacing(2)
    left.addWidget(QLabel(label))
    if hint:
        left.addWidget(muted(hint))
    lay.addLayout(left, 1)
    lay.addWidget(widget, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return row


def page(title: str, *items: QWidget) -> QScrollArea:
    inner = QWidget()
    lay = QVBoxLayout(inner)
    lay.setContentsMargins(28, 24, 28, 24)
    lay.setSpacing(16)
    lay.addWidget(QLabel(title, objectName="PageTitle"))
    for item in items:
        lay.addWidget(item)
    lay.addStretch(1)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(inner)
    return scroll


class ColorButton(QPushButton):
    changed = Signal(str)

    def __init__(self, color: str) -> None:
        super().__init__()
        self.setFixedSize(64, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_color(color)
        self.clicked.connect(self._pick)

    def set_color(self, color: str) -> None:
        self._color = color
        self.setStyleSheet(
            f"background: {color}; border: 2px solid {theme.BORDER}; border-radius: 8px;"
        )

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(self._color), self, "Choose colour")
        if c.isValid():
            self.set_color(c.name())
            self.changed.emit(c.name())


class ModelRow(QFrame):
    download_clicked = Signal(str)
    delete_clicked = Signal(str)
    cancel_clicked = Signal(str)

    def __init__(self, name: str, builtin: bool) -> None:
        super().__init__()
        self.name = name
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 8, 0, 8)
        grid.setHorizontalSpacing(12)
        title = QLabel(name)
        title.setStyleSheet("font-weight: 600;")
        self.detail = muted(MODEL_NOTES.get(name, "Custom Hugging Face model" if not builtin else ""))
        self.size = muted("—")
        self.state = QLabel()
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        self.action = QPushButton()
        self.action.setFixedWidth(110)
        self.delete = QPushButton("Delete", objectName="Danger")
        self.delete.setFixedWidth(110)
        # Only one of the two buttons is visible at a time; they share a column so every
        # row's button lines up.
        self.action.clicked.connect(self._on_action)
        self.delete.clicked.connect(lambda: self.delete_clicked.emit(self.name))
        grid.addWidget(title, 0, 0)
        grid.addWidget(self.detail, 1, 0)
        grid.addWidget(self.size, 0, 1, Qt.AlignmentFlag.AlignRight)
        grid.addWidget(self.state, 1, 1, Qt.AlignmentFlag.AlignRight)
        grid.addWidget(self.action, 0, 2, 2, 1)
        grid.addWidget(self.delete, 0, 2, 2, 1)
        grid.addWidget(self.progress, 2, 0, 1, 3)
        grid.setColumnMinimumWidth(2, 110)
        grid.setColumnStretch(0, 1)
        self._downloading = False

    def set_status(self, downloaded: bool, size: int | None, approx: bool) -> None:
        self.size.setText(human_size(size, approx))
        self._downloading = False
        self.progress.setVisible(False)
        self.state.setText("Downloaded" if downloaded else "Not downloaded")
        self.state.setStyleSheet(f"color: {theme.SUCCESS if downloaded else theme.MUTED};")
        self.action.setText("Re-check" if downloaded else "Download")
        self.action.setEnabled(not downloaded)
        self.action.setVisible(not downloaded)
        self.delete.setVisible(downloaded)

    def set_progress(self, done: int, total: int) -> None:
        self._downloading = True
        self.progress.setVisible(True)
        self.progress.setRange(0, 1000)
        self.progress.setValue(int(1000 * done / total) if total else 0)
        self.state.setText(f"{human_size(done)} / {human_size(total)}")
        self.state.setStyleSheet(f"color: {theme.TEXT};")
        self.action.setText("Cancel")
        self.action.setEnabled(True)
        self.action.setVisible(True)
        self.delete.setVisible(False)

    def _on_action(self) -> None:
        (self.cancel_clicked if self._downloading else self.download_clicked).emit(self.name)


class ModelJobs(QObject):
    """Runs downloads and Hub size lookups off the GUI thread."""

    progress = Signal(str, int, int)
    finished = Signal(str, str)  # name, error ("" on success)
    size_known = Signal(str, int)

    def __init__(self) -> None:
        super().__init__()
        self._cancels: dict[str, threading.Event] = {}

    def downloading(self, name: str) -> bool:
        return name in self._cancels

    def download(self, name: str) -> None:
        if name in self._cancels:
            return
        cancel = threading.Event()
        self._cancels[name] = cancel
        self.progress.emit(name, 0, 0)

        def run() -> None:
            error = ""
            try:
                models.download(name, lambda d, t: self.progress.emit(name, d, t), cancel)
            except models.DownloadCancelled:
                error = "cancelled"
            except Exception as exc:
                log.exception("Download of %s failed", name)
                error = str(exc)
            self._cancels.pop(name, None)
            self.finished.emit(name, error)

        threading.Thread(target=run, name=f"download-{name}", daemon=True).start()

    def cancel(self, name: str) -> None:
        if ev := self._cancels.get(name):
            ev.set()

    def fetch_sizes(self, names: list[str]) -> None:
        def run() -> None:
            for name in names:
                try:
                    self.size_known.emit(name, models.remote_size(name))
                except Exception as exc:  # offline is normal; keep approximate sizes
                    log.info("Size lookup for %s failed: %s", name, exc)
                    return

        threading.Thread(target=run, name="model-sizes", daemon=True).start()


class MainWindow(QMainWindow):
    config_changed = Signal()  # anything changed; app saves (debounced)
    style_changed = Signal()  # overlay styling changed
    hotkeys_changed = Signal()
    toggle_overlay_requested = Signal()

    def __init__(self, config: AppConfig, platform: Platform, controller: CaptionController) -> None:
        super().__init__()
        self.config = config
        self.platform = platform
        self.controller = controller
        self._sources: list[SourceInfo] = []
        self._sizes: dict[str, int] = {}
        self._jobs = ModelJobs()
        self._icons = QFileIconProvider()
        self.setWindowTitle("Capption")
        self.resize(940, 680)
        self.setMinimumSize(760, 560)

        root = QWidget(objectName="Root")
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setCentralWidget(root)

        sidebar = QWidget(objectName="Sidebar")
        sidebar.setFixedWidth(200)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 18, 12, 12)
        side.setSpacing(4)
        side.addWidget(QLabel("Capption", objectName="AppTitle"))
        self.stack = QStackedWidget()
        self._nav = QButtonGroup(self)
        for i, (name, widget) in enumerate([
            ("Captions", self._captions_page()),
            ("Appearance", self._appearance_page()),
            ("Models", self._models_page()),
            ("Hotkeys", self._hotkeys_page()),
            ("Advanced", self._advanced_page()),
        ]):
            btn = QPushButton(name, objectName="NavButton", checkable=True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._nav.addButton(btn, i)
            side.addWidget(btn)
            self.stack.addWidget(widget)
        self._nav.idClicked.connect(self.stack.setCurrentIndex)
        self._nav.button(0).setChecked(True)
        side.addStretch(1)
        self.engine_label = muted("Model not loaded")
        side.addWidget(self.engine_label)
        outer.addWidget(sidebar)
        outer.addWidget(self.stack, 1)

        controller.state_changed.connect(self._on_state)
        controller.status.connect(self._on_status)
        controller.metrics.connect(self._on_metrics)
        controller.engine_changed.connect(self._on_engine)
        controller.model_missing.connect(lambda _n: self.show_page(2))
        self._jobs.progress.connect(self._on_download_progress)
        self._jobs.finished.connect(self._on_download_finished)
        self._jobs.size_known.connect(self._on_size)
        self.refresh_sources()
        self._refresh_models()
        self._jobs.fetch_sizes(self._model_names())
        self._on_state(controller.state)

    def show_page(self, index: int) -> None:
        self._nav.button(index).setChecked(True)
        self.stack.setCurrentIndex(index)

    def _changed(self) -> None:
        self.config_changed.emit()

    # ---------------------------------------------------------------- Captions page
    def _captions_page(self) -> QWidget:
        support = self.platform.capture_support()
        self.banner = QFrame(objectName="Banner")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(14, 10, 14, 10)
        banner_text = QLabel(support.message)
        banner_text.setWordWrap(True)
        bl.addWidget(banner_text)
        self.banner.setVisible(bool(support.message))

        self.source_combo = QComboBox()
        self.source_combo.setMinimumWidth(320)
        self.source_combo.setIconSize(self.source_combo.iconSize() * 1.2)
        refresh = QToolButton()
        refresh.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        refresh.setToolTip("Refresh the list of apps playing audio")
        refresh.clicked.connect(self.refresh_sources)
        src_row = QWidget()
        sl = QHBoxLayout(src_row)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(self.source_combo, 1)
        sl.addWidget(refresh)

        self.model_combo = QComboBox()
        self.model_combo.currentTextChanged.connect(self._on_model_chosen)
        self.language_combo = QComboBox()
        self.language_combo.addItem("Auto-detect", None)
        from faster_whisper.tokenizer import _LANGUAGE_CODES

        langs = sorted(
            ((QLocale.languageToString(QLocale(code).language()), code) for code in _LANGUAGE_CODES),
            key=lambda x: x[0],
        )
        for name, code in langs:
            if name and name != "C":
                self.language_combo.addItem(f"{name} ({code})", code)
        idx = self.language_combo.findData(self.config.asr.language)
        self.language_combo.setCurrentIndex(max(0, idx))
        self.language_combo.currentIndexChanged.connect(self._on_language)
        self.translate_box = QCheckBox("Translate to English")
        self.translate_box.setChecked(self.config.asr.translate)
        self.translate_box.toggled.connect(self._on_translate)

        self.start_btn = QPushButton("Start captions", objectName="Primary")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.clicked.connect(self._toggle_running)
        self.overlay_btn = QPushButton("Show / hide overlay")
        self.overlay_btn.clicked.connect(self.toggle_overlay_requested.emit)
        self.status_label = QLabel("Idle")
        self.status_label.setWordWrap(True)
        actions = QWidget()
        al = QHBoxLayout(actions)
        al.setContentsMargins(0, 0, 0, 0)
        al.addWidget(self.start_btn)
        al.addWidget(self.overlay_btn)
        al.addStretch(1)

        self.debug_label = muted("")
        self.debug_label.setFont(QFont("Menlo, Consolas, monospace", 11))
        self.debug_card = card(section("Debug"), self.debug_label)
        self.debug_card.setVisible(self.config.debug_panel)

        return page(
            "Captions",
            self.banner,
            card(section("Source"), form_row("Application", src_row, "Apps currently producing audio")),
            card(
                section("Recognition"),
                form_row("Model", self.model_combo),
                form_row("Language", self.language_combo),
                form_row("Translate", self.translate_box, "Outputs English whatever the spoken language"),
            ),
            card(actions, self.status_label),
            self.debug_card,
        )

    def refresh_sources(self) -> None:
        self._sources = self.platform.list_sources(self.config)
        current = self.source_combo.currentData()
        wanted = current or self.config.capture.last_exe
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        for info in self._sources:
            self.source_combo.addItem(self._source_icon(info), info.label, info.key)
        if wanted and self.source_combo.findData(wanted) < 0 and wanted == self.config.capture.last_exe:
            # Remembered app isn't running: keep it selectable so Start waits for it.
            self.source_combo.addItem(self._source_icon(SourceInfo(wanted, wanted, "process")),
                                      f"{wanted} (not running)", wanted)
        idx = self.source_combo.findData(wanted) if wanted else 0
        self.source_combo.setCurrentIndex(max(0, idx))
        self.source_combo.blockSignals(False)

    def _source_icon(self, info: SourceInfo) -> QIcon:
        if info.exe_path:
            return self._icons.icon(QFileInfo(info.exe_path))
        pix = {
            "device": QStyle.StandardPixmap.SP_MediaVolume,
            "file": QStyle.StandardPixmap.SP_FileIcon,
        }.get(info.kind, QStyle.StandardPixmap.SP_DesktopIcon)
        return self.style().standardIcon(pix)

    def selected_source(self) -> SourceInfo | None:
        key = self.source_combo.currentData()
        if key is None:
            return None
        found = next((s for s in self._sources if s.key == key), None)
        return found or SourceInfo(key, key, "process")

    def select_source(self, key: str) -> None:
        idx = self.source_combo.findData(key)
        if idx >= 0:
            self.source_combo.setCurrentIndex(idx)

    def _toggle_running(self) -> None:
        if self.controller.state == "idle":
            source = self.selected_source()
            if source is None:
                self._on_status("error", "Pick an application first.")
                return
            self.controller.start(source)
        else:
            self.controller.stop()
        self._changed()

    def _restart_if_running(self) -> None:
        if self.controller.state != "idle" and self.controller.source_info is not None:
            self.controller.start(self.controller.source_info)

    def _on_model_chosen(self, name: str) -> None:
        if name and name != self.config.asr.model:
            self.config.asr.model = name
            self._changed()
            self._restart_if_running()

    def _on_language(self) -> None:
        self.config.asr.language = self.language_combo.currentData()
        self._changed()
        self._restart_if_running()

    def _on_translate(self, on: bool) -> None:
        self.config.asr.translate = on
        self._changed()
        self._restart_if_running()

    def _on_state(self, state: str) -> None:
        running = state != "idle"
        self.start_btn.setText({"idle": "Start captions", "loading": "Loading…"}.get(state, "Stop captions"))
        self.start_btn.setProperty("running", running)
        self.start_btn.style().unpolish(self.start_btn)
        self.start_btn.style().polish(self.start_btn)
        self.source_combo.setEnabled(not running)

    def _on_status(self, level: str, message: str) -> None:
        color = {"error": theme.DANGER, "warning": theme.WARNING}.get(level, theme.MUTED)
        self.status_label.setStyleSheet(f"color: {color};")
        self.status_label.setText(message)

    def _on_metrics(self, m) -> None:
        if self.debug_card.isVisible():
            self.debug_label.setText(self.controller.describe_metrics(m))

    def _on_engine(self, info) -> None:
        # info.model may be a local snapshot path; show the configured name instead.
        self.engine_label.setText(f"{self.config.asr.model.split('/')[-1][:28]}\n{info.device} · {info.compute_type}")

    # ---------------------------------------------------------------- Appearance page
    def _appearance_page(self) -> QWidget:
        o = self.config.overlay
        self.preview = CaptionView(o)
        self.preview.set_text(*PREVIEW_TEXT)
        self.preview.setMinimumWidth(300)
        preview_host = QFrame()
        preview_host.setStyleSheet(
            "QFrame { border-radius: 12px; background: qlineargradient(x1:0, y1:0, x2:1, y2:1,"
            " stop:0 #3A4A6B, stop:0.5 #6B4A5E, stop:1 #2E5D57); }"
        )
        ph = QVBoxLayout(preview_host)
        ph.setContentsMargins(24, 36, 24, 36)
        ph.addWidget(self.preview)

        font = QFontComboBox()
        # Show the family Qt actually resolves to (e.g. Segoe UI doesn't exist on macOS).
        font.setCurrentFont(QFont(QFontInfo(QFont(o.font_family)).family()))
        font.currentFontChanged.connect(lambda f: self._style("font_family", f.family()))
        size = self._spin(10, 96, o.font_size, lambda v: self._style("font_size", v), " px")
        lines = self._spin(1, 6, o.max_lines, lambda v: self._style("max_lines", v))
        width = self._spin(240, 3000, o.width, lambda v: self._style("width", v), " px")
        self.width_spin = width
        fade = self._spin(0, 60, int(o.fade_after_s), lambda v: self._style("fade_after_s", float(v)), " s")
        text_c = ColorButton(o.text_color)
        text_c.changed.connect(lambda c: self._style("text_color", c))
        partial_c = ColorButton(o.partial_color)
        partial_c.changed.connect(lambda c: self._style("partial_color", c))
        bg_c = ColorButton(o.background_color)
        bg_c.changed.connect(lambda c: self._style("background_color", c))
        opacity = QSlider(Qt.Orientation.Horizontal)
        opacity.setRange(0, 100)
        opacity.setValue(int(o.background_opacity * 100))
        opacity.setFixedWidth(200)
        opacity.valueChanged.connect(lambda v: self._style("background_opacity", v / 100))

        return page(
            "Appearance",
            card(section("Live preview"), preview_host),
            card(
                section("Text"),
                form_row("Font", font),
                form_row("Size", size),
                form_row("Confirmed text colour", text_c),
                form_row("Partial text colour", partial_c, "Words that may still change"),
            ),
            card(
                section("Box"),
                form_row("Background colour", bg_c),
                form_row("Background opacity", opacity),
                form_row("Lines shown", lines),
                form_row("Width", width, "You can also drag the overlay's left/right edges"),
                form_row("Fade after silence", fade, "0 keeps the last captions visible"),
            ),
        )

    def _spin(self, lo: int, hi: int, value: int, on_change: Callable[[int], None], suffix: str = "") -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(lo, hi)
        spin.setValue(value)
        spin.setSuffix(suffix)
        spin.setFixedWidth(110)
        spin.valueChanged.connect(on_change)
        return spin

    def _style(self, attr: str, value) -> None:
        setattr(self.config.overlay, attr, value)
        self.preview.apply_style(self.config.overlay)
        self.style_changed.emit()
        self._changed()

    def sync_overlay_width(self) -> None:
        """The overlay was resized by dragging; reflect it without re-emitting."""
        self.width_spin.blockSignals(True)
        self.width_spin.setValue(self.config.overlay.width)
        self.width_spin.blockSignals(False)

    # ---------------------------------------------------------------- Models page
    def _model_names(self) -> list[str]:
        return models.BUILTIN_MODELS + [m for m in self.config.custom_models if m not in models.BUILTIN_MODELS]

    def _models_page(self) -> QWidget:
        self.model_rows: dict[str, ModelRow] = {}
        self.models_box = QVBoxLayout()
        self.models_box.setSpacing(0)
        holder = QWidget()
        holder.setLayout(self.models_box)
        self.custom_edit = QLineEdit()
        self.custom_edit.setPlaceholderText("org/model-name (CTranslate2 Whisper)")
        add = QPushButton("Add model")
        add.clicked.connect(self._add_custom_model)
        self.custom_edit.returnPressed.connect(self._add_custom_model)
        custom_row = QWidget()
        cl = QHBoxLayout(custom_row)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.custom_edit, 1)
        cl.addWidget(add)
        self.models_error = QLabel()
        self.models_error.setStyleSheet(f"color: {theme.DANGER};")
        self.models_error.setWordWrap(True)
        return page(
            "Models",
            card(section("Speech models"), muted(f"Stored in {models.models_dir()}"), holder),
            card(section("Custom Hugging Face model"), custom_row,
                 muted("Must be a faster-whisper / CTranslate2 conversion."), self.models_error),
        )

    def _refresh_models(self) -> None:
        names = self._model_names()
        for name in names:
            if name not in self.model_rows:
                row = ModelRow(name, name in models.BUILTIN_MODELS)
                row.download_clicked.connect(self._jobs.download)
                row.cancel_clicked.connect(self._jobs.cancel)
                row.delete_clicked.connect(self._delete_model)
                self.model_rows[name] = row
                self.models_box.addWidget(row)
        for name, row in self.model_rows.items():
            if self._jobs.downloading(name):
                continue
            exact = self._sizes.get(name)
            row.set_status(models.is_downloaded(name), exact or APPROX_SIZES.get(name), approx=exact is None)
        # Model picker: every known model; downloaded ones marked.
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for name in names:
            self.model_combo.addItem(name)
            if not models.is_downloaded(name):
                self.model_combo.setItemData(self.model_combo.count() - 1, QColor(theme.MUTED), Qt.ItemDataRole.ForegroundRole)
        self.model_combo.setCurrentText(self.config.asr.model)
        self.model_combo.blockSignals(False)

    def _on_download_progress(self, name: str, done: int, total: int) -> None:
        if row := self.model_rows.get(name):
            row.set_progress(done, total)

    def _on_download_finished(self, name: str, error: str) -> None:
        if error and error != "cancelled":
            self.models_error.setText(f"{name}: {error}")
        else:
            self.models_error.setText("")
        self._refresh_models()

    def _on_size(self, name: str, size: int) -> None:
        self._sizes[name] = size
        if (row := self.model_rows.get(name)) and not self._jobs.downloading(name):
            row.set_status(models.is_downloaded(name), size, approx=False)

    def _delete_model(self, name: str) -> None:
        if self.controller.state != "idle" and self.config.asr.model == name:
            self.models_error.setText("Stop captions before deleting the model in use.")
            return
        try:
            models.delete(name)
        except OSError as exc:
            self.models_error.setText(f"Couldn't delete {name}: {exc}")
        self._refresh_models()

    def _add_custom_model(self) -> None:
        repo = self.custom_edit.text().strip()
        if repo.count("/") != 1 or " " in repo:
            self.models_error.setText("Enter a Hugging Face repo id like org/name.")
            return
        if repo not in self.config.custom_models:
            self.config.custom_models.append(repo)
            self._changed()
        self.custom_edit.clear()
        self.models_error.setText("")
        self._refresh_models()
        self._jobs.fetch_sizes([repo])

    # ---------------------------------------------------------------- Hotkeys page
    def _hotkeys_page(self) -> QWidget:
        hk = self.config.hotkeys
        rows = []
        for attr, label, hint in [
            ("toggle_captions", "Start / stop captions", None),
            ("toggle_click_through", "Toggle click-through", "Lets clicks pass through the overlay"),
            ("hide_overlay", "Show / hide overlay", None),
        ]:
            edit = QKeySequenceEdit(QKeySequence(getattr(hk, attr)))
            edit.setMaximumSequenceLength(1)
            edit.setFixedWidth(180)
            edit.editingFinished.connect(lambda a=attr, e=edit: self._set_hotkey(a, e))
            rows.append(form_row(label, edit, hint))
        self.hotkey_status = muted("")
        return page("Hotkeys", card(section("Global hotkeys"), *rows, self.hotkey_status))

    def _set_hotkey(self, attr: str, edit: QKeySequenceEdit) -> None:
        setattr(self.config.hotkeys, attr, edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText))
        self.hotkeys_changed.emit()
        self._changed()

    def set_hotkey_status(self, failed: list[str]) -> None:
        self.hotkey_status.setText(
            "Couldn't register: " + ", ".join(failed) + " (in use by another app?)" if failed else ""
        )
        self.hotkey_status.setStyleSheet(f"color: {theme.WARNING if failed else theme.MUTED};")

    # ---------------------------------------------------------------- Advanced page
    def _advanced_page(self) -> QWidget:
        t = self.config.transcript
        save = QCheckBox()
        save.setChecked(t.enabled)
        save.toggled.connect(lambda v: self._set(t, "enabled", v))
        txt = QCheckBox(".txt")
        txt.setChecked(t.txt)
        txt.toggled.connect(lambda v: self._set(t, "txt", v))
        srt = QCheckBox(".srt")
        srt.setChecked(t.srt)
        srt.toggled.connect(lambda v: self._set(t, "srt", v))
        fmt = QWidget()
        fl = QHBoxLayout(fmt)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.addWidget(txt)
        fl.addWidget(srt)

        device = QComboBox()
        for label, value in [("Auto (GPU if available)", "auto"), ("GPU (CUDA)", "cuda"), ("CPU", "cpu")]:
            device.addItem(label, value)
        device.setCurrentIndex(max(0, device.findData(self.config.asr.device)))
        device.currentIndexChanged.connect(lambda: self._set_asr("device", device.currentData()))

        debug = QCheckBox()
        debug.setChecked(self.config.debug_panel)
        debug.toggled.connect(self._toggle_debug)

        items: list[QWidget] = [
            card(section("Transcripts"),
                 form_row("Save transcript per session", save, "Timestamped files in the data folder"),
                 form_row("Formats", fmt)),
            card(section("Performance"),
                 form_row("Compute device", device, "Falls back to CPU automatically if CUDA fails"),
                 form_row("Debug panel", debug, "Queue depth, inference time and realtime factor")),
        ]
        if not self.platform.capture_support().process_loopback:
            self.dev_file_label = muted(self.config.capture.dev_file or "Built-in sample")
            choose = QPushButton("Choose file…")
            choose.clicked.connect(self._choose_dev_file)
            items.append(card(section("Development"),
                              form_row("Demo app audio", choose, "Audio/video file the demo apps play"),
                              self.dev_file_label))
        return page("Advanced", *items)

    def _set(self, obj, attr: str, value) -> None:
        setattr(obj, attr, value)
        self._changed()

    def _set_asr(self, attr: str, value) -> None:
        setattr(self.config.asr, attr, value)
        self._changed()
        self._restart_if_running()

    def _toggle_debug(self, on: bool) -> None:
        self.config.debug_panel = on
        self.debug_card.setVisible(on)
        self._changed()

    def _choose_dev_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Demo audio", "", "Media (*.wav *.mp3 *.m4a *.flac *.ogg *.mp4 *.mkv *.webm *.mov);;All files (*)"
        )
        if path:
            self.config.capture.dev_file = path
            self.dev_file_label.setText(path)
            self._changed()

    def closeEvent(self, event) -> None:
        # Closing the window keeps the app in the tray.
        event.ignore()
        self.hide()


def debounce(parent: QObject, ms: int, fn: Callable[[], None]) -> Callable[[], None]:
    timer = QTimer(parent, singleShot=True, interval=ms)
    timer.timeout.connect(fn)
    return timer.start
