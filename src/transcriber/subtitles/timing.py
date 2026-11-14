"""Subtitle timing transforms and standards-oriented quality checks."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable

from transcriber.transcription.segments import TranscriptSegment


@dataclass(frozen=True, slots=True)
class TimingIssue:
    code: str
    severity: str
    segment_ids: tuple[str, ...]
    message: str


def validate_subtitles(
    segments: Iterable[TranscriptSegment], *, min_gap: float = 0.0,
    max_duration: float | None = None, max_chars_per_line: int | None = 42,
    max_chars_per_second: float | None = 20.0,
) -> list[TimingIssue]:
    items = sorted(segments, key=lambda item: (item.start, item.end))
    issues: list[TimingIssue] = []
    for index, item in enumerate(items):
        if not isfinite(item.start) or not isfinite(item.end) or item.start < 0 or item.end <= item.start:
            issues.append(TimingIssue("invalid-duration", "error", (item.id,), "Subtitle must have a finite positive duration"))
            continue
        duration = item.end - item.start
        if max_duration is not None and duration > max_duration:
            issues.append(TimingIssue("duration-limit", "warning", (item.id,), f"Duration {duration:.2f}s exceeds {max_duration:.2f}s"))
        if max_chars_per_line is not None:
            longest = max((len(line) for line in item.text.splitlines()), default=0)
            if longest > max_chars_per_line:
                issues.append(TimingIssue("line-length", "warning", (item.id,), f"Line has {longest} characters (limit {max_chars_per_line})"))
        if max_chars_per_second and len(item.text.strip()) / duration > max_chars_per_second:
            issues.append(TimingIssue("reading-speed", "warning", (item.id,), "Reading speed exceeds the configured characters-per-second limit"))
        if index:
            previous = items[index - 1]
            if item.start < previous.end:
                issues.append(TimingIssue("overlap", "error", (previous.id, item.id), "Subtitle overlaps the previous subtitle"))
            elif item.start - previous.end < min_gap:
                issues.append(TimingIssue("minimum-gap", "warning", (previous.id, item.id), f"Gap is shorter than {min_gap:.3f}s"))
        if not item.text.strip():
            issues.append(TimingIssue("empty-text", "warning", (item.id,), "Subtitle text is empty"))
    return issues


def shift_timestamps(segments: Iterable[TranscriptSegment], offset: float) -> list[TranscriptSegment]:
    from dataclasses import replace
    offset = float(offset)
    return [
        replace(item, start=max(0.0, item.start + offset), end=max(0.0, item.end + offset), is_edited=True)
        for item in segments
    ]


def scale_timestamps(segments: Iterable[TranscriptSegment], source_fps: float, target_fps: float) -> list[TranscriptSegment]:
    from dataclasses import replace
    source_fps, target_fps = float(source_fps), float(target_fps)
    if source_fps <= 0 or target_fps <= 0:
        raise ValueError("Frame rates must be greater than zero")
    factor = source_fps / target_fps
    return [replace(item, start=item.start * factor, end=item.end * factor, is_edited=True) for item in segments]


def apply_minimum_gap(segments: Iterable[TranscriptSegment], min_gap: float) -> list[TranscriptSegment]:
    from dataclasses import replace
    min_gap = max(0.0, float(min_gap))
    output = []
    previous_end = 0.0
    for item in sorted(segments, key=lambda segment: (segment.start, segment.end)):
        start = max(item.start, previous_end + min_gap)
        duration = max(0.0, item.end - item.start)
        candidate = replace(item, start=start, end=start + duration, is_edited=True)
        output.append(candidate)
        previous_end = candidate.end
    return output


def clamp_max_duration(segments: Iterable[TranscriptSegment], maximum: float) -> list[TranscriptSegment]:
    from dataclasses import replace
    maximum = float(maximum)
    if maximum <= 0:
        raise ValueError("Maximum duration must be greater than zero")
    return [
        replace(item, end=min(item.end, item.start + maximum), is_edited=True)
        for item in segments
    ]
