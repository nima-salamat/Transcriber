"""Compact shared audio transport used throughout the unified workspace."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QWidget,
)


def _format_time(milliseconds: int) -> str:
    seconds = max(0, int(milliseconds / 1000))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02}:{minutes:02}:{seconds:02}"
    return f"{minutes:02}:{seconds:02}"


class AudioTransportBar(QWidget):
    """A single transport surface bound to the application's shared AudioPlayer."""

    def __init__(self, player, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AudioTransportBar")
        self.player = player
        self._duration_ms = 0
        self._previous_volume = 75

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(8)

        self.play_button = QPushButton("Play", self)
        self.play_button.setObjectName("TransportPlayButton")
        self.play_button.setFixedWidth(58)
        self.play_button.setToolTip("Play or pause the current media")
        self.play_button.clicked.connect(self.player.play_pause)
        layout.addWidget(self.play_button)

        self.time_label = QLabel("00:00 / 00:00", self)
        self.time_label.setObjectName("Muted")
        self.time_label.setMinimumWidth(102)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.time_label)

        self.seek_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.seek_slider.setObjectName("TransportSeekSlider")
        self.seek_slider.setRange(0, 0)
        self.seek_slider.setSingleStep(250)
        self.seek_slider.setPageStep(1000)
        self.seek_slider.setToolTip("Seek in the current audio")
        self.seek_slider.sliderMoved.connect(self.player.seek)
        layout.addWidget(self.seek_slider, 1)

        self.speed_combo = QComboBox(self)
        self.speed_combo.setObjectName("TransportSpeed")
        self.speed_combo.setToolTip("Playback speed")
        for speed in (0.75, 1.0, 1.25, 1.5, 2.0):
            self.speed_combo.addItem(f"{speed:g}×", speed)
        self.speed_combo.setCurrentIndex(1)
        self.speed_combo.currentIndexChanged.connect(
            lambda: self.player.set_speed(float(self.speed_combo.currentData()))
        )
        self.speed_combo.setFixedWidth(76)
        layout.addWidget(self.speed_combo)

        self.volume_label = QLabel("Vol", self)
        self.volume_label.setObjectName("Muted")
        layout.addWidget(self.volume_label)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.volume_slider.setObjectName("TransportVolume")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(75)
        self.volume_slider.setFixedWidth(78)
        self.volume_slider.setToolTip("Playback volume")
        self.volume_slider.valueChanged.connect(self.player.set_volume)
        layout.addWidget(self.volume_slider)

        self.mute_button = QPushButton("Mute", self)
        self.mute_button.setObjectName("WorkspaceToolButton")
        self.mute_button.setFixedWidth(58)
        self.mute_button.clicked.connect(self.toggle_mute)
        layout.addWidget(self.mute_button)

        self.player.position_changed.connect(self._position_changed)
        self.player.duration_changed.connect(self._duration_changed)
        self.player.playback_changed.connect(self._playback_changed)

        self.set_media_loaded(False)

    def set_media_loaded(self, loaded: bool) -> None:
        loaded = bool(loaded)
        self.play_button.setEnabled(loaded)
        self.seek_slider.setEnabled(loaded)
        self.speed_combo.setEnabled(loaded)
        self.time_label.setEnabled(loaded)
        if not loaded:
            self._duration_ms = 0
            self.seek_slider.setRange(0, 0)
            self.seek_slider.setValue(0)
            self.time_label.setText("00:00 / 00:00")
            self._playback_changed(False)

    def _position_changed(self, position_ms: int) -> None:
        value = max(0, int(position_ms))
        if not self.seek_slider.isSliderDown():
            self.seek_slider.setValue(value)
        self._update_time(value)

    def _duration_changed(self, duration_ms: int) -> None:
        self._duration_ms = max(0, int(duration_ms))
        self.seek_slider.setRange(0, self._duration_ms)
        self._update_time(self.seek_slider.value())

    def _update_time(self, position_ms: int) -> None:
        self.time_label.setText(
            f"{_format_time(position_ms)} / {_format_time(self._duration_ms)}"
        )

    def _playback_changed(self, playing: bool) -> None:
        self.play_button.setText("Pause" if playing else "Play")

    def toggle_mute(self) -> None:
        current = self.volume_slider.value()
        if current == 0:
            self.volume_slider.setValue(max(1, self._previous_volume))
            self.mute_button.setText("Mute")
        else:
            self._previous_volume = current
            self.volume_slider.setValue(0)
            self.mute_button.setText("Unmute")
