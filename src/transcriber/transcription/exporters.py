"""Export timestamped transcript data to text, subtitle, JSON, DOCX, and PDF."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

from transcriber.transcription.segments import TranscriptSegment


def _timestamp(seconds: float, separator: str = ",") -> str:
    millis = max(0, round(float(seconds) * 1000))
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, ms = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}{separator}{ms:03}"


def _selected_segments(segments: Iterable[TranscriptSegment], time_range: tuple[float, float] | None):
    items = list(segments)
    if time_range is None:
        return items
    start, end = time_range
    return [s for s in items if s.end >= start and s.start <= end]


def export_transcript(
    path: Path, *, format: str, text: str, segments: Iterable[TranscriptSegment] = (),
    metadata: dict[str, Any] | None = None, include_timestamps: bool = False,
    include_speakers: bool = True, title: str | None = None,
    time_range: tuple[float, float] | None = None,
    selected_text: str | None = None,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    chosen = _selected_segments(segments, time_range)
    body_text = selected_text if selected_text is not None else text
    metadata = dict(metadata or {})
    fmt = format.lower().lstrip(".")
    if fmt in {"txt", "md", "markdown"}:
        if fmt == "txt":
            if include_timestamps and chosen:
                content = "\n".join(
                    f"[{_timestamp(s.start, '.')} ] {s.speaker + ': ' if include_speakers and s.speaker else ''}{s.text}"
                    for s in chosen
                )
            else:
                content = body_text
        else:
            lines = [f"# {title}" if title else "# Transcript", ""]
            if include_timestamps and chosen:
                lines.extend(
                    f"- **{_timestamp(s.start, '.')}** — "
                    f"{s.speaker + ': ' if include_speakers and s.speaker else ''}{s.text}"
                    for s in chosen
                )
            else:
                lines.append(body_text)
            content = "\n".join(lines)
        target.write_text(content.rstrip() + "\n", encoding="utf-8")
    elif fmt in {"srt", "vtt"}:
        separator = "," if fmt == "srt" else "."
        rows = []
        for index, segment in enumerate(chosen, 1):
            start = _timestamp(segment.start, separator)
            end = _timestamp(segment.end, separator)
            caption = f"{segment.speaker}: {segment.text}" if include_speakers and segment.speaker else segment.text
            rows.append((f"{index}\n{start} --> {end}\n{caption}" if fmt == "srt"
                         else f"{start} --> {end}\n{caption}"))
        prefix = "WEBVTT\n\n" if fmt == "vtt" else ""
        target.write_text(prefix + "\n\n".join(rows) + "\n", encoding="utf-8")
    elif fmt == "json":
        payload = {
            "title": title, "metadata": metadata, "text": body_text,
            "segments": [segment.to_dict() for segment in chosen],
        }
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif fmt == "docx":
        try:
            from docx import Document
            from docx.enum.text import WD_ALIGN_PARAGRAPH
            from docx.oxml import OxmlElement
            from docx.oxml.ns import qn
        except ImportError as exc:
            raise RuntimeError("DOCX export requires python-docx: pip install 'transcriber[documents]'") from exc
        document = Document()
        if title:
            document.add_heading(title, level=1)
        if include_timestamps and chosen:
            for segment in chosen:
                paragraph = document.add_paragraph()
                paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
                p_pr = paragraph._p.get_or_add_pPr()
                bidi = OxmlElement("w:bidi")
                bidi.set(qn("w:val"), "1")
                p_pr.append(bidi)
                prefix = f"[{_timestamp(segment.start, '.')} ] "
                if include_speakers and segment.speaker:
                    prefix += segment.speaker + ": "
                paragraph.add_run(prefix + segment.text)
        else:
            paragraph = document.add_paragraph(body_text)
            p_pr = paragraph._p.get_or_add_pPr()
            bidi = OxmlElement("w:bidi")
            bidi.set(qn("w:val"), "1")
            p_pr.append(bidi)
        document.save(target)
    elif fmt == "pdf":
        _export_pdf(target, title=title, text=body_text, segments=chosen,
                    include_timestamps=include_timestamps, include_speakers=include_speakers)
    else:
        raise ValueError(f"Unsupported export format: {fmt}")
    return target


def _export_pdf(path: Path, *, title: str | None, text: str,
                segments: list[TranscriptSegment], include_timestamps: bool,
                include_speakers: bool) -> None:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_RIGHT
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from xml.sax.saxutils import escape
    except ImportError as exc:
        raise RuntimeError("PDF export requires reportlab: pip install 'transcriber[documents]'") from exc
    font_candidates = [
        Path(os.environ.get("TRANSCRIBER_PDF_FONT", "")) if os.environ.get("TRANSCRIBER_PDF_FONT") else None,
        Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf"),
    ]
    font_path = next((candidate for candidate in font_candidates if candidate and candidate.is_file()), None)
    if font_path:
        pdfmetrics.registerFont(TTFont("TranscriberText", str(font_path)))
        font_name = "TranscriberText"
    else:
        font_name = "Helvetica"
    styles = getSampleStyleSheet()
    style = ParagraphStyle("Transcript", parent=styles["BodyText"], fontName=font_name,
                           alignment=TA_RIGHT, leading=16)
    story = []
    if title:
        story.extend([Paragraph(escape(title), styles["Title"]), Spacer(1, 12)])
    rows = ([f"[{_timestamp(s.start, '.')} ] " +
             (f"{s.speaker}: " if include_speakers and s.speaker else "") + s.text
             for s in segments] if include_timestamps and segments else text.splitlines())
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        rtl_support = True
    except ImportError:
        rtl_support = False
    for row in rows:
        display = get_display(arabic_reshaper.reshape(row)) if rtl_support else row
        story.append(Paragraph(escape(display) or "&nbsp;", style))
        story.append(Spacer(1, 5))
    SimpleDocTemplate(str(path), pagesize=A4, title=title or "Transcript").build(story)
