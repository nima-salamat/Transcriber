"""Segment-aware transcript document model.

The model deliberately stays independent from Qt so editing, agents and export
share the exact same validation rules.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace

from transcriber.transcription.segments import TranscriptSegment, TranscriptWord


@dataclass(slots=True)
class TranscriptDocument:
    segments: list[TranscriptSegment] = field(default_factory=list)
    original_text: str = ""
    source_path: str | None = None
    language: str | None = None
    duration: float = 0.0
    revision: int = 0

    def __post_init__(self) -> None:
        self.segments = [
            item if isinstance(item, TranscriptSegment) else TranscriptSegment(**item)
            for item in self.segments
        ]
        self.duration = max(0.0, float(self.duration))
        self.validate()
        if not self.original_text:
            self.original_text = self.text

    @property
    def text(self) -> str:
        return " ".join(item.text.strip() for item in self.segments if item.text.strip())

    def validate(self, *, allow_overlap: bool = True) -> None:
        previous_start = -1.0
        previous_end = -1.0
        for item in self.segments:
            if item.start < 0 or item.end < item.start:
                raise ValueError(f"Invalid time range in segment {item.id}")
            if item.start < previous_start:
                raise ValueError("Segments must be sorted by start time")
            if not allow_overlap and item.start < previous_end:
                raise ValueError("Segments overlap")
            previous_start = item.start
            previous_end = item.end
            for word in item.words or []:
                if word.start < item.start - 0.05 or word.end > item.end + 0.05:
                    raise ValueError(f"Word timestamp falls outside segment {item.id}")

    def get(self, segment_id: str) -> TranscriptSegment:
        for segment in self.segments:
            if segment.id == segment_id:
                return segment
        raise KeyError(segment_id)

    def update_segment(self, segment_id: str, **changes) -> TranscriptSegment:
        current = self.get(segment_id)
        if current.locked:
            raise PermissionError("This segment is locked")
        allowed = {"start", "end", "text", "speaker", "language", "comment", "bookmarked", "reviewed"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"Unsupported segment fields: {', '.join(sorted(unknown))}")
        candidate = replace(current, **changes, is_edited=True)
        if "text" in changes and candidate.text != current.text:
            # Old word boundaries no longer describe the changed content.
            candidate.words = []
        if candidate.end < candidate.start:
            raise ValueError("Segment end time cannot be before its start time")
        previous_index = self.segments.index(current)
        self.segments[previous_index] = candidate
        self.segments.sort(key=lambda item: (item.start, item.end, item.id))
        try:
            self.validate()
        except Exception:
            self.segments.remove(candidate)
            self.segments.insert(previous_index, current)
            self.segments.sort(key=lambda item: (item.start, item.end, item.id))
            raise
        self.revision += 1
        return candidate

    def update_word(self, segment_id: str, word_index: int, *, text: str | None = None,
                    start: float | None = None, end: float | None = None) -> TranscriptWord:
        segment = self.get(segment_id)
        if segment.locked:
            raise PermissionError("This segment is locked")
        words = list(segment.words or [])
        if not 0 <= word_index < len(words):
            raise IndexError(word_index)
        old = words[word_index]
        candidate = replace(
            old,
            text=old.text if text is None else text,
            start=old.start if start is None else start,
            end=old.end if end is None else end,
        )
        if candidate.start < segment.start or candidate.end > segment.end:
            raise ValueError("Word timing must stay inside its segment")
        if word_index and candidate.start < words[word_index - 1].end:
            raise ValueError("Word timing overlaps the previous word")
        if word_index + 1 < len(words) and candidate.end > words[word_index + 1].start:
            raise ValueError("Word timing overlaps the next word")
        words[word_index] = candidate
        segment.words = words
        segment.is_edited = True
        self.revision += 1
        return candidate

    def split_segment(self, segment_id: str, split_at: float) -> tuple[TranscriptSegment, TranscriptSegment]:
        current = self.get(segment_id)
        if current.locked:
            raise PermissionError("This segment is locked")
        split_at = float(split_at)
        if not current.start < split_at < current.end:
            raise ValueError("Split point must be inside the segment")
        left_words = [word for word in current.words or [] if word.end <= split_at]
        right_words = [word for word in current.words or [] if word.start >= split_at]
        if not left_words or not right_words:
            raise ValueError("Choose a split point between two timestamped words")
        left_text = " ".join(word.text.strip() for word in left_words).strip()
        right_text = " ".join(word.text.strip() for word in right_words).strip()
        left = replace(current, end=split_at, text=left_text, words=left_words, is_edited=True)
        right = replace(
            current, id=None, start=split_at, end=current.end, text=right_text,
            words=right_words, is_edited=True, bookmarked=False, comment=None,
        )
        self.segments[self.segments.index(current)] = left
        self.segments.append(right)
        self.segments.sort(key=lambda item: (item.start, item.end))
        self.revision += 1
        self.validate()
        return left, right

    def split_segment_at_text(self, segment_id: str, character_index: int, split_at: float) -> tuple[TranscriptSegment, TranscriptSegment]:
        current = self.get(segment_id)
        if current.locked:
            raise PermissionError("This segment is locked")
        if current.words:
            raise ValueError("Use word-timestamp splitting for a segment with word alignment")
        if not 0 < character_index < len(current.text):
            raise ValueError("Text split point must be inside the segment")
        split_at = float(split_at)
        if not current.start < split_at < current.end:
            raise ValueError("Time split point must be inside the segment")
        first, second = current.text[:character_index].strip(), current.text[character_index:].strip()
        if not first or not second:
            raise ValueError("Both split parts must contain text")
        left = replace(current, text=first, end=split_at, words=[], is_edited=True)
        right = replace(current, id=None, text=second, start=split_at, words=[], is_edited=True,
                        bookmarked=False, comment=None)
        self.segments[self.segments.index(current)] = left
        self.segments.append(right)
        self.segments.sort(key=lambda item: (item.start, item.end))
        self.revision += 1
        self.validate()
        return left, right

    def merge_segments(self, first_id: str, second_id: str, *, allow_gap: bool = True) -> TranscriptSegment:
        first, second = self.get(first_id), self.get(second_id)
        if first is second:
            raise ValueError("Choose two different segments")
        if first.locked or second.locked:
            raise PermissionError("Unlock both segments before merging")
        if second.start < first.start:
            first, second = second, first
        if not allow_gap and second.start > first.end:
            raise ValueError("Segments are separated by a gap")
        speaker = first.speaker if first.speaker == second.speaker else None
        words = list(first.words or []) + list(second.words or [])
        merged = replace(
            first,
            end=max(first.end, second.end),
            text=f"{first.text.rstrip()} {second.text.lstrip()}".strip(),
            speaker=speaker,
            words=words if words else [],
            is_edited=True,
            bookmarked=first.bookmarked or second.bookmarked,
        )
        self.segments = [item for item in self.segments if item.id not in {first.id, second.id}]
        self.segments.append(merged)
        self.segments.sort(key=lambda item: (item.start, item.end))
        self.revision += 1
        self.validate()
        return merged

    def delete_segment(self, segment_id: str) -> None:
        item = self.get(segment_id)
        if item.locked:
            raise PermissionError("This segment is locked")
        self.segments.remove(item)
        self.revision += 1

    def insert_segment(self, segment: TranscriptSegment, *, index: int | None = None) -> None:
        if any(item.id == segment.id for item in self.segments):
            raise ValueError("Segment ID already exists")
        if index is None:
            self.segments.append(segment)
        else:
            self.segments.insert(max(0, min(index, len(self.segments))), segment)
        self.segments.sort(key=lambda item: (item.start, item.end))
        self.revision += 1
        self.validate()

    def set_speaker(self, segment_ids: Iterable[str], speaker: str | None) -> None:
        targets = set(segment_ids)
        locked = [item.id for item in self.segments if item.id in targets and item.locked]
        if locked:
            raise PermissionError(f"Segment {locked[0]} is locked")
        for item in self.segments:
            if item.id in targets:
                item.speaker = speaker
                item.is_edited = True
        if targets:
            self.revision += 1

    def toggle_lock(self, segment_id: str, locked: bool | None = None) -> bool:
        item = self.get(segment_id)
        item.locked = not item.locked if locked is None else bool(locked)
        self.revision += 1
        return item.locked

    def replace_all(self, segments: Iterable[TranscriptSegment]) -> None:
        self.segments = list(segments)
        self.segments.sort(key=lambda item: (item.start, item.end))
        self.revision += 1
        self.validate()
