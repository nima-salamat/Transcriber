"""Searchable transcript history and project actions."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QLabel,
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
        layout.setContentsMargins(2, 2, 10, 12)
        layout.setSpacing(13)
        layout.addWidget(page_header("History", "All transcripts are stored in your local SQLite database."))

        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search titles and transcript content…")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumHeight(40)
        search_row.addWidget(self.search, 1)
        layout.addLayout(search_row)

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(220)
        self.search_timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda: self.search_timer.start())

        card = Card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 14, 14, 14)
        card_layout.setSpacing(10)
        self.items = QListWidget()
        self.items.setSpacing(4)
        self.items.setMinimumHeight(180)
        self.items.itemDoubleClicked.connect(self._open)
        self.items.currentItemChanged.connect(lambda *_: self._update_action_state())
        card_layout.addWidget(self.items, 1)

        self.empty_state = QLabel("No saved transcripts yet. Start a transcription to build your history.")
        self.empty_state.setObjectName("PageEmptyState")
        self.empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state.setWordWrap(True)
        self.empty_state.setMinimumHeight(150)
        card_layout.addWidget(self.empty_state, 1)
        self.items.hide()

        primary_actions = QHBoxLayout()
        self.open_button = primary_button("Open transcript")
        self.open_button.clicked.connect(self.open_selected)
        self.rename_button = QPushButton("Rename")
        self.rename_button.clicked.connect(self.rename_selected)
        self.favorite_button = QPushButton("Pin / unpin")
        self.favorite_button.clicked.connect(self.toggle_favorite)
        primary_actions.addWidget(self.open_button)
        primary_actions.addWidget(self.rename_button)
        primary_actions.addWidget(self.favorite_button)
        primary_actions.addStretch(1)
        card_layout.addLayout(primary_actions)

        secondary_actions = QHBoxLayout()
        self.duplicate_button = QPushButton("Duplicate")
        self.duplicate_button.clicked.connect(self.duplicate_selected)
        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("Danger")
        self.delete_button.clicked.connect(self.delete_selected)
        secondary_actions.addWidget(self.duplicate_button)
        secondary_actions.addWidget(self.delete_button)
        secondary_actions.addStretch(1)
        card_layout.addLayout(secondary_actions)
        layout.addWidget(card, 1)
        self._update_action_state()
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
            item.setData(Qt.ItemDataRole.UserRole, row["id"])
            self.items.addItem(item)

        has_rows = bool(rows)
        self.items.setVisible(has_rows)
        self.empty_state.setVisible(not has_rows)
        self.empty_state.setText(
            "No transcripts match this search. Try a different title or phrase."
            if self.search.text().strip()
            else "No saved transcripts yet. Start a transcription to build your history."
        )
        self._update_action_state()

    def _selected_id(self):
        item = self.items.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _update_action_state(self):
        enabled = self._selected_id() is not None
        for button in (
            self.open_button, self.rename_button, self.favorite_button,
            self.duplicate_button, self.delete_button,
        ):
            button.setEnabled(enabled)

    def _open(self, item):
        transcript_id = item.data(Qt.ItemDataRole.UserRole)
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
