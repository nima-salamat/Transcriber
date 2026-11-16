"""Media source validation and video audio-stream inspection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

AUDIO_SUFFIXES = {
    ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aiff", ".aif",
}
VIDEO_SUFFIXES = {
    ".mp4", ".m4v", ".mkv", ".mov", ".webm", ".avi",
    ".mpg", ".mpeg", ".mts", ".m2ts", ".ts", ".3gp", ".flv", ".wmv",
}
SUPPORTED_MEDIA_SUFFIXES = AUDIO_SUFFIXES | VIDEO_SUFFIXES
SUPPORTED_AUDIO_SUFFIXES = SUPPORTED_MEDIA_SUFFIXES


@dataclass(frozen=True, slots=True)
class VideoAudioInfo:
    audio_stream_count: int
    duration_seconds: float | None


def is_video_file(path: str | Path) -> bool:
    return Path(path).suffix.casefold() in VIDEO_SUFFIXES


def validate_audio_file(path: Path) -> Path:
    candidate = Path(path).expanduser().resolve()
    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(f"Media file does not exist: {candidate}")
    if candidate.suffix.lower() not in SUPPORTED_MEDIA_SUFFIXES:
        raise ValueError(
            f"Unsupported media extension '{candidate.suffix}'. Supported formats: "
            + ", ".join(sorted(SUPPORTED_MEDIA_SUFFIXES))
        )
    if candidate.stat().st_size == 0:
        raise ValueError("The selected media file is empty")
    return candidate


def inspect_video_audio_stream(path: str | Path) -> VideoAudioInfo:
    """Verify a video has audio before ASR starts; engines decode its first audio stream."""
    candidate = validate_audio_file(Path(path))
    if not is_video_file(candidate):
        raise ValueError(f"Expected a supported video file, received: {candidate.name}")
    try:
        import av
    except ImportError as exc:
        raise RuntimeError(
            "Video transcription requires PyAV. Install the ASR runtime with "
            "python -m pip install -e '.[asr]' and restart Transcriber."
        ) from exc
    try:
        container = av.open(str(candidate))
        with container:
            streams = [
                stream for stream in container.streams
                if getattr(stream, "type", None) == "audio"
            ]
            if not streams:
                raise ValueError(
                    f"No audio track was found in '{candidate.name}'. "
                    "Choose a video that contains audible speech or an audio stream."
                )
            duration = None
            total = getattr(container, "duration", None)
            if total is not None:
                duration = max(0.0, float(total) / float(av.time_base))
            else:
                first = streams[0]
                stream_duration = getattr(first, "duration", None)
                time_base = getattr(first, "time_base", None)
                if stream_duration is not None and time_base is not None:
                    duration = max(0.0, float(stream_duration * time_base))
            return VideoAudioInfo(len(streams), duration)
    except ValueError:
        raise
    except Exception as exc:
        raise RuntimeError(
            f"Could not inspect the audio track in video '{candidate.name}': {exc}"
        ) from exc


def decoder_help() -> str:
    return (
        "Transcriber reads audio files directly and extracts the first audio track "
        "from supported video containers. Video recognition uses installed PyAV/FFmpeg "
        "codecs. The video picture is not rendered in the transcription workspace."
    )
