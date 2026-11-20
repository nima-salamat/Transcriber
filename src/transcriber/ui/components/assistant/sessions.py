"""Local conversation lifecycle methods for the AI Assistant panel."""
from __future__ import annotations

from PySide6.QtCore import Qt

from transcriber.ui.workers import FunctionWorker


class AssistantSessionMixin:
    def _session_title(self) -> str:
        session = self.session_store.get_session(getattr(self, "_active_session_id", "")) or {}
        custom_title = str((session.get("metadata") or {}).get("custom_title") or "").strip()
        if custom_title:
            return custom_title[:120]
        for message in self._messages:
            if message.get("role") == "user":
                value = " ".join(str(message.get("text") or "").split())
                if value:
                    return value[:44] + ("…" if len(value) > 44 else "")
        return "New chat"

    def _schedule_session_persist(self):
        if hasattr(self, "_session_persist_timer"):
            self._session_persist_timer.start()

    def _persist_current_session(self, *, refresh_sidebar: bool = False):
        session_id = getattr(self, "_active_session_id", "")
        if not session_id:
            return
        try:
            saved_session = self.session_store.save_state(
                session_id,
                messages=self._messages,
                provider_messages=self._ollama_messages,
                title=self._session_title(),
            )
        except (OSError, KeyError, ValueError) as exc:
            if hasattr(self, "activity_label"):
                self.activity_label.setText(f"Could not save this chat locally: {exc}")
            return
        if hasattr(self, "sidebar"):
            self.sidebar.update_session_title(
                session_id,
                self._session_title(),
                messages=self._messages,
                updated_at=saved_session.get("updated_at"),
            )
        if refresh_sidebar and hasattr(self, "session_list"):
            self._refresh_session_list()

    def _update_conversation_header(self):
        if not hasattr(self, "conversation_header"):
            return
        active = self.session_store.get_session(self._active_session_id) or {}
        title = self._session_title()
        provider = active.get("provider") or self._chat_provider
        provider_label = "Ollama" if provider == "ollama" else "OpenCode"
        model = (
            self._ollama_model if provider == "ollama"
            else self._opencode_model or "provider default"
        )
        connected = self._chat_is_connected()
        state = "Connected" if connected else "Connecting" if self._worker_active else "Disconnected"
        subtitle = f"{provider_label} · {model} · {state}"
        workspace = str(self.project_dir) if provider == "opencode" else str(self.ollama_url.text())
        self.session_title_label.setText(title)
        self.session_subtitle_label.setText(subtitle)
        self.conversation_header.set_conversation(title, subtitle, workspace)
        self.sidebar.set_provider_summary(f"{provider_label} · {model}")

    def _refresh_session_list(self):
        if not hasattr(self, "sidebar"):
            return
        active_id = self._active_session_id
        self.sidebar.refresh_sessions(active_id=active_id)
        self._update_conversation_header()

    def _rename_session(self, session_id: str, title: str):
        clean_title = " ".join(str(title or "").split())[:120]
        if not clean_title:
            return
        try:
            self.session_store.update_metadata(session_id, custom_title=clean_title)
            self.session_store.save_state(session_id, title=clean_title)
        except (OSError, KeyError, ValueError) as exc:
            self.activity_label.setText(f"Could not rename conversation: {exc}")
            return
        self._refresh_session_list()

    def _delete_session(self, session_id: str):
        if self._worker_active:
            return
        was_active = session_id == self._active_session_id
        try:
            next_active_id = self.session_store.delete_session(session_id)
        except (OSError, KeyError, ValueError) as exc:
            self.activity_label.setText(f"Could not delete conversation: {exc}")
            return
        if was_active:
            next_session = self.session_store.get_session(next_active_id) if next_active_id else None
            if next_session is None:
                next_session = self.session_store.create_session(self._chat_provider)
            self._load_session_state(next_session)
            if self._chat_provider == "opencode":
                self._restore_active_opencode_session()
            else:
                self._auto_connect_provider()
        self._refresh_session_list()

    def _restore_active_opencode_session(self):
        if self._chat_provider != "opencode" or not self.client or not self.client.connected:
            return
        if self._worker_active:
            return
        self._worker_active = True
        self.composer.set_busy(True, stoppable=False)
        self.send_button.setEnabled(False)
        self.connect_button.setEnabled(False)
        client = self.client
        stored_id = self._active_opencode_session_id
        mcp_servers = self._mcp_server_config()
        self._switching_to_session_id = self._active_session_id

        def restore(_emit):
            if stored_id:
                client.load_session(stored_id, mcp_servers=mcp_servers, timeout=20)
                return stored_id
            return client.new_session(mcp_servers=mcp_servers, timeout=20)

        worker = FunctionWorker(restore)
        worker.signals.result.connect(self.signals.session_loaded.emit)
        worker.signals.error.connect(self.signals.session_load_error.emit)
        worker.signals.finished.connect(self._worker_finished)
        self.thread_pool.start(worker)

    def _load_session_state(self, session: dict):
        self._active_session_id = session["id"]
        self.session_store.set_active(self._active_session_id)
        self._chat_provider = session["provider"]
        self.provider_combo.blockSignals(True)
        self.provider_combo.setCurrentIndex(
            max(0, self.provider_combo.findData(self._chat_provider))
        )
        self.provider_combo.blockSignals(False)
        self._messages = list(session.get("messages") or [])
        self._ollama_messages = list(session.get("provider_messages") or [])
        metadata = session.get("metadata") or {}
        self._active_opencode_session_id = str(metadata.get("opencode_session_id") or "")
        self._session_requested_ollama_model = str(metadata.get("ollama_model") or "")
        self._streaming_index = None
        self._apply_provider_ui()
        self.sidebar.set_active_session(self._active_session_id)
        self._refresh_chat(scroll_to_bottom=True)
        self._update_conversation_header()

    def _on_session_item_clicked(self, item):
        session_id = str(item if isinstance(item, str) else item.data(Qt.ItemDataRole.UserRole) or "")
        if not session_id or session_id == self._active_session_id:
            return
        if getattr(self, "_agent_turn_active", False):
            # Keep the old session selected until its model worker has stopped and
            # its final partial response/tool history has been saved.
            self._pending_session_switch = {"session_id": session_id}
            if not getattr(self, "_stop_requested", False):
                self.cancel_prompt()
            self.activity_label.setText("Stopping before switching chat…")
            return
        if self._worker_active:
            self.activity_label.setText("Please wait for the current setup operation to finish.")
            return
        self._persist_current_session(refresh_sidebar=False)
        session = self.session_store.get_session(session_id)
        if session is None:
            self._refresh_session_list()
            return
        self._load_session_state(session)
        if self._chat_provider == "opencode":
            if self.client and self.client.connected:
                self._restore_active_opencode_session()
            else:
                self._auto_connect_provider()
        else:
            requested_model = self._session_requested_ollama_model
            model_index = self.model_combo.findData(self._ollama_model)
            if (
                self._ollama_connected
                and self._ollama_model
                and (not requested_model or requested_model == self._ollama_model)
                and model_index >= 0
            ):
                self.model_combo.blockSignals(True)
                self.model_combo.setCurrentIndex(model_index)
                self.model_combo.blockSignals(False)
                self.composer.set_provider_ready(True)
                self.activity_label.setText(f"Ready · {self._ollama_model}")
            else:
                self._auto_connect_provider()

    def _on_session_loaded(self, session_id: str):
        if getattr(self, "_switching_to_session_id", "") != self._active_session_id:
            return
        self._active_opencode_session_id = session_id
        self.session_store.update_metadata(
            self._active_session_id, opencode_session_id=session_id
        )
        self._switching_to_session_id = ""
        self._load_opencode_model_options()
        self.activity_label.setText("Conversation restored · ready to continue.")
        self._update_conversation_header()

    def _on_session_load_error(self, message: str):
        self._switching_to_session_id = ""
        self._append_message("error", "Could not restore the OpenCode session: " + str(message))
    def new_chat(self):
        """Create a separate, locally persisted conversation without discarding older chats."""
        if getattr(self, "_agent_turn_active", False):
            # New chat is queued rather than disabled or allowed to mutate the
            # current transcript while an Agent response is still streaming.
            self._pending_session_switch = {"new_chat": True}
            if not getattr(self, "_stop_requested", False):
                self.cancel_prompt()
            self.activity_label.setText("Stopping before creating a new chat…")
            return
        if self._worker_active:
            self.activity_label.setText("Please wait for the current setup operation to finish.")
            return
        self._persist_current_session()
        session = self.session_store.create_session(self._chat_provider)
        self._load_session_state(session)
        self._refresh_session_list()
        self.activity_label.setText("New conversation · ready for your message.")
        if self._chat_provider == "opencode" and self.client and self.client.connected:
            self._worker_active = True
            self.composer.set_busy(True, stoppable=False)
            self.send_button.setEnabled(False)
            self.connect_button.setEnabled(False)
            client = self.client
            mcp_servers = self._mcp_server_config()
            worker = FunctionWorker(
                lambda _emit: client.new_session(mcp_servers=mcp_servers, timeout=20)
            )
            worker.signals.result.connect(self.signals.new_session_ready.emit)
            worker.signals.error.connect(self.signals.new_session_error.emit)
            worker.signals.finished.connect(self._worker_finished)
            self.thread_pool.start(worker)
    def _on_new_session_ready(self, session_id: str):
        self._active_opencode_session_id = session_id
        self._load_opencode_model_options()
        self.session_store.update_metadata(
            self._active_session_id, opencode_session_id=session_id
        )
        self._append_message("system", "New OpenCode conversation started.")
        self.activity_label.setText("Fresh OpenCode session · ready for your message.")
    def _on_new_session_error(self, message: str):
        self._append_message("error", f"Could not start a new OpenCode session: {message}")
        self.activity_label.setText(f"Could not create a new OpenCode session: {message}")
