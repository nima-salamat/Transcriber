"""Offline Lucide SVG icon registry; icons are rendered with the active palette."""

from __future__ import annotations

from pathlib import Path


class IconRegistry:
    ICONS = {
        "home": "house.svg",
        "record": "mic.svg",
        "projects": "folder-open.svg",
        "settings": "settings-2.svg",
        "search": "search.svg",
        "assistant": "sparkles.svg",
        "waveform": "audio-waveform.svg",
        "back": "chevron-left.svg",
        "forward": "chevron-right.svg",
        "activity": "list-checks.svg",
        "models": "layers.svg",
        "controls": "sliders-horizontal.svg",
        "pause": "pause.svg",
        "play": "play.svg",
        "stop": "square.svg",
        "discard": "trash-2.svg",
        "skip_back": "skip-back.svg",
        "skip_forward": "skip-forward.svg",
    }

    def __init__(self, asset_dir: Path | None = None):
        self.asset_dir = Path(asset_dir or Path(__file__).resolve().parents[2] / "assets" / "icons")
        self._cache: dict[tuple[str, str, int], object] = {}

    def path(self, name: str) -> Path:
        try:
            filename = self.ICONS[name]
        except KeyError as exc:
            raise KeyError(f"Unknown Lucide icon: {name}") from exc
        target = self.asset_dir / filename
        if not target.is_file():
            raise FileNotFoundError(f"Bundled Lucide SVG is missing: {target}")
        return target

    def icon(self, name: str, color: str = "#9aa8b8", size: int = 20):
        from PySide6.QtCore import QByteArray
        from PySide6.QtGui import QIcon, QPainter, QPixmap
        from PySide6.QtSvg import QSvgRenderer

        key = (name, color, int(size))
        if key in self._cache:
            return self._cache[key]
        source = self.path(name).read_text(encoding="utf-8")
        source = source.replace("currentColor", color)
        renderer = QSvgRenderer(QByteArray(source.encode("utf-8")))
        if not renderer.isValid():
            raise ValueError(f"Invalid Lucide SVG asset: {name}")
        pixmap = QPixmap(size, size)
        pixmap.fill(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        result = QIcon(pixmap)
        self._cache[key] = result
        return result
