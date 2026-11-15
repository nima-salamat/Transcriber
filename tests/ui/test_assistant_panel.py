"""UI tests for the chat-first OpenCode assistant surface."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QTextBrowser

from transcriber.ui.components.assistant_panel import AssistantPanel


def test_assistant_panel_is_a_conversation_surface(qtbot, tmp_path):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    paths = SimpleNamespace(config=tmp_path, models=tmp_path)
    panel = AssistantPanel(paths, QThreadPool())
    qtbot.addWidget(panel)

    assert isinstance(panel.chat_view, QTextBrowser)
    assert panel.send_button.text() == "Send"
    assert not panel.send_button.isEnabled()

    panel._append_message("user", "Summarize the open transcript")
    panel._on_notification({
        "params": {
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"text": "Here is a concise summary."},
            }
        }
    })
    panel._on_notification({
        "params": {
            "update": {
                "sessionUpdate": "tool_call",
                "title": "Read transcript",
            }
        }
    })
    panel._refresh_chat()

    visible_text = panel.chat_view.toPlainText()
    assert "Summarize the open transcript" in visible_text
    assert "Here is a concise summary." in visible_text
    assert "Read transcript" in visible_text


def test_quick_prompt_is_inserted_for_review_before_sending(qtbot, tmp_path):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    paths = SimpleNamespace(config=tmp_path, models=tmp_path)
    panel = AssistantPanel(paths, QThreadPool())
    qtbot.addWidget(panel)

    prompt = panel.QUICK_PROMPTS["Review transcript"]
    panel._insert_suggestion(prompt)

    assert panel.prompt.toPlainText() == prompt
    assert not panel._worker_active
