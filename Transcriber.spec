# PyInstaller entry point for the native Transcriber desktop application.
# Build with: python -m PyInstaller --noconfirm --clean Transcriber.spec

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve()
SOURCE = ROOT / "src"
sys.path.insert(0, str(SOURCE))

datas = collect_data_files("transcriber")
hiddenimports = collect_submodules("transcriber")

a = Analysis(
    [str(SOURCE / "transcriber" / "__main__.py")],
    pathex=[str(SOURCE)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Transcriber",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Transcriber",
)
