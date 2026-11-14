"""Import, offline transcription, playback, transcript editing and export."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from transcriber.audio.decoder import decoder_help, validate_audio_file
from transcriber.audio.player import AudioPlayer
from transcriber.editor.commands import CommandHistory
from transcriber.editor.document import TranscriptDocument
from transcriber.engines.base import TranscriptionEngine
from transcriber.transcription.exporters import export_transcript
from transcriber.transcription.segments import (
    TranscriptionOptions,
    TranscriptSegment,
    reconcile_segments,
)
from transcriber.transcription.service import TranscriptionService
from transcriber.ui.widgets import Card, page_header, primary_button
from transcriber.ui.workers import FunctionWorker


class TranscriptionPage(QWidget):
    status_message = Signal(str)
    audio_changed = Signal(str)
    transcript_changed = Signal(object, str, str, float, str)
    segments_edited = Signal(object)

    def __init__(self, paths, settings_store, history, model_manager, thread_pool, parent=None, *, document=None, command_history=None):
        super().__init__(parent)
        self.paths = paths
        self.settings_store = settings_store
        self.history = history
        self.model_manager = model_manager
        self.thread_pool = thread_pool
        self.document = document or TranscriptDocument()
        self.command_history = command_history or CommandHistory(self.document)
        if self.command_history.document is not self.document:
            raise ValueError("TranscriptionPage and CommandHistory must share the same TranscriptDocument")
        self._pending_text_undo_snapshot = None
        self.audio_path: Path | None = None
        self.segments = []
        self.transcript_id: str | None = None
        self.engine: TranscriptionEngine | None = None
        self.cancel_event: threading.Event | None = None
        self._job_engine_id: str | None = None
        self._segment_ranges: list[tuple[int, int, TranscriptSegment]] = []
        self._loading_text = False
        self._record_metadata: dict | None = None
        self._editor_base_text = ""
        self._save_inflight = False
        self._save_queue: list[dict] = []
        self._load_generation = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        layout.addWidget(page_header("New transcription", "Choose a local or explicitly consented cloud recognition engine for each job."))

        source_card = Card()
        source_layout = QHBoxLayout()
        source_layout.setContentsMargins(16, 14, 16, 14)
        self.file_name = QLabel("No audio selected")
        self.file_name.setObjectName("Muted")
        self.open_button = QPushButton("Choose audio file")
        self.open_button.clicked.connect(self.choose_audio)
        self.engine_combo = QComboBox()
        self.engine_combo.addItem("Faster-Whisper · Local", "faster-whisper")
        self.engine_combo.addItem("Google Cloud STT V2 · Online", "google-cloud")
        self.engine_combo.setCurrentIndex(max(0, self.engine_combo.findData(self.settings_store.settings.default_engine)))
        self.engine_combo.currentIndexChanged.connect(self._update_engine_controls)
        source_layout.addWidget(self.open_button)
        source_layout.addWidget(self.file_name, 1)
        source_layout.addWidget(QLabel("Engine"))
        source_layout.addWidget(self.engine_combo)

        recognition_options = QHBoxLayout()
        self.model_combo = QComboBox()
        self.refresh_models()
        self.language_combo = QComboBox()
        self.language_combo.addItem("Auto detect (local engines)", "auto")
        for code, name in [("en", "English"), ("fa", "Persian"), ("de", "German"),
                           ("fr", "French"), ("es", "Spanish"), ("ar", "Arabic"),
                           ("ru", "Russian"), ("zh", "Chinese"), ("ja", "Japanese")]:
            self.language_combo.addItem(name, code)
        self.beam_spin = QSpinBox()
        self.beam_spin.setRange(1, 20)
        self.beam_spin.setValue(self.settings_store.settings.beam_size)
        self.vad_check = QCheckBox("Voice activity detection")
        self.vad_check.setChecked(self.settings_store.settings.vad_filter)
        recognition_options.addWidget(QLabel("Model"))
        recognition_options.addWidget(self.model_combo, 2)
        recognition_options.addWidget(QLabel("Language"))
        recognition_options.addWidget(self.language_combo)
        recognition_options.addWidget(QLabel("Beam"))
        recognition_options.addWidget(self.beam_spin)
        recognition_options.addWidget(self.vad_check)

        advanced_options = QHBoxLayout()
        self.task_combo = QComboBox()
        self.task_combo.addItem("Transcribe in source language", "transcribe")
        self.task_combo.addItem("Translate to English", "translate")
        self.word_timestamps = QCheckBox("Word timings")
        self.word_timestamps.setChecked(self.settings_store.settings.word_timestamps)
        self.word_timestamps.toggled.connect(lambda value: self.settings_store.update(word_timestamps=value))
        self.initial_prompt = QLineEdit()
        self.initial_prompt.setPlaceholderText("Whisper initial prompt (local engine only)…")
        self.initial_prompt.setToolTip("This setting is supported by Faster-Whisper, not Google Cloud Speech-to-Text V2.")
        advanced_options.addWidget(QLabel("Task"))
        advanced_options.addWidget(self.task_combo)
        advanced_options.addWidget(self.word_timestamps)
        advanced_options.addWidget(self.initial_prompt, 1)
        self.engine_privacy_hint = QLabel()
        self.engine_privacy_hint.setObjectName("Muted")
        self.engine_privacy_hint.setWordWrap(True)
        source_outer = QVBoxLayout(source_card)
        source_outer.addLayout(source_layout)
        source_outer.addLayout(recognition_options)
        source_outer.addLayout(advanced_options)
        source_outer.addWidget(self.engine_privacy_hint)
        layout.addWidget(source_card)

        player_card = Card()
        player_layout = QHBoxLayout(player_card)
        player_layout.setContentsMargins(16, 10, 16, 10)
        self.player = AudioPlayer(self)
        self.play_button = QPushButton("▶")
        self.play_button.setFixedWidth(42)
        self.play_button.clicked.connect(self.player.play_pause)
        self.player.playback_changed.connect(lambda playing: self.play_button.setText("Ⅱ" if playing else "▶"))
        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.sliderMoved.connect(self.player.seek)
        self.player.position_changed.connect(self._position_changed)
        self.player.duration_changed.connect(self._duration_changed)
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setObjectName("Muted")
        self.speed_combo = QComboBox()
        for speed in ("0.75×", "1.0×", "1.25×", "1.5×", "2.0×"):
            self.speed_combo.addItem(speed, float(speed[:-1]))
        self.speed_combo.setCurrentIndex(1)
        self.speed_combo.currentIndexChanged.connect(lambda: self.player.set_speed(self.speed_combo.currentData()))
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(75)
        self.volume_slider.setMaximumWidth(100)
        self.volume_slider.valueChanged.connect(self.player.set_volume)
        player_layout.addWidget(self.play_button)
        player_layout.addWidget(self.seek_slider, 1)
        player_layout.addWidget(self.time_label)
        player_layout.addWidget(self.speed_combo)
        player_layout.addWidget(QLabel("Vol"))
        player_layout.addWidget(self.volume_slider)
        layout.addWidget(player_card)

        editor_card = Card()
        editor_layout = QVBoxLayout(editor_card)
        editor_layout.setContentsMargins(14, 12, 14, 12)
        editor_toolbar = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Find in transcript…")
        self.search_input.returnPressed.connect(self.find_next)
        self.find_button = QPushButton("Find next")
        self.find_button.clicked.connect(self.find_next)
        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText("Replace with…")
        self.replace_button = QPushButton("Replace selected")
        self.replace_button.clicked.connect(self.replace_selected)
        self.copy_button = QPushButton("Copy all")
        self.copy_button.clicked.connect(self.copy_all)
        editor_toolbar.addWidget(self.search_input, 2)
        editor_toolbar.addWidget(self.find_button)
        editor_toolbar.addWidget(self.replace_input, 1)
        editor_toolbar.addWidget(self.replace_button)
        editor_toolbar.addWidget(self.copy_button)
        editor_layout.addLayout(editor_toolbar)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("Your transcript will appear here. You can edit it at any time.")
        self.editor.setTabChangesFocus(True)
        self.editor.setUndoRedoEnabled(False)
        self.editor.textChanged.connect(self._schedule_autosave)
        editor_layout.addWidget(self.editor, 1)
        footer = QHBoxLayout()
        self.word_count = QLabel("0 words · 0 characters")
        self.word_count.setObjectName("Muted")
        self.include_timestamps = QCheckBox("Include timestamps when exporting")
        self.include_timestamps.setChecked(True)
        self.export_button = QPushButton("Export…")
        self.export_button.clicked.connect(self.export)
        footer.addWidget(self.word_count)
        footer.addStretch(1)
        footer.addWidget(self.include_timestamps)
        footer.addWidget(self.export_button)
        editor_layout.addLayout(footer)
        layout.addWidget(editor_card, 1)

        bottom = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        self.progress_label = QLabel("Ready")
        self.progress_label.setObjectName("Muted")
        self.start_button = primary_button("Start offline transcription")
        self.start_button.clicked.connect(self.start_transcription)
        self._update_engine_controls()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancel_transcription)
        bottom.addWidget(self.progress_label)
        bottom.addWidget(self.progress, 1)
        bottom.addWidget(self.cancel_button)
        bottom.addWidget(self.start_button)
        layout.addLayout(bottom)

        self.autosave_timer = QTimer(self)
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.setInterval(800)
        self.autosave_timer.timeout.connect(self._autosave)
        self.editor.textChanged.connect(self._update_word_count)
        self.player.position_changed.connect(self._sync_transcript_to_audio)
        self.player.error_occurred.connect(lambda message: self.status_message.emit(f"Audio player: {message}"))
        self._update_engine_controls()

    def _update_engine_controls(self, *_args):
        cloud_selected = self.engine_combo.currentData() == "google-cloud"
        self.model_combo.setEnabled(not cloud_selected)
        self.beam_spin.setEnabled(not cloud_selected)
        self.vad_check.setEnabled(not cloud_selected)
        self.task_combo.setEnabled(not cloud_selected)
        self.initial_prompt.setEnabled(not cloud_selected)
        if cloud_selected and self.task_combo.currentData() != "transcribe":
            self.task_combo.setCurrentIndex(self.task_combo.findData("transcribe"))
        if hasattr(self, "start_button"):
            self.start_button.setText("Send audio to Google Cloud" if cloud_selected else "Start offline transcription")
        self.engine_privacy_hint.setText(
            "Online processing: audio is sent to Google Cloud Speech-to-Text V2. A project ID, "
            "Application Default Credentials and explicit Cloud consent are required. Choose a specific language."
            if cloud_selected else
            "Local processing: Faster-Whisper runs on this device. Audio is not uploaded by this engine."
        )

    @property
    def segments(self) -> list[TranscriptSegment]:
        return self.document.segments

    @segments.setter
    def segments(self, values):
        self.document.replace_all(list(values or []))

    def refresh_models(self):
        selected = self.model_combo.currentData() if hasattr(self, "model_combo") else None
        self.model_combo.clear()
        installed = self.model_manager.installed(include_sizes=False)
        for model in installed:
            if model.get("compatible"):
                self.model_combo.addItem(model["repo_id"], model["repo_id"])
        preferred = self.settings_store.settings.default_model
        for index in range(self.model_combo.count()):
            if self.model_combo.itemData(index) in {selected, preferred}:
                self.model_combo.setCurrentIndex(index)
                break

    def choose_audio(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import audio", str(self.paths.recordings),
            "Media files (*.wav *.mp3 *.m4a *.aac *.flac *.ogg *.opus *.wma *.aiff *.aif *.mp4 *.mkv *.mov *.webm *.avi);;All files (*)",
        )
        if path:
            self.set_audio(path)

    def set_audio(self, path: str | Path):
        try:
            audio = validate_audio_file(Path(path))
        except Exception as exc:
            QMessageBox.warning(self, "Cannot import audio", f"{exc}\n\n{decoder_help()}")
            return
        if self.audio_path is not None and self.audio_path.resolve() != audio.resolve():
            self._autosave()
            self.command_history.clear()
            self._pending_text_undo_snapshot = None
            self.transcript_id = None
            self._record_metadata = None
            self.segments = []
            self._editor_base_text = ""
            self._loading_text = True
            self.editor.clear()
            self._loading_text = False
            self._rebuild_segment_ranges()
            self._update_word_count()
        self.audio_path = audio
        self.file_name.setText(audio.name)
        self.file_name.setToolTip(str(audio))
        self.player.set_source(str(audio))
        self.progress_label.setText("Audio ready")
        self.audio_changed.emit(str(audio))

    def start_transcription(self):
        if self.audio_path is None:
            self.choose_audio()
            if self.audio_path is None:
                return
        engine_id = self.engine_combo.currentData()
        repo_id = self.model_combo.currentData()
        configured = self.settings_store.settings
        cloud_selected = engine_id == "google-cloud"
        if not cloud_selected and not repo_id:
            QMessageBox.information(self, "Model required", "Install a compatible Faster-Whisper model in Model Library first.")
            return
        if cloud_selected:
            if configured.local_only or not configured.cloud_consent:
                QMessageBox.warning(
                    self, "Cloud recognition is disabled",
                    "Audio will be sent to Google Cloud. Disable Local-only mode and explicitly grant Cloud consent in Settings before starting this job.",
                )
                return
            if self.language_combo.currentData() == "auto":
                QMessageBox.information(
                    self, "Choose a Cloud language",
                    "Google Cloud Speech-to-Text V2 requires an explicit language for this workflow. Choose a language instead of Auto detect.",
                )
                return
        language = None if self.language_combo.currentData() == "auto" else self.language_combo.currentData()
        if cloud_selected:
            language = {
                "en": "en-US", "fa": "fa-IR", "de": "de-DE", "fr": "fr-FR",
                "es": "es-ES", "ar": "ar-SA", "ru": "ru-RU", "zh": "cmn-Hans-CN",
                "ja": "ja-JP",
            }.get(language, language)
        options = TranscriptionOptions(
            language=language,
            task="transcribe" if cloud_selected else self.task_combo.currentData(),
            beam_size=self.beam_spin.value(),
            vad_filter=self.vad_check.isChecked(),
            word_timestamps=self.word_timestamps.isChecked(),
            initial_prompt=self.initial_prompt.text().strip() or None,
        )
        changes = {"word_timestamps": self.word_timestamps.isChecked()}
        if not cloud_selected:
            changes.update(beam_size=self.beam_spin.value(), vad_filter=self.vad_check.isChecked(), default_model=repo_id)
        self.settings_store.update(**changes)
        audio_path = self.audio_path
        cancel_event = threading.Event()
        self.cancel_event = cancel_event
        self._job_engine_id = engine_id
        self.start_button.setEnabled(False)
        self.cancel_button.setVisible(True)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.progress_label.setText(
            "Preparing local recognition engine…" if not cloud_selected
            else "Preparing local audio chunks for Google Cloud…"
        )
        model_id = repo_id if not cloud_selected else None
        worker = FunctionWorker(lambda emit: self._run_transcription(
            emit, configured, engine_id, repo_id, audio_path, options, cancel_event, model_id
        ))
        worker.signals.progress.connect(self._on_progress)
        worker.signals.result.connect(self._on_transcription_complete)
        worker.signals.error.connect(self._on_transcription_error)
        worker.signals.finished.connect(self._finish_worker)
        self.thread_pool.start(worker)

    def _run_transcription(
        self, emit, configured, engine_id, repo_id, audio_path, options, cancel_event, model_id
    ):
        if cancel_event.is_set():
            raise InterruptedError("Transcription cancelled before engine preparation")
        if engine_id == "google-cloud":
            self.model_manager.unload_active()
            from transcriber.engines.cloud import GoogleCloudEngine
            engine = GoogleCloudEngine(
                consent_granted=True,
                project_id=configured.google_cloud_project or None,
                location=configured.google_cloud_location,
                model=configured.google_cloud_model,
            )
        else:
            engine = self.model_manager.get_engine(repo_id, configured)
        service = TranscriptionService(engine, self.history)
        try:
            result = service.transcribe(
                audio_path, options, cancel_event=cancel_event,
                progress=lambda percent, message: emit((percent, message)),
                title=Path(audio_path).stem, model_id=model_id,
            )
            return engine, result
        finally:
            if engine_id == "google-cloud":
                engine.unload()

    def cancel_transcription(self):
        if self.cancel_event:
            self.cancel_event.set()
            message = (
                "Cancellation requested · waiting for the current Google request"
                if self._job_engine_id == "google-cloud"
                else "Cancelling…"
            )
            self.progress_label.setText(message)
            self.cancel_button.setEnabled(False)

    def _on_progress(self, value):
        percent, message = value
        self.progress.setValue(int(percent))
        self.progress_label.setText(message)

    def _on_transcription_complete(self, outcome):
        self.engine, result = outcome
        self.command_history.clear()
        self._pending_text_undo_snapshot = None
        self.document.replace_all(result.segments, text=result.text)
        self.transcript_id = result.transcript_id
        self._record_metadata = {
            "title": self.audio_path.stem if self.audio_path else "Transcript",
            "source_path": str(self.audio_path) if self.audio_path else None,
            "engine": self.engine.engine_id if self.engine else "unknown",
            "model_id": self.model_combo.currentData() if self.engine and self.engine.engine_id == "faster-whisper" else None,
            "language": result.language,
            "duration": result.duration,
            "original_text": result.text,
            "tags": [],
            "favorite": False,
        }
        self._loading_text = True
        self.editor.setPlainText(result.text)
        self._loading_text = False
        self._editor_base_text = result.text
        self._rebuild_segment_ranges()
        self.progress_label.setText(
            f"Saved locally · {result.language or 'language unknown'} · {len(result.segments)} segments"
        )
        self.status_message.emit("Transcription completed and saved to History")
        self._update_word_count()
        self.transcript_changed.emit(list(self.segments), str(self.audio_path) if self.audio_path else "",
                                     result.language or "", result.duration, result.text)

    def _on_transcription_error(self, message: str):
        if self.cancel_event and self.cancel_event.is_set():
            self.progress_label.setText("Transcription cancelled")
            self.status_message.emit("Transcription cancelled")
            return
        self.progress_label.setText("Transcription failed")
        QMessageBox.critical(self, "Transcription failed", message)
        self.status_message.emit("Transcription failed")

    def _finish_worker(self):
        self._update_engine_controls()
        self.start_button.setEnabled(True)
        self.cancel_button.setVisible(False)
        self.cancel_button.setEnabled(True)
        self.progress.setVisible(False)
        if self.cancel_event and self.cancel_event.is_set():
            self.progress_label.setText("Transcription cancelled")
        self.cancel_event = None
        self._job_engine_id = None

    def _sync_editor_text_to_document(self):
        current = self.editor.toPlainText()
        if current == self._editor_base_text:
            return
        if self._pending_text_undo_snapshot is None:
            self._pending_text_undo_snapshot = self.command_history.snapshot()
        reconciled = (
            reconcile_segments(self._editor_base_text, current, self.segments)
            if self.segments else []
        )
        self.document.replace_all(reconciled, text=current)
        self._editor_base_text = current
        self._rebuild_segment_ranges()
        self.segments_edited.emit(list(self.segments))

    def _commit_pending_text_edit(self):
        snapshot, self._pending_text_undo_snapshot = self._pending_text_undo_snapshot, None
        if snapshot is not None:
            self.command_history.record_snapshot(snapshot)

    def _schedule_autosave(self):
        if self._loading_text:
            return
        self._sync_editor_text_to_document()
        self._update_word_count()
        self.autosave_timer.start()

    def _capture_save_snapshot(self) -> dict | None:
        self._sync_editor_text_to_document()
        if not self.transcript_id or not self._record_metadata:
            return None
        text = self.editor.toPlainText()
        if not text.strip():
            return None
        return {
            "transcript_id": self.transcript_id,
            "metadata": dict(self._record_metadata),
            "text": text,
            "segments": [
                TranscriptSegment(
                    start=item.start, end=item.end, text=item.text, speaker=item.speaker,
                    words=list(item.words or []), id=item.id, language=item.language,
                    metadata=dict(item.metadata), is_edited=item.is_edited, comment=item.comment,
                    bookmarked=item.bookmarked, locked=item.locked, reviewed=item.reviewed,
                ) for item in self.segments
            ],
        }

    def _persist_snapshot(self, snapshot: dict):
        metadata = snapshot["metadata"]
        return self.history.save(
            transcript_id=snapshot["transcript_id"], title=metadata["title"],
            text=snapshot["text"], segments=snapshot["segments"],
            source_path=metadata["source_path"], engine=metadata["engine"],
            model_id=metadata["model_id"], language=metadata["language"],
            duration=metadata["duration"], original_text=metadata["original_text"],
            tags=metadata["tags"], favorite=metadata["favorite"],
        )

    def _autosave(self):
        self._sync_editor_text_to_document()
        self._commit_pending_text_edit()
        snapshot = self._capture_save_snapshot()
        if snapshot is None:
            return
        if self._save_inflight:
            # Coalesce successive edits to the same project but keep snapshots
            # from the previous project when the user switches audio/history.
            if self._save_queue and self._save_queue[-1]["transcript_id"] == snapshot["transcript_id"]:
                self._save_queue[-1] = snapshot
            else:
                self._save_queue.append(snapshot)
            return
        self._start_save(snapshot)

    def _start_save(self, snapshot: dict):
        self._save_inflight = True
        worker = FunctionWorker(lambda _emit: self._persist_snapshot(snapshot))
        worker.signals.error.connect(self._autosave_error)
        worker.signals.finished.connect(self._autosave_finished)
        worker.signals.result.connect(lambda _result: self.status_message.emit("Changes saved"))
        self.thread_pool.start(worker)

    def _autosave_error(self, message: str):
        self.status_message.emit(f"Could not save transcript changes: {message}")

    def _autosave_finished(self):
        self._save_inflight = False
        if self._save_queue:
            self._start_save(self._save_queue.pop(0))

    def flush_autosave(self):
        """Persist queued edits and the current editor snapshot during shutdown.

        MainWindow calls this only after the Qt worker pool has drained, so a
        synchronous final flush cannot race a background SQLite write.
        """
        self.autosave_timer.stop()
        self._sync_editor_text_to_document()
        self._commit_pending_text_edit()
        current = self._capture_save_snapshot()
        if current:
            if self._save_queue and self._save_queue[-1]["transcript_id"] == current["transcript_id"]:
                self._save_queue[-1] = current
            else:
                self._save_queue.append(current)
        queued, self._save_queue = self._save_queue, []
        self._save_inflight = False
        for snapshot in queued:
            self._persist_snapshot(snapshot)

    def open_history_item(self, transcript_id: str):
        # Capture edits before an async history load changes the selected project.
        self._autosave()
        self._load_generation += 1
        generation = self._load_generation
        self.progress_label.setText("Loading transcript from local history…")
        worker = FunctionWorker(lambda _emit: self.history.get(transcript_id))
        worker.signals.result.connect(lambda record, g=generation: self._apply_history_record(g, record))
        worker.signals.error.connect(lambda message: self.status_message.emit(f"Could not open transcript: {message}"))
        self.thread_pool.start(worker)

    def _apply_history_record(self, generation: int, record):
        if generation != self._load_generation or not record:
            return
        self.transcript_id = record["id"]
        self._record_metadata = {
            "title": record["title"], "source_path": record["source_path"],
            "engine": record["engine"], "model_id": record["model_id"],
            "language": record["language"], "duration": record["duration"],
            "original_text": record["original_text"], "tags": record["tags"],
            "favorite": bool(record["favorite"]),
        }
        self.audio_path = (
            Path(record["source_path"]).expanduser().resolve()
            if record["source_path"] else None
        )
        # History loading must not call set_audio(): that user-import path
        # intentionally saves and clears the current draft, whereas this
        # record is already the new project. Calling it here could persist the
        # previous editor text under the newly assigned transcript ID.
        self.player.player.stop()
        self._audio_duration_ms = 0
        if self.audio_path and self.audio_path.is_file():
            self.file_name.setText(self.audio_path.name)
            self.file_name.setToolTip(str(self.audio_path))
            self.player.set_source(str(self.audio_path))
            self.audio_changed.emit(str(self.audio_path))
        else:
            self.file_name.setText("Source audio is unavailable")
            self.file_name.setToolTip(str(self.audio_path) if self.audio_path else "")
            self.player.player.setSource(QUrl())
            self.audio_changed.emit("")
        self.document.replace_all(
            [TranscriptSegment(**item) for item in record["segments"]],
            text=record["text"],
        )
        self.command_history.clear()
        self._pending_text_undo_snapshot = None
        self._loading_text = True
        self.editor.setPlainText(record["text"])
        self._loading_text = False
        self._editor_base_text = record["text"]
        self._rebuild_segment_ranges()
        self._update_word_count()
        self.progress_label.setText("Transcript loaded · edits auto-save")
        self.transcript_changed.emit(list(self.segments), str(self.audio_path) if self.audio_path else "",
                                     record.get("language") or "", float(record.get("duration") or 0.0),
                                     record.get("original_text") or record.get("text") or "")

    def _rebuild_segment_ranges(self):
        self._segment_ranges = []
        content = self.editor.toPlainText()
        cursor = 0
        for segment in self.segments:
            segment_text = segment.text.strip()
            start = content.find(segment_text, cursor)
            if start < 0:
                continue
            end = start + len(segment_text)
            self._segment_ranges.append((start, end, segment))
            cursor = end

    def _position_changed(self, position: int):
        self.seek_slider.blockSignals(True)
        self.seek_slider.setValue(position)
        self.seek_slider.blockSignals(False)

    def _duration_changed(self, duration: int):
        self.seek_slider.setRange(0, max(0, duration))
        self._update_time_label(self.player.player.position(), duration)

    def _update_time_label(self, position: int, duration: int):
        def clock(value):
            seconds = max(0, int(value / 1000))
            return f"{seconds // 60:02}:{seconds % 60:02}"
        self.time_label.setText(f"{clock(position)} / {clock(duration)}")

    def _sync_transcript_to_audio(self, position: int):
        ms = position / 1000
        current = next((entry for entry in self._segment_ranges
                        if entry[2].start <= ms <= entry[2].end), None)
        if current:
            cursor = self.editor.textCursor()
            cursor.setPosition(current[0])
            cursor.setPosition(current[1], cursor.KeepAnchor)
            self.editor.setTextCursor(cursor)
            self.editor.ensureCursorVisible()

    def _update_word_count(self):
        text = self.editor.toPlainText()
        words = len(text.split())
        self.word_count.setText(f"{words:,} words · {len(text):,} characters")

    def find_next(self):
        query = self.search_input.text()
        if not query:
            return
        if not self.editor.find(query):
            cursor = self.editor.textCursor()
            cursor.movePosition(cursor.Start)
            self.editor.setTextCursor(cursor)
            self.editor.find(query)

    def replace_selected(self):
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            cursor.insertText(self.replace_input.text())

    def copy_all(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.editor.toPlainText())
        self.status_message.emit("Transcript copied")

    def export(self):
        if not self.editor.toPlainText().strip():
            QMessageBox.information(self, "Nothing to export", "There is no transcript text yet.")
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Export transcript", str(self.paths.data / "transcript.txt"),
            "Text (*.txt);;Markdown (*.md);;SubRip subtitles (*.srt);;WebVTT (*.vtt);;JSON (*.json);;Word document (*.docx);;PDF (*.pdf)",
        )
        if not path:
            return
        extension_by_filter = {
            "Text (*.txt)": ".txt", "Markdown (*.md)": ".md",
            "SubRip subtitles (*.srt)": ".srt", "WebVTT (*.vtt)": ".vtt",
            "JSON (*.json)": ".json", "Word document (*.docx)": ".docx",
            "PDF (*.pdf)": ".pdf",
        }
        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(extension_by_filter.get(selected_filter, ".txt"))
        text = self.editor.toPlainText()
        segments = list(self.segments)
        include_timestamps = self.include_timestamps.isChecked()
        audio_path = str(self.audio_path) if self.audio_path else None
        model_id = self.model_combo.currentData()
        self.export_button.setEnabled(False)
        self.status_message.emit(f"Exporting {target.name}…")
        worker = FunctionWorker(lambda _emit: export_transcript(
            target, format=target.suffix, text=text, segments=segments,
            include_timestamps=include_timestamps, title=target.stem,
            metadata={"source": audio_path, "model": model_id},
        ))
        worker.signals.result.connect(lambda output: self._export_complete(output))
        worker.signals.error.connect(lambda message: QMessageBox.critical(self, "Export failed", message))
        worker.signals.finished.connect(lambda: self.export_button.setEnabled(True))
        self.thread_pool.start(worker)

    def _export_complete(self, path):
        self.status_message.emit(f"Exported {Path(path).name}")

    def shutdown(self):
        self.autosave_timer.stop()
        if self.cancel_event:
            self.cancel_event.set()
        self.player.shutdown()
