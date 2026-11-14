"""Microphone recording workspace with device selection and PCM level feedback."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from transcriber.audio.recorder import QtAudioRecorder
from transcriber.ui.widgets import Card, page_header


class RecordingPage(QWidget):
    audio_ready = Signal(str)
    status_message = Signal(str)

    def __init__(self, paths, recording_history=None, settings_store=None, parent=None):
        super().__init__(parent)
        self.paths = paths
        self.recording_history = recording_history
        self.settings_store = settings_store
        self._auto_transcribe_after_save = True
        self.recorder = QtAudioRecorder(self)
        # Qt exposes audioInputsChanged as an instance signal, not a static signal.
        # Keep the QMediaDevices monitor alive for this page lifetime.
        self.media_devices = QMediaDevices(self)
        self.recording_path: Path | None = None
        self._elapsed = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._update_duration)
        self.pulse_timer = QTimer(self)
        self.pulse_timer.setInterval(140)
        self.pulse_timer.timeout.connect(self._pulse_record_button)
        self._pulse_phase = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)
        layout.addWidget(page_header("Live recording", "Capture microphone audio locally, then open it in the transcription workspace."))

        panel = Card()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(30, 28, 30, 28)
        panel_layout.setSpacing(15)
        panel_layout.addWidget(QLabel("INPUT DEVICE"))
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(300)
        self.device_combo.currentIndexChanged.connect(self._save_device_preference)
        panel_layout.addWidget(self.device_combo, 0)
        panel_layout.addStretch(1)
        self.record_button = QPushButton("●")
        self.record_button.setObjectName("RecordButton")
        self.record_button.setFixedSize(112, 112)
        self.record_button.setStyleSheet(
            "QPushButton#RecordButton { border-radius: 56px; background: #d94b5b; color: white; "
            "font-size: 32px; border: 7px solid rgba(217,75,91,0.18); } "
            "QPushButton#RecordButton:hover { background: #c63f50; }"
        )
        self.record_button.setToolTip("Start microphone recording")
        self.record_button.clicked.connect(self.start_recording)
        center = QHBoxLayout()
        center.addStretch(1)
        center.addWidget(self.record_button)
        center.addStretch(1)
        panel_layout.addLayout(center)
        self.state_label = QLabel("Ready to record")
        self.state_label.setObjectName("SectionTitle")
        self.state_label.setAlignment(Qt.AlignCenter)
        self.duration_label = QLabel("00:00")
        self.duration_label.setAlignment(Qt.AlignCenter)
        self.duration_label.setStyleSheet("font-size: 28px; font-weight: 650;")
        panel_layout.addWidget(self.state_label)
        panel_layout.addWidget(self.duration_label)
        self.level = QProgressBar()
        self.level.setRange(0, 100)
        self.level.setTextVisible(False)
        self.level.setMaximumWidth(480)
        level_row = QHBoxLayout()
        level_row.addStretch(1)
        level_row.addWidget(self.level)
        level_row.addStretch(1)
        panel_layout.addLayout(level_row)
        self.auto_transcribe = QCheckBox("Start transcription after saving")
        self.auto_transcribe.setChecked(True)
        auto_row = QHBoxLayout()
        auto_row.addStretch(1)
        auto_row.addWidget(self.auto_transcribe)
        auto_row.addStretch(1)
        panel_layout.addLayout(auto_row)
        self.device_hint = QLabel("Audio is captured as 16-bit PCM WAV. No network service is used.")
        self.device_hint.setObjectName("Muted")
        self.device_hint.setAlignment(Qt.AlignCenter)
        panel_layout.addWidget(self.device_hint)
        panel_layout.addStretch(1)
        layout.addWidget(panel, 1)

        controls = QHBoxLayout()
        self.pause_button = QPushButton("Pause")
        self.resume_button = QPushButton("Resume")
        self.stop_button = QPushButton("Stop and save")
        self.cancel_button = QPushButton("Discard")
        self.pause_button.clicked.connect(self.pause_recording)
        self.resume_button.clicked.connect(self.resume_recording)
        self.stop_button.clicked.connect(self.stop_recording)
        self.cancel_button.clicked.connect(self.cancel_recording)
        for button in (self.pause_button, self.resume_button, self.stop_button, self.cancel_button):
            button.setEnabled(False)
        controls.addStretch(1)
        controls.addWidget(self.pause_button)
        controls.addWidget(self.resume_button)
        controls.addWidget(self.stop_button)
        controls.addWidget(self.cancel_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.recorder.state_changed.connect(self._state_changed)
        self.recorder.level_changed.connect(self.level.setValue)
        self.recorder.duration_changed.connect(self._set_duration)
        self.recorder.error_occurred.connect(self._show_error)
        self.recorder.recording_saved.connect(self._register_saved_recording)
        self.media_devices.audioInputsChanged.connect(self.refresh_devices)
        self.refresh_devices()

    @staticmethod
    def _device_id(device) -> str:
        try:
            return bytes(device.id()).decode("utf-8", "replace")
        except (AttributeError, TypeError, ValueError):
            return str(device.id())

    def _save_device_preference(self, _index: int = -1):
        if self.settings_store is None:
            return
        device_id = str(self.device_combo.currentData() or "")
        if self.settings_store.settings.audio_input_device_id != device_id:
            self.settings_store.update(audio_input_device_id=device_id)

    def refresh_devices(self):
        selected_id = (
            self.settings_store.settings.audio_input_device_id
            if self.settings_store is not None else str(self.device_combo.currentData() or "")
        )
        devices = QtAudioRecorder.devices()
        default_device = QMediaDevices.defaultAudioInput()
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        self.device_combo.addItem("System default microphone", "")
        available_ids = set()
        for device in devices:
            device_id = self._device_id(device)
            available_ids.add(device_id)
            label = device.description()
            if not default_device.isNull() and device == default_device:
                label += " · System default"
            self.device_combo.addItem(label, device_id)
        if selected_id and selected_id not in available_ids:
            self.device_combo.addItem(f"Unavailable microphone · {selected_id}", selected_id)
        index = self.device_combo.findData(selected_id)
        self.device_combo.setCurrentIndex(max(0, index))
        self.device_combo.blockSignals(False)

        if self.recorder._state in {"recording", "paused"}:
            active_device = self.recorder.device_id
            if active_device and active_device not in available_ids:
                self.recorder.device_disconnected()
        self.device_combo.setEnabled(self.recorder._state == "idle")
        can_record = bool(devices) and (
            not selected_id or selected_id in available_ids
        ) and (not selected_id or any(self._device_id(d) == selected_id for d in devices))
        self.record_button.setEnabled(can_record and self.recorder._state == "idle")
        self.device_hint.setText(
            "Audio is captured as 16-bit PCM WAV. Your preferred microphone is shared with Settings."
            if devices else "No input device detected. Connect a microphone and refresh device settings."
        )

    def _selected_input_device(self):
        selected_id = str(self.device_combo.currentData() or "")
        devices = QtAudioRecorder.devices()
        if not selected_id:
            return QMediaDevices.defaultAudioInput()
        return next((device for device in devices if self._device_id(device) == selected_id), None)

    def start_recording(self):
        device = self._selected_input_device()
        if device is None or device.isNull():
            QMessageBox.warning(
                self, "Microphone unavailable",
                "The selected microphone is not available. Choose another input device in Settings.",
            )
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        default_path = self.paths.recordings / f"Recording-{stamp}.wav"
        path, _ = QFileDialog.getSaveFileName(self, "Save recording", str(default_path), "WAV audio (*.wav)")
        if not path:
            return
        if not path.lower().endswith(".wav"):
            path += ".wav"
        target = Path(path)
        if target.exists():
            answer = QMessageBox.question(
                self, "Replace recording?", f"{target.name} already exists. Replace it?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        self._auto_transcribe_after_save = self.auto_transcribe.isChecked()
        try:
            self.recorder.start(Path(path), device)
            self.recording_path = Path(path)
            self._elapsed = 0.0
            self.timer.start()
            self.state_label.setText(f"Recording · {device.description()}")
        except Exception as exc:
            QMessageBox.critical(self, "Microphone error", str(exc))

    def pause_recording(self):
        self.recorder.pause()

    def resume_recording(self):
        self.recorder.resume()

    def stop_recording(self):
        saved = self.recorder.stop()
        self.timer.stop()
        if not saved:
            self.status_message.emit("No audio samples were captured; the empty recording was discarded")

    def _register_saved_recording(self, raw_path: str):
        path = Path(raw_path).expanduser().resolve()
        self.recording_path = path
        try:
            if self.recording_history is not None:
                record = self.recording_history.register(
                    path,
                    duration=self.recorder.duration(),
                    device_id=self.recorder.device_id,
                    device_name=self.recorder.device_name,
                )
                self.status_message.emit(
                    f"Recording saved to library: {record['filename']} · {record['duration']:.1f}s"
                )
            else:
                self.status_message.emit(f"Recording saved: {path.name}")
        except Exception as exc:
            self.status_message.emit(
                f"Recording file saved, but recording history could not be updated: {exc}"
            )
        if self._auto_transcribe_after_save:
            self.audio_ready.emit(str(path))
        self._auto_transcribe_after_save = True

    def cancel_recording(self):
        self.timer.stop()
        self.recorder.cancel()
        self.recording_path = None
        self.duration_label.setText("00:00")
        self.status_message.emit("Recording discarded")

    def _state_changed(self, state: str):
        recording = state == "recording"
        paused = state == "paused"
        active = recording or paused
        self.pause_button.setEnabled(recording)
        self.resume_button.setEnabled(paused)
        self.stop_button.setEnabled(active)
        self.cancel_button.setEnabled(active)
        self.auto_transcribe.setEnabled(not active)
        self.device_combo.setEnabled(not active)
        self.record_button.setEnabled(not active and self.device_combo.count() > 0)
        if recording:
            self.record_button.setText("◉")
            self.record_button.setToolTip("Recording is active")
            self.pulse_timer.start()
            self.state_label.setText(f"Recording · {self.device_combo.currentText()}")
        elif paused:
            self.record_button.setText("Ⅱ")
            self.record_button.setToolTip("Recording is paused")
            self.pulse_timer.stop()
            self._pulse_phase = False
            self._style_record_button(False)
            self.state_label.setText("Recording paused")
        else:
            self.pulse_timer.stop()
            self._pulse_phase = False
            self._style_record_button(False)
            self.record_button.setText("●")
            self.record_button.setToolTip("Start microphone recording")
            if state == "idle":
                self.state_label.setText("Recording saved" if self.recording_path and self.recording_path.exists() else "Ready to record")
            elif state == "cancelled":
                self.state_label.setText("Recording discarded")

    def _pulse_record_button(self):
        self._pulse_phase = not self._pulse_phase
        self._style_record_button(self._pulse_phase)

    def _style_record_button(self, emphasized: bool):
        width = 10 if emphasized else 7
        self.record_button.setStyleSheet(
            "QPushButton#RecordButton { border-radius: 56px; background: #d94b5b; color: white; "
            f"font-size: 32px; border: {width}px solid rgba(217,75,91,0.22); }} "
            "QPushButton#RecordButton:hover { background: #c63f50; }"
        )

    def _set_duration(self, seconds: float):
        self._elapsed = seconds
        self._update_duration()

    def _update_duration(self):
        seconds = int(self.recorder.duration())
        self.duration_label.setText(f"{seconds // 60:02}:{seconds % 60:02}")

    def _show_error(self, message: str):
        self.timer.stop()
        QMessageBox.warning(self, "Recording interrupted", message)
        self.status_message.emit(message)

    def shutdown(self):
        self.timer.stop()
        self.pulse_timer.stop()
        self.recorder.shutdown()
