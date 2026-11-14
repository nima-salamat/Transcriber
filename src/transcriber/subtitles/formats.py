"""SRT, WebVTT and ASS/SSA parsing and export without external dependencies."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from transcriber.transcription.segments import TranscriptSegment
from transcriber.transcription.exporters import _timestamp

_TIME = re.compile(r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{1,3})")
_ASS_TIME = re.compile(r"(?P<h>\d+):(?P<m>\d{2}):(?P<s>\d{2})\.(?P<cs>\d{2})")


def _parse_time(value: str) -> float:
    match = _TIME.search(value.strip())
    if not match:
        raise ValueError(f"Invalid subtitle timestamp: {value!r}")
    part = match.groupdict()
    return int(part["h"]) * 3600 + int(part["m"]) * 60 + int(part["s"]) + int(part["ms"].ljust(3, "0")) / 1000


def _parse_ass_time(value: str) -> float:
    match = _ASS_TIME.search(value.strip())
    if not match:
        raise ValueError(f"Invalid ASS timestamp: {value!r}")
    p = match.groupdict()
    return int(p["h"]) * 3600 + int(p["m"]) * 60 + int(p["s"]) + int(p["cs"]) / 100


def parse_subtitles(path: Path) -> list[TranscriptSegment]:
    source = Path(path)
    suffix = source.suffix.casefold()
    content = source.read_text(encoding="utf-8-sig")
    if suffix in {".srt", ".vtt"}:
        return parse_srt_vtt(content)
    if suffix in {".ass", ".ssa"}:
        return parse_ass(content)
    raise ValueError(f"Unsupported subtitle format: {suffix}")


def parse_srt_vtt(content: str) -> list[TranscriptSegment]:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", normalized.strip())
    output: list[TranscriptSegment] = []
    for block in blocks:
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if not lines or lines[0].strip().upper() == "WEBVTT":
            continue
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        left, right = [part.strip().split()[0] for part in lines[timing_index].split("-->", 1)]
        start, end = _parse_time(left), _parse_time(right)
        text = "\n".join(lines[timing_index + 1:]).strip()
        if end <= start:
            raise ValueError(f"Subtitle end must be after start ({left} --> {right})")
        output.append(TranscriptSegment(start, end, text))
    return output


def parse_ass(content: str) -> list[TranscriptSegment]:
    in_events = False
    format_fields = ["Layer", "Start", "End", "Style", "Name", "MarginL", "MarginR", "MarginV", "Effect", "Text"]
    output: list[TranscriptSegment] = []
    for line in content.replace("\r\n", "\n").splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_events = stripped.casefold() == "[events]"
            continue
        if not in_events:
            continue
        if stripped.casefold().startswith("format:"):
            format_fields = [part.strip() for part in stripped.split(":", 1)[1].split(",")]
            continue
        if not stripped.casefold().startswith("dialogue:"):
            continue
        raw = stripped.split(":", 1)[1].lstrip()
        columns = len(format_fields)
        parts = raw.split(",", max(0, columns - 1))
        if len(parts) != columns:
            continue
        row = dict(zip(format_fields, parts))
        start, end = _parse_ass_time(row.get("Start", "")), _parse_ass_time(row.get("End", ""))
        raw_text = row.get("Text", "").replace(r"\N", "\n").replace(r"\n", "\n").replace(r"\h", " ")
        # Strip ASS override tags; preserve visible text.
        text = re.sub(r"\{[^}]*\}", "", raw_text).strip()
        if end > start:
            output.append(TranscriptSegment(start, end, text, speaker=row.get("Name") or None))
    return output


def export_subtitles(path: Path, segments: Iterable[TranscriptSegment], *, format: str | None = None,
                     title: str = "Transcriber", max_line_length: int | None = None) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fmt = (format or target.suffix.lstrip(".")).casefold()
    items = sorted(segments, key=lambda item: (item.start, item.end))
    if fmt in {"srt", "vtt"}:
        blocks = []
        for i, item in enumerate(items, 1):
            text = item.text
            if max_line_length:
                text = _wrap_text(text, max_line_length)
            start = _timestamp(item.start, "." if fmt == "vtt" else ",")
            end = _timestamp(item.end, "." if fmt == "vtt" else ",")
            blocks.append(f"{i}\n{start} --> {end}\n{text}" if fmt == "srt" else f"{start} --> {end}\n{text}")
        content = ("WEBVTT\n\n" if fmt == "vtt" else "") + "\n\n".join(blocks) + "\n"
    elif fmt in {"ass", "ssa"}:
        rows = [
            "[Script Info]", f"Title: {title}", "ScriptType: v4.00+", "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
            "[V4+ Styles]", "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            "Style: Default,Arial,22,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,0,2,40,40,30,1", "",
            "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
        for item in items:
            ass_text = item.text.replace("\n", r"\N")
            rows.append(
                f"Dialogue: 0,{_ass_time(item.start)},{_ass_time(item.end)},Default,{item.speaker or ''},0,0,0,,{ass_text}"
            )
        content = "\n".join(rows) + "\n"
    else:
        raise ValueError(f"Unsupported subtitle format: {fmt}")
    target.write_text(content, encoding="utf-8-sig" if fmt in {"srt", "ssa", "ass"} else "utf-8")
    return target


def _ass_time(value: float) -> str:
    centiseconds = max(0, round(float(value) * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    seconds, cs = divmod(remainder, 100)
    return f"{hours}:{minutes:02}:{seconds:02}.{cs:02}"


def _wrap_text(text: str, width: int) -> str:
    import textwrap
    return "\n".join(
        line for paragraph in text.splitlines() or [text]
        for line in textwrap.wrap(paragraph, width=max(1, int(width))) or [""]
    )
