"""Native-window application shell and navigation."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from concurrent.futures import CancelledError, Future
from pathlib import Path
from threading import Event

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QThread, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from transcriber.assistant.action_registry import ActionRegistry, ActionSpec
from transcriber.assistant.browser import WindowsBrowserController
from transcriber.assistant.operations import OperationManager
from transcriber.assistant.permissions import AgentPermission, PermissionDenied
from transcriber.audio.decoder import validate_audio_file
from transcriber.audio.waveform import build_waveform
from transcriber.editor.commands import CommandHistory
from transcriber.editor.document import TranscriptDocument
from transcriber.ipc.server import LocalIPCServer
from transcriber.storage.recordings import RecordingRepository
from transcriber.transcription.segments import TranscriptionOptions
from transcriber.ui.components.assistant_panel import AssistantPanel
from transcriber.ui.components.waveform import WaveformTimeline
from transcriber.ui.components.workspace_popups import CommandPalettePopup, GlobalSearchPopup
from transcriber.ui.design.icon_registry import IconRegistry
from transcriber.ui.pages.audio_cleanup import AudioCleanupPage
from transcriber.ui.pages.audio_library import AudioLibraryPage
from transcriber.ui.pages.batch_processing import BatchProcessingPage
from transcriber.ui.pages.history import HistoryPage
from transcriber.ui.pages.home import HomePage
from transcriber.ui.pages.models import ModelLibraryPage
from transcriber.ui.pages.recording import RecordingPage
from transcriber.ui.pages.settings import SettingsPage
from transcriber.ui.pages.subtitle_studio import SubtitleStudioPage
from transcriber.ui.pages.transcript_editor import TranscriptEditorPage
from transcriber.ui.pages.transcription import TranscriptionPage
from transcriber.ui.theme import stylesheet
from transcriber.ui.workers import FunctionWorker


class MainThreadDispatcher(QObject):
    """Serialize Agent/MCP requests onto the Qt GUI thread without touching widgets remotely."""

    invoke = Signal(object, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.invoke.connect(self._execute, Qt.QueuedConnection)

    def __call__(self, handler, arguments, cancel_event=None):
        if QThread.currentThread() == self.thread():
            if cancel_event and cancel_event.is_set():
                raise CancelledError("GUI action was cancelled before execution.")
            return handler(arguments)
        future = Future()
        self.invoke.emit(handler, arguments, future)
        if cancel_event is not None:
            # Cancellation while the callback is still queued prevents it from
            # running. A callback already executing is allowed to finish; the
            # ActionRegistry checks cancellation after approval and before the
            # actual action handler.
            while True:
                if cancel_event.is_set() and future.cancel():
                    raise CancelledError("GUI action was cancelled before dispatch.")
                try:
                    return future.result(timeout=0.05)
                except TimeoutError:
                    continue
        try:
            return future.result(timeout=20)
        except TimeoutError as exc:
            if future.cancel():
                raise TimeoutError(
                    "GUI action timed out before execution and was cancelled."
                ) from exc
            raise TimeoutError(
                "GUI action is already running; check the operation status before retrying."
            ) from exc

    @staticmethod
    def _execute(handler, arguments, future):
        # Atomically move PENDING -> RUNNING or abort if the caller timed out
        # and cancelled while the callback was still queued.
        if not future.set_running_or_notify_cancel():
            return
        try:
            result = handler(arguments)
        except BaseException as exc:
            future.set_exception(exc)
        else:
            future.set_result(result)


class MainWindow(QMainWindow):
    NAVIGATION = [
        ("home", "home", "Home"),
        ("assistant", "assistant", "AI Assistant"),
        ("transcription", "projects", "New transcription"),
        ("recording", "record", "Record audio"),
        ("batch", "activity", "Batch processing"),
        ("history", "projects", "Projects"),
        ("editor", "controls", "Transcript editor"),
        ("subtitles", "activity", "Subtitles & timing"),
        ("models", "models", "AI models"),
        ("audio", "projects", "Audio library"),
        ("cleanup", "controls", "Audio cleanup"),
        ("settings", "settings", "Settings"),
    ]

    def __init__(self, paths, settings_store, history, database, model_manager, recording_history=None):
        super().__init__()
        # Drawer splitters and edge anchors must keep physical left/right semantics even
        # when the host OS locale makes QApplication default to right-to-left.
        self.setLayoutDirection(Qt.LeftToRight)
        self.paths = paths
        self.settings_store = settings_store
        self.history = history
        self.database = database
        self.model_manager = model_manager
        self.recording_history = recording_history or RecordingRepository(database)
        # One domain document is shared by transcription and segment editing.
        self.transcript_document = TranscriptDocument()
        self.transcript_history = CommandHistory(self.transcript_document)
        self._sidebar_collapsed = False
        self.thread_pool = QThreadPool(self)
        self.icon_registry = IconRegistry()
        self.dispatcher = MainThreadDispatcher(self)
        configured_permissions = set()
        for value in settings_store.settings.agent_permissions or []:
            try:
                configured_permissions.add(AgentPermission(value))
            except ValueError:
                continue
        self.action_registry = ActionRegistry(
            permissions=configured_permissions,
            dispatcher=self.dispatcher, approval=self._approve_agent_action,
        )
        self._waveform_generation = 0
        self.thread_pool.setMaxThreadCount(max(2, min(8, settings_store.settings.download_concurrency + 2)))
        self.setWindowTitle("Transcriber")
        self.setMinimumSize(760, 500)
        self.setAcceptDrops(True)
        self._build_ui()
        self._connect_pages()
        self._register_agent_actions()
        self.assistant_panel.set_agent_runtime(self.action_registry)
        self.operation_manager = OperationManager(self.action_registry.execute)
        self._start_local_ipc()
        self._restore_geometry()
        self.apply_theme(settings_store.settings.theme)
        if settings_store.settings.sidebar_collapsed:
            self.toggle_sidebar()
        self.navigate(settings_store.settings.last_page)
        self._shortcuts()

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("Root")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setMinimumWidth(190)
        sidebar.setMaximumWidth(230)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(15, 22, 15, 16)
        side_layout.setSpacing(6)
        brand = QHBoxLayout()
        mark = QLabel("T")
        mark.setStyleSheet("font-size: 22px; color: #75a7ff; font-weight: 800;")
        self.brand_name = QLabel("Transcriber")
        self.brand_name.setStyleSheet("font-size: 18px; font-weight: 700;")
        brand.addWidget(mark)
        brand.addWidget(self.brand_name)
        brand.addStretch(1)
        side_layout.addLayout(brand)
        self.tagline = QLabel("VOICE  /  TEXT  /  LOCAL AI")
        self.tagline.setObjectName("Muted")
        self.tagline.setStyleSheet("font-size: 9px; letter-spacing: 1px; margin: 2px 0 18px 3px;")
        side_layout.addWidget(self.tagline)
        self.nav_buttons: dict[str, QPushButton] = {}
        for key, icon_name, title in self.NAVIGATION:
            button = QPushButton(title)
            button.setObjectName("Nav")
            button.setIcon(self.icon_registry.icon(icon_name, size=18))
            button.setIconSize(__import__("PySide6.QtCore", fromlist=["QSize"]).QSize(18, 18))
            button.setToolTip({
                "Record audio": "Capture and save a microphone recording; this page does not perform live transcription.",
                "Transcript editor": "Correct recognized words, speakers and timed transcript segments.",
                "Subtitles & timing": "Edit subtitle cues, validate readability and export subtitle files.",
                "AI models": "Discover, install and manage local speech-recognition models.",
            }.get(title, title))
            button.setCheckable(True)
            button.setMinimumHeight(40)
            button.clicked.connect(lambda _checked=False, page=key: self.navigate(page))
            self.nav_buttons[key] = button
            side_layout.addWidget(button)
        side_layout.addStretch(1)
        self.sidebar_toggle = QPushButton("Collapse sidebar")
        self.sidebar_toggle.setObjectName("Nav")
        self.sidebar_toggle.clicked.connect(self.toggle_sidebar)
        side_layout.addWidget(self.sidebar_toggle)
        local_status = QLabel("●  LOCAL-FIRST")
        local_status.setStyleSheet("color: #43b68b; font-size: 10px; font-weight: 700; margin: 4px;")
        side_layout.addWidget(local_status)
        self.local_status = local_status
        version = QLabel("Version 2.1.4")
        version.setObjectName("Muted")
        version.setStyleSheet("font-size: 10px; margin: 4px;")
        side_layout.addWidget(version)
        self.sidebar = sidebar
        root_layout.addWidget(sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        toolbar = QFrame()
        toolbar.setObjectName("Sidebar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(24, 13, 24, 13)
        self.page_title = QLabel("Home")
        self.page_title.setStyleSheet("font-size: 16px; font-weight: 650;")
        self.top_status = QLabel("● Local mode")
        self.top_status.setObjectName("Muted")
        self.global_search = QLineEdit()
        self.global_search.setPlaceholderText("Search projects, transcripts and commands…")
        self.global_search.installEventFilter(self)
        self.global_search.setMaximumWidth(250)
        self.command_button = QPushButton("Ctrl+K  Commands")
        self.command_button.clicked.connect(self.show_command_palette)
        self.assistant_button = QPushButton("AI Assistant")
        self.assistant_button.setToolTip("Open the dedicated AI conversation page")
        self.assistant_button.clicked.connect(self.show_ai_assistant)
        new_button = QPushButton("＋  New transcription")
        new_button.setObjectName("Primary")
        new_button.clicked.connect(lambda: self.navigate("transcription"))
        toolbar_layout.addWidget(self.page_title)
        toolbar_layout.addStretch(1)
        toolbar_layout.addWidget(self.global_search)
        toolbar_layout.addWidget(self.command_button)
        toolbar_layout.addWidget(self.assistant_button)
        toolbar_layout.addWidget(self.top_status)
        toolbar_layout.addWidget(new_button)
        content_layout.addWidget(toolbar)

        self.stack = QStackedWidget()
        self.home_page = HomePage(self.history, self.model_manager, self.thread_pool)
        self.transcription_page = TranscriptionPage(self.paths, self.settings_store, self.history, self.model_manager, self.thread_pool, document=self.transcript_document, command_history=self.transcript_history)
        self.recording_page = RecordingPage(self.paths, self.recording_history, self.settings_store)
        self.history_page = HistoryPage(self.history, self.thread_pool)
        self.model_page = ModelLibraryPage(
            self.model_manager, self.settings_store, self.thread_pool, self.release_active_model
        )
        self.audio_page = AudioLibraryPage(self.paths, self.history, self.thread_pool, self.recording_history)
        self.audio_cleanup_page = AudioCleanupPage(self.paths, self.thread_pool)
        self.settings_page = SettingsPage(self.paths, self.settings_store, self.database, self.thread_pool, self.model_manager)
        self.batch_page = BatchProcessingPage(self.paths, self.settings_store, self.history, self.model_manager, self.thread_pool)
        self.editor_page = TranscriptEditorPage(
            document=self.transcript_document,
            history=self.transcript_history,
            before_history_action=self.transcription_page._commit_pending_text_edit,
            before_mutation=self.transcription_page._commit_pending_text_edit,
        )
        self.subtitle_page = SubtitleStudioPage()
        self.pages = {
            "home": ("Home", self.home_page),
            "transcription": ("New transcription", self.transcription_page),
            "recording": ("Record audio", self.recording_page),
            "batch": ("Batch processing", self.batch_page),
            "history": ("Projects", self.history_page),
            "editor": ("Transcript editor", self.editor_page),
            "subtitles": ("Subtitles & timing", self.subtitle_page),
            "models": ("AI models", self.model_page),
            "audio": ("Audio library", self.audio_page),
            "cleanup": ("Audio cleanup", self.audio_cleanup_page),
            "settings": ("Settings", self.settings_page),
        }
        for _, page in self.pages.values():
            self.stack.addWidget(page)
        content_layout.addWidget(self.stack, 1)
        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.workspace_splitter.setObjectName("WorkspaceSplitter")
        self.workspace_splitter.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.workspace_splitter.setHandleWidth(6)
        self.workspace_splitter.setChildrenCollapsible(False)
        # Let the main workspace yield horizontal room to the Inspector when
        # needed, while keeping a useful minimum visible content width.
        content.setMinimumWidth(180)
        content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.workspace_splitter.addWidget(content)
        self.workspace_splitter.setStretchFactor(0, 1)
        root_layout.addWidget(self.workspace_splitter, 1)
        self.setCentralWidget(root)
        self._inspector_width = 430

        self.assistant_dock = QDockWidget("Inspector", self)
        self.assistant_dock.setObjectName("AssistantDock")
        self.assistant_dock.setLayoutDirection(Qt.LeftToRight)
        # Inspector is the right-hand child of an explicit LTR splitter.
        # Drag its left divider left to make the Inspector wider.
        self.assistant_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.assistant_dock.setMinimumWidth(320)
        self.assistant_dock.setMaximumWidth(16777215)
        inspector_tabs = QTabWidget()
        inspector_tabs.setObjectName("InspectorTabs")
        self.inspector_tabs = inspector_tabs
        properties = QWidget()
        properties_layout = QVBoxLayout(properties)
        properties_layout.setContentsMargins(14, 12, 14, 12)
        self.inspector_title = QLabel("No active document")
        self.inspector_title.setStyleSheet("font-weight: 650; font-size: 15px;")
        self.inspector_details = QLabel("Open an audio file or transcript to inspect its properties.")
        self.inspector_details.setWordWrap(True)
        self.inspector_details.setObjectName("Muted")
        properties_layout.addWidget(self.inspector_title)
        properties_layout.addWidget(self.inspector_details)
        properties_layout.addStretch(1)
        self.assistant_panel = AssistantPanel(
            self.paths, self.thread_pool, self.settings_store,
            voice_transcriber=self._transcribe_voice_audio,
            voice_model_loader=self._prepare_voice_models,
            model_manager=self.model_manager,
        )
        self.assistant_panel.status_message.connect(lambda message: self.status_bar.showMessage(message, 7000))
        self.pages["assistant"] = ("AI Assistant", self.assistant_panel)
        self.stack.addWidget(self.assistant_panel)
        inspector_tabs.addTab(properties, "Properties")
        self.assistant_dock.setWidget(inspector_tabs)
        self._install_drawer_title_bar(
            self.assistant_dock, "Inspector", "☷", "width"
        )
        self.workspace_splitter.addWidget(self.assistant_dock)
        self.workspace_splitter.setStretchFactor(1, 0)
        self.workspace_splitter.setSizes([850, self._inspector_width])
        self.workspace_splitter.splitterMoved.connect(self._remember_inspector_width)
        self.workspace_splitter.handle(1).setToolTip("Drag left to widen the Inspector")

        self.timeline_dock = QDockWidget("Audio Timeline", self)
        self.timeline_dock.setObjectName("TimelineDock")
        self.timeline_dock.setLayoutDirection(Qt.LeftToRight)
        self.timeline_dock.setAllowedAreas(Qt.BottomDockWidgetArea)
        # The waveform is a bottom drawer, not a movable/floating dock window.
        self.timeline_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.timeline_dock.setFixedHeight(172)
        self.timeline = WaveformTimeline()
        self.timeline.set_interactive(True)
        self.timeline.seek_requested.connect(lambda value: self.transcription_page.player.seek(int(value * 1000)))
        self.timeline_dock.setWidget(self.timeline)
        self._install_drawer_title_bar(self.timeline_dock, "Audio Timeline", "〰", "height")
        self.addDockWidget(Qt.BottomDockWidgetArea, self.timeline_dock)
        self.setCorner(Qt.BottomRightCorner, Qt.RightDockWidgetArea)
        self.setCorner(Qt.BottomLeftCorner, Qt.BottomDockWidgetArea)

        status = QStatusBar()
        self.setStatusBar(status)
        self.status_bar = status
        self.assistant_drawer_button = QPushButton("Inspector")
        self.assistant_drawer_button.setIcon(self.icon_registry.icon("assistant", color="#79a8ff", size=14))
        self.assistant_drawer_button.setIconSize(QSize(14, 14))
        self.assistant_drawer_button.setCheckable(True)
        self.assistant_drawer_button.setChecked(not self.assistant_dock.isHidden())
        self.assistant_drawer_button.setToolTip("Show or hide the Inspector drawer")
        self.assistant_drawer_button.setAccessibleName("Toggle Inspector drawer")
        self.assistant_drawer_button.toggled.connect(
            lambda visible: self._animate_drawer(self.assistant_dock, visible, "width")
        )
        self.timeline_drawer_button = QPushButton("Waveform")
        self.timeline_drawer_button.setIcon(self.icon_registry.icon("waveform", color="#55b99a", size=14))
        self.timeline_drawer_button.setIconSize(QSize(14, 14))
        self.timeline_drawer_button.setCheckable(True)
        self.timeline_drawer_button.setChecked(not self.timeline_dock.isHidden())
        self.timeline_drawer_button.setToolTip("Show or hide the audio waveform timeline drawer")
        self.timeline_drawer_button.setAccessibleName("Toggle waveform drawer")
        self.timeline_drawer_button.toggled.connect(
            lambda visible: self._animate_drawer(self.timeline_dock, visible, "height")
        )
        for drawer_button in (self.assistant_drawer_button, self.timeline_drawer_button):
            drawer_button.setFixedHeight(25)
            drawer_button.setCursor(Qt.CursorShape.PointingHandCursor)
            drawer_button.setStyleSheet(
                "QPushButton { min-height: 0; max-height: 25px; padding: 2px 8px; "
                "border: 1px solid rgba(130, 145, 165, 0.25); border-radius: 6px; "
                "font-size: 10px; font-weight: 600; } "
                "QPushButton:hover { background: rgba(120, 145, 180, 0.12); } "
                "QPushButton:checked { background: rgba(100, 145, 210, 0.16); "
                "border-color: rgba(110, 155, 220, 0.55); }"
            )
        status.setLayoutDirection(Qt.LeftToRight)
        # Permanent widgets live at the far right and cannot be covered by status messages.
        status.addPermanentWidget(self.assistant_drawer_button)
        status.addPermanentWidget(self.timeline_drawer_button)
        status.showMessage("Ready · Local-first recognition")
        self.assistant_dock.visibilityChanged.connect(
            lambda visible: self._sync_drawer_controls(self.assistant_dock, visible)
        )
        self.timeline_dock.visibilityChanged.connect(
            lambda visible: self._sync_drawer_controls(self.timeline_dock, visible)
        )

        self.command_registry: list[dict] = []
        self.global_search_popup = GlobalSearchPopup(self, self._search_items)
        self.global_search_popup.result_activated.connect(self._activate_search_result)
        self.global_search.textChanged.connect(self._on_global_search_text_changed)
        self.global_search.returnPressed.connect(self.global_search_popup.activate_current)
        self.command_palette_popup = CommandPalettePopup(self)
        self.command_palette_popup.command_activated.connect(self._run_palette_command)
        self._build_menus()

    def _install_drawer_title_bar(self, dock, title: str, glyph: str, dimension: str):
        title_bar = QWidget(dock)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(12, 5, 7, 5)
        title_layout.setSpacing(9)
        icon = QLabel(glyph)
        icon.setStyleSheet("font-size: 16px; font-weight: 800;")
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: 700;")
        title_layout.addWidget(icon)
        title_layout.addWidget(title_label, 1)
        close_button = QPushButton("×")
        close_button.setObjectName(f"DrawerCloseButton_{dock.objectName()}")
        close_button.setFixedSize(28, 28)
        close_button.setToolTip("Close drawer")
        close_button.setAccessibleName(f"Close {title}")
        close_button.setStyleSheet(
            "QPushButton { border: none; border-radius: 7px; font-size: 20px; "
            "font-weight: 400; padding: 0; } "
            "QPushButton:hover { background: rgba(140, 150, 165, 0.18); }"
        )
        close_button.clicked.connect(lambda _checked=False, target=dock, axis=dimension: self._animate_drawer(target, False, axis))
        title_layout.addWidget(close_button)
        dock.setTitleBarWidget(title_bar)

    def _sync_drawer_controls(self, dock, visible: bool):
        pairs = (
            (self.assistant_dock, getattr(self, "assistant_drawer_button", None),
             getattr(self, "assistant_view_action", None), "inspector_visible"),
            (self.timeline_dock, getattr(self, "timeline_drawer_button", None),
             getattr(self, "timeline_view_action", None), "timeline_visible"),
        )
        for target, button, action, setting in pairs:
            if target is not dock:
                continue
            for control in (button, action):
                if control is not None:
                    previous = control.blockSignals(True)
                    control.setChecked(bool(visible))
                    control.blockSignals(previous)
            self.settings_store.update(**{setting: bool(visible)})
            break

    def _remember_inspector_width(self, *_args):
        """Remember the second (right-hand) splitter child's current width."""
        if self.assistant_dock.isHidden():
            return
        sizes = self.workspace_splitter.sizes()
        if len(sizes) == 2 and sizes[1] >= self.assistant_dock.minimumWidth():
            self._inspector_width = sizes[1]

    def _apply_inspector_width(self):
        """Restore a predictable right-pane width after the window is laid out."""
        if self.assistant_dock.isHidden():
            return
        available = self.workspace_splitter.width()
        target = max(self.assistant_dock.minimumWidth(), self._inspector_width)
        if available > target:
            self.workspace_splitter.setSizes([available - target, target])

    def _animate_drawer(self, dock, visible: bool, dimension: str):
        """Show or hide a drawer while keeping each panel's sizing rules explicit."""
        if dock not in (self.assistant_dock, self.timeline_dock):
            return

        if dimension == "width":
            if visible:
                dock.show()
                self._apply_inspector_width()
            else:
                self._remember_inspector_width()
                dock.hide()
        elif dimension == "height":
            # Waveform is a compact strip, not a vertically resizable workspace.
            dock.setFixedHeight(172)
            dock.setVisible(bool(visible))
        else:
            raise ValueError(f"Unsupported drawer dimension: {dimension}")

        self._sync_drawer_controls(dock, not dock.isHidden())

    def _set_transcription_job_busy(self, busy: bool):
        """Lock alternate document entry points while an operation owns the transcript."""
        enabled = not bool(busy)
        self.home_page.recent.setEnabled(enabled)
        self.history_page.items.setEnabled(enabled)
        self.editor_page.setEnabled(enabled)
        self.subtitle_page.setEnabled(enabled)
        tip = "Finish or cancel the current operation before opening another transcript." if busy else ""
        self.home_page.recent.setToolTip(tip)
        self.history_page.items.setToolTip(tip)

    def _connect_pages(self):
        self.home_page.navigate.connect(self.navigate)
        self.home_page.open_transcript.connect(self.open_transcript)
        self.history_page.open_transcript.connect(self.open_transcript)
        self.recording_page.audio_ready.connect(self.open_recording_in_transcriber)
        self.recording_page.open_library.connect(self._show_recordings_library)
        self.audio_page.open_audio.connect(self.open_audio_library_file)
        self.audio_cleanup_page.status_message.connect(lambda message: self.status_bar.showMessage(message, 7000))
        self.transcription_page.job_state_changed.connect(self._set_transcription_job_busy)
        self.transcription_page.audio_changed.connect(self._load_waveform)
        self.transcription_page.transcript_changed.connect(self._on_transcript_changed)
        self.transcription_page.segments_edited.connect(self._on_transcription_text_edited)
        self.transcription_page.player.position_changed.connect(lambda value: self.timeline.set_position(value / 1000.0))
        self.transcription_page.player.duration_changed.connect(self._on_audio_duration_changed)
        self.editor_page.document_changed.connect(self._sync_editor_document)
        self.editor_page.seek_requested.connect(lambda seconds: self.transcription_page.player.seek(int(seconds * 1000)))
        self.subtitle_page.segments_changed.connect(self._sync_subtitle_document)
        self.batch_page.status_message.connect(lambda message: self.status_bar.showMessage(message, 7000))
        self.editor_page.status_message.connect(lambda message: self.status_bar.showMessage(message, 7000))
        self.subtitle_page.status_message.connect(lambda message: self.status_bar.showMessage(message, 7000))
        for page in (self.transcription_page, self.recording_page, self.history_page,
                     self.model_page, self.settings_page, self.batch_page, self.audio_cleanup_page):
            if hasattr(page, "status_message"):
                page.status_message.connect(self.status_bar.showMessage)
        self.settings_page.theme_changed.connect(self.apply_theme)
        self.settings_page.concurrency_changed.connect(self._update_worker_limit)
        self.settings_page.audio_devices_changed.connect(self._apply_audio_device_preferences)
        self._apply_audio_device_preferences(
            self.settings_store.settings.audio_input_device_id,
            self.settings_store.settings.audio_output_device_id,
        )
        self.settings_page.permission_changed.connect(
            lambda permission, enabled: self.action_registry.set_permission(AgentPermission(permission), enabled)
        )
        self.settings_page.agent_settings_saved.connect(self.assistant_panel.sync_settings)
        self.model_page.default_model_changed.connect(
            lambda _repo_id: self.transcription_page.refresh_models(select_default=True)
        )
        self.model_page.installed_models_changed.connect(
            lambda: self.transcription_page.refresh_models()
        )
        self.model_page.installed_models_changed.connect(
            self.settings_page.refresh_vosk_models
        )
        self.model_page.installed_models_changed.connect(
            self.assistant_panel.refresh_wake_models
        )
        self.model_page.installed_models_changed.connect(
            self.assistant_panel.refresh_voice_asr_models
        )


    def _register_command(self, title, category, callback, shortcut=None, keywords=""):
        self.command_registry.append({
            "title": title, "category": category, "shortcut": shortcut,
            "keywords": str(keywords or ""),
            "callback": callback,
        })

    def _add_menu_action(self, menu, title, callback, shortcut=None):
        action = QAction(title, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.WindowShortcut)
        action.triggered.connect(lambda _checked=False, fn=callback: fn())
        menu.addAction(action)
        self._register_command(title, menu.title(), callback, shortcut)
        return action

    def show_ai_assistant(self):
        """Open the dedicated AI voice/chat workspace."""
        self.navigate("assistant")
        self.assistant_panel.prompt.setFocus()

    def _build_menus(self):
        bar = self.menuBar()
        file_menu = bar.addMenu("&File")
        self._add_menu_action(file_menu, "New Transcription", lambda: self.navigate("transcription"), "Ctrl+Shift+N")
        self._add_menu_action(file_menu, "Open Audio…", self.transcription_page.choose_audio, "Ctrl+O")
        file_menu.addSeparator()
        self.close_audio_action = self._add_menu_action(
            file_menu, "Close Audio", self.transcription_page.close_audio, "Ctrl+W"
        )
        self.close_audio_action.setEnabled(self.transcription_page.audio_path is not None)
        self.transcription_page.audio_changed.connect(
            lambda path: self.close_audio_action.setEnabled(bool(path))
        )
        self._add_menu_action(file_menu, "Save Transcript", self.transcription_page._autosave, "Ctrl+S")
        self._add_menu_action(file_menu, "Export Transcript…", self.transcription_page.export_button.click)
        file_menu.addSeparator()
        self._add_menu_action(file_menu, "Exit", self.close, "Ctrl+Q")

        edit_menu = bar.addMenu("&Edit")
        self._add_menu_action(edit_menu, "Undo", self.editor_page.undo, "Ctrl+Z")
        self._add_menu_action(edit_menu, "Redo", self.editor_page.redo, "Ctrl+Y")
        edit_menu.addSeparator()
        self._add_menu_action(edit_menu, "Cut", lambda: self._edit_focused_widget("cut"), "Ctrl+X")
        self._add_menu_action(edit_menu, "Copy", lambda: self._edit_focused_widget("copy"), "Ctrl+C")
        self._add_menu_action(edit_menu, "Paste", lambda: self._edit_focused_widget("paste"), "Ctrl+V")
        self._add_menu_action(edit_menu, "Select All", lambda: self._edit_focused_widget("selectAll"), "Ctrl+A")
        self._add_menu_action(edit_menu, "Find", self.global_search.setFocus, "Ctrl+F")
        self._add_menu_action(edit_menu, "Replace", self._focus_replace, "Ctrl+H")

        view_menu = bar.addMenu("&View")
        panels_menu = view_menu.addMenu("Panels")
        self.sidebar_action = QAction("Sidebar", self)
        self.sidebar_action.setCheckable(True)
        self.sidebar_action.setChecked(True)
        self.sidebar_action.toggled.connect(self._set_sidebar_visible)
        view_menu.addAction(self.sidebar_action)
        panels_menu.addAction(self.sidebar_action)

        self.assistant_view_action = QAction("Inspector", self)
        self.assistant_view_action.setCheckable(True)
        self.assistant_view_action.setChecked(not self.assistant_dock.isHidden())
        self.assistant_view_action.setShortcut(QKeySequence("Ctrl+Shift+I"))
        self.assistant_view_action.setShortcutContext(Qt.WindowShortcut)
        self.assistant_view_action.toggled.connect(
            lambda visible: self._animate_drawer(self.assistant_dock, visible, "width")
        )
        self.timeline_view_action = QAction("Audio Timeline", self)
        self.timeline_view_action.setCheckable(True)
        self.timeline_view_action.setChecked(not self.timeline_dock.isHidden())
        self.timeline_view_action.setShortcut(QKeySequence("Ctrl+Shift+T"))
        self.timeline_view_action.setShortcutContext(Qt.WindowShortcut)
        self.timeline_view_action.toggled.connect(
            lambda visible: self._animate_drawer(self.timeline_dock, visible, "height")
        )
        for action in (self.assistant_view_action, self.timeline_view_action):
            view_menu.addAction(action)
            panels_menu.addAction(action)
            self._register_command(action.text(), "View", action.trigger, action.shortcut().toString())
        self._add_menu_action(view_menu, "Restore Default Layout", self.restore_default_layout)

        tools_menu = bar.addMenu("&Tools")
        for key, _icon, title in self.NAVIGATION:
            if key in {"transcription", "recording", "batch", "cleanup", "subtitles", "models"}:
                self._add_menu_action(tools_menu, title, lambda page=key: self.navigate(page))

        window_menu = bar.addMenu("&Window")
        self._add_menu_action(window_menu, "Minimize", self.showMinimized)
        self._add_menu_action(window_menu, "Maximize / Restore", self._toggle_maximized, "F11")
        for key, _icon, title in self.NAVIGATION:
            self._add_menu_action(window_menu, title, lambda page=key: self.navigate(page))

        help_menu = bar.addMenu("&Help")
        self._add_menu_action(help_menu, "Keyboard Shortcuts", self._show_keyboard_shortcuts)
        self._add_menu_action(help_menu, "About Transcriber", self._show_about)

        # Settings are destinations, too: expose every major control group to
        # both global search and the Ctrl+K command palette.
        for entry in self.settings_page.search_entries():
            self._register_command(
                entry["title"],
                entry["category"],
                lambda target=entry["callback"]: self._open_settings_target(target),
                keywords=entry.get("keywords", ""),
            )

    def _edit_focused_widget(self, operation):
        widget = QApplication.focusWidget()
        method = getattr(widget, operation, None) if widget is not None else None
        if callable(method):
            method()

    def _focus_replace(self):
        self.navigate("editor")
        self.editor_page.replace_input.setFocus()

    def _toggle_maximized(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def _show_keyboard_shortcuts(self):
        QMessageBox.information(
            self, "Keyboard Shortcuts",
            "Ctrl+O  Open audio\\nCtrl+S  Save transcript\\nCtrl+Shift+N  New transcription\\n"
            "Ctrl+K  Command palette\\nCtrl+F  Global search\\nCtrl+Z / Ctrl+Y  Undo / Redo\\n"
            "Ctrl+Shift+I  Toggle inspector\\nCtrl+Shift+T  Toggle timeline\\nF11  Maximize / restore",
        )

    def _show_about(self):
        QMessageBox.about(self, "About Transcriber", "Transcriber 2.1.5\\nLocal-first audio transcription workspace")

    def _set_sidebar_visible(self, visible):
        self.sidebar.setVisible(bool(visible))
        self.settings_store.update(sidebar_visible=bool(visible))

    def restore_default_layout(self):
        self.addDockWidget(Qt.BottomDockWidgetArea, self.timeline_dock)
        self.timeline_dock.setFloating(False)
        self.assistant_dock.setMinimumWidth(320)
        self.assistant_dock.setMaximumWidth(16777215)
        # setFixedHeight sets both limits; never release the maximum again.
        self.timeline_dock.setFixedHeight(172)
        self.assistant_dock.show()
        self.timeline_dock.show()
        self._inspector_width = 430
        self._apply_inspector_width()
        self._sync_drawer_controls(self.assistant_dock, True)
        self._sync_drawer_controls(self.timeline_dock, True)
        self.sidebar.show()
        self._sidebar_collapsed = False
        self.sidebar.setMinimumWidth(190)
        self.sidebar.setMaximumWidth(230)
        self.brand_name.show()
        self.tagline.show()
        self.sidebar_action.setChecked(True)
        self.sidebar_toggle.setText("Collapse sidebar")
        for key, _icon, title in self.NAVIGATION:
            self.nav_buttons[key].setText(title)
        self.settings_store.update(
            sidebar_visible=True, sidebar_collapsed=False,
            inspector_visible=True, timeline_visible=True, window_state=None,
        )

    @staticmethod
    def _command_matches(command: dict, query: str) -> bool:
        searchable = " ".join(
            str(command.get(key) or "")
            for key in ("title", "category", "keywords", "description", "shortcut")
        ).casefold()
        return all(token in searchable for token in str(query or "").casefold().split())

    def _search_items(self, query):
        normalized = str(query or "").strip().casefold()
        results = []
        if normalized:
            try:
                records = self.history.list(query, limit=12)
            except (OSError, RuntimeError, ValueError):
                records = []
            for record in records:
                results.append({
                    "kind": "transcript", "id": record["id"],
                    "title": record["title"], "subtitle": record.get("preview", "Transcript"),
                })
            for page_id, _icon, title in self.NAVIGATION:
                if any(
                    token in title.casefold() or token in page_id.casefold()
                    for token in normalized.split()
                ):
                    results.append({"kind": "page", "id": page_id, "title": title, "subtitle": "Workspace page"})
            for command in self.command_registry:
                if self._command_matches(command, normalized):
                    results.append({
                        "kind": "command", "title": command["title"],
                        "subtitle": command["category"], "command": command,
                    })
        return results[:40]

    def _open_settings_target(self, callback):
        self.navigate("settings")
        QTimer.singleShot(0, callback)

    def _apply_audio_device_preferences(self, input_device_id: str, output_device_id: str):
        self.recording_page.refresh_devices()
        self.transcription_page.player.set_output_device(output_device_id)

    def _on_global_search_text_changed(self, query):
        self.global_search_popup.open_for(self.global_search, query)

    def _activate_search_result(self, result):
        if not result:
            return
        kind = result.get("kind")
        if kind == "transcript":
            self.open_transcript(str(result["id"]))
        elif kind == "page":
            self.navigate(str(result["id"]))
        elif kind == "command":
            self._run_palette_command(result["command"])

    def _run_palette_command(self, command):
        callback = command.get("callback") if isinstance(command, dict) else None
        if callable(callback):
            self.command_palette_popup.hide()
            callback()

    def show_command_palette(self):
        self.command_palette_popup.open(self.command_registry)

    def _on_transcription_text_edited(self, _segments):
        self.editor_page.refresh()
        self.subtitle_page.load_segments(self.transcript_document.segments)
        self.timeline.set_segments(self.transcript_document.segments)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        popup = getattr(self, "global_search_popup", None)
        if popup is not None and popup.isVisible():
            popup.reposition()

    def eventFilter(self, watched, event):
        popup = getattr(self, "global_search_popup", None)
        if watched is self.global_search and popup is not None and popup.isVisible():
            if event.type() == QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_Down:
                    popup.move_selection(1)
                    return True
                if event.key() == Qt.Key.Key_Up:
                    popup.move_selection(-1)
                    return True
                if event.key() == Qt.Key.Key_Escape:
                    popup.hide()
                    return True
        return super().eventFilter(watched, event)

    def _start_local_ipc(self):
        self.ipc_server = LocalIPCServer(self.paths.config / "transcriber-ipc.json", self._handle_ipc)
        try:
            self.ipc_server.start()
        except OSError as exc:
            self.ipc_server = None
            self.status_bar.showMessage(f"Local Agent IPC unavailable: {exc}", 8000)

    def _voice_asr_model_id(self, configured=None) -> str:
        settings = configured or self.settings_store.settings
        candidates = [
            item for item in self.model_manager.installed(include_sizes=False)
            if item.get("compatible")
            and str(item.get("runtime") or "faster-whisper") == "faster-whisper"
        ]
        if not candidates:
            raise RuntimeError(
                "Install a compatible Faster-Whisper model in AI models before using voice commands."
            )
        preferred = settings.voice_asr_model or settings.default_model
        candidates.sort(key=lambda item: (
            item.get("repo_id") != preferred,
            str(item.get("repo_id") or "").casefold(),
        ))
        return str(candidates[0]["repo_id"])

    def _prepare_voice_models(self) -> str:
        """Warm the selected local Faster-Whisper ASR model before microphone capture."""
        if self.transcription_page.is_busy:
            raise RuntimeError(
                "Finish or cancel the current transcription before starting voice chat."
            )
        configured = self.settings_store.settings
        repo_id = self._voice_asr_model_id(configured)
        self.model_manager.get_engine(repo_id, configured)
        return repo_id

    def _transcribe_voice_audio(self, pcm_audio: bytes) -> str:
        """Transcribe an in-memory voice command with the installed local Whisper model."""
        if self.transcription_page.is_busy:
            raise RuntimeError(
                "Finish or cancel the current transcription before using voice commands."
            )
        configured = self.settings_store.settings
        repo_id = self._voice_asr_model_id(configured)
        audio = bytes(pcm_audio)
        audio = audio[: len(audio) - (len(audio) % 2)]
        if len(audio) < 3200:
            raise RuntimeError("The voice command was too short to recognize.")

        self.paths.cache.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(
            prefix="voice-command-", suffix=".wav", dir=self.paths.cache
        )
        os.close(handle)
        temporary_path = Path(temporary_name)
        try:
            with wave.open(str(temporary_path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16_000)
                output.writeframes(audio)

            engine = self.model_manager.get_engine(repo_id, configured)
            language = (
                None if configured.default_language == "auto"
                else configured.default_language
            )
            options = TranscriptionOptions(
                language=language,
                task="transcribe",
                beam_size=max(1, min(5, configured.beam_size)),
                vad_filter=True,
                word_timestamps=False,
                initial_prompt=(
                    "Transcribe this spoken voice-assistant command verbatim. "
                    "Preserve the language spoken. Do not answer the command."
                ),
            )
            result = engine.transcribe(
                temporary_path, options, cancel_event=Event()
            )
            recognized = str(result.text or "").strip()
            if not recognized:
                raise RuntimeError(
                    "Faster-Whisper could not recognize words in that voice command."
                )
            return recognized
        finally:
            temporary_path.unlink(missing_ok=True)

    def _register_agent_actions(self):
        register = self.action_registry.register
        register(ActionSpec("app.navigate", "Navigate to an available Transcriber page.",
                            AgentPermission.READ_ONLY, lambda args: self.navigate(args["page"]), required=("page",)))
        register(ActionSpec("app.get_state", "Read current page, media, transcript and model state.",
                            AgentPermission.READ_ONLY, lambda _args: self._app_state()))
        register(ActionSpec("editor.get_segments", "Read the current transcript segments and timestamps.",
                            AgentPermission.READ_ONLY, lambda _args: [item.to_dict() for item in self.transcription_page.segments]))
        register(ActionSpec("editor.update_segment", "Update text, times, speaker or review metadata for one segment.",
                            AgentPermission.EDIT_CONTENT, self._agent_update_segment,
                            required=("segment_id", "changes")))
        register(ActionSpec("editor.undo", "Undo the last segment-editor operation.",
                            AgentPermission.EDIT_CONTENT, lambda _args: self.editor_page.undo()))
        register(ActionSpec("editor.redo", "Redo the last undone segment-editor operation.",
                            AgentPermission.EDIT_CONTENT, lambda _args: self.editor_page.redo()))
        register(ActionSpec("editor.split_segment", "Split a segment at an existing word-time boundary, or at a supplied character/time pair.",
                            AgentPermission.EDIT_CONTENT, self._agent_split_segment,
                            required=("segment_id", "split_at")))
        register(ActionSpec("editor.merge_segments", "Merge two selected transcript segments.",
                            AgentPermission.EDIT_CONTENT, self._agent_merge_segments,
                            required=("first_id", "second_id")))
        register(ActionSpec("editor.delete_segment", "Delete one transcript segment after explicit GUI approval.",
                            AgentPermission.EDIT_CONTENT, self._agent_delete_segment,
                            required=("segment_id",), destructive=True))
        register(ActionSpec("editor.set_speaker", "Assign a speaker label to one or more segments.",
                            AgentPermission.EDIT_CONTENT, self._agent_set_speaker,
                            required=("segment_ids", "speaker")))
        register(ActionSpec("editor.search", "Search the current transcript using literal or regular-expression matching.",
                            AgentPermission.READ_ONLY, self._agent_search, required=("query",)))
        register(ActionSpec("editor.replace", "Replace matching segment text; regex mode is optional and locked segments are skipped.",
                            AgentPermission.EDIT_CONTENT, self._agent_replace,
                            required=("query", "replacement")))
        register(ActionSpec("subtitle.validate", "Validate current subtitle timings, overlaps and reading speed.",
                            AgentPermission.READ_ONLY, lambda _args: [
                                {"code": item.code, "severity": item.severity, "segment_ids": list(item.segment_ids), "message": item.message}
                                for item in __import__("transcriber.subtitles.timing", fromlist=["validate_subtitles"]).validate_subtitles(self.transcription_page.segments)
                            ]))
        register(ActionSpec("audio.get_status", "Read current audio playback and media path.",
                            AgentPermission.READ_ONLY, lambda _args: {
                                "path": str(self.transcription_page.audio_path) if self.transcription_page.audio_path else None,
                                "position_ms": self.transcription_page.player.player.position(),
                                "duration_ms": self.transcription_page.player.player.duration(),
                                "playing": self.transcription_page.player.player.playbackState().value == 1,
                            }))
        register(ActionSpec("audio.seek", "Seek the current audio file to a time in seconds.",
                            AgentPermission.READ_ONLY, self._agent_audio_seek, required=("seconds",)))
        register(ActionSpec("audio.play", "Start playback of the current media file.",
                            AgentPermission.READ_ONLY, lambda _args: self.transcription_page.player.player.play()))
        register(ActionSpec("audio.stop", "Stop current media playback.",
                            AgentPermission.READ_ONLY, lambda _args: self.transcription_page.player.player.stop()))
        register(ActionSpec("subtitle.export", "Export current subtitle cues to an application-managed output file.",
                            AgentPermission.FILE_EXPORT, self._agent_subtitle_export,
                            required=("format",)))
        register(ActionSpec("transcription.start", "Start transcription for the currently selected audio file.",
                            AgentPermission.EDIT_CONTENT, lambda _args: self.transcription_page.start_transcription()))
        register(ActionSpec("transcription.cancel", "Cancel the current transcription job.",
                            AgentPermission.EDIT_CONTENT, lambda _args: self.transcription_page.cancel_transcription()))
        register(ActionSpec("transcription.get_quality_report", "Calculate transcript quality metrics from real segment timing and any engine-provided word confidence.",
                            AgentPermission.READ_ONLY, self._agent_quality_report))
        register(ActionSpec(
            "desktop.launch_app",
            "Launch one allowlisted Windows application.",
            AgentPermission.DESKTOP_CONTROL,
            self._agent_launch_app,
            required=("app",),
            requires_approval=True,
        ))
        register(ActionSpec(
            "desktop.run_preset",
            "Open a predefined Windows location or built-in application.",
            AgentPermission.DESKTOP_CONTROL,
            self._agent_run_preset,
            required=("preset",),
            requires_approval=True,
        ))
        register(ActionSpec(
            "desktop.open_path",
            "Open an existing local file or folder in its default application.",
            AgentPermission.DESKTOP_CONTROL,
            self._agent_open_path,
            required=("path",),
            requires_approval=True,
        ))
        register(ActionSpec(
            "desktop.open_url",
            "Open an HTTP or HTTPS URL in the default browser.",
            AgentPermission.DESKTOP_CONTROL,
            self._agent_open_url,
            required=("url",),
            requires_approval=True,
        ))
        self.agent_browser = WindowsBrowserController(
            self.paths.config / "agent-browser-profile"
        )
        register(ActionSpec(
            "browser.open", "Open a website in the dedicated controlled Chrome/Edge browser.",
            AgentPermission.BROWSER_CONTROL,
            lambda args: self.agent_browser.open(args["url"]), required=("url",),
        , background=True))
        register(ActionSpec(
            "browser.search", "Search the web in the dedicated controlled Chrome/Edge browser.",
            AgentPermission.BROWSER_CONTROL,
            lambda args: self.agent_browser.search(
                args["query"], engine=str(args.get("engine") or "google")
            ), required=("query",),
        , background=True))
        register(ActionSpec(
            "browser.snapshot", "Read the controlled browser tab and visible interactive elements.",
            AgentPermission.BROWSER_CONTROL,
            lambda _args: self.agent_browser.snapshot(),
        , background=True))
        register(ActionSpec(
            "browser.click", "Click a browser element after the user approves the target.",
            AgentPermission.BROWSER_CONTROL,
            lambda args: self.agent_browser.click(
                text=str(args.get("text") or ""),
                selector=str(args.get("selector") or ""),
                role=str(args.get("role") or ""),
            ), requires_approval=True, background=True,
        ))
        register(ActionSpec(
            "browser.fill", "Fill a browser form field after the user approves the value.",
            AgentPermission.BROWSER_CONTROL,
            lambda args: self.agent_browser.fill(
                str(args.get("value") or ""),
                selector=str(args.get("selector") or ""),
                label=str(args.get("label") or ""),
                placeholder=str(args.get("placeholder") or ""),
            ), required=("value",), requires_approval=True, background=True,
        ))
        register(ActionSpec(
            "browser.press", "Press a limited keyboard key in the controlled browser.",
            AgentPermission.BROWSER_CONTROL,
            lambda args: self.agent_browser.press(
                str(args.get("key") or ""), selector=str(args.get("selector") or "")
            ), required=("key",), requires_approval=True, background=True,
        ))
        register(ActionSpec(
            "browser.back", "Navigate back one page in the controlled browser.",
            AgentPermission.BROWSER_CONTROL, lambda _args: self.agent_browser.back(),
        , background=True))
        register(ActionSpec(
            "browser.screenshot", "Save a screenshot of the controlled browser page.",
            AgentPermission.BROWSER_CONTROL,
            lambda _args: self.agent_browser.screenshot(
                self.paths.data / "agent-browser-screenshots"
            ),
        , background=True))
        register(ActionSpec(
            "browser.close", "Close the controlled browser and its dedicated profile window.",
            AgentPermission.BROWSER_CONTROL, lambda _args: self.agent_browser.close(),
            requires_approval=True, background=True,
        ))
        register(ActionSpec(
            "system.run_command",
            "Run a custom PowerShell command as the current Windows user; every command requires approval.",
            AgentPermission.COMMAND_EXECUTION, self._agent_run_command,
            required=("command",), requires_approval=True, background=True,
        ))
        register(ActionSpec(
            "agent.skills_list", "List locally installed portable Agent Skills.",
            AgentPermission.READ_ONLY,
            lambda _args: self.assistant_panel.skill_manager.summaries(),
        ))
        register(ActionSpec(
            "agent.skill_load", "Load the full instructions for one installed Agent Skill.",
            AgentPermission.READ_ONLY,
            lambda args: self.assistant_panel.skill_manager.load_skill(args["name"]),
            required=("name",),
        ))
        register(ActionSpec(
            "agent.skill_read_resource",
            "Read a text resource from a Skill without executing it.",
            AgentPermission.READ_ONLY,
            lambda args: self.assistant_panel.skill_manager.read_resource(
                args["name"], args["path"]
            ), required=("name", "path"),
        ))

    def _handle_ipc(self, method, params, request_id=None):
        if method in {"app.get_state", "app.list_actions"}:
            if AgentPermission.READ_ONLY not in self.action_registry.permissions:
                raise PermissionDenied("Read-only Agent permission is disabled")
            if method == "app.get_state":
                return self.dispatcher(lambda _payload: self._app_state(), {})
            return self.action_registry.describe()
        if method == "app.execute_action":
            raise ValueError(
                "Synchronous action execution is deprecated. Use app.submit_action with an "
                "idempotency_key, then query app.get_operation."
            )
        if method == "app.submit_action":
            return self.operation_manager.submit(
                str(params.get("name", "")),
                params.get("arguments") or {},
                request_id=request_id,
                idempotency_key=params.get("idempotency_key"),
                deadline_seconds=params.get("deadline_seconds", 120),
            )
        if method == "app.get_operation":
            return self.operation_manager.get(str(params.get("operation_id", "")))
        if method == "app.cancel_operation":
            return self.operation_manager.cancel(str(params.get("operation_id", "")))
        if method == "app.list_operations":
            if AgentPermission.READ_ONLY not in self.action_registry.permissions:
                raise PermissionDenied("Read-only Agent permission is disabled")
            return self.operation_manager.list(limit=params.get("limit", 50))
        raise KeyError(f"Unknown IPC method: {method}")

    def _app_state(self):
        return {
            "available": True, "application": "Transcriber", "page": next(
                (key for key, (_title, page) in self.pages.items() if page is self.stack.currentWidget()), "home"
            ),
            "audio_path": str(self.transcription_page.audio_path) if self.transcription_page.audio_path else None,
            "transcript_id": self.transcription_page.transcript_id,
            "segment_count": len(self.transcription_page.segments),
            "model_id": self.model_manager.active_model_id,
            "opencode_connected": bool(self.assistant_panel.client and self.assistant_panel.client.connected),
            "voice_active": self.assistant_panel.voice_agent is not None,
            "permissions": sorted(item.value for item in self.action_registry.permissions),
        }

    def _agent_update_segment(self, args):
        self.editor_page.history.execute(self.editor_page.document.update_segment,
                                         args["segment_id"], **dict(args["changes"]))
        self.editor_page._finish_change("Segment updated by Agent")
        return self.editor_page.document.get(args["segment_id"]).to_dict()

    def _agent_split_segment(self, args):
        segment_id = str(args["segment_id"])
        split_at = float(args["split_at"])
        if args.get("character_index") is not None:
            result = self.editor_page.history.execute(
                self.editor_page.document.split_segment_at_text,
                segment_id, int(args["character_index"]), split_at,
            )
        else:
            result = self.editor_page.history.execute(
                self.editor_page.document.split_segment, segment_id, split_at,
            )
        self.editor_page._finish_change("Segment split by Agent")
        return [item.to_dict() for item in result]

    def _agent_merge_segments(self, args):
        result = self.editor_page.history.execute(
            self.editor_page.document.merge_segments,
            str(args["first_id"]), str(args["second_id"]),
        )
        self.editor_page._finish_change("Segments merged by Agent")
        return result.to_dict()

    def _agent_delete_segment(self, args):
        segment_id = str(args["segment_id"])
        self.editor_page.history.execute(self.editor_page.document.delete_segment, segment_id)
        self.editor_page._finish_change("Segment deleted by Agent")
        return {"deleted": True, "segment_id": segment_id}

    def _agent_set_speaker(self, args):
        segment_ids = [str(value) for value in args["segment_ids"]]
        speaker = str(args["speaker"]).strip() or None
        self.editor_page.history.execute(self.editor_page.document.set_speaker, segment_ids, speaker)
        self.editor_page._finish_change("Speaker updated by Agent")
        return {"updated": segment_ids, "speaker": speaker}

    def _agent_search(self, args):
        from transcriber.editor.search import search
        matches = search(self.editor_page.document, str(args["query"]), regex=bool(args.get("regex", False)))
        return [{"segment_id": item.segment_id, "start": item.start, "end": item.end, "text": item.text} for item in matches]

    def _agent_replace(self, args):
        from transcriber.editor.search import replace
        count = self.editor_page.history.execute(
            replace, self.editor_page.document, str(args["query"]),
            str(args["replacement"]), regex=bool(args.get("regex", False)),
        )
        if count:
            self.editor_page._finish_change(f"Agent replaced text in {count} segment(s)")
        return {"replacements": count}

    def _agent_subtitle_export(self, args):
        from uuid import uuid4

        from transcriber.subtitles.formats import export_subtitles
        fmt = str(args["format"]).casefold().lstrip(".")
        if fmt not in {"srt", "vtt", "ass", "ssa"}:
            raise ValueError("Subtitle format must be one of: srt, vtt, ass, ssa")
        segments = self.editor_page.snapshot_segments()
        if not segments:
            raise ValueError("There is no transcript to export")
        output_dir = self.paths.data / "agent-exports"
        filename = f"transcript-{uuid4().hex[:10]}.{fmt}"
        target = output_dir / filename
        result = export_subtitles(target, segments, format=fmt, title="Transcriber Agent export")
        return {"exported": True, "path": str(result), "format": fmt, "segment_count": len(segments)}

    def _agent_quality_report(self, _args):
        from transcriber.transcription.quality_report import build_quality_report
        result = build_quality_report(
            segments=self.transcription_page.segments,
            language=self.transcription_page._record_metadata.get("language") if self.transcription_page._record_metadata else None,
            duration=self._audio_duration_seconds(),
        )
        return result.to_dict()

    def _agent_audio_seek(self, args):
        seconds = max(0.0, float(args["seconds"]))
        self.transcription_page.player.seek(int(seconds * 1000))
        return {"position_ms": self.transcription_page.player.player.position()}

    def _agent_launch_app(self, args):
        """Launch only a fixed executable name; never pass model text to a shell."""
        if sys.platform != "win32":
            raise RuntimeError("The built-in desktop application launcher is currently Windows-only.")
        app = str(args.get("app") or "").casefold()
        executables = {
            "notepad": "notepad.exe",
            "calculator": "calc.exe",
            "explorer": "explorer.exe",
            "task_manager": "taskmgr.exe",
            "paint": "mspaint.exe",
            "terminal": "wt.exe",
        }
        executable = executables.get(app)
        if not executable:
            raise ValueError("Choose an application from the built-in allowlist.")
        resolved = shutil.which(executable)
        if resolved is None:
            windows_dir = os.environ.get("WINDIR", r"C:\\Windows")
            candidate = Path(windows_dir) / "System32" / executable
            if candidate.is_file():
                resolved = str(candidate)
        if not resolved:
            raise FileNotFoundError(f"{executable} was not found on this Windows installation.")
        subprocess.Popen(
            [resolved],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        return {"launched": app, "executable": resolved}

    def _agent_open_path(self, args):
        raw_path = str(args.get("path") or "").strip()
        if not raw_path:
            raise ValueError("A local path is required.")
        try:
            resolved = Path(raw_path).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise FileNotFoundError(f"Local path does not exist: {raw_path}") from exc
        if not (resolved.is_file() or resolved.is_dir()):
            raise ValueError("Only existing files and folders can be opened.")
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(resolved))):
            raise RuntimeError(f"Windows could not open: {resolved}")
        return {"opened": str(resolved), "kind": "folder" if resolved.is_dir() else "file"}

    def _agent_open_url(self, args):
        parsed = QUrl(str(args.get("url") or "").strip())
        if not parsed.isValid() or parsed.scheme().casefold() not in {"http", "https"} or not parsed.host():
            raise ValueError("Only valid HTTP or HTTPS URLs can be opened.")
        if not QDesktopServices.openUrl(parsed):
            raise RuntimeError("The default browser could not open this URL.")
        return {"opened_url": parsed.toString()}

    def _agent_run_preset(self, args):
        preset = str(args.get("preset") or "").casefold()
        folders = {
            "downloads_folder": Path.home() / "Downloads",
            "documents_folder": Path.home() / "Documents",
            "desktop_folder": Path.home() / "Desktop",
        }
        if preset in folders:
            target = folders[preset]
            if not target.is_dir():
                target = Path.home()
            return self._agent_open_path({"path": str(target)})
        applications = {
            "task_manager": "task_manager",
            "calculator": "calculator",
            "notepad": "notepad",
        }
        if preset in applications:
            return self._agent_launch_app({"app": applications[preset]})
        if preset == "windows_settings":
            if sys.platform != "win32":
                raise RuntimeError("Windows Settings is only available on Windows.")
            os.startfile("ms-settings:")
            return {"opened": "Windows Settings"}
        diagnostic_commands = {
            "network_config": ("ipconfig.exe", ["/all"], 20.0),
            "running_processes": ("tasklist.exe", [], 20.0),
            "user_identity": ("whoami.exe", [], 10.0),
        }
        if preset in diagnostic_commands:
            if sys.platform != "win32":
                raise RuntimeError("These predefined diagnostic commands are currently Windows-only.")
            executable, arguments, timeout = diagnostic_commands[preset]
            resolved = shutil.which(executable)
            if resolved is None:
                windows_dir = os.environ.get("WINDIR", r"C:\\Windows")
                candidate = Path(windows_dir) / "System32" / executable
                if candidate.is_file():
                    resolved = str(candidate)
            if not resolved:
                raise FileNotFoundError(f"{executable} was not found on this Windows installation.")
            completed = subprocess.run(
                [resolved, *arguments],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            output = (completed.stdout or completed.stderr or "").strip()
            if completed.returncode:
                raise RuntimeError(
                    f"{preset} exited with code {completed.returncode}: {output[:1200]}"
                )
            return {
                "command": [executable, *arguments],
                "output": output[:9000],
                "truncated": len(output) > 9000,
            }
        raise ValueError("Choose a predefined desktop shortcut.")

    def _agent_run_command(self, args):
        """Execute an explicitly approved PowerShell command without elevation or shell=True."""
        if sys.platform != "win32":
            raise RuntimeError("Custom command execution is currently supported on Windows only.")
        command = str(args.get("command") or "").strip()
        if not command or len(command) > 6000 or "\x00" in command:
            raise ValueError("Enter a PowerShell command between 1 and 6,000 characters.")
        hard_blocked = (
            r"(?i)\b(format|diskpart|clear-disk|initialize-disk|remove-partition|set-partition|bcdedit|shutdown|restart-computer|stop-computer)\b",
            r"(?i)\breg(?:\.exe)?\s+delete\b",
            r"(?is)start-process\b.*?-verb\s+runas",
            r"(?is)(?:invoke-webrequest|iwr)\b.*?(?:invoke-expression|\biex\b)|(?:invoke-expression|\biex\b).*?(?:invoke-webrequest|iwr)\b",
        )
        if any(re.search(pattern, command) for pattern in hard_blocked):
            raise PermissionDenied(
                "This command matches a blocked system-administration or download-and-execute pattern."
            )
        destructive = (
            r"(?i)\b(remove-item|remove-file|remove-directory|del|erase|rmdir|set-content|out-file|"
            r"move-item|copy-item|rename-item|new-item|install-module|winget\s+install|"
            r"choco\s+install|pip\s+install|npm\s+install)\b"
        )
        if re.search(destructive, command) and (
            AgentPermission.DESTRUCTIVE_ACTIONS not in self.action_registry.permissions
        ):
            raise PermissionDenied(
                "This command may modify or delete data. Enable Destructive actions in Settings first."
            )
        powershell = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
        if not powershell:
            raise FileNotFoundError("PowerShell (pwsh.exe or powershell.exe) was not found.")
        cwd_value = str(args.get("cwd") or "").strip()
        working_directory = Path(cwd_value).expanduser() if cwd_value else Path.home()
        try:
            working_directory = working_directory.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise FileNotFoundError(f"Working directory does not exist: {cwd_value}") from exc
        if not working_directory.is_dir():
            raise ValueError("The command working directory must be an existing folder.")
        try:
            timeout = int(args.get("timeout_seconds", 30))
        except (TypeError, ValueError):
            timeout = 30
        timeout = max(1, min(timeout, 120))
        script = (
            "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding; "
            "$ErrorActionPreference = 'Stop'; " + command
        )
        try:
            result = subprocess.run(
                [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
                cwd=str(working_directory),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            stdout = (
                exc.stdout.decode("utf-8", errors="replace")
                if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
            )
            stderr = (
                exc.stderr.decode("utf-8", errors="replace")
                if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
            )
            return {
                "timed_out": True,
                "timeout_seconds": timeout,
                "stdout": stdout[-8000:],
                "stderr": stderr[-4000:],
                "command": command,
            }
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        return {
            "exit_code": result.returncode,
            "cwd": str(working_directory),
            "command": command,
            "stdout": stdout[:12_000],
            "stderr": stderr[:6_000],
            "truncated": len(stdout) > 12_000 or len(stderr) > 6_000,
            "timed_out": False,
        }

    def _approve_agent_action(self, spec, args):
        details = json.dumps(args, ensure_ascii=False, indent=2, default=str)
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Agent action confirmation")
        dialog.setIcon(QMessageBox.Warning if spec.requires_approval else QMessageBox.Question)
        dialog.setText(f"Allow the Agent to run {spec.name}?")
        dialog.setInformativeText(
            spec.description
            + ("\\n\\nThis command runs as your current user, without administrator elevation."
               if spec.name == "system.run_command" else "")
        )
        dialog.setDetailedText(details)
        dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        dialog.setDefaultButton(QMessageBox.No)
        return dialog.exec() == QMessageBox.Yes

    def toggle_sidebar(self):
        self._sidebar_collapsed = not getattr(self, "_sidebar_collapsed", False)
        width = 76 if self._sidebar_collapsed else 210
        self.sidebar.setMinimumWidth(width)
        self.sidebar.setMaximumWidth(width)
        self.brand_name.setVisible(not self._sidebar_collapsed)
        self.tagline.setVisible(not self._sidebar_collapsed)
        self.sidebar_toggle.setText("Expand sidebar" if self._sidebar_collapsed else "Collapse sidebar")
        for key, _icon, title in self.NAVIGATION:
            button = self.nav_buttons[key]
            button.setText("" if self._sidebar_collapsed else title)
            button.setToolTip(title)
        self.settings_store.update(sidebar_collapsed=self._sidebar_collapsed)

    def _search_library(self):
        self.global_search_popup.activate_current()

    def _on_audio_duration_changed(self, duration_ms):
        self._audio_duration_ms = max(0, int(duration_ms))
        if self.timeline.peaks:
            self.timeline.set_waveform(self.timeline.peaks, self._audio_duration_seconds())

    def _audio_duration_seconds(self):
        return max(0.0, float(self._audio_duration_ms) / 1000.0) if hasattr(self, "_audio_duration_ms") else 0.0

    def _load_waveform(self, audio_path: str):
        self._waveform_generation += 1
        generation = self._waveform_generation
        self._audio_duration_ms = 0
        if not audio_path:
            self.waveform_status = "No audio loaded"
            self.timeline.set_waveform([], 0.0)
            self.timeline.set_segments(self.transcription_page.segments)
            self.timeline.set_position(0.0)
            self.inspector_title.setText("No active audio")
            self.inspector_details.setText("Open an audio file to inspect its waveform and properties.")
            return
        self.waveform_status = "Loading waveform…"
        worker = FunctionWorker(lambda emit: build_waveform(Path(audio_path), self.paths.cache / "waveforms", bins=4096, progress=lambda value: emit(value)))
        worker.signals.progress.connect(lambda _value: None)
        worker.signals.result.connect(lambda peaks, gen=generation: self._waveform_ready(gen, peaks))
        worker.signals.error.connect(lambda message, gen=generation: self._waveform_failed(gen, message))
        self.thread_pool.start(worker)
        self.inspector_title.setText(Path(audio_path).name)
        self.inspector_details.setText(str(audio_path))

    def _waveform_ready(self, generation, peaks):
        if generation != self._waveform_generation:
            return
        duration = self._audio_duration_seconds()
        if duration <= 0 and self.transcription_page.player.player.duration():
            duration = self.transcription_page.player.player.duration() / 1000.0
        self.timeline.set_waveform(peaks, duration)
        self.timeline.set_segments(self.transcription_page.segments)
        self.status_bar.showMessage("Waveform ready", 4000)

    def _waveform_failed(self, generation, message):
        if generation == self._waveform_generation:
            self.status_bar.showMessage(f"Waveform unavailable: {message}", 7000)

    def _on_transcript_changed(self, segments, source_path, language, duration, original_text=""):
        self.editor_page.load_segments(
            segments, source_path=source_path, language=language, duration=duration,
            original_text=original_text,
            text=self.transcription_page.editor.toPlainText(),
            reset_history=True,
        )
        self.subtitle_page.load_segments(segments)
        self.timeline.set_segments(segments)
        self.inspector_title.setText(Path(source_path).name if source_path else "Transcript")
        self.inspector_details.setText(f"{len(segments)} segments · {language or 'language unknown'} · {duration:.1f}s")
        if source_path and Path(source_path).is_file():
            self._load_waveform(source_path)

    def _sync_editor_document(self, document):
        text = document.text
        self.transcription_page._loading_text = True
        self.transcription_page.editor.setPlainText(text)
        self.transcription_page._loading_text = False
        self.transcription_page._editor_base_text = text
        self.transcription_page._pending_text_undo_snapshot = None
        self.transcription_page._rebuild_segment_ranges()
        self.transcription_page._schedule_autosave()
        self.subtitle_page.load_segments(document.segments)
        self.timeline.set_segments(document.segments)

    def _sync_subtitle_document(self, segments):
        before = self.transcript_history.snapshot()
        text = " ".join(item.text.strip() for item in segments if item.text.strip())
        self.transcript_document.replace_all(segments, text=text)
        self.transcript_history.record_snapshot(before)
        self.editor_page.load_segments(
            self.transcript_document.segments,
            source_path=self.transcription_page.audio_path,
            language=self.transcript_document.language,
            duration=self._audio_duration_seconds(),
            original_text=self.transcript_document.original_text,
            text=self.transcript_document.text,
            reset_history=False,
            update_document=False,
        )
        self.transcription_page._loading_text = True
        self.transcription_page.editor.setPlainText(self.transcript_document.text)
        self.transcription_page._loading_text = False
        self.transcription_page._editor_base_text = self.transcript_document.text
        self.transcription_page._pending_text_undo_snapshot = None
        self.transcription_page._rebuild_segment_ranges()
        self.transcription_page._schedule_autosave()
        self.timeline.set_segments(self.transcript_document.segments)

    def _shortcuts(self):
        shortcuts = {
            "Ctrl+O": lambda: self.transcription_page.choose_audio(),
            "Ctrl+S": lambda: self.transcription_page._autosave(),
            "Ctrl+Shift+N": lambda: self.navigate("transcription"),
            "Ctrl+1": lambda: self.navigate("home"),
            "Ctrl+2": lambda: self.navigate("transcription"),
            "Ctrl+3": lambda: self.navigate("recording"),
            "Ctrl+4": lambda: self.navigate("history"),
            "Ctrl+5": lambda: self.navigate("models"),
            "Ctrl+6": lambda: self.navigate("editor"),
            "Ctrl+7": lambda: self.navigate("subtitles"),
            "Ctrl+8": lambda: self.navigate("cleanup"),
            "Ctrl+9": lambda: self.navigate("audio"),
            "Ctrl+K": self.show_command_palette,
            "Ctrl+Shift+B": lambda: self.navigate("batch"),
            "Ctrl+,": lambda: self.navigate("settings"),
        }
        self._shortcut_refs = []
        for sequence, callback in shortcuts.items():
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
            self._shortcut_refs.append(shortcut)

    def navigate(self, page_id: str):
        if page_id not in self.pages:
            page_id = "home"
        title, page = self.pages[page_id]
        self.stack.setCurrentWidget(page)
        self.page_title.setText(title)
        for key, button in self.nav_buttons.items():
            button.setChecked(key == page_id)
        self.settings_store.update(last_page=page_id)
        if page_id == "transcription":
            if not self.transcription_page.is_busy:
                self.transcription_page.refresh_models()
        elif page_id == "home":
            self.home_page.refresh()
        elif page_id == "models":
            self.model_page.refresh_installed()
        elif page_id == "history":
            self.history_page.refresh()
        elif page_id == "settings":
            self.settings_page.refresh_audio_devices()
        elif page_id == "audio":
            self.audio_page.refresh()
        elif page_id == "editor":
            if not self.editor_page.document.segments and self.transcription_page.segments:
                self.editor_page.load_segments(self.transcription_page.segments,
                                               source_path=self.transcription_page.audio_path,
                                               duration=self._audio_duration_seconds())
        elif page_id == "subtitles":
            if not self.subtitle_page.segments and self.transcription_page.segments:
                self.subtitle_page.load_segments(self.transcription_page.segments)

    def open_transcript(self, transcript_id: str):
        if not self.transcription_page.open_history_item(transcript_id):
            return False
        self.navigate("transcription")
        return True

    def open_recording_in_transcriber(self, path: str):
        if not self.transcription_page.set_audio(path):
            return False
        self.navigate("transcription")
        if self.recording_page.auto_transcribe.isChecked():
            QTimer.singleShot(0, self.transcription_page.start_transcription)
        return True

    def _show_recordings_library(self):
        self.audio_page.refresh()
        self.navigate("audio")

    def open_audio_library_file(self, path: str):
        if not self.transcription_page.set_audio(path):
            return False
        self.navigate("transcription")
        return True

    def release_active_model(self):
        # Unloading may wait for an in-flight CTranslate2 inference. Never do
        # that on the GUI thread.
        if self.transcription_page.cancel_event is not None:
            self.status_bar.showMessage("Cancel or finish the active transcription before unloading the model.", 6000)
            return
        worker = FunctionWorker(lambda _emit: self.model_manager.unload_active())
        worker.signals.result.connect(self._active_model_released)
        worker.signals.error.connect(lambda message: self.status_bar.showMessage(f"Model unload failed: {message}", 8000))
        self.thread_pool.start(worker)

    def _active_model_released(self):
        self.transcription_page.engine = None
        self.model_page.refresh_installed()
        self.status_bar.showMessage("Active model unloaded", 4000)

    def _update_worker_limit(self, downloads: int):
        self.model_manager.set_download_concurrency(downloads)
        self.thread_pool.setMaxThreadCount(max(2, min(8, downloads + 2)))

    def apply_theme(self, theme: str):
        effective = "light" if theme == "light" else "dark"
        QApplication.instance().setStyleSheet(stylesheet(effective))
        model_page = getattr(self, "model_page", None)
        if model_page is not None:
            model_page.refresh_visual_theme()

    def _restore_geometry(self):
        encoded = self.settings_store.settings.geometry
        restored = False
        if encoded:
            try:
                restored = self.restoreGeometry(__import__("PySide6.QtCore", fromlist=["QByteArray"]).QByteArray.fromBase64(encoded.encode("ascii")))
            except Exception:
                restored = False
        if not restored:
            screen = self.screen()
            available = screen.availableGeometry() if screen else None
            if available:
                width = min(1180, max(self.minimumWidth(), int(available.width() * 0.82)))
                height = min(820, max(self.minimumHeight(), int(available.height() * 0.84)))
                self.resize(width, height)
                if self.frameGeometry().right() > available.right() or self.frameGeometry().bottom() > available.bottom():
                    self.move(available.center() - self.rect().center())
            else:
                self.resize(1100, 760)
        saved_state = self.settings_store.settings.window_state
        if saved_state:
            try:
                state_text = saved_state
                if saved_state.startswith("v2|"):
                    _version, stored_width, state_text = saved_state.split("|", 2)
                    self._inspector_width = max(320, int(stored_width))
                state = __import__("PySide6.QtCore", fromlist=["QByteArray"]).QByteArray.fromBase64(
                    state_text.encode("ascii")
                )
                self.restoreState(state)
            except (TypeError, ValueError):
                pass
        settings = self.settings_store.settings
        # Inspector is managed by WorkspaceSplitter; only the waveform remains
        # a QMainWindow dock and is permanently constrained to a compact height.
        self.assistant_dock.setMinimumWidth(320)
        self.assistant_dock.setMaximumWidth(16777215)
        self.timeline_dock.setFloating(False)
        self.timeline_dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)
        if self.dockWidgetArea(self.timeline_dock) != Qt.DockWidgetArea.BottomDockWidgetArea:
            self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.timeline_dock)
        self.timeline_dock.setFixedHeight(172)

        self.assistant_dock.setVisible(settings.inspector_visible)
        self.timeline_dock.setVisible(settings.timeline_visible)
        self._sync_drawer_controls(self.assistant_dock, settings.inspector_visible)
        self._sync_drawer_controls(self.timeline_dock, settings.timeline_visible)
        self.sidebar.setVisible(settings.sidebar_visible)
        self.sidebar_action.setChecked(settings.sidebar_visible)
        QTimer.singleShot(0, self._apply_inspector_width)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent):
        if self.transcription_page.is_busy:
            self.status_bar.showMessage(
                "Finish or cancel the current transcription before importing another media job.",
                7000,
            )
            event.ignore()
            return
        raw_paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if not raw_paths:
            event.ignore()
            return
        # A single valid media file is the fast path. Multiple files or a
        # directory are sent to Batch so every dropped item is accounted for.
        if len(raw_paths) == 1:
            candidate = Path(raw_paths[0]).expanduser()
            if candidate.is_file():
                try:
                    valid_path = validate_audio_file(candidate)
                except (OSError, ValueError) as exc:
                    self.batch_page.add_paths(raw_paths)
                    self.navigate("batch")
                    self.status_bar.showMessage(f"Import rejected: {exc}", 8000)
                else:
                    self.open_audio_library_file(str(valid_path))
                event.acceptProposedAction()
                return
        self.batch_page.add_paths(raw_paths)
        self.navigate("batch")
        event.acceptProposedAction()

    def closeEvent(self, event):
        if self.recording_page.recorder._state in {"recording", "paused"}:
            answer = QMessageBox.question(
                self, "Recording in progress", "Save the active recording before closing?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            )
            if answer == QMessageBox.Cancel:
                event.ignore()
                return
            if answer == QMessageBox.Yes:
                self.recording_page.stop_recording()
            else:
                self.recording_page.cancel_recording()
        self.audio_cleanup_page.shutdown()
        self.audio_page.shutdown()
        self.batch_page.shutdown()
        self.settings_store.update(
            geometry=bytes(self.saveGeometry().toBase64()).decode("ascii"),
            window_state=(
                f"v2|{max(320, self._inspector_width)}|"
                f"{bytes(self.saveState().toBase64()).decode('ascii')}"
            ),
            sidebar_collapsed=self._sidebar_collapsed,
            sidebar_visible=self.sidebar.isVisible(),
            inspector_visible=not self.assistant_dock.isHidden(),
            timeline_visible=not self.timeline_dock.isHidden(),
        )
        # Signal all cancellable tasks before draining the bounded pool.
        self.transcription_page.shutdown()
        self.assistant_panel.shutdown()
        if self.ipc_server:
            self.ipc_server.close()
        # Stop accepting Agent work and cancel operations that have not started.
        # A handler already running is allowed to finish; it is never force-killed.
        self.operation_manager.shutdown(wait=False)
        for cancel_event in self.model_page._downloads.values():
            cancel_event.set()
        self.model_manager.cancel_all_downloads()
        # Do not clear queued workers here: cancellable workers have been signalled,
        # and queued cleanup tasks (notably microphone release) must be allowed to run.
        if not self.thread_pool.waitForDone(15000):
            QMessageBox.warning(
                self, "Background task still running",
                "A background task has not stopped yet. The application will stay open; cancel or wait for the task, then close again.",
            )
            event.ignore()
            return
        self.transcription_page.flush_autosave()
        self.model_manager.unload_active()
        self.recording_page.shutdown()
        super().closeEvent(event)
