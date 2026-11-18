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
        "Inspector": window.assistant_dock,
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
    assert window.workspace_splitter.widget(1) is window.assistant_dock
    assert window.workspace_splitter.layoutDirection() == Qt.LayoutDirection.LeftToRight
    assert window.dockWidgetArea(window.timeline_dock) == Qt.DockWidgetArea.BottomDockWidgetArea
    assert window.timeline_dock.minimumHeight() == window.timeline_dock.maximumHeight() == 172

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


def test_inspector_can_grow_and_waveform_stays_compact(qtbot, tmp_path, monkeypatch):
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
    available_width = window.workspace_splitter.width()
    target_width = min(500, max(inspector.minimumWidth(), available_width - 186))
    window.workspace_splitter.setSizes([available_width - target_width, target_width])
    qtbot.wait(30)
    assert inspector.width() >= target_width - 5
    resized = window.workspace_splitter.sizes()
    assert resized[1] >= target_width - 5
    assert resized[0] >= 175
    remembered_width = inspector.width()
    window._animate_drawer(inspector, False, "width")
    assert inspector.isHidden()
    window._animate_drawer(inspector, True, "width")
    qtbot.wait(30)
    assert not inspector.isHidden()
    assert inspector.width() >= remembered_width - 10

    # Waveform has one compact size. It can be shown/hidden, not vertically
    # dragged, so the actual workspace keeps its available height.
    waveform = window.timeline_dock
    assert waveform.minimumHeight() == 172
    assert waveform.maximumHeight() == 172
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
