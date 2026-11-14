"""Lightweight in-window overlays for search and command navigation."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QFrame, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget,
)


class GlobalSearchPopup(QFrame):
    result_activated = Signal(object)

    def __init__(self, parent: QWidget, provider):
        super().__init__(parent, Qt.Widget)
        self.setObjectName("GlobalSearchPopup")
        self.setFrameShape(QFrame.StyledPanel)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._provider = provider
        self._anchor = None
        self._recent: list[str] = []
        self._query = ""
        self._app_filter_installed = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.heading = QLabel("Search results")
        self.heading.setObjectName("Muted")
        layout.addWidget(self.heading)
        self.list_widget = QListWidget(self)
        self.list_widget.setFocusPolicy(Qt.NoFocus)
        self.list_widget.itemClicked.connect(self._activate_item)
        self.list_widget.itemActivated.connect(self._activate_item)
        layout.addWidget(self.list_widget)
        self.message = QLabel("")
        self.message.setObjectName("Muted")
        layout.addWidget(self.message)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(180)
        self._debounce.timeout.connect(self._search)
        self.hide()

    def open_for(self, anchor: QWidget, query: str):
        self._anchor = anchor
        self._query = str(query or "")
        self.reposition()
        self.show()
        self.raise_()
        if not self._app_filter_installed and QApplication.instance() is not None:
            QApplication.instance().installEventFilter(self)
            self._app_filter_installed = True
        self._debounce.start(0 if self._query.strip() else 1)

    def _search(self):
        query = self._query.strip()
        if not query:
            results = [
                {"kind": "recent", "title": value, "subtitle": "Recent search"}
                for value in reversed(self._recent[-8:])
            ]
        else:
            self.heading.setText("Searching…")
            try:
                results = list(self._provider(query) or [])
            except Exception as exc:
                self._render([], error=str(exc))
                return
        self._render(results)

    def _render(self, results, error=None):
        self.list_widget.clear()
        if error:
            self.heading.setText("Search unavailable")
            self.message.setText(error)
            return
        self.heading.setText("Search results" if self._query.strip() else "Recent searches")
        for result in results:
            title = str(result.get("title") or "Untitled")
            subtitle = str(result.get("subtitle") or result.get("kind") or "")
            item = QListWidgetItem(f"{title}   ·   {subtitle}")
            item.setData(Qt.UserRole, result)
            self.list_widget.addItem(item)
        self.message.setText("No results found" if not results and self._query.strip() else "")
        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)

    def reposition(self):
        if self._anchor is None or self.parentWidget() is None:
            return
        parent = self.parentWidget()
        anchor_pos = self._anchor.mapTo(parent, QPoint(0, self._anchor.height() + 4))
        width = min(560, max(320, parent.width() - 32))
        height = min(390, max(180, parent.height() - 40))
        x = min(max(16, anchor_pos.x()), max(16, parent.width() - width - 16))
        y = anchor_pos.y()
        if y + height > parent.height() - 16:
            y = max(16, anchor_pos.y() - height - self._anchor.height() - 8)
        self.setGeometry(x, y, width, height)

    def move_selection(self, amount: int):
        count = self.list_widget.count()
        if count:
            self.list_widget.setCurrentRow(max(0, min(count - 1, self.list_widget.currentRow() + amount)))

    def activate_current(self):
        item = self.list_widget.currentItem()
        if item is None and self.list_widget.count():
            item = self.list_widget.item(0)
        if item is not None:
            self._activate_item(item)

    def _activate_item(self, item):
        result = item.data(Qt.UserRole)
        if not isinstance(result, dict):
            return
        if self._query.strip() and self._query.strip() not in self._recent:
            self._recent.append(self._query.strip())
        self.hide()
        self.result_activated.emit(result)

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() in (QEvent.Resize, QEvent.Move):
            if self.isVisible():
                self.reposition()
        elif self.isVisible() and event.type() == QEvent.MouseButtonPress:
            widget = watched if isinstance(watched, QWidget) else None
            inside = widget is not None and (widget is self or self.isAncestorOf(widget))
            anchor = widget is not None and (
                widget is self._anchor
                or (self._anchor is not None and self._anchor.isAncestorOf(widget))
            )
            if not inside and not anchor:
                self.hide()
        return False

    def hideEvent(self, event):
        if self._app_filter_installed and QApplication.instance() is not None:
            QApplication.instance().removeEventFilter(self)
            self._app_filter_installed = False
        super().hideEvent(event)


class CommandPalettePopup(QFrame):
    command_activated = Signal(object)

    def __init__(self, parent: QWidget):
        super().__init__(parent, Qt.Widget)
        self.setObjectName("CommandPalettePopup")
        self.setFrameShape(QFrame.StyledPanel)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("Type a command or page…")
        self.search_input.textChanged.connect(self._filter)
        self.search_input.installEventFilter(self)
        layout.addWidget(self.search_input)
        self.list_widget = QListWidget(self)
        self.list_widget.itemActivated.connect(self._activate_item)
        self.list_widget.itemClicked.connect(self._activate_item)
        self.list_widget.installEventFilter(self)
        layout.addWidget(self.list_widget)
        self.hint = QLabel("↑ ↓ Navigate   Enter Run   Esc Close")
        self.hint.setObjectName("Muted")
        layout.addWidget(self.hint)
        self._commands: list[dict] = []
        self.hide()

    def open(self, commands):
        self._commands = list(commands or [])
        self.search_input.clear()
        self._filter("")
        parent = self.parentWidget()
        width = min(620, max(420, parent.width() - 48))
        height = min(480, max(260, parent.height() - 80))
        self.setGeometry(
            max(16, (parent.width() - width) // 2),
            max(16, (parent.height() - height) // 2),
            width, height,
        )
        self.show()
        self.raise_()
        self.search_input.setFocus()

    def _filter(self, query):
        normalized = str(query or "").casefold().strip()
        commands = [
            item for item in self._commands
            if not normalized or normalized in item["title"].casefold()
            or normalized in item["category"].casefold()
        ]
        self.list_widget.clear()
        for command in commands:
            shortcut = f"   [{command['shortcut']}]" if command.get("shortcut") else ""
            item = QListWidgetItem(f"{command['title']}{shortcut}   ·   {command['category']}")
            item.setData(Qt.UserRole, command)
            self.list_widget.addItem(item)
        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)
        self.hint.setText("↑ ↓ Navigate   Enter Run   Esc Close" if commands else "No matching commands")

    def _activate_item(self, item):
        command = item.data(Qt.UserRole)
        if isinstance(command, dict):
            self.hide()
            self.command_activated.emit(command)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape:
                self.hide()
                return True
            if watched is self.search_input and event.key() == Qt.Key_Down and self.list_widget.count():
                self.list_widget.setFocus()
                self.list_widget.setCurrentRow(0)
                return True
            if watched is self.list_widget and event.key() in (Qt.Key_Return, Qt.Key_Enter):
                item = self.list_widget.currentItem()
                if item:
                    self._activate_item(item)
                return True
        return super().eventFilter(watched, event)
