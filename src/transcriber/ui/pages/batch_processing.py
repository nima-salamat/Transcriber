"""Sequential resource-aware batch transcription queue.

The current Faster-Whisper manager owns a single loaded model, therefore this
page deliberately processes one file at a time rather than promising unsafe
parallel inference or simultaneous model residency.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from transcriber.audio.imports import collect_media_paths
from transcriber.transcription.exporters import export_transcript
from transcriber.transcription.segments import TranscriptionOptions
from transcriber.transcription.service import TranscriptionService
from transcriber.ui.widgets import Card, page_header, primary_button
from transcriber.ui.workers import FunctionWorker


class BatchProcessingPage(QWidget):
    status_message = Signal(str)
    open_transcript = Signal(str)

    AUDIO_FILTER = "Audio/video files (*.wav *.mp3 *.m4a *.aac *.flac *.ogg *.opus *.wma *.aiff *.aif *.mp4 *.m4v *.mkv *.mov *.webm *.avi)"

    def __init__(self, paths, settings_store, history, model_manager, thread_pool, parent=None):
        super().__init__(parent)
        self.paths = paths
        self.settings_store = settings_store
        self.history = history
        self.model_manager = model_manager
        self.thread_pool = thread_pool
        self.queue: list[dict] = []
        self._import_feedback = ""
        self._active_index: int | None = None
        self._cancel_event: threading.Event | None = None
        self._paused = False
        self._running = False
        self._worker = None
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)
        root.addWidget(page_header("Batch Processing", "Queue multiple files and process them safely with a single shared ASR model."))

        card = Card()
        controls = QVBoxLayout(card)
        row = QHBoxLayout()
        self.add_files_button = QPushButton("Add files")
        self.add_files_button.clicked.connect(self.add_files)
        self.add_folder_button = QPushButton("Add folder")
        self.add_folder_button.clicked.connect(self.add_folder)
        self.model_combo = QComboBox()
        for model in self.model_manager.installed(include_sizes=False):
            if model.get("compatible"):
                self.model_combo.addItem(model["repo_id"], model["repo_id"])
        row.addWidget(self.add_files_button)
        row.addWidget(self.add_folder_button)
        row.addWidget(QLabel("Model"))
        row.addWidget(self.model_combo, 1)
        controls.addLayout(row)
        row2 = QHBoxLayout()
        self.start_button = primary_button("Start queue")
        self.start_button.clicked.connect(self.start_queue)
        self.pause_button = QPushButton("Pause after current")
        self.pause_button.setToolTip("Finish the current file, then hold the queue until resumed.")
        self.pause_button.clicked.connect(self.toggle_pause)
        self.pause_button.setEnabled(False)
        self.cancel_button = QPushButton("Cancel current")
        self.cancel_button.clicked.connect(self.cancel_current)
        self.cancel_button.setEnabled(False)
        self.stop_queue_button = QPushButton("Stop queue")
        self.stop_queue_button.clicked.connect(self.stop_queue)
        self.stop_queue_button.setEnabled(False)
        self.retry_button = QPushButton("Retry failed")
        self.retry_button.clicked.connect(self.retry_failed)
        self.export_button = QPushButton("Export completed…")
        self.export_button.clicked.connect(self.export_all)
        for button in (self.start_button, self.pause_button, self.cancel_button,
                       self.stop_queue_button, self.retry_button, self.export_button):
            row2.addWidget(button)
        row2.addStretch(1)
        controls.addLayout(row2)
        root.addWidget(card)

        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)
        root.addWidget(self.list, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        root.addWidget(self.progress)
        self.summary = QLabel("No files queued")
        self.summary.setObjectName("Muted")
        root.addWidget(self.summary)

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add media files", str(self.paths.recordings), self.AUDIO_FILTER + ";;All files (*)")
        self._add_paths(files)

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Add folder", str(self.paths.recordings))
        if not folder:
            return
        suffixes = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aiff", ".aif", ".mp4", ".m4v", ".mkv", ".mov", ".webm", ".avi"}
        paths = [str(item) for item in sorted(Path(folder).rglob("*")) if item.is_file() and item.suffix.casefold() in suffixes]
        self._add_paths(paths)

    def _add_paths(self, paths):
        return self.add_paths(paths)

    def add_paths(self, paths):
        existing = [item["path"] for item in self.queue if item["status"] != "Rejected"]
        report = collect_media_paths(paths, existing_paths=existing)
        for path in report.accepted:
            self.queue.append({
                "path": str(path), "status": "Queued", "progress": 0,
                "result": None, "error": None,
            })
        for raw, reason in report.rejected:
            self.queue.append({
                "path": str(raw), "status": "Rejected", "progress": 0,
                "result": None, "error": reason,
            })
        self._import_feedback = (
            f"Last import: {len(report.accepted)} accepted · {len(report.rejected)} rejected · "
            f"{len(report.duplicates)} duplicate(s) ignored"
        )
        self.refresh()
        if paths:
            details = [f"{Path(raw).name}: {reason}" for raw, reason in report.rejected[:4]]
            message = self._import_feedback
            if details:
                message += " · " + " | ".join(details)
            self.status_message.emit(message)
        return report

    def refresh(self):
        self.list.clear()
        for item in self.queue:
            title = f"{Path(item['path']).name}   ·   {item['status']}"
            if item["error"]:
                title += f" — {item['error']}"
            row = QListWidgetItem(title)
            row.setToolTip(item["path"])
            self.list.addItem(row)
        complete = sum(item["status"] == "Completed" for item in self.queue)
        failed = sum(item["status"] == "Failed" for item in self.queue)
        rejected = sum(item["status"] == "Rejected" for item in self.queue)
        pending = sum(item["status"] in {"Queued", "Transcribing", "Cancelled"} for item in self.queue)
        summary = f"{len(self.queue)} entries · {complete} completed · {failed} failed · {pending} pending · {rejected} rejected"
        if self._import_feedback:
            summary += f" · {self._import_feedback}"
        self.summary.setText(summary)
        self.start_button.setEnabled(not self._running and any(item["status"] == "Queued" for item in self.queue) and bool(self.model_combo.currentData()))
        self.retry_button.setEnabled(not self._running and failed > 0)

    def start_queue(self):
        if not self.model_combo.currentData():
            QMessageBox.information(self, "Model required", "Install a compatible Faster-Whisper model before starting the batch queue.")
            return
        self._paused = False
        self._running = True
        self.pause_button.setText("Pause after current")
        self.pause_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.stop_queue_button.setEnabled(True)
        self._start_next()

    def _start_next(self):
        if not self._running or self._paused:
            return
        next_index = next((index for index, item in enumerate(self.queue) if item["status"] == "Queued"), None)
        if next_index is None:
            self._running = False
            self._active_index = None
            self.pause_button.setEnabled(False)
            self.cancel_button.setEnabled(False)
            self.stop_queue_button.setEnabled(False)
            self.progress.setValue(100)
            self.refresh()
            self.status_message.emit("Batch queue finished")
            return
        self._active_index = next_index
        item = self.queue[next_index]
        item["status"] = "Transcribing"
        self._cancel_event = threading.Event()
        self.refresh()
        configured = self.settings_store.settings
        repo_id = self.model_combo.currentData()
        options = TranscriptionOptions(
            language=None if configured.default_language == "auto" else configured.default_language,
            beam_size=configured.beam_size, vad_filter=configured.vad_filter,
            word_timestamps=configured.word_timestamps,
        )
        cancel_event = self._cancel_event

        def run(emit):
            engine = self.model_manager.get_engine(repo_id, configured)
            service = TranscriptionService(engine, self.history)
            result = service.transcribe(
                Path(item["path"]), options, cancel_event=cancel_event,
                progress=lambda percent, message: emit((percent, message)),
                title=Path(item["path"]).stem, model_id=repo_id,
            )
            return result

        worker = FunctionWorker(run)
        self._worker = worker
        worker.signals.progress.connect(self._on_progress)
        worker.signals.result.connect(self._on_result)
        worker.signals.error.connect(self._on_error)
        worker.signals.finished.connect(self._on_finished)
        self.thread_pool.start(worker)

    def _on_progress(self, value):
        percent, message = value
        self.progress.setValue(int(percent))
        self.status_message.emit(str(message))

    def _on_result(self, result):
        if self._active_index is None:
            return
        item = self.queue[self._active_index]
        item["status"] = "Completed"
        item["result"] = result
        item["progress"] = 100
        self.refresh()
        self.status_message.emit(f"Completed {Path(item['path']).name}")

    def _on_error(self, message):
        if self._active_index is None:
            return
        item = self.queue[self._active_index]
        if self._cancel_event and self._cancel_event.is_set():
            item["status"] = "Cancelled"
            item["error"] = None
        else:
            item["status"] = "Failed"
            item["error"] = str(message)
        self.refresh()
        self.status_message.emit(f"Batch item: {message}")

    def _on_finished(self):
        self._worker = None
        self._cancel_event = None
        self._active_index = None
        if self._running and not self._paused:
            self._start_next()
        else:
            if not self._running:
                self.pause_button.setEnabled(False)
                self.cancel_button.setEnabled(False)
                self.stop_queue_button.setEnabled(False)
            self.refresh()

    def toggle_pause(self):
        self._paused = not self._paused
        self.pause_button.setText("Resume queue" if self._paused else "Pause after current")
        if not self._paused and not self._worker:
            self._start_next()
        self.status_message.emit("Queue will pause after the current file" if self._paused else "Batch queue resumed")

    def cancel_current(self):
        if self._cancel_event:
            self._cancel_event.set()
            self.cancel_button.setEnabled(False)
            self.status_message.emit("Cancelling current batch item; the queue will continue…")
        else:
            self._running = False
            self._paused = False
            self.refresh()

    def stop_queue(self):
        self._running = False
        self._paused = False
        if self._cancel_event:
            self._cancel_event.set()
            self.stop_queue_button.setEnabled(False)
            self.status_message.emit("Stopping batch queue after cancelling the active file…")
        else:
            self.pause_button.setEnabled(False)
            self.cancel_button.setEnabled(False)
            self.stop_queue_button.setEnabled(False)
            self.refresh()
            self.status_message.emit("Batch queue stopped")

    def retry_failed(self):
        for item in self.queue:
            if item["status"] in {"Failed", "Cancelled"}:
                item["status"] = "Queued"
                item["error"] = None
        self.refresh()
        self.start_queue()

    def export_all(self):
        completed = [item for item in self.queue if item["status"] == "Completed" and item["result"]]
        if not completed:
            QMessageBox.information(self, "No completed jobs", "Complete at least one transcription first.")
            return
        folder = QFileDialog.getExistingDirectory(self, "Export batch results", str(self.paths.data))
        if not folder:
            return
        output_dir = Path(folder)
        try:
            for item in completed:
                result = item["result"]
                target = output_dir / f"{Path(item['path']).stem}.srt"
                export_transcript(target, format="srt", text=result.text, segments=result.segments,
                                  title=target.stem, include_timestamps=True)
            self.status_message.emit(f"Exported {len(completed)} SRT file(s)")
        except Exception as exc:
            QMessageBox.critical(self, "Batch export failed", str(exc))

    def shutdown(self):
        self._running = False
        if self._cancel_event:
            self._cancel_event.set()
