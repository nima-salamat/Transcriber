"""Non-destructive FFmpeg audio cleanup workspace."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from transcriber.audio.processing import build_filter_chain, process_audio
from transcriber.ui.widgets import Card, page_header, primary_button, section_header, status_pill
from transcriber.ui.workers import FunctionWorker


class AudioCleanupPage(QWidget):
    status_message = Signal(str)
    open_cleaned_file = Signal(str)

    def __init__(self, paths, thread_pool, parent=None):
        super().__init__(parent)
        self.paths = paths
        self.thread_pool = thread_pool
        self.source: Path | None = None
        self._worker: FunctionWorker | None = None
        self._cancel_event = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(15)
        root.addWidget(page_header(
            "Audio cleanup",
            "Build a processing chain and render a new file. Your source recording is never overwritten.",
        ))

        workspace = QHBoxLayout()
        workspace.setSpacing(14)

        left_column = QVBoxLayout()
        left_column.setSpacing(12)
        source_panel = Card()
        source_panel.setObjectName("WorkspacePanel")
        source_layout = QVBoxLayout(source_panel)
        source_layout.setContentsMargins(16, 14, 16, 14)
        source_layout.setSpacing(10)
        source_layout.addWidget(section_header(
            "Source media",
            "Choose the recording that will pass through the processing chain.",
        ))
        source_row = QHBoxLayout()
        self.source_label = QLabel("No source media selected")
        self.source_label.setObjectName("CleanupSourceName")
        self.source_label.setWordWrap(True)
        choose = QPushButton("Choose file…")
        choose.clicked.connect(self.choose_source)
        source_row.addWidget(self.source_label, 1)
        source_row.addWidget(choose)
        source_layout.addLayout(source_row)
        self.source_path_hint = QLabel("Audio and video files with an audio track are supported.")
        self.source_path_hint.setObjectName("Muted")
        self.source_path_hint.setWordWrap(True)
        source_layout.addWidget(self.source_path_hint)
        left_column.addWidget(source_panel)

        options = Card()
        options.setObjectName("WorkspacePanel")
        options_layout = QVBoxLayout(options)
        options_layout.setContentsMargins(16, 14, 16, 15)
        options_layout.setSpacing(10)
        options_layout.addWidget(section_header(
            "Processing chain",
            "Enable only the filters you need. You can combine several operations.",
        ))
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(11)
        self.normalize = QCheckBox("Loudness normalization")
        self.normalize.setToolTip("EBU R128 target: -16 LUFS")
        self.denoise = QCheckBox("Spectral noise reduction")
        self.denoise.setToolTip("FFmpeg single-pass spectral denoise; no learned noise profile.")
        self.silence = QCheckBox("Remove silence")
        self.silence.setToolTip("Remove leading, trailing and detected internal silence.")
        self.highpass = QSpinBox()
        self.highpass.setRange(20, 1000)
        self.highpass.setValue(80)
        self.highpass.setSuffix(" Hz")
        self.highpass_enabled = QCheckBox("Enable")
        high_row = QHBoxLayout()
        high_row.addWidget(self.highpass_enabled)
        high_row.addWidget(self.highpass)
        high_row.addStretch(1)
        self.lowpass = QSpinBox()
        self.lowpass.setRange(1000, 20000)
        self.lowpass.setValue(12000)
        self.lowpass.setSuffix(" Hz")
        self.lowpass_enabled = QCheckBox("Enable")
        low_row = QHBoxLayout()
        low_row.addWidget(self.lowpass_enabled)
        low_row.addWidget(self.lowpass)
        low_row.addStretch(1)
        self.volume = QDoubleSpinBox()
        self.volume.setRange(-24, 24)
        self.volume.setDecimals(1)
        self.volume.setSuffix(" dB")
        self.volume.setSingleStep(1.0)
        self.volume.setValue(0)
        form.addRow("High-pass filter", high_row)
        form.addRow("Low-pass filter", low_row)
        form.addRow("Output gain", self.volume)
        form.addRow("Loudness", self.normalize)
        form.addRow("Noise", self.denoise)
        form.addRow("Silence", self.silence)
        options_layout.addLayout(form)
        left_column.addWidget(options, 1)
        workspace.addLayout(left_column, 3)

        output_panel = Card()
        output_panel.setObjectName("CleanupOutputPanel")
        output_layout = QVBoxLayout(output_panel)
        output_layout.setContentsMargins(17, 16, 17, 16)
        output_layout.setSpacing(12)
        output_layout.addWidget(section_header(
            "Output",
            "Processing creates a separate audio file that can be opened in the transcriber.",
        ))
        self.output_status = status_pill("Ready", "neutral")
        output_layout.addWidget(self.output_status, 0, Qt.AlignLeft)
        output_note = QLabel(
            "Original protected\nThe input file is never modified. Choose the destination and format when you render."
        )
        output_note.setObjectName("CleanupSafetyNote")
        output_note.setWordWrap(True)
        output_layout.addWidget(output_note)
        self.result_label = QLabel("Choose a source file and enable one or more operations.")
        self.result_label.setObjectName("CleanupResult")
        self.result_label.setWordWrap(True)
        self.result_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        output_layout.addWidget(self.result_label, 1)

        self.process_button = primary_button("Render cleaned file…")
        self.process_button.setObjectName("CleanupRenderButton")
        self.process_button.setMinimumHeight(40)
        self.process_button.clicked.connect(self.process)
        self.cancel_button = QPushButton("Cancel processing")
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.setEnabled(False)
        output_layout.addWidget(self.process_button)
        output_layout.addWidget(self.cancel_button)
        workspace.addWidget(output_panel, 2)
        root.addLayout(workspace, 1)

    def choose_source(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose audio/video source", str(self.paths.recordings),
            "Media files (*.wav *.mp3 *.m4a *.aac *.flac *.ogg *.opus *.wma *.aiff *.aif *.mp4 *.mkv *.mov *.webm *.avi *.m4v);;All files (*)",
        )
        if path:
            self.source = Path(path).resolve()
            self.source_label.setText(self.source.name)
            self.source_label.setToolTip(str(self.source))
            self.source_path_hint.setText(str(self.source.parent))
            self.output_status.setText("Source selected")
            self.output_status.setProperty("state", "info")
            self.output_status.style().unpolish(self.output_status)
            self.output_status.style().polish(self.output_status)

    def process(self):
        if self._worker:
            return
        if not self.source or not self.source.is_file():
            QMessageBox.information(self, "Source required", "Choose an existing audio/video file first.")
            return
        try:
            filters = build_filter_chain(
                normalize=self.normalize.isChecked(),
                highpass_hz=self.highpass.value() if self.highpass_enabled.isChecked() else None,
                lowpass_hz=self.lowpass.value() if self.lowpass_enabled.isChecked() else None,
                remove_silence=self.silence.isChecked(), denoise=self.denoise.isChecked(),
                volume_db=self.volume.value(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Invalid processing settings", str(exc))
            return
        if not filters:
            QMessageBox.information(self, "No operations selected", "Select at least one processing operation.")
            return
        default = self.source.with_name(self.source.stem + "-cleaned.wav")
        target_raw, _ = QFileDialog.getSaveFileName(self, "Save cleaned audio", str(default), "WAV audio (*.wav);;FLAC (*.flac);;MP3 (*.mp3);;M4A audio (*.m4a)")
        if not target_raw:
            return
        target = Path(target_raw).expanduser().resolve()
        if target.suffix.lower() not in {".wav", ".flac", ".mp3", ".m4a"}:
            target = target.with_suffix(".wav")
        if target == self.source:
            QMessageBox.warning(self, "Source protected", "Choose a different output file. The original is never overwritten.")
            return
        import threading
        self._cancel_event = threading.Event()
        cancel_event = self._cancel_event
        source = self.source
        self._set_busy(True)
        worker = FunctionWorker(lambda emit: process_audio(
            source, target, filters=filters, cancel_event=cancel_event,
            progress=lambda message: emit(message),
        ))
        self._worker = worker
        worker.signals.progress.connect(lambda message: self.result_label.setText(str(message)))
        worker.signals.result.connect(self._on_result)
        worker.signals.error.connect(self._on_error)
        worker.signals.finished.connect(self._on_finished)
        self.thread_pool.start(worker)
        self.status_message.emit(f"Cleaning {source.name}")

    def cancel(self):
        if self._cancel_event:
            self._cancel_event.set()
            self.cancel_button.setEnabled(False)
            self.result_label.setText("Cancellation requested…")

    def _set_busy(self, busy):
        self.process_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        if busy:
            self.output_status.setText("Processing")
            self.output_status.setProperty("state", "info")
            self.output_status.style().unpolish(self.output_status)
            self.output_status.style().polish(self.output_status)

    def _on_result(self, path):
        self.result_label.setText(f"Created new audio file:\n{path}")
        self.output_status.setText("Completed")
        self.output_status.setProperty("state", "success")
        self.output_status.style().unpolish(self.output_status)
        self.output_status.style().polish(self.output_status)
        self.open_cleaned_file.emit(str(path))
        self.status_message.emit(f"Audio cleanup completed: {Path(path).name}")

    def _on_error(self, message):
        if self._cancel_event and self._cancel_event.is_set():
            self.result_label.setText("Processing cancelled. Source file was not modified.")
            self.output_status.setText("Cancelled")
            self.output_status.setProperty("state", "warning")
            self.output_status.style().unpolish(self.output_status)
            self.output_status.style().polish(self.output_status)
            self.status_message.emit("Audio cleanup cancelled")
            return
        self.result_label.setText(f"Processing failed: {message}")
        self.output_status.setText("Failed")
        self.output_status.setProperty("state", "danger")
        self.output_status.style().unpolish(self.output_status)
        self.output_status.style().polish(self.output_status)
        self.status_message.emit(f"Audio cleanup failed: {message}")

    def _on_finished(self):
        self._worker = None
        self._cancel_event = None
        self._set_busy(False)

    def shutdown(self):
        self.cancel()
