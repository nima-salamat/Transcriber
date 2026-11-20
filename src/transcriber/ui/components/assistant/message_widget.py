"""Role-aware message cards with copy actions."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout

from .message_renderer import SafeMarkdownBrowser


class MessageWidget(QFrame):
    def __init__(self, role: str, text: str, icons=None, parent=None):
        super().__init__(parent)
        self.role = str(role or "assistant")
        self.icons = icons
        self.setObjectName(f"AssistantMessage_{self.role}")
        self.setMaximumWidth(960)
        self.setProperty("role", self.role)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(4)
        header = QHBoxLayout()
        self.role_label = QLabel({
            "user": "You", "assistant": "Transcriber", "tool": "Action",
            "error": "Error", "system": "Update",
        }.get(self.role, "Transcriber"))
        self.role_label.setObjectName("AssistantMessageRole")
        header.addWidget(self.role_label)
        header.addStretch(1)
        self.copy_button = QToolButton()
        self.copy_button.setObjectName("AssistantMessageAction")
        self.copy_button.setText("Copy")
        self.copy_button.setToolTip("Copy this message")
        self.copy_button.clicked.connect(self._copy_message)
        header.addWidget(self.copy_button)
        layout.addLayout(header)
        self.body = SafeMarkdownBrowser(self)
        self.body.setObjectName("AssistantMessageBody")
        layout.addWidget(self.body)
        self.update_text(text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "body"):
            self.body.refresh_document_size()

    def update_text(self, text: str):
        self._text = str(text or "")
        self.body.set_markdown(self._text)
        self.copy_button.setVisible(bool(self._text))

    def _copy_message(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._text)


