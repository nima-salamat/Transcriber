"""Compact conversation header with provider and workspace context."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout


class ConversationHeader(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AssistantConversationHeader")
        self.setMinimumWidth(0)
        layout = QHBoxLayout(self)
        self._layout = layout
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)
        labels = QVBoxLayout()
        labels.setSpacing(2)
        self.title_label = QLabel("New chat")
        self.title_label.setObjectName("AssistantConversationTitle")
        self.title_label.setMinimumWidth(0)
        self.title_label.setWordWrap(True)
        self.title_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.subtitle_label = QLabel("OpenCode · workspace agent")
        self.subtitle_label.setObjectName("Muted")
        self.subtitle_label.setMinimumWidth(0)
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        labels.addWidget(self.title_label)
        labels.addWidget(self.subtitle_label)
        layout.addLayout(labels, 1)
        self.workspace_label = QLabel("")
        self.workspace_label.setObjectName("AssistantWorkspaceBadge")
        self.workspace_label.setMinimumWidth(0)
        self.workspace_label.setMaximumWidth(390)
        self.workspace_label.setWordWrap(True)
        self.workspace_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.workspace_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.workspace_label)

    def set_conversation(self, title: str, subtitle: str, workspace: str = ""):
        self.title_label.setText(str(title or "New chat"))
        self.subtitle_label.setText(str(subtitle or ""))
        self.workspace_label.setText(str(workspace or ""))
        self.workspace_label.setToolTip(str(workspace or ""))

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        narrow = event.size().width() < 580
        if narrow:
            self._layout.setContentsMargins(7, 6, 7, 6)
            self._layout.setSpacing(6)
            self.workspace_label.hide()
        else:
            self._layout.setContentsMargins(12, 8, 12, 8)
            self._layout.setSpacing(12)
            self.workspace_label.show()
