[CmdletBinding()]
param(
    [switch]$WithCuda
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepositoryRoot

if ($env:OS -ne "Windows_NT") {
    throw "This packaging script must be run on Windows."
}

$Extras = "packaging,asr,voice,documents,agent"
if ($WithCuda) {
    $Extras += ",gpu"
}

Write-Host "Installing Transcriber build dependencies..."
python -m pip install --upgrade ".[${Extras}]"
if ($LASTEXITCODE -ne 0) {
    throw "Could not install the Transcriber build dependencies."
}

Write-Host "Building the windowed Transcriber application..."
python -m PyInstaller --noconfirm --clean .\Transcriber.spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed to build Transcriber."
}

$Executable = Join-Path $RepositoryRoot "dist\Transcriber\Transcriber.exe"
if (-not (Test-Path $Executable)) {
    throw "The build finished without producing $Executable"
}

Write-Host "Build complete: $Executable"
