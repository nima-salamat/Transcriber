"""Expandable, truthful presentation of Agent tool activity."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
)


class AgentActivityWidget(QFrame):
    """Summarize actual tool events without displaying private model reasoning."""

    _STATUS_LABELS = {
        "pending": "Waiting",
        "running": "Running",
        "completed": "Completed",
        "failed": "Failed",
        "cancelled": "Cancelled",
        "awaiting_approval": "Waiting for approval",
    }

    def __init__(self, icons=None, parent=None):
        super().__init__(parent)
        self.setObjectName("AssistantActivity")
        self._events: dict[str, tuple[str, str, str]] = {}
        self._rows: dict[str, tuple[QFrame, QLabel, QLabel, QLabel, QLabel]] = {}
        self._expanded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(5)

        header = QHBoxLayout()
        self.toggle_button = QToolButton()
        self.toggle_button.setObjectName("AssistantActivityToggle")
        self.toggle_button.setText("Agent activity")
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle_button.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle_button.clicked.connect(self.toggle_expanded)
        header.addWidget(self.toggle_button)

        self.summary_label = QLabel("No tool activity yet")
        self.summary_label.setObjectName("Muted")
        header.addWidget(self.summary_label, 1)
        layout.addLayout(header)

        self.details = QFrame()
        self.details.setObjectName("AssistantActivityDetails")
        self.details_layout = QVBoxLayout(self.details)
        self.details_layout.setContentsMargins(8, 4, 8, 4)
        self.details_layout.setSpacing(4)
        layout.addWidget(self.details)
        self.details.hide()

    def toggle_expanded(self):
        self._expanded = not self._expanded
        self.details.setVisible(self._expanded)
        self.toggle_button.setArrowType(
            Qt.ArrowType.DownArrow if self._expanded else Qt.ArrowType.RightArrow
        )

    def add_event(
        self,
        event_id: str,
        title: str,
        status: str = "running",
        details: str = "",
    ):
        key = str(event_id or f"event-{len(self._events) + 1}")
        state = str(status or "running").casefold().replace(" ", "_")
        if state not in self._STATUS_LABELS:
            state = "failed" if "fail" in state or "error" in state else "running"
        title_value = str(title or "Agent tool")
        detail_value = str(details or "")
        self._events[key] = (title_value, state, detail_value)

        if key not in self._rows:
            row = QFrame(self.details)
            row.setObjectName("AssistantActivityRow")
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(4, 4, 4, 6)
            row_layout.setSpacing(3)

            heading = QHBoxLayout()
            heading.setSpacing(8)
            icon = QLabel("•")
            icon.setObjectName("AssistantActivityIcon")
            name = QLabel()
            name.setObjectName("AssistantActivityName")
            name.setWordWrap(True)
            status_label = QLabel()
            status_label.setObjectName("AssistantActivityStatus")
            heading.addWidget(icon)
            heading.addWidget(name, 1)
            heading.addWidget(status_label)
            row_layout.addLayout(heading)

            detail_label = QLabel()
            detail_label.setObjectName("AssistantActivityDetail")
            detail_label.setWordWrap(True)
            detail_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            detail_label.hide()
            row_layout.addWidget(detail_label)

            self.details_layout.addWidget(row)
            self._rows[key] = (row, icon, name, status_label, detail_label)

        row, icon, name, status_label, detail_label = self._rows[key]
        title_value, state_value, detail_value = self._events[key]
        icon.setText({
            "running": "◌",
            "completed": "✓",
            "failed": "!",
            "cancelled": "–",
            "awaiting_approval": "◇",
            "pending": "…",
        }.get(state_value, "•"))
        name.setText(title_value)
        status_label.setText(self._STATUS_LABELS[state_value])
        detail_label.setText(detail_value[:2400])
        detail_label.setVisible(bool(detail_value))
        row.setToolTip(detail_value[:8000])
        name.setToolTip(detail_value[:8000])
        row.setProperty("state", state_value)
        row.style().unpolish(row)
        row.style().polish(row)

        finished = sum(
            1
            for _title, value, _detail in self._events.values()
            if value in {"completed", "failed", "cancelled"}
        )
        self.summary_label.setText(
            f"{len(self._events)} action(s) · {finished} finished"
        )
        if self._expanded:
            self.details.show()

    def clear(self):
        self._events.clear()
        self._rows.clear()
        while self.details_layout.count():
            item = self.details_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.summary_label.setText("No tool activity yet")


class AgentThinkingWidget(QFrame):
    """Compact live status and expandable provider-supplied thinking stream."""

    _STATUS_MAP = (
        (("listen", "wake word"), "Listening"),
        (("loading", "load model"), "Loading"),
        (("loaded",), "Loaded"),
        (("ready",), "Ready"),
        (("connect", "connecting"), "Connecting"),
        (("transcrib", "speech recognition"), "Transcribing"),
        (("stopping",), "Stopping"),
        (("stopped", "cancelled", "canceled"), "Stopped"),
        (("fail", "error"), "Error"),
        (("complete", "finished", "done"), "Done"),
        (("tool", "running", "working", "search", "execut"), "Working"),
        (("generat", "response"), "Generating"),
        (("think", "reason"), "Thinking"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QPlainTextEdit

        self.setObjectName("AssistantThinking")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._has_thinking = False
        self._expanded = False
        self._user_collapsed = False
        self._status = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 6, 10, 6)
        outer.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(8)
        self.toggle_button = QToolButton(self)
        self.toggle_button.setObjectName("AssistantThinkingToggle")
        self.toggle_button.setText("Thinking")
        self.toggle_button.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_button.setEnabled(False)
        self.toggle_button.clicked.connect(self.toggle_expanded)
        header.addWidget(self.toggle_button)

        self.status_label = QLabel("Ready", self)
        self.status_label.setObjectName("AssistantThinkingStatus")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.status_label, 1)
        outer.addLayout(header)

        self.body = QPlainTextEdit(self)
        self.body.setObjectName("AssistantThinkingBody")
        self.body.setReadOnly(True)
        self.body.setMaximumBlockCount(240)
        self.body.setMaximumHeight(168)
        self.body.setMinimumHeight(58)
        self.body.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.body.hide()
        outer.addWidget(self.body)
        self.hide()

    @classmethod
    def _friendly_status(cls, value: str) -> str:
        raw = " ".join(str(value or "").split())
        normalized = raw.casefold()
        for cues, label in cls._STATUS_MAP:
            if any(cue in normalized for cue in cues):
                if label == "Working" and raw:
                    detail = raw.split("·", 1)[-1].strip()
                    return f"Working · {detail}" if detail and detail.casefold() != "working" else label
                if label == "Loaded" and raw:
                    detail = raw.split("·", 1)[-1].strip()
                    return f"Loaded · {detail}" if detail and detail.casefold() not in {"loaded", "ready"} else label
                return label
        return raw[:72] or "Ready"

    def begin_turn(self, status: str = "Thinking"):
        self.body.clear()
        self._has_thinking = False
        self._expanded = False
        self._user_collapsed = False
        self.body.hide()
        self.toggle_button.setText(self._friendly_status(status))
        self.toggle_button.setEnabled(False)
        self.toggle_button.setArrowType(Qt.ArrowType.RightArrow)
        self.status_label.setText("")
        self.setVisible(True)
        self._status = self._friendly_status(status)

    def set_status(self, status: str):
        raw = str(status or "").strip()
        if not raw:
            return
        self._status = self._friendly_status(raw)
        if self._has_thinking:
            self.toggle_button.setText("Thought process")
            self.status_label.setText(
                "Live" if self._status in {"Thinking", "Generating"} else self._status
            )
        else:
            self.toggle_button.setText(self._status)
            self.status_label.setText(
                "Live" if self._status in {"Thinking", "Generating", "Listening", "Transcribing"}
                else ""
            )
        if self._status not in {"Ready"}:
            self.show()

    def append_thinking(self, chunk: str):
        value = str(chunk or "")
        if not value:
            return
        self._has_thinking = True
        self.toggle_button.setText("Thinking")
        self.toggle_button.setEnabled(True)
        self._status = "Thinking"
        self.status_label.setText("Live")
        self.show()
        cursor = self.body.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(value)
        self.body.setTextCursor(cursor)
        self.body.ensureCursorVisible()
        if not self._user_collapsed and not self._expanded:
            self._set_expanded(True)

    def finish_turn(self, status: str = "Done"):
        self.set_status(status)
        if self._has_thinking:
            # Keep the provider's reasoning available, but collapse the panel after
            # the final answer just like a completed thought summary.
            self._set_expanded(False)
            self.toggle_button.setText("Thought process")
            self.status_label.setText(
                f"{self._status} · details available"
                if self._status in {"Stopped", "Error"} else "Details available"
            )
        else:
            self.status_label.setText("")

    def toggle_expanded(self):
        if not self._has_thinking:
            return
        self._user_collapsed = self._expanded
        self._set_expanded(not self._expanded)

    def _set_expanded(self, expanded: bool):
        self._expanded = bool(expanded)
        self.body.setVisible(self._expanded)
        self.toggle_button.setArrowType(
            Qt.ArrowType.DownArrow if self._expanded else Qt.ArrowType.RightArrow
        )

    def reset(self):
        self.body.clear()
        self._has_thinking = False
        self._expanded = False
        self._user_collapsed = False
        self.body.hide()
        self.toggle_button.setEnabled(False)
        self.toggle_button.setText("Ready")
        self.toggle_button.setArrowType(Qt.ArrowType.RightArrow)
        self.status_label.clear()
        self.hide()
