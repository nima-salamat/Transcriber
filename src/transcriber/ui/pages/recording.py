"""Recorder workspace with a live waveform, transport controls and take replacement."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPalette
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from transcriber.audio.devices import audio_device_id
from transcriber.audio.player import AudioPlayer
from transcriber.audio.recorder import QtAudioRecorder
from transcriber.ui.components.waveform import WaveformTimeline
from transcriber.ui.design.icon_registry import IconRegistry
from transcriber.ui.widgets import Card, page_header


def _record_button_enabled_for_state(state: str, has_usable_input: bool) -> bool:
    """Keep Start available after a discard event returns the recorder to idle."""
    return state in {"recording", "paused"} or (
        state in {"idle", "cancelled"} and bool(has_usable_input)
    )


def _clock(seconds: float) -> str:
    value = max(0, int(float(seconds)))
    hours, remainder = divmod(value, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"


class RecordingPage(QWidget):
    audio_ready = Signal(str)
    open_library = Signal()
    status_message = Signal(str)

    def __init__(self, paths, recording_history=None, settings_store=None, parent=None):
        super().__init__(parent)
        self.paths = paths
        self.recording_history = recording_history
        self.settings_store = settings_store
        self._auto_transcribe_after_save = True
        self._has_usable_input = False
        self._pulse_phase = False
        self._preview_position = 0.0
        self._preview_duration = 0.0
        self._preview_loading = False
        self._preview_path: Path | None = None
        self.recorder = QtAudioRecorder(self)
        self.preview_player = AudioPlayer(self)
        if settings_store is not None:
            self.preview_player.set_output_device(settings_store.settings.audio_output_device_id)
        self.media_devices = QMediaDevices(self)
        self.recording_path: Path | None = None

        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._update_duration)
        self.pulse_timer = QTimer(self)
        self.pulse_timer.setInterval(180)
        self.pulse_timer.timeout.connect(self._pulse_record_button)
        self._device_refresh_timer = QTimer(self)
        self._device_refresh_timer.setSingleShot(True)
        self._device_refresh_timer.setInterval(350)
        self._device_refresh_timer.timeout.connect(self.refresh_devices)
        self.icons = IconRegistry()

        self.setObjectName("RecordingPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 10, 12)
        layout.setSpacing(15)

        heading = QHBoxLayout()
        heading.addWidget(page_header(
            "Studio recorder",
            "Capture, review and replace parts of a take before saving it to your local recordings.",
        ), 1)
        self.library_button = QPushButton("  Recordings")
        self.library_button.setIcon(self.icons.icon("projects", size=18))
        self.library_button.setIconSize(__import__("PySide6.QtCore", fromlist=["QSize"]).QSize(18, 18))
        self.library_button.setMinimumHeight(40)
        self.library_button.clicked.connect(self.open_library.emit)
        heading.addWidget(self.library_button, 0, Qt.AlignTop)
        layout.addLayout(heading)

        # Recorder console: time, waveform and familiar transport controls.
        console = Card()
        console_layout = QVBoxLayout(console)
        console_layout.setContentsMargins(22, 20, 22, 18)
        console_layout.setSpacing(14)

        status_row = QHBoxLayout()
        self.status_pill = QLabel("READY")
        self.status_pill.setObjectName("RecordingStatus")
        self.status_pill.setAlignment(Qt.AlignCenter)
        self.status_pill.setMinimumWidth(92)
        status_row.addWidget(self.status_pill)
        self.state_label = QLabel("Ready when you are")
        self.state_label.setObjectName("Muted")
        status_row.addWidget(self.state_label)
        status_row.addStretch(1)
        self.input_badge = QLabel("WAV  ·  LOCAL")
        self.input_badge.setObjectName("RecordingFormatBadge")
        status_row.addWidget(self.input_badge)
        console_layout.addLayout(status_row)

        time_row = QHBoxLayout()
        self.duration_label = QLabel("00:00")
        self.duration_label.setObjectName("RecorderMainTimer")
        time_row.addWidget(self.duration_label)
        time_row.addStretch(1)
        self.position_label = QLabel("00:00")
        self.position_label.setObjectName("Muted")
        self.position_label.setToolTip("Selected position")
        self.total_label = QLabel(" / 00:00")
        self.total_label.setObjectName("Muted")
        time_row.addWidget(self.position_label)
        time_row.addWidget(self.total_label)
        console_layout.addLayout(time_row)

        self.waveform = WaveformTimeline()
        self.waveform.setObjectName("RecordingWaveform")
        self.waveform.set_background_enabled(False)
        self.waveform.setMinimumHeight(142)
        self.waveform.set_waveform([], 0.0)
        self.waveform.set_interactive(False)
        self.waveform.seek_requested.connect(self._seek_preview)
        console_layout.addWidget(self.waveform)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        controls.addStretch(1)
        self.play_preview_button = QPushButton()
        self.play_preview_button.setIcon(
            self.icons.icon("play", self._neutral_icon_color(), 18)
        )
        self.play_preview_button.setIconSize(__import__("PySide6.QtCore", fromlist=["QSize"]).QSize(18, 18))
        self.play_preview_button.setToolTip("Listen to the paused recording")
        self.play_preview_button.setObjectName("RecordingPreviewButton")
        self.play_preview_button.setFixedSize(46, 46)
        self.play_preview_button.setEnabled(False)
        self.play_preview_button.clicked.connect(self._toggle_preview)
        controls.addWidget(self.play_preview_button)

        self.record_button = QPushButton("  Start recording")
        self.record_button.setObjectName("RecordPrimary")
        self.record_button.setIcon(self.icons.icon("record", "#ffffff", 20))
        self.record_button.setIconSize(__import__("PySide6.QtCore", fromlist=["QSize"]).QSize(20, 20))
        # Keep the control footprint stable while its label changes between states.
        self.record_button.setFixedSize(220, 54)
        self.record_button.clicked.connect(self._primary_action)
        controls.addWidget(self.record_button)

        self.stop_button = QPushButton()
        self.stop_button.setObjectName("StopRecording")
        self.stop_button.setIcon(self.icons.icon("stop", "#ffffff", 21))
        self.stop_button.setIconSize(__import__("PySide6.QtCore", fromlist=["QSize"]).QSize(21, 21))
        self.stop_button.setFixedSize(54, 54)
        self.stop_button.setToolTip("Finish and save this recording")
        self.stop_button.setAccessibleName("Stop and save recording")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_recording)
        controls.addWidget(self.stop_button)

        self.cancel_button = QPushButton()
        self.cancel_button.setIcon(self.icons.icon("discard", "#ffffff", 18))
        self.cancel_button.setIconSize(__import__("PySide6.QtCore", fromlist=["QSize"]).QSize(18, 18))
        self.cancel_button.setFixedSize(44, 44)
        self.cancel_button.setToolTip("Discard this take")
        self.cancel_button.setAccessibleName("Discard recording")
        self.cancel_button.setObjectName("Danger")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_recording)
        controls.addWidget(self.cancel_button)
        controls.addStretch(1)
        console_layout.addLayout(controls)

        self.transport_hint = QLabel("Pause to review the waveform. Drag the playhead, then resume to replace the audio after that point.")
        self.transport_hint.setObjectName("Muted")
        self.transport_hint.setAlignment(Qt.AlignCenter)
        self.transport_hint.setWordWrap(True)
        console_layout.addWidget(self.transport_hint)
        layout.addWidget(console, 1)

        # Compact capture preferences live below the recorder controls.
        # Device choice and post-save transcription share one small surface.
        capture_options = Card()
        capture_options.setObjectName("RecordingOptionsCard")
        capture_options_layout = QVBoxLayout(capture_options)
        capture_options_layout.setContentsMargins(14, 10, 14, 10)
        capture_options_layout.setSpacing(7)

        device_row = QHBoxLayout()
        device_row.setSpacing(9)
        mic_icon = QLabel()
        mic_icon.setPixmap(self.icons.icon("record", "#d65a68", 17).pixmap(17, 17))
        mic_icon.setFixedSize(22, 22)
        device_row.addWidget(mic_icon, 0, Qt.AlignVCenter)
        device_title = QLabel("Microphone")
        device_title.setObjectName("RecordingDeviceTitle")
        device_row.addWidget(device_title)
        self.device_hint = QLabel("System default")
        self.device_hint.setObjectName("RecordingDeviceHint")
        device_row.addWidget(self.device_hint)
        device_row.addStretch(1)

        self.device_combo = QComboBox()
        self.device_combo.setObjectName("RecordingMicrophoneCombo")
        self.device_combo.setMinimumWidth(150)
        self.device_combo.setMaximumWidth(420)
        self.device_combo.setFixedHeight(32)
        self.device_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.device_combo.setToolTip("Choose a microphone or follow the system default input device")
        self.device_combo.currentIndexChanged.connect(self._save_device_preference)
        device_row.addWidget(self.device_combo, 1)

        self.refresh_button = QPushButton("↻")
        self.refresh_button.setObjectName("RecordingRefreshDevices")
        self.refresh_button.setToolTip("Refresh microphone devices")
        self.refresh_button.setFixedSize(32, 32)
        self.refresh_button.clicked.connect(self.refresh_devices)
        device_row.addWidget(self.refresh_button)
        capture_options_layout.addLayout(device_row)

        preference_row = QHBoxLayout()
        preference_row.setContentsMargins(0, 0, 0, 0)
        preference_row.setSpacing(8)
        self.auto_transcribe = QCheckBox("Transcribe automatically after saving")
        self.auto_transcribe.setObjectName("RecordingAutoTranscribe")
        self.auto_transcribe.setChecked(True)
        preference_row.addWidget(self.auto_transcribe)
        preference_row.addStretch(1)
        local_note = QLabel("●  SAVED ON THIS DEVICE")
        local_note.setObjectName("RecordingLocalNote")
        preference_row.addWidget(local_note)
        capture_options_layout.addLayout(preference_row)

        layout.addWidget(capture_options)

        self.recorder.state_changed.connect(self._state_changed)
        self.recorder.duration_changed.connect(self._set_duration)
        self.recorder.waveform_changed.connect(self._set_waveform)
        self.recorder.error_occurred.connect(self._show_error)
        self.recorder.recording_saved.connect(self._register_saved_recording)
        self.preview_player.position_changed.connect(self._preview_position_changed)
        self.preview_player.playback_changed.connect(self._preview_playback_changed)
        self.preview_player.error_occurred.connect(
            lambda message: self.status_message.emit(f"Preview playback: {message}")
        )
        self.media_devices.audioInputsChanged.connect(self._schedule_device_refresh)

        self._style_status("ready")
        self._style_record_button("ready")
        self.refresh_devices()

    def _schedule_device_refresh(self, *_args):
        # A transient Windows endpoint refresh must never abort an active capture.
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
            default_label = "Follow system default"
            if default_device.isNull():
                default_label = "System default · no microphone"
            self.device_combo.addItem(default_label, "")

            available_ids = set()
            for device in devices:
                current_id = audio_device_id(device)
                available_ids.add(current_id)
                label = device.description()
                if current_id == default_id and default_id:
                    label += " · System default (pin device)"
                self.device_combo.addItem(label, current_id)

            if selected_id and selected_id not in available_ids:
                self.device_combo.addItem("Saved microphone · currently unavailable", selected_id)
            self.device_combo.setCurrentIndex(max(0, self.device_combo.findData(selected_id)))
        finally:
            self.device_combo.blockSignals(blocker)

        self._has_usable_input = (
            selected_id in available_ids if selected_id else not default_device.isNull()
        )
        if not devices and default_device.isNull():
            hint = "No microphone detected"
        elif selected_id and selected_id not in available_ids:
            hint = "Saved device unavailable"
        elif not selected_id:
            hint = "System default"
        else:
            hint = "Selected device" if selected_id in available_ids else "Saved device unavailable"

        self.device_hint.setText(hint)
        idle = self.recorder._state == "idle"
        self.device_combo.setEnabled(idle)
        self.refresh_button.setEnabled(idle)
        if idle:
            self.record_button.setEnabled(self._has_usable_input)
        elif self.recorder._state in {"recording", "paused"} and not self._has_usable_input:
            self.transport_hint.setText(
                "Windows refreshed its input list. The current take will continue unless Qt reports a real capture error."
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
        device = self._selected_input_device()
        if device is None or device.isNull():
            QMessageBox.warning(
                self,
                "Microphone unavailable",
                "Choose an available microphone or switch to the Windows default input.",
            )
            self.refresh_devices()
            return

        directory = Path(self.paths.recordings)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = directory / f"Recording-{stamp}.wav"
        suffix = 1
        while target.exists():
            target = directory / f"Recording-{stamp}-{suffix:02d}.wav"
            suffix += 1

        self.preview_player.stop()
        self.preview_player.clear_source()
        self._preview_path = None
        self._preview_position = 0.0
        self._preview_duration = 0.0
        self.recording_path = None
        self._auto_transcribe_after_save = self.auto_transcribe.isChecked()
        self.waveform.set_waveform([], 0.0)
        self.waveform.set_position(0.0)
        self.duration_label.setText("00:00")
        self.position_label.setText("00:00")
        self.total_label.setText(" / 00:00")
        self.transport_hint.setText("Recording · Pause to review and replace a section.")
        try:
            self.recorder.start(target, device)
            self.timer.start()
            self.status_message.emit("Recording started")
        except Exception as exc:
            self.timer.stop()
            self.state_label.setText("Could not start recording")
            self.status_pill.setText("INPUT ERROR")
            self._style_status("error")
            self.transport_hint.setText(str(exc))
            QMessageBox.critical(self, "Microphone error", str(exc))
            self.refresh_devices()

    def _primary_action(self):
        state = self.recorder._state
        if state == "idle":
            self.start_recording()
        elif state == "recording":
            self.pause_recording()
        elif state == "paused":
            self.resume_recording()

    def pause_recording(self):
        self.recorder.pause()

    def resume_recording(self):
        position = self._preview_position if self._preview_duration else self.recorder.duration()
        self.preview_player.stop()
        self.preview_player.clear_source()
        self._preview_path = None
        self._preview_duration = 0.0
        self._preview_position = position
        self.waveform.set_interactive(False)
        try:
            self.recorder.resume_from(position)
        except Exception as exc:
            QMessageBox.warning(self, "Could not resume recording", str(exc))

    def stop_recording(self):
        self.preview_player.stop()
        self.preview_player.clear_source()
        self._preview_path = None
        self.waveform.set_interactive(False)
        saved = self.recorder.stop()
        self.timer.stop()
        if not saved and self.recording_path is None:
            self.status_message.emit("No audio samples were captured; the empty take was discarded")

    def _load_paused_preview(self):
        if self.recorder._state != "paused":
            return
        try:
            preview = self.recorder.preview_snapshot()
        except (OSError, RuntimeError) as exc:
            preview = None
            self.transport_hint.setText(f"Preview could not be prepared: {exc}")
        self._preview_duration = self.recorder.duration()
        self._preview_position = self._preview_duration
        self.position_label.setText(_clock(self._preview_position))
        self.total_label.setText(f" / {_clock(self._preview_duration)}")
        self.waveform.set_position(self._preview_position)
        self.waveform.set_duration(self._preview_duration)
        self.waveform.set_interactive(True)
        self.play_preview_button.setEnabled(bool(preview))
        self.transport_hint.setText(
            "Listen and drag the playhead to a position. Resume replaces everything after the selected point."
        )
        if preview:
            self._preview_path = preview
            self.preview_player.set_source(str(preview))

    def _toggle_preview(self):
        if self.recorder._state != "paused":
            return
        self.preview_player.play_pause()

    def _seek_preview(self, seconds: float):
        if self.recorder._state != "paused":
            return
        self._preview_position = max(0.0, min(self._preview_duration, float(seconds)))
        self.preview_player.seek(int(self._preview_position * 1000))
        self.position_label.setText(_clock(self._preview_position))

    def _preview_position_changed(self, position_ms: int):
        if self.recorder._state != "paused":
            return
        self._preview_position = max(0.0, min(self._preview_duration, position_ms / 1000.0))
        self.waveform.set_position(self._preview_position)
        self.position_label.setText(_clock(self._preview_position))

    def _preview_playback_changed(self, playing: bool):
        name = "pause" if playing else "play"
        self.play_preview_button.setIcon(
            self.icons.icon(name, self._neutral_icon_color(), 18)
        )
        self.play_preview_button.setToolTip("Pause preview" if playing else "Listen to the paused recording")

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
                    f"Recording saved · {record['filename']} · {record['duration']:.1f}s"
                )
            else:
                self.status_message.emit(f"Recording saved · {path.name}")
        except Exception as exc:
            self.status_message.emit(
                f"The audio file was saved, but its library entry could not be updated: {exc}"
            )

        self.timer.stop()
        self._preview_duration = self.recorder.duration()
        self._preview_position = self._preview_duration
        self.waveform.set_duration(self._preview_duration)
        self.waveform.set_interactive(False)
        self.state_label.setText("Recording saved")
        self.status_pill.setText("SAVED")
        self._style_status("saved")
        self.duration_label.setText(_clock(self._preview_duration))
        self.position_label.setText(_clock(self._preview_duration))
        self.total_label.setText(f" / {_clock(self._preview_duration)}")
        self.transport_hint.setText(f"Saved to your recordings · {path.name}")
        self.play_preview_button.setEnabled(False)
        if self._auto_transcribe_after_save:
            self.audio_ready.emit(str(path))
        self._auto_transcribe_after_save = True

    def cancel_recording(self):
        self.timer.stop()
        self.preview_player.stop()
        self.preview_player.clear_source()
        self._preview_path = None
        self.recorder.cancel()
        self.recording_path = None
        self.duration_label.setText("00:00")
        self.position_label.setText("00:00")
        self.total_label.setText(" / 00:00")
        self.waveform.set_waveform([], 0.0)
        self.waveform.set_interactive(False)
        self.state_label.setText("Take discarded")
        self.status_pill.setText("DISCARDED")
        self._style_status("idle")
        self.transport_hint.setText("The temporary audio was removed.")
        self.status_message.emit("Recording discarded")

    def _state_changed(self, state: str):
        recording = state == "recording"
        paused = state == "paused"
        active = recording or paused

        self.stop_button.setEnabled(active)
        self.cancel_button.setEnabled(active)
        self.auto_transcribe.setEnabled(not active)
        self.device_combo.setEnabled(not active)
        self.refresh_button.setEnabled(not active)
        self.library_button.setEnabled(not active)
        self.play_preview_button.setEnabled(paused and bool(self._preview_path))
        self.record_button.setEnabled(
            _record_button_enabled_for_state(state, self._has_usable_input)
        )

        if recording:
            self.status_pill.setText("RECORDING")
            self._style_status("recording")
            self.state_label.setText("Recording in progress")
            self.record_button.setText("  Pause")
            self.record_button.setIcon(self.icons.icon("pause", "#ffffff", 20))
            self.record_button.setToolTip("Pause this take and review the waveform")
            self.pulse_timer.start()
            self._style_record_button("recording")
            self.waveform.set_interactive(False)
            self.play_preview_button.setEnabled(False)
        elif paused:
            self.status_pill.setText("PAUSED")
            self._style_status("paused")
            self.state_label.setText("Review your take")
            self.record_button.setText("  Resume from here")
            self.record_button.setIcon(self.icons.icon("play", "#ffffff", 20))
            self.record_button.setToolTip("Continue recording from the selected waveform position")
            self.pulse_timer.stop()
            self._style_record_button("paused")
            QTimer.singleShot(0, self._load_paused_preview)
        else:
            self.pulse_timer.stop()
            self._pulse_phase = False
            self.record_button.setText("  Start recording")
            self.record_button.setIcon(self.icons.icon("record", "#ffffff", 20))
            self.record_button.setToolTip("Start a new microphone recording")
            self._style_record_button("ready")
            self.stop_button.setEnabled(False)
            self.cancel_button.setEnabled(False)
            self.play_preview_button.setEnabled(False)
            if state == "cancelled":
                self.status_pill.setText("DISCARDED")
                self._style_status("idle")
                self.state_label.setText("Take discarded")
            elif state == "idle" and self.recording_path is None:
                self.status_pill.setText("READY")
                self._style_status("ready")
                self.state_label.setText("Ready when you are")
                self.waveform.set_interactive(False)

    def _neutral_icon_color(self) -> str:
        return self.palette().color(QPalette.ColorRole.ButtonText).name()

    @staticmethod
    def _repolish(widget: QWidget):
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def _style_status(self, state: str):
        self.status_pill.setProperty("state", state)
        self._repolish(self.status_pill)

    def _style_record_button(self, state: str):
        self.record_button.setProperty("state", state)
        self.record_button.setProperty("pulse", False)
        self._repolish(self.record_button)
        self._repolish(self.stop_button)

    def _pulse_record_button(self):
        self._pulse_phase = not self._pulse_phase
        self.record_button.setProperty("pulse", self._pulse_phase)
        self._repolish(self.record_button)

    def _set_duration(self, seconds: float):
        duration = max(0.0, float(seconds))
        self.duration_label.setText(_clock(duration))
        self.total_label.setText(f" / {_clock(duration)}")
        if self.recorder._state == "recording":
            self._preview_duration = duration
            self._preview_position = duration
            self.position_label.setText(_clock(duration))
            self.waveform.set_duration(duration)
            self.waveform.set_position(duration)
        elif self.recorder._state == "paused":
            self._preview_duration = duration
            self.waveform.set_duration(duration)

    def _set_waveform(self, peaks):
        duration = self.recorder.duration()
        self.waveform.set_waveform(peaks, duration)
        if self.recorder._state == "recording":
            self.waveform.set_position(duration)

    def _update_duration(self):
        self._set_duration(self.recorder.duration())

    def _show_error(self, message: str):
        self.timer.stop()
        self.preview_player.stop()
        self.preview_player.clear_source()
        self.status_pill.setText("AUDIO ERROR")
        self._style_status("error")
        self.state_label.setText("Microphone capture stopped")
        self.transport_hint.setText(str(message))
        self.status_message.emit(str(message))
        QMessageBox.warning(self, "Recording interrupted", str(message))

    def shutdown(self):
        self.timer.stop()
        self.pulse_timer.stop()
        self._device_refresh_timer.stop()
        self.preview_player.shutdown()
        self.recorder.shutdown()
