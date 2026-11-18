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



def test_assistant_can_switch_between_opencode_and_local_ollama(qtbot, tmp_path):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    paths = SimpleNamespace(config=tmp_path, models=tmp_path)
    panel = AssistantPanel(paths, QThreadPool())
    qtbot.addWidget(panel)
    panel.refresh_ollama_models = lambda: None

    panel.provider_combo.setCurrentIndex(panel.provider_combo.findData("ollama"))

    assert panel.provider_combo.currentData() == "ollama"
    assert panel.ollama_controls.isHidden() is False
    assert panel.project_card.isHidden() is True
    assert panel.connect_button.text() == "Connect Ollama"
    assert panel.voice_chat_button.objectName() == "VoiceOrb"
    assert "START" in panel.voice_chat_button.text()
    assert panel.voice_chat_button.accessibleName() == "Start voice conversation"


def test_assistant_exposes_installed_faster_whisper_voice_models(qtbot, tmp_path):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    paths = SimpleNamespace(config=tmp_path, models=tmp_path)
    model_manager = SimpleNamespace(
        installed=lambda *, include_sizes=False: [
            {"repo_id": "Systran/faster-whisper-small", "runtime": "faster-whisper", "compatible": True},
            {"repo_id": "vosk/vosk-model-small-fa-0.42", "runtime": "vosk", "compatible": True},
        ],
        installed_vosk_models=lambda *, include_sizes=False: [],
    )
    panel = AssistantPanel(paths, QThreadPool(), model_manager=model_manager)
    qtbot.addWidget(panel)

    values = [panel.voice_asr_combo.itemData(i) for i in range(panel.voice_asr_combo.count())]
    assert "Systran/faster-whisper-small" in values
    assert "vosk/vosk-model-small-fa-0.42" not in values



def test_voice_lifecycle_status_is_visible_when_voice_settings_are_collapsed(qtbot, tmp_path):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    paths = SimpleNamespace(config=tmp_path, models=tmp_path)
    panel = AssistantPanel(paths, QThreadPool())
    qtbot.addWidget(panel)

    assert panel.voice_panel.isHidden()
    assert not panel.voice_live_status.isHidden()

    panel.voice_agent = SimpleNamespace(mode="command")
    panel._on_voice_state("Wake word detected")
    panel._on_voice_state("Listening for your command…")
    assert "Listening for your command" in panel.voice_live_status.text()

    panel._on_voice_state("Silence detected · transcribing with Faster-Whisper")
    assert "transcribing" in panel.voice_live_status.text().casefold()

    qtbot.wait(80)
    visible_text = panel.chat_view.toPlainText()
    assert "Wake word detected" in visible_text
    assert "Microphone is listening" in visible_text
    assert "Converting speech to text" in visible_text


def test_voice_chat_shows_model_response_progress(qtbot, tmp_path):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    paths = SimpleNamespace(config=tmp_path, models=tmp_path)
    panel = AssistantPanel(paths, QThreadPool())
    qtbot.addWidget(panel)
    panel.voice_agent = SimpleNamespace(mode="processing")
    panel._voice_conversation_mode = True

    panel._append_stream_chunk("Hello")

    assert "Receiving response" in panel.voice_live_status.text()
    assert "Hello" in panel._messages[0]["text"]
