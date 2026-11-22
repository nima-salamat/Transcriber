"""Experimental Google Web Speech compatibility engine.

This adapter uses the legacy Chromium-compatible endpoint with the public
shared key shipped by the SpeechRecognition project. It is not an official
or supported Cloud Speech API, may be rate-limited or revoked without notice,
and must only be used for short, non-sensitive personal audio.

Audio is normalized locally to mono 16 kHz FLAC and split into short chunks.
Requests are sent over HTTPS only; insecure redirects are rejected.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from threading import Event
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from transcriber.core.errors import EngineUnavailableError
from transcriber.engines.base import ProgressCallback, TranscriptionEngine
from transcriber.transcription.segments import (
    TranscriptionOptions,
    TranscriptionResult,
    TranscriptSegment,
)

_ENDPOINT = "https://www.google.com/speech-api/v2/recognize"
# This generic Chromium key is intentionally public in SpeechRecognition's
# upstream implementation. It is not a private application credential and
# Google can revoke or rate-limit it at any time.
_SHARED_PUBLIC_KEY = "AIzaSyBOti4mM-6x9WDnZIjIeyEU21OpBXqWBgw"
_CHUNK_SECONDS = 45
_MAX_REQUEST_BYTES = 10 * 1024 * 1024
_REQUEST_TIMEOUT = 60.0
_LANGUAGE_CODES = {
    "en": "en-US",
    "fa": "fa-IR",
    "de": "de-DE",
    "fr": "fr-FR",
    "es": "es-ES",
    "ar": "ar-SA",
    "ru": "ru-RU",
    "zh": "zh-CN",
    "ja": "ja-JP",
}


class _HTTPSOnlyRedirectHandler(HTTPRedirectHandler):
    """Never let a server downgrade an audio upload from HTTPS to plain HTTP."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme.casefold() != "https":
            raise HTTPError(
                newurl, code, "Refusing an insecure redirect for an audio upload", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class GoogleWebSpeechEngine(TranscriptionEngine):
    """Legacy Google Web Speech endpoint; no user account or Cloud project required."""

    engine_id = "google-web-speech"
    display_name = "Google Web Speech (experimental)"

    def __init__(self, *, consent_granted: bool = False, request_timeout: float = _REQUEST_TIMEOUT):
        if not consent_granted:
            raise PermissionError(
                "Google Web Speech sends the selected audio to Google and requires explicit consent."
            )
        self.api_key = (
            os.environ.get("TRANSCRIBER_GOOGLE_WEB_SPEECH_KEY", "").strip()
            or _SHARED_PUBLIC_KEY
        )
        self.request_timeout = max(10.0, min(float(request_timeout), 180.0))
        self._opener = build_opener(_HTTPSOnlyRedirectHandler())

    @staticmethod
    def _run_process(command: list[str], cancel_event: Event, description: str) -> None:
        with tempfile.TemporaryFile() as error_stream:
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
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
                    raise InterruptedError(f"Google Web Speech {description} was cancelled.")

            if process.returncode:
                error_stream.seek(0)
                detail = error_stream.read(4096).decode("utf-8", errors="replace").strip()
                raise RuntimeError(
                    f"FFmpeg could not {description}."
                    + (f" Details: {detail}" if detail else "")
                )

    def _prepare_chunks(
        self, source: Path, directory: Path, cancel_event: Event
    ) -> list[tuple[Path, float]]:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise EngineUnavailableError(
                "FFmpeg is required for Google Web Speech. Install FFmpeg and add it to PATH. "
                "No audio has been sent."
            )
        pattern = directory / "chunk-%06d.wav"
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(source), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", "-f", "segment", "-segment_time", str(_CHUNK_SECONDS),
            "-reset_timestamps", "1", "-segment_format", "wav", str(pattern),
        ]
        self._run_process(command, cancel_event, "prepare the selected audio locally")

        chunks: list[tuple[Path, float]] = []
        for wav_path in sorted(directory.glob("chunk-*.wav")):
            if cancel_event.is_set():
                raise InterruptedError("Google Web Speech audio preparation was cancelled.")
            try:
                with wave.open(str(wav_path), "rb") as audio:
                    if audio.getcomptype() != "NONE" or audio.getsampwidth() != 2:
                        raise RuntimeError("FFmpeg did not produce 16-bit PCM audio.")
                    duration = audio.getnframes() / max(1, audio.getframerate())
            except (wave.Error, OSError) as exc:
                raise RuntimeError(f"Could not read a prepared audio chunk: {exc}") from exc
            if duration <= 0 or duration > _CHUNK_SECONDS + 0.25:
                raise RuntimeError("A prepared Google Web Speech chunk is outside the 45-second limit.")

            flac_path = wav_path.with_suffix(".flac")
            encode_command = [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-i", str(wav_path), "-map", "0:a:0", "-vn", "-c:a", "flac",
                "-compression_level", "5", str(flac_path),
            ]
            self._run_process(encode_command, cancel_event, "encode a Google request as FLAC")
            wav_path.unlink(missing_ok=True)
            if flac_path.stat().st_size > _MAX_REQUEST_BYTES:
                raise RuntimeError("A prepared audio chunk exceeds Google's 10 MB request limit.")
            chunks.append((flac_path, duration))

        if not chunks:
            raise RuntimeError("FFmpeg did not find a usable audio stream in the selected file.")
        return chunks

    def _recognize(self, content: bytes, language: str) -> str:
        query = urlencode({
            "client": "chromium",
            "lang": language,
            "key": self.api_key,
            "pFilter": 0,
        })
        request = Request(
            f"{_ENDPOINT}?{query}",
            data=content,
            headers={
                "Content-Type": "audio/x-flac; rate=16000",
                "User-Agent": "Transcriber/2.1 GoogleWebSpeechCompatibility",
            },
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self.request_timeout) as response:
                payload = response.read(2 * 1024 * 1024 + 1)
        except HTTPError as exc:
            detail = exc.read(1200).decode("utf-8", errors="replace").strip()
            if exc.code in {401, 403, 429}:
                raise RuntimeError(
                    "Google rejected or rate-limited the shared Web Speech key. "
                    "This experimental endpoint is not guaranteed; use Google Cloud V2 "
                    "or a local engine instead."
                    + (f" Google response: {detail}" if detail else "")
                ) from exc
            raise RuntimeError(
                f"Google Web Speech request failed with HTTP {exc.code}."
                + (f" {detail}" if detail else "")
            ) from exc
        except URLError as exc:
            raise RuntimeError(f"Could not reach the Google Web Speech endpoint: {exc.reason}") from exc

        if len(payload) > 2 * 1024 * 1024:
            raise RuntimeError("Google returned an unexpectedly large recognition response.")
        response_text = payload.decode("utf-8", errors="replace")
        transcripts: list[str] = []
        for line in response_text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            error = item.get("error") if isinstance(item, dict) else None
            if error:
                raise RuntimeError(f"Google Web Speech returned an error: {error}")
            for result in item.get("result") or []:
                alternatives = result.get("alternative") or []
                if not alternatives:
                    continue
                best = max(
                    alternatives,
                    key=lambda choice: float(choice.get("confidence") or 0.0),
                )
                value = " ".join(str(best.get("transcript") or "").split())
                if value and (not transcripts or value != transcripts[-1]):
                    transcripts.append(value)

        return " ".join(transcripts).strip()

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
            raise ValueError("Google Web Speech does not provide Whisper translate mode.")
        if not options.language:
            raise ValueError(
                "Choose a specific language for Google Web Speech; automatic detection is not available."
            )

        language = str(options.language).strip()
        if len(language) <= 3:
            language = _LANGUAGE_CODES.get(language.casefold(), language)
        if not language or any(char.isspace() for char in language):
            raise ValueError("The selected speech-recognition language code is invalid.")

        cancel_event = cancel_event or Event()
        if cancel_event.is_set():
            raise InterruptedError("Google Web Speech transcription was cancelled before starting.")
        if progress:
            progress(0.0, "Preparing short audio chunks locally for Google Web Speech")

        with tempfile.TemporaryDirectory(prefix="transcriber-google-web-") as temporary:
            chunks = self._prepare_chunks(source, Path(temporary), cancel_event)
            total_duration = sum(duration for _path, duration in chunks)
            recognized: list[str] = []
            segments: list[TranscriptSegment] = []
            offset = 0.0

            for index, (chunk_path, duration) in enumerate(chunks, start=1):
                if cancel_event.is_set():
                    raise InterruptedError("Google Web Speech transcription was cancelled.")
                content = chunk_path.read_bytes()
                if len(content) > _MAX_REQUEST_BYTES:
                    raise RuntimeError("A Google Web Speech request exceeds the 10 MB limit.")
                if progress:
                    progress(
                        (index - 1) / len(chunks) * 100.0,
                        f"Sending audio chunk {index} of {len(chunks)} to Google Web Speech",
                    )
                transcript = self._recognize(content, language)
                if cancel_event.is_set():
                    raise InterruptedError("Google Web Speech transcription was cancelled.")
                if transcript:
                    recognized.append(transcript)
                    segments.append(TranscriptSegment(
                        start=offset,
                        end=offset + duration,
                        text=transcript,
                        language=language,
                        metadata={
                            "timing_source": "google-web-speech",
                            "timing_precision": "chunk",
                        },
                    ))
                offset += duration
                if progress:
                    progress(
                        index / len(chunks) * 100.0,
                        f"Recognized audio chunk {index} of {len(chunks)}",
                    )

            if progress:
                progress(100.0, "Google Web Speech finished; saving transcript locally")
            return TranscriptionResult(
                text=" ".join(recognized),
                segments=segments,
                language=language,
                duration=total_duration,
            )

    def unload(self) -> None:
        """No resident model or persistent network client is held between jobs."""
        self._opener = build_opener(_HTTPSOnlyRedirectHandler())
