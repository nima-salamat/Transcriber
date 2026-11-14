"""Non-destructive FFmpeg audio cleanup workspace."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from transcriber.audio.processing import build_filter_chain, process_audio
from transcriber.ui.widgets import Card, page_header, primary_button
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
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)
        root.addWidget(page_header(
            "Audio Cleanup",
            "Apply reversible processing to a new output file. The source recording is never overwritten.",
        ))

        file_card = Card()
        file_layout = QHBoxLayout(file_card)
        self.source_label = QLabel("No source media selected")
        self.source_label.setObjectName("Muted")
        self.source_label.setWordWrap(True)
        choose = QPushButton("Choose audio/video…")
        choose.clicked.connect(self.choose_source)
        file_layout.addWidget(self.source_label, 1)
        file_layout.addWidget(choose)
        root.addWidget(file_card)

        options = Card()
        form = QFormLayout(options)
        form.setContentsMargins(18, 16, 18, 16)
        self.normalize = QCheckBox("Loudness normalization (EBU R128 target -16 LUFS)")
        self.denoise = QCheckBox("FFmpeg spectral denoise (single-pass, no noise profile)")
        self.silence = QCheckBox("Remove leading/trailing and detected internal silence")
        self.highpass = QSpinBox()
        self.highpass.setRange(20, 1000)
        self.highpass.setValue(80)
        self.highpass_enabled = QCheckBox("Enable")
        self.lowpass = QSpinBox()
        self.lowpass.setRange(1000, 20000)
        self.lowpass.setValue(12000)
        self.lowpass_enabled = QCheckBox("Enable")
        self.volume = QDoubleSpinBox()
        self.volume.setRange(-24, 24)
        self.volume.setDecimals(1)
        self.volume.setSuffix(" dB")
        self.volume.setSingleStep(1.0)
        self.volume.setValue(0)
        high_row = QHBoxLayout()
        high_row.addWidget(self.highpass_enabled)
        high_row.addWidget(self.highpass)
        high_row.addStretch(1)
        low_row = QHBoxLayout()
        low_row.addWidget(self.lowpass_enabled)
        low_row.addWidget(self.lowpass)
        low_row.addStretch(1)
        form.addRow("High-pass filter", high_row)
        form.addRow("Low-pass filter", low_row)
        form.addRow("Volume adjustment", self.volume)
        form.addRow("Normalize", self.normalize)
        form.addRow("Noise reduction", self.denoise)
        form.addRow("Silence removal", self.silence)
        root.addWidget(options)

        controls = QHBoxLayout()
        self.process_button = primary_button("Process to new file…")
        self.process_button.clicked.connect(self.process)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.setEnabled(False)
        controls.addWidget(self.process_button)
        controls.addWidget(self.cancel_button)
        controls.addStretch(1)
        root.addLayout(controls)
        self.result_label = QLabel("Choose a source file and select one or more operations.")
        self.result_label.setWordWrap(True)
        self.result_label.setObjectName("Muted")
        root.addWidget(self.result_label)
        root.addStretch(1)

    def choose_source(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose audio/video source", str(self.paths.recordings),
            "Media files (*.wav *.mp3 *.m4a *.aac *.flac *.ogg *.opus *.wma *.aiff *.aif *.mp4 *.mkv *.mov *.webm *.avi *.m4v);;All files (*)",
        )
        if path:
            self.source = Path(path).resolve()
            self.source_label.setText(self.source.name)
            self.source_label.setToolTip(str(self.source))

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

    def _on_result(self, path):
        self.result_label.setText(f"Created new audio file: {path}")
        self.open_cleaned_file.emit(str(path))
        self.status_message.emit(f"Audio cleanup completed: {Path(path).name}")

    def _on_error(self, message):
        if self._cancel_event and self._cancel_event.is_set():
            self.result_label.setText("Processing cancelled. Source file was not modified.")
            self.status_message.emit("Audio cleanup cancelled")
            return
        self.result_label.setText(f"Processing failed: {message}")
        self.status_message.emit(f"Audio cleanup failed: {message}")

    def _on_finished(self):
        self._worker = None
        self._cancel_event = None
        self._set_busy(False)

    def shutdown(self):
        self.cancel()
