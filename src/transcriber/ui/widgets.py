"""Small reusable UI primitives."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")


def page_header(title: str, subtitle: str = "") -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 8)
    layout.setSpacing(4)
    heading = QLabel(title)
    heading.setObjectName("PageTitle")
    layout.addWidget(heading)
    if subtitle:
        desc = QLabel(subtitle)
        desc.setObjectName("Muted")
        desc.setWordWrap(True)
        layout.addWidget(desc)
    return widget


def primary_button(label: str, parent=None) -> QPushButton:
    button = QPushButton(label, parent)
    button.setObjectName("Primary")
    button.setCursor(Qt.PointingHandCursor)
    return button


def labelled_value(label: str, value: str) -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    top = QLabel(label)
    top.setObjectName("Muted")
    bottom = QLabel(value)
    bottom.setWordWrap(True)
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
    label = QLabel(title)
    label.setObjectName("SectionTitle")
    layout.addWidget(label)
    layout.addStretch(1)
    if action is not None:
        layout.addWidget(action)
    return row
