"""Message insertion, stable streaming updates and conversation rendering coordination."""
from __future__ import annotations


class AssistantConversationMixin:
    def _schedule_chat_refresh(self):
        if not self._chat_refresh_timer.isActive():
            self._chat_refresh_timer.start()

    def _refresh_chat(self, *, scroll_to_bottom: bool = False):
        """Update the conversation for structural changes or an explicit session load."""
        if not hasattr(self, "conversation_view"):
            return
        self.conversation_view.set_messages(
            self._messages, force_scroll_to_bottom=scroll_to_bottom
        )
        self.chat_view.setPlainText(self.conversation_view.toPlainText())
        title = self._session_title()
        active = self.session_store.get_session(self._active_session_id) or {}
        provider = active.get("provider") or self._chat_provider
        provider_name = "Ollama" if provider == "ollama" else "OpenCode"
        model = self._ollama_model if provider == "ollama" else "workspace agent"
        state = "Connected" if self._chat_is_connected() else "Disconnected"
        subtitle = f"{provider_name} · {model} · {state}"
        workspace = str(self.project_dir) if provider == "opencode" else str(self.ollama_url.text())
        self.conversation_header.set_conversation(title, subtitle, workspace)

    def _append_message(self, role: str, text: str, **metadata):
        item = {"role": role, "text": str(text), **metadata}
        self._messages.append(item)
        if len(self._messages) > 400:
            drop_count = len(self._messages) - 400
            del self._messages[:drop_count]
            if self._streaming_index is not None:
                self._streaming_index -= drop_count
                if self._streaming_index < 0:
                    self._streaming_index = None
        self._schedule_chat_refresh()
        self._schedule_session_persist()

    def _begin_assistant_stream(self, status: str = "Thinking"):
        """Create the assistant card once; its answer and thinking stream into this card."""
        index = self._streaming_index
        if (
            index is not None
            and 0 <= index < len(self._messages)
            and self._messages[index].get("role") == "assistant"
        ):
            self._messages[index]["status"] = str(status or "Thinking")
            self._set_inline_agent_status(status)
            return index
        self._append_message(
            "assistant",
            "",
            thinking="",
            status=str(status or "Thinking"),
            streaming=True,
        )
        self._streaming_index = len(self._messages) - 1
        # Create the new card immediately, before the first provider token arrives.
        self._refresh_chat()
        if self.voice_agent is not None and self.voice_agent.mode == "processing":
            provider_name = "Ollama" if self._chat_provider == "ollama" else "OpenCode Agent"
            self._set_voice_activity(
                f"Receiving response from {provider_name}…",
                stage="receiving",
                log_message=f"{provider_name} is generating your response.",
            )
        return self._streaming_index

    def _append_thinking_chunk(self, text: str):
        if not text or getattr(self, "_shutting_down", False):
            return
        index = self._streaming_index
        if (
            index is None
            or index < 0
            or index >= len(self._messages)
            or self._messages[index].get("role") != "assistant"
        ):
            index = self._begin_assistant_stream("Thinking")
        item = self._messages[index]
        item["thinking"] = str(item.get("thinking") or "") + str(text)
        item["status"] = "Thinking"
        item["streaming"] = True
        if not self.conversation_view.append_to_latest_assistant_thinking(text):
            self._refresh_chat()
            self.conversation_view.append_to_latest_assistant_thinking(text)
        self._schedule_session_persist()

    def _append_stream_chunk(self, text: str):
        if not text or getattr(self, "_shutting_down", False):
            return
        index = self._streaming_index
        if (
            index is None
            or index < 0
            or index >= len(self._messages)
            or self._messages[index].get("role") != "assistant"
        ):
            index = self._begin_assistant_stream("Generating")
        item = self._messages[index]
        item["text"] = str(item.get("text") or "") + str(text)
        item["status"] = "Generating"
        item["streaming"] = True
        if not self.conversation_view.append_to_latest_assistant_text(text):
            self._refresh_chat()
            self.conversation_view.append_to_latest_assistant_text(text)
        self._schedule_session_persist()

    def _set_inline_agent_status(self, status: str):
        value = " ".join(str(status or "").split())
        if not value:
            return
        index = self._streaming_index
        if (
            index is not None
            and 0 <= index < len(self._messages)
            and self._messages[index].get("role") == "assistant"
        ):
            self._messages[index]["status"] = value
            self.conversation_view.set_latest_assistant_status(value)
            self._schedule_session_persist()
        elif hasattr(self, "composer"):
            self.composer.set_status(value)

    def _finish_assistant_stream(self, status: str = "Done"):
        index = self._streaming_index
        if (
            index is not None
            and 0 <= index < len(self._messages)
            and self._messages[index].get("role") == "assistant"
        ):
            self._messages[index]["status"] = str(status or "Done")
            self._messages[index]["streaming"] = False
            self.conversation_view.finish_latest_assistant_stream(status)
            self._schedule_session_persist()
        self._streaming_index = None

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
