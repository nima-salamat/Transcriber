from __future__ import annotations

from transcriber.core.config import SettingsStore
from transcriber.storage.backup import create_backup, restore_backup
from transcriber.storage.database import Database
from transcriber.storage.history import HistoryRepository


def test_metadata_backup_and_restore_preserve_history_without_audio_models(tmp_path):
    database = Database(tmp_path / "source" / "transcripts.sqlite3")
    history = HistoryRepository(database)
    history.save(title="Keep me", text="Transcript", original_text="Transcript")
    settings = SettingsStore(tmp_path / "source" / "settings.json")
    settings.load()
    settings.update(theme="light")
    backup = create_backup(database, settings.path, tmp_path / "backup.zip")

    target_db = tmp_path / "target" / "transcripts.sqlite3"
    target_settings = tmp_path / "target" / "settings.json"
    restore_backup(backup, target_db, target_settings)

    restored = HistoryRepository(Database(target_db))
    assert restored.count() == 1
    assert restored.list()[0]["title"] == "Keep me"
    assert SettingsStore(target_settings).load().theme == "light"
