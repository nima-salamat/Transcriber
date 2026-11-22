"""Home dashboard for starting work and returning to recent transcripts."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from transcriber.ui.design.icon_registry import IconRegistry
from transcriber.ui.widgets import (
    Card,
    empty_state,
    metric_card,
    page_header,
    primary_button,
    section_header,
)
from transcriber.ui.workers import FunctionWorker



class HomePage(QWidget):
    navigate = Signal(str)
    open_transcript = Signal(str)
    status_message = Signal(str)

    def __init__(self, history, model_manager, thread_pool, parent=None, icons: IconRegistry | None = None):
        super().__init__(parent)
        self.icons = icons or IconRegistry()
        self.history = history
        self.model_manager = model_manager
        self.thread_pool = thread_pool
        self._generation = 0
        self._worker: FunctionWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(16)

        heading = QHBoxLayout()
        heading.setSpacing(10)
        heading.addWidget(page_header(
            "Workspace",
            "Start a new transcript, return to recent work or manage your local audio tools.",
        ), 1)
        start = primary_button("New transcription")
        start.setObjectName("HomePrimaryAction")
        start.setIcon(self.icons.icon("waveform", color="#ffffff", size=18))
        start.setIconSize(QSize(18, 18))
        start.setMinimumHeight(44)
        start.setMinimumWidth(158)
        start.setCursor(Qt.CursorShape.PointingHandCursor)
        start.setToolTip("Create a transcript from an audio or video file")
        start.setAccessibleName("New transcription")
        start.clicked.connect(lambda: self.navigate.emit("transcription"))
        record = QPushButton("Record audio")
        record.setObjectName("HomeSecondaryAction")
        record.setIcon(self.icons.icon("record", size=18))
        record.setIconSize(QSize(18, 18))
        record.setMinimumHeight(44)
        record.setMinimumWidth(142)
        record.setCursor(Qt.CursorShape.PointingHandCursor)
        record.setToolTip("Start a new microphone recording")
        record.setAccessibleName("Record audio")
        record.clicked.connect(lambda: self.navigate.emit("recording"))
        heading.addWidget(record, 0, Qt.AlignmentFlag.AlignTop)
        heading.addWidget(start, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(heading)

        metrics = QHBoxLayout()
        metrics.setSpacing(10)
        transcript_metric, self.transcript_count = metric_card("Saved transcripts")
        model_metric, self.model_count = metric_card("Installed local models")
        metrics.addWidget(transcript_metric, 1)
        metrics.addWidget(model_metric, 1)
        metrics.addStretch(2)
        layout.addLayout(metrics)

        workspace = QHBoxLayout()
        workspace.setSpacing(14)

        recent_panel = Card()
        recent_panel.setObjectName("WorkspacePanel")
        recent_layout = QVBoxLayout(recent_panel)
        recent_layout.setContentsMargins(16, 15, 16, 15)
        recent_layout.setSpacing(11)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search recent transcripts…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(280)
        recent_layout.addWidget(section_header(
            "Recent work",
            "Double-click a transcript to continue editing.",
            self.search,
        ))

        self.recent = QListWidget()
        self.recent.setObjectName("RecentList")
        self.recent.setSpacing(2)
        self.recent.setMinimumHeight(230)
        self.recent.itemDoubleClicked.connect(self._open_item)
        recent_layout.addWidget(self.recent, 1)

        self.empty_state = empty_state(
            "Your workspace is ready",
            "Import an audio or video file to create the first transcript. Saved work will appear here.",
            primary_button("Start a transcription"),
        )
        empty_action = self.empty_state.findChild(QPushButton)
        if empty_action is not None:
            empty_action.clicked.connect(lambda: self.navigate.emit("transcription"))
        recent_layout.addWidget(self.empty_state, 1)
        workspace.addWidget(recent_panel, 3)

        tools_panel = Card()
        tools_panel.setObjectName("WorkspacePanel")
        tools_layout = QVBoxLayout(tools_panel)
        tools_layout.setContentsMargins(15, 15, 15, 15)
        tools_layout.setSpacing(8)
        tools_layout.addWidget(section_header(
            "Tools",
            "Focused workspaces for each stage of your audio workflow.",
        ))

        tool_actions = (
            ("AI models", "Install or switch local speech models", "models"),
            ("Audio library", "Review saved recordings and imported audio", "audio"),
            ("Subtitle studio", "Adjust cue timing and export subtitles", "subtitles"),
            ("Transcript history", "Browse and organize previous transcripts", "history"),
            ("Audio cleanup", "Create a processed copy of an audio file", "cleanup"),
        )
        for title, detail, page in tool_actions:
            button = QPushButton(f"{title}    ›\n{detail}")
            button.setObjectName("WorkspaceShortcut")
            button.setMinimumHeight(54)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _checked=False, target=page: self.navigate.emit(target)
            )
            tools_layout.addWidget(button)
        tools_layout.addStretch(1)
        workspace.addWidget(tools_panel, 2)
        layout.addLayout(workspace, 1)

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(220)
        self.search_timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda: self.search_timer.start())
        self.refresh()

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
