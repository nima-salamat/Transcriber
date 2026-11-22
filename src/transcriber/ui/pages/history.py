"""Searchable transcript history and project actions."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from transcriber.ui.widgets import (
    Card,
    empty_state,
    page_header,
    primary_button,
    section_header,
    status_pill,
)
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
        self._records_by_id: dict[str, dict] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)
        layout.addWidget(page_header(
            "Transcript history",
            "Search, review and organize transcripts saved on this device.",
        ))

        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search transcript titles and content…")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumHeight(38)
        search_row.addWidget(self.search, 1)
        self.result_count = QLabel("—")
        self.result_count.setObjectName("Muted")
        search_row.addWidget(self.result_count)
        layout.addLayout(search_row)

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(220)
        self.search_timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda: self.search_timer.start())

        workspace = QHBoxLayout()
        workspace.setSpacing(14)

        list_panel = Card()
        list_panel.setObjectName("WorkspacePanel")
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(13, 13, 13, 13)
        list_layout.setSpacing(9)
        list_layout.addWidget(section_header("Saved transcripts", "Select an item to inspect its details."))

        self.items = QListWidget()
        self.items.setSpacing(2)
        self.items.setMinimumWidth(320)
        self.items.itemDoubleClicked.connect(self._open)
        self.items.currentItemChanged.connect(self._selection_changed)
        list_layout.addWidget(self.items, 1)

        self.empty_state = empty_state(
            "No matching transcripts",
            "Change the search phrase or create a new transcription to build your library.",
        )
        list_layout.addWidget(self.empty_state, 1)
        workspace.addWidget(list_panel, 3)

        detail_panel = Card()
        detail_panel.setObjectName("WorkspacePanel")
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(17, 16, 17, 16)
        detail_layout.setSpacing(12)
        detail_layout.addWidget(section_header("Transcript details", "Actions apply to the selected item."))

        self.detail_status = status_pill("Nothing selected")
        detail_layout.addWidget(self.detail_status, 0, Qt.AlignmentFlag.AlignLeft)
        self.detail_title = QLabel("Select a transcript")
        self.detail_title.setObjectName("HistoryDetailTitle")
        self.detail_title.setWordWrap(True)
        detail_layout.addWidget(self.detail_title)

        self.detail_metadata = QLabel("Transcript metadata will appear here.")
        self.detail_metadata.setObjectName("Muted")
        self.detail_metadata.setWordWrap(True)
        detail_layout.addWidget(self.detail_metadata)

        preview_heading = QLabel("Preview")
        preview_heading.setObjectName("HistoryPreviewHeading")
        detail_layout.addWidget(preview_heading)
        self.detail_preview = QLabel("Choose a transcript from the list to read its preview.")
        self.detail_preview.setObjectName("HistoryPreview")
        self.detail_preview.setWordWrap(True)
        self.detail_preview.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        detail_layout.addWidget(self.detail_preview, 1)

        actions = QVBoxLayout()
        actions.setSpacing(7)
        self.open_button = primary_button("Open transcript")
        self.open_button.clicked.connect(self.open_selected)
        self.rename_button = QPushButton("Rename")
        self.rename_button.clicked.connect(self.rename_selected)
        self.favorite_button = QPushButton("Pin / unpin")
        self.favorite_button.clicked.connect(self.toggle_favorite)
        self.duplicate_button = QPushButton("Duplicate")
        self.duplicate_button.clicked.connect(self.duplicate_selected)
        self.delete_button = QPushButton("Delete transcript")
        self.delete_button.setObjectName("Danger")
        self.delete_button.clicked.connect(self.delete_selected)
        actions.addWidget(self.open_button)
        actions.addWidget(self.rename_button)
        actions.addWidget(self.favorite_button)
        actions.addWidget(self.duplicate_button)
        actions.addWidget(self.delete_button)
        detail_layout.addLayout(actions)
        workspace.addWidget(detail_panel, 2)

        layout.addLayout(workspace, 1)
        self._update_action_state()
        self.refresh()

    def _selection_changed(self, *_args):
        self._update_action_state()
        self._show_selected_details()

    def _show_selected_details(self):
        transcript_id = self._selected_id()
        record = self._records_by_id.get(transcript_id or "")
        if not record:
            self.detail_status.setText("Nothing selected")
            self.detail_status.setProperty("state", "neutral")
            self.detail_title.setText("Select a transcript")
            self.detail_metadata.setText("Transcript metadata will appear here.")
            self.detail_preview.setText("Choose a transcript from the list to read its preview.")
            self.favorite_button.setText("Pin / unpin")
            return

        favorite = bool(record.get("favorite"))
        self.detail_status.setText("Pinned" if favorite else "Saved locally")
        self.detail_status.setProperty("state", "info" if favorite else "neutral")
        self.detail_status.style().unpolish(self.detail_status)
        self.detail_status.style().polish(self.detail_status)
        self.detail_title.setText(str(record.get("title") or "Untitled transcript"))
        updated = str(record.get("updated_at") or "Unknown").replace("T", " ")[:16]
        self.detail_metadata.setText(
            f"Updated {updated}\n"
            f"Engine: {record.get('engine') or 'Unknown'}  ·  "
            f"Language: {record.get('language') or 'Unknown'}"
        )
        self.detail_preview.setText(
            str(record.get("preview") or "").strip() or "No text preview is available."
        )
        self.favorite_button.setText("Unpin transcript" if favorite else "Pin transcript")

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
        self._records_by_id = {str(row["id"]): row for row in rows}
        for row in rows:
            title = str(row.get("title") or "Untitled transcript")
            updated = str(row.get("updated_at") or "Unknown").replace("T", " ")[:16]
            details = f"{updated}  ·  {row.get('engine') or 'Unknown engine'}  ·  {row.get('language') or 'Unknown language'}"
            item = QListWidgetItem(f"{'★  ' if row.get('favorite') else ''}{title}\n{details}")
            item.setData(Qt.ItemDataRole.UserRole, row["id"])
            item.setToolTip(str(row.get("preview") or title))
            self.items.addItem(item)

        has_rows = bool(rows)
        self.items.setVisible(has_rows)
        self.empty_state.setVisible(not has_rows)
        self.result_count.setText(f"{len(rows)} transcripts")
        if has_rows:
            self.items.setCurrentRow(0)
        else:
            self._show_selected_details()
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
