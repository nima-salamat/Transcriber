"""Static regression checks for PySide6 classes imported from their owning modules."""

from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src" / "transcriber"
EXPECTED_MODULES = {
    "QDesktopServices": "PySide6.QtGui",
    "QMediaDevices": "PySide6.QtMultimedia",
}


def test_pyside6_classes_are_imported_from_their_owning_modules() -> None:
    seen: set[str] = set()
    misplaced: list[str] = []

    for source_file in SOURCE_ROOT.rglob("*.py"):
        try:
            tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        except SyntaxError as exc:  # pragma: no cover - compileall reports syntax errors separately
            raise AssertionError(f"Invalid Python syntax in {source_file}: {exc}") from exc

        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            for alias in node.names:
                expected_module = EXPECTED_MODULES.get(alias.name)
                if expected_module is None:
                    continue
                seen.add(alias.name)
                if node.module != expected_module:
                    misplaced.append(
                        f"{source_file.relative_to(PROJECT_ROOT)}: "
                        f"{alias.name} imported from {node.module}; expected {expected_module}"
                    )

    assert seen == set(EXPECTED_MODULES), (
        "Expected Qt classes were not found in source imports: "
        f"{sorted(set(EXPECTED_MODULES) - seen)}"
    )
    assert not misplaced, "Invalid PySide6 imports:\n" + "\n".join(misplaced)
