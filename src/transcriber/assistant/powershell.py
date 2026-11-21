"""PowerShell execution helpers and permission-aware risk classification."""

import re


MAX_COMMAND_LENGTH = 16_000
MAX_TIMEOUT_SECONDS = 3_600

# This is a permission gate, not a list of allowed commands. Ordinary PowerShell
# cmdlets (including Format-Table and Format-List) remain available. Recognized
# destructive/system-changing operations additionally require the user's
# Destructive actions permission; every command still receives explicit approval.
_DESTRUCTIVE_PATTERNS = (
    r"(?i)\b(?:remove-item|remove-itemproperty|del|erase|rmdir)\b",
    r"(?i)\b(?:set-content|add-content|clear-content|out-file)\b",
    r"(?i)\b(?:move-item|rename-item|copy-item)\b",
    r"(?i)\b(?:install-module|uninstall-module|update-module|"
    r"winget\s+(?:install|upgrade|uninstall)|"
    r"choco(?:latey)?\s+(?:install|upgrade|uninstall)|"
    r"pip(?:3)?\s+(?:install|uninstall)|"
    r"npm\s+(?:install|ci|update|uninstall)|"
    r"yarn\s+add|pnpm\s+add|dotnet\s+tool\s+(?:install|uninstall))\b",
    r"(?i)\b(?:format-volume|format-partition|diskpart|clear-disk|"
    r"initialize-disk|remove-partition|set-partition|bcdedit|"
    r"shutdown|restart-computer|stop-computer)\b",
    r"(?i)\breg(?:\.exe)?\s+(?:delete|add)\b",
    r"(?i)\b(?:set-itemproperty|new-itemproperty|remove-itemproperty|"
    r"set-executionpolicy|new-service|remove-service|set-service|"
    r"stop-service|disable-service|disable-netadapter|"
    r"remove-netfirewallrule|set-netfirewallprofile)\b",
    r"(?i)\bstart-process\b.{0,500}?-verb\s+runas\b",
    r"(?i)\b(?:invoke-expression|iex)\b",
    r"(?i)\bgit\s+(?:clean\s+-[^\s]*f|reset\s+--hard|push\s+--force)\b",
)


def requires_destructive_permission(command: str) -> bool:
    """Return True for known destructive/system-changing PowerShell operations.

    Arbitrary PowerShell cannot be classified perfectly with regular expressions.
    Every command still requires an explicit GUI approval showing the full script.
    """
    value = str(command or "")
    return any(re.search(pattern, value) for pattern in _DESTRUCTIVE_PATTERNS)


def build_powershell_script(command: str) -> str:
    """Build a wrapper that propagates native process exit codes and errors.

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
