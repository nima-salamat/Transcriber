"""Role-aware message cards with reliable clipboard actions."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QClipboard, QGuiApplication
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout

from .message_renderer import SafeMarkdownBrowser


class MessageWidget(QFrame):
    def __init__(self, role: str, text: str, icons=None, parent=None):
        super().__init__(parent)
        self.role = str(role or "assistant")
        self.icons = icons
        self.setObjectName(f"AssistantMessage_{self.role}")
        self.setMinimumWidth(0)
        self.setMaximumWidth(960)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.setProperty("role", self.role)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(11, 9, 11, 10)
        layout.setSpacing(5)

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
        self.copy_button.setAccessibleName("Copy message")
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button.clicked.connect(self._copy_message)
        header.addWidget(self.copy_button)
        layout.addLayout(header)

        self.body = SafeMarkdownBrowser(self)
        self.body.setObjectName("AssistantMessageBody")
        self.body.setMinimumWidth(0)
        self.body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.body)

        self._text = ""
        self._copy_feedback_timer = QTimer(self)
        self._copy_feedback_timer.setSingleShot(True)
        self._copy_feedback_timer.setInterval(1600)
        self._copy_feedback_timer.timeout.connect(self._restore_copy_button)
        self.update_text(text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "body"):
            self.body.refresh_document_size()

    def update_text(self, text: str):
        self._text = str(text or "")
        self.body.set_markdown(self._text)
        self.copy_button.setVisible(bool(self._text))
        if not self._text:
            self._restore_copy_button()

    def _copy_message(self, *_args):
        """Copy the rendered message text, not Markdown markup, to the system clipboard."""
        text = self.body.toPlainText()
        if not text.strip():
            text = self._text
        if not text:
            return

        try:
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(text, QClipboard.Mode.Clipboard)
        except RuntimeError:
            self.copy_button.setText("Copy failed")
            self.copy_button.setToolTip("Could not access the system clipboard")
            self._copy_feedback_timer.start()
            return

        self.copy_button.setText("Copied")
        self.copy_button.setProperty("copied", True)
        self.copy_button.setToolTip("Message copied to clipboard")
        self.copy_button.style().unpolish(self.copy_button)
        self.copy_button.style().polish(self.copy_button)
        self._copy_feedback_timer.start()

    def _restore_copy_button(self):
        self._copy_feedback_timer.stop()
        self.copy_button.setText("Copy")
        self.copy_button.setProperty("copied", False)
        self.copy_button.setToolTip("Copy this message")
        self.copy_button.style().unpolish(self.copy_button)
        self.copy_button.style().polish(self.copy_button)
