"""Cross-platform helpers for spawning background child processes from the GUI."""

from __future__ import annotations

import os
import subprocess


def hidden_subprocess_creation_flags(
    *,
    is_windows: bool | None = None,
    new_process_group: bool = False,
) -> int:
    """Return Windows flags that prevent child command tools opening console windows.

    GUI applications such as Chrome or Windows Terminal should not use this helper:
    their visible windows are intentional. Use it for background commands whose
    output is captured or redirected into the Transcriber interface.
    """
    windows = os.name == "nt" if is_windows is None else bool(is_windows)
    if not windows:
        return 0

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if new_process_group:
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return flags
