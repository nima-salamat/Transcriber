"""Conversation navigation and local history search for the AI workspace."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class _SessionHistoryRow(QWidget):
    """Compact two-line session label that elides text to the available pixel width."""

    def __init__(self, title: str, preview: str, parent=None):
        super().__init__(parent)
        self.setObjectName("AssistantSessionRow")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._full_title = ""
        self._full_preview = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 3, 2, 3)
        layout.setSpacing(2)
        self.title_label = QLabel()
        self.title_label.setObjectName("AssistantSessionTitle")
        self.title_label.setMinimumWidth(0)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.preview_label = QLabel()
        self.preview_label.setObjectName("AssistantSessionPreview")
        self.preview_label.setMinimumWidth(0)
        self.preview_label.setMinimumHeight(14)
        self.preview_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.title_label)
        layout.addWidget(self.preview_label)
        self.set_content(title, preview)

    @staticmethod
    def _character_limit(value: str, limit: int) -> str:
        text = " ".join(str(value or "").split())
        return text if len(text) <= limit else text[:limit].rstrip() + "…"

    def set_content(self, title: str, preview: str):
        self._full_title = self._character_limit(title, 64)
        self._full_preview = self._character_limit(preview, 112)
        self.setToolTip("\n".join(part for part in (title, preview) if part))
        self._refresh_elision()

    def _refresh_elision(self):
        title_width = max(0, self.title_label.contentsRect().width())
        preview_width = max(0, self.preview_label.contentsRect().width())
        self.title_label.setText(
            QFontMetrics(self.title_label.font()).elidedText(
                self._full_title, Qt.TextElideMode.ElideRight, title_width
            )
        )
        self.preview_label.setText(
            QFontMetrics(self.preview_label.font()).elidedText(
                self._full_preview, Qt.TextElideMode.ElideRight, preview_width
            ) if self._full_preview else " "
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_elision()


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
        self.brand_label = QLabel()
        self.brand_label.setObjectName("AssistantBrandIcon")
        self.brand_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.brand_label.setPixmap(icons.icon("assistant", size=24).pixmap(24, 24))
        self.brand_label.setFixedSize(32, 32)
        self.brand_label.setToolTip("AI Assistant")
        self.brand_label.setAccessibleName("AI Assistant")
        brand_row.addWidget(self.brand_label, 0)
        brand_row.addStretch(1)
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

        # When the history is hidden in collapsed mode, this spacer takes its
        # place so the Skills and Settings actions stay anchored to the bottom.
        self.footer_spacer = QWidget(self)
        self.footer_spacer.setObjectName("AssistantSidebarFooterSpacer")
        self.footer_spacer.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding
        )
        self.footer_spacer.hide()
        layout.addWidget(self.footer_spacer, 1)

        footer = QFrame()
        footer.setObjectName("AssistantSidebarFooter")
        self.footer = footer
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

    @staticmethod
    def _display_title(session: dict[str, Any]) -> str:
        metadata = session.get("metadata") or {}
        custom_title = str(metadata.get("custom_title") or "").strip()
        if custom_title:
            return custom_title[:120]
        saved_title = str(session.get("title") or "").strip()
        if saved_title and saved_title.casefold() != "new chat":
            return saved_title[:120]
        for message in session.get("messages") or []:
            if isinstance(message, dict) and message.get("role") == "user":
                prompt = " ".join(str(message.get("text") or "").split())
                if prompt:
                    return prompt[:44] + ("…" if len(prompt) > 44 else "")
        return "New chat"

    @classmethod
    def _display_preview(cls, session: dict[str, Any]) -> str:
        preview = ""
        for message in reversed(session.get("messages") or []):
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            preview = " ".join(str(message.get("text") or "").split())
            if preview:
                break
        if not preview:
            return ""
        title = cls._display_title(session)
        metadata = session.get("metadata") or {}
        # The default title is generated from the first user prompt; avoid duplicating it.
        if not str(metadata.get("custom_title") or "").strip():
            comparable_title = title[:-1] if title.endswith("…") else title
            if preview == comparable_title or (
                title.endswith("…") and preview.startswith(comparable_title)
            ):
                return ""
        return preview[:112] + ("…" if len(preview) > 112 else "")

    def update_session_title(
        self, session_id: str, title: str, *, messages=None, updated_at: str | None = None
    ):
        """Refresh the current row and move it when its message activity becomes newest."""
        identifier = str(session_id or "")
        if not identifier:
            return
        clean_title = str(title or "New chat")
        old_order = [str(item.get("id") or "") for item in self._all_sessions]
        target = None
        for session in self._all_sessions:
            if str(session.get("id") or "") == identifier:
                target = session
                session["title"] = clean_title
                if messages is not None:
                    session["messages"] = [
                        dict(item) for item in messages if isinstance(item, dict)
                    ]
                if updated_at:
                    session["updated_at"] = str(updated_at)
                break
        if target is None:
            return

        self._all_sessions.sort(key=self._updated_at, reverse=True)
        new_order = [str(item.get("id") or "") for item in self._all_sessions]
        if old_order != new_order:
            self._apply_filter()
            return

        for index in range(self.session_list.count()):
            item = self.session_list.item(index)
            if str(item.data(self.SESSION_ROLE) or "") == identifier:
                item.setData(Qt.ItemDataRole.AccessibleTextRole, clean_title)
                row = self.session_list.itemWidget(item)
                if isinstance(row, _SessionHistoryRow):
                    preview = self._display_preview(target)
                    row.set_content(clean_title, preview)
                    item.setToolTip(
                        f"{clean_title}" + (f"\n{preview}" if preview else "") +
                        f"\n{self._updated_at(target).strftime('%Y-%m-%d %H:%M')}"
                    )
                break

    def set_active_session(self, session_id: str):
        """Change active highlighting without rebuilding the history list."""
        self._active_session_id = str(session_id or "")
        self.session_list.blockSignals(True)
        try:
            for index in range(self.session_list.count()):
                item = self.session_list.item(index)
                if str(item.data(self.SESSION_ROLE) or "") == self._active_session_id:
                    self.session_list.setCurrentItem(item)
                    break
        finally:
            self.session_list.blockSignals(False)

    def _apply_filter(self):
        query = self.search_input.text().strip().casefold()
        sessions = self._all_sessions
        if query:
            terms = [part for part in query.split() if part]
            sessions = [
                session for session in sessions
                if all(term in (
                    self._display_title(session).casefold() + "\n" +
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
                title = self._display_title(session)
                provider = "Ollama" if session.get("provider") == "ollama" else "OpenCode"
                preview = self._display_preview(session)
                # The row widget renders the title/preview itself. Keep the
                # QListWidgetItem text empty so the delegate cannot paint a
                # second copy through the row's transparent background.
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.AccessibleTextRole, title)
                item.setSizeHint(QSize(0, 66))
                item.setData(self.SESSION_ROLE, str(session.get("id") or ""))
                item.setToolTip(
                    f"{title}" + (f"\n{preview}" if preview else "") +
                    f"\n{provider} · {self._updated_at(session).strftime('%Y-%m-%d %H:%M')}"
                )
                self.session_list.addItem(item)
                self.session_list.setItemWidget(
                    item, _SessionHistoryRow(title, preview, self.session_list)
                )
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
            self.footer_spacer.show()
            self.provider_label.hide()
            for button, tooltip in (
                (self.skills_button, "Agent Skills"),
                (self.settings_button, "Assistant settings"),
            ):
                button.setText("")
                button.setToolTip(tooltip)
                button.setFixedSize(38, 38)
                button.setProperty("collapsed", True)
                button.style().unpolish(button)
                button.style().polish(button)
        else:
            self.setFixedWidth(264)
            self.brand_label.show()
            self.collapse_button.setText("‹")
            self.collapse_button.setToolTip("Collapse conversation sidebar")
            self.new_chat_button.setText("New chat")
            self.new_chat_button.setToolTip("Create a new conversation")
            self.search_input.show()
            self.footer_spacer.hide()
            self.session_list.setVisible(self.session_list.count() > 0)
            self.empty_state.setVisible(self.session_list.count() == 0)
            self.provider_label.show()
            for button, label in (
                (self.skills_button, "Agent Skills"),
                (self.settings_button, "Assistant settings"),
            ):
                button.setText(label)
                button.setMinimumSize(0, 36)
                button.setMaximumSize(16777215, 16777215)
                button.setProperty("collapsed", False)
                button.style().unpolish(button)
                button.style().polish(button)
            self._apply_filter()

    def set_provider_summary(self, text: str):
        self.provider_label.setText(str(text or ""))
