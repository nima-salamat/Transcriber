"""Conservative repository compatibility checks for CTranslate2 Whisper models."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable

from transcriber.core.errors import ModelCompatibilityError

_REPO_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_REQUIRED = {"model.bin", "config.json", "tokenizer.json"}
_VOCABULARY = {"vocabulary.txt", "vocabulary.json", "vocab.json"}
_OPTIONAL = {
    "preprocessor_config.json", "normalizer.json", "added_tokens.json",
    "special_tokens_map.json", "generation_config.json", "README.md",
}


@dataclass(frozen=True, slots=True)
class CompatibilityReport:
    compatible: bool
    missing_files: tuple[str, ...] = ()
    included_files: tuple[str, ...] = ()
    reason: str = ""


def validate_repo_id(repo_id: str) -> str:
    value = repo_id.strip()
    if not _REPO_ID.fullmatch(value):
        raise ValueError("Use a Hugging Face repository ID in owner/model-name format")
    return value


def required_model_files(file_names: Iterable[str]) -> list[str]:
    """Return the supported model artefacts, preserving nested file paths."""
    selected: list[str] = []
    for raw in file_names:
        path = PurePosixPath(str(raw))
        if path.is_absolute() or ".." in path.parts:
            continue
        if path.parent != PurePosixPath("."):
            continue
        name = path.name
        if name in _REQUIRED or name in _VOCABULARY or name in _OPTIONAL:
            selected.append(path.as_posix())
    return sorted(set(selected))


def validate_faster_whisper_files(file_names: Iterable[str]) -> CompatibilityReport:
    selected = required_model_files(file_names)
    names = {PurePosixPath(item).name for item in selected}
    missing = sorted(_REQUIRED - names)
    if not names.intersection(_VOCABULARY):
        missing.append("vocabulary.txt or vocabulary.json")
    if missing:
        return CompatibilityReport(
            compatible=False, missing_files=tuple(missing), included_files=tuple(selected),
            reason=("Repository does not contain the required CTranslate2 Faster-Whisper "
                    "artefacts. PyTorch/Transformers Whisper checkpoints are not interchangeable."),
        )
    return CompatibilityReport(
        compatible=True, included_files=tuple(selected),
        reason="Required CTranslate2 model, tokenizer, configuration, and vocabulary files found.",
    )


def require_faster_whisper_compatible(file_names: Iterable[str]) -> CompatibilityReport:
    report = validate_faster_whisper_files(file_names)
    if not report.compatible:
        raise ModelCompatibilityError(report.reason + " Missing: " + ", ".join(report.missing_files))
    return report
