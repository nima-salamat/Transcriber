"""Portable metadata backups (database and settings, never large model/audio files)."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from transcriber.storage.database import Database


def create_backup(database: Database, settings_path: Path, destination: Path) -> Path:
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="transcriber-backup-") as temporary:
        root = Path(temporary)
        db_copy = root / "transcripts.sqlite3"
        with closing(database.connect()) as source, closing(sqlite3.connect(db_copy)) as backup:
            source.backup(backup)
            backup.commit()
        settings_copy = root / "settings.json"
        if Path(settings_path).is_file():
            shutil.copy2(settings_path, settings_copy)
        else:
            settings_copy.write_text("{}", encoding="utf-8")
        manifest = {
            "format": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "contents": ["transcripts.sqlite3", "settings.json"],
            "excluded": ["recordings", "models", "cache", "logs"],
        }
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        temporary_target = target.with_suffix(target.suffix + ".tmp")
        with zipfile.ZipFile(temporary_target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in ("manifest.json", "transcripts.sqlite3", "settings.json"):
                archive.write(root / name, arcname=name)
        temporary_target.replace(target)
    return target


def restore_backup(archive_path: Path, database_path: Path, settings_path: Path) -> None:
    """Validate then replace database/settings, rolling back both on write failure."""
    source = Path(archive_path)
    db_target = Path(database_path)
    settings_target = Path(settings_path)
    with tempfile.TemporaryDirectory(prefix="transcriber-restore-") as temporary:
        root = Path(temporary)
        with zipfile.ZipFile(source) as archive:
            names = archive.namelist()
            required = {"manifest.json", "transcripts.sqlite3", "settings.json"}
            if len(names) != len(set(names)) or not required.issubset(names):
                raise ValueError("This is not a valid Transcriber metadata backup")
            if any(name not in required for name in names):
                raise ValueError("Backup contains unexpected archive entries")
            manifest = json.loads(archive.read("manifest.json"))
            if not isinstance(manifest, dict) or manifest.get("format") != 1:
                raise ValueError("Unsupported backup format")
            for name in ("transcripts.sqlite3", "settings.json"):
                info = archive.getinfo(name)
                if info.file_size > 512 * 1024 * 1024:
                    raise ValueError("Backup file is unexpectedly large")
                (root / name).write_bytes(archive.read(name))
        # Configuration must be a JSON object; SQLite must pass its full integrity check.
        try:
            restored_settings = json.loads((root / "settings.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("Backup settings file is not valid JSON") from exc
        if not isinstance(restored_settings, dict):
            raise ValueError("Backup settings must be a JSON object")
        with closing(sqlite3.connect(root / "transcripts.sqlite3")) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise ValueError("Backup database failed its integrity check")

        db_target.parent.mkdir(parents=True, exist_ok=True)
        settings_target.parent.mkdir(parents=True, exist_ok=True)
        old_db = root / "previous.sqlite3"
        old_settings = root / "previous-settings.json"
        had_db = db_target.is_file()
        had_settings = settings_target.is_file()
        if had_db:
            shutil.copy2(db_target, old_db)
        if had_settings:
            shutil.copy2(settings_target, old_settings)

        # Ensure committed WAL contents are folded into the main database before
        # swapping the file. Callers must ensure no application jobs are active.
        if had_db:
            try:
                with closing(sqlite3.connect(db_target, timeout=10)) as connection:
                    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error as exc:
                raise RuntimeError("Could not checkpoint the current transcript database") from exc

        replaced_db = False
        replaced_settings = False
        try:
            os.replace(root / "transcripts.sqlite3", db_target)
            replaced_db = True
            os.replace(root / "settings.json", settings_target)
            replaced_settings = True
            for suffix in ("-wal", "-shm"):
                Path(str(db_target) + suffix).unlink(missing_ok=True)
        except Exception:
            if replaced_db:
                if had_db:
                    os.replace(old_db, db_target)
                else:
                    db_target.unlink(missing_ok=True)
            if replaced_settings:
                if had_settings:
                    os.replace(old_settings, settings_target)
                else:
                    settings_target.unlink(missing_ok=True)
            raise
