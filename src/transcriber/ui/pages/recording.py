"""Polished microphone recording workspace with OS-default device routing."""

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
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from transcriber.audio.devices import audio_device_id
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
        self._has_usable_input = False
        self._pulse_phase = False
        self.recorder = QtAudioRecorder(self)
        self.media_devices = QMediaDevices(self)
        self.recording_path: Path | None = None
        self._elapsed = 0.0

        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._update_duration)
        self.pulse_timer = QTimer(self)
        self.pulse_timer.setInterval(160)
        self.pulse_timer.timeout.connect(self._pulse_record_button)
        self._device_refresh_timer = QTimer(self)
        self._device_refresh_timer.setSingleShot(True)
        self._device_refresh_timer.setInterval(350)
        self._device_refresh_timer.timeout.connect(self.refresh_devices)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        layout.addWidget(
            page_header(
                "Live recording",
                "Record a clear local audio take, monitor the microphone and send it straight to transcription.",
            )
        )

        # Device routing card
        device_card = Card()
        device_card.setObjectName("RecordingDeviceCard")
        device_layout = QVBoxLayout(device_card)
        device_layout.setContentsMargins(20, 16, 20, 16)
        device_layout.setSpacing(10)

        device_heading = QHBoxLayout()
        device_title = QLabel("AUDIO INPUT")
        device_title.setStyleSheet("font-size: 11px; font-weight: 750; letter-spacing: 1px;")
        self.device_hint = QLabel("Following the Windows default microphone")
        self.device_hint.setObjectName("Muted")
        self.device_hint.setWordWrap(True)
        device_heading.addWidget(device_title)
        device_heading.addStretch(1)
        device_heading.addWidget(self.device_hint, 1)
        device_layout.addLayout(device_heading)

        device_row = QHBoxLayout()
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(260)
        self.device_combo.setMinimumHeight(40)
        self.device_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.device_combo.setToolTip("Choose a microphone or follow the Windows default input device")
        self.device_combo.currentIndexChanged.connect(self._save_device_preference)
        device_row.addWidget(self.device_combo, 1)

        self.refresh_button = QPushButton("↻  Refresh devices")
        self.refresh_button.setMinimumHeight(40)
        self.refresh_button.clicked.connect(self.refresh_devices)
        device_row.addWidget(self.refresh_button)
        device_layout.addLayout(device_row)
        layout.addWidget(device_card)

        # Main recording console
        hero = Card()
        hero.setObjectName("RecordingHero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(26, 24, 26, 22)
        hero_layout.setSpacing(18)

        main_row = QHBoxLayout()
        main_row.setSpacing(24)
        details = QVBoxLayout()
        details.setSpacing(8)

        self.status_pill = QLabel("●  READY")
        self.status_pill.setObjectName("RecordingStatus")
        self.status_pill.setAlignment(Qt.AlignCenter)
        self.status_pill.setMaximumWidth(132)
        details.addWidget(self.status_pill, 0, Qt.AlignLeft)

        self.state_label = QLabel("Ready to record")
        self.state_label.setObjectName("PageTitle")
        self.state_label.setStyleSheet("font-size: 23px; font-weight: 700;")
        details.addWidget(self.state_label)

        self.duration_label = QLabel("00:00")
        self.duration_label.setObjectName("RecordingTimer")
        self.duration_label.setStyleSheet(
            "font-size: 54px; font-weight: 750; letter-spacing: 2px; padding: 2px 0;"
        )
        details.addWidget(self.duration_label)

        self.session_hint = QLabel("Your recording will be saved as a WAV file.")
        self.session_hint.setObjectName("Muted")
        self.session_hint.setWordWrap(True)
        details.addWidget(self.session_hint)
        details.addStretch(1)
        main_row.addLayout(details, 1)

        action_column = QVBoxLayout()
        action_column.setAlignment(Qt.AlignCenter)
        action_column.setSpacing(10)
        self.record_button = QPushButton("●")
        self.record_button.setObjectName("RecordButton")
        self.record_button.setFixedSize(126, 126)
        self.record_button.setToolTip("Start microphone recording")
        self.record_button.clicked.connect(self.start_recording)
        action_column.addWidget(self.record_button, 0, Qt.AlignHCenter)
        self.record_action_hint = QLabel("START RECORDING")
        self.record_action_hint.setObjectName("Muted")
        self.record_action_hint.setStyleSheet("font-size: 10px; font-weight: 750; letter-spacing: 1px;")
        self.record_action_hint.setAlignment(Qt.AlignCenter)
        action_column.addWidget(self.record_action_hint)
        main_row.addLayout(action_column)
        hero_layout.addLayout(main_row)

        meter_header = QHBoxLayout()
        meter_title = QLabel("MICROPHONE LEVEL")
        meter_title.setStyleSheet("font-size: 10px; font-weight: 750; letter-spacing: 1px;")
        self.level_value = QLabel("0%")
        self.level_value.setObjectName("Muted")
        meter_header.addWidget(meter_title)
        meter_header.addStretch(1)
        meter_header.addWidget(self.level_value)
        hero_layout.addLayout(meter_header)

        self.level = QProgressBar()
        self.level.setObjectName("RecordingLevel")
        self.level.setRange(0, 100)
        self.level.setValue(0)
        self.level.setTextVisible(False)
        self.level.setFixedHeight(12)
        hero_layout.addWidget(self.level)

        layout.addWidget(hero, 1)

        # Transport controls
        controls_card = Card()
        controls_layout = QHBoxLayout(controls_card)
        controls_layout.setContentsMargins(18, 14, 18, 14)
        controls_layout.setSpacing(10)

        controls_label = QLabel("CONTROLS")
        controls_label.setStyleSheet("font-size: 10px; font-weight: 750; letter-spacing: 1px;")
        controls_layout.addWidget(controls_label)
        controls_layout.addStretch(1)

        self.pause_button = QPushButton("Ⅱ  Pause")
        self.resume_button = QPushButton("▶  Resume")
        self.stop_button = QPushButton("■  Stop and save")
        self.cancel_button = QPushButton("Discard")
        self.stop_button.setObjectName("Primary")
        self.cancel_button.setObjectName("Danger")
        for button in (self.pause_button, self.resume_button, self.stop_button, self.cancel_button):
            button.setMinimumHeight(40)
            button.setEnabled(False)
        self.pause_button.clicked.connect(self.pause_recording)
        self.resume_button.clicked.connect(self.resume_recording)
        self.stop_button.clicked.connect(self.stop_recording)
        self.cancel_button.clicked.connect(self.cancel_recording)
        controls_layout.addWidget(self.pause_button)
        controls_layout.addWidget(self.resume_button)
        controls_layout.addWidget(self.stop_button)
        controls_layout.addWidget(self.cancel_button)
        layout.addWidget(controls_card)

        # Post-recording behaviour and privacy hint
        options_card = Card()
        options_layout = QHBoxLayout(options_card)
        options_layout.setContentsMargins(18, 12, 18, 12)
        self.auto_transcribe = QCheckBox("Open transcription automatically after saving")
        self.auto_transcribe.setChecked(True)
        options_layout.addWidget(self.auto_transcribe)
        options_layout.addStretch(1)
        local_note = QLabel("●  LOCAL WAV · NO CLOUD UPLOAD")
        local_note.setObjectName("Muted")
        local_note.setStyleSheet("font-size: 10px; font-weight: 700; letter-spacing: 0.5px;")
        options_layout.addWidget(local_note)
        layout.addWidget(options_card)

        self.recorder.state_changed.connect(self._state_changed)
        self.recorder.level_changed.connect(self._set_level)
        self.recorder.duration_changed.connect(self._set_duration)
        self.recorder.error_occurred.connect(self._show_error)
        self.recorder.recording_saved.connect(self._register_saved_recording)
        self.media_devices.audioInputsChanged.connect(self._schedule_device_refresh)

        self._style_record_button("ready")
        self.refresh_devices()

    def _schedule_device_refresh(self, *_args):
        # Windows may briefly publish an empty/partial device list while audio
        # endpoints are being re-enumerated. Never terminate an active capture
        # solely because this notification fired; QAudioSource reports capture
        # errors independently and is the authoritative source for disconnection.
        self._device_refresh_timer.start()

    def _save_device_preference(self, _index: int = -1):
        if self.settings_store is None:
            return
        device_id = str(self.device_combo.currentData() or "")
        if self.settings_store.settings.audio_input_device_id != device_id:
            self.settings_store.update(audio_input_device_id=device_id)

    def refresh_devices(self):
        selected_id = (
            self.settings_store.settings.audio_input_device_id
            if self.settings_store is not None
            else str(self.device_combo.currentData() or "")
        )
        devices = QtAudioRecorder.devices()
        default_device = QMediaDevices.defaultAudioInput()
        default_id = "" if default_device.isNull() else audio_device_id(default_device)

        blocker = self.device_combo.blockSignals(True)
        try:
            self.device_combo.clear()
            default_label = "Follow Windows default"
            if not default_device.isNull():
                default_label += f" · {default_device.description()}"
            else:
                default_label += " · No microphone detected"
            self.device_combo.addItem(default_label, "")

            available_ids = set()
            for device in devices:
                current_id = audio_device_id(device)
                available_ids.add(current_id)
                label = device.description()
                if current_id == default_id and default_id:
                    label += " · Windows default (pin device)"
                self.device_combo.addItem(label, current_id)

            if selected_id and selected_id not in available_ids:
                self.device_combo.addItem("Saved microphone · currently unavailable", selected_id)
                self.device_combo.setItemData(
                    self.device_combo.count() - 1, selected_id, Qt.ToolTipRole
                )
            self.device_combo.setCurrentIndex(max(0, self.device_combo.findData(selected_id)))
        finally:
            self.device_combo.blockSignals(blocker)

        self._has_usable_input = (
            default_id != "" if not selected_id else selected_id in available_ids
        )
        if not devices and default_device.isNull():
            hint = "No microphone detected. Connect a microphone or check Windows sound settings."
        elif selected_id and selected_id not in available_ids:
            hint = "The saved microphone is unavailable. Select another device or follow the Windows default."
        elif not selected_id:
            hint = f"Following Windows default: {default_device.description()}"
        else:
            match = next((d for d in devices if audio_device_id(d) == selected_id), None)
            hint = f"Using saved microphone: {match.description()}" if match else "Saved microphone is unavailable."

        self.device_hint.setText(hint)
        self.device_combo.setEnabled(self.recorder._state == "idle")
        self.refresh_button.setEnabled(self.recorder._state == "idle")
        self.record_button.setEnabled(
            self.recorder._state == "idle" and self._has_usable_input
        )
        if self.recorder._state in {"recording", "paused"} and not self._has_usable_input:
            self.session_hint.setText(
                "The input list changed while recording. Capture will continue unless Qt reports a real input error."
            )

    def _selected_input_device(self):
        selected_id = (
            self.settings_store.settings.audio_input_device_id
            if self.settings_store is not None
            else str(self.device_combo.currentData() or "")
        )
        if not selected_id:
            device = QMediaDevices.defaultAudioInput()
            return None if device.isNull() else device
        return next(
            (device for device in QtAudioRecorder.devices() if audio_device_id(device) == selected_id),
            None,
        )

    def start_recording(self):
        # Resolve the endpoint again at the moment of capture. An empty
        # preference deliberately follows Windows' current default device.
        device = self._selected_input_device()
        if device is None or device.isNull():
            QMessageBox.warning(
                self,
                "Microphone unavailable",
                "The selected microphone is not available. Choose another input device or switch to the Windows default.",
            )
            self.refresh_devices()
            return

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        default_path = self.paths.recordings / f"Recording-{stamp}.wav"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save recording", str(default_path), "WAV audio (*.wav)"
        )
        if not path:
            return
        if not path.lower().endswith(".wav"):
            path += ".wav"
        target = Path(path)
        if target.exists():
            answer = QMessageBox.question(
                self,
                "Replace recording?",
                f"{target.name} already exists. Replace it?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        self._auto_transcribe_after_save = self.auto_transcribe.isChecked()
        self.recording_path = None
        self._elapsed = 0.0
        self.duration_label.setText("00:00")
        self.session_hint.setText(f"Capturing from {device.description()} · WAV")
        try:
            # Pass the freshly-resolved QAudioDevice object, not a stale combo
            # item reference retained across Windows device refreshes.
            self.recorder.start(Path(path), device)
            self.timer.start()
            self.status_message.emit(f"Recording from {device.description()}")
        except Exception as exc:
            self.timer.stop()
            self.state_label.setText("Could not start recording")
            self.status_pill.setText("●  INPUT ERROR")
            self._style_status("error")
            self.session_hint.setText(str(exc))
            QMessageBox.critical(self, "Microphone error", str(exc))
            self.refresh_devices()

    def pause_recording(self):
        self.recorder.pause()

    def resume_recording(self):
        self.recorder.resume()

    def stop_recording(self):
        saved = self.recorder.stop()
        self.timer.stop()
        if not saved:
            self.status_message.emit(
                "No audio samples were captured; the empty recording was discarded"
            )

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

        self.state_label.setText("Recording saved")
        self.status_pill.setText("●  SAVED")
        self._style_status("saved")
        self.session_hint.setText(f"{path.name} · Ready to open in transcription")
        if self._auto_transcribe_after_save:
            self.audio_ready.emit(str(path))
        self._auto_transcribe_after_save = True

    def cancel_recording(self):
        self.timer.stop()
        self.recorder.cancel()
        self.recording_path = None
        self.duration_label.setText("00:00")
        self.level.setValue(0)
        self.level_value.setText("0%")
        self.state_label.setText("Recording discarded")
        self.status_pill.setText("●  DISCARDED")
        self._style_status("idle")
        self.session_hint.setText("The temporary audio file was removed.")
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
        self.refresh_button.setEnabled(not active)
        self.record_button.setEnabled(not active and self._has_usable_input)

        if recording:
            self.status_pill.setText("●  RECORDING")
            self._style_status("recording")
            self.state_label.setText("Recording in progress")
            self.record_button.setText("●")
            self.record_button.setToolTip("Recording is active")
            self.record_action_hint.setText("CAPTURING AUDIO")
            self.pulse_timer.start()
            self._style_record_button("recording")
        elif paused:
            self.status_pill.setText("Ⅱ  PAUSED")
            self._style_status("paused")
            self.state_label.setText("Recording paused")
            self.record_button.setText("Ⅱ")
            self.record_button.setToolTip("Recording is paused")
            self.record_action_hint.setText("RECORDING PAUSED")
            self.pulse_timer.stop()
            self._style_record_button("paused")
        else:
            self.pulse_timer.stop()
            self._pulse_phase = False
            self.record_button.setText("●")
            self.record_button.setToolTip("Start microphone recording")
            self.record_action_hint.setText("START RECORDING")
            self._style_record_button("ready")
            if state == "cancelled":
                self.status_pill.setText("●  DISCARDED")
                self._style_status("idle")
                self.state_label.setText("Recording discarded")
            elif state == "idle" and self.recording_path is None:
                self.status_pill.setText("●  READY")
                self._style_status("ready")
                self.state_label.setText("Ready to record")

    def _style_status(self, state: str):
        styles = {
            "ready": "background: rgba(61, 177, 132, 0.14); color: #45b88c;",
            "recording": "background: rgba(225, 75, 91, 0.15); color: #ed6978;",
            "paused": "background: rgba(226, 169, 69, 0.16); color: #d5a64d;",
            "saved": "background: rgba(75, 145, 220, 0.15); color: #6da9e9;",
            "idle": "background: rgba(130, 140, 155, 0.15); color: #9aa5b4;",
            "error": "background: rgba(225, 75, 91, 0.15); color: #ed6978;",
        }
        self.status_pill.setStyleSheet(
            "QLabel#RecordingStatus { "
            + styles.get(state, styles["ready"])
            + " border-radius: 11px; padding: 6px 10px; font-size: 10px; font-weight: 800; }"
        )

    def _style_record_button(self, state: str):
        if state == "recording":
            background, ring = "#cf4355", "rgba(225, 75, 91, 0.25)"
        elif state == "paused":
            background, ring = "#bd8a35", "rgba(226, 169, 69, 0.22)"
        else:
            background, ring = "#df5364", "rgba(223, 83, 100, 0.20)"
        width = 10 if self._pulse_phase and state == "recording" else 7
        self.record_button.setStyleSheet(
            "QPushButton#RecordButton { "
            f"border-radius: 63px; background: {background}; color: white; "
            f"font-size: 42px; font-weight: 500; border: {width}px solid {ring}; }}"
            "QPushButton#RecordButton:hover { background: #c63f50; }"
            "QPushButton#RecordButton:disabled { color: rgba(255,255,255,0.85); }"
        )

    def _pulse_record_button(self):
        self._pulse_phase = not self._pulse_phase
        self._style_record_button("recording")

    def _set_level(self, value: int):
        level = max(0, min(100, int(value)))
        self.level.setValue(level)
        self.level_value.setText(f"{level}%")

    def _set_duration(self, seconds: float):
        self._elapsed = max(0.0, float(seconds))
        self._update_duration()

    def _update_duration(self):
        seconds = int(self.recorder.duration())
        minutes, seconds = divmod(seconds, 60)
        self.duration_label.setText(f"{minutes:02}:{seconds:02}")

    def _show_error(self, message: str):
        self.timer.stop()
        self.status_pill.setText("●  AUDIO ERROR")
        self._style_status("error")
        self.state_label.setText("Microphone capture stopped")
        self.session_hint.setText(str(message))
        self.status_message.emit(str(message))
        QMessageBox.warning(self, "Recording interrupted", str(message))

    def shutdown(self):
        self.timer.stop()
        self.pulse_timer.stop()
        self._device_refresh_timer.stop()
        self.recorder.shutdown()
