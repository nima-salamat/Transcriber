"""Lazy Faster-Whisper adapter; the optional runtime is imported on demand."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from threading import Event, RLock

from transcriber.core.errors import EngineUnavailableError
from transcriber.engines.base import ProgressCallback, TranscriptionEngine
from transcriber.transcription.segments import (
    TranscriptSegment, TranscriptWord, TranscriptionOptions, TranscriptionResult,
)

logger = logging.getLogger("transcriber.engines.faster_whisper")


class FasterWhisperEngine(TranscriptionEngine):
    engine_id = "faster-whisper"
    display_name = "Faster-Whisper (offline)"

    def __init__(
        self, model_path: Path, *, device: str = "auto", compute_type: str = "int8",
        cpu_threads: int = 0, num_workers: int = 1,
    ):
        self.model_path = Path(model_path)
        self.device = device
        self.compute_type = compute_type
        self.cpu_threads = cpu_threads
        self.num_workers = max(1, num_workers)
        self._model = None
        self._lock = RLock()

    def _load(self):
        if self._model is not None:
            return self._model
        if not self.model_path.is_dir():
            raise FileNotFoundError(f"Model directory does not exist: {self.model_path}")
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise EngineUnavailableError(
                "Faster-Whisper is not installed. Install the 'asr' extra: "
                "pip install 'transcriber-desktop[asr]'"
            ) from exc
        requested_device = self.device
        automatic = requested_device == "auto"
        if automatic:
            try:
                import ctranslate2
                requested_device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            except Exception:
                requested_device = "cpu"
        compute_type = self.compute_type
        if requested_device == "cpu" and compute_type in {"float16", "int8_float16"}:
            compute_type = "int8"
        kwargs = {
            "device": requested_device, "compute_type": compute_type,
            "cpu_threads": self.cpu_threads or max(1, os.cpu_count() or 1),
            "num_workers": self.num_workers,
        }
        logger.info("Loading model %s on %s (%s)", self.model_path.name, requested_device, compute_type)
        try:
            self._model = WhisperModel(str(self.model_path), **kwargs)
        except Exception:
            if not automatic or requested_device != "cuda":
                raise
            logger.warning("Automatic CUDA initialization failed; retrying with CPU INT8", exc_info=True)
            self._model = WhisperModel(
                str(self.model_path), device="cpu", compute_type="int8",
                cpu_threads=kwargs["cpu_threads"], num_workers=self.num_workers,
            )
        return self._model

    def transcribe(
        self, audio_path: Path, options: TranscriptionOptions,
        cancel_event: Event | None = None, progress: ProgressCallback | None = None,
    ) -> TranscriptionResult:
        path = Path(audio_path)
        if not path.is_file():
            raise FileNotFoundError(f"Audio file not found: {path}")
        cancel_event = cancel_event or Event()
        with self._lock:
            model = self._load()
            if cancel_event.is_set():
                raise InterruptedError("Transcription cancelled")
            segments_iter, info = model.transcribe(
                str(path), language=options.language, task=options.task,
                beam_size=options.beam_size, vad_filter=options.vad_filter,
                word_timestamps=options.word_timestamps,
                initial_prompt=options.initial_prompt,
                temperature=options.temperature,
            )
            segments: list[TranscriptSegment] = []
            pieces: list[str] = []
            for segment in segments_iter:
                if cancel_event.is_set():
                    raise InterruptedError("Transcription cancelled")
                words = [
                    TranscriptWord(
                        start=word.start, end=word.end, text=word.word,
                        probability=getattr(word, "probability", None),
                    )
                    for word in (getattr(segment, "words", None) or [])
                    if word.start is not None and word.end is not None
                ]
                segment_text = segment.text.strip()
                if segment_text:
                    segments.append(TranscriptSegment(
                        start=segment.start, end=segment.end, text=segment_text, words=words,
                    ))
                    pieces.append(segment_text)
                if progress and getattr(info, "duration", 0):
                    progress(min(99.0, segment.end / info.duration * 100), "Recognizing audio")
            if progress:
                progress(100.0, "Complete")
            return TranscriptionResult(
                text=" ".join(piece for piece in pieces if piece), segments=segments,
                language=getattr(info, "language", None),
                language_probability=getattr(info, "language_probability", None),
                duration=float(getattr(info, "duration", 0.0) or 0.0),
            )

    def load(self):
        """Load and return the model; call from a worker thread for UI applications."""
        with self._lock:
            return self._load()

    def unload(self) -> None:
        with self._lock:
            self._model = None
