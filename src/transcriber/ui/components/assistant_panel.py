"""Conversational OpenCode ACP panel with workspace-aware MCP assistance."""

from __future__ import annotations

import html
import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QPalette, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from transcriber.assistant.prompt_library import PromptLibrary
from transcriber.opencode.acp_client import OpenCodeACPClient
from transcriber.ui.components.prompt_library_dialog import PromptLibraryDialog
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


class AssistantPanel(QWidget):
    """A chat-first surface for the persistent OpenCode session."""

    status_message = Signal(str)

    QUICK_PROMPTS = {
        "Summarize": (
            "Use the current Transcriber workspace context to summarize the open transcript. "
            "Keep the summary concise and preserve important names, dates and decisions."
        ),
        "Review transcript": (
            "Review the currently open transcript for likely speech-recognition mistakes, "
            "unclear passages and inconsistencies. Explain suggested corrections first; "
            "do not modify the transcript until I approve."
        ),
        "Action items": (
            "Extract decisions, tasks, owners and deadlines from the current transcript. "
            "Clearly mark information that is not explicitly stated."
        ),
    }

    def __init__(self, paths, thread_pool, settings_store=None, parent=None, *, voice_transcriber=None):
        super().__init__(parent)
        self.paths = paths
        self.thread_pool = thread_pool
        self.settings_store = settings_store
        self.voice_transcriber = voice_transcriber
        self.voice_agent = None
        self.prompt_library = PromptLibrary(self.paths.config / "agent_prompts")
        self._agent_instructions_injected = False
        self._bootstrap_pending = False
        self._resume_voice_after_prompt = False
        self._voice_asr_active = False
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

        self.client: OpenCodeACPClient | None = None
        self._worker_active = False
        self._messages: list[dict[str, str]] = []
        self._streaming_index: int | None = None
        self._session_file = self.paths.config / "opencode-session.json"
        self.project_dir = Path.cwd()
        if self.settings_store:
            saved_project = self.settings_store.settings.opencode_project_directory
            if saved_project and Path(saved_project).is_dir():
                self.project_dir = Path(saved_project).resolve()

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        title_group = QVBoxLayout()
        title_group.setSpacing(2)
        title = QLabel("AI assistant")
        title.setObjectName("AssistantTitle")
        subtitle = QLabel("Work with the current Transcriber workspace")
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        title_group.addWidget(title)
        title_group.addWidget(subtitle)
        header.addLayout(title_group, 1)

        self.connection_state = QLabel("Disconnected")
        self.connection_state.setObjectName("AssistantStatus")
        self.connection_state.setProperty("state", "disconnected")
        header.addWidget(self.connection_state)
        root.addLayout(header)

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
        root.addWidget(project_card)

        self.chat_view = QTextBrowser()
        self.chat_view.setObjectName("AssistantChat")
        self.chat_view.setOpenExternalLinks(False)
        self.chat_view.setOpenLinks(False)
        self.chat_view.setReadOnly(True)
        self.chat_view.setPlaceholderText("Connect to OpenCode to start a conversation.")
        self.chat_view.setMinimumHeight(150)
        root.addWidget(self.chat_view, 1)
        # Retain the old attribute name for integrations which inspect the panel.
        self.log = self.chat_view

        self.activity_label = QLabel("Connect to OpenCode to enable the workspace assistant.")
        self.activity_label.setObjectName("Muted")
        self.activity_label.setWordWrap(True)
        root.addWidget(self.activity_label)

        suggestion_header = QHBoxLayout()
        suggestion_label = QLabel("START WITH")
        suggestion_label.setObjectName("AssistantEyebrow")
        suggestion_header.addWidget(suggestion_label)
        suggestion_header.addStretch(1)
        self.prompt_library_button = QPushButton("Prompt library")
        self.prompt_library_button.setObjectName("Subtle")
        self.prompt_library_button.setToolTip(
            "Edit specialist instructions, paste prompts or copy the Agent coordinator prompt."
        )
        self.prompt_library_button.clicked.connect(self.open_prompt_library)
        suggestion_header.addWidget(self.prompt_library_button)
        root.addLayout(suggestion_header)

        suggestions = QHBoxLayout()
        suggestions.setSpacing(6)
        for label, prompt in self.QUICK_PROMPTS.items():
            button = QPushButton(label)
            button.setObjectName("Suggestion")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, text=prompt: self._insert_suggestion(text))
            suggestions.addWidget(button)
        root.addLayout(suggestions)

        composer = QFrame()
        composer.setObjectName("AssistantComposer")
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(10, 9, 10, 9)
        composer_layout.setSpacing(8)
        self.prompt = QPlainTextEdit()
        self.prompt.setObjectName("AssistantPrompt")
        self.prompt.setPlaceholderText("Ask about the transcript, request an edit, or explore your workspace…")
        self.prompt.setMinimumHeight(68)
        self.prompt.setMaximumHeight(126)
        self.prompt.setTabChangesFocus(True)
        self.prompt.document().setMaximumBlockCount(80)
        composer_layout.addWidget(self.prompt)

        composer_actions = QHBoxLayout()
        composer_hint = QLabel("Ctrl + Enter to send")
        composer_hint.setObjectName("Muted")
        composer_actions.addWidget(composer_hint)
        composer_actions.addStretch(1)

        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("Subtle")
        self.stop_button.clicked.connect(self.cancel_prompt)
        self.stop_button.setEnabled(False)
        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("Primary")
        self.send_button.clicked.connect(self.send_prompt)
        self.send_button.setEnabled(False)
        composer_actions.addWidget(self.stop_button)
        composer_actions.addWidget(self.send_button)
        composer_layout.addLayout(composer_actions)
        root.addWidget(composer)

        self.send_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self.prompt)
        self.send_shortcut.activated.connect(self.send_prompt)
        self.send_shortcut_alt = QShortcut(QKeySequence("Ctrl+Enter"), self.prompt)
        self.send_shortcut_alt.activated.connect(self.send_prompt)

        connection_row = QHBoxLayout()
        connection_row.setSpacing(8)
        self.connect_button = QPushButton("Connect OpenCode")
        self.connect_button.setObjectName("Primary")
        self.connect_button.clicked.connect(self.connect_opencode)
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.setObjectName("Subtle")
        self.disconnect_button.clicked.connect(self.disconnect_opencode)
        self.disconnect_button.setEnabled(False)
        connection_row.addWidget(self.connect_button, 1)
        connection_row.addWidget(self.disconnect_button)
        root.addLayout(connection_row)

        self.voice_toggle = QPushButton("＋  Voice input settings")
        self.voice_toggle.setObjectName("Disclosure")
        self.voice_toggle.setCheckable(True)
        self.voice_toggle.toggled.connect(self._toggle_voice_panel)
        root.addWidget(self.voice_toggle)

        self.voice_panel = QFrame()
        self.voice_panel.setObjectName("AssistantVoicePanel")
        voice_layout = QVBoxLayout(self.voice_panel)
        voice_layout.setContentsMargins(10, 9, 10, 9)
        voice_layout.setSpacing(7)

        voice_header = QHBoxLayout()
        self.voice_state_label = QLabel("Voice off")
        self.voice_state_label.setObjectName("Muted")
        voice_header.addWidget(self.voice_state_label)
        voice_header.addStretch(1)
        voice_layout.addLayout(voice_header)

        self.wake_phrase = QLineEdit(
            self.settings_store.settings.wake_phrase if self.settings_store else "transcriber"
        )
        self.wake_phrase.setPlaceholderText("Local wake phrase")
        voice_layout.addWidget(self.wake_phrase)

        model_row = QHBoxLayout()
        saved_model = self.settings_store.settings.wake_model_directory if self.settings_store else ""
        self.wake_model_label = QLabel(Path(saved_model).name if saved_model else "No local Vosk model selected")
        self.wake_model_label.setObjectName("Muted")
        self.wake_model_label.setToolTip(saved_model or "")
        self.wake_model_label.setWordWrap(True)
        self.wake_model_button = QPushButton("Choose model…")
        self.wake_model_button.setObjectName("Subtle")
        self.wake_model_button.clicked.connect(self.choose_wake_model)
        model_row.addWidget(self.wake_model_label, 1)
        model_row.addWidget(self.wake_model_button)
        voice_layout.addLayout(model_row)

        voice_actions = QHBoxLayout()
        self.wake_button = QPushButton("Enable local wake")
        self.wake_button.setObjectName("Subtle")
        self.wake_button.clicked.connect(self.toggle_voice_agent)
        self.ptt_button = QPushButton("Push to talk")
        self.ptt_button.setObjectName("Subtle")
        self.ptt_button.clicked.connect(self.push_to_talk)
        self.ptt_button.setEnabled(False)
        voice_actions.addWidget(self.wake_button, 1)
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

        self.voice_panel.setVisible(False)
        root.addWidget(self.voice_panel)

        privacy = QLabel(
            "OpenCode ACP · Transcriber MCP tools · Wake detection and command audio are processed locally."
        )
        privacy.setObjectName("Muted")
        privacy.setWordWrap(True)
        root.addWidget(privacy)

        self._chat_refresh_timer = QTimer(self)
        self._chat_refresh_timer.setSingleShot(True)
        self._chat_refresh_timer.setInterval(45)
        self._chat_refresh_timer.timeout.connect(self._refresh_chat)
        self._refresh_chat()

    def _toggle_voice_panel(self, expanded: bool):
        self.voice_panel.setVisible(expanded)
        self.voice_toggle.setText("−  Voice input settings" if expanded else "＋  Voice input settings")

    def _insert_suggestion(self, prompt: str):
        current = self.prompt.toPlainText().strip()
        self.prompt.setPlainText(f"{current}\n\n{prompt}" if current else prompt)
        self.prompt.setFocus()
        cursor = self.prompt.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.prompt.setTextCursor(cursor)

    def _schedule_chat_refresh(self):
        if not self._chat_refresh_timer.isActive():
            self._chat_refresh_timer.start()

    def _refresh_chat(self):
        palette = self.chat_view.palette()
        text_color = palette.color(QPalette.ColorRole.Text).name()
        muted_color = palette.color(QPalette.ColorRole.PlaceholderText).name()
        surface_color = palette.color(QPalette.ColorRole.AlternateBase).name()
        accent_color = palette.color(QPalette.ColorRole.Highlight).name()
        accent_text = palette.color(QPalette.ColorRole.HighlightedText).name()

        if not self._messages:
            content = (
                '<div align="center" style="margin:34px 12px 14px 12px;">'
                '<div style="font-size:15px;font-weight:700;">A better way to work with your audio</div>'
                f'<p style="color:{muted_color};line-height:1.55;">Connect OpenCode to ask questions, '
                'review transcript text and run approved workspace actions. Your quick prompts are a good place to start.</p>'
                '</div>'
            )
        else:
            blocks = []
            for message in self._messages[-180:]:
                role = message["role"]
                raw_text = str(message.get("text", ""))
                safe_text = html.escape(raw_text).replace("\n", "<br>")
                if role == "user":
                    blocks.append(
                        '<div style="margin:12px 2px 12px 18px;">'
                        '<div align="right" style="font-size:10px;font-weight:700;'
                        f'color:{muted_color};margin-bottom:4px;">YOU</div>'
                        '<div align="right">'
                        f'<span style="background:{accent_color};color:{accent_text};'
                        f'padding:9px 11px;border-radius:12px;">{safe_text}</span>'
                        '</div></div>'
                    )
                elif role == "assistant":
                    blocks.append(
                        '<div style="margin:12px 18px 12px 2px;">'
                        '<div style="font-size:10px;font-weight:700;'
                        f'color:{muted_color};margin-bottom:4px;">OPENCODE</div>'
                        f'<div style="background:{surface_color};color:{text_color};'
                        f'padding:10px 12px;border-radius:12px;line-height:1.5;">{safe_text}</div>'
                        '</div>'
                    )
                elif role == "tool":
                    blocks.append(
                        '<div style="margin:8px 2px;padding:7px 9px;'
                        f'background:{surface_color};border-radius:8px;'
                        f'color:{muted_color};font-size:11px;">'
                        f'⚙  {safe_text}</div>'
                    )
                elif role == "error":
                    blocks.append(
                        '<div style="margin:8px 2px;padding:9px 11px;'
                        'background:#7f1d1d;color:#fee2e2;border-radius:9px;">'
                        f'{safe_text}</div>'
                    )
                else:
                    blocks.append(
                        '<div align="center" style="margin:8px 4px;'
                        f'color:{muted_color};font-size:11px;">{safe_text}</div>'
                    )
            content = "".join(blocks)

        self.chat_view.setHtml(
            "<html><head><meta charset='utf-8'></head>"
            f"<body style='font-family:Segoe UI,Noto Sans,sans-serif;"
            f"font-size:12px;color:{text_color};margin:8px;'>{content}</body></html>"
        )
        scrollbar = self.chat_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _append_message(self, role: str, text: str):
        self._messages.append({"role": role, "text": str(text)})
        if len(self._messages) > 180:
            del self._messages[:-180]
        self._schedule_chat_refresh()

    def _append_stream_chunk(self, text: str):
        if not text:
            return
        if self._streaming_index is None or self._streaming_index >= len(self._messages):
            self._messages.append({"role": "assistant", "text": ""})
            self._streaming_index = len(self._messages) - 1
        self._messages[self._streaming_index]["text"] += str(text)
        self._schedule_chat_refresh()

    def _append(self, text):
        """Compatibility helper that turns former log lines into typed chat items."""
        message = str(text)
        if message.startswith("You: "):
            self._append_message("user", message[5:])
        elif message.startswith("OpenCode: "):
            self._append_message("assistant", message[10:])
        elif message.startswith("Tool: "):
            self._append_message("tool", message[6:])
        elif message.startswith("Tool status: "):
            self._append_message("tool", message[13:])
        elif message.startswith("Error: "):
            self._append_message("error", message[7:])
        else:
            self._append_message("system", message)

    def sync_settings(self):
        if not self.settings_store:
            return
        settings = self.settings_store.settings
        self.wake_phrase.setText(settings.wake_phrase)
        if hasattr(self, "voice_silence_spin"):
            self.voice_silence_spin.setValue(settings.voice_silence_seconds)
        if hasattr(self, "voice_auto_submit_check"):
            self.voice_auto_submit_check.setChecked(settings.voice_auto_submit)
        model_directory = settings.wake_model_directory
        self.wake_model_label.setText(Path(model_directory).name if model_directory else "No local Vosk model selected")
        self.wake_model_label.setToolTip(model_directory or "")
        if not (self.client and self.client.connected) and settings.opencode_project_directory:
            candidate = Path(settings.opencode_project_directory).expanduser()
            if candidate.is_dir():
                self.project_dir = candidate.resolve()
                self._set_project_label()

    def _set_project_label(self):
        path = str(self.project_dir)
        self.project_label.setText(path if len(path) <= 54 else f"…{path[-51:]}")
        self.project_label.setToolTip(path)

    def choose_wake_model(self):
        saved = self.settings_store.settings.wake_model_directory if self.settings_store else ""
        path = QFileDialog.getExistingDirectory(
            self, "Choose local Vosk model directory", saved or str(self.paths.models)
        )
        if not path:
            return
        model_path = Path(path).resolve()
        if not (model_path / "am").is_dir() and not (model_path / "conf").is_dir():
            QMessageBox.warning(
                self, "Invalid Vosk model",
                "The selected directory does not look like a Vosk model folder (expected am/ or conf/).",
            )
            return
        if self.settings_store:
            self.settings_store.update(wake_model_directory=str(model_path))
        self.wake_model_label.setText(model_path.name)
        self.wake_model_label.setToolTip(str(model_path))

    def toggle_voice_agent(self):
        if self.voice_agent is not None:
            agent, self.voice_agent = self.voice_agent, None
            worker = FunctionWorker(lambda _emit: agent.stop())
            worker.signals.error.connect(self._on_voice_error)
            self.thread_pool.start(worker)
            self.wake_button.setText("Enable local wake")
            self.ptt_button.setEnabled(False)
            self.voice_state_label.setText("Voice off")
            self._append_message("system", "Local voice input stopped; microphone released.")
            return

        model_path = self.settings_store.settings.wake_model_directory if self.settings_store else None
        phrase = self.wake_phrase.text().strip()
        if self.settings_store:
            self.settings_store.update(wake_phrase=phrase)
        if not model_path or not Path(model_path).is_dir():
            QMessageBox.information(
                self, "Vosk model required",
                "Choose a locally installed Vosk model before enabling wake detection.",
            )
            return
        try:
            from transcriber.assistant.speech_input import VoskVoiceAgent
        except ImportError as exc:
            QMessageBox.warning(self, "Voice support unavailable", str(exc))
            return

        if not callable(self.voice_transcriber):
            QMessageBox.warning(
                self, "Voice transcription unavailable",
                "The local Faster-Whisper voice transcription service is not available.",
            )
            return

        configured = self.settings_store.settings if self.settings_store else None
        agent = VoskVoiceAgent(
            model_path, phrase,
            silence_seconds=(
                self.voice_silence_spin.value() if hasattr(self, "voice_silence_spin") else
                getattr(configured, "voice_silence_seconds", 1.5)
            ),
            on_state=lambda state: self.signals.voice_state.emit(state),
            on_audio=lambda audio: self.signals.voice_audio.emit(audio),
            on_error=lambda message: self.signals.voice_error.emit(message),
        )
        self.voice_agent = agent
        self.wake_button.setEnabled(False)

        def start_agent(_emit):
            try:
                return agent.start()
            except Exception:
                agent.stop()
                raise

        worker = FunctionWorker(start_agent)
        worker.signals.error.connect(self._on_voice_error)
        worker.signals.result.connect(lambda _value: self._voice_started())
        worker.signals.finished.connect(lambda: self.wake_button.setEnabled(True))
        self.thread_pool.start(worker)

    def _voice_started(self):
        self.wake_button.setText("Stop local wake")
        self.ptt_button.setEnabled(True)
        self.voice_state_label.setText("Wake listening")
        self._append_message(
            "system",
            "Local wake detection is active. Vosk listens for the wake phrase; Faster-Whisper transcribes the captured command.",
        )

    def _on_voice_state(self, state: str):
        self.voice_state_label.setText(state)
        normalized = state.casefold()
        self.ptt_button.setEnabled(
            self.voice_agent is not None
            and (
                "wake listening" in normalized
                or normalized == "voice agent stopped"
            )
        )

    def _on_voice_audio(self, audio: bytes):
        if not callable(self.voice_transcriber) or self._voice_asr_active:
            if self.voice_agent:
                self.voice_agent.resume_after_processing()
            return
        self._voice_asr_active = True
        self.ptt_button.setEnabled(False)
        self.voice_state_label.setText("Transcribing command…")
        self._append_message("system", "Command captured · running local Faster-Whisper recognition.")

        worker = FunctionWorker(
            lambda _emit: self.voice_transcriber(bytes(audio))
        )
        worker.signals.result.connect(self.signals.voice_asr_complete.emit)
        worker.signals.error.connect(self.signals.voice_asr_error.emit)
        worker.signals.finished.connect(self._voice_asr_finished)
        self.thread_pool.start(worker)

    def _voice_asr_finished(self):
        self._voice_asr_active = False

    def _resume_voice_agent(self):
        if self.voice_agent is not None:
            self.voice_agent.resume_after_processing()
            self.ptt_button.setText("Push to talk")
            self.ptt_button.setEnabled(True)
            self.voice_state_label.setText("Wake listening")

    def _on_voice_asr_complete(self, text: str):
        recognized = str(text or "").strip()
        if not recognized:
            self._on_voice_asr_error("No speech could be recognized.")
            return
        self.prompt.setPlainText(recognized)
        self.prompt.setFocus()
        settings = self.settings_store.settings if self.settings_store else None
        auto_submit = bool(settings and settings.voice_auto_submit)
        connected = bool(self.client and self.client.connected)
        if auto_submit and connected and not self._worker_active:
            self._append_message("system", "Voice command recognized · sending it to the Agent.")
            self._resume_voice_after_prompt = True
            self.send_prompt()
        else:
            self._append_message(
                "system",
                "Voice command transcribed with Faster-Whisper. Review or edit it before sending."
            )
            if auto_submit and not connected:
                self.status_message.emit(
                    "Voice command recognized but not sent: OpenCode is disconnected."
                )
            self.ptt_button.setText("Resume listening")
            self.ptt_button.setEnabled(self.voice_agent is not None)
            self.voice_state_label.setText("Command ready for review")

    def _on_voice_asr_error(self, message: str):
        self._append_message("error", f"Voice transcription failed: {message}")
        self.status_message.emit(f"Voice transcription: {message}")
        self.voice_state_label.setText("Voice command failed · wake listening")
        self._resume_voice_agent()

    def _set_voice_auto_submit(self, enabled: bool):
        if self.settings_store:
            self.settings_store.update(voice_auto_submit=bool(enabled))

    def _set_voice_silence_seconds(self, value: float):
        if self.settings_store:
            self.settings_store.update(voice_silence_seconds=float(value))
        if self.voice_agent is not None:
            self.voice_agent.set_silence_seconds(value)

    def open_prompt_library(self):
        dialog = PromptLibraryDialog(self.prompt_library, self)
        dialog.use_prompt.connect(self._insert_suggestion)
        dialog.exec()

    def _on_voice_error(self, message):
        agent, self.voice_agent = self.voice_agent, None
        if agent:
            worker = FunctionWorker(lambda _emit: agent.stop())
            worker.signals.error.connect(
                lambda cleanup_message: self.status_message.emit(
                    f"Voice input cleanup failed: {cleanup_message}"
                )
            )
            self.thread_pool.start(worker)
        self.wake_button.setText("Enable local wake")
        self.wake_button.setEnabled(True)
        self.ptt_button.setEnabled(False)
        self.voice_state_label.setText("Voice error")
        self.status_message.emit(f"Voice input: {message}")
        QMessageBox.warning(self, "Voice input failed", str(message))

    def push_to_talk(self):
        if not self.voice_agent:
            return
        try:
            if self.voice_agent.mode == "processing":
                self._resume_voice_agent()
                return
            self.voice_agent.push_to_talk()
        except Exception as exc:
            QMessageBox.warning(self, "Voice input failed", str(exc))

    def _on_voice_transcript(self, text):
        self.prompt.setPlainText(text)
        self.prompt.setFocus()
        settings = self.settings_store.settings if self.settings_store else None
        auto_submit = bool(settings and settings.voice_auto_submit)
        connected = bool(self.client and self.client.connected)
        if auto_submit and connected and not self._worker_active:
            self._append_message("system", "Recognized locally · sending the reviewed voice command.")
            self.send_prompt()
        else:
            self._append_message("system", "Voice command recognized. Review or edit it before sending.")
            if auto_submit and not connected:
                self.status_message.emit(
                    "Voice command recognized but not sent: OpenCode is disconnected."
                )

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

    def connect_opencode(self):
        if self._worker_active or (self.client and self.client.connected):
            return
        self._worker_active = True
        self._agent_instructions_injected = False
        self.connect_button.setEnabled(False)
        self.connection_state.setText("Connecting…")
        self.connection_state.setProperty("state", "connecting")
        self.connection_state.style().unpolish(self.connection_state)
        self.connection_state.style().polish(self.connection_state)
        self.activity_label.setText("Starting the OpenCode ACP process and restoring the saved session…")

        client = OpenCodeACPClient(
            executable=(self.settings_store.settings.opencode_path if self.settings_store else None),
            cwd=self.project_dir,
            on_notification=lambda message: self.signals.notification.emit(message),
        )
        self.client = client
        mcp_servers = self._mcp_server_config()

        def connect(_emit):
            capabilities = client.start(timeout=25)
            session = self._load_or_create_session(client, mcp_servers)
            return {"capabilities": capabilities, "session_id": session}

        worker = FunctionWorker(connect)
        worker.signals.result.connect(self.signals.connected.emit)
        worker.signals.error.connect(self.signals.error.emit)
        worker.signals.finished.connect(self._worker_finished)
        self.thread_pool.start(worker)

    def _load_or_create_session(self, client, mcp_servers):
        stored = {}
        try:
            stored = json.loads(self._session_file.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            pass
        if stored.get("cwd") == str(self.project_dir) and stored.get("session_id"):
            try:
                client.load_session(
                    str(stored["session_id"]), mcp_servers=mcp_servers, timeout=20
                )
                return client.session_id
            except Exception:
                pass
        return client.new_session(mcp_servers=mcp_servers, timeout=20)

    def _on_connected(self, result):
        session_id = result.get("session_id")
        try:
            self._session_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._session_file.with_suffix(".tmp")
            temporary.write_text(
                json.dumps({"cwd": str(self.project_dir), "session_id": session_id}, indent=2),
                encoding="utf-8",
            )
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            os.replace(temporary, self._session_file)
        except OSError as exc:
            self._append_message("system", f"Session persistence warning: {exc}")

        self.connection_state.setText("Connected")
        self.connection_state.setProperty("state", "connected")
        self.connection_state.style().unpolish(self.connection_state)
        self.connection_state.style().polish(self.connection_state)
        self.connect_button.setEnabled(False)
        self.disconnect_button.setEnabled(True)
        self.send_button.setEnabled(True)
        self.activity_label.setText("Connected · Transcriber workspace tools are attached to this ACP session.")
        self._append_message("system", f"OpenCode connected · session {str(session_id)[:12]}")

    def send_prompt(self):
        prompt = self.prompt.toPlainText().strip()
        if not prompt:
            return
        if not self.client or not self.client.connected:
            self._append_message("system", "Connect to OpenCode before sending a message.")
            self.status_message.emit("OpenCode is disconnected")
            return
        if self._worker_active:
            return

        self._worker_active = True
        if self.voice_agent is not None and self.voice_agent.mode == "processing":
            self._resume_voice_after_prompt = True
        self._streaming_index = None
        self.send_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.activity_label.setText("OpenCode is working…")
        self._append_message("user", prompt)
        self.prompt.clear()
        client = self.client
        outbound_prompt = prompt
        if not self._agent_instructions_injected:
            outbound_prompt = (
                self.prompt_library.bootstrap_prompt()
                + "\n\n--- USER REQUEST ---\n"
                + prompt
            )
            self._bootstrap_pending = True
            self._append_message(
                "system",
                "Loaded the editable Transcriber coordinator and specialist prompt pack for this session."
            )
        worker = FunctionWorker(
            lambda _emit: client.prompt(outbound_prompt, timeout=None)
        )
        worker.signals.result.connect(self.signals.prompt_complete.emit)
        worker.signals.error.connect(self.signals.error.emit)
        worker.signals.finished.connect(self._worker_finished)
        self.thread_pool.start(worker)

    def cancel_prompt(self):
        if not self.client or not self.client.connected:
            return
        self.stop_button.setEnabled(False)
        client = self.client
        worker = FunctionWorker(lambda _emit: client.cancel(timeout=5))
        worker.signals.error.connect(self.signals.error.emit)
        self.thread_pool.start(worker)
        self.activity_label.setText("Cancellation requested…")
        self._append_message("system", "Cancellation requested.")

    def _on_notification(self, message):
        params = message.get("params", {}) if isinstance(message, dict) else {}
        update = params.get("update", {}) if isinstance(params, dict) else {}
        if not isinstance(update, dict):
            return

        kind = update.get("sessionUpdate", "")
        if kind == "agent_message_chunk":
            content = update.get("content", {})
            if isinstance(content, dict):
                self._append_stream_chunk(content.get("text", ""))
        elif kind == "agent_thought_chunk":
            self.activity_label.setText("OpenCode is reasoning…")
        elif kind == "tool_call":
            title = update.get("title", update.get("toolCallId", "Workspace tool"))
            self._append_message("tool", f"Running · {title}")
            self.activity_label.setText(f"Running tool · {title}")
        elif kind == "tool_call_update":
            status = update.get("status", "updated")
            title = update.get("title", update.get("toolCallId", "Workspace tool"))
            self._append_message("tool", f"{title} · {status}")
            self.activity_label.setText(f"Tool {status} · {title}")
        elif kind == "current_mode_update":
            mode = update.get("currentMode", "default")
            self.activity_label.setText(f"Agent mode · {mode}")
        elif kind:
            self._append_message("system", f"Agent update · {kind.replace('_', ' ').title()}")

    def _on_prompt_complete(self, result):
        self._streaming_index = None
        if self._bootstrap_pending:
            self._agent_instructions_injected = True
            self._bootstrap_pending = False
        reason = result.get("stopReason", "completed") if isinstance(result, dict) else "completed"
        self.activity_label.setText(f"Turn {reason} · Ready for your next message.")

    def _on_error(self, message):
        self._streaming_index = None
        if self._bootstrap_pending:
            self._bootstrap_pending = False
        self._append_message("error", str(message))
        self.connection_state.setText("Connection error")
        self.connection_state.setProperty("state", "error")
        self.connection_state.style().unpolish(self.connection_state)
        self.connection_state.style().polish(self.connection_state)
        self.activity_label.setText("Something went wrong. Check that OpenCode is installed and available.")
        self.status_message.emit(f"OpenCode: {message}")
        if self.client and not self.client.connected:
            self.disconnect_button.setEnabled(False)
            self.connect_button.setEnabled(True)

    def _worker_finished(self):
        self._worker_active = False
        connected = bool(self.client and self.client.connected)
        self.send_button.setEnabled(connected)
        self.stop_button.setEnabled(False)
        self.connect_button.setEnabled(not connected)
        self.disconnect_button.setEnabled(connected)
        if connected and self.activity_label.text().startswith("OpenCode is working"):
            self.activity_label.setText("Ready · Ask another question or choose a suggested task.")
        if self._resume_voice_after_prompt:
            self._resume_voice_after_prompt = False
            self._resume_voice_agent()

    def disconnect_opencode(self):
        client, self.client = self.client, None
        if client:
            worker = FunctionWorker(lambda _emit: client.close())
            worker.signals.error.connect(self.signals.error.emit)
            self.thread_pool.start(worker)
        self.connection_state.setText("Disconnected")
        self.connection_state.setProperty("state", "disconnected")
        self.connection_state.style().unpolish(self.connection_state)
        self.connection_state.style().polish(self.connection_state)
        self.connect_button.setEnabled(True)
        self.disconnect_button.setEnabled(False)
        self.send_button.setEnabled(False)
        self.activity_label.setText("Disconnected · Connect OpenCode to continue the conversation.")
        self._append_message("system", "OpenCode disconnected.")

    def shutdown(self):
        if self.voice_agent:
            agent, self.voice_agent = self.voice_agent, None
            worker = FunctionWorker(lambda _emit: agent.stop())
            self.thread_pool.start(worker)
        if self.client:
            self.client.close()
            self.client = None
