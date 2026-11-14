"""Home dashboard with recent transcript access."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
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
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(20)
        layout.addWidget(page_header("Good to hear from you", "Your local transcription workspace."))

        hero = Card()
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(24, 22, 24, 22)
        copy = QVBoxLayout()
        eyebrow = QLabel("LOCAL-FIRST SPEECH RECOGNITION")
        eyebrow.setObjectName("Muted")
        title = QLabel("Turn audio into useful text.")
        title.setStyleSheet("font-size: 22px; font-weight: 650;")
        description = QLabel(
            "Transcribe files on this device with Faster-Whisper. Your audio stays local "
            "unless you explicitly enable a cloud engine."
        )
        description.setWordWrap(True)
        description.setMaximumWidth(560)
        copy.addWidget(eyebrow)
        copy.addWidget(title)
        copy.addWidget(description)
        hero_layout.addLayout(copy, 1)
        action = primary_button("＋  New transcription")
        action.clicked.connect(lambda: self.navigate.emit("transcription"))
        action.setMinimumHeight(44)
        hero_layout.addWidget(action)
        layout.addWidget(hero)

        stats = QHBoxLayout()
        self.transcript_count = QLabel("—")
        self.model_count = QLabel("—")
        stats.addWidget(self._stat_card("Saved transcripts", self.transcript_count))
        stats.addWidget(self._stat_card("Installed models", self.model_count))
        stats.addStretch(1)
        layout.addLayout(stats)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search recent transcripts…")
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(220)
        self.search_timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda: self.search_timer.start())
        layout.addWidget(self.search)
        self.recent = QListWidget()
        self.recent.itemDoubleClicked.connect(self._open_item)
        layout.addWidget(self.recent, 1)
        self.refresh()

    @staticmethod
    def _stat_card(title: str, value: QLabel) -> Card:
        card = Card()
        row = QVBoxLayout(card)
        row.setContentsMargins(18, 13, 18, 13)
        heading = QLabel(title)
        heading.setObjectName("Muted")
        value.setStyleSheet("font-size: 25px; font-weight: 650;")
        row.addWidget(heading)
        row.addWidget(value)
        return card

    def _open_item(self, item: QListWidgetItem):
        transcript_id = item.data(256)
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
            item = QListWidgetItem(f"{row['title']}\n{row['preview']}")
            item.setData(256, row["id"])
            self.recent.addItem(item)
        self.transcript_count.setText(str(transcript_count))
        self.model_count.setText(str(model_count))
