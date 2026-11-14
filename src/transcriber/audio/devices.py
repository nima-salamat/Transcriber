"""Qt Multimedia input device enumeration helpers."""

from __future__ import annotations

from PySide6.QtMultimedia import QMediaDevices


def audio_input_devices():
    """Return current QAudioDevice inputs; device objects remain owned by Qt."""
    return list(QMediaDevices.audioInputs())


def default_audio_input():
    return QMediaDevices.defaultAudioInput()
