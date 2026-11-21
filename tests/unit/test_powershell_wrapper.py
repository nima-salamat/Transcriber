from transcriber.assistant.powershell import (\n    build_powershell_script,\n    requires_destructive_permission,\n)


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



def test_normal_powershell_commands_are_not_misclassified_as_destructive():
    assert not requires_destructive_permission("Get-Process | Format-Table")
    assert not requires_destructive_permission("Get-Location | Format-List")
    assert not requires_destructive_permission("Get-ChildItem -Force")
    assert not requires_destructive_permission("New-Item -ItemType Directory -Path .\\build")


def test_recognized_file_and_package_mutations_require_destructive_permission():
    assert requires_destructive_permission("Remove-Item .\\build -Recurse")
    assert requires_destructive_permission("Set-Content .\\config.json '{}'")
    assert requires_destructive_permission("Move-Item .\\a.txt .\\b.txt")
    assert requires_destructive_permission("winget install Git.Git")
    assert requires_destructive_permission("pip install pytest")


def test_system_administration_and_high_impact_commands_require_destructive_permission():
    assert requires_destructive_permission("Format-Volume -DriveLetter X -FileSystem NTFS")
    assert requires_destructive_permission("reg.exe delete HKCU\\Software\\Example /f")
    assert requires_destructive_permission(
        "Start-Process -FilePath powershell.exe -Verb RunAs"
    )
    assert requires_destructive_permission("Invoke-Expression 'Get-Process'")
    assert requires_destructive_permission("git reset --hard HEAD~1")
