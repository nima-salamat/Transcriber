"""Expandable, truthful presentation of Agent tool activity."""
from __future__ import annotations

from PySide6.QtCore import Qt
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
