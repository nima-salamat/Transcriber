"""Safe collection and validation of media paths for batch import."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from transcriber.audio.decoder import validate_audio_file


@dataclass(frozen=True, slots=True)
class MediaImportReport:
    accepted: tuple[Path, ...]
    rejected: tuple[tuple[str, str], ...]
    duplicates: tuple[str, ...]


def _identity(path: Path) -> str:
    return os.path.normcase(str(path.resolve())).casefold()


def collect_media_paths(paths, *, existing_paths=()) -> MediaImportReport:
    """Expand directories, validate supported non-empty files and de-duplicate.

    Directory traversal is deterministic. Rejected inputs retain their original
    display path and a concise reason so the UI can report every skipped item.
    """
    accepted: list[Path] = []
    rejected: list[tuple[str, str]] = []
    duplicates: list[str] = []
    seen = set()

    for existing in existing_paths:
        try:
            seen.add(_identity(Path(existing).expanduser()))
        except (OSError, RuntimeError, ValueError):
            continue

    candidates: list[tuple[str, Path]] = []
    for raw in paths or ():
        display = str(raw)
        try:
            candidate = Path(raw).expanduser()
            if not candidate.exists():
                rejected.append((display, "Path does not exist"))
                continue
            if candidate.is_dir():
                try:
                    discovered = sorted(
                        (item for item in candidate.rglob("*") if item.is_file()),
                        key=lambda item: str(item).casefold(),
                    )
                except OSError as exc:
                    rejected.append((display, f"Cannot scan directory: {exc}"))
                    continue
                supported = []
                for item in discovered:
                    if item.suffix.casefold() in {
                        ".wav",
                        ".mp3",
                        ".m4a",
                        ".aac",
                        ".flac",
                        ".ogg",
                        ".opus",
                        ".wma",
                        ".aiff",
                        ".aif",
                        ".mp4",
                        ".m4v",
                        ".mkv",
                        ".mov",
                        ".webm",
                        ".avi",
                    }:
                        supported.append(item)
                if not supported:
                    rejected.append((display, "Directory contains no supported media files"))
                else:
                    candidates.extend((str(item), item) for item in supported)
            else:
                candidates.append((display, candidate))
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            rejected.append((display, f"Invalid path: {exc}"))

    for display, candidate in candidates:
        try:
            valid = validate_audio_file(candidate)
            identity = _identity(valid)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            rejected.append((display, str(exc)))
            continue
        if identity in seen:
            duplicates.append(display)
            continue
        seen.add(identity)
        accepted.append(valid)

    return MediaImportReport(tuple(accepted), tuple(rejected), tuple(duplicates))
