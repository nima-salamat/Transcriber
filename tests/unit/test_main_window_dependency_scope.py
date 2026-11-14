"""Static regression checks for MainWindow startup dependencies."""
from __future__ import annotations

import ast
from pathlib import Path


def test_main_window_builder_uses_instance_dependencies() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "src" / "transcriber" / "ui" / "main_window.py"
    ).read_text(encoding="utf-8")
    module = ast.parse(source)
    main_window = next(
        node for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "MainWindow"
    )
    builder = next(
        node for node in main_window.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_build_ui"
    )

    # These are constructor arguments, not locals in _build_ui. A bare name
    # here raises NameError when the GUI is constructed.
    dependency_names = {"paths", "settings_store", "history", "database", "model_manager"}
    referenced_names = {
        node.id for node in ast.walk(builder)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    assert not (dependency_names & referenced_names)

    # Keep a positive assertion so the test catches accidental removal of the
    # actual dependencies rather than merely the bare-name spellings.
    attributes = {
        node.attr for node in ast.walk(builder)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    }
    assert dependency_names <= attributes



def test_drawer_controls_are_compact_and_permanently_right_aligned() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "src" / "transcriber" / "ui" / "main_window.py"
    ).read_text(encoding="utf-8")

    assert "status.addPermanentWidget(self.assistant_drawer_button)" in source
    assert "status.addPermanentWidget(self.timeline_drawer_button)" in source
    assert "status.addWidget(self.assistant_drawer_button)" not in source
    assert "status.addWidget(self.timeline_drawer_button)" not in source
    assert "drawer_button.setFixedHeight(25)" in source


def test_dock_geometry_uses_physical_left_to_right_direction() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "src" / "transcriber" / "ui" / "main_window.py"
    ).read_text(encoding="utf-8")

    assert "self.setLayoutDirection(Qt.LeftToRight)" in source
    assert "self.assistant_dock.setLayoutDirection(Qt.LeftToRight)" in source
    assert "self.timeline_dock.setLayoutDirection(Qt.LeftToRight)" in source
    assert "self.assistant_dock.setAllowedAreas(Qt.RightDockWidgetArea)" in source
    assert "self.assistant_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)" in source
    assert "self.timeline_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)" in source
