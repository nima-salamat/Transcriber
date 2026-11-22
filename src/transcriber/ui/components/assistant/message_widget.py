"""Role-aware message cards with incremental streaming and inline Agent thinking."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QClipboard, QGuiApplication, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
)

from .message_renderer import SafeMarkdownBrowser


class MessageWidget(QFrame):
    def __init__(
        self,
        role: str,
        text: str,
        icons=None,
        parent=None,
        *,
        thinking: str = "",
        status: str = "",
        streaming: bool = False,
    ):
        super().__init__(parent)
        self.role = str(role or "assistant")
        self.icons = icons
        self.setObjectName(f"AssistantMessage_{self.role}")
        self.setMinimumWidth(0)
        self.setMaximumWidth(1100)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.setProperty("role", self.role)

        self._text = ""
        self._streaming = False
        self._thinking_text = ""
        self._thinking_expanded = False
        self._thinking_user_collapsed = False
        self._status = ""
        self._collapsible = self.role in {"tool", "system"}
        self._details_expanded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(11, 9, 11, 10)
        layout.setSpacing(5)

        header = QHBoxLayout()
        self.role_label = QLabel({
            "user": "You", "assistant": "Transcriber", "tool": "Action",
            "error": "Error", "system": "Status",
        }.get(self.role, "Transcriber"))
        self.role_label.setObjectName("AssistantMessageRole")
        header.addWidget(self.role_label)

        if self._collapsible:
            self.detail_toggle = QToolButton(self)
            self.detail_toggle.setObjectName("AssistantMessageDisclosure")
            self.detail_toggle.setText("Show details")
            self.detail_toggle.setArrowType(Qt.ArrowType.RightArrow)
            self.detail_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            self.detail_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
            self.detail_toggle.setAccessibleName("Show agent activity details")
            self.detail_toggle.clicked.connect(self._toggle_details)
            header.addWidget(self.detail_toggle)
        else:
            self.detail_toggle = None
        header.addStretch(1)

        self.copy_button = QToolButton(self)
        self.copy_button.setObjectName("AssistantMessageAction")
        self.copy_button.setText("Copy")
        self.copy_button.setToolTip("Copy this message")
        self.copy_button.setAccessibleName("Copy message")
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button.clicked.connect(self._copy_message)
        header.addWidget(self.copy_button)
        layout.addLayout(header)

        # Thinking belongs to the assistant message itself, above its answer,
        # rather than a detached panel at the bottom of the conversation.
        self.thinking_frame = QFrame(self)
        self.thinking_frame.setObjectName("AssistantInlineThinking")
        thinking_layout = QVBoxLayout(self.thinking_frame)
        thinking_layout.setContentsMargins(0, 2, 0, 2)
        thinking_layout.setSpacing(4)
        thinking_header = QHBoxLayout()
        thinking_header.setSpacing(7)
        self.thinking_toggle = QToolButton(self.thinking_frame)
        self.thinking_toggle.setObjectName("AssistantInlineThinkingToggle")
        self.thinking_toggle.setText("Thinking")
        self.thinking_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.thinking_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.thinking_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.thinking_toggle.clicked.connect(self._toggle_thinking)
        thinking_header.addWidget(self.thinking_toggle)
        self.thinking_status = QLabel("", self.thinking_frame)
        self.thinking_status.setObjectName("AssistantInlineThinkingStatus")
        thinking_header.addWidget(self.thinking_status)
        thinking_header.addStretch(1)
        thinking_layout.addLayout(thinking_header)

        self.thinking_body = QPlainTextEdit(self.thinking_frame)
        self.thinking_body.setObjectName("AssistantInlineThinkingBody")
        self.thinking_body.setReadOnly(True)
        self.thinking_body.setFrameShape(QFrame.Shape.NoFrame)
        self.thinking_body.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.thinking_body.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.thinking_body.setMaximumBlockCount(240)
        self.thinking_body.setMinimumHeight(0)
        self.thinking_body.setMaximumHeight(136)
        self.thinking_body.hide()
        thinking_layout.addWidget(self.thinking_body)
        layout.addWidget(self.thinking_frame)
        self.thinking_frame.hide()

        self.body = SafeMarkdownBrowser(self)
        self.body.setObjectName("AssistantMessageBody")
        self.body.setMinimumWidth(0)
        self.body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.body)

        if self._collapsible:
            self.body.hide()
            self.copy_button.hide()

        self._copy_feedback_timer = QTimer(self)
        self._copy_feedback_timer.setSingleShot(True)
        self._copy_feedback_timer.setInterval(1600)
        self._copy_feedback_timer.timeout.connect(self._restore_copy_button)

        self.update_text(text)
        self.set_thinking_text(thinking)
        self.set_status(status)
        self._streaming = bool(streaming)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "body"):
            self.body.refresh_document_size()

    @staticmethod
    def _system_status_title(text: str) -> str:
        value = " ".join(str(text or "").casefold().split())
        labels = (
            (("listening", "wake word", "waiting for the wake"), "Listening"),
            (("transcrib", "converting speech", "speech-to-text"), "Transcribing"),
            (("loading", "load model"), "Loading"),
            (("loaded", "instructions loaded", "model loaded"), "Loaded"),
            (("connecting", "connection requested"), "Connecting"),
            (("connected", "connection established"), "Connected"),
            (("stopping", "stop requested", "cancellation requested"), "Stopping"),
            (("stopped", "cancelled", "canceled"), "Stopped"),
            (("thinking", "reasoning"), "Thinking"),
            (("generating", "receiving response"), "Generating"),
            (("waiting", "queued", "pending"), "Waiting"),
            (("completed", "finished", "successfully"), "Done"),
            (("error", "could not", "failed", "failure"), "Error"),
        )
        for cues, label in labels:
            if any(cue in value for cue in cues):
                return label
        return "Status"

    def update_text(self, text: str):
        self._text = str(text or "")
        self._streaming = False
        if self.role == "system":
            self.role_label.setText(self._system_status_title(self._text))
        self.body.set_markdown(self._text)
        self.copy_button.setVisible(
            bool(self._text) and (not self._collapsible or self._details_expanded)
        )
        if not self._text:
            self._restore_copy_button()

    def append_stream_text(self, chunk: str):
        """Append a token to the existing QTextDocument without reparsing Markdown."""
        value = str(chunk or "")
        if not value or self._collapsible:
            return
        self._streaming = True
        self._text += value
        self.body.append_plain_text(value)
        self.copy_button.setVisible(False)

    def finalize_stream(self, status: str = "Done"):
        """Render Markdown once, after streaming ends, rather than on every token."""
        if self._streaming:
            self.body.set_markdown(self._text)
            self._streaming = False
        self.copy_button.setVisible(bool(self._text))
        self.set_status(status)
        if self._thinking_text:
            self._thinking_user_collapsed = False
            self._set_thinking_expanded(False)
            self.thinking_toggle.setText("Thought process")

    def update_state(
        self,
        text: str,
        thinking: str = "",
        status: str = "",
        *,
        role: str | None = None,
        streaming: bool = False,
    ):
        if role is not None and str(role) != self.role:
            self.role = str(role or "assistant")
            self.setObjectName(f"AssistantMessage_{self.role}")
            self.setProperty("role", self.role)
            self.role_label.setText({
                "user": "You", "assistant": "Transcriber", "tool": "Action",
                "error": "Error", "system": "Status",
            }.get(self.role, "Transcriber"))
            self._collapsible = self.role in {"tool", "system"}
        value = str(text or "")
        if value != self._text or (not streaming and self._streaming):
            self.update_text(value)
        self.set_thinking_text(thinking)
        self.set_status(status)
        self._streaming = bool(streaming)

    def append_thinking_chunk(self, chunk: str):
        value = str(chunk or "")
        if not value or self.role != "assistant":
            return
        self._thinking_text += value
        self.thinking_frame.show()
        self.thinking_toggle.setText(
            "Thought process" if self._thinking_user_collapsed else "Thinking"
        )
        self.thinking_status.setText("Live")
        cursor = self.thinking_body.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(value)
        self.thinking_body.setTextCursor(cursor)
        self.thinking_body.ensureCursorVisible()
        if not self._thinking_user_collapsed and not self._thinking_expanded:
            self._set_thinking_expanded(True)

    def set_thinking_text(self, text: str):
        value = str(text or "")
        if self.role != "assistant":
            return
        if value != self._thinking_text:
            self._thinking_text = value
            self.thinking_body.setPlainText(value)
        visible = bool(value) or bool(self._status)
        self.thinking_frame.setVisible(visible)
        if value:
            self.thinking_toggle.setEnabled(True)
            self.thinking_toggle.setText("Thought process")
            if not self._thinking_expanded:
                self.thinking_body.hide()
        else:
            self.thinking_toggle.setEnabled(bool(self._status))
            self.thinking_body.hide()

    def set_status(self, status: str):
        value = " ".join(str(status or "").split())
        if self.role != "assistant":
            return
        self._status = value
        self.thinking_frame.setVisible(bool(value) or bool(self._thinking_text))
        if self._thinking_text:
            self.thinking_toggle.setText("Thought process")
            self.thinking_status.setText(
                "Live" if value.casefold() in {"thinking", "generating"} else value
            )
        else:
            self.thinking_toggle.setText(value or "Thinking")
            self.thinking_status.setText(
                "Live" if value.casefold() in {"thinking", "generating"} else ""
            )
        self.thinking_toggle.setEnabled(bool(value) or bool(self._thinking_text))

    def _toggle_thinking(self):
        if not self._thinking_text:
            return
        self._thinking_user_collapsed = self._thinking_expanded
        self._set_thinking_expanded(not self._thinking_expanded)

    def _set_thinking_expanded(self, expanded: bool):
        self._thinking_expanded = bool(expanded)
        self.thinking_body.setVisible(self._thinking_expanded)
        self.thinking_toggle.setArrowType(
            Qt.ArrowType.DownArrow if self._thinking_expanded else Qt.ArrowType.RightArrow
        )
        if self._thinking_text and self._status.casefold() not in {"thinking", "generating"}:
            self.thinking_toggle.setText("Thought process")

    def _toggle_details(self):
        if not self._collapsible:
            return
        self._details_expanded = not self._details_expanded
        self.body.setVisible(self._details_expanded)
        self.copy_button.setVisible(self._details_expanded and bool(self._text))
        self.detail_toggle.setArrowType(
            Qt.ArrowType.DownArrow if self._details_expanded else Qt.ArrowType.RightArrow
        )
        self.detail_toggle.setText(
            "Hide details" if self._details_expanded else "Show details"
        )
        self.detail_toggle.setAccessibleName(
            "Hide agent activity details" if self._details_expanded
            else "Show agent activity details"
        )

    def _copy_message(self, *_args):
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
