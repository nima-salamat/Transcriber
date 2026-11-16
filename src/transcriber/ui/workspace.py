"""Unified transcription workspace and compact tool switcher.

The workspace keeps the primary transcription workflow in one window.  The
individual feature widgets remain separate, reusable components, but users no
longer need to navigate through a permanent application sidebar.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class UnifiedWorkspace(QWidget):
    """One coherent work surface for transcript, audio and supporting tools."""

    action_requested = Signal(str)
    view_changed = Signal(str)

    VIEW_INDEX = {
        "transcription": 0,
        "editor": 1,
        "subtitles": 2,
        "recording": 3,
        "batch": 4,
        "history": 5,
        "audio": 5,
        "cleanup": 6,
    }

    def __init__(
        self,
        transcription_page: QWidget,
        editor_page: QWidget,
        subtitle_page: QWidget,
        recording_page: QWidget,
        batch_page: QWidget,
        history_page: QWidget,
        audio_page: QWidget,
        cleanup_page: QWidget,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("UnifiedWorkspace")
        self._current_media = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 12, 18, 12)
        root.setSpacing(10)

        self.header = QFrame(self)
        self.header.setObjectName("WorkspaceHeader")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(2, 2, 2, 2)
        header_layout.setSpacing(10)

        identity = QVBoxLayout()
        identity.setSpacing(2)
        self.document_title = QLabel("No media selected", self.header)
        self.document_title.setObjectName("WorkspaceDocumentTitle")
        self.document_subtitle = QLabel(
            "Open an audio or video file, or start a recording.",
            self.header,
        )
        self.document_subtitle.setObjectName("Muted")
        self.document_subtitle.setWordWrap(True)
        identity.addWidget(self.document_title)
        identity.addWidget(self.document_subtitle)
        header_layout.addLayout(identity, 1)

        self._buttons: dict[str, object] = {}
        primary_actions = (
            ("record", "Record", "Open the microphone recording workspace"),
            ("batch", "Batch", "Process a group of media files"),
            ("library", "Library", "Browse projects and local recordings"),
            ("export", "Export", "Export the current transcript or captions"),
        )
        for key, label, tooltip in primary_actions:
            button = QPushButton(label, self.header)
            button.setObjectName("WorkspaceToolButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(tooltip)
            button.setAccessibleName(label)
            button.clicked.connect(
                lambda _checked=False, action=key: self.action_requested.emit(action)
            )
            self._buttons[key] = button
            header_layout.addWidget(button)

        more_button = QToolButton(self.header)
        more_button.setText("More")
        more_button.setObjectName("WorkspaceToolButton")
        more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more_button.setToolTip("Advanced and less frequently used tools")
        more_button.setAccessibleName("More workspace tools")
        more_menu = QMenu(more_button)
        for key, label in (
            ("cleanup", "Audio cleanup"),
            ("models", "Manage models…"),
            ("settings", "Preferences…"),
        ):
            action = more_menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, item=key: self.action_requested.emit(item)
            )
            self._buttons[key] = action
        more_button.setMenu(more_menu)
        self._buttons["more"] = more_button
        header_layout.addWidget(more_button)

        root.addWidget(self.header)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("UnifiedWorkspaceTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(False)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.addTab(transcription_page, "Transcribe")
        self.tabs.addTab(editor_page, "Segments")
        self.tabs.addTab(subtitle_page, "Captions")
        self.tabs.addTab(recording_page, "Record")
        self.tabs.addTab(batch_page, "Batch")

        self.library_tabs = QTabWidget(self.tabs)
        self.library_tabs.setObjectName("LibraryViews")
        self.library_tabs.setDocumentMode(True)
        self.library_tabs.addTab(history_page, "Projects")
        self.library_tabs.addTab(audio_page, "Recordings")
        self.tabs.addTab(self.library_tabs, "Library")

        self.tabs.addTab(cleanup_page, "Audio cleanup")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.library_tabs.currentChanged.connect(self._on_library_view_changed)
        root.addWidget(self.tabs, 1)

    def _on_tab_changed(self, index: int) -> None:
        if index == 5:
            self._on_library_view_changed(self.library_tabs.currentIndex())
            return
        names = {
            0: "transcription",
            1: "editor",
            2: "subtitles",
            3: "recording",
            4: "batch",
            6: "cleanup",
        }
        self.view_changed.emit(names.get(index, "transcription"))

    def _on_library_view_changed(self, index: int) -> None:
        if self.tabs.currentIndex() == 5:
            self.view_changed.emit("audio" if index == 1 else "history")

    def set_view(self, view: str) -> None:
        index = self.VIEW_INDEX.get(str(view), 0)
        self.tabs.setCurrentIndex(index)
        if view == "audio":
            self.library_tabs.setCurrentIndex(1)
        elif view == "history":
            self.library_tabs.setCurrentIndex(0)

    def set_media(self, path: str | Path | None) -> None:
        self._current_media = str(path or "")
        if not self._current_media:
            self.document_title.setText("No media selected")
            self.document_subtitle.setText(
                "Open an audio or video file, or start a recording."
            )
            return
        name = Path(self._current_media).name
        self.document_title.setText(name)
        self.document_title.setToolTip(self._current_media)
        self.document_subtitle.setText("Local workspace · edits are autosaved")

    @property
    def current_view(self) -> str:
        index = self.tabs.currentIndex()
        if index == 5 and self.library_tabs.currentIndex() == 1:
            return "audio"
        return {
            0: "transcription",
            1: "editor",
            2: "subtitles",
            3: "recording",
            4: "batch",
            5: "history",
            6: "cleanup",
        }.get(index, "transcription")

    def button(self, action: str):
        """Return a toolbar button or a More-menu action for UI tests/integration."""
        return self._buttons.get(action)

    def trigger(self, action: str) -> bool:
        control = self._buttons.get(action)
        if control is None:
            return False
        trigger = getattr(control, "trigger", None)
        if callable(trigger):
            trigger()
            return True
        click = getattr(control, "click", None)
        if callable(click):
            click()
            return True
        return False
