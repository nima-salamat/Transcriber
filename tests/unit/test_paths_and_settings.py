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


def test_audio_device_preferences_round_trip(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    store.load()

    saved = store.update(
        audio_input_device_id="microphone-device-id",
        audio_output_device_id="speaker-device-id",
    )
    reloaded = SettingsStore(store.path).load()

    assert saved.audio_input_device_id == "microphone-device-id"
    assert saved.audio_output_device_id == "speaker-device-id"
    assert reloaded.audio_input_device_id == "microphone-device-id"
    assert reloaded.audio_output_device_id == "speaker-device-id"


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



def test_voice_silence_window_is_validated_and_persisted(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    store.load()

    saved = store.update(voice_silence_seconds=2.3)
    assert saved.voice_silence_seconds == 2.3
    assert SettingsStore(store.path).load().voice_silence_seconds == 2.3

    invalid = AppSettings(voice_silence_seconds=0.1)
    invalid.validate()
    assert invalid.voice_silence_seconds == 1.5
    invalid_nan = AppSettings(voice_silence_seconds=float("nan"))
    invalid_nan.validate()
    assert invalid_nan.voice_silence_seconds == 1.5



def test_ollama_and_voice_model_settings_round_trip(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    store.load()

    saved = store.update(
        chat_provider="ollama",
        ollama_base_url="http://127.0.0.1:11434",
        ollama_model="qwen2.5:7b",
        ollama_keep_alive="1h",
        voice_asr_model="Systran/faster-whisper-small",
    )
    loaded = SettingsStore(store.path).load()

    assert saved.chat_provider == "ollama"
    assert loaded.chat_provider == "ollama"
    assert loaded.ollama_model == "qwen2.5:7b"
    assert loaded.ollama_keep_alive == "1h"
    assert loaded.voice_asr_model == "Systran/faster-whisper-small"


def test_invalid_chat_provider_and_ollama_url_fall_back_safely():
    settings = AppSettings(chat_provider="remote", ollama_base_url="localhost:11434")
    settings.validate()
    assert settings.chat_provider == "opencode"
    assert settings.ollama_base_url == "http://127.0.0.1:11434"
