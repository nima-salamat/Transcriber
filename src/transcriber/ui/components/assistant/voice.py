"""Local voice, wake-word and push-to-talk lifecycle methods for the AI Assistant."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox

from transcriber.ui.components.prompt_library_dialog import PromptLibraryDialog
from transcriber.ui.workers import FunctionWorker


class AssistantVoiceMixin:
    def start_voice_chat(self):
        if getattr(self, "_shutting_down", False):
            return
        # The orb can cancel the pending voice start while the provider connects.
        if self._start_voice_after_connect and self.voice_agent is None:
            self._start_voice_after_connect = False
            self._voice_conversation_mode = False
            self._set_voice_activity(
                "Voice chat start cancelled · provider connection may continue",
                stage="cancelled",
                log_message="Voice chat startup was cancelled before microphone activation.",
            )
            return
        if self.voice_agent is not None:
            self._voice_conversation_mode = False
            self.toggle_voice_agent()
            return
        if self._worker_active:
            self.status_message.emit("Wait for the current model operation to finish before starting voice chat.")
            return
        self._voice_conversation_mode = True
        self._set_voice_activity(
            "Connecting to the selected chat model…",
            stage="connecting",
            log_message="Voice chat started · connecting to the selected chat model.",
        )
        if not self._chat_is_connected():
            self._start_voice_after_connect = True
            self.connect_provider()
            return
        self.toggle_voice_agent()

    def refresh_voice_asr_models(self, selected_model: str | None = None):
        if not hasattr(self, "voice_asr_combo"):
            return
        combo = self.voice_asr_combo
        selected = selected_model or (combo.currentData() if combo.count() else "")
        if not selected and self.settings_store:
            selected = self.settings_store.settings.default_model
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Use default Faster-Whisper model", "")
        installed = []
        if self.model_manager is not None:
            try:
                installed = self.model_manager.installed(include_sizes=False)
            except Exception:
                installed = []
        for item in installed:
            if not item.get("compatible") or str(item.get("runtime") or "faster-whisper") != "faster-whisper":
                continue
            repo_id = str(item.get("repo_id") or "")
            if repo_id:
                combo.addItem(repo_id, repo_id)
        index = combo.findData(selected or "")
        combo.setCurrentIndex(max(0, index))
        combo.blockSignals(False)

    def _voice_asr_model_changed(self, _index: int):
        if self.settings_store:
            self.settings_store.update(voice_asr_model=str(self.voice_asr_combo.currentData() or ""))

    def _provider_base_url_changed(self):
        new_url = str(self.ollama_url.text() or "").strip().rstrip("/")
        old_url = (
            self.ollama_client.base_url
            if self.ollama_client is not None else
            self.settings_store.settings.ollama_base_url if self.settings_store else ""
        )
        if self.settings_store:
            normalized = self.settings_store.update(ollama_base_url=new_url)
            new_url = normalized.ollama_base_url
            self.ollama_url.setText(new_url)
        if old_url and new_url == str(old_url).rstrip("/"):
            return

        # Never send a request through a client still bound to the old URL.
        self._ollama_connected = False
        self.ollama_client = None
        self._ollama_model = ""
        self.composer.set_provider_ready(False)
        self.composer.set_connection_state(
            connected=False, connecting=False, provider="ollama"
        )
        self.composer.set_status(
            "Ollama address changed · checking available models at the new server."
        )
        self._session_requested_ollama_model = ""
        self._auto_connect_pending = True
        self.refresh_provider_models()

    @staticmethod
    def _wake_model_path_key(value: str | None) -> str:
        if not value:
            return ""
        try:
            return str(Path(value).expanduser().resolve()).casefold()
        except OSError:
            return str(value).casefold()

    def refresh_wake_models(self, selected_path: str | None = None):
        """Refresh the selector using installed and validated Vosk models."""
        if not hasattr(self, "wake_model_combo"):
            return
        combo = self.wake_model_combo
        if selected_path is None:
            selected_path = combo.currentData()
            if not selected_path and self.settings_store:
                selected_path = self.settings_store.settings.wake_model_directory
        selected_key = self._wake_model_path_key(selected_path)
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Select a Vosk wake-word model…", "")

        models = []
        if self.model_manager is not None:
            try:
                models = self.model_manager.installed_vosk_models(include_sizes=False)
            except Exception as exc:
                self.wake_model_help.setText(f"Could not list installed Vosk models: {exc}")

        for model in models:
            repo_id = str(model.get("repo_id") or "")
            model_name = str(model.get("model_name") or repo_id or "Vosk model")
            language = str(model.get("language_name") or model.get("language") or "").strip()
            label = f"{model_name} · {language}" if language else model_name
            path = str(model.get("path") or "")
            if path:
                combo.addItem(label, path)

        selected_index = -1
        for index in range(1, combo.count()):
            if self._wake_model_path_key(combo.itemData(index)) == selected_key and selected_key:
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
                "No compatible Vosk model is installed. Install one in AI models → Vosk, "
                "or choose an existing local model folder."
            )
        else:
            self.wake_model_help.setText(
                "Choose the language/model that recognizes your activation phrase. "
                "The selected local Faster-Whisper model transcribes your command."
            )

    def choose_wake_model(self):
        saved = str(self.wake_model_combo.currentData() or "")
        path = QFileDialog.getExistingDirectory(
            self, "Choose local Vosk model directory", saved or str(self.paths.models)
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
                self, "Invalid Vosk model",
                "Choose a Vosk model folder containing its am/ or conf/ directory.",
            )
            return
        resolved = str(model_path.resolve())
        if self.settings_store:
            self.settings_store.update(wake_model_directory=resolved)
        self.refresh_wake_models(resolved)

    def toggle_voice_agent(self):
        if getattr(self, "_shutting_down", False):
            return
        if self.voice_agent is not None:
            agent, self.voice_agent = self.voice_agent, None
            worker = FunctionWorker(lambda _emit: agent.stop())
            worker.signals.error.connect(self._on_voice_error)
            self.thread_pool.start(worker)
            self.wake_button.setText("Enable local wake")
            self._sync_voice_orb()
            self.voice_chat_button.setEnabled(True)
            self._voice_conversation_mode = False
            self.ptt_button.setEnabled(False)
            self._set_voice_activity("Voice chat stopped", stage="stopped")
            self._append_message("system", "Local voice input stopped; microphone released.")
            return

        model_path = str(self.wake_model_combo.currentData() or "").strip() or None
        phrase = self.wake_phrase.text().strip()
        if not phrase:
            self._voice_conversation_mode = False
            self._sync_voice_orb()
            QMessageBox.information(
                self, "Activation phrase required",
                "Enter the keyword or phrase that Vosk should listen for.",
            )
            return
        if self.settings_store:
            self.settings_store.update(
                wake_phrase=phrase,
                wake_model_directory=model_path,
            )
        if not model_path or not Path(model_path).is_dir():
            self._voice_conversation_mode = False
            self._sync_voice_orb()
            QMessageBox.information(
                self, "Vosk model required",
                "Choose a locally installed Vosk model before enabling wake detection.",
            )
            return
        try:
            from transcriber.assistant.speech_input import VoskVoiceAgent
        except ImportError as exc:
            self._voice_conversation_mode = False
            self._sync_voice_orb()
            self.voice_chat_button.setEnabled(True)
            QMessageBox.warning(self, "Voice support unavailable", str(exc))
            return

        if not callable(self.voice_transcriber):
            self._voice_conversation_mode = False
            self._sync_voice_orb()
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
        self._sync_voice_orb()
        self.voice_chat_button.setEnabled(False)

        def start_agent(_emit):
            try:
                if getattr(self, "_shutting_down", False) or agent.shutdown_requested:
                    agent.close()
                    return False
                if callable(self.voice_model_loader):
                    self.voice_model_loader()
                if getattr(self, "_shutting_down", False) or agent.shutdown_requested:
                    agent.close()
                    return False
                return agent.start()
            except Exception:
                if getattr(self, "_shutting_down", False):
                    agent.close()
                else:
                    agent.stop()
                raise

        worker = FunctionWorker(start_agent)
        worker.signals.error.connect(self._on_voice_error)
        worker.signals.result.connect(lambda _value: self._voice_started())
        worker.signals.finished.connect(
            lambda: self.wake_button.setEnabled(not getattr(self, "_shutting_down", False))
        )
        self.thread_pool.start(worker)

    def _voice_started(self):
        if getattr(self, "_shutting_down", False) or self.voice_agent is None:
            return
        self.wake_button.setText("Stop local wake")
        self._sync_voice_orb()
        self.voice_chat_button.setEnabled(True)
        self.ptt_button.setEnabled(True)
        self._set_voice_activity(
            "Waiting for the wake word…",
            stage="waiting",
            log_message="Voice chat is ready. Waiting for the wake word.",
        )
        self._append_message(
            "system",
            "Vosk is listening locally for the activation phrase. Faster-Whisper will transcribe your command.",
        )

    def _sync_voice_orb(self):
        """Keep the large voice control and its accessible label in sync with the loop."""
        button = getattr(self, "voice_chat_button", None)
        if button is None:
            return
        active = bool(
            self.voice_agent is not None
            or self._start_voice_after_connect
            or self._voice_conversation_mode
        )
        button.setText("Stop voice" if active else "Start voice")
        button.setIcon(self.ui_icons.icon("stop" if active else "mic", size=17))
        button.setAccessibleName(
            "Stop voice conversation" if active else "Start voice conversation"
        )
        button.setProperty("active", active)
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def _set_voice_activity(
        self, message: str, *, stage: str | None = None, log_message: str | None = None
    ):
        """Update the always-visible voice status and optionally add a chat timeline event."""
        if getattr(self, "_shutting_down", False):
            return
        display = str(message or "Voice chat is active")
        self.voice_live_status.setText(display)
        self.voice_state_label.setText(display)
        stage_labels = {
            "connecting": "Connecting",
            "waiting": "Listening",
            "wake-detected": "Listening",
            "listening": "Listening",
            "transcribing": "Transcribing",
            "receiving": "Generating",
            "response": "Thinking",
            "resuming": "Listening",
            "stopped": "Stopped",
            "cancelled": "Stopped",
            "error": "Error",
            "asr-error": "Error",
        }
        self._set_inline_agent_status(
            stage_labels.get(str(stage or ""), display) if stage else display
        )
        self._sync_voice_orb()
        if stage is not None and stage != self._last_voice_stage:
            self._last_voice_stage = stage
            if log_message:
                self._append_message("system", log_message)

    def _on_voice_state(self, state: str):
        raw_state = str(state or "").strip()
        normalized = raw_state.casefold()
        if "wake phrase detected" in normalized or "wake word detected" in normalized:
            self._set_voice_activity(
                "Wake word detected · listening for your command…",
                stage="wake-detected",
                log_message="Wake word detected. Listening for your command.",
            )
        elif "listening for your command" in normalized or "push-to-talk" in normalized:
            self._set_voice_activity(
                "Listening for your command…",
                stage="listening",
                log_message="Microphone is listening. Speak now.",
            )
        elif "silence detected" in normalized or "transcribing" in normalized:
            self._set_voice_activity(
                "Command captured · transcribing with Faster-Whisper…",
                stage="transcribing",
                log_message="Command captured. Converting speech to text with Faster-Whisper.",
            )
        elif "no speech detected" in normalized:
            self._set_voice_activity(
                "No speech detected · waiting for the wake word…",
                stage="waiting",
                log_message="No speech detected. Waiting for the wake word.",
            )
        elif "wake listening" in normalized:
            self._set_voice_activity(
                "Waiting for the wake word…",
                stage="waiting",
                log_message="Waiting for the wake word.",
            )
        elif "voice agent stopped" in normalized:
            self._set_voice_activity("Voice chat stopped", stage="stopped")
        elif "error" in normalized or "failed" in normalized:
            self._set_voice_activity(raw_state, stage="error", log_message=raw_state)
        else:
            self._set_voice_activity(raw_state or "Voice chat is active")

        self.ptt_button.setEnabled(
            self.voice_agent is not None
            and ("wake listening" in normalized or normalized == "voice agent stopped")
        )

    def _on_voice_audio(self, audio: bytes):
        if not callable(self.voice_transcriber) or self._voice_asr_active:
            if self.voice_agent:
                self.voice_agent.resume_after_processing()
            return
        self._voice_asr_active = True
        self.ptt_button.setEnabled(False)
        self._set_voice_activity(
            "Transcribing your command with Faster-Whisper…", stage="transcribing"
        )

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
            self._set_voice_activity(
                "Resuming wake-word detection…",
                stage="resuming",
                log_message="Response handling finished. Resuming wake-word detection.",
            )
            self.ptt_button.setText("Push to talk")
            self.ptt_button.setEnabled(False)
            self.voice_agent.resume_after_processing()

    def _on_voice_asr_complete(self, text: str):
        recognized = str(text or "").strip()
        if not recognized:
            self._on_voice_asr_error("No speech could be recognized.")
            return
        self.prompt.setPlainText(recognized)
        self.prompt.setFocus()
        settings = self.settings_store.settings if self.settings_store else None
        auto_submit = bool((settings and settings.voice_auto_submit) or self._voice_conversation_mode)
        connected = self._chat_is_connected()
        if auto_submit and connected and not self._worker_active:
            provider_name = "Ollama" if self._chat_provider == "ollama" else "OpenCode Agent"
            self._set_voice_activity(
                f"Sending your command to {provider_name}…",
                stage="sending",
                log_message=f"Speech recognized. Sending your command to {provider_name}.",
            )
            self._resume_voice_after_prompt = True
            self.send_prompt()
        else:
            self._set_voice_activity(
                "Speech recognized · review the transcript before sending",
                stage="review",
                log_message="Speech recognized with Faster-Whisper. The transcript is ready in the message box for review.",
            )
            if auto_submit and not connected:
                self.status_message.emit(
                    "Voice command recognized but not sent: the selected chat provider is disconnected."
                )
            self.ptt_button.setText("Resume listening")
            self.ptt_button.setEnabled(self.voice_agent is not None)
            self.voice_state_label.setText("Command ready for review")
            if self._voice_conversation_mode:
                self._voice_conversation_mode = False
                self._sync_voice_orb()

    def _on_voice_asr_error(self, message: str):
        self.composer.set_status(f"Voice transcription failed: {message}", error=True)
        self.status_message.emit(f"Voice transcription: {message}")
        self._set_voice_activity(
            "Speech recognition failed · resuming wake-word detection…",
            stage="asr-error",
            log_message=f"Speech recognition failed: {message}",
        )
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
        self._sync_voice_orb()
        self.voice_chat_button.setEnabled(True)
        self._voice_conversation_mode = False
        self._start_voice_after_connect = False
        self.ptt_button.setEnabled(False)
        self._set_voice_activity(
            f"Voice input error · {message}", stage="error", log_message=f"Voice input error: {message}"
        )
        self.status_message.emit(f"Voice input: {message}")
        self.composer.set_status(f"Voice input failed: {message}", error=True)

    def push_to_talk(self):
        if not self.voice_agent:
            return
        try:
            if self.voice_agent.mode == "processing":
                self._resume_voice_agent()
                return
            self.voice_agent.push_to_talk()
        except Exception as exc:
            self.composer.set_status(f"Voice input failed: {exc}", error=True)

    def _on_voice_transcript(self, text):
        self.prompt.setPlainText(text)
        self.prompt.setFocus()
        settings = self.settings_store.settings if self.settings_store else None
        auto_submit = bool((settings and settings.voice_auto_submit) or self._voice_conversation_mode)
        connected = self._chat_is_connected()
        if auto_submit and connected and not self._worker_active:
            self._append_message("system", "Recognized locally · sending the voice command to the selected model.")
            self.send_prompt()
        else:
            self._append_message("system", "Voice command recognized. Review or edit it before sending.")
            if auto_submit and not connected:
                self.status_message.emit(
                    "Voice command recognized but not sent: the selected chat provider is disconnected."
                )

