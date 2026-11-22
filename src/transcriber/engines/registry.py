"""Construction of configured recognition engines."""

from pathlib import Path

from transcriber.core.errors import EngineUnavailableError
from transcriber.engines.cloud import GoogleCloudEngine
from transcriber.engines.faster_whisper import FasterWhisperEngine
from transcriber.engines.google_web import GoogleWebSpeechEngine


class EngineRegistry:
    def create(self, engine_id: str, *, model_path: Path | None = None,
               settings=None, cloud_consent: bool = False):
        if engine_id == "faster-whisper":
            if model_path is None:
                raise ValueError("A local Faster-Whisper model must be installed and selected")
            return FasterWhisperEngine(
                model_path, device=getattr(settings, "device", "auto"),
                compute_type=getattr(settings, "compute_type", "int8"),
                cpu_threads=getattr(settings, "cpu_threads", 0),
            )
        if engine_id == "google-cloud":
            return GoogleCloudEngine(
                consent_granted=cloud_consent,
                project_id=getattr(settings, "google_cloud_project", None),
                location=getattr(settings, "google_cloud_location", "eu"),
                model=getattr(settings, "google_cloud_model", "chirp_3"),
            )
        if engine_id == "google-web":
            return GoogleWebSpeechEngine(consent_granted=cloud_consent)
        raise EngineUnavailableError(f"Unsupported transcription engine: {engine_id}")
