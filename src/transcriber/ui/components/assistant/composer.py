"""Adaptive message composer with explicit keyboard and action semantics."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSizePolicy, QVBoxLayout


class PromptEditor(QPlainTextEdit):
    send_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AssistantPrompt")
        self.setPlaceholderText("Message your agent…")
        self.setMinimumHeight(48)
        self.setMaximumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setTabChangesFocus(True)
        self.document().setMaximumBlockCount(80)
        self.textChanged.connect(self._fit_height)
        self._fit_height()

    def _fit_height(self):
        height = int(self.document().documentLayout().documentSize().height()) + 18
        self.setFixedHeight(max(48, min(180, height)))

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            modifiers = event.modifiers()
            if modifiers & Qt.KeyboardModifier.ControlModifier or not modifiers & Qt.KeyboardModifier.ShiftModifier:
                self.send_requested.emit()
                event.accept()
                return
        super().keyPressEvent(event)


class MessageComposer(QFrame):
    """Visual composer; provider and voice lifecycles remain panel responsibilities."""
    send_requested = Signal()
    stop_requested = Signal()
    voice_requested = Signal()

    def __init__(self, icons, parent=None):
        super().__init__(parent)
        self.icons = icons
        self._provider_ready = False
        self._busy = False
        self.setObjectName("AssistantComposer")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)
        self.prompt = PromptEditor(self)
        self.prompt.send_requested.connect(self.send_requested.emit)
        self.prompt.textChanged.connect(self._sync_send_button)
        layout.addWidget(self.prompt)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.voice_chat_button = QPushButton("Start voice")
        self.voice_chat_button.setObjectName("AssistantVoiceButton")
        self.voice_chat_button.setIcon(icons.icon("mic", size=17))
        self.voice_chat_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.voice_chat_button.setAccessibleName("Start voice conversation")
        self.voice_chat_button.setToolTip("Start or stop local voice conversation. Microphone activation is explicit.")
        self.voice_chat_button.clicked.connect(self.voice_requested.emit)
        actions.addWidget(self.voice_chat_button)

        self.voice_live_status = QLabel("Voice off")
        self.voice_live_status.setObjectName("AssistantVoiceStatus")
        self.voice_live_status.setWordWrap(True)
        self.voice_live_status.setAccessibleName("Voice chat status")
        actions.addWidget(self.voice_live_status, 1)

        self.agent_mode_check = QCheckBox("Agent mode")
        self.agent_mode_check.setObjectName("AssistantAgentMode")
        self.agent_mode_check.setChecked(True)
        self.agent_mode_check.setEnabled(False)
        self.agent_mode_check.setToolTip("Allow currently permitted Agent tools. Sensitive actions still require approval.")
        actions.addWidget(self.agent_mode_check)

        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("Subtle")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        actions.addWidget(self.stop_button)

        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("AssistantSendButton")
        self.send_button.setIcon(icons.icon("send", color="#ffffff", size=18))
        self.send_button.setMinimumWidth(86)
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self.send_requested.emit)
        actions.addWidget(self.send_button)
        layout.addLayout(actions)

    def _sync_send_button(self):
        self.send_button.setEnabled(self._provider_ready and not self._busy and bool(self.prompt.toPlainText().strip()))

    def set_provider_ready(self, ready: bool):
        self._provider_ready = bool(ready)
        self._sync_send_button()

    def set_busy(self, busy: bool):
        self._busy = bool(busy)
        self.stop_button.setEnabled(self._busy)
        self._sync_send_button()
