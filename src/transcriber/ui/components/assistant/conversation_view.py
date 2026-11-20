"""Incremental conversation renderer with scroll anchoring and safe Markdown."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget, QSizePolicy

from .message_widget import MessageWidget


class ConversationView(QFrame):
    """Incremental message cards; follow tokens only while the reader is at the bottom."""
    def __init__(self, icons=None, parent=None):
        super().__init__(parent)
        self.setObjectName("AssistantConversationView")
        self.icons = icons
        self._widgets: list[MessageWidget] = []
        self._rows: list[QWidget] = []
        self._signatures: list[tuple[str, str]] = []
        self._messages: list[dict] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setObjectName("AssistantConversationScroll")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setMinimumWidth(0)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.content = QWidget()
        self.content.setObjectName("AssistantConversationContent")
        self.content.setMinimumWidth(0)
        self.content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(18, 22, 18, 26)
        self.content_layout.setSpacing(13)
        self.empty_state = QFrame()
        self.empty_state.setObjectName("AssistantEmptyState")
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setContentsMargins(18, 34, 18, 34)
        empty_layout.setSpacing(12)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("How can I help you today?")
        title.setObjectName("AssistantEmptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        title.setMinimumWidth(0)
        empty_layout.addWidget(title)
        self._empty_title = title
        self._empty_layout = empty_layout
        description = QLabel(
            "Ask questions, work with audio, review transcripts, research the web, "
            "or automate your desktop with permission-aware tools."
        )
        description.setObjectName("AssistantEmptyDescription")
        description.setWordWrap(True)
        description.setMinimumWidth(0)
        description.setMaximumWidth(620)
        description.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(description)
        self.content_layout.addWidget(self.empty_state)
        self.content_layout.addStretch(1)
        self.scroll_area.setWidget(self.content)
        outer.addWidget(self.scroll_area, 1)
        self.jump_button = QPushButton("↓  Jump to latest")
        self.jump_button.setObjectName("AssistantJumpLatest")
        self.jump_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.jump_button.clicked.connect(self.scroll_to_latest)
        self.jump_button.hide()
        outer.addWidget(self.jump_button, 0, Qt.AlignmentFlag.AlignHCenter)

    def toPlainText(self) -> str:
        return "\n\n".join(str(item.get("text") or "") for item in self._messages)

    def _is_near_bottom(self) -> bool:
        bar = self.scroll_area.verticalScrollBar()
        return bar.maximum() - bar.value() <= 72

    def set_messages(self, messages: list[dict], *, force_scroll_to_bottom: bool = False):
        values = list(messages or [])[-400:]
        incoming = [
            (str(item.get("role") or "assistant"), str(item.get("text") or ""))
            for item in values
        ]
        was_near_bottom = self._is_near_bottom()
        old_count = len(self._signatures)
        stable_count = max(0, old_count - 1)
        stable_prefix_matches = (
            len(incoming) >= old_count
            and incoming[:stable_count] == self._signatures[:stable_count]
        )
        if not stable_prefix_matches:
            self._clear_message_widgets()
            self._widgets = []
            self._signatures = []
            for role, text in incoming:
                self._append_widget(role, text)
            self._signatures = incoming[:]
        else:
            # The last item is the only existing item allowed to change: providers
            # stream into it. Update its widget instead of rebuilding the history.
            if old_count and incoming[old_count - 1] != self._signatures[-1]:
                role, text = incoming[old_count - 1]
                if self._widgets[old_count - 1].role == role:
                    self._widgets[old_count - 1].update_text(text)
                    self._signatures[-1] = (role, text)
                else:
                    self._clear_message_widgets()
                    self._widgets = []
                    self._signatures = []
                    for item_role, item_text in incoming:
                        self._append_widget(item_role, item_text)
                    self._signatures = incoming[:]
                    old_count = len(incoming)
            if self._signatures and len(incoming) > len(self._signatures):
                for role, text in incoming[len(self._signatures):]:
                    self._append_widget(role, text)
                    self._signatures.append((role, text))
            elif not self._signatures and incoming:
                for role, text in incoming:
                    self._append_widget(role, text)
                    self._signatures.append((role, text))
        self._messages = [dict(item) for item in values]
        self.empty_state.setVisible(not bool(incoming))
        if force_scroll_to_bottom:
            self.jump_button.hide()
            self.scroll_to_latest()
        elif was_near_bottom:
            self.jump_button.hide()
            self.scroll_to_latest()
        elif incoming:
            self.jump_button.show()

    def _append_widget(self, role: str, text: str):
        # Each message gets a full-width row. The card is aligned within that row,
        # but always receives a bounded width so its markdown can wrap on narrow screens.
        row = QWidget(self.content)
        row.setObjectName("AssistantMessageRow")
        row.setMinimumWidth(0)
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)

        widget = MessageWidget(role, text, self.icons, row)
        widget.setMinimumWidth(0)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        if role == "user":
            row_layout.addStretch(1)
            row_layout.addWidget(widget, 0)
        else:
            row_layout.addWidget(widget, 0)
            row_layout.addStretch(1)

        self.content_layout.insertWidget(max(0, self.content_layout.count() - 1), row)
        self._widgets.append(widget)
        self._rows.append(row)

    def _clear_message_widgets(self):
        for row in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

    def scroll_to_latest(self):
        QTimer.singleShot(0, self._scroll_to_latest_now)

    def _scroll_to_latest_now(self):
        bar = self.scroll_area.verticalScrollBar()
        bar.setValue(bar.maximum())
        self.jump_button.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        narrow = event.size().width() < 560
        if narrow:
            self.content_layout.setContentsMargins(8, 12, 8, 16)
            self._empty_layout.setContentsMargins(8, 18, 8, 18)
            self._empty_layout.setSpacing(9)
            self.prompt_grid.setHorizontalSpacing(7)
            self.prompt_grid.setVerticalSpacing(8)
        else:
            self.content_layout.setContentsMargins(18, 22, 18, 26)
            self._empty_layout.setContentsMargins(18, 34, 18, 34)
            self._empty_layout.setSpacing(12)
        for widget in self._widgets:
            widget.body.refresh_document_size()
        if self._is_near_bottom():
            self.scroll_to_latest()
