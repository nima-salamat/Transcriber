"""Reusable Qt Multimedia playback controller."""

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer


class AudioPlayer(QObject):
    position_changed = Signal(int)
    duration_changed = Signal(int)
    playback_changed = Signal(bool)
    error_occurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = QMediaPlayer(self)
        self.output = QAudioOutput(self)
        self.player.setAudioOutput(self.output)
        self.output.setVolume(0.75)
        self.player.positionChanged.connect(self.position_changed)
        self.player.durationChanged.connect(self.duration_changed)
        self.player.playbackStateChanged.connect(
            lambda state: self.playback_changed.emit(state == QMediaPlayer.PlayingState)
        )
        self.player.errorOccurred.connect(lambda error, message: self.error_occurred.emit(message))

    def set_source(self, path: str) -> None:
        self.player.setSource(QUrl.fromLocalFile(path))

    def play_pause(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def seek(self, position_ms: int) -> None:
        self.player.setPosition(max(0, int(position_ms)))

    def set_speed(self, speed: float) -> None:
        self.player.setPlaybackRate(max(0.5, min(2.0, float(speed))))

    def set_volume(self, volume: int) -> None:
        self.output.setVolume(max(0, min(100, int(volume))) / 100)

    def shutdown(self) -> None:
        self.player.stop()
