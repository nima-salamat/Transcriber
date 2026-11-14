from __future__ import annotations

import json

from transcriber.core.config import AppSettings, SettingsStore
from transcriber.core.paths import AppPaths


def test_paths_respect_user_override_and_create_expected_directories(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSCRIBER_HOME", str(tmp_path / "portable"))
    paths = AppPaths.discover().ensure()

    assert paths.config == tmp_path / "portable" / "config"
    assert paths.models == tmp_path / "portable" / "data" / "models"
    assert paths.recordings.is_dir()
    assert (paths.models / ".staging").is_dir()
    assert paths.database.parent == paths.data


def test_settings_round_trip_and_validation(tmp_path):
    store = SettingsStore(tmp_path / "config" / "settings.json")
    store.load()
    saved = store.update(theme="light", beam_size=99, download_concurrency=20, device="unknown")

    assert saved.theme == "light"
    assert saved.beam_size == 20
    assert saved.download_concurrency == 4
    assert saved.device == "auto"
    assert SettingsStore(store.path).load() == saved


def test_malformed_settings_file_is_preserved_and_defaults_are_used(tmp_path):
    path = tmp_path / "settings.json"
    broken = '{"beam_size": "not-a-number", "theme": "neon"}'
    path.write_text(broken, encoding="utf-8")

    settings = SettingsStore(path).load()

    assert settings == AppSettings()
    assert path.read_text(encoding="utf-8") == broken


def test_settings_update_ignores_unknown_keys_and_is_valid_json(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    store.load()
    store.update(theme="dark", unknown_key="ignored")
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    assert raw["theme"] == "dark"
    assert "unknown_key" not in raw


def test_settings_boolean_strings_are_parsed_not_truthiness_coerced(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"local_only": "false", "cloud_consent": "true"}', encoding="utf-8")
    loaded = SettingsStore(path).load()
    assert loaded.local_only is False
    assert loaded.cloud_consent is True


def test_non_object_settings_json_falls_back_without_destroying_file(tmp_path):
    path = tmp_path / "settings.json"
    broken = '["not", "an", "object"]'
    path.write_text(broken, encoding="utf-8")
    loaded = SettingsStore(path).load()
    assert loaded == AppSettings()
    assert path.read_text(encoding="utf-8") == broken
