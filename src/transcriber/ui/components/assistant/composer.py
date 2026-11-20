"""Compact chat composer with a model picker and ChatGPT-style input row."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QMenu, QPlainTextEdit, QProgressBar,
    QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidgetAction,
)


class PromptEditor(QPlainTextEdit):
    send_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AssistantPrompt")
        self.setPlaceholderText("Message your agent…")
        self.setMinimumHeight(44)
        self.setMaximumHeight(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setTabChangesFocus(True)
        self.document().setMaximumBlockCount(80)
        self.textChanged.connect(self._fit_height)
        self._fit_height()

    def _fit_height(self):
        height = int(self.document().documentLayout().documentSize().height()) + 20
        self.setFixedHeight(max(44, min(160, height)))

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            modifiers = event.modifiers()
            if (
                modifiers & Qt.KeyboardModifier.ControlModifier
                or not modifiers & Qt.KeyboardModifier.ShiftModifier
            ):
                self.send_requested.emit()
                event.accept()
                return
        super().keyPressEvent(event)


class ModelPicker(QFrame):
    """Left-side model menu with provider selection, connect/disconnect and status."""

    connect_requested = Signal()
    disconnect_requested = Signal()

    def __init__(self, icons, parent=None, *, provider="opencode"):
        super().__init__(parent)
        self.icons = icons
        self._provider = str(provider or "opencode")
        self._active_model = ""
        self._connected = False
        self._connecting = False
        self._busy = False
        self.setObjectName("AssistantModelPicker")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)

        self.button = QToolButton(self)
        self.button.setObjectName("AssistantModelPickerButton")
        self.button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.button.setIcon(icons.icon("models", size=17))
        self.button.setText("Choose model")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.button.setToolTip("Choose the AI provider and model, then connect")
        self.button.setMinimumHeight(42)
        self.button.setMinimumWidth(150)
        self.button.setMaximumWidth(230)
        layout.addWidget(self.button)

        self.spinner = QProgressBar(self)
        self.spinner.setObjectName("AssistantConnectionSpinner")
        self.spinner.setRange(0, 0)
        self.spinner.setTextVisible(False)
        self.spinner.setFixedSize(16, 16)
        self.spinner.hide()
        layout.addWidget(self.spinner)

        self.status_label = QLabel("Disconnected", self)
        self.status_label.setObjectName("AssistantModelConnectionStatus")
        self.status_label.setProperty("state", "disconnected")
        self.status_label.setMinimumWidth(78)
        layout.addWidget(self.status_label)

        self.menu = QMenu(self.button)
        self.menu.setObjectName("AssistantModelPickerMenu")
        popup = QFrame()
        popup.setObjectName("AssistantModelPickerPopup")
        popup.setMinimumWidth(370)
        popup_layout = QVBoxLayout(popup)
        popup_layout.setContentsMargins(14, 13, 14, 13)
        popup_layout.setSpacing(9)

        provider_label = QLabel("PROVIDER")
        provider_label.setObjectName("AssistantModelPickerCaption")
        popup_layout.addWidget(provider_label)
        self.provider_combo = QComboBox(popup)
        self.provider_combo.setObjectName("AssistantProviderSelect")
        self.provider_combo.addItem("OpenCode", "opencode")
        self.provider_combo.addItem("Ollama", "ollama")
        self.provider_combo.setCurrentIndex(max(0, self.provider_combo.findData(self._provider)))
        popup_layout.addWidget(self.provider_combo)

        model_label = QLabel("MODEL")
        model_label.setObjectName("AssistantModelPickerCaption")
        popup_layout.addWidget(model_label)
        self.model_combo = QComboBox(popup)
        self.model_combo.setObjectName("AssistantModelSelect")
        self.model_combo.addItem("Loading available models…", "")
        self.model_combo.setMinimumHeight(38)
        model_row = QHBoxLayout()
        model_row.setSpacing(8)
        model_row.addWidget(self.model_combo, 1)

        self.connect_button = QPushButton("Connect", popup)
        self.connect_button.setObjectName("AssistantModelConnectButton")
        self.connect_button.setMinimumHeight(38)
        self.connect_button.setMinimumWidth(92)
        self.connect_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.connect_button.clicked.connect(self.connect_requested.emit)
        model_row.addWidget(self.connect_button)

        self.disconnect_button = QPushButton("Disconnect", popup)
        self.disconnect_button.setObjectName("Subtle")
        self.disconnect_button.setMinimumHeight(38)
        self.disconnect_button.clicked.connect(self.disconnect_requested.emit)
        self.disconnect_button.hide()
        model_row.addWidget(self.disconnect_button)
        popup_layout.addLayout(model_row)

        self.menu_status = QLabel("Choose a model to connect.", popup)
        self.menu_status.setObjectName("AssistantModelPickerMenuStatus")
        self.menu_status.setWordWrap(True)
        popup_layout.addWidget(self.menu_status)

        menu_action = QWidgetAction(self.menu)
        menu_action.setDefaultWidget(popup)
        self.menu.addAction(menu_action)
        self.button.setMenu(self.menu)

        self.provider_combo.currentIndexChanged.connect(self._sync_button_text)
        self.model_combo.currentIndexChanged.connect(self._sync_button_text)
        self._sync_button_text()

    def _sync_button_text(self, *_args):
        provider = str(self.provider_combo.currentData() or self._provider)
        self._provider = provider
        model = str(self.model_combo.currentText() or "").strip()
        if not model or self.model_combo.currentData() in (None, ""):
            model = "Choose model"
        prefix = "Ollama" if provider == "ollama" else "OpenCode"
        self.button.setText(model if model != "Choose model" else f"{prefix} · Choose model")
        self.button.setToolTip(f"{prefix} · {model}. Open to change the model or connect.")

    def set_connection_state(
        self,
        *,
        connected: bool,
        active_model: str = "",
        connecting: bool = False,
        error: str = "",
        provider: str | None = None,
    ):
        self._connected = bool(connected)
        self._connecting = bool(connecting)
        if provider:
            self._provider = str(provider)
        self._active_model = str(active_model or "")
        selected = str(self.model_combo.currentData() or "")
        if self._provider == "ollama":
            matches_active = (
                self._connected and bool(selected) and selected == self._active_model
            )
        else:
            matches_active = self._connected and (
                (not selected and not self._active_model)
                or (bool(selected) and selected == self._active_model)
            )

        if connecting:
            text, state = "Connecting…", "connecting"
            menu_text = "Connecting to the selected model…"
        elif error:
            text, state = "Connection failed", "error"
            menu_text = str(error)
        elif matches_active:
            text, state = "Connected", "connected"
            menu_text = (
                f"Connected · {self._active_model}"
                if self._active_model else "Connected to the provider's default model."
            )
        elif connected:
            text, state = "Other model active", "disconnected"
            menu_text = (
                f"Provider is connected to {self._active_model}. "
                "Press Connect to switch to the selected model."
            )
        else:
            text, state = "Disconnected", "disconnected"
            menu_text = "Disconnected · Choose a model and press Connect."

        self.status_label.setText(text)
        self.status_label.setProperty("state", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.menu_status.setText(menu_text)
        self.spinner.setVisible(bool(connecting))
        self.connect_button.setEnabled(
            not self._busy
            and not connecting
            and not matches_active
            and (bool(selected) or self._provider == "opencode")
        )
        self.disconnect_button.setVisible(bool(connected))
        self.disconnect_button.setEnabled(bool(connected) and not connecting and not self._busy)
        self._sync_button_text()

    def set_busy(self, busy: bool):
        self._busy = bool(busy)
        self.provider_combo.setEnabled(not self._busy)
        self.model_combo.setEnabled(not self._busy and self.model_combo.count() > 1)
        if self._busy:
            self.connect_button.setEnabled(False)
            self.disconnect_button.setEnabled(False)


class MessageComposer(QFrame):
    """One-row input dock: model at left, prompt in the middle, voice/send at right."""

    send_requested = Signal()
    stop_requested = Signal()
    voice_requested = Signal()
    connect_requested = Signal()
    disconnect_requested = Signal()

    def __init__(self, icons, parent=None, *, provider="opencode"):
        super().__init__(parent)
        self.icons = icons
        self._provider_ready = False
        self._busy = False
        self._stoppable = False
        self.setObjectName("AssistantComposer")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 9, 12, 9)
        root.setSpacing(5)
        row = QHBoxLayout()
        row.setSpacing(10)

        self.model_picker = ModelPicker(icons, self, provider=provider)
        self.model_picker.connect_requested.connect(self.connect_requested.emit)
        self.model_picker.disconnect_requested.connect(self.disconnect_requested.emit)
        self.provider_combo = self.model_picker.provider_combo
        self.model_combo = self.model_picker.model_combo
        row.addWidget(self.model_picker, 0)

        self.prompt = PromptEditor(self)
        self.prompt.send_requested.connect(self._on_primary_action)
        self.prompt.textChanged.connect(self._sync_send_button)
        row.addWidget(self.prompt, 1)

        self.voice_chat_button = QPushButton("Start voice", self)
        self.voice_chat_button.setObjectName("AssistantVoiceButton")
        self.voice_chat_button.setIcon(icons.icon("mic", size=17))
        self.voice_chat_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.voice_chat_button.setAccessibleName("Start voice conversation")
        self.voice_chat_button.setToolTip("Start or stop local voice conversation")
        self.voice_chat_button.setMinimumHeight(42)
        self.voice_chat_button.clicked.connect(self.voice_requested.emit)
        row.addWidget(self.voice_chat_button, 0)

        self.send_button = QPushButton(self)
        self.send_button.setObjectName("AssistantSendButton")
        self.send_button.setIcon(icons.icon("send", color="#ffffff", size=18))
        self.send_button.setFixedSize(42, 42)
        self.send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_button.setToolTip("Send message · Enter")
        self.send_button.setAccessibleName("Send message")
        self.send_button.clicked.connect(self._on_primary_action)
        self.send_button.setEnabled(False)
        row.addWidget(self.send_button, 0)
        self.stop_button = self.send_button

        root.addLayout(row)

        self.voice_live_status = QLabel("Voice off", self)
        self.voice_live_status.setObjectName("AssistantVoiceStatus")
        self.voice_live_status.setWordWrap(True)
        self.voice_live_status.setAccessibleName("Voice chat status")
        self.voice_live_status.hide()
        root.addWidget(self.voice_live_status)

        self.status_label = QLabel("Disconnected", self)
        self.status_label.setObjectName("AssistantComposerStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status_label.hide()
        root.addWidget(self.status_label)

    def _on_primary_action(self):
        if self._busy:
            if self._stoppable:
                self.stop_requested.emit()
            return
        if self._provider_ready and self.prompt.toPlainText().strip():
            self.send_requested.emit()

    def set_status(self, text: str, *, error: bool = False):
        self.status_label.setText(str(text or ""))
        self.status_label.setProperty("state", "error" if error else "normal")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.status_label.setVisible(bool(text))

    def set_connection_state(self, **kwargs):
        self.model_picker.set_connection_state(**kwargs)

    def set_busy(self, busy: bool, *, stoppable: bool = True):
        self._busy = bool(busy)
        self._stoppable = self._busy and bool(stoppable)
        self.model_picker.set_busy(self._busy)
        self.voice_chat_button.setEnabled(not self._busy)
        if self._stoppable:
            self.send_button.setIcon(self.icons.icon("stop", color="#ffffff", size=16))
            self.send_button.setToolTip("Stop the current response")
            self.send_button.setAccessibleName("Stop response")
            self.send_button.setEnabled(True)
        else:
            self.send_button.setIcon(self.icons.icon("send", color="#ffffff", size=18))
            self.send_button.setToolTip("Send message · Enter")
            self.send_button.setAccessibleName("Send message")
            self._sync_send_button()

    def _sync_send_button(self):
        self.send_button.setEnabled(
            not self._busy
            and self._provider_ready
            and bool(self.prompt.toPlainText().strip())
        )

    def set_provider_ready(self, ready: bool):
        self._provider_ready = bool(ready)
        self._sync_send_button()
