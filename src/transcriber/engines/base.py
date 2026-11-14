"""Engine interface independent of Qt and concrete recognition vendors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from threading import Event

from transcriber.transcription.segments import TranscriptionOptions, TranscriptionResult

ProgressCallback = Callable[[float, str], None]


class TranscriptionEngine(ABC):
    engine_id: str
    display_name: str

    @abstractmethod
    def transcribe(
        self, audio_path: Path, options: TranscriptionOptions,
        cancel_event: Event | None = None, progress: ProgressCallback | None = None,
    ) -> TranscriptionResult:
        """Transcribe an audio file and return timestamped segments."""

    def unload(self) -> None:
        """Release accelerator and model memory, when supported."""
