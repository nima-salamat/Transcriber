"""Persistent model download task ledger."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from transcriber.storage.database import Database


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _safe_error(message: str | None) -> str | None:
    if not message:
        return None
    value = str(message)[:1000]
    value = re.sub(
        r"(?i)(authorization|access[_-]?token|api[_-]?key|password)\s*[:=]\s*[^,;\s]+",
        r"\1=[redacted]",
        value,
    )
    value = re.sub(r"(?i)(token=)[^&\s]+", r"\1[redacted]", value)
    return value


class DownloadRepository:
    """SQLite ledger for resumable model-download jobs."""

    def __init__(self, database: Database):
        self.database = database
        self.database.initialize()

    @staticmethod
    def _decode(row):
        if row is None:
            return None
        result = dict(row)
        try:
            result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
        except (TypeError, ValueError):
            result["metadata"] = {}
        return result

    def enqueue(
        self, task_id: str, repo_id: str, revision: str | None,
        target_path: str, metadata: dict | None = None,
    ) -> dict:
        now = _now()
        payload = json.dumps(metadata or {}, ensure_ascii=False)
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO model_download_jobs(
                    task_id,repo_id,revision,target_path,state,downloaded_bytes,
                    total_bytes,metadata_json,error,created_at,updated_at
                ) VALUES(?,?,?,?, 'queued',0,NULL,?,NULL,?,?)
                ON CONFLICT(task_id) DO UPDATE SET
                    repo_id=excluded.repo_id,
                    revision=COALESCE(excluded.revision,model_download_jobs.revision),
                    target_path=excluded.target_path,
                    state='queued',
                    error=NULL,
                    metadata_json=CASE WHEN excluded.metadata_json='{}'
                        THEN model_download_jobs.metadata_json ELSE excluded.metadata_json END,
                    updated_at=excluded.updated_at
                """,
                (task_id, repo_id, revision, target_path, payload, now, now),
            )
            row = connection.execute(
                "SELECT * FROM model_download_jobs WHERE task_id=?", (task_id,)
            ).fetchone()
        return self._decode(row)

    def update(
        self, task_id: str, *, state: str | None = None,
        revision: str | None = None, downloaded_bytes: int | None = None,
        total_bytes: int | None = None, metadata: dict | None = None,
        error: str | None = None,
    ) -> None:
        fields = ["updated_at=?"]
        values: list[object] = [_now()]
        for column, value in (
            ("state", state),
            ("revision", revision),
            ("downloaded_bytes", downloaded_bytes),
            ("total_bytes", total_bytes),
        ):
            if value is not None:
                fields.append(f"{column}=?")
                values.append(value)
        if metadata is not None:
            fields.append("metadata_json=?")
            values.append(json.dumps(metadata, ensure_ascii=False))
        if error is not None or state in {"installed", "cancelled", "paused", "stopped"}:
            fields.append("error=?")
            values.append(_safe_error(error))
        values.append(str(task_id))
        with self.database.connect() as connection:
            connection.execute(
                f"UPDATE model_download_jobs SET {', '.join(fields)} WHERE task_id=?",
                values,
            )

    def get(self, task_id: str) -> dict | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM model_download_jobs WHERE task_id=?", (str(task_id),)
            ).fetchone()
        return self._decode(row)

    def list(self, *, limit: int = 500) -> list[dict]:
        limit = max(1, min(int(limit), 2000))
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM model_download_jobs ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def mark_interrupted(self) -> int:
        """Convert volatile in-flight states into explicit recoverable Stopped jobs."""
        now = _now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE model_download_jobs
                SET state='stopped',
                    error='Application exited before this download finished. Resume it explicitly.',
                    updated_at=?
                WHERE state IN ('queued','inspecting','downloading','validating','installing','pausing','stopping','cancelling')
                """,
                (now,),
            )
        return int(cursor.rowcount)
