"""Chat composer with provider/model selection and a docked send/stop row."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QSizePolicy, QVBoxLayout,
)


class PromptEditor(QPlainTextEdit):
    send_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AssistantPrompt")
        self.setPlaceholderText("Message your agent…")
        self.setMinimumHeight(58)
        self.setMaximumHeight(190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setTabChangesFocus(True)
        self.document().setMaximumBlockCount(80)
        self.textChanged.connect(self._fit_height)
        self._fit_height()

    def _fit_height(self):
        height = int(self.document().documentLayout().documentSize().height()) + 22
        self.setFixedHeight(max(58, min(190, height)))

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            modifiers = event.modifiers()
            if modifiers & Qt.KeyboardModifier.ControlModifier or not modifiers & Qt.KeyboardModifier.ShiftModifier:
                self.send_requested.emit()
                event.accept()
                return
        super().keyPressEvent(event)


class MessageComposer(QFrame):
    """Own the bottom dock: provider, model, prompt and generation controls."""
    send_requested = Signal()
    stop_requested = Signal()
    voice_requested = Signal()
    refresh_models_requested = Signal()

    def __init__(self, icons, parent=None, *, provider="opencode"):
        super().__init__(parent)
        self.icons = icons
        self._provider_ready = False
        self._busy = False
        self.setObjectName("AssistantComposer")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 10)
        layout.setSpacing(8)

        self.prompt = PromptEditor(self)
        self.prompt.send_requested.connect(self.send_requested.emit)
        self.prompt.textChanged.connect(self._sync_send_button)
        layout.addWidget(self.prompt)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.provider_combo = QComboBox(self)
        self.provider_combo.setObjectName("AssistantProviderSelect")
        self.provider_combo.addItem("OpenCode", "opencode")
        self.provider_combo.addItem("Ollama", "ollama")
        self.provider_combo.setCurrentIndex(max(0, self.provider_combo.findData(provider)))
        self.provider_combo.setMinimumWidth(116)
        self.provider_combo.setToolTip("Choose the provider for this conversation")
        controls.addWidget(self.provider_combo)

        self.model_combo = QComboBox(self)
        self.model_combo.setObjectName("AssistantModelSelect")
        self.model_combo.addItem("Loading available models…", "")
        self.model_combo.setMinimumWidth(220)
        self.model_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.model_combo.setToolTip("Choose a model supplied by the selected provider")
        controls.addWidget(self.model_combo, 1)

        self.refresh_models_button = QPushButton("Refresh", self)
        self.refresh_models_button.setObjectName("AssistantRefreshModels")
        self.refresh_models_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_models_button.setToolTip("Refresh the provider's available models")
        self.refresh_models_button.clicked.connect(self.refresh_models_requested.emit)
        controls.addWidget(self.refresh_models_button)

        self.voice_chat_button = QPushButton("Voice", self)
        self.voice_chat_button.setObjectName("AssistantVoiceButton")
        self.voice_chat_button.setIcon(icons.icon("mic", size=17))
        self.voice_chat_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.voice_chat_button.setAccessibleName("Start voice conversation")
        self.voice_chat_button.setToolTip("Start or stop local voice conversation")
        self.voice_chat_button.clicked.connect(self.voice_requested.emit)
        controls.addWidget(self.voice_chat_button)

        self.agent_mode_check = QCheckBox("Agent mode", self)
        self.agent_mode_check.setObjectName("AssistantAgentMode")
        self.agent_mode_check.setChecked(True)
        self.agent_mode_check.setEnabled(False)
        self.agent_mode_check.setToolTip(
            "Allow permitted Agent tools. Sensitive actions still require approval."
        )
        controls.addWidget(self.agent_mode_check)

        self.stop_button = QPushButton("Stop", self)
        self.stop_button.setObjectName("AssistantStopButton")
        self.stop_button.setIcon(icons.icon("stop", color="#ffffff", size=15))
        self.stop_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_button.setToolTip("Stop the current model response")
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self.stop_button.setEnabled(False)
        self.stop_button.hide()
        controls.addWidget(self.stop_button)

        self.send_button = QPushButton("Send", self)
        self.send_button.setObjectName("AssistantSendButton")
        self.send_button.setIcon(icons.icon("send", color="#ffffff", size=18))
        self.send_button.setMinimumWidth(92)
        self.send_button.setMinimumHeight(38)
        self.send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_button.setToolTip("Send message · Enter")
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self.send_requested.emit)
        controls.addWidget(self.send_button)
        layout.addLayout(controls)

        self.voice_live_status = QLabel("Voice off", self)
        self.voice_live_status.setObjectName("AssistantVoiceStatus")
        self.voice_live_status.setWordWrap(True)
        self.voice_live_status.setAccessibleName("Voice chat status")
        self.voice_live_status.hide()
        layout.addWidget(self.voice_live_status)

        self.status_label = QLabel("Connecting to the selected AI provider…", self)
        self.status_label.setObjectName("AssistantComposerStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status_label)

    def set_status(self, text: str, *, error: bool = False):
        self.status_label.setText(str(text or ""))
        self.status_label.setProperty("state", "error" if error else "normal")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _sync_send_button(self):
        self.send_button.setEnabled(
            self._provider_ready and not self._busy and bool(self.prompt.toPlainText().strip())
        )

    def set_provider_ready(self, ready: bool):
        self._provider_ready = bool(ready)
        self._sync_send_button()

    def set_busy(self, busy: bool, *, stoppable: bool = True):
        self._busy = bool(busy)
        show_stop = self._busy and bool(stoppable)
        self.stop_button.setEnabled(show_stop)
        self.stop_button.setVisible(show_stop)
        self.refresh_models_button.setEnabled(not self._busy)
        self.provider_combo.setEnabled(not self._busy)
        self.model_combo.setEnabled(not self._busy and self.model_combo.count() > 1)
        self._sync_send_button()
