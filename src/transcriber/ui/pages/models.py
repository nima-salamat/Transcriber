"""Live Hugging Face model discovery and locally installed model management."""

from __future__ import annotations

import threading
import uuid

from PySide6.QtCore import QTimer, QUrl, Signal, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
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
            self.install_button.setEnabled(True)
        else:
            self.compatibility.setText("Not compatible")
            self.compatibility.setStyleSheet("color: #d65a65; font-weight: 600;")
            self.install_button.setEnabled(False)
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
        self.detail_label.setText(
            f"Estimated download: {size_text}\nFiles: " + (", ".join(files) or "Not provided") +
            f"\n{report.reason}{missing}\nPinned revision: {metadata.revision or 'Unknown'}"
        )

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
            self.install_button.setEnabled(progress.state != "Installed" and bool(self.report and self.report.compatible))


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
        self._downloads: dict[str, threading.Event] = {}
        self._download_task_ids: dict[str, str] = {}
        self._download_workers: dict[str, FunctionWorker] = {}
        self._downloads_refresh_pending = False

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
        self.installed_scroll = QScrollArea()
        self.installed_scroll.setWidgetResizable(True)
        self.installed_container = QWidget()
        self.installed_cards = QVBoxLayout(self.installed_container)
        self.installed_cards.setContentsMargins(0, 4, 8, 4)
        self.installed_cards.setSpacing(10)
        self.installed_cards.addStretch(1)
        self.installed_scroll.setWidget(self.installed_container)
        installed_layout.addWidget(self.installed_scroll, 1)
        refresh = QPushButton("Refresh installed models")
        refresh.clicked.connect(self.refresh_installed)
        installed_layout.addWidget(refresh)
        self.tabs.addTab(installed, "Installed")
        layout.addWidget(self.tabs, 1)
        self.discover_hint.setText("Choose Curated models or search the Hub to fetch live repository metadata.")
        self.refresh_installed()
        self.refresh_downloads()

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
            card.compatibility.setText("Inspecting repository files…")
        worker = FunctionWorker(lambda _emit: self.model_manager.inspect(repo_id))
        worker.signals.result.connect(lambda result, rid=repo_id: self._inspection_result(rid, result))
        worker.signals.error.connect(lambda message, rid=repo_id: self._inspection_error(rid, message))
        self.thread_pool.start(worker)

    def _inspection_result(self, repo_id, result):
        card = self.cards.get(repo_id)
        if card:
            card.inspect_button.setEnabled(True)
            card.set_inspection(*result)

    def _inspection_error(self, repo_id, message):
        card = self.cards.get(repo_id)
        if card:
            card.inspect_button.setEnabled(True)
            card.compatibility.setText("Inspection failed")
            card.detail_label.setText(message)

    def _on_tab_changed(self, _index):
        if self.tabs.currentWidget() is self.download_tab:
            self.refresh_downloads()
        else:
            self.downloads_refresh_timer.stop()

    def refresh_downloads(self):
        if self._downloads_refresh_pending:
            return
        self._downloads_refresh_pending = True
        worker = FunctionWorker(lambda _emit: self.model_manager.downloader.list_jobs())
        worker.signals.result.connect(self._show_download_jobs)
        worker.signals.error.connect(self._show_download_jobs_error)
        worker.signals.finished.connect(self._downloads_refresh_finished)
        self.thread_pool.start(worker)

    def _downloads_refresh_finished(self):
        self._downloads_refresh_pending = False

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

            item.setSizeHint(row.sizeHint())
            self.download_list.addItem(item)
            self.download_list.setItemWidget(item, row)
            rows.append(state)

        recoverable = sum(state in {"paused", "stopped", "failed"} for state in rows)
        active = any(state in active_states for state in rows)
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
        self._downloads[repo_id] = event
        self._download_workers[repo_id] = worker
        self.thread_pool.start(worker)
        self.status_message.emit(f"Resuming {repo_id} at revision {str(job.get('revision') or '')[:12]}.")

    def restart_download(self, job: dict):
        repo_id = str(job.get("repo_id") or "")
        if not repo_id:
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
        self.installed_cards.insertWidget(0, QLabel("Inspecting installed models…"))
        worker = FunctionWorker(lambda _emit: self.model_manager.installed(include_sizes=True))
        worker.signals.result.connect(self._show_installed_models)
        worker.signals.error.connect(self._show_installed_error)
        self.thread_pool.start(worker)

    def _clear_installed_cards(self):
        while self.installed_cards.count() > 0:
            item = self.installed_cards.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.installed_cards.addStretch(1)

    def _show_installed_models(self, installed):
        self._clear_installed_cards()
        for model in installed:
            card = Card()
            layout = QVBoxLayout(card)
            layout.setContentsMargins(18, 14, 18, 14)
            title = QLabel(model["repo_id"])
            title.setStyleSheet("font-weight: 650; font-size: 15px;")
            status = "Active · protected" if model["active"] else "Installed"
            if not model["compatible"]:
                status = "Corrupted or incompatible · reinstall recommended"
            info = QLabel(
                f"{status} · {_human_size(model['size_bytes'])} · revision {model.get('revision') or 'Unknown'}\n"
                f"Location: {model['path']}\n{model.get('compatibility_message', '')}"
            )
            info.setObjectName("Muted")
            info.setWordWrap(True)
            actions = QHBoxLayout()
            open_button = QPushButton("Show files")
            open_button.clicked.connect(lambda _=False, p=model["path"]: QDesktopServices.openUrl(QUrl.fromLocalFile(p)))
            default_button = QPushButton("Set as default")
            default_button.setEnabled(self.settings_store.settings.default_model != model["repo_id"])
            default_button.clicked.connect(lambda _=False, rid=model["repo_id"]: self.set_default_model(rid))
            load_button = QPushButton("Unload" if model["active"] else "Load model")
            load_button.clicked.connect(lambda _=False, rid=model["repo_id"], active=model["active"]:
                                        self.release_active_model() if active else self.load_model(rid))
            delete_button = QPushButton("Delete model")
            delete_button.setObjectName("Danger")
            delete_button.setEnabled(not model["active"])
            delete_button.clicked.connect(lambda _=False, rid=model["repo_id"]: self.delete_model(rid))
            actions.addWidget(open_button)
            actions.addWidget(default_button)
            actions.addWidget(load_button)
            actions.addStretch(1)
            actions.addWidget(delete_button)
            layout.addWidget(title)
            layout.addWidget(info)
            layout.addLayout(actions)
            self.installed_cards.addWidget(card)
        self.installed_cards.addStretch(1)

    def _show_installed_error(self, message):
        self._clear_installed_cards()
        self.installed_cards.insertWidget(0, QLabel(f"Could not inspect installed models: {message}"))

    def set_default_model(self, repo_id: str):
        self.settings_store.update(default_model=repo_id)
        self.default_model_changed.emit(repo_id)
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
