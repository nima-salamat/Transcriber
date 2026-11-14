"""Organized settings and local storage controls."""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox,
    QVBoxLayout, QWidget,
)

from transcriber.storage.backup import create_backup, restore_backup
from transcriber.ui.widgets import Card, page_header
from transcriber.ui.workers import FunctionWorker


class SettingsPage(QWidget):
    theme_changed = Signal(str)
    concurrency_changed = Signal(int)
    status_message = Signal(str)

    def __init__(self, paths, settings_store, database, thread_pool, model_manager, parent=None):
        super().__init__(parent)
        self.paths = paths
        self.settings_store = settings_store
        self.database = database
        self.thread_pool = thread_pool
        self.model_manager = model_manager
        self._workers: list[FunctionWorker] = []
        self._storage_worker: FunctionWorker | None = None
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.addWidget(page_header("Settings", "Tune recognition, privacy, and where Transcriber stores your data."))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setSpacing(14)
        current = self.settings_store.settings

        general = Card()
        form = QFormLayout(general)
        form.setContentsMargins(18, 16, 18, 16)
        self.theme = QComboBox()
        self.theme.addItem("Dark", "dark")
        self.theme.addItem("Light", "light")
        self.theme.addItem("System default (dark fallback)", "system")
        self.theme.setCurrentIndex(max(0, self.theme.findData(current.theme)))
        self.theme.currentIndexChanged.connect(self._theme_changed)
        form.addRow("Appearance", self.theme)
        self.language = QComboBox()
        self.language.addItem("English (currently the only built-in language)", "en")
        self.language.setCurrentIndex(max(0, self.language.findData(current.language)))
        self.language.currentIndexChanged.connect(lambda: self._save(language=self.language.currentData()))
        form.addRow("Application language", self.language)
        layout.addWidget(self._section("General", general))

        recognition = Card()
        recog_form = QFormLayout(recognition)
        recog_form.setContentsMargins(18, 16, 18, 16)
        self.engine = QComboBox()
        self.engine.addItem("Faster-Whisper (offline)", "faster-whisper")
        self.engine.addItem("Google Speech Recognition (online, optional)", "google-cloud")
        self.engine.setCurrentIndex(max(0, self.engine.findData(current.default_engine)))
        self.engine.currentIndexChanged.connect(lambda: self._save(default_engine=self.engine.currentData()))
        self.device = QComboBox()
        for label, value in (("Automatic", "auto"), ("CPU", "cpu"), ("CUDA GPU", "cuda")):
            self.device.addItem(label, value)
        self.device.setCurrentIndex(max(0, self.device.findData(current.device)))
        self.device.currentIndexChanged.connect(lambda: self._save(device=self.device.currentData()))
        self.compute = QComboBox()
        for value in ("int8", "int8_float16", "float16", "float32", "default"):
            self.compute.addItem(value, value)
        self.compute.setCurrentIndex(max(0, self.compute.findData(current.compute_type)))
        self.compute.currentIndexChanged.connect(lambda: self._save(compute_type=self.compute.currentData()))
        self.threads = QSpinBox()
        self.threads.setRange(0, 256)
        self.threads.setSpecialValueText("Automatic")
        self.threads.setValue(current.cpu_threads)
        self.threads.valueChanged.connect(lambda value: self._save(cpu_threads=value))
        self.beam = QSpinBox()
        self.beam.setRange(1, 20)
        self.beam.setValue(current.beam_size)
        self.beam.valueChanged.connect(lambda value: self._save(beam_size=value))
        self.vad = QCheckBox("Filter silence and non-speech regions")
        self.vad.setChecked(current.vad_filter)
        self.vad.toggled.connect(lambda value: self._save(vad_filter=value))
        self.word_timestamps = QCheckBox("Request word-level timestamps")
        self.word_timestamps.setChecked(current.word_timestamps)
        self.word_timestamps.toggled.connect(lambda value: self._save(word_timestamps=value))
        recog_form.addRow("Recognition engine", self.engine)
        recog_form.addRow("Compute device", self.device)
        recog_form.addRow("Compute type", self.compute)
        recog_form.addRow("CPU threads", self.threads)
        recog_form.addRow("Beam size", self.beam)
        recog_form.addRow("Voice activity detection", self.vad)
        recog_form.addRow("Word-level timestamps", self.word_timestamps)
        layout.addWidget(self._section("Recognition", recognition))

        jobs = Card()
        jobs_form = QFormLayout(jobs)
        jobs_form.setContentsMargins(18, 16, 18, 16)
        self.download_workers = QSpinBox()
        self.download_workers.setRange(1, 4)
        self.download_workers.setValue(current.download_concurrency)
        self.download_workers.valueChanged.connect(self._concurrency_changed)
        jobs_form.addRow("Concurrent background downloads", self.download_workers)
        layout.addWidget(self._section("Background jobs", jobs))

        privacy = Card()
        privacy_form = QFormLayout(privacy)
        privacy_form.setContentsMargins(18, 16, 18, 16)
        self.local_only = QCheckBox("Keep recognition local; do not use a cloud engine")
        self.local_only.setChecked(current.local_only)
        self.local_only.toggled.connect(lambda value: self._save(local_only=value))
        self.cloud_consent = QCheckBox("I understand that cloud recognition sends audio to Google for processing")
        self.cloud_consent.setChecked(current.cloud_consent)
        self.cloud_consent.toggled.connect(lambda value: self._save(cloud_consent=value))
        privacy_form.addRow("Local-only mode", self.local_only)
        privacy_form.addRow("Cloud consent", self.cloud_consent)
        note = QLabel("Telemetry is not implemented. The cloud adapter is never selected automatically and requires consent.")
        note.setWordWrap(True)
        note.setObjectName("Muted")
        privacy_form.addRow("Privacy", note)
        layout.addWidget(self._section("Privacy", privacy))

        storage = Card()
        storage_layout = QVBoxLayout(storage)
        storage_layout.setContentsMargins(18, 16, 18, 16)
        self.model_dir = self._path_row("Model directory", current.model_directory or str(self.paths.models), storage_layout)
        self.recording_dir = self._path_row("Recording directory", current.recording_directory or str(self.paths.recordings), storage_layout)
        apply_paths = QPushButton("Save storage locations (restart required)")
        apply_paths.clicked.connect(self._save_paths)
        storage_layout.addWidget(apply_paths)
        self.storage_usage = QLabel("Calculating storage usage…")
        self.storage_usage.setObjectName("Muted")
        storage_layout.addWidget(self.storage_usage)
        actions = QHBoxLayout()
        self.backup_button = QPushButton("Create metadata backup…")
        self.backup_button.clicked.connect(self._backup)
        self.restore_button = QPushButton("Restore metadata backup…")
        self.restore_button.clicked.connect(self._restore)
        self.clear_cache_button = QPushButton("Clear model cache")
        self.clear_cache_button.clicked.connect(self._clear_cache)
        for button in (self.backup_button, self.restore_button, self.clear_cache_button):
            actions.addWidget(button)
        storage_layout.addLayout(actions)
        layout.addWidget(self._section("Storage", storage))
        layout.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        self._refresh_storage_usage()

    @staticmethod
    def _section(title: str, content: QWidget) -> QWidget:
        outer = QWidget()
        layout = QVBoxLayout(outer)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(title)
        label.setStyleSheet("font-size: 16px; font-weight: 650; padding: 2px 0;")
        layout.addWidget(label)
        layout.addWidget(content)
        return outer

    def _path_row(self, label: str, value: str, parent_layout: QVBoxLayout) -> QLineEdit:
        row = QHBoxLayout()
        title = QLabel(label)
        title.setMinimumWidth(140)
        edit = QLineEdit(value)
        browse = QPushButton("Browse…")
        browse.clicked.connect(lambda: self._browse_directory(edit))
        row.addWidget(title)
        row.addWidget(edit, 1)
        row.addWidget(browse)
        parent_layout.addLayout(row)
        return edit

    def _browse_directory(self, edit: QLineEdit):
        path = QFileDialog.getExistingDirectory(self, "Choose directory", edit.text())
        if path:
            edit.setText(path)

    def _save(self, **changes):
        self.settings_store.update(**changes)
        self.status_message.emit("Settings saved")

    def _concurrency_changed(self, value: int):
        self._save(download_concurrency=value)
        self.concurrency_changed.emit(value)

    def _theme_changed(self):
        theme = self.theme.currentData()
        self._save(theme=theme)
        self.theme_changed.emit(theme)

    def _save_paths(self):
        model_dir = Path(self.model_dir.text()).expanduser()
        recording_dir = Path(self.recording_dir.text()).expanduser()
        if not model_dir.is_absolute() or not recording_dir.is_absolute():
            QMessageBox.warning(self, "Invalid path", "Storage locations must be absolute paths.")
            return
        try:
            model_dir.mkdir(parents=True, exist_ok=True)
            recording_dir.mkdir(parents=True, exist_ok=True)
            self._save(model_directory=str(model_dir.resolve()), recording_directory=str(recording_dir.resolve()))
            QMessageBox.information(self, "Restart required", "The new storage locations will be used after restarting Transcriber.")
        except OSError as exc:
            QMessageBox.warning(self, "Cannot use directory", str(exc))

    @staticmethod
    def _directory_size(path: Path) -> int:
        total = 0
        if path.exists():
            for item in path.rglob("*"):
                if item.is_file() and not item.is_symlink():
                    try:
                        total += item.stat().st_size
                    except OSError:
                        continue
        return total

    def _track_worker(self, worker: FunctionWorker, on_result, on_error):
        self._workers.append(worker)
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error)
        worker.signals.finished.connect(lambda current=worker: self._forget_worker(current))
        self.thread_pool.start(worker)

    def _forget_worker(self, worker: FunctionWorker):
        try:
            self._workers.remove(worker)
        except ValueError:
            pass

    def _refresh_storage_usage(self):
        paths = self.paths
        worker = FunctionWorker(lambda _emit: (
            self._directory_size(paths.models),
            self._directory_size(paths.recordings),
            paths.database.stat().st_size if paths.database.exists() else 0,
        ))
        self._storage_worker = worker
        self._track_worker(
            worker, self._show_storage_usage,
            lambda message: self.storage_usage.setText(f"Storage usage unavailable: {message}"),
        )

    def _show_storage_usage(self, usage):
        models, recordings, database = usage
        self.storage_usage.setText(
            f"Models: {models:,} bytes    ·    Recordings: {recordings:,} bytes    ·    Database: {database:,} bytes"
        )

    def _backup(self):
        path, _ = QFileDialog.getSaveFileName(self, "Create backup", "Transcriber-backup.zip", "Zip archive (*.zip)")
        if not path:
            return
        target = Path(path)
        self.backup_button.setEnabled(False)
        worker = FunctionWorker(lambda _emit: create_backup(self.database, self.settings_store.path, target))
        self._track_worker(
            worker,
            lambda output: QMessageBox.information(
                self, "Backup created", f"Metadata backup saved to {output}. Models and recordings are intentionally excluded."
            ),
            lambda message: QMessageBox.critical(self, "Backup failed", message),
        )
        worker.signals.finished.connect(lambda: self.backup_button.setEnabled(True))

    def _restore(self):
        path, _ = QFileDialog.getOpenFileName(self, "Restore backup", "", "Zip archive (*.zip)")
        if not path:
            return
        answer = QMessageBox.warning(
            self, "Replace local metadata",
            "This replaces the local transcript database and settings. Make a current backup first. Continue?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        source = Path(path)
        self.restore_button.setEnabled(False)
        worker = FunctionWorker(lambda _emit: restore_backup(source, self.paths.database, self.settings_store.path))
        self._track_worker(
            worker,
            lambda _result: QMessageBox.information(
                self, "Restore complete", "Restart Transcriber to reload restored settings and transcript history."
            ),
            lambda message: QMessageBox.critical(self, "Restore failed", message),
        )
        worker.signals.finished.connect(lambda: self.restore_button.setEnabled(True))

    def _clear_cache(self):
        answer = QMessageBox.question(
            self, "Clear cache",
            "Remove cached Hub downloads? This may make future model downloads take longer. Installed models are not deleted.",
        )
        if answer != QMessageBox.Yes:
            return
        if self.model_manager.active_downloads:
            QMessageBox.warning(self, "Downloads active", "Cancel or finish active model downloads before clearing the shared download cache.")
            return

        def clear(_emit):
            self.model_manager.clear_download_cache()
            return True

        self.clear_cache_button.setEnabled(False)
        worker = FunctionWorker(clear)
        self._track_worker(
            worker,
            lambda _result: (self.status_message.emit("Cache cleared"), self._refresh_storage_usage()),
            lambda message: QMessageBox.warning(self, "Cache cleanup failed", message),
        )
        worker.signals.finished.connect(lambda: self.clear_cache_button.setEnabled(True))
