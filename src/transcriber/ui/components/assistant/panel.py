"""ChatGPT-style general desktop Agent with persistent conversations and voice input."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QPalette, QShortcut, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from transcriber.assistant.chat_sessions import ChatSessionStore
from transcriber.assistant.ollama_client import OllamaCancellation, OllamaClient, OllamaError
from transcriber.assistant.prompt_library import PromptLibrary
from transcriber.assistant.skills import AgentSkillManager
from transcriber.opencode.acp_client import OpenCodeACPClient
from transcriber.ui.components.prompt_library_dialog import PromptLibraryDialog
from transcriber.ui.components.assistant.sessions import AssistantSessionMixin
from transcriber.ui.components.assistant.providers import AssistantProviderMixin
from transcriber.ui.components.assistant.voice import AssistantVoiceMixin
from transcriber.ui.components.assistant.conversation import AssistantConversationMixin
from transcriber.ui.components.assistant.activity_widget import AgentActivityWidget
from transcriber.ui.components.assistant.composer import MessageComposer
from transcriber.ui.components.assistant.conversation_view import ConversationView
from transcriber.ui.components.assistant.header import ConversationHeader
from transcriber.ui.components.assistant.sidebar import AssistantSidebar
from transcriber.ui.design.icon_registry import IconRegistry
from transcriber.ui.workers import FunctionWorker


class _AssistantSignals(QObject):
    notification = Signal(object)
    connected = Signal(object)
    error = Signal(str)
    prompt_complete = Signal(object)
    voice_state = Signal(str)
    voice_transcript = Signal(str)
    voice_audio = Signal(object)
    voice_error = Signal(str)
    voice_asr_complete = Signal(str)
    voice_asr_error = Signal(str)
    ollama_models_ready = Signal(object)
    ollama_refresh_error = Signal(str)
    ollama_connected = Signal(object)
    ollama_chunk = Signal(str)
    ollama_complete = Signal(object)
    ollama_error = Signal(str)
    ollama_tool_status = Signal(str)
    new_session_ready = Signal(str)
    new_session_error = Signal(str)
    session_loaded = Signal(str)
    session_load_error = Signal(str)
    ollama_tool_result = Signal(object)


class AssistantPanel(QWidget, AssistantSessionMixin, AssistantProviderMixin, AssistantVoiceMixin, AssistantConversationMixin):
    """A chat-first surface for the persistent OpenCode session."""

    status_message = Signal(str)

    QUICK_PROMPTS = {
        "Search the web": "Search the web for reliable information about the topic I provide, compare sources and summarize the findings with source links.",
        "Open an app": "Open the desktop application I name and tell me when it is ready.",
        "Find a file": "Help me locate a file or folder on this computer. Ask for a useful clue if the location is unclear.",
        "Review transcript": (
            "Review the currently open transcript for likely speech-recognition mistakes, "
            "unclear passages and inconsistencies. Explain suggested corrections first; "
            "do not modify the transcript until I approve."
        ),
    }

    def __init__(
        self, paths, thread_pool, settings_store=None, parent=None, *,
        voice_transcriber=None, model_manager=None, voice_model_loader=None,
    ):
        super().__init__(parent)
        self.paths = paths
        self.thread_pool = thread_pool
        self.settings_store = settings_store
        self.voice_transcriber = voice_transcriber
        self.voice_model_loader = voice_model_loader
        self.model_manager = model_manager
        self.voice_agent = None
        self.ollama_client: OllamaClient | None = None
        self._ollama_connected = False
        self._ollama_model = ""
        self._action_registry = None
        self._ollama_cancellation = None
        self.ui_icons = IconRegistry()
        session_directory = getattr(self.paths, "data", None) or self.paths.config
        self.session_store = ChatSessionStore(Path(session_directory) / "assistant_sessions.json")
        active_session = self.session_store.active_session()
        if active_session is None:
            default_provider = (
                self.settings_store.settings.chat_provider if self.settings_store else "opencode"
            )
            active_session = self.session_store.create_session(default_provider)
        self._active_session_id = active_session["id"]
        self._chat_provider = active_session["provider"]
        self._messages: list[dict[str, str]] = list(active_session["messages"])
        self._ollama_messages: list[dict] = list(active_session["provider_messages"])
        self._active_opencode_session_id = str(
            (active_session.get("metadata") or {}).get("opencode_session_id") or ""
        )
        self._start_voice_after_connect = False
        self._voice_conversation_mode = False
        self.prompt_library = PromptLibrary(self.paths.config / "agent_prompts")
        self.skill_manager = AgentSkillManager(self.paths.config / "agent-skills")
        self._resume_voice_after_prompt = False
        self._voice_asr_active = False
        self._last_voice_stage = ""
        self.signals = _AssistantSignals(self)
        self.signals.notification.connect(self._on_notification)
        self.signals.connected.connect(self._on_connected)
        self.signals.error.connect(self._on_error)
        self.signals.prompt_complete.connect(self._on_prompt_complete)
        self.signals.voice_state.connect(self._on_voice_state)
        self.signals.voice_transcript.connect(self._on_voice_transcript)
        self.signals.voice_audio.connect(self._on_voice_audio)
        self.signals.voice_error.connect(self._on_voice_error)
        self.signals.voice_asr_complete.connect(self._on_voice_asr_complete)
        self.signals.voice_asr_error.connect(self._on_voice_asr_error)
        self.signals.ollama_models_ready.connect(self._on_ollama_models_ready)
        self.signals.ollama_refresh_error.connect(self._on_ollama_refresh_error)
        self.signals.ollama_connected.connect(self._on_ollama_connected)
        self.signals.ollama_chunk.connect(self._append_stream_chunk)
        self.signals.ollama_complete.connect(self._on_ollama_chat_complete)
        self.signals.ollama_error.connect(self._on_ollama_error)
        self.signals.ollama_tool_status.connect(self._on_ollama_tool_status)
        self.signals.new_session_ready.connect(self._on_new_session_ready)
        self.signals.new_session_error.connect(self._on_new_session_error)
        self.signals.session_loaded.connect(self._on_session_loaded)
        self.signals.session_load_error.connect(self._on_session_load_error)
        self.signals.ollama_tool_result.connect(self._on_ollama_tool_result)

        self.client: OpenCodeACPClient | None = None
        self._worker_active = False
        self._streaming_index: int | None = None
        self._session_file = self.paths.config / "opencode-session.json"
        self._session_persist_timer = QTimer(self)
        self._session_persist_timer.setSingleShot(True)
        self._session_persist_timer.setInterval(350)
        self._session_persist_timer.timeout.connect(self._persist_current_session)
        self.project_dir = Path.cwd()
        if self.settings_store:
            saved_project = self.settings_store.settings.opencode_project_directory
            if saved_project and Path(saved_project).is_dir():
                self.project_dir = Path(saved_project).resolve()

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(10)
        title_group = QVBoxLayout()
        title_group.setSpacing(3)
        title = QLabel("AI assistant")
        title.setObjectName("AssistantTitle")
        subtitle = QLabel("General desktop agent · browser, apps, commands and skills")
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        title_group.addWidget(title)
        title_group.addWidget(subtitle)
        header.addLayout(title_group, 1)

        self.provider_combo = QComboBox()
        self.provider_combo.setObjectName("AssistantProviderSelect")
        self.provider_combo.addItem("OpenCode", "opencode")
        self.provider_combo.addItem("Ollama", "ollama")
        self.provider_combo.setMinimumWidth(112)
        self.provider_combo.setCurrentIndex(
            max(0, self.provider_combo.findData(self._chat_provider))
        )
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        header.addWidget(self.provider_combo)

        self.connection_state = QLabel("Disconnected")
        self.connection_state.setObjectName("AssistantStatus")
        self.connection_state.setProperty("state", "disconnected")
        header.addWidget(self.connection_state)

        self.connect_button = QPushButton("Connect")
        self.connect_button.setObjectName("AssistantConnectButton")
        self.connect_button.setIcon(self.ui_icons.icon("connect", size=16))
        self.connect_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.connect_button.setToolTip("Connect the selected AI provider")
        self.connect_button.clicked.connect(self.connect_provider)
        header.addWidget(self.connect_button)

        self.disconnect_button = QPushButton()
        self.disconnect_button.setObjectName("AssistantDisconnectButton")
        self.disconnect_button.setIcon(self.ui_icons.icon("stop", size=15))
        self.disconnect_button.setFixedSize(34, 34)
        self.disconnect_button.setToolTip("Disconnect the current provider")
        self.disconnect_button.clicked.connect(self.disconnect_provider)
        self.disconnect_button.setEnabled(False)
        header.addWidget(self.disconnect_button)

        self.settings_button = QPushButton("⚙")
        self.settings_button.setObjectName("AssistantSettingsButton")
        self.settings_button.setFixedSize(40, 40)
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.setToolTip("Assistant settings")
        self.settings_button.setAccessibleName("Open assistant settings")
        self.settings_button.clicked.connect(self.show_settings)
        header.addWidget(self.settings_button)
        root.addLayout(header)

        self.page_stack = QStackedWidget(self)
        self.page_stack.setObjectName("AssistantPageStack")
        self.conversation_page = QWidget()
        self.conversation_page.setObjectName("AssistantConversationPage")
        self.conversation_layout = QHBoxLayout(self.conversation_page)
        self.conversation_layout.setContentsMargins(0, 0, 0, 0)
        self.conversation_layout.setSpacing(0)

        self.sidebar = AssistantSidebar(self.session_store, self.ui_icons, self)
        self.sidebar.new_chat_requested.connect(self.new_chat)
        self.sidebar.session_selected.connect(self._on_session_item_clicked)
        self.sidebar.rename_requested.connect(self._rename_session)
        self.sidebar.delete_requested.connect(self._delete_session)
        self.sidebar.skills_requested.connect(self.show_skills)
        self.sidebar.settings_requested.connect(self.show_settings)
        self.agent_sidebar = self.sidebar  # compatibility alias
        self.new_chat_button = self.sidebar.new_chat_button
        self.session_list = self.sidebar.session_list
        self.skills_button = self.sidebar.skills_button
        self.conversation_layout.addWidget(self.agent_sidebar)
        chat_workspace = QWidget()
        chat_workspace.setObjectName("AssistantChatWorkspace")
        self.chat_layout = QVBoxLayout(chat_workspace)
        self.chat_layout.setContentsMargins(18, 4, 10, 6)
        self.chat_layout.setSpacing(10)
        self.conversation_header = ConversationHeader(self)
        self.session_title_label = self.conversation_header.title_label
        self.session_subtitle_label = self.conversation_header.subtitle_label
        self.chat_layout.addWidget(self.conversation_header)
        self.conversation_layout.addWidget(chat_workspace, 1)

        self.settings_page = QWidget()
        self.settings_page.setObjectName("AssistantSettingsPage")
        settings_page_layout = QVBoxLayout(self.settings_page)
        settings_page_layout.setContentsMargins(0, 0, 0, 0)
        settings_page_layout.setSpacing(12)

        settings_header = QHBoxLayout()
        self.settings_back_button = QPushButton("←  Back to conversation")
        self.settings_back_button.setObjectName("Subtle")
        self.settings_back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_back_button.clicked.connect(self.show_conversation)
        settings_header.addWidget(self.settings_back_button)
        settings_heading = QLabel("Assistant settings")
        settings_heading.setObjectName("AssistantTitle")
        settings_header.addWidget(settings_heading)
        settings_header.addStretch(1)
        settings_page_layout.addLayout(settings_header)

        self.settings_scroll = QScrollArea()
        self.settings_scroll.setObjectName("AssistantSettingsScroll")
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.settings_content = QWidget()
        self.settings_content.setObjectName("AssistantSettingsContent")
        self.settings_layout = QVBoxLayout(self.settings_content)
        self.settings_layout.setContentsMargins(0, 2, 8, 10)
        self.settings_layout.setSpacing(12)
        self.settings_scroll.setWidget(self.settings_content)
        settings_page_layout.addWidget(self.settings_scroll, 1)

        self.page_stack.addWidget(self.conversation_page)
        self.page_stack.addWidget(self.settings_page)
        self.page_stack.setCurrentWidget(self.conversation_page)
        root.addWidget(self.page_stack, 1)


        self.ollama_controls = QFrame()
        self.ollama_controls.setObjectName("AssistantContext")
        ollama_layout = QVBoxLayout(self.ollama_controls)
        ollama_layout.setContentsMargins(10, 8, 10, 8)
        ollama_layout.setSpacing(6)
        ollama_url_row = QHBoxLayout()
        ollama_url_row.addWidget(QLabel("Ollama URL"))
        self.ollama_url = QLineEdit(
            self.settings_store.settings.ollama_base_url
            if self.settings_store else "http://127.0.0.1:11434"
        )
        self.ollama_url.setPlaceholderText("http://127.0.0.1:11434")
        self.ollama_url.editingFinished.connect(self._provider_base_url_changed)
        ollama_url_row.addWidget(self.ollama_url, 1)
        ollama_layout.addLayout(ollama_url_row)
        ollama_model_row = QHBoxLayout()
        ollama_model_row.addWidget(QLabel("Model"))
        self.ollama_model_combo = QComboBox()
        self.ollama_model_combo.setMinimumWidth(130)
        self.ollama_model_combo.setToolTip("Choose a model already installed in your local Ollama service.")
        ollama_model_row.addWidget(self.ollama_model_combo, 1)
        self.refresh_ollama_button = QPushButton("Refresh")
        self.refresh_ollama_button.setObjectName("Subtle")
        self.refresh_ollama_button.clicked.connect(self.refresh_ollama_models)
        ollama_model_row.addWidget(self.refresh_ollama_button)
        ollama_layout.addLayout(ollama_model_row)
        self.ollama_help = QLabel(
            "Connects to the local Ollama API. Install models with ollama pull <model> first."
        )
        self.ollama_help.setObjectName("Muted")
        self.ollama_help.setWordWrap(True)
        ollama_layout.addWidget(self.ollama_help)
        self.ollama_controls.setVisible(self._chat_provider == "ollama")
        self.settings_layout.addWidget(self.ollama_controls)

        project_card = QFrame()
        project_card.setObjectName("AssistantContext")
        project_layout = QHBoxLayout(project_card)
        project_layout.setContentsMargins(11, 8, 9, 8)
        project_layout.setSpacing(8)
        project_text = QVBoxLayout()
        project_text.setSpacing(2)
        project_caption = QLabel("PROJECT CONTEXT")
        project_caption.setObjectName("AssistantEyebrow")
        self.project_label = QLabel(str(self.project_dir))
        self.project_label.setObjectName("AssistantProject")
        self.project_label.setWordWrap(True)
        self.project_label.setToolTip(str(self.project_dir))
        project_text.addWidget(project_caption)
        project_text.addWidget(self.project_label)
        project_layout.addLayout(project_text, 1)

        self.project_button = QPushButton("Change")
        self.project_button.setObjectName("Subtle")
        self.project_button.setToolTip("Choose the project directory for the OpenCode session")
        self.project_button.clicked.connect(self.choose_project)
        project_layout.addWidget(self.project_button)
        self.project_card = project_card
        self.settings_layout.addWidget(project_card)

        prompt_library_card = QFrame()
        prompt_library_card.setObjectName("AssistantSettingsCard")
        prompt_library_layout = QVBoxLayout(prompt_library_card)
        prompt_library_layout.setContentsMargins(14, 12, 14, 12)
        prompt_library_layout.setSpacing(7)
        prompt_library_title = QLabel("Agent instructions")
        prompt_library_title.setObjectName("AssistantSectionTitle")
        prompt_library_description = QLabel(
            "Manage the coordinator prompt and specialist instructions used by OpenCode."
        )
        prompt_library_description.setObjectName("Muted")
        prompt_library_description.setWordWrap(True)
        self.prompt_library_button = QPushButton("Open prompt library")
        self.prompt_library_button.setObjectName("Subtle")
        self.prompt_library_button.setToolTip(
            "Edit specialist instructions, paste prompts or copy the Agent coordinator prompt."
        )
        self.prompt_library_button.clicked.connect(self.open_prompt_library)
        prompt_library_layout.addWidget(prompt_library_title)
        prompt_library_layout.addWidget(prompt_library_description)
        prompt_library_layout.addWidget(self.prompt_library_button)
        self.settings_layout.addWidget(prompt_library_card)

        self.skills_card = QFrame()
        self.skills_card.setObjectName("AssistantSettingsCard")
        skills_layout = QVBoxLayout(self.skills_card)
        skills_layout.setContentsMargins(14, 12, 14, 14)
        skills_layout.setSpacing(8)
        skills_title = QLabel("Agent skills")
        skills_title.setObjectName("AssistantSectionTitle")
        skills_layout.addWidget(skills_title)
        skills_description = QLabel(
            "Skills add reusable workflows and specialist knowledge. The Agent loads a skill's "
            "instructions only when a task matches its description. Downloaded scripts are stored "
            "as resources and are never executed automatically."
        )
        skills_description.setObjectName("Muted")
        skills_description.setWordWrap(True)
        skills_layout.addWidget(skills_description)
        self.skills_catalog_combo = QComboBox()
        for item in self.skill_manager.CATALOG:
            self.skills_catalog_combo.addItem(item["label"], item["url"])
        skills_layout.addWidget(self.skills_catalog_combo)
        skills_actions = QHBoxLayout()
        self.skills_install_button = QPushButton("Install selected skill")
        self.skills_install_button.setObjectName("Primary")
        self.skills_install_button.clicked.connect(self.install_selected_skill)
        self.skills_refresh_button = QPushButton("Refresh")
        self.skills_refresh_button.setObjectName("Subtle")
        self.skills_refresh_button.clicked.connect(self.refresh_skills)
        skills_actions.addWidget(self.skills_install_button)
        skills_actions.addWidget(self.skills_refresh_button)
        skills_layout.addLayout(skills_actions)
        self.skills_custom_url = QLineEdit()
        self.skills_custom_url.setPlaceholderText(
            "Or paste a GitHub skill folder URL …/tree/main/path/to/skill"
        )
        skills_layout.addWidget(self.skills_custom_url)
        self.skills_custom_install_button = QPushButton("Install from GitHub URL")
        self.skills_custom_install_button.setObjectName("Subtle")
        self.skills_custom_install_button.clicked.connect(self.install_custom_skill)
        skills_layout.addWidget(self.skills_custom_install_button)
        self.skills_list_label = QLabel()
        self.skills_list_label.setObjectName("AssistantSkillsList")
        self.skills_list_label.setWordWrap(True)
        skills_layout.addWidget(self.skills_list_label)
        self.skills_status_label = QLabel("")
        self.skills_status_label.setObjectName("Muted")
        self.skills_status_label.setWordWrap(True)
        skills_layout.addWidget(self.skills_status_label)
        self.settings_layout.addWidget(self.skills_card)
        self.refresh_skills()

        self.conversation_view = ConversationView(self.QUICK_PROMPTS, self.ui_icons, self)
        self.conversation_view.prompt_requested.connect(self._insert_suggestion)
        self.chat_layout.addWidget(self.conversation_view, 1)

        # Legacy inspection surface kept synchronized for integrations that
        # historically read chat_view.toPlainText().
        self.chat_view = QTextBrowser(self)
        self.chat_view.setObjectName("AssistantChatCompatibilityMirror")
        self.chat_view.hide()
        self.log = self.chat_view

        self.activity_widget = AgentActivityWidget(self.ui_icons, self)
        self.chat_layout.addWidget(self.activity_widget)
        self._activity_event_counter = 0

        self.activity_label = QLabel("Connect an AI provider to start using your desktop agent.")
        self.activity_label.setObjectName("Muted")
        self.activity_label.setWordWrap(True)
        self.chat_layout.addWidget(self.activity_label)

        suggestion_header = QHBoxLayout()
        suggestion_label = QLabel("QUICK PROMPTS")
        suggestion_label.setObjectName("AssistantEyebrow")
        suggestion_header.addWidget(suggestion_label)
        suggestion_header.addStretch(1)
        self.chat_layout.addLayout(suggestion_header)

        suggestions = QHBoxLayout()
        suggestions.setSpacing(6)
        for label, prompt in self.QUICK_PROMPTS.items():
            button = QPushButton(label)
            button.setObjectName("Suggestion")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, text=prompt: self._insert_suggestion(text))
            suggestions.addWidget(button)
        self.suggestions_container = QWidget()
        self.suggestions_container.setObjectName("AssistantSuggestions")
        self.suggestions_container.setLayout(suggestions)
        self.chat_layout.addWidget(self.suggestions_container)
        self.suggestions_container.hide()  # prompts now live in the centered empty state

        self.composer = MessageComposer(self.ui_icons, self)
        self.prompt = self.composer.prompt
        self.voice_chat_button = self.composer.voice_chat_button
        self.voice_live_status = self.composer.voice_live_status
        self.agent_mode_check = self.composer.agent_mode_check
        self.stop_button = self.composer.stop_button
        self.send_button = self.composer.send_button
        self.composer.send_requested.connect(self.send_prompt)
        self.composer.stop_requested.connect(self.cancel_prompt)
        self.composer.voice_requested.connect(self.start_voice_chat)
        self.chat_layout.addWidget(self.composer)



        self.voice_panel = QFrame()
        self.voice_panel.setObjectName("AssistantSettingsCard")
        voice_layout = QVBoxLayout(self.voice_panel)
        voice_layout.setContentsMargins(14, 12, 14, 14)
        voice_layout.setSpacing(9)

        voice_header = QHBoxLayout()
        voice_section_title = QLabel("Voice input")
        voice_section_title.setObjectName("AssistantSectionTitle")
        voice_header.addWidget(voice_section_title)
        voice_header.addStretch(1)
        self.voice_state_label = QLabel("Voice off")
        self.voice_state_label.setObjectName("Muted")
        voice_header.addWidget(self.voice_state_label)
        voice_header.addStretch(1)
        voice_layout.addLayout(voice_header)

        wake_phrase_title = QLabel("Activation keyword / phrase")
        voice_layout.addWidget(wake_phrase_title)
        self.wake_phrase = QLineEdit(
            self.settings_store.settings.wake_phrase if self.settings_store else "transcriber"
        )
        self.wake_phrase.setPlaceholderText("For example: transcriber")
        self.wake_phrase.setToolTip(
            "Vosk listens for this phrase. Use words supported by the selected model's language."
        )
        voice_layout.addWidget(self.wake_phrase)

        asr_title = QLabel("Faster-Whisper speech-to-text model")
        voice_layout.addWidget(asr_title)
        self.voice_asr_combo = QComboBox()
        self.voice_asr_combo.setToolTip(
            "This local model turns each captured voice command into text before it is sent to the chat model."
        )
        self.voice_asr_combo.currentIndexChanged.connect(self._voice_asr_model_changed)
        voice_layout.addWidget(self.voice_asr_combo)
        self.refresh_voice_asr_models(
            self.settings_store.settings.voice_asr_model if self.settings_store else ""
        )

        model_title = QLabel("Vosk model used for wake-word detection")
        voice_layout.addWidget(model_title)
        model_row = QHBoxLayout()
        self.wake_model_combo = QComboBox()
        self.wake_model_combo.setMinimumWidth(170)
        self.wake_model_combo.setToolTip(
            "This model detects only the activation phrase. Faster-Whisper transcribes the command."
        )
        self.wake_model_refresh_button = QPushButton("Refresh")
        self.wake_model_refresh_button.setObjectName("Subtle")
        self.wake_model_refresh_button.clicked.connect(lambda: self.refresh_wake_models())
        self.wake_model_browse_button = QPushButton("Browse local…")
        self.wake_model_browse_button.setObjectName("Subtle")
        self.wake_model_browse_button.clicked.connect(self.choose_wake_model)
        model_row.addWidget(self.wake_model_combo, 1)
        model_row.addWidget(self.wake_model_refresh_button)
        model_row.addWidget(self.wake_model_browse_button)
        voice_layout.addLayout(model_row)
        self.wake_model_help = QLabel()
        self.wake_model_help.setObjectName("Muted")
        self.wake_model_help.setWordWrap(True)
        voice_layout.addWidget(self.wake_model_help)
        saved_model = (
            self.settings_store.settings.wake_model_directory if self.settings_store else ""
        )
        self.refresh_wake_models(saved_model)

        voice_actions = QHBoxLayout()
        self.wake_button = QPushButton("Enable local wake")
        self.wake_button.setObjectName("Subtle")
        self.wake_button.clicked.connect(self.toggle_voice_agent)
        self.ptt_button = QPushButton("Push to talk")
        self.ptt_button.setObjectName("Subtle")
        self.ptt_button.clicked.connect(self.push_to_talk)
        self.ptt_button.setEnabled(False)
        self.wake_button.hide()
        voice_actions.addWidget(self.ptt_button)
        voice_layout.addLayout(voice_actions)

        voice_options = QHBoxLayout()
        voice_options.addWidget(QLabel("Finish after"))
        self.voice_silence_spin = QDoubleSpinBox()
        self.voice_silence_spin.setRange(0.5, 8.0)
        self.voice_silence_spin.setDecimals(1)
        self.voice_silence_spin.setSingleStep(0.1)
        self.voice_silence_spin.setSuffix(" s silence")
        self.voice_silence_spin.setValue(
            getattr(self.settings_store.settings, "voice_silence_seconds", 1.5)
            if self.settings_store else 1.5
        )
        self.voice_silence_spin.valueChanged.connect(self._set_voice_silence_seconds)
        voice_options.addWidget(self.voice_silence_spin)
        voice_options.addStretch(1)
        voice_layout.addLayout(voice_options)

        self.voice_auto_submit_check = QCheckBox(
            "Send recognized commands to Agent automatically"
        )
        self.voice_auto_submit_check.setChecked(
            bool(self.settings_store and self.settings_store.settings.voice_auto_submit)
        )
        self.voice_auto_submit_check.toggled.connect(self._set_voice_auto_submit)
        voice_layout.addWidget(self.voice_auto_submit_check)
        voice_help = QLabel(
            "Vosk listens locally for the wake phrase. The app then records your command, "
            "waits for the full silence interval and transcribes it with the installed local Faster-Whisper model. "
            "Commands stay in memory and are not saved as recordings."
        )
        voice_help.setObjectName("Muted")
        voice_help.setWordWrap(True)
        voice_layout.addWidget(voice_help)

        self.voice_panel.setVisible(True)
        self.settings_layout.addWidget(self.voice_panel)

        privacy = QLabel(
            "Voice wake detection and command audio are processed locally. "
            "Only the recognized text is sent to the selected chat provider."
        )
        privacy.setObjectName("Muted")
        privacy.setWordWrap(True)
        privacy_card = QFrame()
        privacy_card.setObjectName("AssistantSettingsCard")
        privacy_layout = QVBoxLayout(privacy_card)
        privacy_layout.setContentsMargins(14, 10, 14, 10)
        privacy_layout.addWidget(privacy)
        self.settings_layout.addWidget(privacy_card)
        self.settings_layout.addStretch(1)

        self._chat_refresh_timer = QTimer(self)
        self._chat_refresh_timer.setSingleShot(True)
        self._chat_refresh_timer.setInterval(45)
        self._chat_refresh_timer.timeout.connect(self._refresh_chat)
        self._refresh_chat()
        self._apply_provider_ui()
        self._refresh_session_list()
        self._refresh_chat()
        self._sync_voice_orb()

    def refresh_skills(self):
        skills = self.skill_manager.list_skills()
        if not skills:
            self.skills_list_label.setText("No Agent Skills are installed.")
            return
        self.skills_list_label.setText(
            "Installed skills\\n"
            + "\\n".join(
                f"• {skill.name} — {skill.description}" for skill in skills
            )
        )

    def show_skills(self):
        self.show_settings()
        QTimer.singleShot(0, lambda: self.settings_scroll.ensureWidgetVisible(self.skills_card, 12, 12))

    def install_selected_skill(self):
        url = str(self.skills_catalog_combo.currentData() or "").strip()
        if url:
            self._install_skill_url(url)

    def install_custom_skill(self):
        url = self.skills_custom_url.text().strip()
        if not url:
            self.skills_status_label.setText("Paste a public GitHub skill folder URL first.")
            return
        self._install_skill_url(url)

    def _install_skill_url(self, url: str):
        self.skills_install_button.setEnabled(False)
        self.skills_custom_install_button.setEnabled(False)
        self.skills_status_label.setText("Downloading and validating the Agent Skill…")
        worker = FunctionWorker(lambda _emit: self.skill_manager.install_from_github(url))
        worker.signals.result.connect(self._on_skill_installed)
        worker.signals.error.connect(
            lambda message: self.skills_status_label.setText(f"Skill installation failed: {message}")
        )
        worker.signals.finished.connect(
            lambda: (
                self.skills_install_button.setEnabled(True),
                self.skills_custom_install_button.setEnabled(True),
            )
        )
        self.thread_pool.start(worker)

    def _on_skill_installed(self, skill):
        self.refresh_skills()
        self.skills_status_label.setText(
            f"Installed {skill.name}. Its instructions are now available to the Agent."
        )
        self.skills_custom_url.clear()

    def set_agent_runtime(self, action_registry):
        """Attach the application's permission-aware action registry."""
        self._action_registry = action_registry
        if action_registry is None:
            self.agent_mode_check.setChecked(False)
        else:
            self.agent_mode_check.setToolTip(
                "Ollama sees only currently permitted tools. Desktop actions remain hidden "
                "until Desktop control is enabled in Settings, and each action asks before running."
            )
        self._apply_provider_ui()

    def show_settings(self):
        """Switch to the dedicated assistant settings page."""
        self.page_stack.setCurrentWidget(self.settings_page)
        self.settings_button.setAccessibleName("Assistant settings open")

    def show_conversation(self):
        """Return to the uncluttered conversation surface."""
        self.page_stack.setCurrentWidget(self.conversation_page)
        self.settings_button.setAccessibleName("Open assistant settings")
        self.prompt.setFocus()

    @staticmethod
    def _markdown_fragment(value: str) -> str:
        """Render message Markdown using Qt's rich-text parser."""
        document = QTextDocument()
        document.setMarkdown(str(value or ""))
        rendered = document.toHtml()
        lowered = rendered.casefold()
        body_start = lowered.find("<body")
        if body_start >= 0:
            opening_end = rendered.find(">", body_start)
            closing_start = lowered.find("</body>", opening_end)
            if opening_end >= 0 and closing_start >= 0:
                fragment = rendered[opening_end + 1:closing_start]
            elif opening_end >= 0:
                fragment = rendered[opening_end + 1:]
            else:
                fragment = rendered
        else:
            fragment = rendered
        return fragment
    def sync_settings(self):
        if not self.settings_store:
            return
        settings = self.settings_store.settings
        self.wake_phrase.setText(settings.wake_phrase)
        self.ollama_url.setText(settings.ollama_base_url)
        provider_index = self.provider_combo.findData(settings.chat_provider)
        if provider_index >= 0 and provider_index != self.provider_combo.currentIndex():
            self.provider_combo.setCurrentIndex(provider_index)
        self.refresh_voice_asr_models(settings.voice_asr_model)
        if hasattr(self, "voice_silence_spin"):
            self.voice_silence_spin.setValue(settings.voice_silence_seconds)
        if hasattr(self, "voice_auto_submit_check"):
            self.voice_auto_submit_check.setChecked(settings.voice_auto_submit)
        self.refresh_wake_models(settings.wake_model_directory)
        if not (self.client and self.client.connected) and settings.opencode_project_directory:
            candidate = Path(settings.opencode_project_directory).expanduser()
            if candidate.is_dir():
                self.project_dir = candidate.resolve()
                self._set_project_label()

    def _set_project_label(self):
        path = str(self.project_dir)
        self.project_label.setText(path if len(path) <= 54 else f"…{path[-51:]}")
        self.project_label.setToolTip(path)

    def choose_project(self):
        path = QFileDialog.getExistingDirectory(
            self, "Choose OpenCode project", str(self.project_dir)
        )
        if not path:
            return
        new_path = Path(path).resolve()
        if not new_path.is_dir():
            return
        if self.client and self.client.connected:
            QMessageBox.information(
                self, "Disconnect first",
                "The active ACP process is bound to its original working directory. "
                "Disconnect first, then change the project and reconnect.",
            )
            return
        self.project_dir = new_path
        self._set_project_label()
        if self.settings_store:
            self.settings_store.update(opencode_project_directory=str(new_path))

    @staticmethod
    def _mcp_child_environment(source=None):
        """Pass only the runtime environment needed by the local MCP process."""
        allowed = {
            "path", "systemroot", "windir", "temp", "tmp", "home",
            "userprofile", "appdata", "localappdata", "programdata",
            "virtual_env", "conda_prefix", "pythonpath", "pythonhome",
            "ld_library_path", "dyld_library_path",
        }
        source = os.environ if source is None else source
        return {
            str(key): str(value)
            for key, value in source.items()
            if str(key).casefold() in allowed
        }

    def _mcp_server_config(self):
        if getattr(sys, "frozen", False):
            command, args = sys.executable, ["--mcp-server"]
        else:
            command, args = sys.executable, ["-m", "transcriber.mcp_server"]
        return [{
            "type": "stdio",
            "name": "transcriber",
            "command": command,
            "args": args,
            "env": self._mcp_child_environment(),
        }]

    def shutdown(self):
        self._session_persist_timer.stop()
        self._persist_current_session()
        if self.voice_agent:
            agent, self.voice_agent = self.voice_agent, None
            worker = FunctionWorker(lambda _emit: agent.stop())
            self.thread_pool.start(worker)
        if self.client:
            self.client.close()
            self.client = None
