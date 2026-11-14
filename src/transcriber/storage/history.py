"""Transcript history repository."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from .database import Database
from transcriber.transcription.segments import TranscriptSegment


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class HistoryRepository:
    def __init__(self, database: Database):
        self.database = database
        self.database.initialize()

    def save(
        self, *, transcript_id: str | None = None, title: str, text: str,
        segments: list[TranscriptSegment] | None = None, source_path: str | None = None,
        engine: str = "faster-whisper", model_id: str | None = None,
        language: str | None = None, duration: float = 0.0,
        original_text: str | None = None, tags: list[str] | None = None,
        favorite: bool = False,
    ) -> str:
        transcript_id = transcript_id or str(uuid.uuid4())
        now = utc_now()
        with self.database.connect() as connection:
            existing = connection.execute(
                "SELECT created_at FROM transcripts WHERE id=?", (transcript_id,)
            ).fetchone()
            created_at = existing["created_at"] if existing else now
            connection.execute(
                """INSERT INTO transcripts(
                    id,title,source_path,engine,model_id,language,duration,text,original_text,
                    favorite,tags_json,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET title=excluded.title,
                    source_path=excluded.source_path, engine=excluded.engine,
                    model_id=excluded.model_id, language=excluded.language,
                    duration=excluded.duration, text=excluded.text,
                    original_text=COALESCE(excluded.original_text, transcripts.original_text),
                    favorite=excluded.favorite, tags_json=excluded.tags_json,
                    updated_at=excluded.updated_at""",
                (transcript_id, title, source_path, engine, model_id, language,
                 max(0.0, float(duration)), text, original_text, int(favorite),
                 json.dumps(tags or [], ensure_ascii=False), created_at, now),
            )
            if segments is not None:
                connection.execute(
                    "DELETE FROM transcript_segments WHERE transcript_id=?", (transcript_id,)
                )
                connection.executemany(
                    "INSERT INTO transcript_segments("
                    "transcript_id,ordinal,start,end,text,speaker,words_json,uid,language,metadata_json,"
                    "is_edited,comment,bookmarked,locked,reviewed) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [(transcript_id, i, s.start, s.end, s.text, s.speaker,
                      json.dumps([word.__dict__ if hasattr(word, "__dict__") else {
                          "start": word.start, "end": word.end, "text": word.text,
                          "probability": word.probability,
                      } for word in (s.words or [])], ensure_ascii=False),
                      s.id, s.language, json.dumps(s.metadata, ensure_ascii=False), int(s.is_edited),
                      s.comment, int(s.bookmarked), int(s.locked), int(s.reviewed))
                     for i, s in enumerate(segments)],
                )
        return transcript_id

    def get(self, transcript_id: str) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM transcripts WHERE id=?", (transcript_id,)).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["tags"] = json.loads(result.pop("tags_json"))
            segment_rows = connection.execute(
                "SELECT start,end,text,speaker,words_json,uid AS id,language,metadata_json,"
                "is_edited,comment,bookmarked,locked,reviewed FROM transcript_segments "
                "WHERE transcript_id=? ORDER BY ordinal", (transcript_id,)
            ).fetchall()
            result["segments"] = []
            for item in segment_rows:
                segment = dict(item)
                try:
                    segment["words"] = json.loads(segment.pop("words_json") or "[]")
                except (TypeError, ValueError):
                    segment["words"] = []
                    segment.pop("words_json", None)
                try:
                    segment["metadata"] = json.loads(segment.pop("metadata_json") or "{}")
                except (TypeError, ValueError):
                    segment["metadata"] = {}
                    segment.pop("metadata_json", None)
                segment["is_edited"] = bool(segment.get("is_edited", 0))
                segment["bookmarked"] = bool(segment.get("bookmarked", 0))
                segment["locked"] = bool(segment.get("locked", 0))
                segment["reviewed"] = bool(segment.get("reviewed", 0))
                if not segment.get("id"):
                    segment.pop("id", None)
                result["segments"].append(segment)
            return result

    def list(self, query: str = "", limit: int = 200) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        pattern = f"%{query.strip()}%"
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT id,title,source_path,engine,model_id,language,duration,
                   substr(text,1,240) AS preview,favorite,tags_json,created_at,updated_at
                   FROM transcripts WHERE (?='' OR title LIKE ? COLLATE NOCASE OR text LIKE ? COLLATE NOCASE)
                   ORDER BY favorite DESC, updated_at DESC LIMIT ?""",
                (query.strip(), pattern, pattern, limit),
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["tags"] = json.loads(item.pop("tags_json"))
            output.append(item)
        return output

    def count(self) -> int:
        with self.database.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS total FROM transcripts").fetchone()
            return int(row["total"] if row else 0)

    def set_favorite(self, transcript_id: str, favorite: bool) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE transcripts SET favorite=?, updated_at=? WHERE id=?",
                (int(favorite), utc_now(), transcript_id),
            )

    def rename(self, transcript_id: str, title: str) -> None:
        title = title.strip()
        if not title:
            raise ValueError("A transcript title cannot be empty")
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE transcripts SET title=?, updated_at=? WHERE id=?",
                (title, utc_now(), transcript_id),
            )

    def delete(self, transcript_id: str) -> None:
        with self.database.connect() as connection:
            connection.execute("DELETE FROM transcripts WHERE id=?", (transcript_id,))

    def duplicate(self, transcript_id: str) -> str:
        source = self.get(transcript_id)
        if source is None:
            raise KeyError(transcript_id)
        segments = [TranscriptSegment(**item) for item in source["segments"]]
        return self.save(
            title=f"{source['title']} (copy)", text=source["text"], segments=segments,
            source_path=source["source_path"], engine=source["engine"],
            model_id=source["model_id"], language=source["language"],
            duration=source["duration"], original_text=source["original_text"],
            tags=source["tags"], favorite=False,
        )
