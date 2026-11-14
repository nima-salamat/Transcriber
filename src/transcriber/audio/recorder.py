"""PCM16 WAV microphone recorder based on Qt Multimedia's QAudioSource."""

from __future__ import annotations

import math
import os
import struct
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtMultimedia import QAudioDevice, QAudioFormat, QAudioSource, QMediaDevices, QtAudio

from transcriber.audio.devices import audio_device_id


class QtAudioRecorder(QObject):
    state_changed = Signal(str)
    level_changed = Signal(int)
    duration_changed = Signal(float)
    recording_saved = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source: QAudioSource | None = None
        self._io = None
        self._stream = None
        self._path: Path | None = None
        self._target_path: Path | None = None
        self._format: QAudioFormat | None = None
        self._data_bytes = 0
        self._started = 0.0
        self._elapsed_before_pause = 0.0
        self._state = "idle"
        self._last_duration_emit = 0.0
        # Avoid QAudioSource.stateChanged(QAudio::State) Python slot conversion.
        # The error enum is polled on the GUI event loop instead.
        self._state_watchdog = QTimer(self)
        self._state_watchdog.setInterval(250)
        self._state_watchdog.timeout.connect(self._check_source_error)
        self.device_id: str | None = None
        self.device_name: str | None = None

    @staticmethod
    def devices() -> list[QAudioDevice]:
        return list(QMediaDevices.audioInputs())

    @staticmethod
    def _recording_format(device: QAudioDevice) -> QAudioFormat:
        # Try common mono/stereo rates. Refuse unsupported formats instead of
        # writing bytes into a WAV header that describes a different sample type.
        for rate, channels in ((48000, 1), (44100, 1), (48000, 2), (44100, 2), (16000, 1)):
            audio_format = QAudioFormat()
            audio_format.setSampleRate(rate)
            audio_format.setChannelCount(channels)
            audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            if device.isFormatSupported(audio_format):
                return audio_format
        preferred = device.preferredFormat()
        if preferred.sampleFormat() == QAudioFormat.SampleFormat.Int16:
            return preferred
        raise RuntimeError(
            f"{device.description()} does not expose a supported 16-bit PCM input format. "
            "Choose another microphone or check the system audio settings."
        )

    def start(self, path: Path, device: QAudioDevice | None = None) -> None:
        if self._state in {"recording", "paused"}:
            raise RuntimeError("A recording is already active")
        selected = device if device is not None else QMediaDevices.defaultAudioInput()
        if selected.isNull():
            raise RuntimeError("No microphone is available. Connect an input device and retry.")
        audio_format = self._recording_format(selected)
        target = Path(path).expanduser().resolve()
        if target.suffix.casefold() != ".wav":
            raise ValueError("The Qt microphone recorder writes PCM WAV only. Choose a .wav destination.")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.recording.tmp")
        self._path = temporary
        self._target_path = target
        self._format = audio_format
        self.device_id = audio_device_id(selected)
        self.device_name = str(selected.description())
        self._data_bytes = 0
        self._elapsed_before_pause = 0.0
        self._started = time.monotonic()
        try:
            self._stream = temporary.open("xb")
            self._stream.write(b"\0" * 44)
            source = QAudioSource(selected, audio_format, self)
            source.setBufferSize(max(4096, audio_format.bytesPerFrame() * audio_format.sampleRate() // 5))
            self._source = source
            self._io = source.start()
            if self._io is None:
                raise RuntimeError(f"Microphone could not start: {source.error()}")
            self._io.readyRead.connect(self._read_audio)
            self._state = "recording"
            if source.error() != QtAudio.Error.NoError:
                raise RuntimeError(f"Microphone could not start: {source.error()}")
            self._state_watchdog.start()
            self.state_changed.emit(self._state)
        except Exception:
            self._release_capture()
            if self._stream:
                self._stream.close()
                self._stream = None
            temporary.unlink(missing_ok=True)
            self._path = None
            self._target_path = None
            self._format = None
            self.device_id = None
            self.device_name = None
            self._state = "idle"
            raise

    def _check_source_error(self) -> None:
        source = self._source
        if source is None or self._state not in {"recording", "paused"}:
            self._state_watchdog.stop()
            return
        try:
            error = source.error()
        except RuntimeError:
            # The Qt source is already being destroyed.
            return
        if error == QtAudio.Error.NoError:
            return
        self._state_watchdog.stop()
        # Save complete PCM frames already received; do not leave a dead
        # QAudioSource attached to a UI that still claims to be recording.
        # Emit the error after the idle-state notification so the UI does not
        # immediately overwrite the diagnostic with "Ready to record".
        self._finish_recording(publish=True)
        self.error_occurred.emit(f"Microphone capture failed: {error}")

    def _read_audio(self) -> None:
        if not self._io or not self._stream:
            return
        try:
            chunk = bytes(self._io.readAll())
            frame_bytes = self._format.bytesPerFrame() if self._format else 0
            if frame_bytes > 0:
                chunk = chunk[: len(chunk) - (len(chunk) % frame_bytes)]
            if not chunk:
                return
            self._stream.write(chunk)
            self._data_bytes += len(chunk)
            sample_bytes = len(chunk) - (len(chunk) % 2)
            samples = memoryview(chunk[:sample_bytes]).cast("h")
            if samples:
                rms = math.sqrt(sum(float(sample) ** 2 for sample in samples) / len(samples))
                level = max(0, min(100, int(rms / 32768.0 * 330)))
                self.level_changed.emit(level)
            now = time.monotonic()
            if now - self._last_duration_emit >= 0.1:
                self._last_duration_emit = now
                self.duration_changed.emit(self.duration())
        except (OSError, RuntimeError, ValueError) as exc:
            self._finish_recording(publish=False)
            self.error_occurred.emit(f"Could not write microphone audio: {exc}")

    def duration(self) -> float:
        current = time.monotonic() - self._started if self._state == "recording" else 0.0
        return max(0.0, self._elapsed_before_pause + current)

    def pause(self) -> None:
        if self._state != "recording" or not self._source:
            return
        self._elapsed_before_pause += time.monotonic() - self._started
        self._source.suspend()
        self._state = "paused"
        self.state_changed.emit(self._state)
        self.duration_changed.emit(self.duration())

    def resume(self) -> None:
        if self._state != "paused" or not self._source:
            return
        self._started = time.monotonic()
        self._source.resume()
        self._state = "recording"
        self.state_changed.emit(self._state)

    def stop(self) -> Path | None:
        return self._finish_recording(publish=True)

    def _release_capture(self) -> None:
        self._state_watchdog.stop()
        source, self._source = self._source, None
        io_device, self._io = self._io, None
        if io_device:
            try:
                io_device.readyRead.disconnect(self._read_audio)
            except (RuntimeError, TypeError):
                pass
        if source:
            source.stop()
            source.deleteLater()

    def _finish_recording(self, *, publish: bool) -> Path | None:
        if self._state not in {"recording", "paused"}:
            return None
        if self._state == "recording":
            self._elapsed_before_pause += time.monotonic() - self._started
        self._release_capture()
        saved_path: Path | None = None
        write_error: Exception | None = None
        if self._stream:
            try:
                self._stream.flush()
                audio_format = self._format
                if audio_format:
                    sample_rate = audio_format.sampleRate()
                    channels = audio_format.channelCount()
                    byte_rate = sample_rate * channels * 2
                    block_align = channels * 2
                    # The file header is written only after capture has stopped.
                    header = struct.pack(
                        "<4sI4s4sIHHIIHH4sI",
                        b"RIFF", 36 + self._data_bytes, b"WAVE", b"fmt ", 16,
                        1, channels, sample_rate, byte_rate, block_align, 16,
                        b"data", self._data_bytes,
                    )
                    self._stream.seek(0)
                    self._stream.write(header)
                    self._stream.flush()
                    os.fsync(self._stream.fileno())
            except (OSError, ValueError) as exc:
                write_error = exc
                publish = False
            finally:
                self._stream.close()
                self._stream = None

        self._state = "idle"
        self.level_changed.emit(0)
        self.state_changed.emit(self._state)
        self.duration_changed.emit(self._elapsed_before_pause)
        if write_error:
            self.error_occurred.emit(f"Could not finalize the WAV recording: {write_error}")
        temporary, self._path = self._path, None
        target, self._target_path = self._target_path, None
        if temporary and self._data_bytes > 0 and publish and not write_error and target:
            try:
                os.replace(temporary, target)
                saved_path = target
            except OSError as exc:
                self.error_occurred.emit(f"Could not publish the completed recording: {exc}")
                temporary.unlink(missing_ok=True)
        elif temporary:
            temporary.unlink(missing_ok=True)
        self._format = None
        if saved_path:
            self.recording_saved.emit(str(saved_path))
        return saved_path

    def cancel(self) -> None:
        self._finish_recording(publish=False)
        self._path = None
        self._format = None
        self.state_changed.emit("cancelled")

    def device_disconnected(self) -> None:
        self.stop()
        self.error_occurred.emit("The selected microphone was disconnected")

    def shutdown(self) -> None:
        self.cancel()
