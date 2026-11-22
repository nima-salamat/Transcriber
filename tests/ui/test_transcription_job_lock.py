from __future__ import annotations

import os
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from transcriber.core.config import SettingsStore
from transcriber.core.paths import AppPaths
from transcriber.models.downloader import ModelDownloader
from transcriber.models.hub_client import HuggingFaceHubClient
from transcriber.models.manager import ModelManager
from transcriber.models.registry import ModelRegistry
from transcriber.storage.database import Database
from transcriber.storage.history import HistoryRepository
from transcriber.ui.main_window import MainWindow


def make_window(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSCRIBER_HOME", str(tmp_path / "app-data"))
    paths = AppPaths.discover().ensure()
    settings = SettingsStore(paths.settings)
    settings.load()
    database = Database(paths.database)
    history = HistoryRepository(database)
    hub = HuggingFaceHubClient()
    registry = ModelRegistry(paths.models, paths.registry)
    downloader = ModelDownloader(hub, registry, paths.cache / "hub")
    manager = ModelManager(registry, hub, downloader)
    return MainWindow(paths, settings, history, database, manager), settings


def test_active_job_blocks_history_switch_and_source_replacement(qtbot, tmp_path, monkeypatch):
    window, _settings = make_window(tmp_path, monkeypatch)
    qtbot.addWidget(window)
    window.show()
    page = window.transcription_page
    active_video = tmp_path / "active.mp4"
    active_video.write_bytes(b"active source")
    page.audio_path = active_video
    page.cancel_event = threading.Event()
    page.cancel_event.set()
    page._refresh_busy_controls()

    assert not page.open_history_item("old-transcript-id")
    assert not page.set_audio(tmp_path / "another.mp4")
    assert not page.close_audio()
    assert page.audio_path == active_video
    assert not window.home_page.recent.isEnabled()
    assert not window.history_page.items.isEnabled()
    assert not window.editor_page.isEnabled()
    assert not window.subtitle_page.isEnabled()

    window.navigate("home")
    assert not window.open_transcript("old-transcript-id")
    assert window.stack.currentWidget() is window.home_page

    page._finish_worker()
    assert not page.is_busy
    assert window.home_page.recent.isEnabled()
    assert window.history_page.items.isEnabled()
    assert window.editor_page.isEnabled()
    assert window.subtitle_page.isEnabled()
    window.close()


def test_history_read_locks_out_media_switch_until_result_finishes(qtbot, tmp_path, monkeypatch):
    window, _settings = make_window(tmp_path, monkeypatch)
    qtbot.addWidget(window)
    page = window.transcription_page
    entered = threading.Event()
    release = threading.Event()

    def slow_read(_transcript_id):
        entered.set()
        release.wait(3)
        return None

    page.history.get = slow_read
    assert page.open_history_item("missing-transcript")
    qtbot.waitUntil(entered.is_set, timeout=2000)
    assert page.is_busy
    audio = tmp_path / "next.wav"
    audio.write_bytes(b"audio")
    assert not page.set_audio(audio)
    release.set()
    qtbot.waitUntil(lambda: not page.is_busy, timeout=3000)
    window.close()


def test_engine_selector_and_controls_are_reenabled_after_transcription(qtbot, tmp_path, monkeypatch):
    window, _settings = make_window(tmp_path, monkeypatch)
    qtbot.addWidget(window)
    page = window.transcription_page

    page.cancel_event = threading.Event()
    page._job_engine_id = "faster-whisper"
    page._refresh_busy_controls()

    assert not page.engine_combo.isEnabled()
    assert not page.language_combo.isEnabled()
    assert not page.open_button.isEnabled()

    page._finish_worker()

    assert page.engine_combo.isEnabled()
    assert page.language_combo.isEnabled()
    assert page.open_button.isEnabled()

    google_index = page.engine_combo.findData("google-web")
    assert google_index >= 0
    page.engine_combo.setCurrentIndex(google_index)
    assert page.model_combo.isEnabled() is False
    assert page.language_combo.isEnabled()

    local_index = page.engine_combo.findData("faster-whisper")
    page.engine_combo.setCurrentIndex(local_index)
    assert page.model_combo.isEnabled()
    window.close()
