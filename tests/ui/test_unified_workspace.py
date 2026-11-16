"""Regression tests for the single-workspace Transcriber UI."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtWidgets import QApplication

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


def test_all_primary_workflows_live_in_one_workspace(qtbot, tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    window, _settings = make_window(tmp_path, monkeypatch)
    qtbot.addWidget(window)
    window.resize(1280, 820)
    window.show()
    qtbot.wait(40)

    assert window.stack.count() == 1
    assert window.stack.currentWidget() is window.workspace
    assert window.workspace.tabs.count() == 7
    assert [
        window.workspace.tabs.tabText(index)
        for index in range(3)
    ] == ["Transcribe", "Segments", "Captions"]

    for route, expected_index, expected_view in (
        ("transcription", 0, "transcription"),
        ("editor", 1, "editor"),
        ("subtitles", 2, "subtitles"),
        ("recording", 3, "recording"),
        ("batch", 4, "batch"),
        ("history", 5, "history"),
        ("audio", 5, "audio"),
        ("cleanup", 6, "cleanup"),
    ):
        window.navigate(route)
        assert window.stack.currentWidget() is window.workspace
        assert window.workspace.tabs.currentIndex() == expected_index
        assert window.workspace.current_view == expected_view

    # Model management and preferences are secondary dialogs, not permanent
    # entries in the workspace's primary view strip.
    window.navigate("models")
    assert window.model_dialog.isVisible()
    window.model_dialog.hide()
    window.navigate("settings")
    assert window.settings_dialog.isVisible()
    window.settings_dialog.hide()
    window.close()


def test_workspace_tool_buttons_switch_to_the_expected_mode(qtbot, tmp_path, monkeypatch):
    window, _settings = make_window(tmp_path, monkeypatch)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(30)

    actions = (
        ("record", "recording"),
        ("batch", "batch"),
        ("library", "audio"),
        ("cleanup", "cleanup"),
    )
    for action, expected in actions:
        assert window.workspace.trigger(action)
        assert window.workspace.current_view == expected

    assert window.workspace.trigger("models")
    assert window.model_dialog.isVisible()
    window.model_dialog.hide()
    assert window.workspace.trigger("settings")
    assert window.settings_dialog.isVisible()
    window.settings_dialog.hide()
    window.close()


def test_empty_workspace_hides_optional_panels_without_forgetting_timeline_preference(
    qtbot, tmp_path, monkeypatch
):
    window, settings = make_window(tmp_path, monkeypatch)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(30)

    assert window.assistant_dock.isHidden()
    assert window.timeline_dock.isHidden()
    assert settings.settings.inspector_visible is False
    assert settings.settings.timeline_visible is True
    assert window.audio_transport.player is window.transcription_page.player
    assert not window.audio_transport.play_button.isEnabled()

    # Selecting media reveals the shared transport and waveform when preferred.
    window._load_waveform(str(tmp_path / "sample.wav"))
    assert not window.timeline_dock.isHidden()
    assert window.audio_transport.play_button.isEnabled()
    window.close()
