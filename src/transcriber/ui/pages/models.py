"""Live Hugging Face model discovery and locally installed model management."""

from __future__ import annotations

import threading
import uuid
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from transcriber.models.hub_client import CURATED_MODELS
from transcriber.ui.widgets import Card, page_header, primary_button
from transcriber.ui.workers import FunctionWorker


def _human_size(value: int | None) -> str:
    if value is None:
        return "Unknown"
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return "Unknown"


def _installed_runtime_key(model: dict | str) -> str:
    """Normalize current and older registry metadata into the two UI runtime filters."""
    if isinstance(model, dict):
        metadata = model.get("metadata") if isinstance(model.get("metadata"), dict) else {}
        raw = (
            model.get("runtime") or model.get("engine") or metadata.get("runtime")
            or model.get("model_type") or ""
        )
        identity = " ".join((
            str(raw), str(model.get("repo_id") or ""),
            str(model.get("model_name") or ""),
        )).casefold()
    else:
        identity = str(model or "").casefold()

    if "vosk" in identity or "kaldi" in identity:
        return "vosk"
    if "whisper" in identity or "ctranslate" in identity:
        return "faster-whisper"
    return "faster-whisper"


class ModelCard(Card):
    inspect_requested = Signal(str)
    install_requested = Signal(str)
    open_requested = Signal(str)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.report = None
        self.installed_info = None
        self.inspection_detail = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 15, 18, 15)
        layout.setSpacing(8)
        top = QHBoxLayout()
        heading_text = (
            f"{model.source_repo}/{model.source_file}"
            if getattr(model, "source", "") == "huggingface"
            else model.repo_id
        )
        heading = QLabel(heading_text)
        heading.setObjectName("ModelDetailHeading")
        top.addWidget(heading, 1)
        self.compatibility = QLabel("Compatibility not inspected")
        self.compatibility.setObjectName("ModelCompatibility")
        self._set_compatibility_state("neutral")
        top.addWidget(self.compatibility)
        layout.addLayout(top)
        description = QLabel(model.description or "Description: Not provided by the repository card.")
        description.setObjectName("Muted")
        description.setWordWrap(True)
        layout.addWidget(description)
        metadata = QLabel(
            f"Owner: {model.author or 'Unknown'}    ·    Task: {model.task or 'Unknown'}    ·    "
            f"License: {model.license or 'Not provided'}    ·    "
            f"Languages: {', '.join(model.languages) if model.languages else 'Not provided'}\n"
            f"Downloads: {model.downloads if model.downloads is not None else 'Unknown'}    ·    "
            f"Likes: {model.likes if model.likes is not None else 'Unknown'}    ·    "
            f"Updated: {model.last_modified or 'Unknown'}"
        )
        metadata.setObjectName("Muted")
        metadata.setWordWrap(True)
        layout.addWidget(metadata)
        self.detail_label = QLabel("File list and exact sizes are available after inspection.")
        self.detail_label.setObjectName("Muted")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)
        actions = QHBoxLayout()
        self.inspect_button = QPushButton("Inspect compatibility")
        self.inspect_button.clicked.connect(lambda: self.inspect_requested.emit(model.repo_id))
        self.install_button = primary_button("Install model")
        self.install_button.setEnabled(False)
        self.install_button.clicked.connect(lambda: self.install_requested.emit(model.repo_id))
        is_vosk = str(getattr(model, "runtime", "faster-whisper")) == "vosk"
        open_label = (
            "Open Hugging Face file ↗"
            if getattr(model, "source", "") == "huggingface"
            else "Official Vosk model list ↗"
            if is_vosk else "Open on Hugging Face ↗"
        )
        open_button = QPushButton(open_label)
        open_button.clicked.connect(lambda: self.open_requested.emit(model.url))
        actions.addWidget(self.inspect_button)
        actions.addWidget(self.install_button)
        actions.addStretch(1)
        actions.addWidget(open_button)
        layout.addLayout(actions)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        self.progress_text = QLabel("")
        self.progress_text.setObjectName("Muted")
        layout.addWidget(self.progress)
        layout.addWidget(self.progress_text)

    def _set_compatibility_state(self, state: str):
        """Apply a semantic compatibility state through the shared theme."""
        self.compatibility.setProperty("state", state)
        style = self.compatibility.style()
        style.unpolish(self.compatibility)
        style.polish(self.compatibility)
        self.compatibility.update()

    def set_inspection(self, metadata, report):
        self.model = metadata
        self.report = report
        runtime = str(getattr(metadata, "runtime", "faster-whisper"))
        runtime_name = "Vosk" if runtime == "vosk" else "Faster-Whisper"
        if report.compatible:
            self.compatibility.setText(f"Compatible · {runtime_name}")
            self._set_compatibility_state("compatible")
        else:
            self.compatibility.setText(f"Not compatible · {runtime_name}")
            self._set_compatibility_state("incompatible")
        missing = (" Missing: " + ", ".join(report.missing_files)) if report.missing_files else ""
        if runtime == "vosk":
            self.inspection_detail = (
                "Runtime: Vosk / Kaldi\n"
                f"Language: {getattr(metadata, 'language_name', 'Unknown')} "
                f"({getattr(metadata, 'language', 'unknown')})\n"
                f"Model type: {getattr(metadata, 'model_type', 'unknown')}\n"
                f"Archive size: {getattr(metadata, 'size_text', '') or _human_size(getattr(metadata, 'size_bytes', None))}\n"
                f"Checksum ({getattr(metadata, 'checksum_algorithm', 'md5').upper()}): "
                f"{getattr(metadata, 'checksum', 'unknown')}\n"
                f"Source: {getattr(metadata, 'source_label', 'Official Vosk catalogue')}\n"
                f"{report.reason}{missing}\n"
                "Inspected against the Vosk API directory structure, not CTranslate2."
            )
        else:
            sizes = {item.name: item.size for item in metadata.files}
            files = []
            total = 0
            known = True
            for name in report.included_files:
                size = sizes.get(name)
                files.append(f"{name} ({_human_size(size)})")
                if size is None:
                    known = False
                else:
                    total += size
            size_text = _human_size(total) if known else "Unknown (one or more file sizes not supplied)"
            self.inspection_detail = (
                f"Estimated download: {size_text}\nFiles: "
                + (", ".join(files) or "Not provided")
                + f"\n{report.reason}{missing}\nPinned revision: {metadata.revision or 'Unknown'}"
            )
        self.detail_label.setText(self.inspection_detail)
        self.set_installed(self.installed_info)

    def set_installed(self, installed_info):
        """Keep Hub inspection and local installation state visible together."""
        self.installed_info = installed_info
        if installed_info:
            compatible = bool(installed_info.get("compatible"))
            runtime = str(installed_info.get("runtime") or "faster-whisper")
            runtime_name = "Vosk" if runtime == "vosk" else "Faster-Whisper"
            self.compatibility.setText(
                f"{runtime_name} · Installed" if compatible
                else f"{runtime_name} · Repair needed"
            )
            self._set_compatibility_state("compatible" if compatible else "warning")
            self.install_button.setText("Installed" if compatible else "Installed · Repair")
            self.install_button.setEnabled(False)
            path = installed_info.get("path")
            revision = installed_info.get("revision")
            self.detail_label.setText(
                f"Local {runtime_name} installation · revision {revision or 'unknown'}"
                + (f"\n{path}" if path else "")
            )
        else:
            if self.report:
                compatible = bool(self.report.compatible)
                runtime = str(getattr(self.model, "runtime", "faster-whisper"))
                runtime_name = "Vosk" if runtime == "vosk" else "Faster-Whisper"
                self.compatibility.setText(
                    f"Compatible · {runtime_name}" if compatible
                    else f"Not compatible · {runtime_name}"
                )
                self._set_compatibility_state("compatible" if compatible else "incompatible")
                if self.inspection_detail:
                    self.detail_label.setText(self.inspection_detail)
            else:
                self.compatibility.setText("Compatibility not inspected")
                self._set_compatibility_state("neutral")
            self.install_button.setText("Install model")
            self.install_button.setEnabled(bool(self.report and self.report.compatible))

    def set_download_progress(self, progress):
        self.progress.setVisible(True)
        percent = progress.percent
        if percent is not None:
            self.progress.setValue(int(percent))
        else:
            self.progress.setRange(0, 0)
        speed = f" · {_human_size(int(progress.speed_bytes_per_second))}/s" if progress.speed_bytes_per_second else ""
        downloaded = _human_size(progress.downloaded_bytes)
        total = _human_size(progress.total_bytes)
        eta = f" · ETA {int(progress.eta_seconds)}s" if progress.eta_seconds is not None else ""
        self.progress_text.setText(f"{progress.state}: {downloaded} / {total}{speed}{eta} · {progress.message}")
        if progress.state in {"Installed", "Failed", "Cancelled", "Paused", "Stopped"}:
            self.progress.setRange(0, 100)
            self.progress.setVisible(progress.state != "Installed")
            if progress.state == "Installed":
                self.install_button.setText("Installed")
                self.install_button.setEnabled(False)
            else:
                # Keep the cancel-action wiring intact until the worker's
                # finished signal restores the normal Install button.
                self.install_button.setEnabled(False)


class ModelLibraryPage(QWidget):
    status_message = Signal(str)
    default_model_changed = Signal(str)
    installed_models_changed = Signal()
    vosk_model_selected = Signal(str)

    def __init__(self, model_manager, settings_store, thread_pool, release_active_model, parent=None):
        super().__init__(parent)
        self.model_manager = model_manager
        self.settings_store = settings_store
        self.thread_pool = thread_pool
        self.release_active_model = release_active_model
        self.cards: dict[str, ModelCard] = {}
        self._installed_by_id: dict[str, dict] = {}
        self._installed_card_rows: list[tuple[QWidget, str, str, str]] = []
        self._download_card_rows: list[tuple[QWidget, str, str, str]] = []
        self._download_jobs: list[dict] = []
        self._downloads: dict[str, threading.Event] = {}
        self._download_task_ids: dict[str, str] = {}
        self._download_workers: dict[str, FunctionWorker] = {}
        self._downloads_refresh_pending = False
        self._downloads_refresh_again = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 10, 12)
        layout.setSpacing(14)
        layout.addWidget(page_header(
            "Model library",
            "Discover models from Hugging Face or the official Vosk catalogue. "
            "Each model is inspected against the format required by its own runtime.",
        ))
        self.tabs = QTabWidget()
        discover = QWidget()
        discover_layout = QVBoxLayout(discover)
        search_panel = Card()
        search_panel.setObjectName("ModelDiscoveryToolbar")
        search_layout = QVBoxLayout(search_panel)
        search_layout.setContentsMargins(12, 11, 12, 11)
        search_layout.setSpacing(9)

        self.provider_combo = QComboBox()
        self.provider_combo.addItem("Faster-Whisper · Hugging Face", "faster-whisper")
        self.provider_combo.addItem("Vosk · Official + Hugging Face", "vosk")
        self.provider_combo.currentIndexChanged.connect(self._provider_changed)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search model name or publisher…")
        self.search_input.returnPressed.connect(self.search_models)
        search_button = primary_button("Search models")
        search_button.clicked.connect(self.search_models)
        self.search_button = search_button
        self.curated_button = QPushButton("Curated models")
        self.curated_button.clicked.connect(self.load_curated)

        search_row = QHBoxLayout()
        search_row.addWidget(self.provider_combo)
        search_row.addWidget(self.search_input, 1)
        search_row.addWidget(search_button)
        search_row.addWidget(self.curated_button)
        search_layout.addLayout(search_row)

        self.language_filter = QComboBox()
        self.language_filter.addItem("All languages", "")
        self.language_filter.addItem("Persian / Farsi", "fa")
        self.language_filter.addItem("English", "en")
        self.language_filter.addItem("German", "de")
        self.language_filter.addItem("French", "fr")
        self.language_filter.addItem("Spanish", "es")
        self.language_filter.addItem("Arabic", "ar")
        self.language_filter.addItem("Russian", "ru")
        self.language_filter.addItem("Chinese", "cn")
        self.language_filter.addItem("Hindi", "hi")
        self.language_filter.addItem("Italian", "it")
        self.language_filter.addItem("Turkish", "tr")
        self.source_filter = QComboBox()
        self.source_filter.addItem("All Vosk sources", "")
        self.source_filter.addItem("Official Vosk catalogue", "official")
        self.source_filter.addItem("Hugging Face mirrors", "huggingface")
        self.language_filter.setVisible(False)
        self.source_filter.setVisible(False)
        self.sort_combo = QComboBox()
        self.sort_combo.addItem("Most downloaded", "downloads")
        self.sort_combo.addItem("Most liked", "likes")
        self.sort_combo.addItem("Recently updated", "lastModified")
        filters_row = QHBoxLayout()
        filters_row.addWidget(QLabel("Filters"))
        filters_row.addWidget(self.language_filter)
        filters_row.addWidget(self.source_filter)
        filters_row.addWidget(self.sort_combo)
        filters_row.addStretch(1)
        search_layout.addLayout(filters_row)
        discover_layout.addWidget(search_panel)
        self.discover_hint = QLabel("Search uses the official Hugging Face Hub API. Curated entries are fetched live; unavailable metadata is not fabricated.")
        self.discover_hint.setObjectName("Muted")
        self.discover_hint.setWordWrap(True)
        discover_layout.addWidget(self.discover_hint)
        self.discover_scroll = QScrollArea()
        self.discover_scroll.setWidgetResizable(True)
        self.discover_container = QWidget()
        self.discover_cards = QVBoxLayout(self.discover_container)
        self.discover_cards.setContentsMargins(0, 4, 8, 4)
        self.discover_cards.setSpacing(10)
        self.discover_cards.addStretch(1)
        self.discover_scroll.setWidget(self.discover_container)
        discover_layout.addWidget(self.discover_scroll, 1)
        self.tabs.addTab(discover, "Discover")

        downloads = QWidget()
        downloads_layout = QVBoxLayout(downloads)
        downloads_layout.setContentsMargins(10, 10, 10, 10)
        self.downloads_hint = QLabel(
            "Download tasks are stored locally. Paused and stopped tasks can be resumed at the same pinned revision. "
            "The shared Hugging Face cache is retained when a task pauses, stops or is cancelled."
        )
        self.downloads_hint.setObjectName("Muted")
        self.downloads_hint.setWordWrap(True)
        downloads_layout.addWidget(self.downloads_hint)
        download_filters = QHBoxLayout()
        self.download_search = QLineEdit()
        self.download_search.setPlaceholderText("Search downloads by model or source…")
        self.download_search.textChanged.connect(self._filter_download_cards)
        self.download_state_filter = QComboBox()
        self.download_state_filter.addItem("All states", "")
        for label, value in (
            ("In progress", "active"), ("Ready to resume", "recoverable"),
            ("Failed", "failed"), ("Completed", "installed"), ("Cancelled", "cancelled"),
        ):
            self.download_state_filter.addItem(label, value)
        self.download_state_filter.currentIndexChanged.connect(self._filter_download_cards)
        self.download_runtime_filter = QComboBox()
        self.download_runtime_filter.addItem("All runtimes", "")
        self.download_runtime_filter.addItem("Faster-Whisper", "faster-whisper")
        self.download_runtime_filter.addItem("Vosk / Kaldi", "vosk")
        self.download_runtime_filter.currentIndexChanged.connect(self._filter_download_cards)
        self.download_summary = QLabel("0 tasks")
        self.download_summary.setObjectName("Muted")
        download_filters.addWidget(self.download_search, 1)
        download_filters.addWidget(self.download_runtime_filter)
        download_filters.addWidget(self.download_state_filter)
        download_filters.addWidget(self.download_summary)
        downloads_layout.addLayout(download_filters)
        self.download_list = QListWidget()
        self.download_list.setObjectName("DownloadTaskList")
        self.download_list.setAlternatingRowColors(False)
        self.download_list.setSpacing(12)
        self.download_list.setFrameShape(QFrame.NoFrame)
        self.download_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.download_list.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.download_list.verticalScrollBar().setSingleStep(18)
        self.download_list.horizontalScrollBar().setSingleStep(18)
        self.download_list.setUniformItemSizes(True)
        downloads_layout.addWidget(self.download_list, 1)
        download_actions = QHBoxLayout()
        self.clear_failed_button = QPushButton("Clear failed")
        self.clear_failed_button.setToolTip("Remove failed tasks from download history; model files and caches are not affected")
        self.clear_failed_button.clicked.connect(self.clear_failed_downloads)
        download_actions.addWidget(self.clear_failed_button)
        refresh_downloads = QPushButton("Refresh")
        refresh_downloads.clicked.connect(self.refresh_downloads)
        download_actions.addWidget(refresh_downloads)
        download_actions.addStretch(1)
        downloads_layout.addLayout(download_actions)
        self.download_tab = downloads
        self.tabs.addTab(downloads, "Downloads")

        self.downloads_refresh_timer = QTimer(self)
        self.downloads_refresh_timer.setInterval(1500)
        self.downloads_refresh_timer.timeout.connect(self.refresh_downloads)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        installed = QWidget()
        installed.setObjectName("InstalledTab")
        installed_layout = QVBoxLayout(installed)
        installed_layout.setContentsMargins(14, 14, 14, 14)
        installed_layout.setSpacing(10)
        installed_toolbar = QHBoxLayout()
        self.installed_summary = QLabel("Installed models")
        self.installed_summary.setObjectName("ModelInstalledSummary")
        self.installed_search = QLineEdit()
        self.installed_search.setPlaceholderText("Search installed models…")
        self.installed_search.textChanged.connect(self._filter_installed_cards)
        self.installed_runtime_filter = QComboBox()
        self.installed_runtime_filter.addItem("All runtimes", "")
        self.installed_runtime_filter.addItem("Faster-Whisper", "faster-whisper")
        self.installed_runtime_filter.addItem("Vosk / Kaldi", "vosk")
        self.installed_runtime_filter.currentIndexChanged.connect(self._filter_installed_cards)
        self.installed_state_filter = QComboBox()
        self.installed_state_filter.addItem("All states", "")
        self.installed_state_filter.addItem("Ready", "ready")
        self.installed_state_filter.addItem("Active", "active")
        self.installed_state_filter.addItem("Needs repair", "repair")
        self.installed_state_filter.currentIndexChanged.connect(self._filter_installed_cards)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_installed)
        installed_toolbar.addWidget(self.installed_summary)
        installed_toolbar.addWidget(self.installed_search, 1)
        installed_toolbar.addWidget(self.installed_runtime_filter)
        installed_toolbar.addWidget(self.installed_state_filter)
        installed_toolbar.addWidget(refresh)
        installed_layout.addLayout(installed_toolbar)
        self.installed_scroll = QScrollArea()
        self.installed_scroll.setWidgetResizable(True)
        self.installed_container = QWidget()
        self.installed_cards = QGridLayout(self.installed_container)
        self.installed_cards.setContentsMargins(0, 4, 8, 8)
        self.installed_cards.setHorizontalSpacing(12)
        self.installed_cards.setVerticalSpacing(12)
        self.installed_cards.setColumnStretch(0, 1)
        self.installed_cards.setColumnStretch(1, 1)
        self.installed_scroll.setWidget(self.installed_container)
        installed_layout.addWidget(self.installed_scroll, 1)
        self.tabs.addTab(installed, "Installed")

        import_tab = QWidget()
        import_layout = QVBoxLayout(import_tab)
        import_layout.setContentsMargins(18, 18, 18, 18)
        import_layout.setSpacing(12)
        self.import_repo_id = QLineEdit("local/imported-model")
        self.import_repo_id.setPlaceholderText("local/model-name (owner/model-name format)")
        self.manual_runtime_combo = QComboBox()
        self.manual_runtime_combo.addItem("Faster-Whisper · CTranslate2", "faster-whisper")
        self.manual_runtime_combo.addItem("Vosk · Kaldi", "vosk")
        self.manual_runtime_combo.currentIndexChanged.connect(self._manual_runtime_changed)
        self.manual_language_combo = QComboBox()
        self.manual_language_combo.addItem("Language not specified", "")
        for code, name in (
            ("fa", "Persian / Farsi"), ("en", "English"), ("de", "German"),
            ("fr", "French"), ("es", "Spanish"), ("ar", "Arabic"),
            ("ru", "Russian"), ("zh", "Chinese"), ("ja", "Japanese"),
            ("tr", "Turkish"), ("it", "Italian"),
        ):
            self.manual_language_combo.addItem(name, code)
        self.manual_language_combo.setVisible(False)
        form = QFormLayout()
        form.addRow("Model runtime", self.manual_runtime_combo)
        form.addRow("Model language", self.manual_language_combo)
        form.addRow("Local model ID", self.import_repo_id)
        import_layout.addLayout(form)
        self.import_requirements = QLabel(
            "Faster-Whisper import validates the CTranslate2 model, tokenizer, configuration and vocabulary files. "
            "PyTorch/Transformers checkpoints are not Faster-Whisper models."
        )
        requirements = self.import_requirements
        requirements.setObjectName("Muted")
        requirements.setWordWrap(True)
        import_layout.addWidget(requirements)
        import_actions = QHBoxLayout()
        self.import_directory_button = QPushButton("Import directory…")
        self.import_directory_button.clicked.connect(self._choose_import_directory)
        self.import_zip_button = QPushButton("Import ZIP…")
        self.import_zip_button.clicked.connect(self._choose_import_zip)
        import_actions.addWidget(self.import_directory_button)
        import_actions.addWidget(self.import_zip_button)
        import_actions.addStretch(1)
        import_layout.addLayout(import_actions)
        self.import_progress = QProgressBar()
        self.import_progress.setRange(0, 0)
        self.import_progress.setVisible(False)
        import_layout.addWidget(self.import_progress)
        self.import_status = QLabel(
            "Imported models are copied into managed storage and registered only after validation."
        )
        self.import_status.setObjectName("Muted")
        self.import_status.setWordWrap(True)
        import_layout.addWidget(self.import_status)
        import_layout.addStretch(1)
        self.tabs.addTab(import_tab, "Import")

        layout.addWidget(self.tabs, 1)
        self.discover_hint.setText("Choose Curated models or search the Hub to fetch live repository metadata.")
        self.refresh_installed()
        self.refresh_downloads()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow_installed_grid()

    def _reflow_installed_grid(self):
        if not hasattr(self, "installed_scroll") or not self._installed_card_rows:
            return
        available_width = self.installed_scroll.viewport().width()
        columns = 2 if available_width >= 700 else 1
        if getattr(self, "_installed_grid_columns", 0) == columns:
            return
        self._installed_grid_columns = columns
        self.installed_cards.setColumnStretch(0, 1)
        self.installed_cards.setColumnStretch(1, 1 if columns == 2 else 0)
        for index, (card, _searchable, _runtime, _state) in enumerate(self._installed_card_rows):
            self.installed_cards.removeWidget(card)
            card.setMinimumWidth(300 if columns == 2 else 0)
            row, column = divmod(index, columns)
            self.installed_cards.addWidget(card, row, column)
        # Do not stretch the last row to fill the viewport; cards keep a stable height.
        for row_index in range((len(self._installed_card_rows) + columns - 1) // columns + 1):
            self.installed_cards.setRowStretch(row_index, 0)

    def _manual_runtime_changed(self, *_args):
        is_vosk = self.manual_runtime_combo.currentData() == "vosk"
        self.manual_language_combo.setVisible(is_vosk)
        self.import_requirements.setText(
            "Vosk import checks the acoustic model, feature configuration and decoding graph. "
            "The selected language is stored as metadata; it does not alter the model files."
            if is_vosk else
            "Faster-Whisper import validates the CTranslate2 model, tokenizer, configuration and vocabulary files. "
            "PyTorch/Transformers checkpoints are not Faster-Whisper models."
        )
        if is_vosk and self.import_repo_id.text() == "local/imported-model":
            self.import_repo_id.setText("local/vosk-model")
        elif not is_vosk and self.import_repo_id.text() == "local/vosk-model":
            self.import_repo_id.setText("local/imported-model")

    def _choose_import_directory(self):
        is_vosk = self.manual_runtime_combo.currentData() == "vosk"
        source = QFileDialog.getExistingDirectory(
            self,
            "Import Vosk model directory" if is_vosk else "Import Faster-Whisper model directory",
            str(self.model_manager.registry.root),
        )
        if source:
            self._start_local_import(source, archive=False)

    def _choose_import_zip(self):
        is_vosk = self.manual_runtime_combo.currentData() == "vosk"
        source, _selected = QFileDialog.getOpenFileName(
            self,
            "Import Vosk model ZIP archive" if is_vosk else "Import Faster-Whisper model ZIP archive",
            str(self.model_manager.registry.root),
            "Vosk model ZIP (*.zip)" if is_vosk else "Faster-Whisper model ZIP (*.zip)",
        )
        if source:
            self._start_local_import(source, archive=True)

    def _start_local_import(self, source: str, *, archive: bool):
        from transcriber.models.compatibility import validate_repo_id

        try:
            repo_id = validate_repo_id(self.import_repo_id.text())
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid local model ID", str(exc))
            return
        if repo_id in self._downloads:
            QMessageBox.information(self, "Model operation active", f"A download for {repo_id} is already active.")
            return
        self.import_directory_button.setEnabled(False)
        self.import_zip_button.setEnabled(False)
        self.import_progress.setVisible(True)
        is_vosk = self.manual_runtime_combo.currentData() == "vosk"
        language_code = self.manual_language_combo.currentData() if is_vosk else None
        runtime_label = "Vosk / Kaldi" if is_vosk else "Faster-Whisper / CTranslate2"
        self.import_status.setText(
            f"Validating and importing {source} as {repo_id} · {runtime_label}…"
        )

        def import_model(_emit):
            if is_vosk:
                if archive:
                    return self.model_manager.import_vosk_zip(
                        source, repo_id, language_code=language_code or None,
                    )
                return self.model_manager.import_vosk_directory(
                    source, repo_id, language_code=language_code or None,
                )
            if archive:
                return self.model_manager.import_zip(source, repo_id)
            return self.model_manager.import_directory(source, repo_id)

        worker = FunctionWorker(import_model)
        worker.signals.result.connect(
            lambda target, rid=repo_id: self._local_import_complete(rid, target)
        )
        worker.signals.error.connect(self._local_import_failed)
        worker.signals.finished.connect(self._local_import_finished)
        self.thread_pool.start(worker)

    def _local_import_complete(self, repo_id, target):
        self.import_status.setText(
            f"Imported and validated {repo_id}. Managed files: {target}"
        )
        self.refresh_installed()
        self.installed_models_changed.emit()
        self.status_message.emit(f"Local model imported: {repo_id}")

    def _local_import_failed(self, message):
        self.import_status.setText(f"Import failed: {message}")
        self.status_message.emit(f"Model import failed: {message}")

    def _local_import_finished(self):
        self.import_progress.setVisible(False)
        self.import_directory_button.setEnabled(True)
        self.import_zip_button.setEnabled(True)

    def _clear_cards(self):
        while self.discover_cards.count() > 0:
            item = self.discover_cards.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.discover_cards.addStretch(1)
        self.cards.clear()

    def _append_card(self, model):
        if self.discover_cards.count() and self.discover_cards.itemAt(self.discover_cards.count() - 1).spacerItem():
            self.discover_cards.takeAt(self.discover_cards.count() - 1)
        card = ModelCard(model)
        card.set_installed(self._installed_by_id.get(model.repo_id))
        card.inspect_requested.connect(self.inspect_model)
        card.install_requested.connect(self.install_model)
        card.open_requested.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        self.discover_cards.addWidget(card)
        self.cards[model.repo_id] = card

    def _provider_changed(self, *_args):
        is_vosk = self.provider_combo.currentData() == "vosk"
        self.sort_combo.setVisible(not is_vosk)
        self.language_filter.setVisible(is_vosk)
        self.source_filter.setVisible(is_vosk)
        self.curated_button.setText("Recommended models" if is_vosk else "Curated models")
        self.search_button.setText("Search Vosk" if is_vosk else "Search Hub")
        self.search_input.setPlaceholderText(
            "Search Vosk model name or language (English / en, Persian / fa, or a language name)…"
            if is_vosk else "Search model name or publisher on Hugging Face…"
        )
        self.discover_hint.setText(
            "Vosk API / Kaldi · live official catalogue, with active lightweight models ranked by archive size. Filter by language or source; archived/obsolete entries are excluded from recommendations."
            if is_vosk else
            "Hugging Face Hub · CTranslate2 model, tokenizer, configuration and vocabulary files are checked."
        )

        if is_vosk:
            self._refresh_vosk_languages()

    def _refresh_vosk_languages(self):
        """Load every language present in the active official Vosk catalogue."""
        worker = FunctionWorker(lambda _emit: self.model_manager.vosk_languages())
        worker.signals.result.connect(self._merge_vosk_languages)
        worker.signals.error.connect(
            lambda message: self.discover_hint.setText(
                "Could not refresh Vosk language filters: " + str(message)
            )
            if self.provider_combo.currentData() == "vosk" else None
        )
        self.thread_pool.start(worker)

    def _merge_vosk_languages(self, languages):
        """Add catalogue languages without removing the broad, built-in language filters."""
        if self.provider_combo.currentData() != "vosk":
            return
        selected = self.language_filter.currentData()
        self.language_filter.blockSignals(True)
        known_codes = {
            str(self.language_filter.itemData(index) or "").casefold()
            for index in range(self.language_filter.count())
        }
        added = 0
        for code, name in languages:
            normalized_code = str(code or "").strip().casefold()
            display_name = str(name or "").strip()
            if not normalized_code or not display_name or normalized_code in known_codes:
                continue
            self.language_filter.addItem(
                f"{display_name} ({normalized_code})",
                normalized_code,
            )
            known_codes.add(normalized_code)
            added += 1
        selected_index = self.language_filter.findData(selected)
        if selected_index >= 0:
            self.language_filter.setCurrentIndex(selected_index)
        self.language_filter.blockSignals(False)
        if added:
            self.discover_hint.setText(
                self.discover_hint.text()
                + f" · {added} additional language filter(s) loaded from the catalogue."
            )

    def search_models(self):
        query = self.search_input.text().strip()
        provider = self.provider_combo.currentData()
        self._clear_cards()
        if provider == "vosk":
            language = self.language_filter.currentData()
            source = self.source_filter.currentData()
            self.discover_hint.setText("Searching official Vosk models and verified Hugging Face mirrors…")
            worker = FunctionWorker(
                lambda _emit: self.model_manager.search_vosk(
                    query, limit=100, language=language, source=source,
                )
            )
        else:
            sort = self.sort_combo.currentData()
            self.discover_hint.setText("Searching Hugging Face…")
            worker = FunctionWorker(
                lambda _emit: self.model_manager.search(query, sort=sort, limit=30)
            )
        worker.signals.result.connect(self._show_search_results)
        worker.signals.error.connect(
            lambda message: self.discover_hint.setText(f"Model search failed: {message}")
        )
        self.thread_pool.start(worker)

    def _show_search_results(self, models):
        if not models:
            self.discover_hint.setText("No models were returned by this catalogue search.")
            return
        for model in models:
            self._append_card(model)
        provider = (
            "Vosk catalogue / Hugging Face mirror"
            if self.provider_combo.currentData() == "vosk"
            else "live Hugging Face Hub"
        )
        self.discover_hint.setText(
            f"{len(models)} {provider} result(s). Inspect each model before installation."
        )

    def load_curated(self):
        if self.provider_combo.currentData() == "vosk":
            self.source_filter.setCurrentIndex(self.source_filter.findData(""))
            self.search_input.clear()
            self._clear_cards()
            selected_language = str(self.language_filter.currentData() or "")
            scope = (
                f" for {self.language_filter.currentText()}"
                if selected_language else " across all available languages"
            )
            self.discover_hint.setText(
                "Loading active Vosk catalogue entries"
                + scope
                + " · lightweight models first, then ascending archive size…"
            )
            worker = FunctionWorker(
                lambda _emit, language=selected_language:
                self.model_manager.curated_vosk(language)
            )
            worker.signals.result.connect(self._show_search_results)
            worker.signals.error.connect(
                lambda message: self.discover_hint.setText(f"Could not load recommended Vosk models: {message}")
            )
            self.thread_pool.start(worker)
            return
        if self.provider_combo.currentData() != "faster-whisper":
            self.provider_combo.setCurrentIndex(self.provider_combo.findData("faster-whisper"))
        self.search_input.clear()
        self._clear_cards()
        self.discover_hint.setText("Fetching curated Faster-Whisper model metadata from Hugging Face…")
        def fetch_curated(_emit):
            models = []
            errors = []
            for repo_id in CURATED_MODELS:
                try:
                    models.append(self.model_manager.hub.inspect(repo_id))
                except Exception as exc:
                    errors.append(f"{repo_id}: {exc}")
            return models, errors
        worker = FunctionWorker(fetch_curated)
        worker.signals.result.connect(self._show_curated_results)
        worker.signals.error.connect(lambda message: self.discover_hint.setText(f"Could not load curated models: {message}"))
        self.thread_pool.start(worker)

    def _show_curated_results(self, outcome):
        models, errors = outcome
        self._show_search_results(models)
        if errors:
            previous = self.discover_hint.text()
            self.discover_hint.setText(previous + " · Some curated repositories could not be inspected: " + " | ".join(errors[:3]))

    def inspect_model(self, repo_id: str):
        card = self.cards.get(repo_id)
        if card:
            card.inspect_button.setEnabled(False)
            card.report = None
            card.install_button.setEnabled(False)
            card.compatibility.setText("Inspecting repository files…")
        worker = FunctionWorker(lambda _emit: self.model_manager.inspect(repo_id))
        worker.signals.result.connect(
            lambda result, rid=repo_id, owner=card: self._inspection_result(rid, result, owner)
        )
        worker.signals.error.connect(
            lambda message, rid=repo_id, owner=card: self._inspection_error(rid, message, owner)
        )
        self.thread_pool.start(worker)

    def _inspection_result(self, repo_id, result, owner=None):
        card = self.cards.get(repo_id)
        if card and (owner is None or card is owner):
            card.inspect_button.setEnabled(True)
            card.set_inspection(*result)
            card.set_installed(self._installed_by_id.get(repo_id))

    def _inspection_error(self, repo_id, message, owner=None):
        card = self.cards.get(repo_id)
        if card and (owner is None or card is owner):
            card.report = None
            card.inspect_button.setEnabled(True)
            card.install_button.setEnabled(False)
            card.compatibility.setText("Inspection failed")
            card.detail_label.setText(message)

    def _on_tab_changed(self, _index):
        if self.tabs.currentWidget() is self.download_tab:
            self.refresh_downloads()
        else:
            self.downloads_refresh_timer.stop()

    def refresh_downloads(self):
        if self._downloads_refresh_pending:
            self._downloads_refresh_again = True
            return
        self._downloads_refresh_pending = True
        worker = FunctionWorker(lambda _emit: self.model_manager.list_download_jobs())
        worker.signals.result.connect(self._show_download_jobs)
        worker.signals.error.connect(self._show_download_jobs_error)
        worker.signals.finished.connect(self._downloads_refresh_finished)
        self.thread_pool.start(worker)

    def _downloads_refresh_finished(self):
        self._downloads_refresh_pending = False
        if self._downloads_refresh_again:
            self._downloads_refresh_again = False
            QTimer.singleShot(0, self.refresh_downloads)

    def _show_download_jobs_error(self, message):
        self.downloads_hint.setText(f"Could not load persistent download history: {message}")

    def refresh_visual_theme(self):
        """Rebuild token-colored model cards after the application theme changes."""
        if self._download_jobs:
            self._show_download_jobs(self._download_jobs)
        if self._installed_by_id:
            self._show_installed_models(list(self._installed_by_id.values()))

    def _show_download_jobs(self, jobs):
        self._download_jobs = list(jobs)
        self.download_list.clear()
        self._download_card_rows.clear()
        active_states = {
            "queued", "inspecting", "downloading", "validating", "installing",
            "pausing", "stopping", "cancelling",
        }
        resumable_states = {"paused", "stopped"}
        state_counts = {
            "active": 0, "recoverable": 0, "failed": 0,
            "installed": 0, "cancelled": 0,
        }

        for job in jobs:
            state = str(job.get("state") or "unknown").casefold()
            repo_id = str(job.get("repo_id") or "Unknown model")
            task_id = str(job.get("task_id") or "")
            metadata = job.get("metadata") or {}
            runtime = (
                "vosk" if metadata.get("runtime") == "vosk" or self.model_manager.is_vosk_model_id(repo_id)
                else "faster-whisper"
            )
            runtime_label = "VOSK / KALDI" if runtime == "vosk" else "FASTER-WHISPER"
            source = (
                metadata.get("source_repo") or metadata.get("source")
                or ("Official Vosk catalogue" if runtime == "vosk" else "Hugging Face Hub")
            )
            language = str(metadata.get("language_name") or metadata.get("language") or "")
            downloaded_bytes = int(job.get("downloaded_bytes") or 0)
            total_bytes = job.get("total_bytes")
            try:
                total_bytes = int(total_bytes) if total_bytes is not None else None
            except (TypeError, ValueError):
                total_bytes = None
            percent = (
                max(0, min(100, int(downloaded_bytes / total_bytes * 100)))
                if total_bytes and total_bytes > 0 else None
            )

            if state in active_states:
                filter_state = "active"
                state_counts["active"] += 1
            elif state == "failed":
                filter_state = "failed"
                state_counts["failed"] += 1
            elif state in resumable_states:
                filter_state = "recoverable"
                state_counts["recoverable"] += 1
            elif state in {"installed", "completed"}:
                filter_state = "installed"
                state_counts["installed"] += 1
            elif state == "cancelled":
                filter_state = "cancelled"
                state_counts["cancelled"] += 1
            else:
                filter_state = state

            state_tone = (
                "success" if state in {"installed", "completed"}
                else "danger" if state == "failed"
                else "warning" if state in {"paused", "stopped", "pausing", "stopping"}
                else "info" if state in active_states
                else "neutral"
            )
            model_title = str(metadata.get("model_name") or repo_id)
            revision = str(job.get("revision") or "revision unavailable")
            size_line = f"{_human_size(downloaded_bytes)} / {_human_size(total_bytes)}"
            if percent is not None:
                size_line += f"  ·  {percent}%"
            supporting = [runtime_label]
            if language:
                supporting.append(language)
            supporting.append(str(source))
            detail = "  ·  ".join(supporting)

            row = QFrame()
            row.setObjectName("DownloadTaskCard")
            row.setFrameShape(QFrame.NoFrame)
            row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            row.setFixedHeight(252)
            row.setProperty("state", state_tone)
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(16, 13, 16, 13)
            row_layout.setSpacing(9)

            heading = QHBoxLayout()
            heading.setSpacing(8)
            title = QLabel(model_title)
            title.setObjectName("ModelTaskTitle")
            title.setWordWrap(True)
            title.setTextInteractionFlags(Qt.TextSelectableByMouse)
            heading.addWidget(title, 1)

            runtime_badge = QLabel("Vosk / Kaldi" if runtime == "vosk" else "Faster-Whisper")
            runtime_badge.setObjectName("ModelRuntimeBadge")
            heading.addWidget(runtime_badge, 0, Qt.AlignTop)

            state_text = {
                "queued": "QUEUED", "inspecting": "INSPECTING",
                "downloading": "DOWNLOADING", "validating": "VERIFYING",
                "installing": "INSTALLING", "pausing": "PAUSING",
                "stopping": "STOPPING", "cancelling": "CANCELLING",
                "paused": "PAUSED", "stopped": "STOPPED",
                "failed": "FAILED", "installed": "INSTALLED",
                "completed": "COMPLETED", "cancelled": "CANCELLED",
            }.get(state, state.replace("_", " ").upper())
            state_badge = QLabel(state_text)
            state_badge.setObjectName("ModelTaskStateBadge")
            state_badge.setProperty("state", state_tone)
            heading.addWidget(state_badge, 0, Qt.AlignTop)
            row_layout.addLayout(heading)

            meta_label = QLabel(detail)
            meta_label.setObjectName("ModelTaskMeta")
            meta_label.setWordWrap(True)
            row_layout.addWidget(meta_label)

            transfer_row = QHBoxLayout()
            transfer_caption = QLabel("TRANSFER")
            transfer_caption.setObjectName("ModelTransferCaption")
            transfer_value = QLabel(size_line)
            transfer_value.setObjectName("ModelTransferValue")
            transfer_row.addWidget(transfer_caption)
            transfer_row.addStretch(1)
            transfer_row.addWidget(transfer_value)
            row_layout.addLayout(transfer_row)

            progress = QProgressBar()
            progress.setObjectName("DownloadTaskProgress")
            progress.setTextVisible(False)
            progress.setFixedHeight(7)
            progress.setProperty("state", state_tone)
            if total_bytes and total_bytes > 0:
                progress.setRange(0, 100)
                progress.setValue(percent or 0)
            elif state in {"queued", "inspecting", "downloading", "validating", "installing"}:
                progress.setRange(0, 0)
            else:
                progress.setRange(0, 100)
                progress.setValue(100 if state in {"installed", "completed"} else 0)
            row_layout.addWidget(progress)

            if job.get("error"):
                error_label = QLabel(str(job["error"]))
                error_label.setWordWrap(True)
                error_label.setMaximumHeight(36)
                error_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                error_label.setToolTip(str(job["error"]))
                error_label.setObjectName("ModelErrorNotice")
                row_layout.addWidget(error_label)

            revision_label = QLabel(f"Revision · {revision[:16]}{'…' if len(revision) > 16 else ''}")
            revision_label.setObjectName("ModelRevision")
            revision_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row_layout.addWidget(revision_label)

            actions = QHBoxLayout()
            actions.setSpacing(7)
            actions.addStretch(1)

            def compact_button(label: str, role: str = "neutral") -> QPushButton:
                button = QPushButton(label)
                button.setCursor(Qt.PointingHandCursor)
                button.setFixedHeight(28)
                button.setObjectName("ModelTaskActionButton")
                button.setProperty("variant", role)
                return button

            if state in {"queued", "inspecting", "downloading"}:
                pause = compact_button("Pause")
                pause.clicked.connect(
                    lambda _checked=False, rid=repo_id: self.pause_download(rid)
                )
                stop = compact_button("Stop", "warning")
                stop.clicked.connect(
                    lambda _checked=False, rid=repo_id: self.stop_download(rid)
                )
                cancel = compact_button("Cancel", "danger")
                cancel.clicked.connect(
                    lambda _checked=False, rid=repo_id: self.cancel_download(rid)
                )
                actions.addWidget(pause)
                actions.addWidget(stop)
                actions.addWidget(cancel)
            elif state in {"paused", "stopped", "failed"}:
                primary_label = "Retry" if state == "failed" else "Resume"
                resume = compact_button(primary_label, "primary")
                resume.clicked.connect(
                    lambda _checked=False, current=job, failed=(state == "failed"): (
                        self.restart_download(current) if failed
                        else self.resume_download(current)
                    )
                )
                actions.addWidget(resume)
                restart = compact_button("Start over")
                restart.clicked.connect(
                    lambda _checked=False, current=job: self.restart_download(current)
                )
                actions.addWidget(restart)
            elif state == "cancelled":
                restart = compact_button("Download again", "primary")
                restart.clicked.connect(
                    lambda _checked=False, current=job: self.restart_download(current)
                )
                actions.addWidget(restart)
            elif state in {"pausing", "stopping", "cancelling"}:
                pending = QLabel("Applying request…")
                pending.setObjectName("ModelPendingAction")
                actions.addWidget(pending)
            elif state in {"validating", "installing"}:
                pending = QLabel("Verifying and registering model…")
                pending.setObjectName("ModelPendingAction")
                actions.addWidget(pending)

            if state not in active_states and task_id:
                remove_label = (
                    "Remove from history" if state in {"installed", "completed"}
                    else "Delete partial files"
                )
                remove = compact_button(remove_label, "danger")
                remove.clicked.connect(
                    lambda _checked=False, current=job: self.remove_download_job(current)
                )
                actions.addWidget(remove)
            row_layout.addLayout(actions)

            # The QListWidget item must reserve the exact same height as its
            # fixed-height card. QWidget.sizeHint() can still be smaller than a
            # fixed-height constraint before the layout is polished, which causes
            # the next item to be painted over this card on some Qt styles.
            row_layout.activate()
            row.updateGeometry()
            item = QListWidgetItem()
            self.download_list.addItem(item)
            self.download_list.setItemWidget(item, row)
            item.setSizeHint(QSize(0, row.height()))
            searchable = " ".join((
                repo_id, model_title, str(source), runtime, state, language,
                str(job.get("error") or ""),
            )).casefold()
            self._download_card_rows.append((row, searchable, runtime, filter_state))

        self.download_summary.setText(
            f"{len(jobs)} tasks  ·  {state_counts['active']} active  ·  "
            f"{state_counts['failed']} failed  ·  {state_counts['recoverable']} resumable"
        )
        self.clear_failed_button.setEnabled(state_counts["failed"] > 0)
        downloads_index = self.tabs.indexOf(self.download_tab)
        if downloads_index >= 0:
            self.tabs.setTabText(
                downloads_index,
                f"Downloads · {state_counts['active']}" if state_counts["active"] else "Downloads",
            )
        if not jobs:
            self.downloads_hint.setText(
                "No download tasks yet. Discover a model, inspect its runtime compatibility, then install it."
            )
        else:
            self.downloads_hint.setText(
                "Tasks are kept locally. Failed, paused and stopped entries can be retried or removed from history. "
                "Removing a task does not delete an installed model or the reusable download cache."
            )
        self._filter_download_cards()
        if self.tabs.currentWidget() is self.download_tab and state_counts["active"]:
            self.downloads_refresh_timer.start()
        else:
            self.downloads_refresh_timer.stop()

    def _filter_download_cards(self, *_args):
        needle = self.download_search.text().strip().casefold()
        runtime_filter = str(self.download_runtime_filter.currentData() or "")
        state_filter = str(self.download_state_filter.currentData() or "")
        for widget, searchable, runtime, state in self._download_card_rows:
            widget.setVisible(
                (not needle or needle in searchable)
                and (not runtime_filter or runtime == runtime_filter)
                and (not state_filter or state == state_filter)
            )

    def remove_download_job(self, job: dict):
        """Remove one terminal task from history, without touching model files or caches."""
        task_id = str(job.get("task_id") or "")
        repo_id = str(job.get("repo_id") or "this model")
        if not task_id:
            return
        if repo_id in self._downloads:
            QMessageBox.information(
                self, "Download is active",
                "Cancel or stop the active task before removing it from history.",
            )
            return
        state = str(job.get("state") or "").casefold()
        if state in {"queued", "inspecting", "downloading", "validating", "installing",
                     "pausing", "stopping", "cancelling"}:
            return
        removes_partial_data = state not in {"installed", "completed"}
        answer = QMessageBox.question(
            self,
            "Delete partial download?" if removes_partial_data else "Remove download history?",
            (
                f"Delete the incomplete download for {repo_id} and remove its history entry?\n\n"
                "The task-specific Vosk archive, abandoned staging files, and this model's "
                "Hugging Face incomplete/revision cache will be removed. Cache blobs shared "
                "with other models or revisions are kept."
                if removes_partial_data else
                f"Remove the completed entry for {repo_id} from Downloads?\n\n"
                "The installed model files will remain untouched."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            removed = self.model_manager.remove_download_job(task_id)
            if removed:
                self.status_message.emit(f"Removed download history: {repo_id}")
            self.refresh_downloads()
        except Exception as exc:
            QMessageBox.warning(self, "Cannot remove download history", str(exc))

    def clear_failed_downloads(self):
        jobs = self.model_manager.list_download_jobs()
        failed = [job for job in jobs if str(job.get("state") or "").casefold() == "failed"]
        if not failed:
            return
        answer = QMessageBox.question(
            self,
            "Clear failed downloads?",
            f"Delete partial files for {len(failed)} failed download entr{'y' if len(failed) == 1 else 'ies'} "
            "and remove them from history? Cache blobs shared with other models are preserved.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        removed = 0
        errors = []
        for job in failed:
            try:
                removed += int(self.model_manager.remove_download_job(str(job.get("task_id") or "")))
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            QMessageBox.warning(
                self, "Some failed tasks could not be removed",
                f"Removed {removed} task(s).\\n" + "\\n".join(errors[:3]),
            )
        else:
            self.status_message.emit(f"Removed {removed} failed download entr{'y' if removed == 1 else 'ies'}.")
        self.refresh_downloads()

    def pause_download(self, repo_id: str):
        if self.model_manager.pause_download(repo_id):
            self.status_message.emit(f"Pausing {repo_id} at the next safe transfer boundary…")
            self.refresh_downloads()

    def stop_download(self, repo_id: str):
        if self.model_manager.stop_download(repo_id):
            self.status_message.emit(f"Stopping {repo_id}; cached data will be retained.")
            self.refresh_downloads()

    def cancel_download(self, repo_id: str):
        event = self._downloads.get(repo_id)
        if not event:
            return
        answer = QMessageBox.question(
            self,
            "Cancel model download?",
            f"Cancel the download for {repo_id}? The partial archive or reusable cache will be kept where possible.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        event.set()
        if self.model_manager.cancel_download(repo_id):
            self.status_message.emit(f"Cancelling download: {repo_id}; shared cache is retained.")
            self.refresh_downloads()

    def resume_download(self, job: dict):
        repo_id = str(job.get("repo_id") or "")
        task_id = str(job.get("task_id") or "")
        if not repo_id or not task_id:
            return
        if repo_id in self._downloads:
            self.status_message.emit(f"A download for {repo_id} is already active.")
            return
        event = threading.Event()
        self._downloads[repo_id] = event
        self._download_task_ids[repo_id] = task_id
        worker = FunctionWorker(lambda emit: self.model_manager.resume_download(
            task_id, cancel_event=event, progress=emit,
        ))
        self._wire_download_worker(worker, repo_id, task_id)
        self._download_workers[repo_id] = worker
        self.thread_pool.start(worker)
        self.status_message.emit(f"Resuming {repo_id} at revision {str(job.get('revision') or '')[:12]}.")

    def restart_download(self, job: dict):
        repo_id = str(job.get("repo_id") or "")
        if not repo_id:
            return
        if repo_id in self._downloads:
            self.status_message.emit(f"A download for {repo_id} is already active.")
            return
        model = job.get("metadata") or {}
        task_id = uuid.uuid4().hex
        event = threading.Event()
        self._downloads[repo_id] = event
        self._download_task_ids[repo_id] = task_id
        if model.get("runtime") == "vosk" or self.model_manager.is_vosk_model_id(repo_id):
            worker = FunctionWorker(lambda emit: self.model_manager.install_vosk(
                repo_id, cancel_event=event, progress=emit, task_id=task_id, metadata=model,
            ))
        else:
            worker = FunctionWorker(lambda emit: self.model_manager.install(
                repo_id,
                revision=job.get("revision"),
                cancel_event=event,
                progress=emit,
                task_id=task_id,
                metadata=model,
            ))
        self._wire_download_worker(worker, repo_id, task_id)
        self._download_workers[repo_id] = worker
        self.thread_pool.start(worker)
        self.status_message.emit(f"Restarting {repo_id} as a new download task.")

    def _wire_download_worker(self, worker, repo_id: str, task_id: str, card=None):
        worker.signals.progress.connect(
            lambda progress, current_card=card: (
                current_card.set_download_progress(progress) if current_card else None
            )
        )
        worker.signals.result.connect(
            lambda result, rid=repo_id: self._download_complete(rid, result)
        )
        worker.signals.error.connect(
            lambda message, rid=repo_id, tid=task_id: self._download_failed(rid, tid, message)
        )
        worker.signals.finished.connect(
            lambda rid=repo_id, tid=task_id: self._download_finished(rid, tid)
        )

    def install_model(self, repo_id: str):
        card = self.cards.get(repo_id)
        if not card or not card.report or not card.report.compatible:
            return
        model = card.model
        is_vosk = str(getattr(model, "runtime", "faster-whisper")) == "vosk"
        if not model.revision:
            QMessageBox.warning(
                self, "Revision unavailable",
                "The model catalogue did not provide a reproducible revision or checksum.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Install Vosk model" if is_vosk else "Install model",
            (
                f"Download {repo_id} from the official Vosk catalogue?\n\n"
                f"Language: {model.language_name}\nType: {model.model_type}\n"
                f"Archive: {model.size_text or _human_size(model.size_bytes)}\n"
                f"Checksum ({model.checksum_algorithm.upper()}): {model.checksum}\n"
                f"Source: {model.source_label}\n\n"
                "The ZIP checksum and Vosk directory layout will be verified before installation."
                if is_vosk else
                f"Download {repo_id} from Hugging Face?\n\nRevision: {model.revision}\n"
                f"License: {model.license or 'Not provided'}\n\n"
                "The repository will be validated before it is marked installed. "
                "Review the model card and its license before continuing."
            ),
        )
        if answer != QMessageBox.Yes:
            return
        if repo_id in self._downloads:
            self.status_message.emit(f"A download for {repo_id} is already active.")
            return
        task_id = uuid.uuid4().hex
        event = threading.Event()
        self._downloads[repo_id] = event
        self._download_task_ids[repo_id] = task_id
        card.install_button.setText("Cancel download")
        try:
            card.install_button.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        card.install_button.clicked.connect(lambda _checked=False, rid=repo_id: self.cancel_download(rid))
        card.progress.setVisible(True)
        card.progress.setRange(0, 0)
        card.progress_text.setText("Queued · task saved to Downloads")
        metadata = {
            "license": model.license,
            "task": model.task,
            "languages": list(model.languages or []),
            "repository_url": model.url,
            "runtime": "vosk" if is_vosk else "faster-whisper",
        }
        if is_vosk:
            metadata.update(model.metadata)
            worker = FunctionWorker(lambda emit: self.model_manager.install_vosk(
                repo_id, cancel_event=event, progress=emit, task_id=task_id, metadata=metadata,
            ))
        else:
            worker = FunctionWorker(lambda emit: self.model_manager.install(
                repo_id,
                revision=model.revision,
                cancel_event=event,
                progress=emit,
                task_id=task_id,
                metadata=metadata,
            ))
        self._wire_download_worker(worker, repo_id, task_id, card)
        self._download_workers[repo_id] = worker
        self.thread_pool.start(worker)
        self.refresh_downloads()

    def _download_complete(self, repo_id, path):
        card = self.cards.get(repo_id)
        if card:
            card.progress_text.setText(f"Installed and validated · {path}")
            card.install_button.setText("Installed")
            card.install_button.setEnabled(False)
        self.refresh_installed()
        self.installed_models_changed.emit()
        self.status_message.emit(f"Model installed: {repo_id}")

    def _download_failed(self, repo_id, task_id, message):
        card = self.cards.get(repo_id)
        job = None
        repository = self.model_manager.job_repository
        if repository is not None:
            try:
                job = repository.get(task_id)
            except Exception:
                job = None
        state = str(job.get("state") if job else "failed").casefold()
        if job and job.get("error"):
            message = str(job["error"])
        state_label = {
            "paused": "Paused",
            "stopped": "Stopped",
            "cancelled": "Cancelled",
        }.get(state, "Download failed")
        if card:
            card.progress_text.setText(f"{state_label}: {message}")
        self.status_message.emit(f"{state_label}: {repo_id}")

    def _download_finished(self, repo_id, task_id):
        self._downloads.pop(repo_id, None)
        self._download_task_ids.pop(repo_id, None)
        self._download_workers.pop(repo_id, None)
        card = self.cards.get(repo_id)
        if card and card.install_button.text() == "Cancel download":
            try:
                card.install_button.clicked.disconnect()
            except (RuntimeError, TypeError):
                pass
            card.install_button.setText("Install model")
            card.install_button.setEnabled(bool(card.report and card.report.compatible))
            card.install_button.clicked.connect(lambda _checked=False, rid=repo_id: self.install_model(rid))
        self.refresh_downloads()
        self.refresh_installed_if_needed()

    def refresh_installed_if_needed(self):
        if self.tabs.currentWidget().objectName() == "InstalledTab":
            self.refresh_installed()

    def refresh_installed(self):
        self._clear_installed_cards()
        self.installed_cards.addWidget(QLabel("Refreshing local model registry…"), 0, 0, 1, 2)
        worker = FunctionWorker(lambda _emit: self.model_manager.installed(include_sizes=True))
        worker.signals.result.connect(self._show_installed_models)
        worker.signals.error.connect(self._show_installed_error)
        self.thread_pool.start(worker)

    def _clear_installed_cards(self):
        self._installed_card_rows.clear()
        self._installed_grid_columns = 0
        for row in range(100):
            self.installed_cards.setRowStretch(row, 0)
        while self.installed_cards.count() > 0:
            item = self.installed_cards.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _sync_discover_install_states(self):
        for repo_id, card in self.cards.items():
            card.set_installed(self._installed_by_id.get(repo_id))

    def _filter_installed_cards(self, *_args):
        needle = self.installed_search.text().strip().casefold()
        runtime_filter_value = str(self.installed_runtime_filter.currentData() or "").strip()
        runtime_filter = _installed_runtime_key(runtime_filter_value) if runtime_filter_value else ""
        state_filter = str(self.installed_state_filter.currentData() or "").strip().casefold()
        for card, searchable, runtime, state in self._installed_card_rows:
            matches_query = not needle or needle in searchable
            matches_runtime = not runtime_filter or _installed_runtime_key(runtime) == runtime_filter
            matches_state = not state_filter or state == state_filter
            card.setVisible(matches_query and matches_runtime and matches_state)

    def _show_installed_models(self, installed):
        self._clear_installed_cards()
        self._installed_by_id = {item["repo_id"]: item for item in installed}
        self._sync_discover_install_states()
        count = len(installed)
        self.installed_summary.setText(
            f"{count} installed model{'s' if count != 1 else ''}"
        )
        if not installed:
            empty = QLabel(
                "No models installed yet. Discover a compatible model or import one from disk."
            )
            empty.setObjectName("Muted")
            empty.setWordWrap(True)
            empty.setAlignment(Qt.AlignCenter)
            self.installed_cards.addWidget(empty, 0, 0, 1, 2)
            return

        default_model = self.settings_store.settings.default_model
        wake_model_directory = str(self.settings_store.settings.wake_model_directory or "")
        for index, model in enumerate(installed):
            runtime = _installed_runtime_key(model)
            is_vosk = runtime == "vosk"
            runtime_name = "VOSK / KALDI" if is_vosk else "FASTER-WHISPER"
            repo_id = str(model["repo_id"])
            active = bool(model.get("active"))
            compatible = bool(model.get("compatible"))
            state = "active" if active else "ready" if compatible else "repair"
            state_text = {
                "active": "ACTIVE",
                "ready": "READY",
                "repair": "NEEDS REPAIR",
            }[state]
            card = QFrame()
            card.setObjectName("InstalledModelCard")
            card.setMinimumWidth(300)
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            card.setFixedHeight(360)
            card.setProperty("state", state)
            layout = QVBoxLayout(card)
            layout.setContentsMargins(17, 15, 17, 14)
            layout.setSpacing(10)

            top = QHBoxLayout()
            top.setSpacing(8)
            title = QLabel(repo_id)
            title.setObjectName("ModelInstalledTitle")
            title.setWordWrap(True)
            title.setTextInteractionFlags(Qt.TextSelectableByMouse)
            top.addWidget(title, 1)

            state_badge = QLabel(state_text)
            state_badge.setObjectName("ModelInstalledStateBadge")
            state_badge.setProperty("state", state)
            top.addWidget(state_badge, 0, Qt.AlignTop)
            layout.addLayout(top)

            runtime_badge = QLabel(runtime_name)
            runtime_badge.setObjectName("ModelRuntimeBadge")
            layout.addWidget(runtime_badge, 0, Qt.AlignLeft)

            revision = str(model.get("revision") or "Unknown")
            size_label = _human_size(model.get("size_bytes"))
            if is_vosk:
                language = str(
                    model.get("language_name") or model.get("language_code") or "Unknown language"
                )
                checksum_label = str(
                    model.get("archive_checksum_algorithm") or "revision"
                ).upper()
                info_text = (
                    f"{language}  ·  {size_label}\n"
                    f"{model.get('model_name') or repo_id}  ·  "
                    f"{checksum_label}: {revision[:16]}"
                )
            else:
                info_text = (
                    f"CTranslate2 model  ·  {size_label}\n"
                    f"Revision: {revision[:16]}{'…' if len(revision) > 16 else ''}"
                )
            info_panel = QFrame()
            info_panel.setObjectName("ModelInstalledInfoPanel")
            info_layout = QVBoxLayout(info_panel)
            info_layout.setContentsMargins(10, 8, 10, 8)
            info_label = QLabel(info_text)
            info_label.setObjectName("ModelInstalledInfoLabel")
            info_label.setWordWrap(True)
            info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            info_layout.addWidget(info_label)
            layout.addWidget(info_panel)

            if not is_vosk and repo_id == default_model:
                default_label = QLabel("★  DEFAULT FOR FASTER-WHISPER TRANSCRIPTIONS")
                default_label.setObjectName("ModelDefaultBadge")
                layout.addWidget(default_label)

            path_caption = QLabel("MODEL LOCATION")
            path_caption.setObjectName("ModelPathCaption")
            layout.addWidget(path_caption)
            path_label = QLabel(str(model["path"]))
            path_label.setObjectName("ModelPathLabel")
            path_label.setWordWrap(True)
            path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            path_label.setToolTip(str(model["path"]))
            layout.addWidget(path_label)

            compatibility = QLabel(
                model.get("compatibility_message") or
                ("Model structure validated and ready to use." if compatible
                 else "The local model structure needs attention.")
            )
            compatibility.setObjectName("ModelInstalledCompatibility")
            compatibility.setProperty("state", "compatible" if compatible else "warning")
            compatibility.setWordWrap(True)
            layout.addWidget(compatibility)

            def action_button(label: str, role: str = "neutral") -> QPushButton:
                button = QPushButton(label)
                button.setCursor(Qt.PointingHandCursor)
                button.setFixedHeight(29)
                button.setObjectName("ModelInstalledActionButton")
                button.setProperty("variant", role)
                return button

            utility_actions = QHBoxLayout()
            utility_actions.setSpacing(7)
            open_button = action_button("Open folder")
            open_button.clicked.connect(
                lambda _=False, p=str(model["path"]):
                QDesktopServices.openUrl(QUrl.fromLocalFile(p))
            )
            utility_actions.addWidget(open_button)

            if not is_vosk:
                is_default = repo_id == default_model
                default_button = action_button(
                    "★ Default model" if is_default else "Set as default"
                )
                default_button.setEnabled(compatible and not is_default)
                default_button.clicked.connect(
                    lambda _=False, rid=repo_id: self.set_default_model(rid)
                )
                utility_actions.addWidget(default_button)
            else:
                current_voice_path = ""
                try:
                    current_voice_path = str(Path(wake_model_directory).resolve())
                except (OSError, RuntimeError):
                    pass
                try:
                    this_model_path = str(Path(model["path"]).resolve())
                except (OSError, RuntimeError):
                    this_model_path = str(model["path"])
                voice_selected = bool(current_voice_path and current_voice_path == this_model_path)
                voice_button = action_button(
                    "✓ Voice model selected" if voice_selected else "Use for voice assistant"
                )
                voice_button.setEnabled(compatible and not voice_selected)
                voice_button.clicked.connect(
                    lambda _=False, rid=repo_id: self.set_vosk_voice_model(rid)
                )
                utility_actions.addWidget(voice_button)
            utility_actions.addStretch(1)
            layout.addLayout(utility_actions)

            main_actions = QHBoxLayout()
            load_button = action_button("Unload" if active else "Load model", "primary" if compatible and not active else "neutral")
            load_button.setEnabled(compatible)
            load_button.clicked.connect(
                lambda _=False, rid=repo_id, is_active=active:
                self.release_active_model() if is_active else self.load_model(rid)
            )
            delete_button = action_button("Delete model", "danger")
            delete_button.setEnabled(not active)
            delete_button.clicked.connect(
                lambda _=False, rid=repo_id: self.delete_model(rid)
            )
            main_actions.addWidget(load_button)
            main_actions.addStretch(1)
            main_actions.addWidget(delete_button)
            layout.addLayout(main_actions)

            self.installed_cards.addWidget(card, index, 0)
            searchable = " ".join((
                repo_id, runtime,
                str(model.get("language_name") or model.get("language_code") or ""),
                str(model.get("revision") or ""), str(model.get("path") or ""),
            )).casefold()
            self._installed_card_rows.append((card, searchable, runtime, state))

        self._reflow_installed_grid()
        self._filter_installed_cards(self.installed_search.text())

    def _show_installed_error(self, message):
        self._clear_installed_cards()
        self._installed_by_id = {}
        self._sync_discover_install_states()
        self.installed_summary.setText("Installed models unavailable")
        label = QLabel(f"Could not inspect installed models: {message}")
        label.setObjectName("Muted")
        label.setWordWrap(True)
        self.installed_cards.addWidget(label, 0, 0, 1, 2)

    def set_vosk_voice_model(self, repo_id: str):
        model = self._installed_by_id.get(repo_id)
        if not model or model.get("runtime") != "vosk" or not model.get("compatible"):
            return
        model_path = str(Path(model["path"]).resolve())
        self.settings_store.update(wake_model_directory=model_path, vosk_default_model=repo_id)
        self.vosk_model_selected.emit(model_path)
        self.refresh_installed()
        self.status_message.emit(
            f"Vosk voice model selected: {model.get('language_name') or repo_id}"
        )

    def set_default_model(self, repo_id: str):
        self.settings_store.update(default_model=repo_id)
        self.default_model_changed.emit(repo_id)
        self._sync_discover_install_states()
        self.refresh_installed()
        self.status_message.emit(f"Default model set to {repo_id}")

    def load_model(self, repo_id: str):
        self.status_message.emit(f"Loading {repo_id}…")
        worker = FunctionWorker(lambda _emit: self.model_manager.load(repo_id, self.settings_store.settings))
        worker.signals.result.connect(lambda _result: self._model_loaded(repo_id))
        worker.signals.error.connect(lambda message: QMessageBox.critical(self, "Model load failed", message))
        self.thread_pool.start(worker)

    def _model_loaded(self, repo_id: str):
        self.refresh_installed()
        self.status_message.emit(f"Model loaded: {repo_id}")

    def delete_model(self, repo_id: str):
        answer = QMessageBox.question(self, "Delete model", f"Permanently remove the local files for {repo_id}? Transcripts are not affected.")
        if answer != QMessageBox.Yes:
            return
        try:
            if self.model_manager.active_model_id == repo_id:
                self.release_active_model()
            self.model_manager.delete(repo_id)
            self.refresh_installed()
            self.installed_models_changed.emit()
            self.status_message.emit(f"Model deleted: {repo_id}")
        except Exception as exc:
            QMessageBox.warning(self, "Cannot delete model", str(exc))
