"""Shared transcript data structures."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(slots=True)
class TranscriptWord:
    start: float
    end: float
    text: str
    probability: float | None = None

    def __post_init__(self) -> None:
        self.start = max(0.0, float(self.start))
        self.end = max(self.start, float(self.end))
        self.text = str(self.text)
        if self.probability is not None:
            self.probability = max(0.0, min(1.0, float(self.probability)))


@dataclass(slots=True)
class TranscriptSegment:
    start: float
    end: float
    text: str
    speaker: str | None = None
    words: list[TranscriptWord] | None = None

    def __post_init__(self) -> None:
        self.start = max(0.0, float(self.start))
        self.end = max(self.start, float(self.end))
        self.text = str(self.text)
        self.words = [
            item if isinstance(item, TranscriptWord) else TranscriptWord(**item)
            for item in (self.words or [])
        ]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class TranscriptionResult:
    text: str
    segments: list[TranscriptSegment]
    language: str | None = None
    language_probability: float | None = None
    duration: float = 0.0
    transcript_id: str | None = None


@dataclass(slots=True)
class TranscriptionOptions:
    language: str | None = None
    task: str = "transcribe"
    beam_size: int = 5
    vad_filter: bool = True
    word_timestamps: bool = False
    initial_prompt: str | None = None
    temperature: float = 0.0


def reconcile_segments(
    source_text: str,
    edited_text: str,
    segments: list[TranscriptSegment],
) -> list[TranscriptSegment]:
    """Carry text edits into existing timed segments without fabricating timings.

    Character diffs map each segment's original text range into the edited document.
    Segment start/end times and speaker labels are retained. Word timings are only
    retained for segments whose text did not change, since their offsets would no
    longer be trustworthy after an edit.
    """
    from dataclasses import replace
    from difflib import SequenceMatcher

    if not segments or not source_text:
        return []
    if source_text == edited_text:
        return [replace(item, words=list(item.words or [])) for item in segments]

    matcher = SequenceMatcher(a=source_text, b=edited_text, autojunk=False)
    opcodes = matcher.get_opcodes()

    def map_boundary(position: int) -> int:
        # Attribute text inserted exactly at a segment boundary to the segment
        # preceding that boundary. The following segment therefore starts after it.
        for tag, old_start, old_end, new_start, new_end in opcodes:
            if tag == "insert" and old_start == old_end == position:
                return new_end
        for tag, old_start, old_end, new_start, new_end in opcodes:
            if old_start <= position <= old_end:
                if tag == "equal":
                    return new_start + (position - old_start)
                if tag == "replace":
                    old_width = max(1, old_end - old_start)
                    ratio = (position - old_start) / old_width
                    return round(new_start + ratio * (new_end - new_start))
                if tag == "delete":
                    return new_start
        return len(edited_text)

    output: list[TranscriptSegment] = []
    cursor = 0
    for segment in segments:
        original = segment.text.strip()
        if not original:
            continue
        start = source_text.find(original, cursor)
        if start < 0:
            # A segment with inconsistent source offsets cannot safely be rewritten.
            continue
        end = start + len(original)
        new_start = max(0, min(len(edited_text), map_boundary(start)))
        new_end = max(new_start, min(len(edited_text), map_boundary(end)))
        replacement = edited_text[new_start:new_end].strip()
        cursor = end
        if not replacement:
            continue
        changed = replacement != original
        output.append(replace(
            segment,
            text=replacement,
            words=[] if changed else list(segment.words or []),
        ))
    return output
