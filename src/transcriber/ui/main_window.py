"""Native-window application shell and navigation."""

from __future__ import annotations

from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPushButton, QStackedWidget, QStatusBar, QVBoxLayout, QWidget,
)

from transcriber.ui.pages.audio_library import AudioLibraryPage
from transcriber.ui.pages.history import HistoryPage
from transcriber.ui.pages.home import HomePage
from transcriber.ui.pages.models import ModelLibraryPage
from transcriber.ui.pages.recording import RecordingPage
from transcriber.ui.pages.settings import SettingsPage
from transcriber.ui.pages.transcription import TranscriptionPage
from transcriber.ui.theme import stylesheet
from transcriber.ui.workers import FunctionWorker


class MainWindow(QMainWindow):
    NAVIGATION = [
        ("home", "⌂", "Home"),
        ("transcription", "＋", "New transcription"),
        ("recording", "◉", "Live recording"),
        ("history", "◷", "History"),
        ("models", "▦", "Model library"),
        ("audio", "♫", "Audio library"),
        ("settings", "⚙", "Settings"),
    ]

    def __init__(self, paths, settings_store, history, database, model_manager):
        super().__init__()
        self.paths = paths
        self.settings_store = settings_store
        self.history = history
        self.database = database
        self.model_manager = model_manager
        self.thread_pool = QThreadPool(self)
        self.thread_pool.setMaxThreadCount(max(2, min(8, settings_store.settings.download_concurrency + 2)))
        self.setWindowTitle("Transcriber")
        self.setMinimumSize(720, 500)
        self.setAcceptDrops(True)
        self._build_ui()
        self._connect_pages()
        self._restore_geometry()
        self.apply_theme(settings_store.settings.theme)
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
        mark = QLabel("◉")
        mark.setStyleSheet("font-size: 25px; color: #75a7ff; font-weight: 700;")
        brand_name = QLabel("Transcriber")
        brand_name.setStyleSheet("font-size: 18px; font-weight: 700;")
        brand.addWidget(mark)
        brand.addWidget(brand_name)
        brand.addStretch(1)
        side_layout.addLayout(brand)
        tagline = QLabel("VOICE  /  TEXT  /  LOCAL AI")
        tagline.setObjectName("Muted")
        tagline.setStyleSheet("font-size: 9px; letter-spacing: 1px; margin: 2px 0 18px 3px;")
        side_layout.addWidget(tagline)
        self.nav_buttons: dict[str, QPushButton] = {}
        for key, glyph, title in self.NAVIGATION:
            button = QPushButton(f"{glyph}    {title}")
            button.setObjectName("Nav")
            button.setCheckable(True)
            button.setMinimumHeight(40)
            button.clicked.connect(lambda _checked=False, page=key: self.navigate(page))
            self.nav_buttons[key] = button
            side_layout.addWidget(button)
        side_layout.addStretch(1)
        local_status = QLabel("●  LOCAL-FIRST")
        local_status.setStyleSheet("color: #43b68b; font-size: 10px; font-weight: 700; margin: 4px;")
        side_layout.addWidget(local_status)
        version = QLabel("Version 2.0.0")
        version.setObjectName("Muted")
        version.setStyleSheet("font-size: 10px; margin: 4px;")
        side_layout.addWidget(version)
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
        new_button = QPushButton("＋  New transcription")
        new_button.setObjectName("Primary")
        new_button.clicked.connect(lambda: self.navigate("transcription"))
        toolbar_layout.addWidget(self.page_title)
        toolbar_layout.addStretch(1)
        toolbar_layout.addWidget(self.top_status)
        toolbar_layout.addWidget(new_button)
        content_layout.addWidget(toolbar)

        self.stack = QStackedWidget()
        self.home_page = HomePage(history, model_manager, self.thread_pool)
        self.transcription_page = TranscriptionPage(paths, settings_store, history, model_manager, self.thread_pool)
        self.recording_page = RecordingPage(paths)
        self.history_page = HistoryPage(history, self.thread_pool)
        self.model_page = ModelLibraryPage(
            model_manager, settings_store, self.thread_pool, self.release_active_model
        )
        self.audio_page = AudioLibraryPage(paths, history, self.thread_pool)
        self.settings_page = SettingsPage(paths, settings_store, database, self.thread_pool, model_manager)
        self.pages = {
            "home": ("Home", self.home_page),
            "transcription": ("New transcription", self.transcription_page),
            "recording": ("Live recording", self.recording_page),
            "history": ("History", self.history_page),
            "models": ("Model library", self.model_page),
            "audio": ("Audio library", self.audio_page),
            "settings": ("Settings", self.settings_page),
        }
        for _, page in self.pages.values():
            self.stack.addWidget(page)
        content_layout.addWidget(self.stack, 1)
        root_layout.addWidget(content, 1)
        self.setCentralWidget(root)

        status = QStatusBar()
        status.showMessage("Ready · Local-first recognition")
        self.setStatusBar(status)
        self.status_bar = status

    def _connect_pages(self):
        self.home_page.navigate.connect(self.navigate)
        self.home_page.open_transcript.connect(self.open_transcript)
        self.history_page.open_transcript.connect(self.open_transcript)
        self.recording_page.audio_ready.connect(self.open_recording_in_transcriber)
        self.audio_page.open_audio.connect(self.open_audio_library_file)
        for page in (self.transcription_page, self.recording_page, self.history_page,
                     self.model_page, self.settings_page):
            if hasattr(page, "status_message"):
                page.status_message.connect(self.status_bar.showMessage)
        self.settings_page.theme_changed.connect(self.apply_theme)
        self.settings_page.concurrency_changed.connect(self._update_worker_limit)
        self.model_page.default_model_changed.connect(lambda _repo_id: self.transcription_page.refresh_models())

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
            "Ctrl+6": lambda: self.navigate("audio"),
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
        if page_id == "home":
            self.home_page.refresh()
        elif page_id == "models":
            self.model_page.refresh_installed()
        elif page_id == "history":
            self.history_page.refresh()
        elif page_id == "audio":
            self.audio_page.refresh()

    def open_transcript(self, transcript_id: str):
        self.transcription_page.open_history_item(transcript_id)
        self.navigate("transcription")

    def open_recording_in_transcriber(self, path: str):
        self.transcription_page.set_audio(path)
        self.navigate("transcription")
        if self.recording_page.auto_transcribe.isChecked():
            QTimer.singleShot(0, self.transcription_page.start_transcription)

    def open_audio_library_file(self, path: str):
        self.transcription_page.set_audio(path)
        self.navigate("transcription")

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

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent):
        files = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if files:
            self.open_recording_in_transcriber(files[0])
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
        self.settings_store.update(geometry=bytes(self.saveGeometry().toBase64()).decode("ascii"))
        # Signal all cancellable tasks before draining the bounded pool.
        self.transcription_page.shutdown()
        for cancel_event in self.model_page._downloads.values():
            cancel_event.set()
        self.model_manager.downloader.cancel_all()
        self.thread_pool.clear()
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
