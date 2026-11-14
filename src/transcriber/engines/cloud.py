"""Optional Google SpeechRecognition adapter, gated behind explicit consent."""

from __future__ import annotations

from pathlib import Path
from threading import Event

from transcriber.core.errors import EngineUnavailableError
from transcriber.engines.base import ProgressCallback, TranscriptionEngine
from transcriber.transcription.segments import TranscriptSegment, TranscriptionOptions, TranscriptionResult


class GoogleCloudEngine(TranscriptionEngine):
    engine_id = "google-cloud"
    display_name = "Google Speech Recognition (online)"

    def __init__(self, *, consent_granted: bool = False):
        if not consent_granted:
            raise PermissionError("Cloud recognition requires explicit consent in Privacy settings")

    def transcribe(self, audio_path: Path, options: TranscriptionOptions,
                   cancel_event: Event | None = None,
                   progress: ProgressCallback | None = None) -> TranscriptionResult:
        try:
            import speech_recognition as sr
        except ImportError as exc:
            raise EngineUnavailableError("Install the optional cloud extra: pip install 'transcriber-desktop[cloud]'") from exc
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Transcription cancelled")
        recognizer = sr.Recognizer()
        path = Path(audio_path)
        temporary_wav = None
        audio = None
        try:
            try:
                with sr.AudioFile(str(path)) as source:
                    audio = recognizer.record(source)
            except (sr.AudioFileError, ValueError):
                try:
                    from pydub import AudioSegment
                except ImportError as exc:
                    raise EngineUnavailableError(
                        "This cloud adapter needs WAV/FLAC input or pydub+FFmpeg to convert this format"
                    ) from exc
                import tempfile
                handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                temporary_wav = Path(handle.name)
                handle.close()
                AudioSegment.from_file(str(path)).export(str(temporary_wav), format="wav")
                with sr.AudioFile(str(temporary_wav)) as source:
                    audio = recognizer.record(source)
        finally:
            if temporary_wav:
                temporary_wav.unlink(missing_ok=True)
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Transcription cancelled")
        # This is an explicit network request; this adapter is never selected implicitly.
        text = recognizer.recognize_google(audio, language=options.language or "en-US")
        if progress:
            progress(100.0, "Complete")
        return TranscriptionResult(text=text, segments=[TranscriptSegment(0, 0, text)])
