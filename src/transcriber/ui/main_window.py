"""Native-window application shell and navigation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
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
    QScrollArea,
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
from transcriber.assistant.powershell import (
    MAX_COMMAND_LENGTH,
    MAX_TIMEOUT_SECONDS,
    build_powershell_script,
    requires_destructive_permission,
)
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
    NAVIGATION_SECTIONS = (
        ("WORKSPACE", ("home", "assistant", "transcription", "recording", "batch")),
        ("LIBRARY & TOOLS", ("history", "editor", "subtitles", "models", "audio", "cleanup")),
        ("PREFERENCES", ("settings",)),
    )

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
        self._assistant_layout_active = False
        self._assistant_previous_sidebar_collapsed = False
        self._assistant_previous_toolbar_hidden = False
        self._assistant_previous_inspector_visible = True
        self.thread_pool = QThreadPool(self)
        self.icon_registry = IconRegistry()
        self.dispatcher = MainThreadDispatcher(self)
        configured_permissions = set()
        for value in settings_store.settings.agent_permissions or []:
            try:
                configured_permissions.add(AgentPermission(value))
            except ValueError:
                continue
        configured_trusted_permissions = set()
        for value in settings_store.settings.agent_trusted_permissions or []:
            try:
                configured_trusted_permissions.add(AgentPermission(value))
            except ValueError:
                continue
        self.action_registry = ActionRegistry(
            permissions=configured_permissions,
            trusted_permissions=configured_trusted_permissions,
            dispatcher=self.dispatcher, approval=self._approve_agent_action,
        )
        self._waveform_generation = 0
        self._shutdown_started = False
        self._shutdown_complete = False
        self._active_agent_approval: QMessageBox | None = None
        self._shutdown_browser_thread: threading.Thread | None = None
        self._shutdown_started_at = 0.0
        self._shutdown_timer = QTimer(self)
        self._shutdown_timer.setInterval(100)
        self._shutdown_timer.timeout.connect(self._poll_shutdown)
        self.thread_pool.setMaxThreadCount(max(2, min(8, settings_store.settings.download_concurrency + 2)))
        self.setWindowTitle("Transcriber")
        self.setMinimumSize(760, 500)
        self.setAcceptDrops(True)
        self._build_ui()
        self._connect_pages()
        self._register_agent_actions()
        self.assistant_panel.set_agent_runtime(self.action_registry)
        self.operation_manager = OperationManager(
            self.action_registry.execute,
            cancellable_action_handler=lambda name, arguments, cancel_event: (
                self.action_registry.execute(
                    name, arguments, cancellation=cancel_event
                )
            ),
        )
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
        sidebar.setMinimumWidth(220)
        sidebar.setMaximumWidth(220)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(13, 18, 13, 14)
        side_layout.setSpacing(8)

        brand = QHBoxLayout()
        brand.setContentsMargins(2, 0, 2, 3)
        brand.setSpacing(9)
        mark = QLabel("T")
        mark.setObjectName("SidebarMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(34, 34)
        self.brand_name = QLabel("Transcriber")
        self.brand_name.setObjectName("SidebarBrand")
        brand.addWidget(mark)
        brand.addWidget(self.brand_name)
        brand.addStretch(1)
        side_layout.addLayout(brand)

        self.tagline = QLabel("VOICE  /  TEXT  /  LOCAL AI")
        self.tagline.setObjectName("SidebarTagline")
        side_layout.addWidget(self.tagline)

        # The navigation scrolls independently; branding and utility controls
        # remain anchored when the application is opened on a short display.
        nav_scroll = QScrollArea(sidebar)
        nav_scroll.setObjectName("SidebarNavigationScroll")
        nav_scroll.setWidgetResizable(True)
        nav_scroll.setFrameShape(QFrame.Shape.NoFrame)
        nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        nav_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        nav_scroll.setMinimumHeight(0)
        nav_content = QWidget()
        nav_content.setObjectName("SidebarNavigationContent")
        nav_layout = QVBoxLayout(nav_content)
        nav_layout.setContentsMargins(0, 7, 0, 7)
        nav_layout.setSpacing(3)

        navigation = {key: (icon_name, title) for key, icon_name, title in self.NAVIGATION}
        self.nav_buttons: dict[str, QPushButton] = {}
        self.sidebar_section_labels: list[QLabel] = []
        tooltips = {
            "recording": "Capture and save a microphone recording; this page does not perform live transcription.",
            "editor": "Correct recognized words, speakers and timed transcript segments.",
            "subtitles": "Edit subtitle cues, validate readability and export subtitle files.",
            "models": "Discover, install and manage local speech-recognition models.",
        }
        for section_title, page_keys in self.NAVIGATION_SECTIONS:
            section_label = QLabel(section_title, nav_content)
            section_label.setObjectName("SidebarSectionLabel")
            self.sidebar_section_labels.append(section_label)
            nav_layout.addWidget(section_label)
            for key in page_keys:
                icon_name, title = navigation[key]
                button = QPushButton(title, nav_content)
                button.setObjectName("Nav")
                button.setIcon(self.icon_registry.icon(icon_name, size=18))
                button.setIconSize(QSize(18, 18))
                button.setToolTip(tooltips.get(key, title))
                button.setAccessibleName(title)
                button.setCheckable(True)
                button.setMinimumHeight(38)
                button.setMinimumWidth(0)
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.clicked.connect(lambda _checked=False, page=key: self.navigate(page))
                self.nav_buttons[key] = button
                nav_layout.addWidget(button)
            nav_layout.addSpacing(7)

        nav_layout.addStretch(1)
        nav_scroll.setWidget(nav_content)
        side_layout.addWidget(nav_scroll, 1)
        self.sidebar_navigation_scroll = nav_scroll
        self.sidebar_navigation_content = nav_content

        self.sidebar_toggle = QPushButton("Collapse sidebar")
        self.sidebar_toggle.setObjectName("SidebarCollapseButton")
        self.sidebar_toggle.setMinimumHeight(36)
        self.sidebar_toggle.clicked.connect(self.toggle_sidebar)
        side_layout.addWidget(self.sidebar_toggle)

        local_status = QLabel("●  LOCAL-FIRST")
        local_status.setObjectName("SidebarLocalStatus")
        side_layout.addWidget(local_status)
        self.local_status = local_status

        version = QLabel("Version 2.1.4")
        version.setObjectName("SidebarVersion")
        side_layout.addWidget(version)
        self.sidebar_version = version
        self.sidebar = sidebar
        root_layout.addWidget(sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        toolbar = QFrame()
        toolbar.setObjectName("TopBar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(22, 10, 22, 10)
        toolbar_layout.setSpacing(10)
        self.page_title = QLabel("Home")
        self.page_title.setObjectName("ToolbarPageTitle")
        self.top_status = QLabel("● Local mode")
        self.top_status.setObjectName("Muted")
        self.global_search = QLineEdit()
        self.global_search.setPlaceholderText("Search projects, transcripts and commands…")
        self.global_search.installEventFilter(self)
        self.global_search.setMinimumWidth(150)
        self.global_search.setMaximumWidth(320)
        self.global_search.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
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
        self.toolbar = toolbar
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
        status.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
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
            # Hiding the Inspector is an implementation detail of immersive
            # Assistant mode. Do not persist that temporary visibility change.
            if setting == "inspector_visible" and getattr(self, "_assistant_layout_active", False):
                break
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
        self._add_menu_action(edit_menu, "Select all", lambda: self._edit_focused_widget("selectAll"), "Ctrl+A")
        view_menu = bar.addMenu("&View")
        self.assistant_view_action = self._add_menu_action(
            view_menu, "Inspector", lambda: self._animate_drawer(
                self.assistant_dock, self.assistant_dock.isHidden(), "width"
            )
        )
        self.assistant_view_action.setCheckable(True)
        self.assistant_view_action.setChecked(not self.assistant_dock.isHidden())
        self.timeline_view_action = self._add_menu_action(
            view_menu, "Waveform", lambda: self._animate_drawer(
                self.timeline_dock, self.timeline_dock.isHidden(), "height"
            )
        )
        self.timeline_view_action.setCheckable(True)
        self.timeline_view_action.setChecked(not self.timeline_dock.isHidden())
        view_menu.addSeparator()
        self._add_menu_action(view_menu, "Collapse sidebar", self.toggle_sidebar, "Ctrl+B")
        self._add_menu_action(view_menu, "Command palette", self.show_command_palette, "Ctrl+K")
        self._add_menu_action(view_menu, "Global search", self.focus_global_search, "Ctrl+Shift+F")

        help_menu = bar.addMenu("&Help")
        self._add_menu_action(help_menu, "About Transcriber", self.show_about_dialog)

    def _shortcuts(self):
        shortcuts = {
            "Ctrl+K": self.show_command_palette,
            "Ctrl+B": self.toggle_sidebar,
            "Ctrl+Shift+F": self.focus_global_search,
            "Ctrl+Shift+N": lambda: self.navigate("transcription"),
        }
        self._shortcut_refs = []
        for sequence, callback in shortcuts.items():
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
            self._shortcut_refs.append(shortcut)

    def navigate(self, page_id: str):
        if page_id not in self.pages:
            page_id = "home"

        if page_id == "assistant" and not self._assistant_layout_active:
            # Reuse the existing MainWindow stack; no second application window.
            # Save the user's layout and restore it verbatim when leaving Assistant.
            self._assistant_layout_active = True
            self._assistant_previous_sidebar_collapsed = self._sidebar_collapsed
            self._assistant_previous_toolbar_hidden = self.toolbar.isHidden()
            self._assistant_previous_inspector_visible = not self.assistant_dock.isHidden()
            self._apply_sidebar_collapsed_state(True, persist=False)
            self.toolbar.hide()
            if not self.assistant_dock.isHidden():
                self.assistant_dock.hide()
        elif page_id != "assistant" and self._assistant_layout_active:
            self._assistant_layout_active = False
            self._apply_sidebar_collapsed_state(
                self._assistant_previous_sidebar_collapsed, persist=False
            )
            self.toolbar.setVisible(not self._assistant_previous_toolbar_hidden)
            self.assistant_dock.setVisible(self._assistant_previous_inspector_visible)

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
        elif page_id == "history":
            self.history_page.refresh()
        elif page_id == "models":
            self.model_page.refresh_installed()
        elif page_id == "audio":
            self.audio_page.refresh()
        elif page_id == "assistant":
            self.assistant_panel.on_page_activated()
        return page

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
                state = __import__("PySide6.QtCore", fromlist=["QByteArray"]).QByteArray.fromBase64(state_text.encode("ascii"))
                self.restoreState(state)
            except Exception:
                pass

    def _save_geometry(self):
        self.settings_store.update(
            geometry=bytes(self.saveGeometry().toBase64()).decode("ascii"),
            window_state=f"v2|{self._inspector_width}|{bytes(self.saveState().toBase64()).decode('ascii')}",
        )

    def closeEvent(self, event):
        if self._shutdown_complete:
            event.accept()
            return
        if self._shutdown_started:
            event.ignore()
            return
        self._shutdown_started = True
        self._shutdown_started_at = time.monotonic()
        self._shutdown_timer.start()
        self._save_geometry()
        self.assistant_panel.begin_shutdown()
        self.recording_page.shutdown()
        self.audio_cleanup_page.shutdown()
        self.batch_page.shutdown()
        self.transcription_page.shutdown()
        event.ignore()

    def _poll_shutdown(self):
        if self._shutdown_complete:
            self._shutdown_timer.stop()
            self.close()
            return
        if self._shutdown_browser_thread is not None and self._shutdown_browser_thread.is_alive():
            return
        if self._shutdown_started_at and time.monotonic() - self._shutdown_started_at > 8:
            # Never block application exit forever on an external browser process.
            self._shutdown_complete = True
            self._shutdown_timer.stop()
            self.close()
            return
        if self.thread_pool.activeThreadCount() == 0:
            self._shutdown_complete = True
            self._shutdown_timer.stop()
            self.close()
