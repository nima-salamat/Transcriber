"""Incremental conversation renderer with stable streaming cards and scroll anchoring."""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .message_widget import MessageWidget


class ConversationView(QFrame):
    """Stable message cards; streamed tokens are inserted into an existing document."""

    prompt_selected = Signal(str)

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
        self.content_layout.setContentsMargins(10, 14, 10, 16)
        self.content_layout.setSpacing(11)

        self.empty_state = QFrame()
        self.empty_state.setObjectName("AssistantEmptyState")
        self.empty_state.setMaximumWidth(720)
        self.empty_state.setMinimumWidth(0)
        self.empty_state.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum
        )
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setContentsMargins(12, 12, 12, 12)
        empty_layout.setSpacing(8)
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

        self.prompt_grid = QWidget(self.empty_state)
        self.prompt_grid.setObjectName("AssistantPromptGrid")
        self.prompt_grid.setMinimumWidth(0)
        self.prompt_grid.setMaximumWidth(680)
        self.prompt_grid.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.prompt_grid_layout = QGridLayout(self.prompt_grid)
        self.prompt_grid_layout.setContentsMargins(0, 0, 0, 0)
        self.prompt_grid_layout.setHorizontalSpacing(8)
        self.prompt_grid_layout.setVerticalSpacing(8)
        self.prompt_buttons: list[QPushButton] = []

        prompt_examples = (
            (
                "Summarize a transcript",
                "Key points and action items.",
                "Summarize the transcript I provide into a concise overview, key points, decisions, and action items.",
            ),
            (
                "Improve transcript quality",
                "Spot unclear speech errors.",
                "Review the transcript I provide for likely speech-recognition mistakes, unclear phrases, repetitions, and formatting issues. Suggest corrections without silently changing uncertain words.",
            ),
            (
                "Create readable subtitles",
                "Clean, readable subtitle cues.",
                "Help me turn the transcript I provide into readable subtitle cues. Keep each cue concise, use natural line breaks, and preserve the original meaning.",
            ),
            (
                "Plan an audio workflow",
                "A faster transcription workflow.",
                "Help me choose an efficient workflow for transcribing and cleaning an audio recording. Explain the best order of steps and relevant options.",
            ),
        )
        for title_text, detail_text, prompt_text in prompt_examples:
            button = QPushButton(self.prompt_grid)
            button.setObjectName("AssistantPromptSuggestion")
            button.setMinimumWidth(0)
            button.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
            )
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAccessibleName(title_text)
            button.setToolTip(f"Use this prompt: {title_text}")

            card_layout = QVBoxLayout(button)
            card_layout.setContentsMargins(16, 9, 16, 9)
            card_layout.setSpacing(2)
            card_layout.addStretch(1)
            title_label = QLabel(title_text, button)
            title_label.setObjectName("AssistantPromptSuggestionTitle")
            title_label.setMinimumWidth(0)
            title_label.setAlignment(
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
            )
            title_label.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )
            detail_label = QLabel(detail_text, button)
            detail_label.setObjectName("AssistantPromptSuggestionDescription")
            detail_label.setMinimumWidth(0)
            detail_label.setWordWrap(False)
            detail_label.setAlignment(
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
            )
            detail_label.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )
            card_layout.addWidget(title_label)
            card_layout.addWidget(detail_label)
            card_layout.addStretch(1)
            # QPushButton's own sizeHint does not include child labels reliably.
            # Derive its minimum height from the actual label metrics and padding.
            card_layout.activate()
            button.setMinimumHeight(card_layout.sizeHint().height() + 2)
            button.clicked.connect(
                lambda _checked=False, value=prompt_text: self.prompt_selected.emit(value)
            )
            self.prompt_buttons.append(button)

        empty_layout.addWidget(self.prompt_grid)
        self._prompt_columns = 0
        self._layout_prompt_suggestions(self.width())

        # Center the welcome screen, but remove its top spacer once a chat
        # starts so message history remains anchored to the top.
        self.empty_top_spacer = QWidget(self.content)
        self.empty_top_spacer.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding
        )
        self.content_layout.addWidget(self.empty_top_spacer, 1)
        self.content_layout.addWidget(
            self.empty_state, 0, Qt.AlignmentFlag.AlignHCenter
        )
        self.content_layout.addStretch(1)
        self.scroll_area.setWidget(self.content)
        self._update_empty_state_scroll_height()
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
        self._stream_scroll_timer.timeout.connect(self.scroll_to_latest)

        # Own deferred callbacks so deleting the conversation view cancels
        # pending work instead of invoking slots on an already-destroyed Qt object.
        self._scroll_sync_timer = QTimer(self)
        self._scroll_sync_timer.setSingleShot(True)
        self._scroll_sync_timer.timeout.connect(self._sync_follow_state_from_scrollbar)
        self._scroll_apply_timer = QTimer(self)
        self._scroll_apply_timer.setSingleShot(True)
        self._scroll_apply_timer.timeout.connect(self._apply_deferred_scroll)
        self._message_width_timer = QTimer(self)
        self._message_width_timer.setSingleShot(True)
        self._message_width_timer.timeout.connect(self._update_message_widths)
        self._follow_stream = True
        self._scroll_generation = 0
        self._programmatic_scroll = False
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.sliderPressed.connect(self._begin_manual_scroll)
        scrollbar.sliderMoved.connect(self._sync_follow_state_from_scrollbar)
        scrollbar.sliderReleased.connect(self._sync_follow_state_from_scrollbar)
        scrollbar.actionTriggered.connect(self._begin_manual_scroll)
        scrollbar.actionTriggered.connect(self._schedule_scroll_sync)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def _layout_prompt_suggestions(self, width: int):
        available_width = max(0, int(width) - 32)
        self.empty_state.setMinimumWidth(min(688, available_width))
        # Keep two compact columns until the conversation pane becomes narrow.
        columns = 2 if int(width) >= 540 else 1
        if columns == self._prompt_columns:
            return
        self._prompt_columns = columns
        while self.prompt_grid_layout.count():
            self.prompt_grid_layout.takeAt(0)
        for index, button in enumerate(self.prompt_buttons):
            self.prompt_grid_layout.addWidget(
                button, index // columns, index % columns
            )
        for column in range(2):
            self.prompt_grid_layout.setColumnStretch(
                column, 1 if column < columns else 0
            )

    def _update_empty_state_scroll_height(self):
        """Keep every welcome card reachable when the chat viewport is short."""
        if self.empty_state.isHidden():
            self.content.setMinimumHeight(0)
            return

        self.prompt_grid_layout.activate()
        self._empty_layout.activate()
        self.content_layout.activate()
        # Include layout margins and the two spacer gaps as well as the card
        # height; otherwise the final row can extend past the scroll widget.
        required_height = self.content_layout.minimumSize().height()
        self.content.setMinimumHeight(max(0, required_height))

    def dispose(self):
        """Stop deferred UI work and detach the application event filter."""
        for timer_name in (
            "_stream_scroll_timer",
            "_scroll_sync_timer",
            "_scroll_apply_timer",
            "_message_width_timer",
        ):
            timer = getattr(self, timer_name, None)
            if timer is not None:
                timer.stop()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)

    def closeEvent(self, event):
        self.dispose()
        super().closeEvent(event)

    def toPlainText(self) -> str:
        return "\n\n".join(str(item.get("text") or "") for item in self._messages)

    def _is_near_bottom(self) -> bool:
        bar = self.scroll_area.verticalScrollBar()
        return bar.maximum() - bar.value() <= 4

    def _begin_manual_scroll(self):
        self._stream_scroll_timer.stop()
        self._scroll_generation += 1
        self._follow_stream = False

    def _schedule_scroll_sync(self, *_args):
        self._scroll_sync_timer.start(0)

    def _sync_follow_state_from_scrollbar(self, *_args):
        if self._programmatic_scroll:
            return
        self._follow_stream = self._is_near_bottom()
        self.jump_button.setVisible(bool(self._messages) and not self._follow_stream)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel and isinstance(watched, QWidget):
            scroll_area = self.scroll_area
            inside = watched is scroll_area or scroll_area.isAncestorOf(watched)
            if inside:
                bar = scroll_area.verticalScrollBar()
                angle = event.angleDelta().y()
                delta = angle if angle else event.pixelDelta().y()
                at_top = bar.value() <= bar.minimum()
                at_bottom = bar.value() >= bar.maximum()
                # Do not let wheel input at the boundary bubble to an outer
                # scroll area. That propagation is perceived as a jump or bounce.
                if (delta < 0 and at_bottom) or (delta > 0 and at_top):
                    event.accept()
                    return True
                self._stream_scroll_timer.stop()
                self._scroll_generation += 1
                # Disable auto-follow immediately; a resize/layout event can
                # occur before the scrollbar has applied this wheel delta.
                self._follow_stream = False
                self._schedule_scroll_sync()
        return super().eventFilter(watched, event)

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
        has_messages = bool(incoming)
        self.empty_state.setVisible(not has_messages)
        self.empty_top_spacer.setVisible(not has_messages)
        self._update_empty_state_scroll_height()
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
        widget.setMaximumWidth(self._responsive_message_max_width())
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
        self._scroll_generation += 1
        self._scroll_apply_timer.start(0)

    def _apply_deferred_scroll(self):
        self._scroll_to_latest_now(self._scroll_generation)

    def _scroll_to_latest_now(self, generation: int | None = None):
        if generation is not None and generation != self._scroll_generation:
            return
        bar = self.scroll_area.verticalScrollBar()
        self._programmatic_scroll = True
        try:
            bar.setValue(bar.maximum())
        finally:
            self._programmatic_scroll = False
        self.jump_button.hide()
        self._follow_stream = True

    def _responsive_message_max_width(self) -> int:
        """Keep chat cards inside the viewport instead of forcing a desktop width."""
        viewport_width = max(1, self.scroll_area.viewport().width())
        return max(1, min(1100, int(viewport_width * 0.97)))

    def _update_message_widths(self):
        max_width = self._responsive_message_max_width()
        for widget in self._widgets:
            if widget.maximumWidth() != max_width:
                widget.setMaximumWidth(max_width)
                widget.body.refresh_document_size()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        narrow = event.size().width() < 560
        if narrow:
            self.content_layout.setContentsMargins(4, 8, 4, 10)
            self._empty_layout.setContentsMargins(8, 10, 8, 10)
            self._empty_layout.setSpacing(7)
        else:
            self.content_layout.setContentsMargins(10, 14, 10, 16)
            self._empty_layout.setContentsMargins(12, 14, 12, 14)
            self._empty_layout.setSpacing(9)
        self._layout_prompt_suggestions(event.size().width())
        self._update_empty_state_scroll_height()
        for widget in self._widgets:
            widget.body.refresh_document_size()
        # Let the scroll area's viewport finish its layout before measuring it.
        self._message_width_timer.start(0)
        if self._follow_stream:
            self.scroll_to_latest()
