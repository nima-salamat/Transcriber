from transcriber.assistant.powershell import build_powershell_script


def test_powershell_wrapper_propagates_native_exit_code_and_catches_errors():
    command = "python -m pytest -q"
    script = build_powershell_script(command)

    assert "[Console]::OutputEncoding" in script
    assert "$ErrorActionPreference = 'Stop'" in script
    assert "try { & { " + command + " }; " in script
    assert "if ($null -ne $LASTEXITCODE) { exit [int]$LASTEXITCODE }" in script
    assert "catch { [Console]::Error.WriteLine($_.ToString()); exit 1 }" in script


def test_powershell_wrapper_handles_simple_commands():
    command = "Get-Location"
    script = build_powershell_script(command)

    assert "& { Get-Location }; " in script
    assert script.endswith("catch { [Console]::Error.WriteLine($_.ToString()); exit 1 }")
