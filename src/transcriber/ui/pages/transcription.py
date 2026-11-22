"""Import, offline transcription, playback, transcript editing and export."""

from __future__ import annotations

import threading
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPalette, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from transcriber.audio.decoder import (
    SUPPORTED_MEDIA_SUFFIXES,
    decoder_help,
    inspect_video_audio_stream,
    is_video_file,
    validate_audio_file,
)
from transcriber.audio.player import AudioPlayer
from transcriber.editor.commands import CommandHistory
from transcriber.editor.document import TranscriptDocument
from transcriber.engines.base import TranscriptionEngine
from transcriber.subtitles.formats import export_subtitles
from transcriber.transcription.exporters import export_transcript
from transcriber.transcription.segments import (
    TranscriptionOptions,
    TranscriptSegment,
    reconcile_segments,
)
from transcriber.transcription.service import TranscriptionService
from transcriber.ui.design.icon_registry import IconRegistry
from transcriber.ui.widgets import page_header, primary_button
from transcriber.ui.workers import FunctionWorker


class TranscriptionPage(QWidget):
    status_message = Signal(str)
    audio_changed = Signal(str)
    transcript_changed = Signal(object, str, str, float, str)
    segments_edited = Signal(object)
    job_state_changed = Signal(bool)

    def __init__(self, paths, settings_store, history, model_manager, thread_pool, parent=None, *, document=None, command_history=None):
        super().__init__(parent)
        self.paths = paths
        self.settings_store = settings_store
        self.history = history
        self.model_manager = model_manager
        self.thread_pool = thread_pool
        self.document = document or TranscriptDocument()
        self.command_history = command_history or CommandHistory(self.document)
        if self.command_history.document is not self.document:
            raise ValueError("TranscriptionPage and CommandHistory must share the same TranscriptDocument")
        self._pending_text_undo_snapshot = None
        self.audio_path: Path | None = None
        self.segments = []
        self.transcript_id: str | None = None
        self.engine: TranscriptionEngine | None = None
        self.cancel_event: threading.Event | None = None
        self._job_engine_id: str | None = None
        self._segment_ranges: list[tuple[int, int, TranscriptSegment]] = []
        self._loading_text = False
        self._record_metadata: dict | None = None
        self._editor_base_text = ""
        self._save_inflight = False
        self._save_queue: list[dict] = []
        self._load_generation = 0
        self._history_load_pending = False

        self._icons = IconRegistry()
        icon_muted = self.palette().color(QPalette.ColorRole.Mid).name()

        self.setObjectName("NewTranscriptionPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 10, 10)
        layout.setSpacing(8)
        layout.addWidget(page_header(
            "New transcription",
            "Import media, choose recognition options, then edit and export the result.",
        ))

        # Keep source selection compact; the transcript workspace owns the
        # majority of the available page height.
        scroll = QScrollArea(self)
        scroll.setObjectName("NewTranscriptionScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        content = QWidget()
        content.setObjectName("NewTranscriptionContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 8, 0)
        content_layout.setSpacing(8)

        source_bar = QFrame()
        source_bar.setObjectName("TranscriptionSourceBar")
        source_layout = QHBoxLayout(source_bar)
        source_layout.setContentsMargins(4, 2, 4, 8)
        source_layout.setSpacing(9)

        source_label = QLabel("SOURCE")
        source_label.setObjectName("TranscriptionSourceLabel")
        source_layout.addWidget(source_label)

        self.open_button = primary_button("Open media")
        self.open_button.setObjectName("TranscriptionChooseMedia")
        self.open_button.setFixedHeight(34)
        self.open_button.setIcon(self._icons.icon("projects", "#ffffff", 16))
        self.open_button.setIconSize(QSize(16, 16))
        self.open_button.clicked.connect(self.choose_audio)
        self.open_button.setToolTip("Import an audio file or a video that contains an audio track.")

        self.file_name = QLabel("No media selected")
        self.file_name.setObjectName("TranscriptionFileName")
        self.file_name.setMinimumHeight(30)
        self.file_name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.file_name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.close_audio_button = QPushButton()
        self.close_audio_button.setObjectName("TranscriptionCloseMedia")
        self.close_audio_button.setFixedSize(30, 30)
        self.close_audio_button.setIcon(self._icons.icon("discard", icon_muted, 15))
        self.close_audio_button.setIconSize(QSize(15, 15))
        self.close_audio_button.setToolTip("Close the loaded audio file")
        self.close_audio_button.setAccessibleName("Close audio")
        self.close_audio_button.setEnabled(False)
        self.close_audio_button.clicked.connect(self.close_audio)

        source_layout.addWidget(self.open_button)
        source_layout.addWidget(self.file_name, 1)
        source_layout.addWidget(self.close_audio_button)
        content_layout.addWidget(source_bar)

        # One compact setup panel: primary engine/model/language/task controls
        # share one row, while optional tuning stays on a second, low-profile row.
        settings_panel = QFrame()
        settings_panel.setObjectName("TranscriptionSettingsPanel")
        settings_outer = QVBoxLayout(settings_panel)
        settings_outer.setContentsMargins(13, 10, 13, 9)
        settings_outer.setSpacing(7)

        settings_heading = QHBoxLayout()
        settings_heading.setSpacing(8)
        settings_title = QLabel("Recognition")
        settings_title.setObjectName("TranscriptionSettingsTitle")
        settings_hint = QLabel("Engine, model and output")
        settings_hint.setObjectName("TranscriptionSectionHint")
        settings_heading.addWidget(settings_title)
        settings_heading.addWidget(settings_hint)
        settings_heading.addStretch(1)
        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setObjectName("TranscriptionAdvancedToggle")
        self.advanced_toggle.setText("Advanced options")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        settings_heading.addWidget(self.advanced_toggle)
        settings_outer.addLayout(settings_heading)

        settings_grid = QGridLayout()
        settings_grid.setContentsMargins(0, 0, 0, 0)
        settings_grid.setHorizontalSpacing(10)
        settings_grid.setVerticalSpacing(4)
        for column, stretch in enumerate((3, 4, 2, 3)):
            settings_grid.setColumnStretch(column, stretch)

        def add_setting_label(text: str, row: int, column: int, span: int = 1):
            label = QLabel(text)
            label.setObjectName("TranscriptionFieldLabel")
            settings_grid.addWidget(label, row, column, 1, span)
            return label

        self.engine_combo = QComboBox()
        self.engine_combo.addItem("Faster-Whisper · Local", "faster-whisper")
        self.engine_combo.addItem("Vosk / Kaldi · Offline", "vosk")
        self.engine_combo.addItem("Google Cloud STT V2 · Online", "google-cloud")
        self.engine_combo.addItem(
            "Google Web Speech · Experimental (no login)", "google-web"
        )
        self.engine_combo.setItemData(
            self.engine_combo.findData("google-web"),
            "Legacy Chromium-compatible Google endpoint. Shared key, no login, no guarantee; "
            "audio is sent to Google and requires the Cloud consent switch.",
            Qt.ToolTipRole,
        )
        self.engine_combo.setCurrentIndex(max(
            0, self.engine_combo.findData(self.settings_store.settings.default_engine)
        ))
        self.engine_combo.currentIndexChanged.connect(self._update_engine_controls)

        self.model_combo = QComboBox()
        self.model_combo.setMinimumContentsLength(18)
        self.model_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.refresh_models()

        self.default_model_button = QPushButton("Default")
        self.default_model_button.setObjectName("TranscriptionDefaultModel")
        self.default_model_button.setFixedHeight(32)
        self.default_model_button.setToolTip(
            "Make the selected installed Faster-Whisper model the default for new transcriptions."
        )
        self.default_model_button.clicked.connect(self.set_selected_model_as_default)
        self.model_combo.currentIndexChanged.connect(self._update_default_model_control)

        model_field = QWidget()
        model_field_layout = QHBoxLayout(model_field)
        model_field_layout.setContentsMargins(0, 0, 0, 0)
        model_field_layout.setSpacing(6)
        model_field_layout.addWidget(self.model_combo, 1)
        model_field_layout.addWidget(self.default_model_button)

        self.language_combo = QComboBox()
        self.language_combo.addItem("Auto detect (local)", "auto")
        for code, name in [
            ("en", "English"), ("fa", "Persian"), ("de", "German"),
            ("fr", "French"), ("es", "Spanish"), ("ar", "Arabic"),
            ("ru", "Russian"), ("zh", "Chinese"), ("ja", "Japanese"),
        ]:
            self.language_combo.addItem(name, code)

        self.task_combo = QComboBox()
        self.task_combo.addItem("Transcribe", "transcribe")
        self.task_combo.addItem("Translate to English", "translate")

        add_setting_label("ENGINE", 0, 0)
        add_setting_label("MODEL", 0, 1)
        add_setting_label("LANGUAGE", 0, 2)
        add_setting_label("TASK", 0, 3)
        settings_grid.addWidget(self.engine_combo, 1, 0)
        settings_grid.addWidget(model_field, 1, 1)
        settings_grid.addWidget(self.language_combo, 1, 2)
        settings_grid.addWidget(self.task_combo, 1, 3)
        settings_outer.addLayout(settings_grid)

        self.beam_spin = QSpinBox()
        self.beam_spin.setRange(1, 20)
        self.beam_spin.setValue(self.settings_store.settings.beam_size)
        self.beam_spin.setFixedWidth(60)
        self.vad_check = QCheckBox("Voice activity detection")
        self.vad_check.setChecked(self.settings_store.settings.vad_filter)
        self.word_timestamps = QCheckBox("Word-level timings")
        self.word_timestamps.setChecked(self.settings_store.settings.word_timestamps)
        self.word_timestamps.toggled.connect(
            lambda value: self.settings_store.update(word_timestamps=value)
        )

        self.initial_prompt = QLineEdit()
        self.initial_prompt.setPlaceholderText("Optional vocabulary, names or context…")
        self.initial_prompt.setToolTip(
            "This setting is supported by Faster-Whisper, not Google Cloud Speech-to-Text V2."
        )

        options_row = QHBoxLayout()
        options_row.setSpacing(10)
        beam_label = QLabel("BEAM")
        beam_label.setObjectName("TranscriptionInlineLabel")
        options_row.addWidget(beam_label)
        options_row.addWidget(self.beam_spin)
        options_row.addWidget(self.vad_check)
        options_row.addWidget(self.word_timestamps)
        options_row.addWidget(self.initial_prompt, 1)
        advanced_content = QWidget(settings_panel)
        advanced_layout = QVBoxLayout(advanced_content)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.addLayout(options_row)
        advanced_content.setVisible(False)
        self.advanced_toggle.toggled.connect(
            lambda expanded: (
                advanced_content.setVisible(expanded),
                self.advanced_toggle.setArrowType(
                    Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
                ),
            )
        )
        settings_outer.addWidget(advanced_content)

        privacy_row = QHBoxLayout()
        privacy_row.setContentsMargins(1, 0, 0, 0)
        privacy_row.setSpacing(7)
        privacy_mark = QLabel("i")
        privacy_mark.setObjectName("TranscriptionPrivacyMark")
        privacy_mark.setFixedSize(16, 16)
        privacy_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.engine_privacy_hint = QLabel()
        self.engine_privacy_hint.setObjectName("TranscriptionPrivacyHint")
        self.engine_privacy_hint.setWordWrap(True)
        privacy_row.addWidget(privacy_mark, 0, Qt.AlignmentFlag.AlignTop)
        privacy_row.addWidget(self.engine_privacy_hint, 1)
        settings_outer.addLayout(privacy_row)
        content_layout.addWidget(settings_panel)

        # The player is a transport strip inside the main editing workspace,
        # not a separate tall card competing with the transcript.
        workspace = QFrame()
        workspace.setObjectName("TranscriptionWorkspace")
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(12, 10, 12, 11)
        workspace_layout.setSpacing(9)

        player_bar = QFrame()
        player_bar.setObjectName("TranscriptionPlayerBar")
        playback_row = QHBoxLayout(player_bar)
        playback_row.setContentsMargins(8, 5, 8, 5)
        playback_row.setSpacing(9)

        self.player = AudioPlayer(self)
        self.player_status = QLabel("No audio loaded")
        self.player_status.setObjectName("TranscriptionPlayerStatus")
        self.player_status.setMinimumWidth(84)
        self.player_status.setMaximumWidth(112)
        self.player_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.player.status_changed.connect(self.player_status.setText)

        self.play_button = QPushButton()
        self.play_button.setObjectName("TranscriptionPlayButton")
        self.play_button.setFixedSize(36, 36)
        self.play_button.setIcon(self._icons.icon("play", "#ffffff", 16))
        self.play_button.setIconSize(QSize(16, 16))
        self.play_button.setEnabled(False)
        self.play_button.setAccessibleName("Play or pause audio")
        self.play_button.setToolTip("Play or pause audio")
        self.play_button.clicked.connect(self.player.play_pause)
        self.player.playback_changed.connect(
            lambda playing: self.play_button.setIcon(
                self._icons.icon("pause" if playing else "play", "#ffffff", 16)
            )
        )

        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setObjectName("TranscriptionSeekSlider")
        self.seek_slider.setRange(0, 0)
        self.seek_slider.setFixedHeight(22)
        self.seek_slider.sliderMoved.connect(self.player.seek)
        self.player.position_changed.connect(self._position_changed)
        self.player.duration_changed.connect(self._duration_changed)

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setObjectName("TranscriptionPlaybackTime")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setFixedWidth(104)

        self.speed_combo = QComboBox()
        for speed in ("0.75×", "1.0×", "1.25×", "1.5×", "2.0×"):
            self.speed_combo.addItem(speed, float(speed[:-1]))
        self.speed_combo.setCurrentIndex(1)
        self.speed_combo.setFixedSize(76, 30)
        self.speed_combo.setToolTip("Playback speed")
        self.speed_combo.currentIndexChanged.connect(
            lambda: self.player.set_speed(self.speed_combo.currentData())
        )

        self.volume_label = QLabel("VOL")
        self.volume_label.setObjectName("TranscriptionInlineLabel")
        self.volume_label.setToolTip("Playback volume")
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setObjectName("TranscriptionVolumeSlider")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(75)
        self.volume_slider.setFixedSize(78, 20)
        self.volume_slider.setToolTip("Playback volume")
        self.volume_slider.valueChanged.connect(self.player.set_volume)

        playback_row.addWidget(self.player_status)
        playback_row.addWidget(self.play_button)
        playback_row.addWidget(self.time_label)
        playback_row.addWidget(self.seek_slider, 1)
        playback_row.addWidget(self.speed_combo)
        playback_row.addWidget(self.volume_label)
        playback_row.addWidget(self.volume_slider)
        workspace_layout.addWidget(player_bar)

        editor_heading = QHBoxLayout()
        editor_heading.setSpacing(8)
        editor_title = QLabel("Transcript")
        editor_title.setObjectName("TranscriptionSectionTitle")
        self.word_count = QLabel("0 words · 0 characters")
        self.word_count.setObjectName("TranscriptionWordCount")
        editor_heading.addWidget(editor_title)
        editor_heading.addStretch(1)
        editor_heading.addWidget(self.word_count)
        workspace_layout.addLayout(editor_heading)

        # Search and replace share a single compact toolbar rather than taking
        # two full-width rows away from the editor.
        tools_row = QHBoxLayout()
        tools_row.setSpacing(7)
        self.search_input = QLineEdit()
        self.search_input.setObjectName("TranscriptionSearch")
        self.search_input.setPlaceholderText("Find in transcript…")
        self.search_input.returnPressed.connect(self.find_next)

        self.find_button = QPushButton("Find")
        self.find_button.setObjectName("TranscriptionToolButton")
        self.find_button.setFixedSize(72, 32)
        self.find_button.setIcon(self._icons.icon("search", icon_muted, 14))
        self.find_button.setIconSize(QSize(14, 14))
        self.find_button.clicked.connect(self.find_next)

        self.replace_input = QLineEdit()
        self.replace_input.setObjectName("TranscriptionReplace")
        self.replace_input.setPlaceholderText("Replace with…")
        self.replace_button = QPushButton("Replace")
        self.replace_button.setObjectName("TranscriptionToolButton")
        self.replace_button.setFixedSize(82, 32)
        self.replace_button.clicked.connect(self.replace_selected)

        self.copy_button = QPushButton("Copy all")
        self.copy_button.setObjectName("TranscriptionToolButton")
        self.copy_button.setFixedSize(78, 32)
        self.copy_button.clicked.connect(self.copy_all)

        tools_row.addWidget(self.search_input, 3)
        tools_row.addWidget(self.find_button)
        tools_row.addWidget(self.replace_input, 2)
        tools_row.addWidget(self.replace_button)
        tools_row.addWidget(self.copy_button)
        workspace_layout.addLayout(tools_row)

        self.editor = QPlainTextEdit()
        self.editor.setObjectName("TranscriptionEditor")
        self.editor.setPlaceholderText(
            "Your transcript will appear here. You can edit it at any time."
        )
        self.editor.setTabChangesFocus(True)
        self.editor.setUndoRedoEnabled(False)
        self.editor.setMinimumHeight(340)
        self.editor.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._search_highlight_timer = QTimer(self)
        self._search_highlight_timer.setSingleShot(True)
        self._search_highlight_timer.setInterval(1800)
        self._search_highlight_timer.timeout.connect(self._clear_search_highlight)
        self._search_highlight_range: tuple[int, int] | None = None
        self.editor.textChanged.connect(self._schedule_autosave)
        self.editor.textChanged.connect(self._clear_search_highlight)
        workspace_layout.addWidget(self.editor, 1)

        editor_footer = QHBoxLayout()
        self.include_timestamps = QCheckBox("Include timestamps")
        self.include_timestamps.setChecked(True)
        self.export_button = QPushButton("Export text")
        self.export_button.setObjectName("TranscriptionToolButton")
        self.export_button.setFixedHeight(34)
        self.export_button.clicked.connect(self.export)
        self.subtitle_export_button = primary_button("Export subtitles")
        self.subtitle_export_button.setObjectName("TranscriptionExportSubtitles")
        self.subtitle_export_button.setFixedHeight(34)
        self.subtitle_export_button.setToolTip(
            "Export timed transcript segments as SRT, WebVTT, ASS or SSA."
        )
        self.subtitle_export_button.setEnabled(False)
        self.subtitle_export_button.clicked.connect(self.export_subtitles)
        editor_footer.addWidget(self.include_timestamps)
        editor_footer.addStretch(1)
        editor_footer.addWidget(self.export_button)
        editor_footer.addWidget(self.subtitle_export_button)
        workspace_layout.addLayout(editor_footer)

        content_layout.addWidget(workspace, 1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        # Progress occupies its own hairline above the action row. At rest the
        # footer stays compact; during a job the progress track spans the page.
        action_bar = QFrame(self)
        action_bar.setObjectName("TranscriptionActionBar")
        action_layout = QVBoxLayout(action_bar)
        action_layout.setContentsMargins(0, 7, 0, 0)
        action_layout.setSpacing(5)

        self.progress = QProgressBar()
        self.progress.setObjectName("TranscriptionProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.setVisible(False)

        action_controls = QHBoxLayout()
        action_controls.setSpacing(9)
        self.progress_label = QLabel("Ready")
        self.progress_label.setObjectName("TranscriptionProgressLabel")

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("TranscriptionCancel")
        self.cancel_button.setFixedHeight(36)
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancel_transcription)

        self.start_button = primary_button("Start transcription")
        self.start_button.setObjectName("TranscriptionStart")
        self.start_button.setFixedHeight(38)
        self.start_button.setMinimumWidth(184)
        self.start_button.clicked.connect(self.start_transcription)

        action_controls.addWidget(self.progress_label, 1)
        action_controls.addWidget(self.cancel_button)
        action_controls.addWidget(self.start_button)
        action_layout.addWidget(self.progress)
        action_layout.addLayout(action_controls)
        layout.addWidget(action_bar)

        self._update_engine_controls()

        self.autosave_timer = QTimer(self)
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.setInterval(800)
        self.autosave_timer.timeout.connect(self._autosave)
        self.editor.textChanged.connect(self._update_word_count)
        self.player.position_changed.connect(self._sync_transcript_to_audio)
        self.player.error_occurred.connect(lambda message: self.status_message.emit(f"Audio player: {message}"))
        self._busy_controls = (
            self.open_button, self.engine_combo, self.model_combo,
            self.default_model_button, self.language_combo, self.beam_spin,
            self.vad_check, self.task_combo, self.word_timestamps,
            self.initial_prompt, self.advanced_toggle, self.search_input, self.find_button,
            self.replace_input, self.replace_button, self.copy_button,
            self.editor, self.include_timestamps, self.export_button,
            self.subtitle_export_button,
        )
        self._refresh_busy_controls()

    @property
    def is_busy(self) -> bool:
        return self.cancel_event is not None or self._history_load_pending

    def _has_timed_subtitles(self) -> bool:
        return any(item.text.strip() and item.end > item.start for item in self.segments)

    def _refresh_busy_controls(self):
        busy = self.is_busy
        if busy:
            for control in self._busy_controls:
                control.setEnabled(False)
            self.start_button.setEnabled(False)
            self.close_audio_button.setEnabled(False)
            self.export_button.setEnabled(False)
            self.subtitle_export_button.setEnabled(False)
        else:
            # Re-enable the controls disabled by the busy state first. The
            # engine-specific updater below then applies capability restrictions
            # (for example, no local model selector for Google engines).
            for control in self._busy_controls:
                control.setEnabled(True)
            self._update_engine_controls()
            self.start_button.setEnabled(True)
            self.close_audio_button.setEnabled(self.audio_path is not None)
            self.export_button.setEnabled(bool(self.editor.toPlainText().strip()))
            self.subtitle_export_button.setEnabled(self._has_timed_subtitles())
        self.cancel_button.setVisible(self.cancel_event is not None)
        self.cancel_button.setEnabled(
            self.cancel_event is not None and not self.cancel_event.is_set()
        )
        self.job_state_changed.emit(busy)

    def _update_engine_controls(self, *_args):
        engine_id = self.engine_combo.currentData()
        google_cloud_selected = engine_id == "google-cloud"
        google_web_selected = engine_id == "google-web"
        online_selected = google_cloud_selected or google_web_selected
        vosk_selected = engine_id == "vosk"
        if hasattr(self, "model_combo"):
            self.refresh_models()
        self.model_combo.setEnabled(not online_selected)
        if hasattr(self, "default_model_button"):
            self.default_model_button.setVisible(not online_selected and not vosk_selected)
            self._update_default_model_control()
        self.beam_spin.setEnabled(not online_selected and not vosk_selected)
        self.vad_check.setEnabled(not online_selected and not vosk_selected)
        self.task_combo.setEnabled(not online_selected and not vosk_selected)
        self.initial_prompt.setEnabled(not online_selected and not vosk_selected)
        self.word_timestamps.setEnabled(not google_web_selected)
        if (online_selected or vosk_selected) and self.task_combo.currentData() != "transcribe":
            self.task_combo.setCurrentIndex(self.task_combo.findData("transcribe"))
        if hasattr(self, "start_button"):
            self.start_button.setText(
                "Send to Google Cloud" if google_cloud_selected
                else "Send to Google Web Speech" if google_web_selected
                else "Start Vosk transcription" if vosk_selected
                else "Start transcription"
            )
        self.engine_privacy_hint.setText(
            "Supported online processing: audio is sent to Google Cloud Speech-to-Text V2. "
            "A project ID, Application Default Credentials and explicit Cloud consent are required. "
            "Choose a specific language."
            if google_cloud_selected else
            "Experimental compatibility mode: audio is sent to Google's legacy Web Speech endpoint "
            "over HTTPS using a shared public Chromium key. No account or Cloud project is needed, "
            "but Google may rate-limit or disable the endpoint at any time. It provides chunk-level "
            "timing only. Use only for short, non-sensitive audio and choose a specific language."
            if google_web_selected else
            "Local processing: Vosk / Kaldi runs offline using the selected Vosk model. No audio is uploaded."
            if vosk_selected else
            "Local processing: Faster-Whisper runs on this device. Audio is not uploaded by this engine."
        )

    @property
    def segments(self) -> list[TranscriptSegment]:
        return self.document.segments

    @segments.setter
    def segments(self, values):
        self.document.replace_all(list(values or []))

    def refresh_models(self, *, select_default: bool = False):
        selected = self.model_combo.currentData() if hasattr(self, "model_combo") else None
        selected_engine = (
            self.engine_combo.currentData() if hasattr(self, "engine_combo") else "faster-whisper"
        )
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        if selected_engine in {"google-cloud", "google-web"}:
            self.model_combo.addItem("Managed by Google · no local model required", None)
            self.model_combo.blockSignals(False)
            self._update_default_model_control()
            return
        installed = self.model_manager.installed(include_sizes=False)
        target_runtime = "vosk" if selected_engine == "vosk" else "faster-whisper"
        models = sorted(
            (
                item for item in installed
                if item.get("compatible")
                and str(item.get("runtime") or "faster-whisper") == target_runtime
            ),
            key=lambda item: str(item["repo_id"]).casefold(),
        )
        preferred = (
            self.settings_store.settings.vosk_default_model
            if target_runtime == "vosk"
            else self.settings_store.settings.default_model
        )
        if preferred:
            models.sort(key=lambda item: (
                item["repo_id"] != preferred,
                str(item["repo_id"]).casefold(),
            ))

        for model in models:
            repo_id = model["repo_id"]
            if target_runtime == "vosk":
                language = str(model.get("language_name") or model.get("language_code") or "Unknown language")
                label = f"Vosk · {language} · {repo_id}"
                if repo_id == preferred:
                    label = f"★  {label} · DEFAULT"
                tooltip = f"{repo_id} — Vosk / Kaldi · {language}"
            else:
                label = f"★  {repo_id}  ·  DEFAULT" if repo_id == preferred else repo_id
                tooltip = f"{repo_id} — {'Default model' if repo_id == preferred else 'Installed Faster-Whisper model'}"
            self.model_combo.addItem(label, repo_id)
            self.model_combo.setItemData(self.model_combo.count() - 1, tooltip, Qt.ToolTipRole)

        if not models:
            description = (
                "No compatible Vosk models installed. Open Model Library → Discover → Vosk."
                if target_runtime == "vosk"
                else "Install or import a Faster-Whisper model from Model Library."
            )
            self.model_combo.addItem("No compatible models installed", None)
            self.model_combo.setItemData(0, description, Qt.ToolTipRole)
        else:
            target = preferred if select_default or selected not in {item["repo_id"] for item in models} else selected
            index = self.model_combo.findData(target)
            self.model_combo.setCurrentIndex(index if index >= 0 else 0)
        self.model_combo.blockSignals(False)
        self._update_default_model_control()

    def _update_default_model_control(self, *_args):
        if not hasattr(self, "default_model_button"):
            return
        selected = self.model_combo.currentData()
        selected_engine = self.engine_combo.currentData()
        configured_default = (
            self.settings_store.settings.vosk_default_model
            if selected_engine == "vosk"
            else self.settings_store.settings.default_model
        )
        is_default = bool(selected and selected == configured_default)
        cloud_selected = selected_engine in {"google-cloud", "google-web"}
        vosk_selected = selected_engine == "vosk"
        self.default_model_button.setVisible(not cloud_selected and not vosk_selected)
        self.default_model_button.setText("★  Default model" if is_default else "Set as default")
        self.default_model_button.setEnabled(
            bool(selected) and not is_default and not cloud_selected and not vosk_selected
        )
        self.default_model_button.setToolTip(
            f"{selected} is the default model." if is_default
            else "Set the selected installed Faster-Whisper model as the default for future jobs."
        )

    def set_selected_model_as_default(self):
        repo_id = self.model_combo.currentData()
        if not repo_id:
            return
        if self.engine_combo.currentData() == "vosk":
            self.settings_store.update(vosk_default_model=repo_id)
            engine_name = "Vosk"
        else:
            self.settings_store.update(default_model=repo_id)
            engine_name = "Faster-Whisper"
        self.refresh_models(select_default=True)
        self.status_message.emit(f"Default {engine_name} model set to {repo_id}")

    def choose_audio(self):
        if self.is_busy:
            self.status_message.emit("Finish the current operation before selecting another media file.")
            return False
        suffixes = " ".join(f"*{suffix}" for suffix in sorted(SUPPORTED_MEDIA_SUFFIXES))
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose audio or video", str(self.paths.recordings),
            f"Audio and video ({suffixes});;All files (*)",
        )
        return self.set_audio(path) if path else False

    def set_audio(self, path: str | Path) -> bool:
        if self.is_busy:
            self.status_message.emit(
                "The current transcription must finish before another media file can be loaded."
            )
            return False
        try:
            audio = validate_audio_file(Path(path))
        except Exception as exc:
            QMessageBox.warning(self, "Cannot import media", f"{exc}\n\n{decoder_help()}")
            return False
        if self.audio_path is not None and self.audio_path.resolve() != audio.resolve():
            self._autosave()
            self.command_history.clear()
            self._pending_text_undo_snapshot = None
            self.transcript_id = None
            self._record_metadata = None
            self.segments = []
            self._editor_base_text = ""
            self._loading_text = True
            self.editor.clear()
            self._loading_text = False
            self._rebuild_segment_ranges()
            self._update_word_count()
        self.audio_path = audio
        self.close_audio_button.setEnabled(True)
        self.play_button.setEnabled(True)
        media_kind = "Video" if is_video_file(audio) else "Audio"
        self.file_name.setText(f"{media_kind} · {audio.name}")
        self.file_name.setToolTip(str(audio))
        self.player.set_source(str(audio))
        self.progress_label.setText(f"{media_kind} ready")
        self.audio_changed.emit(str(audio))
        self._refresh_busy_controls()
        return True

    def close_audio(self) -> bool:
        if self.is_busy:
            self.status_message.emit("The current operation must finish before its media source can be closed.")
            return False
        self._autosave()
        self.player.stop()
        self.player.clear_source()
        self.audio_path = None
        self._audio_duration_ms = 0
        self.file_name.setText("No media selected")
        self.file_name.setToolTip("")
        self.close_audio_button.setEnabled(False)
        self.player_status.setText("No media loaded")
        self.play_button.setEnabled(False)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.setValue(0)
        self.time_label.setText("00:00 / 00:00")
        self.audio_changed.emit("")
        self.progress_label.setText("Media closed · transcript preserved")
        self.status_message.emit("Media closed; transcript and edits were kept.")
        self._refresh_busy_controls()
        return True

    def start_transcription(self):
        if self.is_busy:
            self.status_message.emit("A transcription or history operation is already running.")
            return
        if self.audio_path is None:
            self.choose_audio()
            if self.audio_path is None:
                return
        engine_id = self.engine_combo.currentData()
        repo_id = self.model_combo.currentData()
        configured = self.settings_store.settings
        google_cloud_selected = engine_id == "google-cloud"
        google_web_selected = engine_id == "google-web"
        online_selected = google_cloud_selected or google_web_selected
        vosk_selected = engine_id == "vosk"
        if not online_selected and not repo_id:
            QMessageBox.information(
                self, "Model required",
                "Install a compatible Vosk or Faster-Whisper model for the selected engine in Model Library first.",
            )
            return
        if online_selected:
            if configured.local_only or not configured.cloud_consent:
                QMessageBox.warning(
                    self, "Online recognition is disabled",
                    "This engine sends the selected audio to Google. Disable Local-only mode and explicitly grant online audio consent in Settings before starting this job.",
                )
                return
            if self.language_combo.currentData() == "auto":
                QMessageBox.information(
                    self, "Choose a language",
                    "Google's online recognition endpoints require an explicit language. Choose a language instead of Auto detect.",
                )
                return
        language = None if self.language_combo.currentData() == "auto" else self.language_combo.currentData()
        if google_cloud_selected:
            language = {
                "en": "en-US", "fa": "fa-IR", "de": "de-DE", "fr": "fr-FR",
                "es": "es-ES", "ar": "ar-SA", "ru": "ru-RU", "zh": "cmn-Hans-CN",
                "ja": "ja-JP",
            }.get(language, language)
        options = TranscriptionOptions(
            language=language,
            task="transcribe" if online_selected or vosk_selected else self.task_combo.currentData(),
            beam_size=self.beam_spin.value(),
            vad_filter=self.vad_check.isChecked(),
            word_timestamps=self.word_timestamps.isChecked(),
            initial_prompt=None if online_selected or vosk_selected else self.initial_prompt.text().strip() or None,
        )
        changes = {"word_timestamps": self.word_timestamps.isChecked()}
        if not online_selected and not vosk_selected:
            # Picking a model for this one job must not silently change the
            # separately configured default model.
            changes.update(beam_size=self.beam_spin.value(), vad_filter=self.vad_check.isChecked())
        self.settings_store.update(**changes)
        audio_path = self.audio_path
        cancel_event = threading.Event()
        self.cancel_event = cancel_event
        self._job_engine_id = engine_id
        self._refresh_busy_controls()
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.progress_label.setText(
            "Preparing local recognition engine…" if not online_selected
            else "Preparing local audio chunks for Google Cloud…" if google_cloud_selected
            else "Preparing audio chunks for Google Web Speech…"
        )
        model_id = repo_id if not online_selected else None
        worker = FunctionWorker(lambda emit: self._run_transcription(
            emit, configured, engine_id, repo_id, audio_path, options, cancel_event, model_id
        ))
        worker.signals.progress.connect(self._on_progress)
        worker.signals.result.connect(self._on_transcription_complete)
        worker.signals.error.connect(self._on_transcription_error)
        worker.signals.finished.connect(self._finish_worker)
        self.thread_pool.start(worker)

    def _run_transcription(
        self, emit, configured, engine_id, repo_id, audio_path, options, cancel_event, model_id
    ):
        if cancel_event.is_set():
            raise InterruptedError("Transcription cancelled before engine preparation")
        if is_video_file(audio_path):
            emit((0.0, "Inspecting the video's audio track…"))
            media_info = inspect_video_audio_stream(audio_path)
            if media_info.audio_stream_count > 1:
                emit((0.0, f"Video contains {media_info.audio_stream_count} audio tracks · using the first track"))
            else:
                emit((0.0, "Reading the video's audio track for transcription…"))
        if engine_id in {"google-cloud", "google-web"}:
            self.model_manager.unload_active()
            if engine_id == "google-cloud":
                from transcriber.engines.cloud import GoogleCloudEngine
                engine = GoogleCloudEngine(
                    consent_granted=True,
                    project_id=configured.google_cloud_project or None,
                    location=configured.google_cloud_location,
                    model=configured.google_cloud_model,
                )
            else:
                from transcriber.engines.google_web import GoogleWebSpeechEngine
                engine = GoogleWebSpeechEngine(consent_granted=True)
        else:
            engine = self.model_manager.get_engine(repo_id, configured)
        service = TranscriptionService(engine, self.history)
        try:
            result = service.transcribe(
                audio_path, options, cancel_event=cancel_event,
                progress=lambda percent, message: emit((percent, message)),
                title=Path(audio_path).stem, model_id=model_id,
            )
            return engine, result
        finally:
            if engine_id in {"google-cloud", "google-web"}:
                engine.unload()

    def cancel_transcription(self):
        if self.cancel_event:
            self.cancel_event.set()
            message = (
                "Cancellation requested · waiting for the current Google request"
                if self._job_engine_id in {"google-cloud", "google-web"}
                else "Cancelling…"
            )
            self.progress_label.setText(message)
            self.cancel_button.setEnabled(False)

    def _on_progress(self, value):
        percent, message = value
        self.progress.setValue(int(percent))
        self.progress_label.setText(message)

    def _on_transcription_complete(self, outcome):
        self.engine, result = outcome
        transcript_text = str(result.text or "")
        if not transcript_text.strip() and result.segments:
            # Some engine adapters may return timed segments without the merged
            # text field. Recover the visible transcript without inventing words.
            transcript_text = " ".join(
                segment.text.strip() for segment in result.segments if segment.text.strip()
            )
            result.text = transcript_text
        self.command_history.clear()
        self._pending_text_undo_snapshot = None
        self.document.replace_all(result.segments, text=transcript_text)
        self.transcript_id = result.transcript_id
        self._record_metadata = {
            "title": self.audio_path.stem if self.audio_path else "Transcript",
            "source_path": str(self.audio_path) if self.audio_path else None,
            "engine": self.engine.engine_id if self.engine else "unknown",
            "model_id": self.model_combo.currentData() if self.engine and self.engine.engine_id in {"faster-whisper", "vosk"} else None,
            "language": result.language,
            "duration": result.duration,
            "original_text": transcript_text,
            "tags": [],
            "favorite": False,
        }
        self._loading_text = True
        self.editor.setPlainText(transcript_text)
        self._loading_text = False
        self._editor_base_text = transcript_text
        if transcript_text.strip():
            self.editor.setPlaceholderText("Your transcript will appear here. You can edit it at any time.")
            self.progress_label.setText(
                f"Saved locally · {result.language or 'language unknown'} · {len(result.segments)} segments"
            )
            self.status_message.emit("Transcription completed and saved to History")
        else:
            self.editor.setPlaceholderText(
                "No speech was detected in this recording. Check the microphone input level and recording, then try again."
            )
            self.progress_label.setText(
                f"No speech detected · {result.duration:.1f}s audio · {len(result.segments)} segments"
            )
            self.status_message.emit(
                "Transcription finished, but no speech was detected. Check that the microphone captured audible speech."
            )
        self._rebuild_segment_ranges()
        self._update_word_count()
        self.transcript_changed.emit(
            list(self.segments), str(self.audio_path) if self.audio_path else "",
            result.language or "", result.duration, transcript_text
        )

    def _on_transcription_error(self, message: str):
        if self.cancel_event and self.cancel_event.is_set():
            self.progress_label.setText("Transcription cancelled")
            self.status_message.emit("Transcription cancelled")
            return
        self.progress_label.setText("Transcription failed")
        QMessageBox.critical(self, "Transcription failed", message)
        self.status_message.emit("Transcription failed")

    def _finish_worker(self):
        was_cancelled = self.cancel_event is not None and self.cancel_event.is_set()
        self.progress.setVisible(False)
        if was_cancelled:
            self.progress_label.setText("Transcription cancelled")
        self.cancel_event = None
        self._job_engine_id = None
        self._refresh_busy_controls()

    def _sync_editor_text_to_document(self):
        current = self.editor.toPlainText()
        if current == self._editor_base_text:
            return
        if self._pending_text_undo_snapshot is None:
            self._pending_text_undo_snapshot = self.command_history.snapshot()
        reconciled = (
            reconcile_segments(self._editor_base_text, current, self.segments)
            if self.segments else []
        )
        self.document.replace_all(reconciled, text=current)
        self._editor_base_text = current
        self._rebuild_segment_ranges()
        self.segments_edited.emit(list(self.segments))

    def _commit_pending_text_edit(self):
        snapshot, self._pending_text_undo_snapshot = self._pending_text_undo_snapshot, None
        if snapshot is not None:
            self.command_history.record_snapshot(snapshot)

    def _schedule_autosave(self):
        if self._loading_text:
            return
        self._sync_editor_text_to_document()
        self._update_word_count()
        self.autosave_timer.start()

    def _capture_save_snapshot(self) -> dict | None:
        self._sync_editor_text_to_document()
        if not self.transcript_id or not self._record_metadata:
            return None
        text = self.editor.toPlainText()
        if not text.strip():
            return None
        return {
            "transcript_id": self.transcript_id,
            "metadata": dict(self._record_metadata),
            "text": text,
            "segments": [
                TranscriptSegment(
                    start=item.start, end=item.end, text=item.text, speaker=item.speaker,
                    words=list(item.words or []), id=item.id, language=item.language,
                    metadata=dict(item.metadata), is_edited=item.is_edited, comment=item.comment,
                    bookmarked=item.bookmarked, locked=item.locked, reviewed=item.reviewed,
                ) for item in self.segments
            ],
        }

    def _persist_snapshot(self, snapshot: dict):
        metadata = snapshot["metadata"]
        return self.history.save(
            transcript_id=snapshot["transcript_id"], title=metadata["title"],
            text=snapshot["text"], segments=snapshot["segments"],
            source_path=metadata["source_path"], engine=metadata["engine"],
            model_id=metadata["model_id"], language=metadata["language"],
            duration=metadata["duration"], original_text=metadata["original_text"],
            tags=metadata["tags"], favorite=metadata["favorite"],
        )

    def _autosave(self):
        self._sync_editor_text_to_document()
        self._commit_pending_text_edit()
        snapshot = self._capture_save_snapshot()
        if snapshot is None:
            return
        if self._save_inflight:
            # Coalesce successive edits to the same project but keep snapshots
            # from the previous project when the user switches audio/history.
            if self._save_queue and self._save_queue[-1]["transcript_id"] == snapshot["transcript_id"]:
                self._save_queue[-1] = snapshot
            else:
                self._save_queue.append(snapshot)
            return
        self._start_save(snapshot)

    def _start_save(self, snapshot: dict):
        self._save_inflight = True
        worker = FunctionWorker(lambda _emit: self._persist_snapshot(snapshot))
        worker.signals.error.connect(self._autosave_error)
        worker.signals.finished.connect(self._autosave_finished)
        worker.signals.result.connect(lambda _result: self.status_message.emit("Changes saved"))
        self.thread_pool.start(worker)

    def _autosave_error(self, message: str):
        self.status_message.emit(f"Could not save transcript changes: {message}")

    def _autosave_finished(self):
        self._save_inflight = False
        if self._save_queue:
            self._start_save(self._save_queue.pop(0))

    def flush_autosave(self):
        """Persist queued edits and the current editor snapshot during shutdown.

        MainWindow calls this only after the Qt worker pool has drained, so a
        synchronous final flush cannot race a background SQLite write.
        """
        self.autosave_timer.stop()
        self._sync_editor_text_to_document()
        self._commit_pending_text_edit()
        current = self._capture_save_snapshot()
        if current:
            if self._save_queue and self._save_queue[-1]["transcript_id"] == current["transcript_id"]:
                self._save_queue[-1] = current
            else:
                self._save_queue.append(current)
        queued, self._save_queue = self._save_queue, []
        self._save_inflight = False
        for snapshot in queued:
            self._persist_snapshot(snapshot)

    def open_history_item(self, transcript_id: str) -> bool:
        if self.is_busy:
            self.status_message.emit("Finish or cancel the current operation before opening another transcript.")
            return False
        self._autosave()
        self._load_generation += 1
        generation = self._load_generation
        self._history_load_pending = True
        self.progress_label.setText("Loading transcript from local history…")
        self._refresh_busy_controls()
        worker = FunctionWorker(lambda _emit: self.history.get(transcript_id))
        worker.signals.result.connect(lambda record, g=generation: self._apply_history_record(g, record))
        worker.signals.error.connect(lambda message, g=generation: self._history_load_failed(g, message))
        worker.signals.finished.connect(lambda g=generation: self._finish_history_load(g))
        self.thread_pool.start(worker)
        return True

    def _history_load_failed(self, generation: int, message: str):
        if generation == self._load_generation:
            self.progress_label.setText("Could not load transcript")
            self.status_message.emit(f"Could not open transcript: {message}")

    def _finish_history_load(self, generation: int):
        if generation == self._load_generation:
            self._history_load_pending = False
            self._refresh_busy_controls()

    def _apply_history_record(self, generation: int, record):
        if generation != self._load_generation:
            return
        if not record:
            self.progress_label.setText("Transcript was not found in local history.")
            self.status_message.emit("Transcript was not found in local history.")
            return
        self.transcript_id = record["id"]
        self._record_metadata = {
            "title": record["title"], "source_path": record["source_path"],
            "engine": record["engine"], "model_id": record["model_id"],
            "language": record["language"], "duration": record["duration"],
            "original_text": record["original_text"], "tags": record["tags"],
            "favorite": bool(record["favorite"]),
        }
        self.audio_path = (
            Path(record["source_path"]).expanduser().resolve()
            if record["source_path"] else None
        )
        self.player.player.stop()
        self._audio_duration_ms = 0
        if self.audio_path and self.audio_path.is_file():
            self.close_audio_button.setEnabled(True)
            self.play_button.setEnabled(True)
            media_kind = "Video" if is_video_file(self.audio_path) else "Audio"
            self.file_name.setText(f"{media_kind} · {self.audio_path.name}")
            self.file_name.setToolTip(str(self.audio_path))
            self.player.set_source(str(self.audio_path))
            self.audio_changed.emit(str(self.audio_path))
        else:
            self.close_audio_button.setEnabled(False)
            self.play_button.setEnabled(False)
            self.file_name.setText("Source media is unavailable")
            self.file_name.setToolTip(str(self.audio_path) if self.audio_path else "")
            self.player.clear_source()
            self.audio_changed.emit("")
        self.document.replace_all(
            [TranscriptSegment(**item) for item in record["segments"]],
            text=record["text"],
        )
        self.command_history.clear()
        self._pending_text_undo_snapshot = None
        self._loading_text = True
        self.editor.setPlainText(record["text"])
        self._loading_text = False
        self._editor_base_text = record["text"]
        self._rebuild_segment_ranges()
        self._update_word_count()
        self.progress_label.setText("Transcript loaded · edits auto-save")
        self.transcript_changed.emit(
            list(self.segments), str(self.audio_path) if self.audio_path else "",
            record.get("language") or "", float(record.get("duration") or 0.0),
            record.get("original_text") or record.get("text") or "",
        )

    def _rebuild_segment_ranges(self):
        self._segment_ranges = []
        content = self.editor.toPlainText()
        cursor = 0
        for segment in self.segments:
            segment_text = segment.text.strip()
            start = content.find(segment_text, cursor)
            if start < 0:
                continue
            end = start + len(segment_text)
            self._segment_ranges.append((start, end, segment))
            cursor = end

    def _position_changed(self, position: int):
        self.seek_slider.blockSignals(True)
        self.seek_slider.setValue(position)
        self.seek_slider.blockSignals(False)

    def _duration_changed(self, duration: int):
        self.seek_slider.setRange(0, max(0, duration))
        self._update_time_label(self.player.player.position(), duration)

    def _update_time_label(self, position: int, duration: int):
        def clock(value):
            seconds = max(0, int(value / 1000))
            return f"{seconds // 60:02}:{seconds % 60:02}"
        self.time_label.setText(f"{clock(position)} / {clock(duration)}")

    def _sync_transcript_to_audio(self, position: int):
        ms = position / 1000
        current = next((entry for entry in self._segment_ranges
                        if entry[2].start <= ms <= entry[2].end), None)
        if current:
            cursor = self.editor.textCursor()
            cursor.setPosition(current[0])
            cursor.setPosition(current[1], QTextCursor.MoveMode.KeepAnchor)
            self.editor.setTextCursor(cursor)
            self.editor.ensureCursorVisible()

    def _update_word_count(self):
        text = self.editor.toPlainText()
        words = len(text.split())
        self.word_count.setText(f"{words:,} words · {len(text):,} characters")
        if hasattr(self, "subtitle_export_button"):
            self.subtitle_export_button.setEnabled(not self.is_busy and self._has_timed_subtitles())
        if hasattr(self, "export_button"):
            self.export_button.setEnabled(not self.is_busy and bool(text.strip()))

    def find_next(self):
        query = self.search_input.text().strip()
        if not query:
            self._clear_search_highlight()
            return False
        found = self.editor.find(query)
        if not found:
            cursor = self.editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self.editor.setTextCursor(cursor)
            found = self.editor.find(query)
        if not found:
            self._clear_search_highlight()
            self.status_message.emit(f"No matches found for “{query}”")
            return False
        self.editor.ensureCursorVisible()
        self._show_search_highlight(self.editor.textCursor())
        return True

    def find_text(self, query: str) -> bool:
        """Navigate to the first match, used by the global transcript search."""
        value = str(query or "").strip()
        if not value:
            return False
        self.search_input.setText(value)
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.editor.setTextCursor(cursor)
        return self.find_next()

    def _show_search_highlight(self, cursor: QTextCursor):
        self._search_highlight_timer.stop()
        if not cursor.hasSelection():
            self._clear_search_highlight()
            return
        selection = QTextEdit.ExtraSelection()
        selection.cursor = QTextCursor(cursor)
        self._search_highlight_range = (cursor.selectionStart(), cursor.selectionEnd())
        formatting = QTextCharFormat()
        accent = QColor(self.editor.palette().color(QPalette.ColorRole.Highlight))
        accent.setAlpha(135)
        formatting.setBackground(accent)
        formatting.setForeground(
            self.editor.palette().color(QPalette.ColorRole.HighlightedText)
        )
        selection.format = formatting
        self.editor.setExtraSelections([selection])
        self._search_highlight_timer.start()

    def _clear_search_highlight(self):
        timer = getattr(self, "_search_highlight_timer", None)
        if timer is not None:
            timer.stop()
        editor = getattr(self, "editor", None)
        target_range = self._search_highlight_range
        self._search_highlight_range = None
        if editor is not None:
            current = editor.textCursor()
            if (
                target_range is not None
                and current.hasSelection()
                and (current.selectionStart(), current.selectionEnd()) == target_range
            ):
                # The extra selection is transient; collapse only our own native
                # text selection so the highlight disappears when its timer ends.
                current.setPosition(current.selectionEnd())
                editor.setTextCursor(current)
            editor.setExtraSelections([])

    def replace_selected(self):
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            cursor.insertText(self.replace_input.text())

    def copy_all(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.editor.toPlainText())
        self.status_message.emit("Transcript copied")

    def export(self):
        if not self.editor.toPlainText().strip():
            QMessageBox.information(self, "Nothing to export", "There is no transcript text yet.")
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Export transcript", str(self.paths.data / "transcript.txt"),
            "Text (*.txt);;Markdown (*.md);;JSON (*.json);;Word document (*.docx);;PDF (*.pdf)",
        )
        if not path:
            return
        extension_by_filter = {
            "Text (*.txt)": ".txt", "Markdown (*.md)": ".md",
            "JSON (*.json)": ".json", "Word document (*.docx)": ".docx",
            "PDF (*.pdf)": ".pdf",
        }
        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(extension_by_filter.get(selected_filter, ".txt"))
        text = self.editor.toPlainText()
        segments = list(self.segments)
        include_timestamps = self.include_timestamps.isChecked()
        audio_path = str(self.audio_path) if self.audio_path else None
        model_id = self.model_combo.currentData()
        self.export_button.setEnabled(False)
        self.status_message.emit(f"Exporting {target.name}…")
        worker = FunctionWorker(lambda _emit: export_transcript(
            target, format=target.suffix, text=text, segments=segments,
            include_timestamps=include_timestamps, title=target.stem,
            metadata={"source": audio_path, "model": model_id},
        ))
        worker.signals.result.connect(lambda output: self._export_complete(output))
        worker.signals.error.connect(lambda message: QMessageBox.critical(self, "Export failed", message))
        worker.signals.finished.connect(lambda: self.export_button.setEnabled(True))
        self.thread_pool.start(worker)

    def export_subtitles(self):
        if self.is_busy:
            return
        self._sync_editor_text_to_document()
        segments = [item for item in self.segments if item.text.strip() and item.end > item.start]
        if not segments:
            QMessageBox.information(
                self, "No timed subtitle cues",
                "This transcript has no usable segment timings. Subtitle export requires timed transcript segments.",
            )
            return
        source_name = self.audio_path.stem if self.audio_path else "transcript"
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Export subtitles", str(self.paths.data / f"{source_name}.srt"),
            "SubRip (*.srt);;WebVTT (*.vtt);;Advanced SubStation Alpha (*.ass);;SubStation Alpha (*.ssa)",
        )
        if not path:
            return
        suffix_by_filter = {
            "SubRip (*.srt)": ".srt", "WebVTT (*.vtt)": ".vtt",
            "Advanced SubStation Alpha (*.ass)": ".ass", "SubStation Alpha (*.ssa)": ".ssa",
        }
        target = Path(path)
        if target.suffix.casefold() not in {".srt", ".vtt", ".ass", ".ssa"}:
            target = target.with_suffix(suffix_by_filter.get(selected_filter, ".srt"))
        snapshot = deepcopy(segments)
        self.subtitle_export_button.setEnabled(False)
        self.status_message.emit(f"Exporting subtitles to {target.name}…")
        worker = FunctionWorker(lambda _emit: export_subtitles(target, snapshot, title=source_name))
        worker.signals.result.connect(self._export_complete)
        worker.signals.error.connect(
            lambda message: QMessageBox.critical(self, "Subtitle export failed", message)
        )
        worker.signals.finished.connect(self._update_word_count)
        self.thread_pool.start(worker)

    def _export_complete(self, path):
        self.status_message.emit(f"Exported {Path(path).name}")

    def shutdown(self):
        self.autosave_timer.stop()
        if self.cancel_event:
            self.cancel_event.set()
        self.player.shutdown()
