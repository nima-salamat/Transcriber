from __future__ import annotations

from transcriber.subtitles.formats import export_subtitles
from transcriber.transcription.segments import TranscriptSegment


def test_timed_transcript_segments_export_to_srt_vtt_ass_and_ssa(tmp_path):
    segments = [
        TranscriptSegment(0.25, 1.5, "Hello from a video"),
        TranscriptSegment(1.6, 3.0, "Subtitle export works"),
    ]
    for suffix in (".srt", ".vtt", ".ass", ".ssa"):
        target = export_subtitles(tmp_path / f"captions{suffix}", segments, title="Lecture")
        payload = target.read_text(encoding="utf-8-sig")
        assert "Hello from a video" in payload
        assert "Subtitle export works" in payload
