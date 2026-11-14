"""Application service for selecting engines and persisting transcription results."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import Event

from transcriber.engines.base import TranscriptionEngine
from transcriber.storage.history import HistoryRepository
from transcriber.transcription.segments import TranscriptionOptions, TranscriptionResult


class TranscriptionService:
    def __init__(self, engine: TranscriptionEngine, history: HistoryRepository | None = None):
        self.engine = engine
        self.history = history

    def transcribe(
        self, audio_path: Path, options: TranscriptionOptions,
        *, cancel_event: Event | None = None,
        progress: Callable[[float, str], None] | None = None,
        title: str | None = None, model_id: str | None = None,
    ) -> TranscriptionResult:
        result = self.engine.transcribe(audio_path, options, cancel_event, progress)
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Transcription cancelled before saving")
        if self.history:
            result.transcript_id = self.history.save(
                title=title or Path(audio_path).stem, text=result.text,
                segments=result.segments, source_path=str(Path(audio_path).resolve()),
                engine=self.engine.engine_id, model_id=model_id,
                language=result.language, duration=result.duration,
                original_text=result.text,
            )
        return result
