"""Organized settings and local storage controls."""

from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from transcriber.audio.devices import audio_device_id
from transcriber.opencode.acp_client import (
    build_opencode_invocation,
    resolve_opencode_executable,
)
from transcriber.storage.backup import create_backup, restore_backup
from transcriber.ui.widgets import Card, page_header
from transcriber.ui.workers import FunctionWorker


class SettingsPage(QWidget):
    theme_changed = Signal(str)
    concurrency_changed = Signal(int)
    permission_changed = Signal(str, bool)
    agent_settings_saved = Signal()
    status_message = Signal(str)
    audio_devices_changed = Signal(str, str)

    def __init__(self, paths, settings_store, database, thread_pool, model_manager, parent=None):
        super().__init__(parent)
        self.paths = paths
        self.settings_store = settings_store
        self.database = database
        self.thread_pool = thread_pool
        self.model_manager = model_manager
        self._workers: list[FunctionWorker] = []
        self._sections: dict[str, QWidget] = {}
        self.media_devices = QMediaDevices(self)
        self._storage_worker: FunctionWorker | None = None
        self._build()
        self.media_devices.audioInputsChanged.connect(self.refresh_audio_devices)
        self.media_devices.audioOutputsChanged.connect(self.refresh_audio_devices)

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(14)
        outer.addWidget(page_header(
            "Settings",
            "Tune recognition, privacy and local storage. Choose a category to jump to its controls.",
        ))
        workspace = QHBoxLayout()
        workspace.setSpacing(14)

        self.section_nav = QListWidget()
        self.section_nav.setObjectName("SettingsNavigation")
        self.section_nav.setFixedWidth(170)
        self.section_nav.setSpacing(2)
        self.section_nav.setFrameShape(QFrame.NoFrame)
        self.section_nav.itemClicked.connect(self._navigate_section)
        workspace.addWidget(self.section_nav)

        scroll = QScrollArea()
        scroll.setObjectName("SettingsContentScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setSpacing(14)
        current = self.settings_store.settings

        general = Card()
        form = QFormLayout(general)
        form.setContentsMargins(18, 16, 18, 16)
        self.theme = QComboBox()
        self.theme.addItem("Dark", "dark")
        self.theme.addItem("Light", "light")
        self.theme.addItem("System default (dark fallback)", "system")
        self.theme.setCurrentIndex(max(0, self.theme.findData(current.theme)))
        self.theme.currentIndexChanged.connect(self._theme_changed)
        form.addRow("Appearance", self.theme)
        self.language = QComboBox()
        self.language.addItem("English (currently the only built-in language)", "en")
        self.language.setCurrentIndex(max(0, self.language.findData(current.language)))
        self.language.currentIndexChanged.connect(lambda: self._save(language=self.language.currentData()))
        form.addRow("Application language", self.language)
        layout.addWidget(self._section("General", general, "general"))

        devices = Card()
        devices_form = QFormLayout(devices)
        devices_form.setContentsMargins(18, 16, 18, 16)
        self.audio_input_device = QComboBox()
        self.audio_input_device.setMinimumWidth(320)
        self.audio_input_device.currentIndexChanged.connect(self._audio_input_changed)
        self.audio_output_device = QComboBox()
        self.audio_output_device.setMinimumWidth(320)
        self.audio_output_device.currentIndexChanged.connect(self._audio_output_changed)
        devices_form.addRow("Microphone / recording input", self.audio_input_device)
        devices_form.addRow("Speaker / playback output", self.audio_output_device)
        device_actions = QHBoxLayout()
        self.refresh_audio_devices_button = QPushButton("Refresh audio devices")
        self.refresh_audio_devices_button.clicked.connect(self.refresh_audio_devices)
        device_actions.addWidget(self.refresh_audio_devices_button)
        device_actions.addStretch(1)
        devices_form.addRow("Device list", device_actions)
        self.audio_device_status = QLabel(
            "The selected microphone is also used by Live recording. Playback uses the selected output device."
        )
        self.audio_device_status.setObjectName("Muted")
        self.audio_device_status.setWordWrap(True)
        devices_form.addRow("Audio routing", self.audio_device_status)
        layout.addWidget(self._section("Audio devices", devices, "devices"))
        self.refresh_audio_devices()

        recognition = Card()
        recog_form = QFormLayout(recognition)
        recog_form.setContentsMargins(18, 16, 18, 16)
        self.engine = QComboBox()
        self.engine.addItem("Faster-Whisper (offline)", "faster-whisper")
        self.engine.addItem("Vosk / Kaldi (offline)", "vosk")
        self.engine.addItem("Google Cloud Speech-to-Text V2 (online)", "google-cloud")
        self.engine.addItem("Google Web Speech (experimental · no login)", "google-web")
        self.engine.setCurrentIndex(max(0, self.engine.findData(current.default_engine)))
        self.engine.currentIndexChanged.connect(lambda: self._save(default_engine=self.engine.currentData()))
        self.device = QComboBox()
        for label, value in (("Automatic", "auto"), ("CPU", "cpu"), ("CUDA GPU", "cuda")):
            self.device.addItem(label, value)
        self.device.setCurrentIndex(max(0, self.device.findData(current.device)))
        self.device.setToolTip(
            "CUDA GPU requires NVIDIA cuBLAS for CUDA 12 and cuDNN 9. "
            "Automatic mode retries on CPU if a CUDA runtime DLL is missing."
        )
        self.device.currentIndexChanged.connect(lambda: self._save(device=self.device.currentData()))
        self.compute = QComboBox()
        for value in ("int8", "int8_float16", "float16", "float32", "default"):
            self.compute.addItem(value, value)
        self.compute.setCurrentIndex(max(0, self.compute.findData(current.compute_type)))
        self.compute.currentIndexChanged.connect(lambda: self._save(compute_type=self.compute.currentData()))
        self.threads = QSpinBox()
        self.threads.setRange(0, 256)
        self.threads.setSpecialValueText("Automatic")
        self.threads.setValue(current.cpu_threads)
        self.threads.valueChanged.connect(lambda value: self._save(cpu_threads=value))
        self.beam = QSpinBox()
        self.beam.setRange(1, 20)
        self.beam.setValue(current.beam_size)
        self.beam.valueChanged.connect(lambda value: self._save(beam_size=value))
        self.vad = QCheckBox("Filter silence and non-speech regions")
        self.vad.setChecked(current.vad_filter)
        self.vad.toggled.connect(lambda value: self._save(vad_filter=value))
        self.word_timestamps = QCheckBox("Request word-level timestamps")
        self.word_timestamps.setChecked(current.word_timestamps)
        self.word_timestamps.toggled.connect(lambda value: self._save(word_timestamps=value))
        recog_form.addRow("Recognition engine", self.engine)
        recog_form.addRow("Compute device", self.device)
        recog_form.addRow("Compute type", self.compute)
        recog_form.addRow("CPU threads", self.threads)
        recog_form.addRow("Beam size", self.beam)
        recog_form.addRow("Voice activity detection", self.vad)
        recog_form.addRow("Word-level timestamps", self.word_timestamps)
        layout.addWidget(self._section("Recognition", recognition, "recognition"))

        cloud = Card()
        cloud_form = QFormLayout(cloud)
        cloud_form.setContentsMargins(18, 16, 18, 16)
        self.google_cloud_project = QLineEdit(current.google_cloud_project)
        self.google_cloud_project.setPlaceholderText("Google Cloud project ID (or GOOGLE_CLOUD_PROJECT)")
        self.google_cloud_location = QComboBox()
        for label, value in (("Europe multi-region", "eu"), ("United States multi-region", "us"), ("Global", "global")):
            self.google_cloud_location.addItem(label, value)
        self.google_cloud_location.setCurrentIndex(max(0, self.google_cloud_location.findData(current.google_cloud_location)))
        self.google_cloud_model = QComboBox()
        for label, value in (("Chirp 3", "chirp_3"), ("Long", "long"), ("Short", "short")):
            self.google_cloud_model.addItem(label, value)
        self.google_cloud_model.setCurrentIndex(max(0, self.google_cloud_model.findData(current.google_cloud_model)))
        cloud_form.addRow("Google Cloud project", self.google_cloud_project)
        cloud_form.addRow("API region", self.google_cloud_location)
        cloud_form.addRow("V2 model", self.google_cloud_model)
        cloud_actions = QHBoxLayout()
        save_cloud = QPushButton("Save Cloud configuration")
        save_cloud.clicked.connect(self._save_google_cloud_settings)
        self.verify_cloud = QPushButton("Verify ADC credentials")
        self.verify_cloud.clicked.connect(self._verify_google_cloud_credentials)
        cloud_actions.addWidget(save_cloud)
        cloud_actions.addWidget(self.verify_cloud)
        cloud_actions.addStretch(1)
        cloud_form.addRow("Configuration", cloud_actions)
        self.cloud_status = QLabel(
            "Uses Application Default Credentials. Verification checks local credentials only; API enablement and IAM permission are checked on the first request."
        )
        self.cloud_status.setObjectName("Muted")
        self.cloud_status.setWordWrap(True)
        cloud_form.addRow("Status", self.cloud_status)
        cloud_note = QLabel(
            "Requires a Google Cloud project, billing, Speech-to-Text API enabled and suitable IAM permissions. "
            "No service-account key is stored by Transcriber. Audio is sent inline in chunks; this workflow does not upload files to Google Cloud Storage."
        )
        cloud_note.setWordWrap(True)
        cloud_note.setObjectName("Muted")
        cloud_form.addRow("Requirements", cloud_note)
        layout.addWidget(self._section("Google Cloud Speech-to-Text V2", cloud, "cloud"))

        jobs = Card()
        jobs_form = QFormLayout(jobs)
        jobs_form.setContentsMargins(18, 16, 18, 16)
        self.download_workers = QSpinBox()
        self.download_workers.setRange(1, 4)
        self.download_workers.setValue(current.download_concurrency)
        self.download_workers.valueChanged.connect(self._concurrency_changed)
        jobs_form.addRow("Concurrent background downloads", self.download_workers)
        layout.addWidget(self._section("Background jobs", jobs, "jobs"))

        runtime = Card()
        runtime_form = QFormLayout(runtime)
        runtime_form.setContentsMargins(18, 16, 18, 16)
        self.max_active_models = QSpinBox()
        self.max_active_models.setRange(1, 10)
        self.max_active_models.setValue(current.max_active_models)
        self.max_active_models.valueChanged.connect(lambda value: self._save(max_active_models=value))
        self.ram_budget = QSpinBox()
        self.ram_budget.setRange(0, 1_048_576)
        self.ram_budget.setSingleStep(512)
        self.ram_budget.setSuffix(" MB")
        self.ram_budget.setValue(current.ram_budget_mb)
        self.ram_budget.valueChanged.connect(lambda value: self._save(ram_budget_mb=value))
        self.vram_budget = QSpinBox()
        self.vram_budget.setRange(0, 1_048_576)
        self.vram_budget.setSingleStep(256)
        self.vram_budget.setSuffix(" MB")
        self.vram_budget.setValue(current.vram_budget_mb)
        self.vram_budget.valueChanged.connect(lambda value: self._save(vram_budget_mb=value))
        runtime_form.addRow("Maximum loaded models (1–10)", self.max_active_models)
        runtime_form.addRow("RAM budget", self.ram_budget)
        runtime_form.addRow("VRAM budget", self.vram_budget)
        runtime_note = QLabel(
            "The generic ModelRuntimeManager enforces these resource policies for registered adapters. "
            "The current Faster-Whisper application service is still single-active-model; these settings "
            "do not make multiple Whisper models load simultaneously yet."
        )
        runtime_note.setWordWrap(True)
        runtime_note.setObjectName("Muted")
        runtime_form.addRow("Current integration", runtime_note)
        layout.addWidget(self._section("Model runtime policy", runtime, "runtime"))

        agent = Card()
        agent_layout = QVBoxLayout(agent)
        agent_layout.setContentsMargins(18, 16, 18, 16)
        executable_row = QHBoxLayout()
        executable_row.addWidget(QLabel("OpenCode launcher"))
        self.opencode_path = QLineEdit(current.opencode_path or "")
        self.opencode_path.setPlaceholderText(
            "Leave empty to use PATH (Windows npm installs: opencode.cmd)"
        )
        self.opencode_path.setToolTip(
            "On Windows, select the opencode.cmd launcher from %APPDATA%\\npm. "
            "The extensionless npm shim is not a native executable."
        )
        browse_executable = QPushButton("Browse…")
        browse_executable.clicked.connect(self._browse_opencode)
        executable_row.addWidget(self.opencode_path, 1)
        executable_row.addWidget(browse_executable)
        agent_layout.addLayout(executable_row)
        self.opencode_project = self._path_row(
            "OpenCode project", current.opencode_project_directory or str(Path.cwd()), agent_layout,
        )
        wake_row = QHBoxLayout()
        wake_row.addWidget(QLabel("Activation keyword / phrase"))
        self.wake_phrase = QLineEdit(current.wake_phrase)
        self.wake_phrase.setPlaceholderText("For example: transcriber")
        self.wake_phrase.setToolTip(
            "Vosk listens for this exact phrase. Choose words that the selected Vosk model supports."
        )
        wake_row.addWidget(self.wake_phrase, 1)
        agent_layout.addLayout(wake_row)

        wake_model_title = QLabel("Wake-word Vosk model")
        wake_model_title.setToolTip(
            "This model is used only to detect the activation phrase, not to transcribe the command."
        )
        agent_layout.addWidget(wake_model_title)
        wake_model_row = QHBoxLayout()
        self.wake_model_combo = QComboBox()
        self.wake_model_combo.setMinimumWidth(240)
        self.wake_model_combo.setToolTip(
            "Choose one of the installed and validated Vosk models."
        )
        self.refresh_wake_models_button = QPushButton("Refresh")
        self.refresh_wake_models_button.clicked.connect(lambda: self.refresh_vosk_models())
        self.browse_wake_model_button = QPushButton("Browse local…")
        self.browse_wake_model_button.clicked.connect(self._browse_wake_model)
        wake_model_row.addWidget(self.wake_model_combo, 1)
        wake_model_row.addWidget(self.refresh_wake_models_button)
        wake_model_row.addWidget(self.browse_wake_model_button)
        agent_layout.addLayout(wake_model_row)
        self.wake_model_help = QLabel()
        self.wake_model_help.setObjectName("Muted")
        self.wake_model_help.setWordWrap(True)
        agent_layout.addWidget(self.wake_model_help)
        self.refresh_vosk_models(current.wake_model_directory)
        self.voice_auto_submit = QCheckBox(
            "Automatically send recognized voice commands to the connected OpenCode session"
        )
        self.voice_auto_submit.setChecked(current.voice_auto_submit)
        self.voice_auto_submit.toggled.connect(
            lambda enabled: self._save(voice_auto_submit=enabled)
        )
        agent_layout.addWidget(self.voice_auto_submit)
        agent_buttons = QHBoxLayout()
        save_agent = QPushButton("Save Agent settings")
        save_agent.clicked.connect(self._save_agent_settings)
        self.test_opencode = QPushButton("Test OpenCode launcher")
        self.test_opencode.clicked.connect(self._test_opencode)
        agent_buttons.addWidget(save_agent)
        agent_buttons.addWidget(self.test_opencode)
        agent_buttons.addStretch(1)
        agent_layout.addLayout(agent_buttons)
        agent_note = QLabel(
            "Set the activation phrase and select the Vosk model that listens for it here. "
            "Install or import Vosk models from AI models → Vosk. Wake detection starts only after "
            "you enable it in the Assistant panel. The command is then transcribed by the selected "
            "local Faster-Whisper model; raw voice audio is not sent to OpenCode."
        )
        agent_note.setWordWrap(True)
        agent_note.setObjectName("Muted")
        agent_layout.addWidget(agent_note)
        permission_title = QLabel("Agent permissions")
        permission_title.setObjectName("SettingsSubsectionTitle")
        agent_layout.addWidget(permission_title)
        permission_labels = {
            "read_only": "Read application state",
            "edit_content": "Edit transcript content",
            "modify_settings": "Modify application settings",
            "audio_capture": "Start microphone/audio capture",
            "file_export": "Export files",
            "model_management": "Download/load/unload models",
            "destructive_actions": "Allow destructive actions (still asks for confirmation)",
            "desktop_control": "Open local applications, files and folders (asks before every action)",
            "browser_control": "Control the dedicated Chrome/Edge browser (website interactions ask first)",
            "command_execution": "Run custom PowerShell commands (confirmation required for every command)",
        }
        enabled_permissions = set(current.agent_permissions or ["read_only", "edit_content"])
        self.agent_permission_checks = {}
        permission_grid = QFormLayout()
        for permission, label in permission_labels.items():
            check = QCheckBox(label)
            check.setChecked(permission in enabled_permissions)
            check.toggled.connect(lambda enabled, key=permission: self._permission_changed(key, enabled))
            self.agent_permission_checks[permission] = check
            permission_grid.addRow(check)
        agent_layout.addLayout(permission_grid)
        layout.addWidget(self._section("OpenCode & Voice Agent", agent, "agent"))

        privacy = Card()
        privacy_form = QFormLayout(privacy)
        privacy_form.setContentsMargins(18, 16, 18, 16)
        self.local_only = QCheckBox("Keep recognition local; do not use a cloud engine")
        self.local_only.setChecked(current.local_only)
        self.local_only.toggled.connect(lambda value: self._save(local_only=value))
        self.cloud_consent = QCheckBox("I understand that online recognition sends audio to Google for processing")
        self.cloud_consent.setChecked(current.cloud_consent)
        self.cloud_consent.toggled.connect(lambda value: self._save(cloud_consent=value))
        privacy_form.addRow("Local-only mode", self.local_only)
        privacy_form.addRow("Cloud consent", self.cloud_consent)
        note = QLabel(
            "Google Cloud Speech-to-Text V2 is the supported API and requires a Google Cloud project, "
            "billing configuration and Application Default Credentials. Google Web Speech is a separate "
            "unofficial compatibility endpoint: it uses a shared public Chromium key, needs no account or "
            "Cloud project, has no reliability or quota guarantee, and may be disabled by Google at any time. "
            "Both online engines send audio to Google; use the experimental endpoint only for short, non-sensitive audio."
        )
        note.setWordWrap(True)
        note.setObjectName("Muted")
        privacy_form.addRow("Privacy", note)
        layout.addWidget(self._section("Privacy", privacy, "privacy"))

        storage = Card()
        storage_layout = QVBoxLayout(storage)
        storage_layout.setContentsMargins(18, 16, 18, 16)
        self.model_dir = self._path_row("Model directory", current.model_directory or str(self.paths.models), storage_layout)
        self.recording_dir = self._path_row("Recording directory", current.recording_directory or str(self.paths.recordings), storage_layout)
        apply_paths = QPushButton("Save storage locations (restart required)")
        apply_paths.clicked.connect(self._save_paths)
        storage_layout.addWidget(apply_paths)
        self.storage_usage = QLabel("Calculating storage usage…")
        self.storage_usage.setObjectName("Muted")
        storage_layout.addWidget(self.storage_usage)
        actions = QHBoxLayout()
        self.backup_button = QPushButton("Create metadata backup…")
        self.backup_button.clicked.connect(self._backup)
        self.restore_button = QPushButton("Restore metadata backup…")
        self.restore_button.clicked.connect(self._restore)
        self.clear_cache_button = QPushButton("Clear model cache")
        self.clear_cache_button.clicked.connect(self._clear_cache)
        for button in (self.backup_button, self.restore_button, self.clear_cache_button):
            actions.addWidget(button)
        storage_layout.addLayout(actions)
        layout.addWidget(self._section("Storage", storage, "storage"))
        layout.addStretch(1)
        scroll.setWidget(body)
        self.scroll = scroll
        categories = (
            ("general", "General"),
            ("devices", "Audio devices"),
            ("recognition", "Recognition"),
            ("cloud", "Cloud services"),
            ("jobs", "Background jobs"),
            ("runtime", "Model runtime"),
            ("agent", "Assistant & Agent"),
            ("privacy", "Privacy"),
            ("storage", "Storage"),
        )
        for key, title in categories:
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.section_nav.addItem(item)
        self.section_nav.setCurrentRow(0)
        workspace.addWidget(scroll, 1)
        outer.addLayout(workspace, 1)
        self._refresh_storage_usage()

    def _section(self, title: str, content: QWidget, key: str) -> QWidget:
        outer = QWidget()
        outer.setObjectName(f"SettingsSection_{key}")
        layout = QVBoxLayout(outer)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(title)
        label.setObjectName("SettingsSectionTitle")
        layout.addWidget(label)
        layout.addWidget(content)
        self._sections[key] = outer
        return outer


    def refresh_audio_devices(self):
        if not hasattr(self, "audio_input_device"):
            return
        current = self.settings_store.settings
        inputs = list(QMediaDevices.audioInputs())
        outputs = list(QMediaDevices.audioOutputs())
        default_input = QMediaDevices.defaultAudioInput()
        default_output = QMediaDevices.defaultAudioOutput()

        input_blocker = self.audio_input_device.blockSignals(True)
        output_blocker = self.audio_output_device.blockSignals(True)
        try:
            self.audio_input_device.clear()
            default_input_id = "" if default_input.isNull() else audio_device_id(default_input)
            default_input_label = "Follow Windows default"
            if not default_input.isNull():
                default_input_label += f" · {default_input.description()}"
            else:
                default_input_label += " · No microphone detected"
            self.audio_input_device.addItem(default_input_label, "")
            input_ids = set()
            for device in inputs:
                device_id = audio_device_id(device)
                input_ids.add(device_id)
                label = device.description()
                if device_id == default_input_id and default_input_id:
                    label += " · Windows default (pin device)"
                self.audio_input_device.addItem(label, device_id)
            if current.audio_input_device_id and current.audio_input_device_id not in input_ids:
                self.audio_input_device.addItem(
                    f"Unavailable microphone · {current.audio_input_device_id}",
                    current.audio_input_device_id,
                )
            input_index = self.audio_input_device.findData(current.audio_input_device_id)
            self.audio_input_device.setCurrentIndex(max(0, input_index))

            self.audio_output_device.clear()
            default_output_id = "" if default_output.isNull() else audio_device_id(default_output)
            default_output_label = "Follow Windows default"
            if not default_output.isNull():
                default_output_label += f" · {default_output.description()}"
            else:
                default_output_label += " · No output detected"
            self.audio_output_device.addItem(default_output_label, "")
            output_ids = set()
            for device in outputs:
                device_id = audio_device_id(device)
                output_ids.add(device_id)
                label = device.description()
                if device_id == default_output_id and default_output_id:
                    label += " · Windows default (pin device)"
                self.audio_output_device.addItem(label, device_id)
            if current.audio_output_device_id and current.audio_output_device_id not in output_ids:
                self.audio_output_device.addItem(
                    f"Unavailable output · {current.audio_output_device_id}",
                    current.audio_output_device_id,
                )
            output_index = self.audio_output_device.findData(current.audio_output_device_id)
            self.audio_output_device.setCurrentIndex(max(0, output_index))
        finally:
            self.audio_input_device.blockSignals(input_blocker)
            self.audio_output_device.blockSignals(output_blocker)

        if not inputs:
            self.audio_device_status.setText("No microphone input detected. Connect a microphone or check Windows sound settings.")
        elif not outputs:
            self.audio_device_status.setText("No playback output detected. Connect speakers or headphones.")
        else:
            self.audio_device_status.setText(
                "Device preferences are saved automatically. Missing devices remain selected until you choose another device or the system default."
            )
        self.audio_devices_changed.emit(
            current.audio_input_device_id, current.audio_output_device_id
        )

    def _audio_input_changed(self, _index: int):
        device_id = str(self.audio_input_device.currentData() or "")
        self._save(audio_input_device_id=device_id)
        self.audio_devices_changed.emit(
            device_id, self.settings_store.settings.audio_output_device_id
        )

    def _audio_output_changed(self, _index: int):
        device_id = str(self.audio_output_device.currentData() or "")
        self._save(audio_output_device_id=device_id)
        self.audio_devices_changed.emit(
            self.settings_store.settings.audio_input_device_id, device_id
        )

    def _navigate_section(self, item: QListWidgetItem):
        key = str(item.data(Qt.ItemDataRole.UserRole) or "")
        self.focus_section(key)

    def focus_section(self, key: str):
        section_key = str(key)
        section = self._sections.get(section_key)
        if section is not None:
            self.scroll.ensureWidgetVisible(section, 12, 12)
        for index in range(self.section_nav.count()):
            item = self.section_nav.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == section_key:
                self.section_nav.setCurrentItem(item)
                break

    def search_entries(self) -> list[dict]:
        """Return searchable settings destinations for global search and Ctrl+K."""
        entries = [
            ("Appearance", "General", "theme dark light color UI", "general"),
            ("Application language", "General", "language locale translation", "general"),
            ("Microphone input device", "Audio devices", "microphone mic input recording capture headset", "devices"),
            ("Playback output device", "Audio devices", "speaker headphones audio output playback sound", "devices"),
            ("Refresh audio devices", "Audio devices", "rescan detect microphone speakers hardware", "devices"),
            ("Recognition engine", "Recognition", "faster whisper offline google cloud speech engine", "recognition"),
            ("Compute device · CPU / CUDA GPU", "Recognition", "device processor CPU GPU graphics acceleration cuda", "recognition"),
            ("Compute precision", "Recognition", "compute type int8 float16 precision", "recognition"),
            ("CPU thread count", "Recognition", "threads performance processor", "recognition"),
            ("Beam size", "Recognition", "decoding accuracy search", "recognition"),
            ("Voice activity detection", "Recognition", "VAD silence speech filter", "recognition"),
            ("Word-level timestamps", "Recognition", "word timing timestamps alignment", "recognition"),
            ("Google Cloud configuration", "Cloud", "online speech project region model", "cloud"),
            ("Verify cloud credentials", "Cloud", "ADC authentication credentials google", "cloud"),
            ("Background download concurrency", "Background jobs", "parallel downloads workers", "jobs"),
            ("Model runtime limits", "Model runtime", "loaded models RAM VRAM memory budget", "runtime"),
            ("OpenCode executable and project", "OpenCode & Voice Agent", "agent executable path project directory", "agent"),
            ("Voice wake phrase and model", "OpenCode & Voice Agent", "microphone wake word vosk voice assistant", "agent"),
            ("Agent permissions", "OpenCode & Voice Agent", "permissions access microphone file export destructive desktop browser command", "agent"),
            ("Local-only and cloud consent", "Privacy", "privacy internet online offline audio consent", "privacy"),
            ("Model and recording folders", "Storage", "paths directories recordings models", "storage"),
            ("Backup and restore", "Storage", "backup metadata restore database", "storage"),
            ("Clear model cache", "Storage", "delete cache disk space models", "storage"),
        ]
        return [
            {
                "title": title,
                "category": category,
                "keywords": f"{keywords} settings configuration preferences options",
                "callback": lambda section=section: self.focus_section(section),
            }
            for title, category, keywords, section in entries
        ]

    def _path_row(self, label: str, value: str, parent_layout: QVBoxLayout) -> QLineEdit:
        row = QHBoxLayout()
        title = QLabel(label)
        title.setMinimumWidth(140)
        edit = QLineEdit(value)
        browse = QPushButton("Browse…")
        browse.clicked.connect(lambda: self._browse_directory(edit))
        row.addWidget(title)
        row.addWidget(edit, 1)
        row.addWidget(browse)
        parent_layout.addLayout(row)
        return edit

    def _browse_directory(self, edit: QLineEdit):
        path = QFileDialog.getExistingDirectory(self, "Choose directory", edit.text())
        if path:
            edit.setText(path)

    def _browse_opencode(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose OpenCode launcher",
            self.opencode_path.text(),
            "OpenCode launchers (*.exe *.cmd *.bat *.ps1);;All files (*)",
        )
        if path:
            self.opencode_path.setText(path)

    def _save(self, **changes):
        self.settings_store.update(**changes)
        self.status_message.emit("Settings saved")

    def _save_google_cloud_settings(self):
        self._save(
            google_cloud_project=self.google_cloud_project.text().strip(),
            google_cloud_location=self.google_cloud_location.currentData(),
            google_cloud_model=self.google_cloud_model.currentData(),
        )
        self.cloud_status.setText("Configuration saved. Credential verification does not send audio.")

    def _verify_google_cloud_credentials(self):
        project_id = self.google_cloud_project.text().strip() or None
        self.verify_cloud.setEnabled(False)
        self.cloud_status.setText("Refreshing Application Default Credentials…")

        def verify(_emit):
            from transcriber.engines.cloud import GoogleCloudEngine
            return GoogleCloudEngine.verify_credentials(project_id)

        worker = FunctionWorker(verify)
        self._track_worker(
            worker,
            lambda result: self.cloud_status.setText(
                f"Credentials available for project {result['project_id']} ({result['credential_type']}). "
                "Speech API access will be checked by the first real recognition request."
            ),
            lambda message: self.cloud_status.setText(f"Credential verification failed: {message}"),
        )
        worker.signals.finished.connect(lambda: self.verify_cloud.setEnabled(True))

    def _concurrency_changed(self, value: int):
        self._save(download_concurrency=value)
        self.concurrency_changed.emit(value)

    def _theme_changed(self):
        theme = self.theme.currentData()
        self._save(theme=theme)
        self.theme_changed.emit(theme)

    def _save_paths(self):
        model_dir = Path(self.model_dir.text()).expanduser()
        recording_dir = Path(self.recording_dir.text()).expanduser()
        if not model_dir.is_absolute() or not recording_dir.is_absolute():
            QMessageBox.warning(self, "Invalid path", "Storage locations must be absolute paths.")
            return
        try:
            model_dir.mkdir(parents=True, exist_ok=True)
            recording_dir.mkdir(parents=True, exist_ok=True)
            self._save(model_directory=str(model_dir.resolve()), recording_directory=str(recording_dir.resolve()))
            QMessageBox.information(self, "Restart required", "The new storage locations will be used after restarting Transcriber.")
        except OSError as exc:
            QMessageBox.warning(self, "Cannot use directory", str(exc))

    def _permission_changed(self, permission: str, enabled: bool):
        current = set(self.settings_store.settings.agent_permissions or [])
        if enabled:
            current.add(permission)
        else:
            current.discard(permission)
        ordered = [name for name in (
            "read_only", "edit_content", "modify_settings", "audio_capture",
            "file_export", "model_management", "destructive_actions", "desktop_control",
            "browser_control", "command_execution",
        ) if name in current]
        self._save(agent_permissions=ordered)
        self.permission_changed.emit(permission, enabled)

    @staticmethod
    def _wake_model_path_key(value: str | None) -> str:
        if not value:
            return ""
        try:
            return str(Path(value).expanduser().resolve()).casefold()
        except OSError:
            return str(value).casefold()

    def refresh_vosk_models(self, selected_path: str | None = None):
        """Populate the wake selector from installed, validated Vosk models."""
        if not hasattr(self, "wake_model_combo"):
            return
        if selected_path is None:
            selected_path = self.wake_model_combo.currentData()
            if not selected_path:
                selected_path = self.settings_store.settings.wake_model_directory
        selected_key = self._wake_model_path_key(selected_path)

        combo = self.wake_model_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Select a Vosk wake-word model…", "")

        try:
            models = self.model_manager.installed_vosk_models(include_sizes=False)
        except Exception as exc:
            models = []
            self.wake_model_help.setText(f"Could not list installed Vosk models: {exc}")

        for model in models:
            repo_id = str(model.get("repo_id") or "")
            model_name = str(model.get("model_name") or repo_id or "Vosk model")
            language = str(model.get("language_name") or model.get("language") or "").strip()
            label = f"{model_name} · {language}" if language else model_name
            path = str(model.get("path") or "")
            if path:
                combo.addItem(label, path)

        selected_index = combo.findData(selected_path)
        if selected_index < 0 and selected_key:
            for index in range(1, combo.count()):
                if self._wake_model_path_key(combo.itemData(index)) == selected_key:
                    selected_index = index
                    break

        if selected_index < 0 and selected_path:
            custom_path = Path(selected_path).expanduser()
            if (
                custom_path.is_dir()
                and not custom_path.is_symlink()
                and ((custom_path / "am").is_dir() or (custom_path / "conf").is_dir())
            ):
                combo.addItem(f"Custom local model · {custom_path.name}", str(custom_path.resolve()))
                selected_index = combo.count() - 1

        combo.setCurrentIndex(max(0, selected_index))
        combo.blockSignals(False)

        if combo.count() == 1:
            self.wake_model_help.setText(
                "No installed Vosk model is available. Open AI models → Vosk to install one, "
                "or use Browse local… to select an existing Vosk model folder."
            )
        else:
            self.wake_model_help.setText(
                "The selected Vosk model detects only the activation phrase. "
                "Faster-Whisper handles the command after the wake phrase."
            )

    def _browse_wake_model(self):
        current = str(self.wake_model_combo.currentData() or "")
        path = QFileDialog.getExistingDirectory(
            self,
            "Choose local Vosk wake-word model",
            current or str(self.paths.models),
        )
        if not path:
            return
        model_path = Path(path).expanduser()
        if (
            model_path.is_symlink()
            or not model_path.is_dir()
            or not ((model_path / "am").is_dir() or (model_path / "conf").is_dir())
        ):
            QMessageBox.warning(
                self,
                "Invalid Vosk model",
                "Choose a Vosk model folder containing its am/ or conf/ directory.",
            )
            return
        self.refresh_vosk_models(str(model_path.resolve()))

    def _save_agent_settings(self):
        executable = self.opencode_path.text().strip() or None
        project = self.opencode_project.text().strip() or None
        wake_model = str(self.wake_model_combo.currentData() or "").strip() or None
        wake_phrase = self.wake_phrase.text().strip()
        if project and not Path(project).expanduser().is_dir():
            QMessageBox.warning(self, "Invalid project directory", "OpenCode project must be an existing directory.")
            return
        if not wake_phrase:
            QMessageBox.warning(
                self, "Activation phrase required",
                "Enter the keyword or phrase that Vosk should listen for.",
            )
            return
        if wake_model:
            model_path = Path(wake_model).expanduser()
            if (
                model_path.is_symlink()
                or not model_path.is_dir()
                or not ((model_path / "am").is_dir() or (model_path / "conf").is_dir())
            ):
                QMessageBox.warning(
                    self, "Invalid Vosk model",
                    "Choose a Vosk model folder containing its am/ or conf/ directory.",
                )
                return
        self._save(
            opencode_path=executable,
            opencode_project_directory=project,
            wake_model_directory=wake_model,
            wake_phrase=wake_phrase,
        )
        self.agent_settings_saved.emit()

    def _test_opencode(self):
        configured = self.opencode_path.text().strip() or None
        self.test_opencode.setEnabled(False)

        def run(_emit):
            executable = resolve_opencode_executable(configured)
            command, launch_options = build_opencode_invocation(
                executable, ["--version"]
            )
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=12,
                check=False,
                **launch_options,
            )
            if result.returncode != 0:
                detail = result.stderr.strip() or result.stdout.strip()
                raise RuntimeError(
                    detail or f"OpenCode exited with code {result.returncode}"
                )
            return (
                result.stdout.strip()
                or result.stderr.strip()
                or f"OpenCode responded using {executable}"
            )

        worker = FunctionWorker(run)
        worker.signals.result.connect(lambda message: self._opencode_test_result(True, message))
        worker.signals.error.connect(lambda message: self._opencode_test_result(False, message))
        worker.signals.finished.connect(lambda: self.test_opencode.setEnabled(True))
        self.thread_pool.start(worker)

    def _opencode_test_result(self, success: bool, message: str):
        if success:
            QMessageBox.information(self, "OpenCode available", message)
        else:
            QMessageBox.warning(self, "OpenCode test failed", message)

    @staticmethod
    def _directory_size(path: Path) -> int:
        total = 0
        if path.exists():
            for item in path.rglob("*"):
                if item.is_file() and not item.is_symlink():
                    try:
                        total += item.stat().st_size
                    except OSError:
                        continue
        return total

    def _track_worker(self, worker: FunctionWorker, on_result, on_error):
        self._workers.append(worker)
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error)
        worker.signals.finished.connect(lambda current=worker: self._forget_worker(current))
        self.thread_pool.start(worker)

    def _forget_worker(self, worker: FunctionWorker):
        try:
            self._workers.remove(worker)
        except ValueError:
            pass

    def _refresh_storage_usage(self):
        paths = self.paths
        worker = FunctionWorker(lambda _emit: (
            self._directory_size(paths.models),
            self._directory_size(paths.recordings),
            paths.database.stat().st_size if paths.database.exists() else 0,
        ))
        self._storage_worker = worker
        self._track_worker(
            worker, self._show_storage_usage,
            lambda message: self.storage_usage.setText(f"Storage usage unavailable: {message}"),
        )

    def _show_storage_usage(self, usage):
        models, recordings, database = usage
        self.storage_usage.setText(
            f"Models: {models:,} bytes    ·    Recordings: {recordings:,} bytes    ·    Database: {database:,} bytes"
        )

    def _backup(self):
        path, _ = QFileDialog.getSaveFileName(self, "Create backup", "Transcriber-backup.zip", "Zip archive (*.zip)")
        if not path:
            return
        target = Path(path)
        self.backup_button.setEnabled(False)
        worker = FunctionWorker(lambda _emit: create_backup(self.database, self.settings_store.path, target))
        self._track_worker(
            worker,
            lambda output: QMessageBox.information(
                self, "Backup created", f"Metadata backup saved to {output}. Models and recordings are intentionally excluded."
            ),
            lambda message: QMessageBox.critical(self, "Backup failed", message),
        )
        worker.signals.finished.connect(lambda: self.backup_button.setEnabled(True))

    def _restore(self):
        path, _ = QFileDialog.getOpenFileName(self, "Restore backup", "", "Zip archive (*.zip)")
        if not path:
            return
        answer = QMessageBox.warning(
            self, "Replace local metadata",
            "This replaces the local transcript database and settings. Make a current backup first. Continue?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        source = Path(path)
        self.restore_button.setEnabled(False)
        worker = FunctionWorker(lambda _emit: restore_backup(source, self.paths.database, self.settings_store.path))
        self._track_worker(
            worker,
            lambda _result: QMessageBox.information(
                self, "Restore complete", "Restart Transcriber to reload restored settings and transcript history."
            ),
            lambda message: QMessageBox.critical(self, "Restore failed", message),
        )
        worker.signals.finished.connect(lambda: self.restore_button.setEnabled(True))

    def _clear_cache(self):
        answer = QMessageBox.question(
            self, "Clear cache",
            "Remove cached Hub downloads? This may make future model downloads take longer. Installed models are not deleted.",
        )
        if answer != QMessageBox.Yes:
            return
        if self.model_manager.active_downloads:
            QMessageBox.warning(self, "Downloads active", "Cancel or finish active model downloads before clearing the shared download cache.")
            return

        def clear(_emit):
            self.model_manager.clear_download_cache()
            return True

        self.clear_cache_button.setEnabled(False)
        worker = FunctionWorker(clear)
        self._track_worker(
            worker,
            lambda _result: (self.status_message.emit("Cache cleared"), self._refresh_storage_usage()),
            lambda message: QMessageBox.warning(self, "Cache cleanup failed", message),
        )
        worker.signals.finished.connect(lambda: self.clear_cache_button.setEnabled(True))
