"""Live Hugging Face model discovery and locally installed model management."""

from __future__ import annotations

import threading
import uuid

from PySide6.QtCore import QTimer, QUrl, Signal, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
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
        heading = QLabel(model.repo_id)
        heading.setStyleSheet("font-size: 15px; font-weight: 650;")
        top.addWidget(heading, 1)
        self.compatibility = QLabel("Compatibility not inspected")
        self.compatibility.setObjectName("Muted")
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
        open_button = QPushButton("Open on Hugging Face ↗")
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

    def set_inspection(self, metadata, report):
        self.model = metadata
        self.report = report
        if report.compatible:
            self.compatibility.setText("Compatible · Faster-Whisper")
            self.compatibility.setStyleSheet("color: #36a47e; font-weight: 600;")
        else:
            self.compatibility.setText("Not compatible")
            self.compatibility.setStyleSheet("color: #d65a65; font-weight: 600;")
        files = []
        sizes = {item.name: item.size for item in metadata.files}
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
        missing = (" Missing: " + ", ".join(report.missing_files)) if report.missing_files else ""
        self.inspection_detail = (
            f"Estimated download: {size_text}\nFiles: " + (", ".join(files) or "Not provided") +
            f"\n{report.reason}{missing}\nPinned revision: {metadata.revision or 'Unknown'}"
        )
        self.detail_label.setText(self.inspection_detail)
        self.set_installed(self.installed_info)

    def set_installed(self, installed_info):
        """Keep Hub inspection and local installation state visible together."""
        self.installed_info = installed_info
        if installed_info:
            compatible = bool(installed_info.get("compatible"))
            self.compatibility.setText(
                "Installed · Ready" if compatible else "Installed · Repair needed"
            )
            self.compatibility.setStyleSheet(
                "color: #36a47e; font-weight: 700;" if compatible
                else "color: #d49a42; font-weight: 700;"
            )
            self.install_button.setText("Installed" if compatible else "Installed · Repair")
            self.install_button.setEnabled(False)
            path = installed_info.get("path")
            revision = installed_info.get("revision")
            self.detail_label.setText(
                f"Local installation detected · revision {revision or 'unknown'}"
                + (f"\n{path}" if path else "")
            )
        else:
            if self.report:
                compatible = bool(self.report.compatible)
                self.compatibility.setText(
                    "Compatible · Faster-Whisper" if compatible else "Not compatible"
                )
                self.compatibility.setStyleSheet(
                    "color: #36a47e; font-weight: 600;" if compatible
                    else "color: #d65a65; font-weight: 600;"
                )
                if self.inspection_detail:
                    self.detail_label.setText(self.inspection_detail)
            else:
                self.compatibility.setText("Compatibility not inspected")
                self.compatibility.setStyleSheet("")
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
            elif not self.installed_info:
                self.install_button.setText("Install model")
                self.install_button.setEnabled(bool(self.report and self.report.compatible))


class ModelLibraryPage(QWidget):
    status_message = Signal(str)
    default_model_changed = Signal(str)

    def __init__(self, model_manager, settings_store, thread_pool, release_active_model, parent=None):
        super().__init__(parent)
        self.model_manager = model_manager
        self.settings_store = settings_store
        self.thread_pool = thread_pool
        self.release_active_model = release_active_model
        self.cards: dict[str, ModelCard] = {}
        self._installed_by_id: dict[str, dict] = {}
        self._installed_card_rows: list[tuple[QWidget, str]] = []
        self._downloads: dict[str, threading.Event] = {}
        self._download_task_ids: dict[str, str] = {}
        self._download_workers: dict[str, FunctionWorker] = {}
        self._downloads_refresh_pending = False
        self._downloads_refresh_again = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        layout.addWidget(page_header("Model library", "Discover compatible speech models from Hugging Face. Installation is explicit and pinned to a repository revision."))
        self.tabs = QTabWidget()
        discover = QWidget()
        discover_layout = QVBoxLayout(discover)
        controls = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search model name or publisher on Hugging Face…")
        self.search_input.returnPressed.connect(self.search_models)
        self.sort_combo = QComboBox()
        self.sort_combo.addItem("Most downloaded", "downloads")
        self.sort_combo.addItem("Most liked", "likes")
        self.sort_combo.addItem("Recently updated", "lastModified")
        search_button = primary_button("Search Hub")
        search_button.clicked.connect(self.search_models)
        curated_button = QPushButton("Curated models")
        curated_button.clicked.connect(self.load_curated)
        controls.addWidget(self.search_input, 1)
        controls.addWidget(self.sort_combo)
        controls.addWidget(search_button)
        controls.addWidget(curated_button)
        discover_layout.addLayout(controls)
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
        self.download_list = QListWidget()
        self.download_list.setAlternatingRowColors(True)
        downloads_layout.addWidget(self.download_list, 1)
        download_actions = QHBoxLayout()
        refresh_downloads = QPushButton("Refresh downloads")
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
        self.installed_summary.setStyleSheet("font-size: 15px; font-weight: 650;")
        self.installed_search = QLineEdit()
        self.installed_search.setPlaceholderText("Filter installed models…")
        self.installed_search.textChanged.connect(self._filter_installed_cards)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_installed)
        installed_toolbar.addWidget(self.installed_summary, 1)
        installed_toolbar.addWidget(self.installed_search, 1)
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
        form = QFormLayout()
        form.addRow("Local model ID", self.import_repo_id)
        import_layout.addLayout(form)
        requirements = QLabel(
            "Import accepts a local directory or ZIP containing root-level CTranslate2 Faster-Whisper "
            "artifacts: model.bin, config.json, tokenizer.json and a vocabulary file. "
            "PyTorch/Transformers checkpoints are not Faster-Whisper models."
        )
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

    def _choose_import_directory(self):
        source = QFileDialog.getExistingDirectory(
            self, "Import Faster-Whisper model directory", str(self.model_manager.registry.root)
        )
        if source:
            self._start_local_import(source, archive=False)

    def _choose_import_zip(self):
        source, _selected = QFileDialog.getOpenFileName(
            self, "Import model ZIP archive", str(self.model_manager.registry.root),
            "ZIP archives (*.zip)",
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
        self.import_status.setText(
            f"Validating and importing {source} as {repo_id}…"
        )

        def import_model(_emit):
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

    def search_models(self):
        query = self.search_input.text().strip()
        sort = self.sort_combo.currentData()
        self.discover_hint.setText("Searching Hugging Face…")
        self._clear_cards()
        worker = FunctionWorker(lambda _emit: self.model_manager.search(query, sort=sort, limit=30))
        worker.signals.result.connect(self._show_search_results)
        worker.signals.error.connect(lambda message: self.discover_hint.setText(f"Hub search failed: {message}"))
        self.thread_pool.start(worker)

    def _show_search_results(self, models):
        if not models:
            self.discover_hint.setText("No models were returned by the Hub search.")
            return
        for model in models:
            self._append_card(model)
        self.discover_hint.setText(f"{len(models)} live Hub result(s). Inspect a repository before installation.")

    def load_curated(self):
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
        worker = FunctionWorker(lambda _emit: self.model_manager.downloader.list_jobs())
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

    def _show_download_jobs(self, jobs):
        self.download_list.clear()
        rows = []
        active_states = {
            "queued", "inspecting", "downloading", "validating", "installing",
            "pausing", "stopping", "cancelling",
        }
        for job in jobs:
            state = str(job.get("state") or "unknown").casefold()
            repo_id = str(job.get("repo_id") or "Unknown repository")
            revision = str(job.get("revision") or "revision not pinned")
            downloaded = _human_size(job.get("downloaded_bytes") or 0)
            total = _human_size(job.get("total_bytes"))
            details = (
                f"{repo_id}  ·  {state.title()}  ·  {downloaded} / {total}  ·  "
                f"revision {revision[:12]}"
            )
            if job.get("error"):
                details += f"\n{job['error']}"
            item = QListWidgetItem()
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(10, 5, 10, 5)
            label = QLabel(details)
            label.setWordWrap(True)
            row_layout.addWidget(label, 1)

            if state in {"queued", "inspecting", "downloading"}:
                pause = QPushButton("Pause")
                pause.clicked.connect(
                    lambda _checked=False, rid=repo_id: self.pause_download(rid)
                )
                stop = QPushButton("Stop")
                stop.clicked.connect(
                    lambda _checked=False, rid=repo_id: self.stop_download(rid)
                )
                cancel = QPushButton("Cancel")
                cancel.clicked.connect(
                    lambda _checked=False, rid=repo_id: self.cancel_download(rid)
                )
                row_layout.addWidget(pause)
                row_layout.addWidget(stop)
                row_layout.addWidget(cancel)
            elif state in {"paused", "stopped", "failed"}:
                resume = QPushButton("Resume")
                resume.clicked.connect(
                    lambda _checked=False, current=job: self.resume_download(current)
                )
                row_layout.addWidget(resume)
            elif state == "cancelled":
                restart = QPushButton("Restart")
                restart.clicked.connect(
                    lambda _checked=False, current=job: self.restart_download(current)
                )
                row_layout.addWidget(restart)
            elif state in {"pausing", "stopping", "cancelling"}:
                pending = QLabel("Applying…")
                pending.setObjectName("Muted")
                row_layout.addWidget(pending)
            elif state in {"validating", "installing"}:
                pending = QLabel("Finishing atomic install…")
                pending.setObjectName("Muted")
                row_layout.addWidget(pending)

            item.setSizeHint(row.sizeHint())
            self.download_list.addItem(item)
            self.download_list.setItemWidget(item, row)
            rows.append(state)

        recoverable = sum(state in {"paused", "stopped", "failed"} for state in rows)
        active = any(state in active_states for state in rows)
        downloads_index = self.tabs.indexOf(self.download_tab)
        if downloads_index >= 0:
            self.tabs.setTabText(
                downloads_index,
                f"Downloads · {recoverable} ready" if recoverable else "Downloads",
            )
        if not jobs:
            self.downloads_hint.setText(
                "No download tasks yet. Inspect a compatible Hub repository and choose Install model."
            )
        else:
            self.downloads_hint.setText(
                f"{len(jobs)} saved download task(s) · {recoverable} ready to resume · "
                "Interrupted transfers never restart automatically."
            )
        if self.tabs.currentWidget() is self.download_tab and active:
            self.downloads_refresh_timer.start()
        else:
            self.downloads_refresh_timer.stop()

    def pause_download(self, repo_id: str):
        if self.model_manager.downloader.pause(repo_id):
            self.status_message.emit(f"Pausing {repo_id} at the next safe transfer boundary…")
            self.refresh_downloads()

    def stop_download(self, repo_id: str):
        if self.model_manager.downloader.stop(repo_id):
            self.status_message.emit(f"Stopping {repo_id}; cached data will be retained.")
            self.refresh_downloads()

    def cancel_download(self, repo_id: str):
        event = self._downloads.get(repo_id)
        if not event:
            return
        answer = QMessageBox.question(
            self,
            "Cancel model download?",
            f"Cancel the download for {repo_id}? Reusable data in the shared Hugging Face cache will be retained.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        event.set()
        if self.model_manager.downloader.cancel(repo_id):
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
        if not model.revision:
            QMessageBox.warning(self, "Revision unavailable", "The Hub did not provide a commit revision. This repository cannot be installed reproducibly.")
            return
        answer = QMessageBox.question(
            self, "Install model",
            f"Download {repo_id} from Hugging Face?\n\nRevision: {model.revision}\nLicense: {model.license or 'Not provided'}\n\nThe repository will be validated before it is marked installed. Review the model card and its license before continuing.",
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
        }
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
        self.status_message.emit(f"Model installed: {repo_id}")

    def _download_failed(self, repo_id, task_id, message):
        card = self.cards.get(repo_id)
        job = None
        repository = self.model_manager.downloader.job_repository
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
            card.install_button.setText("Install model")
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
        for row in range(100):
            self.installed_cards.setRowStretch(row, 0)
        while self.installed_cards.count() > 0:
            item = self.installed_cards.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _sync_discover_install_states(self):
        for repo_id, card in self.cards.items():
            card.set_installed(self._installed_by_id.get(repo_id))

    def _filter_installed_cards(self, query):
        needle = str(query or "").strip().casefold()
        for card, searchable in self._installed_card_rows:
            card.setVisible(not needle or needle in searchable)

    def _show_installed_models(self, installed):
        self._clear_installed_cards()
        self._installed_by_id = {item["repo_id"]: item for item in installed}
        self._sync_discover_install_states()
        count = len(installed)
        self.installed_summary.setText(
            f"{count} installed model{'s' if count != 1 else ''}"
        )
        if not installed:
            empty = QLabel("No compatible local models are registered yet. Install one from Discover or import a model.")
            empty.setObjectName("Muted")
            empty.setWordWrap(True)
            self.installed_cards.addWidget(empty, 0, 0, 1, 2)
            return

        default_model = self.settings_store.settings.default_model
        for index, model in enumerate(installed):
            card = Card()
            card.setMinimumWidth(300)
            layout = QVBoxLayout(card)
            layout.setContentsMargins(16, 14, 16, 14)
            layout.setSpacing(9)

            top = QHBoxLayout()
            title = QLabel(model["repo_id"])
            title.setStyleSheet("font-size: 14px; font-weight: 700;")
            title.setWordWrap(True)
            top.addWidget(title, 1)

            state = "ACTIVE" if model["active"] else "INSTALLED"
            state_color = "#36a47e" if model["compatible"] else "#d49a42"
            if not model["compatible"]:
                state = "REPAIR NEEDED"
            state_label = QLabel(state)
            state_label.setStyleSheet(
                f"font-size: 9px; font-weight: 750; color: {state_color}; "
                "padding: 4px 7px; border: 1px solid "
                f"{state_color}; border-radius: 7px;"
            )
            top.addWidget(state_label, 0, Qt.AlignTop)
            layout.addLayout(top)

            if model["repo_id"] == default_model:
                default_label = QLabel("★  DEFAULT FOR NEW TRANSCRIPTIONS")
                default_label.setStyleSheet(
                    "font-size: 9px; font-weight: 700; color: #75a7ff; "
                    "padding: 4px 7px; border-radius: 6px; "
                    "background: rgba(117, 167, 255, 0.12);"
                )
                layout.addWidget(default_label)

            revision = str(model.get("revision") or "Unknown")
            info = QLabel(
                f"Faster-Whisper / CTranslate2  ·  {_human_size(model.get('size_bytes'))}\n"
                f"Revision: {revision[:16]}{'…' if len(revision) > 16 else ''}"
            )
            info.setObjectName("Muted")
            info.setWordWrap(True)
            layout.addWidget(info)

            path_label = QLabel(str(model["path"]))
            path_label.setObjectName("Muted")
            path_label.setWordWrap(True)
            path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            path_label.setToolTip(str(model["path"]))
            layout.addWidget(path_label)

            compatibility = QLabel(
                model.get("compatibility_message") or "Model files validated and ready to use."
            )
            compatibility.setObjectName("Muted")
            compatibility.setWordWrap(True)
            layout.addWidget(compatibility)

            actions = QHBoxLayout()
            actions.setSpacing(6)
            open_button = QPushButton("Open folder")
            open_button.clicked.connect(
                lambda _=False, p=model["path"]: QDesktopServices.openUrl(QUrl.fromLocalFile(p))
            )
            default_button = QPushButton("★ Default" if model["repo_id"] == default_model else "Set default")
            default_button.setEnabled(model["compatible"] and model["repo_id"] != default_model)
            default_button.clicked.connect(
                lambda _=False, rid=model["repo_id"]: self.set_default_model(rid)
            )
            load_button = QPushButton("Unload" if model["active"] else "Load")
            load_button.setEnabled(model["compatible"])
            load_button.clicked.connect(
                lambda _=False, rid=model["repo_id"], active=model["active"]:
                self.release_active_model() if active else self.load_model(rid)
            )
            delete_button = QPushButton("Delete")
            delete_button.setObjectName("Danger")
            delete_button.setEnabled(not model["active"])
            delete_button.clicked.connect(
                lambda _=False, rid=model["repo_id"]: self.delete_model(rid)
            )
            actions.addWidget(open_button)
            actions.addWidget(default_button)
            actions.addWidget(load_button)
            actions.addStretch(1)
            actions.addWidget(delete_button)
            layout.addLayout(actions)

            row, column = divmod(index, 2)
            self.installed_cards.addWidget(card, row, column)
            searchable = " ".join((
                model["repo_id"], str(model.get("revision") or ""),
                str(model.get("path") or ""),
            )).casefold()
            self._installed_card_rows.append((card, searchable))

        self.installed_cards.setRowStretch((count + 1) // 2, 1)
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
            self.status_message.emit(f"Model deleted: {repo_id}")
        except Exception as exc:
            QMessageBox.warning(self, "Cannot delete model", str(exc))
