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
    outer.setSpacing(12)

    accent = QFrame(widget)
    accent.setObjectName("PageHeaderAccent")
    accent.setFixedSize(3, 38 if subtitle else 30)
    outer.addWidget(accent, 0, Qt.AlignmentFlag.AlignVCenter)

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
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(12)
    for widget in widgets:
        layout.addWidget(widget)
    return layout


def section_row(title: str, action: QWidget | None = None) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    label = QLabel(title)
    label.setObjectName("SectionTitle")
    layout.addWidget(label)
    layout.addStretch(1)
    if action is not None:
        layout.addWidget(action)
    return row
