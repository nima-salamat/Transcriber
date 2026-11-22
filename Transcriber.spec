# PyInstaller entry point for the native Transcriber desktop application.
# Build with: python -m PyInstaller --noconfirm --clean Transcriber.spec

from pathlib import Path
import struct
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from PySide6.QtCore import QBuffer, QIODevice, QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(SPECPATH).resolve()
SOURCE = ROOT / "src"
sys.path.insert(0, str(SOURCE))


def _write_icon_from_svg(svg_source: Path, icon_file: Path) -> None:
    """Create a multi-resolution Windows ICO from the app's bundled SVG mark."""
    renderer = QSvgRenderer(str(svg_source))
    if not renderer.isValid():
        raise RuntimeError(f"Could not render the application icon: {svg_source}")

    frames = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()

        buffer = QBuffer()
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
            raise RuntimeError("Could not open an in-memory buffer for the app icon.")
        saved = image.save(buffer, "PNG")
        png_data = bytes(buffer.data())
        buffer.close()
        if not saved or not png_data:
            raise RuntimeError(f"Could not encode the {size}px application icon.")
        frames.append((size, png_data))

    directory = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    entries = []
    for size, png_data in frames:
        dimension = 0 if size == 256 else size
        entries.append(
            struct.pack(
                "<BBBBHHII",
                dimension,
                dimension,
                0,
                0,
                1,
                32,
                len(png_data),
                offset,
            )
        )
        offset += len(png_data)

    icon_file.parent.mkdir(parents=True, exist_ok=True)
    icon_file.write_bytes(
        directory
        + b"".join(entries)
        + b"".join(png_data for _size, png_data in frames)
    )


APP_ICON = ROOT / "release" / "Transcriber.ico"
_write_icon_from_svg(
    SOURCE / "transcriber" / "assets" / "icons" / "transcriber.svg",
    APP_ICON,
)

# Faster-Whisper loads its Silero VAD ONNX graph from a path relative to its
# installed package. PyInstaller does not include third-party package data
# automatically, so collect it alongside Transcriber's own static assets.
datas = collect_data_files("transcriber")
datas += collect_data_files("faster_whisper")
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
    icon=str(APP_ICON),
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
