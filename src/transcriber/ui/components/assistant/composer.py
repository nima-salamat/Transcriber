"""Responsive chat composer with a reliable model popup and compact toolbar."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics, QKeyEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
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
    """Provider/model selector with a real popup (not an interactive QMenu action)."""

    connect_requested = Signal()
    disconnect_requested = Signal()
    retry_requested = Signal()

    def __init__(self, icons, parent=None, *, provider="opencode"):
        super().__init__(parent)
        self.icons = icons
        self._provider = str(provider or "opencode")
        self._active_model = ""
        self._connected = False
        self._connecting = False
        self._busy = False
        self._spinner_frames = ("◴", "◷", "◶", "◵")
        self._spinner_index = 0
        self.setObjectName("AssistantModelPicker")
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)

        self.button = QToolButton(self)
        self.button.setObjectName("AssistantModelPickerButton")
        self.button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.button.setIcon(icons.icon("chevron_up", size=14))
        self.button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.button.setText("OpenCode")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setToolTip("Choose the AI provider and model, then connect")
        self.button.setMinimumHeight(42)
        self.button.setMinimumWidth(128)
        self.button.setMaximumWidth(230)
        self.button.clicked.connect(self._toggle_popup)
        layout.addWidget(self.button)

        self.retry_button = QToolButton(self)
        self.retry_button.setObjectName("AssistantRetryConnection")
        self.retry_button.setText("↻")
        self.retry_button.setToolTip("Retry connection")
        self.retry_button.setAccessibleName("Retry provider connection")
        self.retry_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.retry_button.setFixedSize(34, 34)
        self.retry_button.clicked.connect(self.retry_requested.emit)
        layout.addWidget(self.retry_button)

        self.spinner = QLabel("◴", self)
        self.spinner.setObjectName("AssistantConnectionSpinner")
        self.spinner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spinner.setFixedSize(17, 17)
        self.spinner.hide()
        layout.addWidget(self.spinner)

        self.spinner_timer = QTimer(self)
        self.spinner_timer.setInterval(300)
        self.spinner_timer.timeout.connect(self._advance_spinner)

        self.status_label = QLabel("Disconnected", self)
        self.status_label.setObjectName("AssistantModelConnectionStatus")
        self.status_label.setProperty("state", "disconnected")
        self.status_label.setMinimumWidth(0)
        self.status_label.setMaximumWidth(112)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.status_label)

        # A dedicated Popup frame keeps embedded combos and buttons fully interactive.
        self.popup = QFrame(self, Qt.WindowType.Popup)
        self.popup.setObjectName("AssistantModelPickerPopup")
        self.popup.setMinimumWidth(370)
        self.popup.setMaximumWidth(480)
        self.popup.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        popup_layout = QVBoxLayout(self.popup)
        popup_layout.setContentsMargins(14, 13, 14, 13)
        popup_layout.setSpacing(9)

        provider_label = QLabel("PROVIDER", self.popup)
        provider_label.setObjectName("AssistantModelPickerCaption")
        popup_layout.addWidget(provider_label)
        self.provider_combo = QComboBox(self.popup)
        self.provider_combo.setObjectName("AssistantProviderSelect")
        self.provider_combo.addItem("OpenCode", "opencode")
        self.provider_combo.addItem("Ollama", "ollama")
        self.provider_combo.setCurrentIndex(max(0, self.provider_combo.findData(self._provider)))
        popup_layout.addWidget(self.provider_combo)

        model_label = QLabel("MODEL", self.popup)
        model_label.setObjectName("AssistantModelPickerCaption")
        popup_layout.addWidget(model_label)
        self.model_combo = QComboBox(self.popup)
        self.model_combo.setObjectName("AssistantModelSelect")
        self.model_combo.addItem("Loading available models…", "")
        self.model_combo.setMinimumHeight(38)
        model_row = QHBoxLayout()
        model_row.setSpacing(8)
        model_row.addWidget(self.model_combo, 1)

        self.connect_button = QPushButton("Connect", self.popup)
        self.connect_button.setObjectName("AssistantModelConnectButton")
        self.connect_button.setMinimumHeight(38)
        self.connect_button.setMinimumWidth(92)
        self.connect_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.connect_button.clicked.connect(self.connect_requested.emit)
        model_row.addWidget(self.connect_button)

        self.disconnect_button = QPushButton("Disconnect", self.popup)
        self.disconnect_button.setObjectName("Subtle")
        self.disconnect_button.setMinimumHeight(38)
        self.disconnect_button.clicked.connect(self.disconnect_requested.emit)
        self.disconnect_button.hide()
        model_row.addWidget(self.disconnect_button)
        popup_layout.addLayout(model_row)

        self.menu_status = QLabel("Choose a model to connect.", self.popup)
        self.menu_status.setObjectName("AssistantModelPickerMenuStatus")
        self.menu_status.setWordWrap(True)
        popup_layout.addWidget(self.menu_status)

        self.provider_combo.currentIndexChanged.connect(self._sync_button_text)
        self.model_combo.currentIndexChanged.connect(self._sync_button_text)
        self._sync_button_text()

    def _toggle_popup(self):
        if self.popup.isVisible():
            self.popup.hide()
            return

        # The composer sits at the bottom of the chat, so the selector must
        # expand upward. Clamp its horizontal position to the active screen
        # to keep the complete popup visible near either screen edge.
        self.popup.adjustSize()
        popup_size = self.popup.size()
        anchor_top = self.button.mapToGlobal(QPoint(0, 0))
        screen = self.button.screen()
        available = screen.availableGeometry() if screen else None

        x = anchor_top.x()
        y = anchor_top.y() - popup_size.height() - 8
        if available is not None:
            max_x = available.right() - popup_size.width() + 1
            x = min(max(x, available.left()), max(available.left(), max_x))
            # Keep the popup above the button even on shorter screens; never
            # let it fall below the composer where it can be clipped.
            y = max(available.top() + 4, y)

        self.popup.move(QPoint(x, y))
        self.popup.show()
        self.popup.raise_()

    def _advance_spinner(self):
        self._spinner_index = (self._spinner_index + 1) % len(self._spinner_frames)
        self.spinner.setText(self._spinner_frames[self._spinner_index])

    def _sync_button_text(self, *_args):
        provider = str(self.provider_combo.currentData() or self._provider)
        self._provider = provider
        model = str(self.model_combo.currentText() or "").strip()
        if not model or self.model_combo.currentData() in (None, ""):
            model = "Ollama" if provider == "ollama" else "OpenCode"
        # Keep the model name as the only label; the up-chevron communicates
        # that the selector expands. The tooltip retains the full unabridged name.
        self.button.setToolTip(f"{provider.title()} · {model}. Open model selector.")
        self.button.setText(QFontMetrics(self.button.font()).elidedText(
            model,
            Qt.TextElideMode.ElideMiddle,
            max(72, self.button.width() - 48),
        ))

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

        if connecting:
            self.spinner.show()
            if not self.spinner_timer.isActive():
                self._spinner_index = 0
                self.spinner.setText(self._spinner_frames[0])
                self.spinner_timer.start()
        else:
            self.spinner_timer.stop()
            self.spinner.setText(self._spinner_frames[0])
            self.spinner.hide()

        self.connect_button.setEnabled(
            not self._busy
            and not connecting
            and not matches_active
            and self._provider in {"opencode", "ollama"}
        )
        self.disconnect_button.setVisible(bool(connected))
        self.disconnect_button.setEnabled(bool(connected) and not connecting and not self._busy)
        self.retry_button.setVisible(not connected)
        self.retry_button.setEnabled(not self._busy and not connecting)
        self.retry_button.setToolTip("Retry connection")
        self._sync_button_text()

    def set_busy(self, busy: bool):
        self._busy = bool(busy)
        self.provider_combo.setEnabled(not self._busy)
        self.model_combo.setEnabled(not self._busy and self.model_combo.count() > 1)
        if self._busy:
            self.connect_button.setEnabled(False)
            self.disconnect_button.setEnabled(False)
            self.retry_button.setEnabled(False)
        else:
            self.set_connection_state(
                connected=self._connected,
                active_model=self._active_model,
                connecting=self._connecting,
                provider=self._provider,
            )


class MessageComposer(QFrame):
    """Adaptive composer: one row on wide windows, input + toolbar on narrow windows."""

    send_requested = Signal()
    stop_requested = Signal()
    voice_requested = Signal()
    connect_requested = Signal()
    disconnect_requested = Signal()
    retry_requested = Signal()
    error_requested = Signal(str)

    def __init__(self, icons, parent=None, *, provider="opencode"):
        super().__init__(parent)
        self.icons = icons
        self._provider_ready = False
        self._busy = False
        self._stoppable = False
        self._compact_mode: bool | None = None
        self._compact_threshold = 760
        self.setObjectName("AssistantComposer")
        self.setMinimumWidth(0)

        root = QVBoxLayout(self)
        self._root_layout = root
        root.setContentsMargins(12, 9, 12, 9)
        root.setSpacing(5)

        self.row_container = QWidget(self)
        self.row_container.setObjectName("AssistantComposerInputRow")
        self.row_layout = QHBoxLayout(self.row_container)
        self.row_layout.setContentsMargins(0, 0, 0, 0)
        self.row_layout.setSpacing(9)

        self.bottom_row_container = QWidget(self)
        self.bottom_row_container.setObjectName("AssistantComposerToolbar")
        self.bottom_row_layout = QHBoxLayout(self.bottom_row_container)
        self.bottom_row_layout.setContentsMargins(0, 0, 0, 0)
        self.bottom_row_layout.setSpacing(8)
        self.bottom_row_container.hide()

        self.model_picker = ModelPicker(icons, self, provider=provider)
        self.model_picker.connect_requested.connect(self.connect_requested.emit)
        self.model_picker.disconnect_requested.connect(self.disconnect_requested.emit)
        self.model_picker.retry_requested.connect(self.retry_requested.emit)
        self.provider_combo = self.model_picker.provider_combo
        self.model_combo = self.model_picker.model_combo

        self.prompt = PromptEditor(self)
        self.prompt.send_requested.connect(self._on_primary_action)
        self.prompt.textChanged.connect(self._sync_send_button)

        self.voice_chat_button = QPushButton("Start voice", self)
        self.voice_chat_button.setObjectName("AssistantVoiceButton")
        self.voice_chat_button.setIcon(icons.icon("mic", size=17))
        self.voice_chat_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.voice_chat_button.setAccessibleName("Start voice conversation")
        self.voice_chat_button.setToolTip("Start or stop local voice conversation")
        self.voice_chat_button.setMinimumHeight(42)
        self.voice_chat_button.clicked.connect(self.voice_requested.emit)

        self.send_button = QPushButton(self)
        self.send_button.setObjectName("AssistantSendButton")
        self.send_button.setIcon(icons.icon("send", color="#ffffff", size=18))
        self.send_button.setFixedSize(42, 42)
        self.send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_button.setToolTip("Send message · Enter")
        self.send_button.setAccessibleName("Send message")
        self.send_button.clicked.connect(self._on_primary_action)
        self.send_button.setEnabled(False)
        self.stop_button = self.send_button

        self.status_label = QLabel("", self)
        self.status_label.setObjectName("AssistantComposerStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumWidth(0)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status_label.hide()

        self.voice_live_status = QLabel("Voice off", self)
        self.voice_live_status.setObjectName("AssistantVoiceStatus")
        self.voice_live_status.setWordWrap(True)
        self.voice_live_status.setAccessibleName("Voice chat status")
        self.voice_live_status.hide()

        root.addWidget(self.row_container)
        root.addWidget(self.bottom_row_container)
        root.addWidget(self.voice_live_status)

        self._set_compact_mode(False)

    def _set_compact_mode(self, compact: bool):
        compact = bool(compact)
        if self._compact_mode is compact:
            return
        self._compact_mode = compact
        for widget in (
            self.model_picker, self.prompt, self.voice_chat_button,
            self.send_button, self.status_label,
        ):
            self.row_layout.removeWidget(widget)
            self.bottom_row_layout.removeWidget(widget)

        if compact:
            self.row_layout.addWidget(self.prompt, 1)
            self.bottom_row_layout.addWidget(self.model_picker, 0)
            self.bottom_row_layout.addWidget(self.status_label, 1)
            self.bottom_row_layout.addWidget(self.voice_chat_button, 0)
            self.bottom_row_layout.addWidget(self.send_button, 0)
            self.bottom_row_container.show()
        else:
            self.row_layout.addWidget(self.model_picker, 0)
            self.row_layout.addWidget(self.prompt, 1)
            self.row_layout.addWidget(self.voice_chat_button, 0)
            self.row_layout.addWidget(self.send_button, 0)
            self.bottom_row_container.hide()
        self._update_status_visibility()
        self._sync_send_button()

    def _update_status_visibility(self):
        show_status = self._compact_mode and bool(self.status_label.text().strip())
        self.status_label.setVisible(show_status)
        self.model_picker.status_label.setVisible(
            not self._compact_mode or self.width() >= 620
        )
        very_narrow = self._compact_mode and self.width() < 440
        if self._compact_mode:
            self._root_layout.setContentsMargins(
                7 if very_narrow else 10, 6 if very_narrow else 7,
                7 if very_narrow else 10, 6 if very_narrow else 7,
            )
            self.bottom_row_layout.setSpacing(5 if very_narrow else 8)
            self.model_picker.layout().setSpacing(4 if very_narrow else 7)
            self.model_picker.button.setMinimumWidth(64 if very_narrow else 128)
            self.model_picker.button.setMaximumWidth(92 if very_narrow else 230)
            self.model_picker.retry_button.setFixedSize(
                28 if very_narrow else 34, 28 if very_narrow else 34
            )
            self.model_picker.spinner.setFixedSize(
                14 if very_narrow else 17, 14 if very_narrow else 17
            )
        else:
            self._root_layout.setContentsMargins(12, 9, 12, 9)
            self.bottom_row_layout.setSpacing(8)
            self.model_picker.layout().setSpacing(7)
            self.model_picker.button.setMinimumWidth(128)
            self.model_picker.button.setMaximumWidth(230)
            self.model_picker.retry_button.setFixedSize(34, 34)
            self.model_picker.spinner.setFixedSize(17, 17)
        if very_narrow:
            self.voice_chat_button.setText("")
            self.voice_chat_button.setFixedSize(42, 42)
            self.voice_chat_button.setProperty("iconOnly", True)
            self.voice_chat_button.setToolTip("Start voice")
            self.voice_chat_button.setAccessibleName("Start voice conversation")
        else:
            self.voice_chat_button.setText("Start voice")
            self.voice_chat_button.setMinimumSize(0, 42)
            self.voice_chat_button.setMaximumSize(16777215, 42)
            self.voice_chat_button.setProperty("iconOnly", False)
            self.voice_chat_button.setToolTip("Start or stop local voice conversation")
        self.voice_chat_button.style().unpolish(self.voice_chat_button)
        self.voice_chat_button.style().polish(self.voice_chat_button)
        self.model_picker._sync_button_text()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._set_compact_mode(event.size().width() < self._compact_threshold)
        self._update_status_visibility()

    def _on_primary_action(self):
        if self._busy:
            if self._stoppable:
                self.stop_requested.emit()
            return
        if self._provider_ready and self.prompt.toPlainText().strip():
            self.send_requested.emit()

    def set_status(self, text: str, *, error: bool = False):
        value = str(text or "").strip()
        if error and value:
            self.status_label.clear()
            self.status_label.hide()
            self.error_requested.emit(value)
            return
        self.status_label.setText(value)
        self._update_status_visibility()

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
