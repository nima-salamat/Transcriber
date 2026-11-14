"""Lazy Vosk/Kaldi adapter for local, offline file transcription."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import Event, RLock

from transcriber.core.errors import EngineUnavailableError
from transcriber.engines.base import ProgressCallback, TranscriptionEngine
from transcriber.transcription.segments import (
    TranscriptionOptions,
    TranscriptionResult,
    TranscriptSegment,
    TranscriptWord,
)

logger = logging.getLogger("transcriber.engines.vosk")


class VoskEngine(TranscriptionEngine):
    engine_id = "vosk"
    display_name = "Vosk (offline)"

    def __init__(self, model_path: Path, *, language: str | None = None):
        self.model_path = Path(model_path).expanduser().resolve()
        self.language = str(language) if language else None
        self._model = None
        self._lock = RLock()

    def load(self):
        with self._lock:
            if self._model is not None:
                return self._model
            if not self.model_path.is_dir():
                raise FileNotFoundError(f"Vosk model directory does not exist: {self.model_path}")
            try:
                from vosk import Model
            except ImportError as exc:
                raise EngineUnavailableError(
                    "Vosk is not installed. Install local Vosk support with: "
                    "pip install 'transcriber-desktop[voice]'"
                ) from exc
            logger.info("Loading Vosk model %s", self.model_path.name)
            try:
                self._model = Model(str(self.model_path))
            except Exception as exc:
                raise EngineUnavailableError(
                    f"Vosk could not load the installed model {self.model_path.name}: {exc}"
                ) from exc
            return self._model

    @staticmethod
    def _decode_result(raw: str, language: str | None) -> TranscriptSegment | None:
        try:
            payload = json.loads(raw or "{}")
        except (TypeError, ValueError):
            return None
        text = " ".join(str(payload.get("text") or "").split())
        if not text:
            return None
        words = []
        for item in payload.get("result") or []:
            try:
                word = str(item.get("word") or "").strip()
                start = float(item["start"])
                end = float(item["end"])
                confidence = float(item["conf"]) if item.get("conf") is not None else None
            except (KeyError, TypeError, ValueError):
                continue
            if word and end >= start >= 0:
                words.append(TranscriptWord(start, end, word, confidence))
        if words:
            start, end = words[0].start, words[-1].end
        else:
            # Vosk's word list is normally present after SetWords(True). Preserve
            # text even for a runtime/model variant that returns no word details.
            return None
        return TranscriptSegment(
            start=start,
            end=end,
            text=text,
            words=words,
            language=language,
            metadata={"engine": "vosk"},
        )

    def transcribe(
        self,
        audio_path: Path,
        options: TranscriptionOptions,
        cancel_event: Event | None = None,
        progress: ProgressCallback | None = None,
    ) -> TranscriptionResult:
        path = Path(audio_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Audio file not found: {path}")
        if options.task != "transcribe":
            raise ValueError("Vosk models support transcription, not Whisper's translate task.")
        cancel_event = cancel_event or Event()
        try:
            import av
            from vosk import KaldiRecognizer
        except ImportError as exc:
            raise EngineUnavailableError(
                "Vosk file transcription requires the optional voice extra, including PyAV. "
                "Install it with: pip install 'transcriber-desktop[voice]'"
            ) from exc

        with self._lock:
            model = self.load()
            try:
                container = av.open(str(path))
            except Exception as exc:
                raise RuntimeError(f"Could not decode audio for Vosk: {exc}") from exc
            with container:
                audio_stream = next(
                    (stream for stream in container.streams if stream.type == "audio"),
                    None,
                )
                if audio_stream is None:
                    raise ValueError("The selected file does not contain an audio stream.")

                duration = 0.0
                if container.duration is not None:
                    duration = max(0.0, float(container.duration) / float(av.time_base))
                elif audio_stream.duration is not None and audio_stream.time_base is not None:
                    duration = max(
                        0.0,
                        float(audio_stream.duration * audio_stream.time_base),
                    )

                recognizer = KaldiRecognizer(model, 16_000)
                recognizer.SetWords(True)
                resampler = av.AudioResampler(format="s16", layout="mono", rate=16_000)
                segments: list[TranscriptSegment] = []
                text_parts: list[str] = []
                last_position = 0.0

                def collect(raw: str) -> None:
                    segment = self._decode_result(raw, self.language)
                    if segment is not None:
                        segments.append(segment)
                        text_parts.append(segment.text)

                for frame in container.decode(audio_stream):
                    if cancel_event.is_set():
                        raise InterruptedError("Vosk transcription cancelled")
                    if frame.pts is not None and frame.time_base is not None:
                        last_position = max(last_position, float(frame.pts * frame.time_base))
                    for converted in resampler.resample(frame):
                        pcm = converted.to_ndarray().tobytes()
                        if recognizer.AcceptWaveform(pcm):
                            collect(recognizer.Result())
                    if progress and duration > 0:
                        progress(
                            min(99.0, last_position / duration * 100.0),
                            "Vosk is recognizing audio locally",
                        )

                for converted in resampler.resample(None):
                    if cancel_event.is_set():
                        raise InterruptedError("Vosk transcription cancelled")
                    if recognizer.AcceptWaveform(converted.to_ndarray().tobytes()):
                        collect(recognizer.Result())
                if cancel_event.is_set():
                    raise InterruptedError("Vosk transcription cancelled")
                collect(recognizer.FinalResult())

                final_duration = max(
                    duration,
                    max((segment.end for segment in segments), default=0.0),
                )
                if progress:
                    progress(100.0, "Complete")
                return TranscriptionResult(
                    text=" ".join(text_parts),
                    segments=segments,
                    language=self.language,
                    language_probability=None,
                    duration=final_duration,
                )

    def unload(self) -> None:
        with self._lock:
            self._model = None
