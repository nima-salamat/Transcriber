"""OpenCode ACP assistant panel with persistent session and local MCP tools."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QPlainTextEdit, QVBoxLayout, QWidget,
)

from transcriber.opencode.acp_client import OpenCodeACPClient
from transcriber.ui.workers import FunctionWorker


class _AssistantSignals(QObject):
    notification = Signal(object)
    connected = Signal(object)
    error = Signal(str)
    prompt_complete = Signal(object)
    voice_state = Signal(str)
    voice_transcript = Signal(str)


class AssistantPanel(QWidget):
    status_message = Signal(str)

    def __init__(self, paths, thread_pool, settings_store=None, parent=None):
        super().__init__(parent)
        self.paths = paths
        self.thread_pool = thread_pool
        self.settings_store = settings_store
        self.voice_agent = None
        self.signals = _AssistantSignals(self)
        self.signals.notification.connect(self._on_notification)
        self.signals.connected.connect(self._on_connected)
        self.signals.error.connect(self._on_error)
        self.signals.prompt_complete.connect(self._on_prompt_complete)
        self.signals.voice_state.connect(lambda state: self.voice_state_label.setText(state))
        self.signals.voice_transcript.connect(self._on_voice_transcript)
        self.client: OpenCodeACPClient | None = None
        self._worker_active = False
        self.project_dir = Path.cwd()
        self._session_file = self.paths.config / "opencode-session.json"
        if self.settings_store:
            saved_project = self.settings_store.settings.opencode_project_directory
            if saved_project and Path(saved_project).is_dir():
                self.project_dir = Path(saved_project).resolve()

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        header = QHBoxLayout()
        header.addWidget(QLabel("OpenCode Assistant"))
        header.addStretch(1)
        self.connection_state = QLabel("Disconnected")
        self.connection_state.setObjectName("Muted")
        header.addWidget(self.connection_state)
        self.voice_state_label = QLabel("Voice off")
        self.voice_state_label.setObjectName("Muted")
        header.addWidget(self.voice_state_label)
        root.addLayout(header)

        project_row = QHBoxLayout()
        self.project_label = QLabel(str(self.project_dir))
        self.project_label.setObjectName("Muted")
        self.project_label.setWordWrap(True)
        self.project_button = QPushButton("Project…")
        self.project_button.clicked.connect(self.choose_project)
        project_row.addWidget(self.project_label, 1)
        project_row.addWidget(self.project_button)
        root.addLayout(project_row)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Connect to OpenCode to start a persistent agent session.")
        root.addWidget(self.log, 1)

        connection_row = QHBoxLayout()
        self.connect_button = QPushButton("Connect OpenCode")
        self.connect_button.clicked.connect(self.connect_opencode)
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.clicked.connect(self.disconnect_opencode)
        self.disconnect_button.setEnabled(False)
        connection_row.addWidget(self.connect_button)
        connection_row.addWidget(self.disconnect_button)
        root.addLayout(connection_row)

        self.prompt = QPlainTextEdit()
        self.prompt.setMaximumBlockCount(500)
        self.prompt.setPlaceholderText("Ask OpenCode to work with the current transcript…")
        self.prompt.setMaximumHeight(110)
        root.addWidget(self.prompt)

        action_row = QHBoxLayout()
        self.send_button = QPushButton("Send prompt")
        self.send_button.setObjectName("Primary")
        self.send_button.clicked.connect(self.send_prompt)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.cancel_prompt)
        self.stop_button.setEnabled(False)
        action_row.addWidget(self.send_button, 1)
        action_row.addWidget(self.stop_button)
        root.addLayout(action_row)

        voice_row = QHBoxLayout()
        saved_phrase = self.settings_store.settings.wake_phrase if self.settings_store else "transcriber"
        self.wake_phrase = QLineEdit(saved_phrase)
        self.wake_phrase.setPlaceholderText("Wake phrase (local Vosk)")
        self.wake_model_label = QLabel("No Vosk model selected")
        self.wake_model_label.setObjectName("Muted")
        self.wake_model_button = QPushButton("Vosk model…")
        self.wake_model_button.clicked.connect(self.choose_wake_model)
        self.wake_button = QPushButton("Enable local wake")
        self.wake_button.clicked.connect(self.toggle_voice_agent)
        self.ptt_button = QPushButton("Push to talk")
        self.ptt_button.clicked.connect(self.push_to_talk)
        self.ptt_button.setEnabled(False)
        voice_row.addWidget(self.wake_phrase, 1)
        voice_row.addWidget(self.wake_model_label, 1)
        voice_row.addWidget(self.wake_model_button)
        voice_row.addWidget(self.wake_button)
        voice_row.addWidget(self.ptt_button)
        root.addLayout(voice_row)

        foot = QLabel("ACP session · Local MCP tools · Voice is processed locally by optional Vosk; no raw audio is stored or uploaded")
        foot.setObjectName("Muted")
        foot.setWordWrap(True)
        root.addWidget(foot)

    def sync_settings(self):
        if not self.settings_store:
            return
        settings = self.settings_store.settings
        self.wake_phrase.setText(settings.wake_phrase)
        self.wake_model_label.setText(Path(settings.wake_model_directory).name if settings.wake_model_directory else "No Vosk model selected")
        self.wake_model_label.setToolTip(settings.wake_model_directory or "")
        if not (self.client and self.client.connected) and settings.opencode_project_directory:
            candidate = Path(settings.opencode_project_directory).expanduser()
            if candidate.is_dir():
                self.project_dir = candidate.resolve()
                self.project_label.setText(str(self.project_dir))

    def choose_wake_model(self):
        from PySide6.QtWidgets import QFileDialog
        saved = self.settings_store.settings.wake_model_directory if self.settings_store else ""
        path = QFileDialog.getExistingDirectory(self, "Choose local Vosk model directory", saved or str(self.paths.models))
        if not path:
            return
        model_path = Path(path).resolve()
        if not (model_path / "am").is_dir() and not (model_path / "conf").is_dir():
            QMessageBox.warning(self, "Invalid Vosk model", "The selected directory does not look like a Vosk model folder (expected am/ or conf/).")
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
            self._append("Local voice agent stopped; microphone released.")
            return
        model_path = self.settings_store.settings.wake_model_directory if self.settings_store else None
        phrase = self.wake_phrase.text().strip()
        if self.settings_store:
            self.settings_store.update(wake_phrase=phrase)
        if not model_path or not Path(model_path).is_dir():
            QMessageBox.information(self, "Vosk model required", "Choose a locally installed Vosk model before enabling wake detection.")
            return
        try:
            from transcriber.assistant.speech_input import VoskVoiceAgent
        except ImportError as exc:
            QMessageBox.warning(self, "Voice support unavailable", str(exc))
            return
        agent = VoskVoiceAgent(
            model_path, phrase,
            on_state=lambda state: self.signals.voice_state.emit(state),
            on_transcript=lambda text: self.signals.voice_transcript.emit(text),
            on_error=lambda message: self.signals.error.emit(message),
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
        self._append("Local wake detector active. It processes microphone frames in memory only.")

    def _on_voice_error(self, message):
        agent, self.voice_agent = self.voice_agent, None
        if agent:
            # A failed start is already stopped in its worker; a stop failure
            # is reported here without changing ACP's connection state.
            self._append(f"Voice input cleanup: {message}")
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
            self.voice_agent.push_to_talk()
        except Exception as exc:
            QMessageBox.warning(self, "Voice input failed", str(exc))

    def _on_voice_transcript(self, text):
        self.prompt.setPlainText(text)
        self.prompt.setFocus()
        self._append("Recognized locally; review and edit the command before sending it to OpenCode.")

    def choose_project(self):
        path = QFileDialog.getExistingDirectory(self, "Choose OpenCode project", str(self.project_dir))
        if not path:
            return
        new_path = Path(path).resolve()
        if not new_path.is_dir():
            return
        if self.client and self.client.connected:
            QMessageBox.information(
                self, "Disconnect first",
                "The active ACP process is bound to its original working directory. Disconnect first, then change the project and reconnect.",
            )
            return
        self.project_dir = new_path
        self.project_label.setText(str(new_path))
        if self.settings_store:
            self.settings_store.update(opencode_project_directory=str(new_path))

    def _mcp_server_config(self):
        if getattr(sys, "frozen", False):
            command, args = sys.executable, ["--mcp-server"]
        else:
            command, args = sys.executable, ["-m", "transcriber.mcp_server"]
        environment = dict(os.environ)
        return [{
            "type": "stdio", "name": "transcriber", "command": command,
            "args": args, "env": environment,
        }]

    def connect_opencode(self):
        if self._worker_active or (self.client and self.client.connected):
            return
        self._worker_active = True
        self.connect_button.setEnabled(False)
        self.connection_state.setText("Starting ACP…")
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
                client.load_session(str(stored["session_id"]), mcp_servers=mcp_servers, timeout=20)
                return client.session_id
            except Exception:
                pass
        return client.new_session(mcp_servers=mcp_servers, timeout=20)

    def _on_connected(self, result):
        session_id = result.get("session_id")
        try:
            self._session_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._session_file.with_suffix(".tmp")
            temporary.write_text(json.dumps({"cwd": str(self.project_dir), "session_id": session_id}, indent=2), encoding="utf-8")
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            os.replace(temporary, self._session_file)
        except OSError as exc:
            self._append(f"Session persistence warning: {exc}")
        self.connection_state.setText(f"Connected · {str(session_id)[:12]}")
        self.disconnect_button.setEnabled(True)
        self.connect_button.setEnabled(False)
        self._append(f"OpenCode ACP connected. Session: {session_id}")
        self._append("Transcriber MCP tools attached to this ACP session.")

    def send_prompt(self):
        prompt = self.prompt.toPlainText().strip()
        if not prompt:
            return
        if not self.client or not self.client.connected:
            QMessageBox.information(self, "OpenCode is disconnected", "Connect to OpenCode before sending a prompt.")
            return
        if self._worker_active:
            return
        self._worker_active = True
        self.send_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self._append(f"You: {prompt}")
        self.prompt.clear()
        client = self.client
        worker = FunctionWorker(lambda _emit: client.prompt(prompt, timeout=None))
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
        self._append("Cancellation requested…")

    def _on_notification(self, message):
        params = message.get("params", {}) if isinstance(message, dict) else {}
        update = params.get("update", {}) if isinstance(params, dict) else {}
        if isinstance(update, dict):
            kind = update.get("sessionUpdate", "")
            if kind in {"agent_message_chunk", "agent_thought_chunk"}:
                content = update.get("content", {})
                if isinstance(content, dict) and content.get("text"):
                    self._append("OpenCode: " + str(content["text"]))
            elif kind == "tool_call":
                self._append("Tool: " + str(update.get("title", update.get("toolCallId", "running"))))
            elif kind == "tool_call_update":
                self._append("Tool status: " + str(update.get("status", "updated")))
            elif kind:
                self._append(f"Agent update: {kind}")

    def _on_prompt_complete(self, result):
        self._append(f"OpenCode turn finished · {result.get('stopReason', 'completed')}")

    def _on_error(self, message):
        self._append(f"Error: {message}")
        self.connection_state.setText("Error / disconnected")
        self.status_message.emit(f"OpenCode: {message}")
        if self.client and not self.client.connected:
            self.disconnect_button.setEnabled(False)
            self.connect_button.setEnabled(True)

    def _worker_finished(self):
        self._worker_active = False
        self.send_button.setEnabled(bool(self.client and self.client.connected))
        self.stop_button.setEnabled(False)
        if self.client and self.client.connected:
            self.connect_button.setEnabled(False)
            self.disconnect_button.setEnabled(True)
        else:
            self.connect_button.setEnabled(True)
            self.disconnect_button.setEnabled(False)

    def _append(self, text):
        self.log.appendPlainText(str(text))

    def disconnect_opencode(self):
        client, self.client = self.client, None
        if client:
            worker = FunctionWorker(lambda _emit: client.close())
            worker.signals.error.connect(self.signals.error.emit)
            self.thread_pool.start(worker)
        self.connection_state.setText("Disconnected")
        self.connect_button.setEnabled(True)
        self.disconnect_button.setEnabled(False)
        self._append("OpenCode disconnected.")

    def shutdown(self):
        if self.voice_agent:
            self.voice_agent.stop()
            self.voice_agent = None
        if self.client:
            self.client.close()
            self.client = None
