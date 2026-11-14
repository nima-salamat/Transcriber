"""Local audio library browser."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from transcriber.ui.widgets import Card, page_header, primary_button
from transcriber.ui.workers import FunctionWorker


class AudioLibraryPage(QWidget):
    open_audio = Signal(str)
    status_message = Signal(str)

    def __init__(self, paths, history, thread_pool, parent=None):
        super().__init__(parent)
        self.paths = paths
        self.history = history
        self.thread_pool = thread_pool
        self._generation = 0
        self._worker: FunctionWorker | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        layout.addWidget(page_header("Audio library", "Recordings and imported source files referenced by your transcripts."))
        card = Card()
        inner = QVBoxLayout(card)
        inner.setContentsMargins(12, 12, 12, 12)
        self.items = QListWidget()
        self.items.itemDoubleClicked.connect(lambda item: self.open_audio.emit(item.data(256)))
        inner.addWidget(self.items, 1)
        buttons = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        open_file = primary_button("Open selected")
        open_file.clicked.connect(self.open_selected)
        folder = QPushButton("Show recordings folder")
        folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.paths.recordings))))
        buttons.addWidget(refresh)
        buttons.addWidget(open_file)
        buttons.addStretch(1)
        buttons.addWidget(folder)
        inner.addLayout(buttons)
        layout.addWidget(card, 1)
        self.refresh()

    def refresh(self):
        self._generation += 1
        generation = self._generation
        paths = self.paths
        history = self.history

        def load(_emit):
            sources = {row["source_path"] for row in history.list(limit=1000) if row["source_path"]}
            result = [(source, Path(source).is_file(), "source") for source in sources]
            for path in sorted(paths.recordings.glob("*")):
                if path.is_file() and str(path) not in sources:
                    result.append((str(path), True, "recording"))
            return sorted(result, key=lambda item: Path(item[0]).name.casefold())

        worker = FunctionWorker(load)
        worker.signals.result.connect(lambda rows, current=generation: self._apply_rows(current, rows))
        worker.signals.error.connect(lambda message: self.status_message.emit(f"Could not scan audio library: {message}"))
        self._worker = worker
        self.thread_pool.start(worker)

    def _apply_rows(self, generation: int, rows):
        if generation != self._generation:
            return
        self.items.clear()
        for source, exists, kind in rows:
            path = Path(source)
            label = "available" if exists and kind == "source" else "missing" if not exists else "recording"
            item = QListWidgetItem(f"{path.name}  ·  {label}")
            item.setData(256, str(path))
            self.items.addItem(item)

    def open_selected(self):
        item = self.items.currentItem()
        if item:
            self.open_audio.emit(item.data(256))
