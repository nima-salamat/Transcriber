"""Incremental conversation renderer with stable streaming cards and scroll anchoring."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
    QSizePolicy,
)

from .message_widget import MessageWidget


class ConversationView(QFrame):
    """Stable message cards; streamed tokens are inserted into an existing document."""

    def __init__(self, icons=None, parent=None):
        super().__init__(parent)
        self.setObjectName("AssistantConversationView")
        self.icons = icons
        self._widgets: list[MessageWidget] = []
        self._rows: list[QWidget] = []
        self._signatures: list[tuple[str, str, str, str, bool]] = []
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
        self._empty_title = title
        self._empty_layout = empty_layout
        empty_layout.addWidget(title)
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

        self._stream_scroll_timer = QTimer(self)
        self._stream_scroll_timer.setSingleShot(True)
        self._stream_scroll_timer.setInterval(75)
        self._stream_scroll_timer.timeout.connect(self._scroll_to_latest_now)
        self._follow_stream = True

    def toPlainText(self) -> str:
        return "\n\n".join(str(item.get("text") or "") for item in self._messages)

    def _is_near_bottom(self) -> bool:
        bar = self.scroll_area.verticalScrollBar()
        return bar.maximum() - bar.value() <= 72

    @staticmethod
    def _group_helper_messages(messages: list[dict]) -> list[dict]:
        """Merge adjacent tool/system activity without merging assistant turns."""
        grouped: list[dict] = []
        helper_roles = {"tool", "system"}
        for item in messages:
            role = str(item.get("role") or "assistant")
            text = str(item.get("text") or "")
            if role in helper_roles:
                if grouped and grouped[-1]["role"] in helper_roles:
                    previous = grouped[-1]
                    previous["role"] = (
                        "tool" if role == "tool" or previous["role"] == "tool" else "system"
                    )
                    previous["text"] += "\n\n" + text
                else:
                    grouped.append({"role": role, "text": text})
            else:
                grouped.append({
                    "role": role,
                    "text": text,
                    "thinking": str(item.get("thinking") or ""),
                    "status": str(item.get("status") or ""),
                    "streaming": bool(item.get("streaming", False)),
                })
        return grouped

    @staticmethod
    def _signature(item: dict) -> tuple[str, str, str, str, bool]:
        return (
            str(item.get("role") or "assistant"),
            str(item.get("text") or ""),
            str(item.get("thinking") or ""),
            str(item.get("status") or ""),
            bool(item.get("streaming", False)),
        )

    def set_messages(self, messages: list[dict], *, force_scroll_to_bottom: bool = False):
        values = [dict(item) for item in list(messages or [])[-400:]]
        incoming = self._group_helper_messages(values)
        signatures = [self._signature(item) for item in incoming]
        was_near_bottom = self._is_near_bottom()
        old_count = len(self._signatures)
        common = 0
        while (
            common < min(old_count, len(signatures))
            and self._signatures[common] == signatures[common]
        ):
            common += 1

        if common == old_count:
            # Existing cards are unchanged; only append genuinely new messages.
            for index in range(common, len(incoming)):
                self._append_widget(incoming[index])
        elif common == old_count - 1 and old_count > 0 and len(signatures) >= old_count:
            # Only the newest existing message changed. Update that card in place,
            # then append any new activity/reply cards.
            self._widgets[common].update_state(
                incoming[common]["text"],
                incoming[common].get("thinking", ""),
                incoming[common].get("status", ""),
                role=incoming[common]["role"],
                streaming=incoming[common].get("streaming", False),
            )
            for index in range(old_count, len(incoming)):
                self._append_widget(incoming[index])
        else:
            # A previous conversation was loaded/edited, or an older item changed.
            # Rebuild only for these real structural changes, never for token chunks.
            self._clear_message_widgets()
            self._widgets = []
            self._signatures = []
            for item in incoming:
                self._append_widget(item)

        self._signatures = signatures
        self._messages = values
        self.empty_state.setVisible(not bool(incoming))
        if force_scroll_to_bottom:
            self.jump_button.hide()
            self.scroll_to_latest()
        elif was_near_bottom:
            self.jump_button.hide()
            self.scroll_to_latest()
            self._follow_stream = True
        elif incoming:
            self.jump_button.show()
            self._follow_stream = False

    def _append_widget(self, item: dict):
        role = str(item.get("role") or "assistant")
        row = QWidget(self.content)
        row.setObjectName("AssistantMessageRow")
        row.setMinimumWidth(0)
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)

        widget = MessageWidget(
            role,
            str(item.get("text") or ""),
            self.icons,
            row,
            thinking=str(item.get("thinking") or ""),
            status=str(item.get("status") or ""),
            streaming=bool(item.get("streaming", False)),
        )
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

    def _latest_assistant_widget(self) -> MessageWidget | None:
        for widget in reversed(self._widgets):
            if widget.role == "assistant":
                return widget
        return None

    def _sync_latest_signature(self):
        if not self._widgets or not self._signatures:
            return
        widget = self._widgets[-1]
        self._signatures[-1] = (
            widget.role,
            widget._text,
            widget._thinking_text,
            widget._status,
            widget._streaming,
        )

    def append_to_latest_assistant_text(self, chunk: str) -> bool:
        widget = self._latest_assistant_widget()
        if widget is None:
            return False
        was_near_bottom = self._is_near_bottom()
        widget.append_stream_text(chunk)
        self._sync_snapshot_assistant(text_chunk=str(chunk or ""))
        self._sync_widget_signature(widget)
        self._follow_stream = self._follow_stream and was_near_bottom
        if self._follow_stream:
            self.jump_button.hide()
            self._stream_scroll_timer.start()
        else:
            self.jump_button.show()
        return True

    def append_to_latest_assistant_thinking(self, chunk: str) -> bool:
        widget = self._latest_assistant_widget()
        if widget is None:
            return False
        was_near_bottom = self._is_near_bottom()
        widget.append_thinking_chunk(chunk)
        self._sync_snapshot_assistant(thinking_chunk=str(chunk or ""))
        self._sync_widget_signature(widget)
        self._follow_stream = self._follow_stream and was_near_bottom
        if self._follow_stream:
            self.jump_button.hide()
            self._stream_scroll_timer.start()
        else:
            self.jump_button.show()
        return True

    def set_latest_assistant_status(self, status: str) -> bool:
        widget = self._latest_assistant_widget()
        if widget is None:
            return False
        widget.set_status(status)
        self._sync_snapshot_assistant(status=str(status or ""))
        self._sync_widget_signature(widget)
        return True

    def finish_latest_assistant_stream(self, status: str = "Done") -> bool:
        widget = self._latest_assistant_widget()
        if widget is None:
            return False
        widget.finalize_stream(status)
        self._sync_snapshot_assistant(status=str(status or "Done"), streaming=False)
        self._sync_widget_signature(widget)
        return True

    def _sync_snapshot_assistant(
        self,
        *,
        text_chunk: str = "",
        thinking_chunk: str = "",
        status: str | None = None,
        streaming: bool | None = None,
    ):
        # Keep the transcript snapshot and compatibility text mirror in sync
        # without rebuilding visible cards while tokens arrive.
        for item in reversed(self._messages):
            if str(item.get("role") or "") != "assistant":
                continue
            if text_chunk:
                item["text"] = str(item.get("text") or "") + text_chunk
            if thinking_chunk:
                item["thinking"] = str(item.get("thinking") or "") + thinking_chunk
            if status is not None:
                item["status"] = status
            if streaming is not None:
                item["streaming"] = bool(streaming)
            return

    def _sync_widget_signature(self, widget: MessageWidget):
        try:
            index = self._widgets.index(widget)
        except ValueError:
            return
        self._signatures[index] = (
            widget.role,
            widget._text,
            widget._thinking_text,
            widget._status,
            widget._streaming,
        )

    def _clear_message_widgets(self):
        for row in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

    def scroll_to_latest(self):
        self._stream_scroll_timer.stop()
        self._scroll_to_latest_now_queued()

    def _scroll_to_latest_now_queued(self):
        QTimer.singleShot(0, self._scroll_to_latest_now)

    def _scroll_to_latest_now(self):
        bar = self.scroll_area.verticalScrollBar()
        bar.setValue(bar.maximum())
        self.jump_button.hide()
        self._follow_stream = True

    def resizeEvent(self, event):
        super().resizeEvent(event)
        narrow = event.size().width() < 560
        if narrow:
            self.content_layout.setContentsMargins(8, 12, 8, 16)
            self._empty_layout.setContentsMargins(8, 18, 8, 18)
            self._empty_layout.setSpacing(9)
        else:
            self.content_layout.setContentsMargins(18, 22, 18, 26)
            self._empty_layout.setContentsMargins(18, 34, 18, 34)
            self._empty_layout.setSpacing(12)
        for widget in self._widgets:
            widget.body.refresh_document_size()
        if self._is_near_bottom():
            self.scroll_to_latest()
