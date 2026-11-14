"""Single source of truth for applying the selected application theme."""

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from transcriber.ui.theme import stylesheet


class ThemeManager(QObject):
    changed = Signal(str)

    def __init__(self, theme: str = "dark", parent=None):
        super().__init__(parent)
        self.theme = "light" if theme == "light" else "dark"

    def apply(self, theme: str) -> None:
        normalized = "light" if theme == "light" else "dark"
        self.theme = normalized
        app = QApplication.instance()
        if app:
            app.setStyleSheet(stylesheet(normalized))
        self.changed.emit(normalized)
