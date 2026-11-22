from __future__ import annotations

from transcriber.storage.database import Database
from transcriber.storage.history import HistoryRepository
from transcriber.transcription.segments import TranscriptSegment


def make_history(tmp_path):
    database = Database(tmp_path / "db" / "transcripts.sqlite3")
    return database, HistoryRepository(database)


def test_history_persists_segments_original_text_and_favorites(tmp_path):
    database, history = make_history(tmp_path)
    segments = [TranscriptSegment(0.1, 1.8, "Hello"), TranscriptSegment(2, 3, "world", "Speaker 1")]
    transcript_id = history.save(
        title="Meeting", text="Hello world", segments=segments,
        source_path="/audio/meeting.wav", language="en", duration=3.0,
        original_text="Hello, world", favorite=True, tags=["work"],
    )

    saved = history.get(transcript_id)
    assert saved["text"] == "Hello world"
    assert saved["original_text"] == "Hello, world"
    assert saved["favorite"] == 1
    assert saved["tags"] == ["work"]
    assert saved["segments"][1]["speaker"] == "Speaker 1"
    assert history.count() == 1
    assert history.list("MEET")[0]["id"] == transcript_id


def test_history_edit_preserves_original_text_and_can_duplicate_delete(tmp_path):
    _, history = make_history(tmp_path)
    original = history.save(title="Note", text="Recognized", original_text="Recognized")
    history.save(transcript_id=original, title="Note renamed", text="Edited", original_text=None)
    history.set_favorite(original, True)
    duplicate = history.duplicate(original)

    edited = history.get(original)
    copied = history.get(duplicate)
    assert edited["text"] == "Edited"
    assert edited["original_text"] == "Recognized"
    assert edited["favorite"] == 1
    assert copied["title"] == "Note renamed (copy)"
    assert copied["favorite"] == 0
    assert history.count() == 2
    history.delete(original)
    assert history.get(original) is None
    assert history.count() == 1


def test_history_rename_rejects_blank_titles(tmp_path):
    _, history = make_history(tmp_path)
    transcript_id = history.save(title="Valid", text="text")
    try:
        history.rename(transcript_id, "   ")
    except ValueError as exc:
        assert "cannot be empty" in str(exc)
    else:
        raise AssertionError("Blank title must be rejected")


def test_database_migrates_legacy_segments_without_word_timestamps(tmp_path):
    import sqlite3

    path = tmp_path / "legacy.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE transcript_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transcript_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                start REAL NOT NULL,
                end REAL NOT NULL,
                text TEXT NOT NULL,
                speaker TEXT,
                UNIQUE(transcript_id, ordinal)
            )"""
        )

    database = Database(path)
    database.initialize()

    with database.connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(transcript_segments)")}
    assert "words_json" in columns
