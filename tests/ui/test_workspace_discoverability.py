"""Regression tests for the unified single-workspace application shell."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QInputDialog, QWidget

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


def _menu_actions(menu):
    return {
        action.text().replace("&", "").strip(): action
        for action in menu.actions()
        if not action.isSeparator() and action.text().strip()
    }


def _view_menu(window):
    for action in window.menuBar().actions():
        if action.menu() and action.text().replace("&", "").strip().casefold() == "view":
            return action.menu()
    pytest.fail("MainWindow has no View menu.")


def test_main_window_uses_one_primary_workspace(qtbot, tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    window, settings = make_window(tmp_path, monkeypatch)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(30)

    assert not window.sidebar.isVisible()
    assert window.nav_buttons == {}
    assert set(window.pages) == {"transcription", "editor", "subtitles", "recording", "batch"}
    assert window.stack.count() == 5
    assert window.workspace_mode_bar.isVisible()
    assert window.mode_buttons["transcription"].isChecked()
    assert window.editor_page.document is window.transcript_document
    assert window.transcription_page.document is window.transcript_document
    assert window.audio_transport.player is window.transcription_page.player
    assert window.transcription_page.player_card.isHidden()
    assert window.transcription_page.open_button.isHidden()
    assert window.transcription_page.export_button.isHidden()
    assert window.transcription_page.subtitle_export_button.isHidden()
    assert window.audio_transport.isHidden()
    assert not window.assistant_dock.isVisible()
    assert window.timeline_dock.isVisible()
    assert not window.library_dialog.isVisible()
    assert not window.model_dialog.isVisible()
    assert not window.preferences_dialog.isVisible()
    assert not window.cleanup_dialog.isVisible()
    assert settings.settings.sidebar_visible is False
    assert settings.settings.inspector_visible is False

    window.close()


def test_advanced_recognition_options_are_collapsed_by_default(qtbot, tmp_path, monkeypatch):
    window, _settings = make_window(tmp_path, monkeypatch)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(20)

    page = window.transcription_page
    assert page.model_combo.isVisible()
    assert page.language_combo.isVisible()
    assert not page.advanced_options_panel.isVisible()
    assert page.advanced_toggle.isVisible()

    page.advanced_toggle.click()
    assert page.advanced_options_panel.isVisible()
    assert page.beam_spin.isVisible()
    assert page.vad_check.isVisible()
    assert page.task_combo.isVisible()
    assert page.word_timestamps.isVisible()
    assert page.initial_prompt.isVisible()

    page.advanced_toggle.click()
    assert not page.advanced_options_panel.isVisible()
    window.close()


def test_transcript_segments_and_captions_are_workspace_modes(qtbot, tmp_path, monkeypatch):
    window, _settings = make_window(tmp_path, monkeypatch)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(20)

    window.navigate("editor")
    assert window.stack.currentWidget() is window.editor_page
    assert window.workspace_mode_bar.isVisible()
    assert window.mode_buttons["editor"].isChecked()

    window.navigate("subtitles")
    assert window.stack.currentWidget() is window.subtitle_page
    assert window.workspace_mode_bar.isVisible()
    assert window.mode_buttons["subtitles"].isChecked()

    window.navigate("transcription")
    assert window.stack.currentWidget() is window.transcription_page
    assert window.workspace_mode_bar.isVisible()
    assert window.mode_buttons["transcription"].isChecked()

    window.navigate("recording")
    assert window.stack.currentWidget() is window.recording_page
    assert not window.workspace_mode_bar.isVisible()

    window.navigate("batch")
    assert window.stack.currentWidget() is window.batch_page
    assert not window.workspace_mode_bar.isVisible()

    window.close()


def test_secondary_tools_open_as_contextual_non_modal_dialogs(qtbot, tmp_path, monkeypatch):
    window, _settings = make_window(tmp_path, monkeypatch)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(20)
    current = window.stack.currentWidget()

    window.show_library(0)
    assert window.library_dialog.isVisible()
    assert window.library_tabs.currentIndex() == 0
    assert window.library_dialog.isModal() is False

    window.show_library(1)
    assert window.library_tabs.currentIndex() == 1

    window.show_model_manager()
    assert window.model_dialog.isVisible()
    assert window.model_dialog.isModal() is False

    window.show_preferences()
    assert window.preferences_dialog.isVisible()
    assert window.preferences_dialog.isModal() is False

    window.show_audio_cleanup()
    assert window.cleanup_dialog.isVisible()
    assert window.cleanup_dialog.isModal() is False

    assert window.stack.currentWidget() is current
    window.close()


def test_view_menu_can_reopen_contextual_workspace_panels(qtbot, tmp_path, monkeypatch):
    window, _settings = make_window(tmp_path, monkeypatch)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(30)

    actions = _menu_actions(_view_menu(window))
    expected = {
        "Inspector / AI Assistant": window.assistant_dock,
        "Audio Timeline": window.timeline_dock,
    }
    assert not window.assistant_dock.isVisible()
    assert window.timeline_dock.isVisible()

    for title, dock in expected.items():
        assert title in actions, f"View menu is missing a toggle for {title}"
        action = actions[title]
        assert action.isCheckable()
        dock.close()
        qtbot.wait(10)
        assert not dock.isVisible()
        assert not action.isChecked()
        action.trigger()
        qtbot.wait(10)
        assert dock.isVisible(), f"{title} could not be restored from View menu"
        assert action.isChecked()

    window.close()


def test_restore_default_layout_keeps_inspector_optional_and_waveform_compact(
    qtbot, tmp_path, monkeypatch
):
    window, _settings = make_window(tmp_path, monkeypatch)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(30)

    actions = _menu_actions(_view_menu(window))
    restore = actions.get("Restore Default Layout")
    assert restore is not None

    window.assistant_dock.show()
    window.timeline_dock.hide()
    restore.trigger()
    qtbot.wait(20)

    assert not window.assistant_dock.isVisible()
    assert window.timeline_dock.isVisible()
    assert window.workspace_splitter.widget(1) is window.assistant_dock
    assert window.workspace_splitter.layoutDirection() == Qt.LayoutDirection.LeftToRight
    assert window.dockWidgetArea(window.timeline_dock) == Qt.DockWidgetArea.BottomDockWidgetArea
    assert window.timeline_dock.minimumHeight() == window.timeline_dock.maximumHeight() == 148

    window.close()


def test_global_search_does_not_navigate_away_from_current_mode(qtbot, tmp_path, monkeypatch):
    window, _settings = make_window(tmp_path, monkeypatch)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(30)
    window.navigate("editor")

    current = window.stack.currentWidget()
    window.global_search.setText("meeting notes")
    qtbot.wait(400)

    assert window.stack.currentWidget() is current
    popups = [
        child for child in window.findChildren(QWidget)
        if child.objectName() == "GlobalSearchPopup" and child.isVisible()
    ]
    assert popups
    assert all(child.window() is window for child in popups)
    window.close()


def test_command_palette_is_an_in_window_popup_not_a_modal_dialog(qtbot, tmp_path, monkeypatch):
    window, _settings = make_window(tmp_path, monkeypatch)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(30)

    def reject_legacy_dialog(*_args, **_kwargs):
        pytest.fail("Command palette must not use a separate QInputDialog window.")

    monkeypatch.setattr(QInputDialog, "getItem", reject_legacy_dialog)
    window.show_command_palette()

    popups = [
        child for child in window.findChildren(QWidget)
        if child.objectName() == "CommandPalettePopup" and child.isVisible()
    ]
    assert popups
    assert all(child.window() is window for child in popups)
    assert QApplication.activeModalWidget() is None
    window.close()


def test_toolbar_adapts_to_narrow_desktop_windows(qtbot, tmp_path, monkeypatch):
    window, _settings = make_window(tmp_path, monkeypatch)
    qtbot.addWidget(window)
    window.resize(820, 700)
    window.show()
    qtbot.wait(30)

    assert window.global_search.isHidden()
    assert window.assistant_button.isHidden()
    assert window.command_button.text() == "⌘K"
    assert window.model_button.text() == "Model"

    window.resize(1180, 780)
    qtbot.wait(30)
    assert not window.global_search.isHidden()
    assert not window.assistant_button.isHidden()
    assert window.command_button.text() == "Ctrl+K"
    assert window.model_button.text() != "Model"
    window.close()


def test_inspector_resizes_horizontally_and_waveform_stays_fixed(qtbot, tmp_path, monkeypatch):
    window, _settings = make_window(tmp_path, monkeypatch)
    qtbot.addWidget(window)
    window.resize(1280, 850)
    window.show()
    qtbot.wait(40)

    inspector = window.assistant_dock
    assert inspector.minimumWidth() >= 320
    assert inspector.maximumWidth() > 600
    assert window.workspace_splitter.widget(1) is inspector
    assert window.workspace_splitter.layoutDirection() == Qt.LayoutDirection.LeftToRight

    window._animate_drawer(inspector, True, "width")
    qtbot.wait(30)
    available_width = window.workspace_splitter.width()
    target_width = min(500, max(inspector.minimumWidth(), available_width - 540))
    window.workspace_splitter.setSizes([available_width - target_width, target_width])
    qtbot.wait(30)
    assert inspector.width() >= target_width - 5
    remembered_width = inspector.width()

    window._animate_drawer(inspector, False, "width")
    assert inspector.isHidden()
    window._animate_drawer(inspector, True, "width")
    qtbot.wait(30)
    assert not inspector.isHidden()
    assert inspector.width() >= remembered_width - 10

    waveform = window.timeline_dock
    assert waveform.minimumHeight() == 148
    assert waveform.maximumHeight() == 148
    fixed_height = waveform.height()
    window.resize(window.width(), window.height() + 120)
    qtbot.wait(30)
    assert waveform.height() == fixed_height

    for _ in range(3):
        window._animate_drawer(waveform, False, "height")
        assert waveform.isHidden()
        window._animate_drawer(waveform, True, "height")
        assert not waveform.isHidden()
        assert waveform.height() == fixed_height

    window.close()


def test_waveform_is_interactive_and_emits_seek_positions(qtbot):
    from transcriber.ui.components.waveform import WaveformTimeline

    app = QApplication.instance() or QApplication([])
    assert app is not None
    timeline = WaveformTimeline()
    timeline.resize(500, 150)
    timeline.set_waveform([0.25, 0.5, 0.75], 100.0)
    qtbot.addWidget(timeline)
    timeline.show()

    received = []
    timeline.seek_requested.connect(received.append)
    qtbot.mouseClick(timeline, Qt.MouseButton.LeftButton, pos=timeline.rect().center())

    assert timeline._interactive
    assert len(received) == 1
    assert 49.0 <= received[0] <= 51.0
