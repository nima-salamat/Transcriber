"""Home dashboard for starting work and returning to recent transcripts."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from transcriber.ui.widgets import Card, page_header, primary_button
from transcriber.ui.workers import FunctionWorker


class HomePage(QWidget):
    navigate = Signal(str)
    open_transcript = Signal(str)
    status_message = Signal(str)

    def __init__(self, history, model_manager, thread_pool, parent=None):
        super().__init__(parent)
        self.history = history
        self.model_manager = model_manager
        self.thread_pool = thread_pool
        self._generation = 0
        self._worker: FunctionWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 26)
        layout.setSpacing(19)
        layout.addWidget(
            page_header(
                "Your audio workspace",
                "A calm place to turn recordings into searchable, editable text.",
            )
        )

        hero = Card()
        hero.setObjectName("Card")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(25, 23, 25, 23)
        hero_layout.setSpacing(24)
        copy = QVBoxLayout()
        copy.setSpacing(7)
        eyebrow = QLabel("LOCAL-FIRST TRANSCRIPTION")
        eyebrow.setObjectName("Muted")
        eyebrow.setStyleSheet("font-size: 10px; font-weight: 750; letter-spacing: 1.2px;")
        title = QLabel("Make every recording useful.")
        title.setObjectName("SectionTitle")
        title.setStyleSheet("font-size: 24px; font-weight: 750;")
        description = QLabel(
            "Transcribe with an installed Faster-Whisper model, edit the result and create subtitles. "
            "Audio stays on this device unless you explicitly choose an online engine."
        )
        description.setWordWrap(True)
        description.setMaximumWidth(610)
        copy.addWidget(eyebrow)
        copy.addWidget(title)
        copy.addWidget(description)
        hero_layout.addLayout(copy, 1)

        actions = QVBoxLayout()
        actions.setSpacing(7)
        start = primary_button("＋  New transcription")
        start.setMinimumHeight(43)
        start.clicked.connect(lambda: self.navigate.emit("transcription"))
        record = QPushButton("●  Record audio")
        record.setObjectName("Subtle")
        record.clicked.connect(lambda: self.navigate.emit("recording"))
        actions.addWidget(start)
        actions.addWidget(record)
        hero_layout.addLayout(actions)
        layout.addWidget(hero)

        stats = QHBoxLayout()
        stats.setSpacing(12)
        self.transcript_count = QLabel("—")
        self.model_count = QLabel("—")
        stats.addWidget(self._stat_card("Saved transcripts", self.transcript_count), 1)
        stats.addWidget(self._stat_card("Installed local models", self.model_count), 1)
        stats.addStretch(2)
        layout.addLayout(stats)

        content = QHBoxLayout()
        content.setSpacing(16)

        recent_card = Card()
        recent_layout = QVBoxLayout(recent_card)
        recent_layout.setContentsMargins(16, 15, 16, 15)
        recent_layout.setSpacing(10)
        recent_header = QHBoxLayout()
        recent_title = QLabel("Recent work")
        recent_title.setObjectName("SectionTitle")
        recent_header.addWidget(recent_title)
        recent_header.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search transcripts…")
        self.search.setMaximumWidth(230)
        recent_header.addWidget(self.search)
        recent_layout.addLayout(recent_header)

        self.recent = QListWidget()
        self.recent.setObjectName("RecentList")
        self.recent.setSpacing(3)
        self.recent.setMinimumHeight(210)
        self.recent.itemDoubleClicked.connect(self._open_item)
        recent_layout.addWidget(self.recent, 1)

        self.empty_state = QLabel("No transcripts yet. Start with an audio file or a live recording.")
        self.empty_state.setObjectName("Muted")
        self.empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state.setWordWrap(True)
        self.empty_state.setMinimumHeight(110)
        recent_layout.addWidget(self.empty_state)
        content.addWidget(recent_card, 3)

        quick_card = Card()
        quick_layout = QVBoxLayout(quick_card)
        quick_layout.setContentsMargins(17, 16, 17, 16)
        quick_layout.setSpacing(9)
        quick_title = QLabel("Explore your workspace")
        quick_title.setObjectName("SectionTitle")
        quick_layout.addWidget(quick_title)
        quick_subtitle = QLabel("Jump straight to the tools you need.")
        quick_subtitle.setObjectName("Muted")
        quick_layout.addWidget(quick_subtitle)

        quick_actions = (
            ("Model library", "Manage and install offline speech models", "models"),
            ("Audio library", "Browse imported files and recordings", "audio"),
            ("Subtitle studio", "Create and validate subtitle files", "subtitles"),
            ("Transcript history", "Find and reopen previous work", "history"),
        )
        for title, description, page in quick_actions:
            button = QPushButton(f"{title}\n{description}")
            button.setObjectName("QuickAction")
            button.setMinimumHeight(57)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, target=page: self.navigate.emit(target))
            quick_layout.addWidget(button)
        quick_layout.addStretch(1)
        content.addWidget(quick_card, 2)
        layout.addLayout(content, 1)

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(220)
        self.search_timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda: self.search_timer.start())
        self.refresh()

    @staticmethod
    def _stat_card(title: str, value: QLabel) -> Card:
        card = Card()
        row = QVBoxLayout(card)
        row.setContentsMargins(18, 14, 18, 14)
        row.setSpacing(5)
        heading = QLabel(title)
        heading.setObjectName("Muted")
        value.setStyleSheet("font-size: 25px; font-weight: 750;")
        row.addWidget(heading)
        row.addWidget(value)
        return card

    def _open_item(self, item: QListWidgetItem):
        transcript_id = item.data(Qt.ItemDataRole.UserRole)
        if transcript_id:
            self.open_transcript.emit(transcript_id)

    def refresh(self, *_):
        self._generation += 1
        generation = self._generation
        query = self.search.text()
        worker = FunctionWorker(
            lambda _emit: (
                self.history.list(query, limit=50),
                self.history.count(),
                self.model_manager.registry.count_installed(),
            )
        )
        worker.signals.result.connect(lambda result, current=generation: self._apply_result(current, result))
        worker.signals.error.connect(lambda message: self.status_message.emit(f"Could not load home: {message}"))
        self._worker = worker
        self.thread_pool.start(worker)

    def _apply_result(self, generation: int, result):
        if generation != self._generation:
            return
        rows, transcript_count, model_count = result
        self.recent.clear()
        for row in rows:
            title = str(row.get("title") or "Untitled transcript")
            preview = str(row.get("preview") or "").strip()
            item = QListWidgetItem(f"{title}\n{preview}")
            item.setData(Qt.ItemDataRole.UserRole, row["id"])
            item.setToolTip(f"{title}\n\n{preview}")
            item.setSizeHint(QSize(0, 66))
            self.recent.addItem(item)
        has_rows = bool(rows)
        self.recent.setVisible(has_rows)
        self.empty_state.setVisible(not has_rows)
        self.transcript_count.setText(str(transcript_count))
        self.model_count.setText(str(model_count))
