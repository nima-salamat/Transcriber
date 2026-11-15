"""Regression tests for discoverable workspace panel visibility controls.

The native QDockWidget close button must never leave a panel unreachable.  The
View menu is the single, discoverable source of truth for dock visibility.
"""
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
    pytest.fail("MainWindow has no View menu; closed workspace panels cannot be rediscovered.")


def test_view_menu_can_reopen_each_closeable_workspace_dock(qtbot, tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    window, _settings = make_window(tmp_path, monkeypatch)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(30)

    actions = _menu_actions(_view_menu(window))
    expected = {
        "Inspector / AI Assistant": window.assistant_dock,
        "Audio Timeline": window.timeline_dock,
    }
    for title, dock in expected.items():
        assert title in actions, f"View menu is missing a toggle for {title}"
        action = actions[title]
        assert action.isCheckable(), f"{title} visibility action must be checkable"
        assert dock.isVisible()
        dock.close()
        qtbot.wait(10)
        assert not dock.isVisible()
        assert not action.isChecked()
        action.trigger()
        qtbot.wait(10)
        assert dock.isVisible(), f"{title} could not be restored from View menu"
        assert action.isChecked()

    window.close()


def test_restore_default_layout_restores_the_workspace_docks(qtbot, tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    window, _settings = make_window(tmp_path, monkeypatch)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(30)

    actions = _menu_actions(_view_menu(window))
    restore = actions.get("Restore Default Layout")
    assert restore is not None, "View menu needs a Restore Default Layout action"

    window.assistant_dock.close()
    window.timeline_dock.close()
    qtbot.wait(10)
    assert not window.assistant_dock.isVisible()
    assert not window.timeline_dock.isVisible()

    restore.trigger()
    qtbot.wait(20)
    assert window.assistant_dock.isVisible()
    assert window.timeline_dock.isVisible()
    assert window.dockWidgetArea(window.assistant_dock) == Qt.DockWidgetArea.RightDockWidgetArea
    assert window.dockWidgetArea(window.timeline_dock) == Qt.DockWidgetArea.BottomDockWidgetArea

    window.close()


def test_global_search_opens_an_in_window_popup_without_navigating_away(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QWidget

    window, _settings = make_window(tmp_path, monkeypatch)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(30)
    window.navigate("home")

    window.global_search.setText("meeting notes")
    qtbot.wait(400)

    assert window.stack.currentWidget() is window.home_page, (
        "Typing in global search should not navigate away from the current workspace."
    )
    popups = [
        child for child in window.findChildren(QWidget)
        if child.objectName() == "GlobalSearchPopup" and child.isVisible()
    ]
    assert popups, "Global search must show results in a popup inside the main window."
    assert all(child.window() is window for child in popups)
    window.close()


def test_command_palette_is_an_in_window_popup_not_a_modal_dialog(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog, QWidget

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
    assert popups, "Ctrl+K must open a searchable in-window command palette."
    assert all(child.window() is window for child in popups)
    assert QApplication.activeModalWidget() is None
    window.close()


def test_drawer_open_close_keeps_native_resize_constraints(qtbot, tmp_path, monkeypatch):
    window, _settings = make_window(tmp_path, monkeypatch)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(30)

    cases = (
        (window.assistant_dock, "width", 360, Qt.Orientation.Horizontal, 300),
        (window.timeline_dock, "height", 220, Qt.Orientation.Vertical, 160),
    )
    for dock, dimension, preferred, orientation, minimum in cases:
        window._animate_drawer(dock, False, dimension)
        assert dock.isHidden()

        for _ in range(3):
            window._animate_drawer(dock, True, dimension)
            qtbot.wait(10)
            assert not dock.isHidden()
            if dimension == "width":
                assert dock.minimumWidth() == minimum
                assert dock.maximumWidth() >= dock.minimumWidth()
            else:
                assert dock.minimumHeight() == minimum
                assert dock.maximumHeight() >= dock.minimumHeight()
            window.resizeDocks([dock], [preferred], orientation)
            window._animate_drawer(dock, False, dimension)
            assert dock.isHidden()

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
