"""Reusable Qt Multimedia playback controller."""

from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer

from transcriber.audio.devices import audio_device_id


class AudioPlayer(QObject):
    position_changed = Signal(int)
    duration_changed = Signal(int)
    playback_changed = Signal(bool)
    status_changed = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = QMediaPlayer(self)
        self.output = QAudioOutput(self)
        self._devices = QMediaDevices(self)
        self._source_path: Path | None = None
        self._output_available = False
        self._preferred_output_device_id = ""

        self.player.setAudioOutput(self.output)
        self.output.setVolume(0.75)
        self._select_output_device()
        self._devices.audioOutputsChanged.connect(self._select_output_device)

        # Bridge Qt integer signals into the public Python API.
        self.player.positionChanged.connect(
            lambda position: self.position_changed.emit(int(position))
        )
        self.player.durationChanged.connect(
            lambda duration: self.duration_changed.emit(int(duration))
        )
        self.player.playbackStateChanged.connect(self._on_playback_state_changed)
        self.player.mediaStatusChanged.connect(
            lambda status: self._on_media_status(status)
        )
        self.player.errorOccurred.connect(
            lambda error, message: self._on_player_error(error, message)
        )

    @staticmethod
    def _enum_name(value) -> str:
        return str(getattr(value, "name", None) or value).split(".")[-1]


    def set_output_device(self, device_id: str | None) -> bool:
        """Apply a saved output device preference; an empty ID means system default."""
        self._preferred_output_device_id = str(device_id or "")
        return self._select_output_device()

    def _select_output_device(self, *_args) -> bool:
        """Apply the preferred output device, falling back to the current system default."""
        try:
            device = None
            if self._preferred_output_device_id:
                device = next(
                    (
                        item for item in QMediaDevices.audioOutputs()
                        if audio_device_id(item) == self._preferred_output_device_id
                    ),
                    None,
                )
            preferred_missing = bool(self._preferred_output_device_id and device is None)
            if device is None:
                device = QMediaDevices.defaultAudioOutput()
            if device is None or device.isNull():
                self._output_available = False
                self.status_changed.emit("No audio output device is available")
                return False
            if self.output.device() != device:
                self.output.setDevice(device)
            self._output_available = True
            if preferred_missing:
                self.status_changed.emit(
                    "Saved playback device is unavailable; using the system default output"
                )
            return True
        except (RuntimeError, TypeError, ValueError) as exc:
            self._output_available = False
            self.status_changed.emit(f"Audio output unavailable: {exc}")
            return False

    def set_source(self, path: str) -> None:
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            self.clear_source()
            message = f"Audio file is unavailable: {source}"
            self.status_changed.emit(message)
            self.error_occurred.emit(message)
            return

        self.player.stop()
        self._source_path = source
        self.player.setSource(QUrl.fromLocalFile(str(source)))
        self.status_changed.emit("Loading audio…")
        self._select_output_device()

    def clear_source(self) -> None:
        self.player.stop()
        self._source_path = None
        self.player.setSource(QUrl())
        self.duration_changed.emit(0)
        self.position_changed.emit(0)
        self.playback_changed.emit(False)
        self.status_changed.emit("No audio loaded")

    def stop(self) -> None:
        """Stop playback without clearing the currently loaded source."""
        self.player.stop()

    def play_pause(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.status_changed.emit("Paused")
            return
        if self._source_path is None or not self._source_path.is_file():
            message = "Choose an available audio file before playback."
            self.status_changed.emit(message)
            self.error_occurred.emit(message)
            return
        if not self._select_output_device():
            message = "Qt Multimedia cannot find a usable audio output device."
            self.error_occurred.emit(message)
            return
        if self._enum_name(self.player.mediaStatus()) == "EndOfMedia":
            self.player.setPosition(0)
        self.status_changed.emit("Starting playback…")
        self.player.play()

    def _on_playback_state_changed(self, state) -> None:
        playing = state == QMediaPlayer.PlayingState
        self.playback_changed.emit(playing)
        if playing:
            self.status_changed.emit("Playing")
        elif self._source_path is not None:
            media_status = self._enum_name(self.player.mediaStatus())
            if media_status == "EndOfMedia":
                self.status_changed.emit("Finished")
            elif media_status not in {"LoadingMedia", "BufferingMedia", "StalledMedia"}:
                self.status_changed.emit("Paused")

    def _on_media_status(self, status) -> None:
        name = self._enum_name(status)
        labels = {
            "NoMedia": "No audio loaded",
            "LoadingMedia": "Loading audio…",
            "LoadedMedia": "Audio ready",
            "BufferingMedia": "Buffering audio…",
            "BufferedMedia": "Audio ready",
            "StalledMedia": "Audio playback stalled",
            "EndOfMedia": "Finished",
            "InvalidMedia": "Unsupported or unreadable audio format",
        }
        label = labels.get(name, f"Audio status: {name}")
        self.status_changed.emit(label)
        if name == "InvalidMedia":
            self.error_occurred.emit(
                "Qt Multimedia could not decode this audio file. Check the Qt FFmpeg/media backend and file codec."
            )

    def _on_player_error(self, error, message: str) -> None:
        detail = str(message or "").strip() or self._enum_name(error)
        self.status_changed.emit(f"Playback error: {detail}")
        self.error_occurred.emit(f"{self._enum_name(error)}: {detail}")

    def seek(self, position_ms: int) -> None:
        self.player.setPosition(max(0, int(position_ms)))

    def set_speed(self, speed: float) -> None:
        self.player.setPlaybackRate(max(0.5, min(2.0, float(speed))))

    def set_volume(self, volume: int) -> None:
        self.output.setVolume(max(0, min(100, int(volume))) / 100)

    def shutdown(self) -> None:
        self.player.stop()
