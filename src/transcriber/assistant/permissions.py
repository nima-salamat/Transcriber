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


DEFAULT_PERMISSIONS = frozenset({AgentPermission.READ_ONLY, AgentPermission.EDIT_CONTENT})


class PermissionDenied(PermissionError):
    pass
