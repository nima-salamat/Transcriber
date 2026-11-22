"""Explicit permission boundaries for Agent-driven operations."""

from __future__ import annotations

from enum import StrEnum


class AgentPermission(StrEnum):
    READ_ONLY = "read_only"
    EDIT_CONTENT = "edit_content"
    MODIFY_SETTINGS = "modify_settings"
    AUDIO_CAPTURE = "audio_capture"
    FILE_EXPORT = "file_export"
    MODEL_MANAGEMENT = "model_management"
    DESTRUCTIVE_ACTIONS = "destructive_actions"
    DESKTOP_CONTROL = "desktop_control"
    BROWSER_CONTROL = "browser_control"
    COMMAND_EXECUTION = "command_execution"


DEFAULT_PERMISSIONS = frozenset({
    AgentPermission.READ_ONLY,
    AgentPermission.EDIT_CONTENT,
    # Command execution is a usable capability, never silent authorization:
    # system.run_command is marked requires_approval and opens a GUI prompt
    # for every invocation before PowerShell is launched.
    AgentPermission.COMMAND_EXECUTION,
})


class PermissionDenied(PermissionError):
    pass
