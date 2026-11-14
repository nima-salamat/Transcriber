"""Deterministic text cleanup suggestions; callers preview before applying."""

from __future__ import annotations

import re
from dataclasses import dataclass

from transcriber.editor.document import TranscriptDocument


@dataclass(frozen=True, slots=True)
class CleanupChange:
    segment_id: str
    before: str
    after: str
    reasons: tuple[str, ...]


_FILLERS = {
    "en": {"um", "uh", "erm", "uhh"},
    "fa": {"اِ", "اُم", "اِم"},
}


def _clean_text(text: str, language: str | None, actions: set[str]) -> tuple[str, list[str]]:
    result = text
    reasons: list[str] = []
    if "repeated" in actions:
        cleaned = re.sub(r"\b([\w'-]+)(\s+\1\b)+", r"\1", result, flags=re.IGNORECASE)
        if cleaned != result:
            result = cleaned
            reasons.append("repeated words")
    if "filler" in actions:
        words = _FILLERS.get((language or "").split("-")[0], _FILLERS["en"])
        if words:
            pattern = r"(?i)(?<!\w)(?:" + "|".join(re.escape(word) for word in sorted(words, key=len, reverse=True)) + r")(?!\w)[, ]*"
            cleaned = re.sub(pattern, "", result)
            if cleaned != result:
                result = cleaned
                reasons.append("filler words")
    if "spaces" in actions:
        cleaned = re.sub(r"[ \t]{2,}", " ", result).strip()
        if cleaned != result:
            result = cleaned
            reasons.append("spacing")
    if "punctuation" in actions:
        cleaned = re.sub(r"\s+([,.;:!?؟،])", r"\1", result)
        cleaned = re.sub(r"([,.;:!?؟،])(?=\S)", r"\1 ", cleaned)
        if cleaned != result:
            result = cleaned
            reasons.append("punctuation spacing")
    if "duplicate-sentences" in actions:
        cleaned = re.sub(r"([^.!?؟]+[.!?؟])(?:\s+\1)+", r"\1", result, flags=re.IGNORECASE)
        if cleaned != result:
            result = cleaned
            reasons.append("duplicate sentence")
    return result, reasons


def preview_cleanup(document: TranscriptDocument, actions: set[str]) -> list[CleanupChange]:
    preview: list[CleanupChange] = []
    for item in document.segments:
        if item.locked:
            continue
        cleaned, reasons = _clean_text(item.text, item.language or document.language, actions)
        if cleaned != item.text:
            preview.append(CleanupChange(item.id, item.text, cleaned, tuple(reasons)))
    return preview


def apply_cleanup(document: TranscriptDocument, changes: list[CleanupChange]) -> int:
    # Validate the complete preview before applying any change. A stale item
    # must never leave the user with a partially cleaned transcript.
    for change in changes:
        item = document.get(change.segment_id)
        if item.locked:
            continue
        if item.text != change.before:
            raise RuntimeError(f"Segment {item.id} changed after preview; regenerate the preview")
    count = 0
    for change in changes:
        item = document.get(change.segment_id)
        if item.locked:
            continue
        item.text = change.after
        item.words = []
        item.is_edited = True
        count += 1
    if count:
        document.revision += 1
    return count
