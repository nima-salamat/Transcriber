from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

from transcriber.core.process import hidden_subprocess_creation_flags


def test_hidden_process_flags_are_no_console_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False)

    assert hidden_subprocess_creation_flags(is_windows=True) == 0x08000000
    assert hidden_subprocess_creation_flags(
        is_windows=True, new_process_group=True
    ) == 0x08000200


def test_hidden_process_flags_are_portable() -> None:
    assert hidden_subprocess_creation_flags(is_windows=False) == 0


def test_windows_desktop_entry_point_is_a_gui_script() -> None:
    root = Path(__file__).resolve().parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["gui-scripts"]["transcriber"] == "transcriber.__main__:main"
    assert "transcriber" not in project["project"].get("scripts", {})
    assert project["project"]["scripts"]["transcriber-mcp"] == "transcriber.mcp_server:main"


def test_pyinstaller_spec_builds_without_a_console_window() -> None:
    root = Path(__file__).resolve().parents[2]
    spec = (root / "Transcriber.spec").read_text(encoding="utf-8")

    assert 'name="Transcriber"' in spec
    assert "console=False" in spec



def test_inno_setup_builds_a_per_user_installer_with_shortcuts() -> None:
    root = Path(__file__).resolve().parents[2]
    script = (root / "installer" / "windows" / "Transcriber.iss").read_text(encoding="utf-8")

    assert "PrivilegesRequired=lowest" in script
    assert r"DefaultDirName={localappdata}\Programs\Transcriber" in script
    assert "Transcriber-Setup-{#AppVersion}-x64" in script
    assert "[Tasks]" in script and "desktopicon" in script
    assert "[Icons]" in script and "{autoprograms}" in script
