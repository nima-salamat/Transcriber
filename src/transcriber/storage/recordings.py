"""Persistent recording metadata independent from transcript history."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from transcriber.storage.database import Database


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class RecordingRepository:
    """Tracks saved microphone recordings without coupling them to transcripts."""

    def __init__(self, database: Database):
        self.database = database
        self.database.initialize()

    def register(
        self, file_path: str | Path, *, duration: float = 0.0,
        device_id: str | None = None, device_name: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        path = Path(file_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Recording file does not exist: {path}")
        stat = path.stat()
        now = _utc_now()
        recorded_at = datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(timespec="seconds")
        extension = path.suffix.lower().lstrip(".") or "unknown"
        recording_id = uuid.uuid4().hex
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO recordings(
                    id,file_path,filename,duration,file_size,format,recorded_at,
                    device_id,device_name,metadata_json,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(file_path) DO UPDATE SET
                    filename=excluded.filename,
                    duration=excluded.duration,
                    file_size=excluded.file_size,
                    format=excluded.format,
                    recorded_at=excluded.recorded_at,
                    device_id=excluded.device_id,
                    device_name=excluded.device_name,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    recording_id, str(path), path.name, max(0.0, float(duration)),
                    int(stat.st_size), extension, recorded_at, device_id, device_name,
                    json.dumps(metadata or {}, ensure_ascii=False), now, now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM recordings WHERE file_path=?", (str(path),)
            ).fetchone()
        return self._decode(row)

    @staticmethod
    def _decode(row) -> dict | None:
        if row is None:
            return None
        result = dict(row)
        try:
            result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
        except (TypeError, ValueError):
            result["metadata"] = {}
        return result

    def list(self, query: str = "", limit: int = 500) -> list[dict]:
        limit = max(1, min(int(limit), 2000))
        text = str(query or "").strip()
        pattern = f"%{text}%"
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM recordings
                WHERE (?='' OR filename LIKE ? COLLATE NOCASE OR file_path LIKE ? COLLATE NOCASE)
                ORDER BY recorded_at DESC LIMIT ?
                """,
                (text, pattern, pattern, limit),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def get(self, recording_id: str) -> dict | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM recordings WHERE id=?", (str(recording_id),)
            ).fetchone()
        return self._decode(row)

    def references_to(self, file_path: str | Path) -> list[dict]:
        path = str(Path(file_path).expanduser().resolve())
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT id,title,updated_at FROM transcripts WHERE source_path=? ORDER BY updated_at DESC",
                (path,),
            ).fetchall()
        return [dict(row) for row in rows]

    def rename(self, recording_id: str, new_filename: str) -> Path:
        name = str(new_filename or "").strip()
        if not name or Path(name).name != name or name in {".", ".."}:
            raise ValueError("Enter a filename only; directory paths are not allowed.")
        current = self.get(recording_id)
        if current is None:
            raise KeyError(recording_id)
        source = Path(current["file_path"])
        if not source.is_file():
            raise FileNotFoundError(f"Recording file is missing: {source}")
        requested_suffix = Path(name).suffix
        if requested_suffix and requested_suffix.casefold() != source.suffix.casefold():
            raise ValueError(
                f"Recording format is {source.suffix.lower()}; renaming cannot change its media format."
            )
        if not requested_suffix:
            name += source.suffix
        target = source.with_name(name)
        if target.exists():
            raise FileExistsError(f"A file already exists at {target}")
        source.rename(target)
        try:
            with self.database.connect() as connection:
                connection.execute(
                    "UPDATE recordings SET file_path=?, filename=?, file_size=?, updated_at=? WHERE id=?",
                    (str(target), target.name, target.stat().st_size, _utc_now(), str(recording_id)),
                )
                # Keep transcript source references valid when a recording is renamed.
                connection.execute(
                    "UPDATE transcripts SET source_path=?, updated_at=? WHERE source_path=?",
                    (str(target), _utc_now(), str(source)),
                )
        except Exception:
            try:
                target.rename(source)
            except OSError:
                pass
            raise
        return target

    def delete(self, recording_id: str, *, delete_file: bool = True) -> dict:
        current = self.get(recording_id)
        if current is None:
            raise KeyError(recording_id)
        source = Path(current["file_path"])
        trash_path = None
        if delete_file and source.is_file():
            trash_dir = source.parent / ".transcriber-trash"
            trash_dir.mkdir(parents=True, exist_ok=True)
            trash_path = trash_dir / f"{uuid.uuid4().hex}-{source.name}"
            os.replace(source, trash_path)
        try:
            with self.database.connect() as connection:
                connection.execute("DELETE FROM recordings WHERE id=?", (str(recording_id),))
        except Exception:
            if trash_path and trash_path.exists():
                try:
                    os.replace(trash_path, source)
                except OSError:
                    pass
            raise
        if trash_path:
            try:
                trash_path.unlink(missing_ok=True)
                try:
                    trash_path.parent.rmdir()
                except OSError:
                    pass
            except OSError:
                # The persistent index is already removed; preserve a failed
                # deletion in the hidden trash folder rather than risk the source.
                pass
        return current
