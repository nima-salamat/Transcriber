"""Conversation navigation and local history search for the AI workspace."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QVBoxLayout


class AssistantSidebar(QFrame):
    """Own the conversation-list UI; delegate persistence to ChatSessionStore."""
    new_chat_requested = Signal()
    session_selected = Signal(str)
    rename_requested = Signal(str, str)
    delete_requested = Signal(str)
    skills_requested = Signal()
    settings_requested = Signal()
    SESSION_ROLE = Qt.ItemDataRole.UserRole
    HEADER_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(self, session_store, icons, parent=None):
        super().__init__(parent)
        self.session_store = session_store
        self.icons = icons
        self._active_session_id = ""
        self._collapsed = False
        self._all_sessions: list[dict[str, Any]] = []
        self.setObjectName("AssistantSidebar")
        self.setMinimumWidth(232)
        self.setMaximumWidth(292)
        self.setFixedWidth(264)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(10)

        brand_row = QHBoxLayout()
        self.brand_label = QLabel("Transcriber")
        self.brand_label.setObjectName("AssistantBrand")
        brand_row.addWidget(self.brand_label, 1)
        self.collapse_button = QPushButton("‹")
        self.collapse_button.setObjectName("AssistantIconButton")
        self.collapse_button.setFixedSize(30, 30)
        self.collapse_button.setToolTip("Collapse conversation sidebar")
        self.collapse_button.setAccessibleName("Collapse conversation sidebar")
        self.collapse_button.clicked.connect(self.toggle_collapsed)
        brand_row.addWidget(self.collapse_button)
        layout.addLayout(brand_row)

        self.new_chat_button = QPushButton("New chat")
        self.new_chat_button.setObjectName("AssistantNewChatButton")
        self.new_chat_button.setIcon(icons.icon("new_chat", size=17))
        self.new_chat_button.setMinimumHeight(40)
        self.new_chat_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_chat_button.setAccessibleName("Create a new conversation")
        self.new_chat_button.clicked.connect(self.new_chat_requested.emit)
        layout.addWidget(self.new_chat_button)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("AssistantHistorySearch")
        self.search_input.setPlaceholderText("Search conversations")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setToolTip("Search saved conversation titles and messages")
        self.search_input.setAccessibleName("Search conversation history")
        layout.addWidget(self.search_input)

        self.search_status = QLabel("")
        self.search_status.setObjectName("Muted")
        self.search_status.hide()
        layout.addWidget(self.search_status)

        self.session_list = QListWidget()
        self.session_list.setObjectName("AssistantSessionList")
        self.session_list.setSpacing(1)
        self.session_list.setUniformItemSizes(False)
        self.session_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.session_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.session_list.setAccessibleName("Saved conversations")
        self.session_list.itemClicked.connect(self._on_item_clicked)
        self.session_list.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.session_list, 1)

        self.empty_state = QLabel("No conversations found")
        self.empty_state.setObjectName("AssistantSidebarEmpty")
        self.empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state.setWordWrap(True)
        self.empty_state.hide()
        layout.addWidget(self.empty_state)

        footer = QFrame()
        footer.setObjectName("AssistantSidebarFooter")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(0, 8, 0, 0)
        footer_layout.setSpacing(5)
        self.provider_label = QLabel("Provider details appear in the chat header")
        self.provider_label.setObjectName("Muted")
        self.provider_label.setWordWrap(True)
        footer_layout.addWidget(self.provider_label)
        self.skills_button = QPushButton("Agent Skills")
        self.skills_button.setObjectName("AssistantSidebarAction")
        self.skills_button.setIcon(icons.icon("skills", size=16))
        self.skills_button.clicked.connect(self.skills_requested.emit)
        footer_layout.addWidget(self.skills_button)
        self.settings_button = QPushButton("Assistant settings")
        self.settings_button.setObjectName("AssistantSidebarAction")
        self.settings_button.setIcon(icons.icon("settings", size=16))
        self.settings_button.clicked.connect(self.settings_requested.emit)
        footer_layout.addWidget(self.settings_button)
        layout.addWidget(footer)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self._apply_filter)
        self.search_input.textChanged.connect(lambda _text: self._search_timer.start())
        self.refresh_sessions()

    @staticmethod
    def _updated_at(session: dict[str, Any]) -> datetime:
        raw = str(session.get("updated_at") or "")
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if value.tzinfo is None:
                value = value.astimezone()
            return value.astimezone()
        except (ValueError, TypeError):
            return datetime.fromtimestamp(0).astimezone()

    @classmethod
    def _group_for(cls, session: dict[str, Any], now: datetime) -> str:
        stamp = cls._updated_at(session)
        if stamp.date() == now.date():
            return "Today"
        if stamp.date() == now.date() - timedelta(days=1):
            return "Yesterday"
        if stamp >= now - timedelta(days=7):
            return "Previous 7 days"
        return "Older"

    def refresh_sessions(self, active_id: str | None = None):
        self._all_sessions = self.session_store.list_sessions()
        self._active_session_id = str(active_id if active_id is not None else self.session_store.active_session_id or "")
        self._apply_filter()

    def _apply_filter(self):
        query = self.search_input.text().strip().casefold()
        sessions = self._all_sessions
        if query:
            terms = [part for part in query.split() if part]
            sessions = [
                session for session in sessions
                if all(term in (
                    str(session.get("title") or "").casefold() + "\n" +
                    "\n".join(str(m.get("text") or "") for m in (session.get("messages") or []) if isinstance(m, dict)).casefold()
                ) for term in terms)
            ]

        self.session_list.blockSignals(True)
        self.session_list.clear()
        now = datetime.now().astimezone()
        groups = {"Today": [], "Yesterday": [], "Previous 7 days": [], "Older": []}
        for session in sessions:
            groups[self._group_for(session, now)].append(session)
        selected = None
        for group_name, entries in groups.items():
            if not entries:
                continue
            heading = QListWidgetItem(group_name.upper())
            heading.setData(self.HEADER_ROLE, True)
            heading.setFlags(Qt.ItemFlag.NoItemFlags)
            self.session_list.addItem(heading)
            for session in entries:
                title = str(session.get("title") or "New chat")
                provider = "Ollama" if session.get("provider") == "ollama" else "OpenCode"
                item = QListWidgetItem(title)
                item.setData(self.SESSION_ROLE, str(session.get("id") or ""))
                item.setToolTip(f"{title}\n{provider} · {self._updated_at(session).strftime('%Y-%m-%d %H:%M')}")
                self.session_list.addItem(item)
                if session.get("id") == self._active_session_id:
                    selected = item
        self.session_list.blockSignals(False)
        if selected is not None:
            self.session_list.setCurrentItem(selected)
        self.session_list.setVisible(bool(sessions))
        self.empty_state.setVisible(not bool(sessions))
        if query:
            self.search_status.setText(f"{len(sessions)} matching conversation(s)")
            self.search_status.show()
        else:
            self.search_status.hide()

    def _on_item_clicked(self, item: QListWidgetItem):
        session_id = str(item.data(self.SESSION_ROLE) or "")
        if session_id:
            self.session_selected.emit(session_id)

    def _show_context_menu(self, position):
        item = self.session_list.itemAt(position)
        session_id = str(item.data(self.SESSION_ROLE) or "") if item else ""
        if not session_id:
            return
        session = self.session_store.get_session(session_id) or {}
        menu = QMenu(self)
        rename_action = menu.addAction("Rename conversation")
        delete_action = menu.addAction("Delete conversation")
        chosen = menu.exec(self.session_list.viewport().mapToGlobal(position))
        if chosen is rename_action:
            value, accepted = QInputDialog.getText(
                self, "Rename conversation", "Conversation title:",
                text=str(session.get("title") or "New chat")
            )
            if accepted and value.strip():
                self.rename_requested.emit(session_id, value.strip())
        elif chosen is delete_action:
            answer = QMessageBox.question(
                self, "Delete conversation",
                "Delete this locally saved conversation? This cannot be undone.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.delete_requested.emit(session_id)

    def toggle_collapsed(self):
        self._collapsed = not self._collapsed
        if self._collapsed:
            self.setFixedWidth(62)
            self.brand_label.hide()
            self.collapse_button.setText("›")
            self.collapse_button.setToolTip("Expand conversation sidebar")
            self.new_chat_button.setText("")
            self.new_chat_button.setToolTip("New chat")
            self.search_input.hide()
            self.search_status.hide()
            self.session_list.hide()
            self.empty_state.hide()
            self.provider_label.hide()
            self.skills_button.setText("")
            self.skills_button.setToolTip("Agent Skills")
            self.settings_button.setText("")
            self.settings_button.setToolTip("Assistant settings")
        else:
            self.setFixedWidth(264)
            self.brand_label.show()
            self.collapse_button.setText("‹")
            self.collapse_button.setToolTip("Collapse conversation sidebar")
            self.new_chat_button.setText("New chat")
            self.new_chat_button.setToolTip("Create a new conversation")
            self.search_input.show()
            self.session_list.setVisible(self.session_list.count() > 0)
            self.empty_state.setVisible(self.session_list.count() == 0)
            self.provider_label.show()
            self.skills_button.setText("Agent Skills")
            self.settings_button.setText("Assistant settings")
            self._apply_filter()

    def set_provider_summary(self, text: str):
        self.provider_label.setText(str(text or ""))
