"""PowerShell script wrapper used by the Python-owned Agent command executor."""

from __future__ import annotations


def build_powershell_script(command: str) -> str:
    """Build a non-elevated script wrapper that propagates native exit codes.

    PowerShell stores the exit code of the most recent native process in
    $LASTEXITCODE; the outer powershell.exe/pwsh.exe process does not reliably
    propagate that code unless the script explicitly exits with it.
    Terminating PowerShell errors are converted into exit code 1 and stderr.
    """
    source = str(command or "")
    return (
        "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding; "
        "$ErrorActionPreference = 'Stop'; "
        "try { & { " + source + " }; "
        "if ($null -ne $LASTEXITCODE) { exit [int]$LASTEXITCODE }; exit 0 "
        "} catch { [Console]::Error.WriteLine($_.ToString()); exit 1 }"
    )
