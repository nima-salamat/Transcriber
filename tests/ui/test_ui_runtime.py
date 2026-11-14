"""Real shell/navigation smoke tests for environments with the optional Qt stack."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt
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


def test_native_shell_navigation_theme_and_geometry(qtbot, tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window, settings = make_window(tmp_path, monkeypatch)
    qtbot.addWidget(window)
    window.resize(1040, 740)
    window.show()
    qtbot.wait(30)

    assert not (window.windowFlags() & Qt.WindowType.FramelessWindowHint)
    assert window.minimumWidth() >= 700
    assert window.stack.count() == len(window.pages) == 11
    assert set(window.pages) == {
        "home", "transcription", "recording", "batch", "history", "editor",
        "subtitles", "models", "audio", "cleanup", "settings",
    }

    for page_id in window.pages:
        window.navigate(page_id)
        assert window.stack.currentWidget() is window.pages[page_id][1]
        assert window.page_title.text() == window.pages[page_id][0]
        assert window.nav_buttons[page_id].isChecked()

    window.settings_page.theme.setCurrentIndex(window.settings_page.theme.findData("light"))
    assert settings.settings.theme == "light"
    assert app.styleSheet()

    window.settings_page.theme.setCurrentIndex(window.settings_page.theme.findData("dark"))
    assert settings.settings.theme == "dark"
    assert window.saveGeometry().isEmpty() is False

    window.thread_pool.waitForDone(5000)
    window.close()
    assert settings.settings.geometry
