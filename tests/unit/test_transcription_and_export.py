from __future__ import annotations

import json
from threading import Event

import pytest

from transcriber.storage.database import Database
from transcriber.storage.history import HistoryRepository
from transcriber.transcription.exporters import export_transcript
from transcriber.transcription.segments import (
    TranscriptionOptions,
    TranscriptionResult,
    TranscriptSegment,
)
from transcriber.transcription.service import TranscriptionService


class FakeEngine:
    engine_id = "fake-offline"
    display_name = "Fake offline"

    def transcribe(self, audio_path, options, cancel_event=None, progress=None):
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Transcription cancelled")
        if progress:
            progress(100, "Done")
        return TranscriptionResult(
            "سلام world", [TranscriptSegment(0.0, 1.2, "سلام"), TranscriptSegment(1.2, 2.0, "world")],
            language="fa", duration=2.0,
        )


def test_transcription_service_saves_completed_result_to_history(tmp_path):
    history = HistoryRepository(Database(tmp_path / "db.sqlite3"))
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"fake audio")
    result = TranscriptionService(FakeEngine(), history).transcribe(
        audio, TranscriptionOptions(language="fa"), title="Sample", model_id="local-model",
    )
    saved = history.list()[0]
    assert result.text == "سلام world"
    assert saved["title"] == "Sample"
    assert saved["model_id"] == "local-model"
    assert saved["engine"] == "fake-offline"
    assert history.get(saved["id"])["segments"][0]["text"] == "سلام"


def test_cancelled_transcription_does_not_create_history_record(tmp_path):
    history = HistoryRepository(Database(tmp_path / "db.sqlite3"))
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"fake audio")
    cancelled = Event()
    cancelled.set()
    with pytest.raises(InterruptedError):
        TranscriptionService(FakeEngine(), history).transcribe(
            audio, TranscriptionOptions(), cancel_event=cancelled,
        )
    assert history.count() == 0


def test_subtitle_and_json_exports_preserve_timestamps_and_unicode(tmp_path):
    segments = [TranscriptSegment(1.25, 2.5, "سلام", "Speaker 1")]
    srt = export_transcript(
        tmp_path / "out.srt", format="srt", text="سلام", segments=segments,
        include_timestamps=True, include_speakers=True,
    )
    vtt = export_transcript(
        tmp_path / "out.vtt", format="vtt", text="سلام", segments=segments,
        include_timestamps=True, include_speakers=False,
    )
    json_path = export_transcript(
        tmp_path / "out.json", format="json", text="سلام", segments=segments,
        include_timestamps=True, title="تست",
    )
    assert "00:00:01,250 --> 00:00:02,500" in srt.read_text(encoding="utf-8")
    assert "Speaker 1: سلام" in srt.read_text(encoding="utf-8")
    assert vtt.read_text(encoding="utf-8").startswith("WEBVTT\n")
    assert json.loads(json_path.read_text(encoding="utf-8"))["segments"][0]["text"] == "سلام"


def test_text_markdown_and_time_range_export(tmp_path):
    segments = [TranscriptSegment(0, 1, "first"), TranscriptSegment(10, 11, "second")]
    txt = export_transcript(
        tmp_path / "selected.txt", format="txt", text="first second", segments=segments,
        include_timestamps=True, time_range=(8, 12),
    )
    md = export_transcript(tmp_path / "selected.md", format="md", text="edited text", title="Notes")
    assert "second" in txt.read_text(encoding="utf-8")
    assert "first" not in txt.read_text(encoding="utf-8")
    assert md.read_text(encoding="utf-8").startswith("# Notes")


def test_optional_docx_export_produces_document(tmp_path):
    pytest.importorskip("docx")
    target = export_transcript(tmp_path / "rtl.docx", format="docx", text="متن فارسی", title="گزارش")
    assert target.is_file() and target.stat().st_size > 1000


def test_edit_reconciliation_keeps_segment_times_and_invalidates_changed_word_times():
    from transcriber.transcription.segments import TranscriptWord, reconcile_segments

    segments = [
        TranscriptSegment(0.0, 1.4, "Hello world.", words=[TranscriptWord(0.0, 0.4, "Hello")]),
        TranscriptSegment(1.5, 2.4, "Next line."),
    ]
    edited = reconcile_segments("Hello world. Next line.", "Hello brave world. Next line!", segments)

    assert [item.text for item in edited] == ["Hello brave world.", "Next line!"]
    assert [(item.start, item.end) for item in edited] == [(0.0, 1.4), (1.5, 2.4)]
    assert edited[0].words == []  # old word offsets no longer describe the edited sentence
    assert edited[1].words == []


def test_edit_reconciliation_preserves_word_times_for_unchanged_segments():
    from transcriber.transcription.segments import TranscriptWord, reconcile_segments

    words = [TranscriptWord(0.0, 0.3, "Hello", 0.98)]
    segments = [TranscriptSegment(0, 1, "Hello." , words=words), TranscriptSegment(1, 2, "World.")]
    edited = reconcile_segments("Hello. World.", "Hello. World again.", segments)
    assert edited[0].words == words
    assert edited[0].start == 0
    assert edited[1].text == "World again."


def test_database_history_keeps_word_level_timestamps(tmp_path):
    from transcriber.transcription.segments import TranscriptWord

    history = HistoryRepository(Database(tmp_path / "db.sqlite3"))
    transcript_id = history.save(
        title="Words", text="Hello", segments=[TranscriptSegment(
            0, 1, "Hello", words=[TranscriptWord(0.1, 0.6, "Hello", 0.91)],
        )],
    )
    loaded = history.get(transcript_id)
    assert loaded["segments"][0]["words"][0]["text"] == "Hello"
    assert loaded["segments"][0]["words"][0]["probability"] == 0.91


def test_online_adapter_requires_explicit_consent():
    from transcriber.engines.cloud import GoogleCloudEngine

    with pytest.raises(PermissionError, match="explicit consent"):
        GoogleCloudEngine()
    assert GoogleCloudEngine(consent_granted=True).engine_id == "google-cloud"
