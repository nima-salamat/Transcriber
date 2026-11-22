"""Single source of truth for applying the selected application theme."""

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from transcriber.ui.theme import stylesheet


class ThemeManager(QObject):
    changed = Signal(str)

    def __init__(self, theme: str = "light", parent=None):
        super().__init__(parent)
        self.theme = "dark" if theme == "dark" else "light"

    def apply(self, theme: str) -> None:
        normalized = "dark" if theme == "dark" else "light"
        self.theme = normalized
        app = QApplication.instance()
        if app:
            app.setStyleSheet(stylesheet(normalized))
        self.changed.emit(normalized)
