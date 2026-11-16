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
    assert panel.prompt_library_button.text() == "Prompt library"
    assert "specialist" in panel.prompt_library.read("00-AGENT.md").casefold()
    assert panel.voice_silence_spin.value() == 1.5
    assert not panel.voice_auto_submit_check.isChecked()
    assert panel.wake_phrase.placeholderText() == "For example: transcriber"
    assert panel.wake_model_combo.count() == 1
    assert panel.wake_model_combo.itemText(0) == "Select a Vosk wake-word model…"

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



def test_assistant_wake_model_selector_lists_installed_vosk_models(qtbot, tmp_path):
    from transcriber.core.config import SettingsStore

    app = QApplication.instance() or QApplication([])
    assert app is not None
    paths = SimpleNamespace(config=tmp_path / "config", models=tmp_path / "models")
    paths.config.mkdir()
    paths.models.mkdir()
    model_path = paths.models / "vosk-model-small-fa-0.42"
    (model_path / "am").mkdir(parents=True)

    store = SettingsStore(paths.config / "settings.json")
    store.load()
    store.update(wake_model_directory=str(model_path))

    model_manager = SimpleNamespace(
        installed_vosk_models=lambda *, include_sizes=False: [
            {
                "repo_id": "vosk/vosk-model-small-fa-0.42",
                "model_name": "vosk-model-small-fa-0.42",
                "language_name": "Persian",
                "path": str(model_path),
            }
        ]
    )
    panel = AssistantPanel(
        paths,
        QThreadPool(),
        store,
        model_manager=model_manager,
    )
    qtbot.addWidget(panel)

    assert panel.wake_model_combo.count() == 2
    assert panel.wake_model_combo.currentData() == str(model_path)
    assert "Persian" in panel.wake_model_combo.currentText()
