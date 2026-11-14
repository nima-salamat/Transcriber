"""Searchable transcript history and project actions."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from transcriber.ui.widgets import Card, page_header, primary_button
from transcriber.ui.workers import FunctionWorker


class HistoryPage(QWidget):
    open_transcript = Signal(str)
    status_message = Signal(str)

    def __init__(self, history, thread_pool, parent=None):
        super().__init__(parent)
        self.history = history
        self.thread_pool = thread_pool
        self._generation = 0
        self._worker: FunctionWorker | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        layout.addWidget(page_header("History", "All transcripts are stored in your local SQLite database."))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search titles and transcript content…")
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(220)
        self.search_timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda: self.search_timer.start())
        layout.addWidget(self.search)
        card = Card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        self.items = QListWidget()
        self.items.itemDoubleClicked.connect(self._open)
        card_layout.addWidget(self.items, 1)
        actions = QHBoxLayout()
        open_button = primary_button("Open transcript")
        open_button.clicked.connect(self.open_selected)
        rename_button = QPushButton("Rename")
        rename_button.clicked.connect(self.rename_selected)
        favorite_button = QPushButton("Pin / unpin")
        favorite_button.clicked.connect(self.toggle_favorite)
        duplicate_button = QPushButton("Duplicate")
        duplicate_button.clicked.connect(self.duplicate_selected)
        delete_button = QPushButton("Delete")
        delete_button.setObjectName("Danger")
        delete_button.clicked.connect(self.delete_selected)
        for button in (open_button, rename_button, favorite_button, duplicate_button, delete_button):
            actions.addWidget(button)
        card_layout.addLayout(actions)
        layout.addWidget(card, 1)
        self.refresh()

    def refresh(self, *_):
        self._generation += 1
        generation = self._generation
        query = self.search.text()
        worker = FunctionWorker(lambda _emit: self.history.list(query, limit=500))
        worker.signals.result.connect(lambda rows, current=generation: self._apply_rows(current, rows))
        worker.signals.error.connect(lambda message: self.status_message.emit(f"Could not load history: {message}"))
        self._worker = worker
        self.thread_pool.start(worker)

    def _apply_rows(self, generation: int, rows):
        if generation != self._generation:
            return
        self.items.clear()
        for row in rows:
            pinned = "★  " if row["favorite"] else ""
            details = f"{row['updated_at'][:16].replace('T', ' ')}  ·  {row['engine']}  ·  {row['language'] or 'Unknown language'}"
            item = QListWidgetItem(f"{pinned}{row['title']}\n{details}\n{row['preview']}")
            item.setData(256, row["id"])
            self.items.addItem(item)

    def _selected_id(self):
        item = self.items.currentItem()
        return item.data(256) if item else None

    def _open(self, item):
        transcript_id = item.data(256)
        if transcript_id:
            self.open_transcript.emit(transcript_id)

    def open_selected(self):
        transcript_id = self._selected_id()
        if transcript_id:
            self.open_transcript.emit(transcript_id)

    def rename_selected(self):
        transcript_id = self._selected_id()
        if not transcript_id:
            return
        from PySide6.QtWidgets import QInputDialog
        record = self.history.get(transcript_id)
        title, accepted = QInputDialog.getText(self, "Rename transcript", "Title:", text=record["title"])
        if accepted and title.strip():
            self.history.rename(transcript_id, title)
            self.refresh()

    def toggle_favorite(self):
        transcript_id = self._selected_id()
        if transcript_id:
            record = self.history.get(transcript_id)
            self.history.set_favorite(transcript_id, not bool(record["favorite"]))
            self.refresh()

    def duplicate_selected(self):
        transcript_id = self._selected_id()
        if transcript_id:
            self.history.duplicate(transcript_id)
            self.refresh()
            self.status_message.emit("Transcript duplicated")

    def delete_selected(self):
        transcript_id = self._selected_id()
        if not transcript_id:
            return
        answer = QMessageBox.question(
            self, "Delete transcript",
            "Delete this transcript from local history? This does not delete its source audio file.",
        )
        if answer == QMessageBox.Yes:
            self.history.delete(transcript_id)
            self.refresh()
            self.status_message.emit("Transcript deleted")
