"""Segment-aware search and replace with safe regular-expression handling."""

from __future__ import annotations

import re
from dataclasses import dataclass

from transcriber.editor.document import TranscriptDocument


@dataclass(frozen=True, slots=True)
class SearchMatch:
    segment_id: str
    start: int
    end: int
    text: str


def search(document: TranscriptDocument, query: str, *, regex: bool = False,
           case_sensitive: bool = False) -> list[SearchMatch]:
    if not query:
        return []
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.compile(query if regex else re.escape(query), flags)
    return [
        SearchMatch(item.id, match.start(), match.end(), match.group(0))
        for item in document.segments for match in pattern.finditer(item.text)
    ]


def replace(document: TranscriptDocument, query: str, replacement: str, *, regex: bool = False,
            case_sensitive: bool = False, segment_ids: set[str] | None = None) -> int:
    if not query:
        raise ValueError("Search text cannot be empty")
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.compile(query if regex else re.escape(query), flags)
    changed = 0
    for item in document.segments:
        if segment_ids is not None and item.id not in segment_ids:
            continue
        if item.locked:
            continue
        new_text, count = pattern.subn(replacement, item.text)
        if count:
            item.text = new_text
            item.words = []  # character edits invalidate existing word alignment
            item.is_edited = True
            changed += count
    if changed:
        document.revision += 1
    return changed
