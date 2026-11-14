"""SQLite schema and connection lifecycle."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 4


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS transcripts (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    source_path TEXT,
                    engine TEXT NOT NULL,
                    model_id TEXT,
                    language TEXT,
                    duration REAL NOT NULL DEFAULT 0,
                    text TEXT NOT NULL DEFAULT '',
                    original_text TEXT,
                    favorite INTEGER NOT NULL DEFAULT 0,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_transcripts_updated
                    ON transcripts(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_transcripts_title
                    ON transcripts(title COLLATE NOCASE);
                CREATE TABLE IF NOT EXISTS transcript_segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transcript_id TEXT NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL,
                    start REAL NOT NULL,
                    end REAL NOT NULL,
                    text TEXT NOT NULL,
                    speaker TEXT,
                    words_json TEXT NOT NULL DEFAULT '[]',
                    uid TEXT,
                    language TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    is_edited INTEGER NOT NULL DEFAULT 0,
                    comment TEXT,
                    bookmarked INTEGER NOT NULL DEFAULT 0,
                    locked INTEGER NOT NULL DEFAULT 0,
                    reviewed INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(transcript_id, ordinal)
                );
                CREATE INDEX IF NOT EXISTS idx_segments_transcript
                    ON transcript_segments(transcript_id, ordinal);
                CREATE TABLE IF NOT EXISTS recordings (
                    id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL UNIQUE,
                    filename TEXT NOT NULL,
                    duration REAL NOT NULL DEFAULT 0,
                    file_size INTEGER NOT NULL DEFAULT 0,
                    format TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    device_id TEXT,
                    device_name TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_recordings_recorded_at
                    ON recordings(recorded_at DESC);
                """
            )
            segment_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(transcript_segments)")
            }
            migrations = {
                "words_json": "TEXT NOT NULL DEFAULT '[]'",
                "uid": "TEXT",
                "language": "TEXT",
                "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
                "is_edited": "INTEGER NOT NULL DEFAULT 0",
                "comment": "TEXT",
                "bookmarked": "INTEGER NOT NULL DEFAULT 0",
                "locked": "INTEGER NOT NULL DEFAULT 0",
                "reviewed": "INTEGER NOT NULL DEFAULT 0",
            }
            for column, definition in migrations.items():
                if column not in segment_columns:
                    connection.execute(f"ALTER TABLE transcript_segments ADD COLUMN {column} {definition}")
            connection.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('version', ?)",
                (str(SCHEMA_VERSION),),
            )
