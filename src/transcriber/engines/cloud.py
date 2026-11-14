"""Official Google Cloud Speech-to-Text V2 adapter.

Audio is sent only after the caller has explicitly granted consent. Local files
are normalized and split into <=50-second PCM chunks for V2 synchronous
recognition, which avoids hidden Cloud Storage uploads and respects Google's
10 MB / 60-second inline request limits.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from threading import Event

from transcriber.core.errors import EngineUnavailableError
from transcriber.engines.base import ProgressCallback, TranscriptionEngine
from transcriber.transcription.segments import (
    TranscriptionOptions,
    TranscriptionResult,
    TranscriptSegment,
    TranscriptWord,
)

_PROJECT_ID = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_LOCATION = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
_ALLOWED_MODELS = {"chirp_3", "long", "short"}
_MAX_INLINE_BYTES = 10 * 1024 * 1024
_CHUNK_SECONDS = 50


def _duration_seconds(value) -> float | None:
    if value is None:
        return None
    seconds = getattr(value, "seconds", None)
    nanos = getattr(value, "nanos", None)
    if seconds is None:
        return None
    return max(0.0, float(seconds) + float(nanos or 0) / 1_000_000_000)


class GoogleCloudEngine(TranscriptionEngine):
    """Google Cloud Speech-to-Text V2 recognizer using Application Default Credentials."""

    engine_id = "google-cloud-v2"
    display_name = "Google Cloud Speech-to-Text V2 (online)"

    def __init__(
        self,
        *,
        consent_granted: bool = False,
        project_id: str | None = None,
        location: str = "eu",
        model: str = "chirp_3",
        request_timeout: float = 120.0,
    ):
        if not consent_granted:
            raise PermissionError(
                "Cloud recognition requires explicit consent for sending audio to Google."
            )
        self.project_id = (project_id or os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()
        if not self.project_id or not _PROJECT_ID.fullmatch(self.project_id):
            raise ValueError(
                "Set a valid Google Cloud project ID in Settings or GOOGLE_CLOUD_PROJECT."
            )
        self.location = str(location or "eu").strip().casefold()
        if not _LOCATION.fullmatch(self.location):
            raise ValueError("Google Cloud Speech-to-Text location contains invalid characters.")
        self.model = str(model or "chirp_3").strip()
        if self.model not in _ALLOWED_MODELS:
            raise ValueError(f"Unsupported Speech-to-Text V2 model: {self.model}")
        self.request_timeout = max(15.0, min(float(request_timeout), 600.0))
        self._client = None

    @staticmethod
    def verify_credentials(project_id: str | None = None) -> dict[str, str]:
        """Verify ADC token refresh without sending audio or creating cloud resources.

        This confirms local credential availability. Speech API enablement and
        IAM permission are verified by the first real recognition request.
        """
        try:
            import google.auth
            from google.auth.transport.requests import Request
        except ImportError as exc:
            raise EngineUnavailableError(
                "Install the official Cloud Speech client with "
                "pip install 'transcriber-desktop[cloud]'."
            ) from exc
        try:
            credentials, detected_project = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            if not credentials.valid:
                credentials.refresh(Request())
        except Exception as exc:
            raise RuntimeError(
                "Google Application Default Credentials are unavailable. Run "
                "'gcloud auth application-default login' or configure workload identity."
            ) from exc
        resolved_project = (project_id or os.environ.get("GOOGLE_CLOUD_PROJECT")
                            or detected_project or "").strip()
        if not resolved_project or not _PROJECT_ID.fullmatch(resolved_project):
            raise ValueError(
                "Credentials were found, but no valid project ID is configured. "
                "Set it in Transcriber Settings or GOOGLE_CLOUD_PROJECT."
            )
        return {
            "project_id": resolved_project,
            "credential_type": type(credentials).__name__,
            "status": "Application Default Credentials can refresh successfully.",
        }

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from google.api_core.client_options import ClientOptions
            from google.cloud.speech_v2 import SpeechClient
        except ImportError as exc:
            raise EngineUnavailableError(
                "Install the official Google Cloud Speech-to-Text V2 client with "
                "pip install 'transcriber-desktop[cloud]'."
            ) from exc
        endpoint = (
            "speech.googleapis.com"
            if self.location == "global"
            else f"{self.location}-speech.googleapis.com"
        )
        self._client = SpeechClient(client_options=ClientOptions(api_endpoint=endpoint))
        return self._client

    @staticmethod
    def _wav_duration(path: Path) -> tuple[float, int]:
        try:
            with wave.open(str(path), "rb") as stream:
                if stream.getcomptype() != "NONE":
                    raise ValueError("Cloud request chunks must be uncompressed PCM WAV.")
                duration = stream.getnframes() / max(1, stream.getframerate())
        except (wave.Error, OSError) as exc:
            raise RuntimeError(f"FFmpeg produced an unreadable PCM WAV chunk: {exc}") from exc
        size = path.stat().st_size
        if size > _MAX_INLINE_BYTES:
            raise RuntimeError("Prepared audio chunk exceeds Google's 10 MB inline request limit.")
        if duration > 59.0:
            raise RuntimeError("Prepared audio chunk exceeds the 60-second synchronous request limit.")
        return duration, size

    def _prepare_chunks(self, source: Path, directory: Path, cancel_event: Event):
        """Create bounded local WAV requests; no GCS bucket or upload is used."""
        target = directory / "chunk-000000.wav"
        try:
            with wave.open(str(source), "rb") as stream:
                duration = stream.getnframes() / max(1, stream.getframerate())
                valid_pcm = stream.getcomptype() == "NONE" and stream.getsampwidth() == 2
            if valid_pcm and duration <= _CHUNK_SECONDS and source.stat().st_size <= _MAX_INLINE_BYTES:
                shutil.copyfile(source, target)
                chunk_duration, _size = self._wav_duration(target)
                return [(target, chunk_duration)]
        except (wave.Error, OSError):
            pass

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise EngineUnavailableError(
                "FFmpeg is required to normalize or split this audio for Google Cloud Speech-to-Text. "
                "Install FFmpeg and make sure it is available on PATH. No audio has been uploaded."
            )
        if cancel_event.is_set():
            raise InterruptedError("Cloud transcription cancelled before audio preparation.")
        pattern = directory / "chunk-%06d.wav"
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(source), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", "-f", "segment", "-segment_time", str(_CHUNK_SECONDS),
            "-reset_timestamps", "1", "-segment_format", "wav", str(pattern),
        ]
        with tempfile.TemporaryFile() as error_stream:
            try:
                process = subprocess.Popen(
                    command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=error_stream,
                )
            except OSError as exc:
                raise EngineUnavailableError(f"Could not start FFmpeg: {exc}") from exc
            while process.poll() is None:
                if cancel_event.wait(0.15):
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
                    raise InterruptedError("Cloud transcription cancelled during audio preparation.")
            if process.returncode:
                error_stream.seek(0)
                detail = error_stream.read(4096).decode("utf-8", errors="replace").strip()
                raise RuntimeError(
                    "FFmpeg could not decode/prepare the selected audio."
                    + (f" Details: {detail}" if detail else "")
                )
        chunks = []
        for chunk in sorted(directory.glob("chunk-*.wav")):
            if cancel_event.is_set():
                raise InterruptedError("Cloud transcription cancelled after audio preparation.")
            chunk_duration, _size = self._wav_duration(chunk)
            if chunk_duration > _CHUNK_SECONDS + 0.25:
                raise RuntimeError("FFmpeg produced an audio chunk outside the configured size boundary.")
            chunks.append((chunk, chunk_duration))
        if not chunks:
            raise RuntimeError("FFmpeg did not produce an audio stream from the selected file.")
        return chunks

    def _recognize_chunk(self, content: bytes, language: str, word_timestamps: bool):
        from google.cloud.speech_v2.types import cloud_speech

        features = cloud_speech.RecognitionFeatures(
            enable_word_time_offsets=bool(word_timestamps),
            enable_automatic_punctuation=True,
        )
        config = cloud_speech.RecognitionConfig(
            auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
            language_codes=[language],
            model=self.model,
            features=features,
        )
        recognizer = (
            f"projects/{self.project_id}/locations/{self.location}/recognizers/_"
        )
        request = cloud_speech.RecognizeRequest(
            recognizer=recognizer,
            config=config,
            content=content,
        )
        return self._get_client().recognize(
            request=request, timeout=self.request_timeout,
        )

    def transcribe(
        self,
        audio_path: Path,
        options: TranscriptionOptions,
        cancel_event: Event | None = None,
        progress: ProgressCallback | None = None,
    ) -> TranscriptionResult:
        source = Path(audio_path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Audio file not found: {source}")
        if options.task != "transcribe":
            raise ValueError("Google Cloud Speech-to-Text V2 does not implement Whisper translate mode.")
        if not options.language:
            raise ValueError(
                "Choose a specific language for Google Cloud Speech-to-Text V2; "
                "automatic language detection is not configured for this job."
            )
        language = str(options.language)
        if len(language) <= 3:
            language = {
                "en": "en-US", "fa": "fa-IR", "de": "de-DE", "fr": "fr-FR",
                "es": "es-ES", "ar": "ar-SA", "ru": "ru-RU", "zh": "cmn-Hans-CN",
                "ja": "ja-JP",
            }.get(language, language)
        cancel_event = cancel_event or Event()
        if cancel_event.is_set():
            raise InterruptedError("Cloud transcription cancelled before starting.")
        if progress:
            progress(0.0, "Preparing audio locally for Google Cloud Speech-to-Text V2")
        with tempfile.TemporaryDirectory(prefix="transcriber-cloud-") as temporary:
            chunks = self._prepare_chunks(source, Path(temporary), cancel_event)
            total_duration = sum(duration for _path, duration in chunks)
            texts: list[str] = []
            segments: list[TranscriptSegment] = []
            audio_offset = 0.0
            for index, (chunk_path, chunk_duration) in enumerate(chunks, start=1):
                if cancel_event.is_set():
                    raise InterruptedError("Cloud transcription cancelled before the next request.")
                content = chunk_path.read_bytes()
                if len(content) > _MAX_INLINE_BYTES:
                    raise RuntimeError("Prepared request exceeds Google's 10 MB inline audio limit.")
                if progress:
                    progress(
                        (index - 1) / len(chunks) * 100.0,
                        f"Submitting cloud recognition request {index} of {len(chunks)}",
                    )
                try:
                    response = self._recognize_chunk(content, language, options.word_timestamps)
                except Exception:
                    self.unload()
                    raise
                if cancel_event.is_set():
                    raise InterruptedError("Cloud transcription cancelled after a recognition request.")
                previous_result_end = 0.0
                untimed_text: list[str] = []
                for result in response.results:
                    alternatives = getattr(result, "alternatives", None) or []
                    if not alternatives:
                        continue
                    alternative = alternatives[0]
                    transcript = str(getattr(alternative, "transcript", "") or "").strip()
                    if not transcript:
                        continue
                    texts.append(transcript)
                    words = []
                    for word in (getattr(alternative, "words", None) or []):
                        word_start = _duration_seconds(getattr(word, "start_offset", None))
                        word_end = _duration_seconds(getattr(word, "end_offset", None))
                        word_text = str(getattr(word, "word", "") or "")
                        if word_start is None or word_end is None or word_end < word_start:
                            continue
                        words.append(TranscriptWord(
                            start=audio_offset + word_start,
                            end=audio_offset + word_end,
                            text=word_text,
                            probability=(
                                float(word.confidence)
                                if getattr(word, "confidence", None) is not None else None
                            ),
                        ))
                    result_end = _duration_seconds(getattr(result, "result_end_offset", None))
                    if words:
                        segment_start = words[0].start
                        segment_end = max(words[-1].end, audio_offset + (result_end or 0.0))
                    elif result_end is not None and result_end > previous_result_end:
                        segment_start = audio_offset + previous_result_end
                        segment_end = audio_offset + result_end
                    else:
                        untimed_text.append(transcript)
                        continue
                    if segment_end < segment_start:
                        untimed_text.append(transcript)
                        continue
                    segments.append(TranscriptSegment(
                        start=segment_start,
                        end=segment_end,
                        text=transcript,
                        words=words,
                        metadata={"timing_source": "google-cloud-speech-v2"},
                    ))
                    if result_end is not None:
                        previous_result_end = max(previous_result_end, result_end)
                    elif words:
                        previous_result_end = max(previous_result_end, words[-1].end - audio_offset)
                if untimed_text:
                    # The source chunk's actual boundaries are known; this is
                    # explicitly marked as chunk-level, not phrase/word timing.
                    segments.append(TranscriptSegment(
                        start=audio_offset,
                        end=audio_offset + chunk_duration,
                        text=" ".join(untimed_text),
                        metadata={
                            "timing_source": "google-cloud-speech-v2",
                            "timing_precision": "chunk",
                        },
                    ))
                audio_offset += chunk_duration
                if progress:
                    progress(
                        index / len(chunks) * 100.0,
                        f"Recognized chunk {index} of {len(chunks)}",
                    )
            if self._client is not None:
                self._client.close()
                self._client = None
            if progress:
                progress(100.0, "Cloud recognition complete; saving transcript locally")
            return TranscriptionResult(
                text=" ".join(texts),
                segments=segments,
                language=language,
                duration=total_duration,
            )

    def unload(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
