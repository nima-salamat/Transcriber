"""Incremental conversation renderer with scroll anchoring and safe Markdown."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .message_widget import MessageWidget


class ConversationView(QFrame):
    """Incremental message cards; follow tokens only while the reader is at the bottom."""
    prompt_requested = Signal(str)

    def __init__(self, quick_prompts=None, icons=None, parent=None):
        super().__init__(parent)
        self.setObjectName("AssistantConversationView")
        self.icons = icons
        self._widgets: list[MessageWidget] = []
        self._signatures: list[tuple[str, str]] = []
        self._messages: list[dict] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setObjectName("AssistantConversationScroll")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.content = QWidget()
        self.content.setObjectName("AssistantConversationContent")
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
        empty_layout.addWidget(title)
        description = QLabel(
            "Ask questions, work with audio, review transcripts, research the web, "
            "or automate your desktop with permission-aware tools."
        )
        description.setObjectName("AssistantEmptyDescription")
        description.setWordWrap(True)
        description.setMaximumWidth(620)
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(description)
        prompt_grid = QVBoxLayout()
        prompt_grid.setSpacing(7)
        suggestions = list((quick_prompts or {}).items())
        for index in range(0, len(suggestions), 2):
            row = QHBoxLayout()
            row.setSpacing(8)
            for label, prompt in suggestions[index:index + 2]:
                button = QPushButton(label)
                button.setObjectName("AssistantPromptSuggestion")
                button.setMinimumHeight(42)
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.clicked.connect(lambda _checked=False, value=prompt: self.prompt_requested.emit(value))
                row.addWidget(button)
            while row.count() < 2:
                row.addStretch(1)
            prompt_grid.addLayout(row)
        empty_layout.addLayout(prompt_grid)
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

    def set_messages(self, messages: list[dict]):
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
        if was_near_bottom:
            self.jump_button.hide()
            self.scroll_to_latest()
        elif incoming:
            self.jump_button.show()

    def _append_widget(self, role: str, text: str):
        widget = MessageWidget(role, text, self.icons, self.content)
        alignment = Qt.AlignmentFlag.AlignRight if role == "user" else Qt.AlignmentFlag.AlignLeft
        self.content_layout.insertWidget(max(0, self.content_layout.count() - 1), widget, 0, alignment)
        self._widgets.append(widget)

    def _clear_message_widgets(self):
        for widget in self._widgets:
            widget.setParent(None)
            widget.deleteLater()

    def scroll_to_latest(self):
        QTimer.singleShot(0, self._scroll_to_latest_now)

    def _scroll_to_latest_now(self):
        bar = self.scroll_area.verticalScrollBar()
        bar.setValue(bar.maximum())
        self.jump_button.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._is_near_bottom():
            self.scroll_to_latest()
