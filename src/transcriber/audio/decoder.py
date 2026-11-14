"""Audio source validation and decoder diagnostics."""

from __future__ import annotations

from pathlib import Path

SUPPORTED_AUDIO_SUFFIXES = {
    ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aiff", ".aif",
    # Faster-Whisper/PyAV and FFmpeg can read the audio stream of common
    # video containers. This does not imply a video editor or preview panel.
    ".mp4", ".m4v", ".mkv", ".mov", ".webm", ".avi",
}


def validate_audio_file(path: Path) -> Path:
    candidate = Path(path).expanduser().resolve()
    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(f"Audio file does not exist: {candidate}")
    if candidate.suffix.lower() not in SUPPORTED_AUDIO_SUFFIXES:
        raise ValueError(
            f"Unsupported audio extension '{candidate.suffix}'. Supported formats: "
            + ", ".join(sorted(SUPPORTED_AUDIO_SUFFIXES))
        )
    if candidate.stat().st_size == 0:
        raise ValueError("The selected audio file is empty")
    return candidate


def decoder_help() -> str:
    return (
        "Faster-Whisper decodes audio through its PyAV/FFmpeg runtime. "
        "Install the ASR extra and verify that the file is readable; some WMA/AAC "
        "variants depend on the codec support bundled with the installed PyAV build."
    )
