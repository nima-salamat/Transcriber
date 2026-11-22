"""Evidence-based transcript quality report.

The report derives warnings only from timestamp/text/word-confidence data that
is actually present. It never invents an ASR confidence value.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass

from transcriber.transcription.segments import TranscriptionResult, TranscriptSegment


@dataclass(frozen=True, slots=True)
class QualityIssue:
    code: str
    severity: str
    segment_ids: tuple[str, ...]
    message: str


@dataclass(frozen=True, slots=True)
class QualityReport:
    language: str | None
    language_probability: float | None
    audio_duration: float
    segment_count: int
    word_count: int
    speaker_count: int
    silence_regions: tuple[tuple[float, float], ...]
    duplicate_segment_ids: tuple[str, ...]
    mean_word_confidence: float | None
    low_confidence_word_count: int
    issues: tuple[QualityIssue, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def build_quality_report(
    result: TranscriptionResult | None = None,
    *,
    segments: Iterable[TranscriptSegment] | None = None,
    language: str | None = None,
    language_probability: float | None = None,
    duration: float | None = None,
    silence_threshold: float = 0.8,
    low_confidence_threshold: float = 0.45,
) -> QualityReport:
    if result is not None:
        source = list(result.segments)
        language = result.language
        language_probability = result.language_probability
        duration = result.duration
    else:
        source = list(segments or [])
    items = sorted(source, key=lambda item: (item.start, item.end, item.id))
    audio_duration = max(0.0, float(duration or max((item.end for item in items), default=0.0)))
    silence: list[tuple[float, float]] = []
    issues: list[QualityIssue] = []
    duplicate_ids: list[str] = []
    normalized: dict[str, list[str]] = {}
    confidences: list[float] = []
    low_count = 0

    for item in items:
        normalized_text = re.sub(r"\W+", " ", item.text.casefold(), flags=re.UNICODE).strip()
        if not normalized_text:
            issues.append(QualityIssue("empty-segment", "warning", (item.id,), "Segment has no recognized text"))
        else:
            normalized.setdefault(normalized_text, []).append(item.id)
        for word in item.words or []:
            if word.probability is not None:
                confidence = max(0.0, min(1.0, float(word.probability)))
                confidences.append(confidence)
                if confidence < low_confidence_threshold:
                    low_count += 1

    for duplicate_group in normalized.values():
        if len(duplicate_group) > 1:
            duplicate_ids.extend(duplicate_group)
            issues.append(QualityIssue(
                "duplicate-segment", "warning", tuple(duplicate_group),
                "Identical normalized text appears in multiple segments; review for repeated recognition.",
            ))

    previous = None
    for item in items:
        if previous is not None:
            gap_start = max(0.0, previous.end)
            gap_end = max(gap_start, item.start)
            if gap_end - gap_start >= max(0.1, float(silence_threshold)):
                silence.append((gap_start, gap_end))
        previous = item
    if low_count:
        issues.append(QualityIssue(
            "low-word-confidence", "warning",
            tuple(item.id for item in items if any(
                word.probability is not None and word.probability < low_confidence_threshold
                for word in (item.words or [])
            )),
            f"{low_count} word(s) have engine-provided confidence below {low_confidence_threshold:.2f}.",
        ))

    if items and audio_duration > 0 and items[-1].end > audio_duration + 0.25:
        issues.append(QualityIssue(
            "timestamp-overrun", "error", (items[-1].id,),
            "The final segment extends beyond the reported media duration.",
        ))
    if not items:
        issues.append(QualityIssue("no-segments", "error", (), "No transcript segments were produced."))

    speakers = {item.speaker for item in items if item.speaker}
    word_count = sum(len((item.text or "").split()) for item in items)
    return QualityReport(
        language=language,
        language_probability=(float(language_probability) if language_probability is not None else None),
        audio_duration=audio_duration,
        segment_count=len(items),
        word_count=word_count,
        speaker_count=len(speakers),
        silence_regions=tuple(silence),
        duplicate_segment_ids=tuple(dict.fromkeys(duplicate_ids)),
        mean_word_confidence=(sum(confidences) / len(confidences) if confidences else None),
        low_confidence_word_count=low_count,
        issues=tuple(issues),
    )
