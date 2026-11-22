from __future__ import annotations

from pathlib import Path, PureWindowsPath

import pytest

from transcriber.opencode.acp_client import (
    ACPError,
    build_opencode_invocation,
    resolve_opencode_executable,
)


def test_windows_resolver_prefers_npm_cmd_wrapper_for_extensionless_selection(tmp_path):
    selected = tmp_path / "opencode"
    wrapper = tmp_path / "opencode.cmd"
    selected.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    wrapper.write_text("@echo off\r\n", encoding="utf-8")

    resolved = resolve_opencode_executable(str(selected), is_windows=True)

    assert Path(resolved) == wrapper


def test_windows_resolver_reports_extensionless_npm_script_without_wrapper(tmp_path):
    selected = tmp_path / "opencode"
    selected.write_text("#!/usr/bin/env node\n", encoding="utf-8")

    with pytest.raises(ACPError, match="opencode.cmd"):
        resolve_opencode_executable(str(selected), is_windows=True)


def test_windows_cmd_launcher_is_executed_through_command_processor():
    executable = r"C:\Program Files\OpenCode npm\opencode.cmd"

    command, options = build_opencode_invocation(
        executable, ["acp"], is_windows=True
    )

    assert isinstance(command, str)
    assert command == (
        '"C:\\Program Files\\OpenCode npm\\opencode.cmd" acp'
    )
    assert options == {"shell": True}


def test_windows_exe_launcher_does_not_use_shell():
    command, options = build_opencode_invocation(
        r"C:\Program Files\OpenCode\opencode.exe",
        ["acp"],
        is_windows=True,
    )

    assert command == [r"C:\Program Files\OpenCode\opencode.exe", "acp"]
    assert options == {}


def test_windows_powershell_launcher_uses_explicit_file_mode(monkeypatch):
    monkeypatch.setattr(
        "transcriber.opencode.acp_client.shutil.which",
        lambda _name: None,
    )

    command, options = build_opencode_invocation(
        r"C:\Users\nima\AppData\Roaming\npm\opencode.ps1",
        ["acp"],
        is_windows=True,
    )

    assert command == [
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        r"C:\Users\nima\AppData\Roaming\npm\opencode.ps1",
        "acp",
    ]
    assert options == {}


def test_non_windows_launcher_remains_a_normal_argv():
    command, options = build_opencode_invocation(
        "/usr/local/bin/opencode",
        ["acp"],
        is_windows=False,
    )

    assert command == ["/usr/local/bin/opencode", "acp"]
    assert options == {}


def test_windows_suffix_detection_uses_windows_paths():
    assert PureWindowsPath(r"C:\Users\nima\opencode.cmd").suffix == ".cmd"
