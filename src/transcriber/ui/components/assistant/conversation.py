"""Message insertion, incremental refresh and conversation rendering coordination."""
from __future__ import annotations

from PySide6.QtGui import QTextCursor


class AssistantConversationMixin:
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

    def _refresh_chat(self, *, scroll_to_bottom: bool = False):
        """Update messages; explicit session loads always open at the newest message."""
        if not hasattr(self, "conversation_view"):
            return
        self.conversation_view.set_messages(
            self._messages, force_scroll_to_bottom=scroll_to_bottom
        )
        self.chat_view.setPlainText(self.conversation_view.toPlainText())
        self.suggestions_container.setVisible(False)
        title = self._session_title()
        active = self.session_store.get_session(self._active_session_id) or {}
        provider = active.get("provider") or self._chat_provider
        provider_name = "Ollama" if provider == "ollama" else "OpenCode"
        model = self._ollama_model if provider == "ollama" else "workspace agent"
        state = "Connected" if self._chat_is_connected() else "Disconnected"
        subtitle = f"{provider_name} · {model} · {state}"
        workspace = str(self.project_dir) if provider == "opencode" else str(self.ollama_url.text())
        self.conversation_header.set_conversation(title, subtitle, workspace)

    def _append_message(self, role: str, text: str):
        self._messages.append({"role": role, "text": str(text)})
        if len(self._messages) > 400:
            del self._messages[:-400]
        self._schedule_chat_refresh()
        self._schedule_session_persist()

    def _append_stream_chunk(self, text: str):
        if not text:
            return
        first_chunk = self._streaming_index is None or self._streaming_index >= len(self._messages)
        if first_chunk:
            self._messages.append({"role": "assistant", "text": ""})
            self._streaming_index = len(self._messages) - 1
            if self.voice_agent is not None and self.voice_agent.mode == "processing":
                provider_name = "Ollama" if self._chat_provider == "ollama" else "OpenCode Agent"
                self._set_voice_activity(
                    f"Receiving response from {provider_name}…",
                    stage="receiving",
                    log_message=f"{provider_name} is generating your response.",
                )
        self._messages[self._streaming_index]["text"] += str(text)
        self._schedule_chat_refresh()
        self._schedule_session_persist()

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

