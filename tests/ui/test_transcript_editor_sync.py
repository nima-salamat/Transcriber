"""Regression tests for keeping all transcript editing surfaces in sync."""
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
from transcriber.transcription.segments import TranscriptSegment
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
    return MainWindow(paths, settings, history, database, manager), history


def load_sample_transcript(window, history):
    segment = TranscriptSegment(0.0, 2.0, "Original transcript", id="segment-1", language="en")
    transcript_id = history.save(
        title="Sync regression",
        text="Original transcript",
        segments=[segment],
        engine="test",
        language="en",
        duration=2.0,
        original_text="Original transcript",
    )
    page = window.transcription_page
    page._load_generation += 1
    page._apply_history_record(page._load_generation, history.get(transcript_id))
    return transcript_id


def test_direct_text_edit_updates_segment_editor_and_subtitle_views(qtbot, tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window, history = make_window(tmp_path, monkeypatch)
    qtbot.addWidget(window)
    window.show()
    transcript_id = load_sample_transcript(window, history)

    window.transcription_page.editor.setPlainText("Edited transcript")

    assert window.transcription_page.segments[0].text == "Edited transcript"
    assert window.editor_page.document.text == "Edited transcript", (
        "Direct edits in the New Transcription text editor must update the canonical "
        "segment document used by the Transcript Editor and Agent."
    )
    assert window.subtitle_page.segments[0].text == "Edited transcript", (
        "Subtitle Studio must not retain a stale copy after transcript text editing."
    )
    assert history.get(transcript_id)["text"] == "Original transcript"
    window.close()


def test_direct_text_edit_is_autosaved_without_navigation_or_close(qtbot, tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window, history = make_window(tmp_path, monkeypatch)
    qtbot.addWidget(window)
    window.show()
    transcript_id = load_sample_transcript(window, history)

    window.transcription_page.editor.setPlainText("Autosaved transcript")
    qtbot.wait(1100)

    saved = history.get(transcript_id)
    assert saved["text"] == "Autosaved transcript", (
        "Typing in the New Transcription editor must schedule autosave; persistence "
        "must not depend on navigating away, opening another transcript or closing the app."
    )
    window.close()
