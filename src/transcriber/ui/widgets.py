"""Small reusable UI primitives shared by every application page."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from transcriber.ui.design.tokens import SPACING



class Card(QFrame):
    """Theme-aware surface used consistently across page workspaces."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(0)


def page_header(title: str, subtitle: str = "") -> QWidget:
    """A compact page heading with one shared visual hierarchy."""
    widget = QWidget()
    widget.setObjectName("PageHeader")
    widget.setMinimumWidth(0)

    outer = QHBoxLayout(widget)
    outer.setContentsMargins(0, 0, 0, 8)
    outer.setSpacing(0)

    copy = QWidget(widget)
    copy.setObjectName("PageHeaderCopy")
    copy.setMinimumWidth(0)
    copy.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    layout = QVBoxLayout(copy)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)

    heading = QLabel(str(title), copy)
    heading.setObjectName("PageTitle")
    heading.setWordWrap(True)
    heading.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(heading)

    if subtitle:
        description = QLabel(str(subtitle), copy)
        description.setObjectName("PageDescription")
        description.setWordWrap(True)
        description.setMinimumWidth(0)
        description.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(description)

    outer.addWidget(copy, 1)
    return widget


def primary_button(label: str, parent=None) -> QPushButton:
    button = QPushButton(label, parent)
    button.setObjectName("Primary")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def labelled_value(label: str, value: str) -> QWidget:
    widget = QWidget()
    widget.setMinimumWidth(0)
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    top = QLabel(label)
    top.setObjectName("Muted")
    bottom = QLabel(value)
    bottom.setWordWrap(True)
    bottom.setMinimumWidth(0)
    layout.addWidget(top)
    layout.addWidget(bottom)
    return widget


def add_card_content(card: Card, *widgets) -> QVBoxLayout:
    layout = QVBoxLayout(card)
    layout.setContentsMargins(*(SPACING["lg"] for _ in range(4)))
    layout.setSpacing(SPACING["md"])
    for widget in widgets:
        layout.addWidget(widget)
    return layout


def section_row(title: str, action: QWidget | None = None) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(SPACING["sm"])
    label = QLabel(title)
    label.setObjectName("SectionTitle")
    layout.addWidget(label)
    layout.addStretch(1)
    if action is not None:
        layout.addWidget(action)
    return row


def section_header(title: str, subtitle: str = "", action: QWidget | None = None) -> QWidget:
    """A compact section heading with optional context and one trailing action."""
    widget = QWidget()
    widget.setObjectName("SectionHeader")
    widget.setMinimumWidth(0)
    row = QHBoxLayout(widget)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(SPACING["md"])

    copy = QWidget(widget)
    copy.setObjectName("SectionHeaderCopy")
    copy.setMinimumWidth(0)
    copy_layout = QVBoxLayout(copy)
    copy_layout.setContentsMargins(0, 0, 0, 0)
    copy_layout.setSpacing(3)

    heading = QLabel(str(title), copy)
    heading.setObjectName("SectionTitle")
    copy_layout.addWidget(heading)
    if subtitle:
        description = QLabel(str(subtitle), copy)
        description.setObjectName("SectionDescription")
        description.setWordWrap(True)
        copy_layout.addWidget(description)

    row.addWidget(copy, 1)
    if action is not None:
        row.addWidget(action, 0, Qt.AlignmentFlag.AlignVCenter)
    return widget


def empty_state(title: str, description: str = "", action: QWidget | None = None) -> QFrame:
    """A reusable, task-oriented empty state rather than a centered placeholder label."""
    frame = QFrame()
    frame.setObjectName("WorkspaceEmptyState")
    frame.setMinimumWidth(0)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(24, 22, 24, 22)
    layout.setSpacing(SPACING["sm"])
    layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

    heading = QLabel(str(title), frame)
    heading.setObjectName("EmptyStateTitle")
    heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
    heading.setWordWrap(True)
    layout.addWidget(heading)
    if description:
        detail = QLabel(str(description), frame)
        detail.setObjectName("EmptyStateDescription")
        detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail.setWordWrap(True)
        detail.setMaximumWidth(520)
        layout.addWidget(detail, 0, Qt.AlignmentFlag.AlignHCenter)
    if action is not None:
        layout.addSpacing(SPACING["sm"])
        layout.addWidget(action, 0, Qt.AlignmentFlag.AlignHCenter)
    return frame


def status_pill(text: str, state: str = "neutral", parent=None) -> QLabel:
    """Create a compact, accessible label whose state is rendered by the theme."""
    label = QLabel(str(text), parent)
    label.setObjectName("StatusPill")
    label.setProperty("state", str(state))
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def metric_card(caption: str, value: str = "—", detail: str = "") -> tuple[Card, QLabel]:
    """A compact metric surface; returns the card and its live value label."""
    card = Card()
    card.setObjectName("MetricCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 11, 14, 11)
    layout.setSpacing(3)
    label = QLabel(str(caption).upper())
    label.setObjectName("MetricCaption")
    result = QLabel(str(value))
    result.setObjectName("MetricValue")
    layout.addWidget(label)
    layout.addWidget(result)
    if detail:
        note = QLabel(str(detail))
        note.setObjectName("MetricDetail")
        note.setWordWrap(True)
        layout.addWidget(note)
    return card, result
