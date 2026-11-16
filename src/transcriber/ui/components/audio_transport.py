"""Compact shared playback controls for the unified workspace."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
)

from transcriber.audio.player import AudioPlayer


class AudioTransportBar(QFrame):
    """A view over the workspace's single AudioPlayer controller."""

    def __init__(self, player: AudioPlayer, parent=None):
        super().__init__(parent)
        self.player = player
        self._duration_ms = 0
        self.setObjectName("AudioTransportBar")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 7, 12, 7)
        layout.setSpacing(10)

        self.play_button = QPushButton("▶")
        self.play_button.setObjectName("TransportPlay")
        self.play_button.setFixedSize(36, 34)
        self.play_button.setToolTip("Play or pause audio")
        self.play_button.setAccessibleName("Play or pause audio")
        self.play_button.clicked.connect(self.player.play_pause)
        layout.addWidget(self.play_button)

        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.setToolTip("Seek through the current audio")
        self.position_slider.setAccessibleName("Audio position")
        self.position_slider.sliderMoved.connect(self.player.seek)
        layout.addWidget(self.position_slider, 1)

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setObjectName("Muted")
        self.time_label.setMinimumWidth(105)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.time_label)

        self.status_label = QLabel("No audio loaded")
        self.status_label.setObjectName("Muted")
        self.status_label.setMinimumWidth(90)
        self.status_label.setMaximumWidth(170)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.status_label.setToolTip("Audio playback status")
        layout.addWidget(self.status_label)

        self.speed_combo = QComboBox()
        for speed in (0.75, 1.0, 1.25, 1.5, 2.0):
            self.speed_combo.addItem(f"{speed:g}×", speed)
        self.speed_combo.setCurrentIndex(1)
        self.speed_combo.setMaximumWidth(84)
        self.speed_combo.setToolTip("Playback speed")
        self.speed_combo.currentIndexChanged.connect(
            lambda: self.player.set_speed(self.speed_combo.currentData())
        )
        layout.addWidget(self.speed_combo)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(75)
        self.volume_slider.setMaximumWidth(88)
        self.volume_slider.setToolTip("Playback volume")
        self.volume_slider.setAccessibleName("Playback volume")
        self.volume_slider.valueChanged.connect(self.player.set_volume)
        layout.addWidget(self.volume_slider)

        self.player.playback_changed.connect(self._on_playback_changed)
        self.player.position_changed.connect(self._on_position_changed)
        self.player.duration_changed.connect(self._on_duration_changed)
        self.player.status_changed.connect(self.status_label.setText)

        self.set_media_loaded("")

    @staticmethod
    def _format_time(milliseconds: int) -> str:
        total_seconds = max(0, int(milliseconds // 1000))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours:02}:{minutes:02}:{seconds:02}"
        return f"{minutes:02}:{seconds:02}"

    def _on_playback_changed(self, playing: bool):
        self.play_button.setText("Ⅱ" if playing else "▶")
        self.play_button.setToolTip("Pause audio" if playing else "Play audio")

    def _on_position_changed(self, position_ms: int):
        if not self.position_slider.isSliderDown():
            self.position_slider.blockSignals(True)
            self.position_slider.setValue(max(0, int(position_ms)))
            self.position_slider.blockSignals(False)
        self._update_time_label(position_ms)

    def _on_duration_changed(self, duration_ms: int):
        self._duration_ms = max(0, int(duration_ms))
        self.position_slider.setRange(0, self._duration_ms)
        self._update_time_label(self.position_slider.value())

    def _update_time_label(self, position_ms: int):
        self.time_label.setText(
            f"{self._format_time(position_ms)} / {self._format_time(self._duration_ms)}"
        )

    def set_media_loaded(self, path: str):
        loaded = bool(str(path or "").strip())
        self.setVisible(loaded)
        self.setEnabled(loaded)
        if not loaded:
            self._duration_ms = 0
            self.position_slider.setRange(0, 0)
            self.position_slider.setValue(0)
            self._update_time_label(0)
            self._on_playback_changed(False)
