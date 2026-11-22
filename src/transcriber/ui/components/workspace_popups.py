"""Lightweight in-window overlays for search and command navigation."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)


class CommandPalettePopup(QFrame):
    """One searchable result list for workspace commands and transcript matches."""

    command_activated = Signal(object)

    def __init__(self, parent: QWidget):
        super().__init__(parent, Qt.Widget)
        self.setObjectName("CommandPalettePopup")
        self.setFrameShape(QFrame.StyledPanel)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumWidth(0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self.search_input = QLineEdit(self)
        self.search_input.setObjectName("CommandPaletteSearch")
        self.search_input.setPlaceholderText(
            "Search commands, pages, transcripts and settings…"
        )
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._filter)
        self.search_input.installEventFilter(self)
        layout.addWidget(self.search_input)
        self.list_widget = QListWidget(self)
        self.list_widget.setObjectName("CommandPaletteResults")
        self.list_widget.itemActivated.connect(self._activate_item)
        self.list_widget.itemClicked.connect(self._activate_item)
        self.list_widget.installEventFilter(self)
        layout.addWidget(self.list_widget, 1)
        self.hint = QLabel("↑ ↓ Navigate   Enter Open   Esc Close")
        self.hint.setObjectName("Muted")
        layout.addWidget(self.hint)
        self._commands: list[dict] = []
        self._search_provider = None
        self._query = ""
        self.hide()

    def open(self, commands, *, search_provider=None, initial_query=""):
        self._commands = list(commands or [])
        self._search_provider = search_provider
        self._query = str(initial_query or "")
        self.search_input.setText(self._query)
        self._filter(self._query)
        parent = self.parentWidget()
        width = min(700, max(320, parent.width() - 32))
        height = min(520, max(240, parent.height() - 56))
        self.setGeometry(
            max(16, (parent.width() - width) // 2),
            max(16, (parent.height() - height) // 2),
            width,
            height,
        )
        self.show()
        self.raise_()
        self.search_input.setFocus()
        self.search_input.selectAll()

    @staticmethod
    def _score(item: dict, query: str) -> int:
        title = str(item.get("title") or "")
        category = str(item.get("category") or "")
        folded = title.casefold()
        if not query:
            return 0
        if folded == query:
            return 0
        if folded.startswith(query):
            return 1
        if query in folded:
            return 2
        if query in category.casefold():
            return 3
        return 4

    def _filter(self, query):
        normalized = str(query or "").casefold().strip()
        self._query = str(query or "").strip()
        tokens = normalized.split()
        matches = []
        seen = set()

        for index, command in enumerate(self._commands):
            searchable = " ".join(
                str(command.get(key) or "")
                for key in ("title", "category", "keywords", "description", "shortcut")
            ).casefold()
            if tokens and not all(token in searchable for token in tokens):
                continue
            kind = str(command.get("kind") or "command")
            identity = (
                ("command", str(command.get("title") or "").casefold())
                if kind == "command"
                else (kind, str(command.get("id") or command.get("title") or ""))
            )
            if identity in seen:
                continue
            seen.add(identity)
            matches.append((self._score(command, normalized), index, command))

        search_error = ""
        if normalized and callable(self._search_provider):
            try:
                found = list(self._search_provider(self._query) or [])
            except Exception as exc:
                found = []
                search_error = str(exc)
            offset = len(self._commands)
            for index, result in enumerate(found):
                if not isinstance(result, dict):
                    continue
                identity = (
                    str(result.get("kind") or "result"),
                    str(result.get("id") or result.get("title") or ""),
                )
                if identity in seen:
                    continue
                seen.add(identity)
                matches.append((self._score(result, normalized), offset + index, result))

        matches.sort(key=lambda entry: (entry[0], entry[1]))
        results = [entry[2] for entry in matches]
        self.list_widget.clear()
        for result in results:
            title = str(result.get("title") or "Untitled")
            category = str(
                result.get("category")
                or ("Transcripts" if result.get("kind") == "transcript" else "Command")
            )
            shortcut = f"   [{result['shortcut']}]" if result.get("shortcut") else ""
            item = QListWidgetItem(f"{title}{shortcut}   ·   {category}")
            item.setToolTip(str(
                result.get("description")
                or result.get("keywords")
                or result.get("subtitle")
                or ""
            ))
            item.setData(Qt.UserRole, result)
            self.list_widget.addItem(item)

        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)
        if search_error:
            self.hint.setText(
                f"{len(results)} result(s) · Transcript lookup unavailable: {search_error}"
            )
        elif results:
            self.hint.setText(
                f"{len(results)} result(s) · ↑ ↓ Navigate · Enter Open · Esc Close"
            )
        else:
            self.hint.setText(
                "No matching commands, pages or transcripts"
                if normalized else "Start typing to search commands, pages and transcripts"
            )

    def _activate_item(self, item):
        result = item.data(Qt.UserRole)
        if not isinstance(result, dict):
            return
        if result.get("kind") == "transcript" and self._query:
            result = {**result, "search_query": self._query}
        self.hide()
        self.command_activated.emit(result)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape:
                self.hide()
                return True
            if (
                watched is self.search_input
                and event.key() == Qt.Key_Down
                and self.list_widget.count()
            ):
                self.list_widget.setFocus()
                self.list_widget.setCurrentRow(0)
                return True
            if watched is self.list_widget and event.key() in (Qt.Key_Return, Qt.Key_Enter):
                item = self.list_widget.currentItem()
                if item:
                    self._activate_item(item)
                return True
        return super().eventFilter(watched, event)
