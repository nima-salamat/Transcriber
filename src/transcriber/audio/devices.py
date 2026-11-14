"""Qt Multimedia device discovery and stable device-ID helpers."""

from __future__ import annotations

from PySide6.QtMultimedia import QAudioDevice, QMediaDevices


def audio_device_id(device: QAudioDevice) -> str:
    """Return a stable, lossless string for Qt's opaque QByteArray device ID."""
    raw = device.id()
    if isinstance(raw, str):
        return raw
    try:
        return bytes(raw).hex()
    except (TypeError, ValueError):
        return str(raw)


def audio_input_devices() -> list[QAudioDevice]:
    """Return current QAudioDevice inputs; device objects remain owned by Qt."""
    return list(QMediaDevices.audioInputs())


def audio_output_devices() -> list[QAudioDevice]:
    """Return current output devices."""
    return list(QMediaDevices.audioOutputs())


def default_audio_input() -> QAudioDevice:
    """Return the input selected as default by the operating system."""
    return QMediaDevices.defaultAudioInput()


def default_audio_output() -> QAudioDevice:
    """Return the output selected as default by the operating system."""
    return QMediaDevices.defaultAudioOutput()


def find_audio_input(device_id: str) -> QAudioDevice | None:
    """Resolve a saved input ID against the current Qt device list."""
    if not device_id:
        return default_audio_input()
    return next(
        (device for device in audio_input_devices() if audio_device_id(device) == device_id),
        None,
    )


def find_audio_output(device_id: str) -> QAudioDevice | None:
    """Resolve a saved output ID; an empty ID follows the OS default."""
    if not device_id:
        return default_audio_output()
    return next(
        (device for device in audio_output_devices() if audio_device_id(device) == device_id),
        None,
    )
