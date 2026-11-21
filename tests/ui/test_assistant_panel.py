"""UI tests for the chat-first OpenCode assistant surface."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import QApplication, QTextBrowser

from transcriber.ui.components.assistant.message_widget import MessageWidget
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
    assert panel.prompt_library_button.text() == "Open prompt library"
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


def test_assistant_surface_has_no_quick_prompts_or_redundant_global_header(qtbot, tmp_path):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    paths = SimpleNamespace(config=tmp_path, models=tmp_path)
    panel = AssistantPanel(paths, QThreadPool())
    qtbot.addWidget(panel)

    assert panel.root_layout.count() == 1
    assert panel.settings_button is panel.sidebar.settings_button
    assert not hasattr(panel, "QUICK_PROMPTS")
    assert not hasattr(panel, "suggestions_container")
    assert not hasattr(panel.conversation_view, "prompt_grid")



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



def test_voice_orb_tracks_connecting_and_stopped_states(qtbot, tmp_path):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    paths = SimpleNamespace(config=tmp_path, models=tmp_path)
    panel = AssistantPanel(paths, QThreadPool())
    qtbot.addWidget(panel)

    assert "Voice" in panel.voice_chat_button.text()
    assert panel.voice_chat_button.accessibleName() == "Start voice conversation"

    panel._voice_conversation_mode = True
    panel._sync_voice_orb()
    assert "Stop voice" in panel.voice_chat_button.text()
    assert panel.voice_chat_button.accessibleName() == "Stop voice conversation"

    panel._voice_conversation_mode = False
    panel._sync_voice_orb()
    assert "Voice" in panel.voice_chat_button.text()
    assert panel.voice_chat_button.accessibleName() == "Start voice conversation"



def test_agent_runtime_controls_the_agent_tools_toggle(qtbot, tmp_path):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    paths = SimpleNamespace(config=tmp_path, models=tmp_path)
    panel = AssistantPanel(paths, QThreadPool())
    qtbot.addWidget(panel)

    assert not panel.agent_mode_check.isEnabled()
    registry = SimpleNamespace(describe=lambda **_kwargs: [])
    panel.set_agent_runtime(registry)
    assert not panel.agent_mode_check.isEnabled()
    assert panel.agent_mode_check.isChecked()

    panel.provider_combo.setCurrentIndex(panel.provider_combo.findData("ollama"))
    assert panel.agent_mode_check.isEnabled()


def test_new_local_chat_clears_only_the_current_conversation(qtbot, tmp_path):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    paths = SimpleNamespace(config=tmp_path, models=tmp_path)
    panel = AssistantPanel(paths, QThreadPool())
    qtbot.addWidget(panel)
    panel._chat_provider = "ollama"
    panel._ollama_messages = [
        {"role": "system", "content": "instructions"},
        {"role": "user", "content": "old conversation"},
    ]
    panel._messages = [{"role": "user", "text": "old conversation"}]

    panel.new_chat()

    assert panel._ollama_messages == []
    assert "old conversation" not in panel.chat_view.toPlainText()
    assert "New local conversation started." in panel._messages[-1]["text"]


def test_ollama_stop_is_independent_of_opencode_connection(qtbot, tmp_path):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    paths = SimpleNamespace(config=tmp_path, models=tmp_path)
    panel = AssistantPanel(paths, QThreadPool())
    qtbot.addWidget(panel)
    class Cancellation:
        cancelled = False
        def cancel(self):
            self.cancelled = True
    token = Cancellation()
    panel._chat_provider = "ollama"
    panel._ollama_cancellation = token
    panel._agent_turn_active = True
    panel._worker_active = True

    panel.cancel_prompt()

    assert token.cancelled
    assert panel._stop_requested
    assert panel.composer._busy is True
    assert panel.composer._stoppable is True
    assert panel.stop_button.isEnabled() is False
    assert panel.stop_button.toolTip() == "Stop the current response"
    assert "Stop requested" in panel._messages[-1]["text"]

def test_settings_icon_opens_a_separate_stacked_settings_page(qtbot, tmp_path):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    paths = SimpleNamespace(config=tmp_path, models=tmp_path)
    panel = AssistantPanel(paths, QThreadPool())
    qtbot.addWidget(panel)

    assert panel.page_stack.currentWidget() is panel.conversation_page
    assert panel.settings_button.toolTip() == "Assistant settings"
    assert panel.settings_button is panel.sidebar.settings_button
    assert not panel.conversation_page.isAncestorOf(panel.provider_combo)
    assert not panel.conversation_page.isAncestorOf(panel.prompt_library_button)

    panel.settings_button.click()
    assert panel.page_stack.currentWidget() is panel.settings_page
    assert panel.settings_content.isAncestorOf(panel.provider_combo)
    assert panel.settings_content.isAncestorOf(panel.voice_panel)
    assert panel.settings_content.isAncestorOf(panel.project_card)
    assert panel.settings_content.isAncestorOf(panel.prompt_library_button)

    panel.settings_back_button.click()
    assert panel.page_stack.currentWidget() is panel.conversation_page


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
    assert panel.voice_chat_button.objectName() == "AssistantVoiceButton"
    assert "Voice" in panel.voice_chat_button.text()
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



def test_voice_lifecycle_status_is_visible_on_the_conversation_page(qtbot, tmp_path):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    paths = SimpleNamespace(config=tmp_path, models=tmp_path)
    panel = AssistantPanel(paths, QThreadPool())
    qtbot.addWidget(panel)

    assert panel.page_stack.currentWidget() is panel.conversation_page
    assert panel.voice_panel.parentWidget() is panel.settings_content
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



def test_assistant_message_copy_button_copies_rendered_text(qtbot):
    app = QApplication.instance() or QApplication([])
    assert app is not None

    widget = MessageWidget("assistant", "**Formatted answer**\n\nSecond paragraph.")
    qtbot.addWidget(widget)
    widget.show()
    expected = widget.body.toPlainText()

    widget.copy_button.click()

    qtbot.waitUntil(lambda: QApplication.clipboard().text() == expected)
    assert widget.copy_button.text() == "Copied"


def test_helper_messages_are_collapsed_until_the_user_expands_them(qtbot):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    for role in ("tool", "system"):
        widget = MessageWidget(role, "Internal helper information")
        qtbot.addWidget(widget)
        widget.show()

        assert widget.body.isHidden()
        assert widget.detail_toggle.arrowType() == Qt.ArrowType.RightArrow
        assert widget.copy_button.isHidden()

        widget.detail_toggle.click()
        assert not widget.body.isHidden()
        assert widget.detail_toggle.arrowType() == Qt.ArrowType.DownArrow
        assert widget.copy_button.isVisible()

        widget.detail_toggle.click()
        assert widget.body.isHidden()
        assert widget.detail_toggle.arrowType() == Qt.ArrowType.RightArrow



def test_history_sidebar_shows_a_bounded_latest_user_preview(qtbot, tmp_path):
    from transcriber.assistant.chat_sessions import ChatSessionStore
    from transcriber.ui.components.assistant.sidebar import AssistantSidebar
    from transcriber.ui.design.icon_registry import IconRegistry

    store = ChatSessionStore(tmp_path / "sessions.json")
    session = store.create_session("ollama", title="Transcript review")
    latest_prompt = "Latest question about this transcript: " + ("more detail " * 20)
    store.save_state(
        session["id"],
        title="Transcript review",
        messages=[
            {"role": "user", "text": "Initial question that established the conversation"},
            {"role": "assistant", "text": "Initial answer"},
            {"role": "user", "text": latest_prompt},
        ],
    )
    sidebar = AssistantSidebar(store, IconRegistry())
    qtbot.addWidget(sidebar)
    sidebar.resize(264, 520)
    sidebar.show()

    item = next(
        sidebar.session_list.item(index)
        for index in range(sidebar.session_list.count())
        if sidebar.session_list.item(index).data(sidebar.SESSION_ROLE) == session["id"]
    )
    row = sidebar.session_list.itemWidget(item)
    assert row is not None
    # Only the custom row widget should render visible text; the native item
    # must stay empty or its delegate text bleeds through the transparent row.
    assert item.text() == ""
    assert row._full_preview.startswith("Latest question about this transcript")
    assert len(row._full_preview) <= 113
    qtbot.wait(40)
    assert row.preview_label.text()

    sidebar.update_session_title(
        session["id"],
        "Renamed transcript review",
        messages=session["messages"],
        updated_at=session["updated_at"],
    )
    assert item.text() == ""
    assert row.title_label.text() == "Renamed transcript review"


def test_loading_a_session_forces_conversation_to_latest_message(qtbot):
    from transcriber.ui.components.assistant.conversation_view import ConversationView

    app = QApplication.instance() or QApplication([])
    assert app is not None
    view = ConversationView()
    qtbot.addWidget(view)
    view.resize(680, 460)
    view.show()
    messages = [
        {"role": "user" if index % 2 == 0 else "assistant",
         "text": f"Message {index}: " + ("long conversation text " * 12)}
        for index in range(36)
    ]

    view.set_messages(messages)
    qtbot.waitUntil(lambda: view.scroll_area.verticalScrollBar().maximum() > 0)
    bar = view.scroll_area.verticalScrollBar()
    bar.setValue(0)
    assert bar.value() == 0

    view.set_messages(messages, force_scroll_to_bottom=True)
    qtbot.waitUntil(lambda: bar.value() == bar.maximum() and bar.maximum() > 0)


def test_agent_execution_contract_explains_continue_and_async_completion():
    from transcriber.assistant.prompt_library import AGENT_EXECUTION_CONTRACT

    assert "CONTINUE" in AGENT_EXECUTION_CONTRACT
    assert "DONE" in AGENT_EXECUTION_CONTRACT
    assert "app_execute_action" in AGENT_EXECUTION_CONTRACT
    assert "app_get_operation_status" in AGENT_EXECUTION_CONTRACT
    assert "queued" in AGENT_EXECUTION_CONTRACT
    assert "completed" in AGENT_EXECUTION_CONTRACT
    assert "general-purpose PowerShell" in AGENT_EXECUTION_CONTRACT
    assert "system.run_command" in AGENT_EXECUTION_CONTRACT
    assert "Ollama" in AGENT_EXECUTION_CONTRACT
    assert "OpenCode" in AGENT_EXECUTION_CONTRACT
    assert "Destructive actions" in AGENT_EXECUTION_CONTRACT
    assert "do not use a separate shell to evade" in AGENT_EXECUTION_CONTRACT


def test_consecutive_helper_events_share_one_collapsed_details_card(qtbot):
    from transcriber.ui.components.assistant.conversation_view import ConversationView

    app = QApplication.instance() or QApplication([])
    assert app is not None
    view = ConversationView()
    qtbot.addWidget(view)
    view.resize(720, 520)
    view.show()

    view.set_messages([
        {"role": "tool", "text": "Running browser.search"},
        {"role": "tool", "text": "Completed browser.search"},
        {"role": "system", "text": "Browser page loaded"},
        {"role": "assistant", "text": "Here are the search results."},
        {"role": "tool", "text": "Running browser.snapshot"},
        {"role": "tool", "text": "Completed browser.snapshot"},
    ])

    assert len(view._widgets) == 3
    first_group, answer, second_group = view._widgets
    assert first_group.role == "tool"
    assert "Running browser.search" in first_group._text
    assert "Completed browser.search" in first_group._text
    assert "Browser page loaded" in first_group._text
    assert answer.role == "assistant"
    assert answer._text == "Here are the search results."
    assert second_group.role == "tool"
    assert "Running browser.snapshot" in second_group._text
    assert "Completed browser.snapshot" in second_group._text
    assert first_group.body.isHidden()
    assert second_group.body.isHidden()


def test_browser_skill_and_enabled_action_schemas_are_preloaded(qtbot, tmp_path):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    panel = AssistantPanel(
        SimpleNamespace(config=tmp_path, models=tmp_path),
        QThreadPool(),
    )
    qtbot.addWidget(panel)

    skills = panel._matched_skill_context(
        "Open Chrome and search for mobile phone prices."
    )
    assert "PRELOADED AGENT SKILL: browser-automation" in skills
    assert "browser.search" in skills
    assert "real tool call" in skills

    class Registry:
        def describe(self, *, include_disabled=False):
            return [{
                "name": "browser.search",
                "description": "Search the controlled browser.",
                "required": ["query"],
                "permission": "browser_control",
                "requires_approval": False,
                "destructive": False,
                "enabled": True,
            }]

    panel._action_registry = Registry()
    actions = panel._mcp_action_context()
    assert "browser.search" in actions
    assert "app_execute_action" in actions
    assert "operation_id" in actions


def test_assistant_thinking_is_inline_and_streams_without_rebuilding_the_card(
    qtbot, tmp_path, monkeypatch
):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    panel = AssistantPanel(
        SimpleNamespace(config=tmp_path, models=tmp_path),
        QThreadPool(),
    )
    qtbot.addWidget(panel)

    panel._begin_assistant_stream("Thinking")
    widget = panel.conversation_view._widgets[-1]
    calls = []
    original_set_markdown = widget.body.set_markdown

    def record_markdown(value):
        calls.append(value)
        original_set_markdown(value)

    monkeypatch.setattr(widget.body, "set_markdown", record_markdown)

    panel._append_thinking_chunk("Checking the first part. ")
    panel._append_thinking_chunk("Checking the second part.")
    panel._append_stream_chunk("The answer ")
    panel._append_stream_chunk("is 42.")

    assert panel.conversation_view._widgets[-1] is widget
    assert widget.thinking_body.toPlainText() == (
        "Checking the first part. Checking the second part."
    )
    assert widget.body.toPlainText() == "The answer is 42."
    assert widget.layout().indexOf(widget.thinking_frame) < widget.layout().indexOf(widget.body)
    # Stream chunks use QTextCursor; Markdown is rendered once after generation.
    assert calls == []

    panel._finish_assistant_stream("Done")
    assert calls == ["The answer is 42."]
    assert widget.thinking_toggle.text() == "Thought process"
    assert widget.thinking_body.isHidden()
    assert widget._streaming is False


def test_voice_status_uses_short_labels_in_the_composer_status(qtbot, tmp_path):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    panel = AssistantPanel(
        SimpleNamespace(config=tmp_path, models=tmp_path),
        QThreadPool(),
    )
    qtbot.addWidget(panel)

    panel._set_voice_activity("Microphone is listening. Speak now.", stage="listening")
    assert panel.composer.status_label.text() == "Listening"

    panel._set_voice_activity("Converting speech to text…", stage="transcribing")
    assert panel.composer.status_label.text() == "Transcribing"

    panel._set_voice_activity("Speech recognition failed", stage="error")
    assert panel.composer.status_label.text() == "Error"


def test_assistant_shutdown_cancels_active_models_voice_and_opencode(qtbot, tmp_path):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    panel = AssistantPanel(
        SimpleNamespace(config=tmp_path, models=tmp_path),
        QThreadPool(),
    )
    qtbot.addWidget(panel)

    class Token:
        def __init__(self):
            self.cancelled = False
        def cancel(self):
            self.cancelled = True

    class Closeable:
        def __init__(self):
            self.closed = 0
        def close(self):
            self.closed += 1

    model_load = Token()
    ollama_turn = Token()
    voice = Closeable()
    opencode = Closeable()
    panel._model_load_cancellation = model_load
    panel._ollama_cancellation = ollama_turn
    panel.voice_agent = voice
    panel.client = opencode

    panel.shutdown()
    panel.shutdown()

    assert panel._shutting_down
    assert model_load.cancelled
    assert ollama_turn.cancelled
    assert panel.voice_agent is None
    assert panel.client is None
    qtbot.waitUntil(
        lambda: voice.closed == 1 and opencode.closed == 1,
        timeout=3000,
    )
    assert panel.shutdown_complete

def test_ollama_thinking_signal_is_rendered_inside_the_assistant_message(qtbot, tmp_path):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    panel = AssistantPanel(
        SimpleNamespace(config=tmp_path, models=tmp_path),
        QThreadPool(),
    )
    qtbot.addWidget(panel)

    panel._begin_assistant_stream("Thinking")
    panel.signals.ollama_thinking.emit("Checking the project structure.")
    panel._append_stream_chunk("I found the project files.")

    widget = panel.conversation_view._widgets[-1]
    assert widget.role == "assistant"
    assert widget.thinking_body.toPlainText() == "Checking the project structure."
    assert widget.body.toPlainText() == "I found the project files."
    assert not hasattr(panel, "agent_thinking")


def test_conversation_messages_expand_a_little_on_wide_desktops(qtbot):
    from transcriber.ui.components.assistant.conversation_view import ConversationView

    app = QApplication.instance() or QApplication([])
    assert app is not None
    view = ConversationView()
    qtbot.addWidget(view)
    view.resize(900, 520)
    view.show()
    view.set_messages([
        {"role": "assistant", "text": "A response that should remain readable."},
        {"role": "user", "text": "A longer user message that can use more horizontal room."},
    ])
    qtbot.wait(30)

    assert all(widget.maximumWidth() == 960 for widget in view._widgets)

    view.resize(1500, 520)
    qtbot.wait(50)

    assert all(widget.maximumWidth() == 1120 for widget in view._widgets)
    assert all(widget.width() <= view.scroll_area.viewport().width() for widget in view._widgets)


def test_agent_permissions_and_remembered_browser_approval_are_persistent(qtbot, tmp_path):
    from transcriber.assistant.action_registry import ActionRegistry
    from transcriber.assistant.permissions import AgentPermission
    from transcriber.core.config import SettingsStore

    app = QApplication.instance() or QApplication([])
    assert app is not None
    paths = SimpleNamespace(config=tmp_path, models=tmp_path)
    settings_store = SettingsStore(tmp_path / "settings.json")
    settings_store.load()
    panel = AssistantPanel(paths, QThreadPool(), settings_store)
    qtbot.addWidget(panel)
    registry = ActionRegistry(
        permissions={AgentPermission.READ_ONLY, AgentPermission.EDIT_CONTENT},
    )
    panel.set_agent_runtime(registry)

    browser_permission = panel.agent_permission_checks[AgentPermission.BROWSER_CONTROL]
    assert not browser_permission.isChecked()
    browser_permission.setChecked(True)
    assert "browser_control" in settings_store.settings.agent_permissions
    assert AgentPermission.BROWSER_CONTROL in registry.permissions
    assert panel.agent_trust_browser_check.isEnabled()

    panel.agent_trust_browser_check.setChecked(True)
    assert settings_store.settings.agent_trusted_permissions == ["browser_control"]
    assert AgentPermission.BROWSER_CONTROL in registry.trusted_permissions
    reloaded_settings = SettingsStore(tmp_path / "settings.json")
    reloaded_settings.load()
    assert reloaded_settings.settings.agent_trusted_permissions == ["browser_control"]

    browser_permission.setChecked(False)
    assert "browser_control" not in settings_store.settings.agent_permissions
    assert settings_store.settings.agent_trusted_permissions == []
    assert AgentPermission.BROWSER_CONTROL not in registry.trusted_permissions
    assert not panel.agent_trust_browser_check.isEnabled()


def test_opencode_stop_bypasses_a_saturated_shared_worker_pool(qtbot, tmp_path):
    from threading import Event

    app = QApplication.instance() or QApplication([])
    assert app is not None
    panel = AssistantPanel(
        SimpleNamespace(config=tmp_path, models=tmp_path),
        QThreadPool(),
    )
    qtbot.addWidget(panel)

    cancelled = Event()

    class FakeClient:
        connected = True

        def cancel(self, *, timeout=3.0):
            assert timeout == 5
            cancelled.set()

    class SaturatedPool:
        def start(self, *_args, **_kwargs):
            raise AssertionError("Stop must not be queued in the shared worker pool.")

    panel.client = FakeClient()
    panel.thread_pool = SaturatedPool()
    panel._chat_provider = "opencode"
    panel._agent_turn_active = True
    panel._worker_active = True

    panel.cancel_prompt()

    qtbot.waitUntil(cancelled.is_set, timeout=1500)
    assert panel._stop_requested
    assert not panel.stop_button.isEnabled()
    assert panel.activity_label.text() == "Stopping…"




def test_opencode_prompt_context_exposes_general_powershell_only_when_permission_is_enabled(
    qtbot, tmp_path
):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    panel = AssistantPanel(
        SimpleNamespace(config=tmp_path, models=tmp_path),
        QThreadPool(),
    )
    qtbot.addWidget(panel)

    class Registry:
        enabled = True

        def describe(self, *, include_disabled=False):
            return [{
                "name": "system.run_command",
                "description": "Run PowerShell.",
                "required": ["command"],
                "permission": "command_execution",
                "requires_approval": True,
                "destructive": False,
                "enabled": self.enabled,
            }]

    registry = Registry()
    panel._action_registry = registry
    enabled_context = panel._mcp_action_context()
    assert "system.run_command" in enabled_context
    assert "general-purpose PowerShell" in enabled_context
    assert "app_execute_action" in enabled_context
    assert "timeout_seconds" in enabled_context

    registry.enabled = False
    disabled_context = panel._mcp_action_context()
    assert "PowerShell is unavailable" in disabled_context
    assert "Run PowerShell commands" in disabled_context
    assert "bypass" in disabled_context



def test_ollama_next_generation_round_shows_thinking_before_any_new_tokens(
    qtbot, tmp_path
):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    panel = AssistantPanel(
        SimpleNamespace(config=tmp_path, models=tmp_path),
        QThreadPool(),
    )
    qtbot.addWidget(panel)

    panel._begin_assistant_stream("Thinking")
    panel._finish_assistant_stream("Working")
    panel.signals.ollama_round_started.emit(2)

    widget = panel.conversation_view._widgets[-1]
    assert widget.role == "assistant"
    assert widget._status == "Thinking"
    assert widget._streaming is True
    assert widget.thinking_toggle.text() == "Thinking"

    panel.signals.ollama_thinking.emit("Reviewing the command result.")
    panel.signals.ollama_chunk.emit("The next step is complete.")

    assert panel.conversation_view._widgets[-1] is widget
    assert widget.thinking_body.toPlainText() == "Reviewing the command result."
    assert widget.body.toPlainText() == "The next step is complete."


def test_opencode_tool_completion_starts_the_next_thinking_card_immediately(
    qtbot, tmp_path
):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    panel = AssistantPanel(
        SimpleNamespace(config=tmp_path, models=tmp_path),
        QThreadPool(),
    )
    qtbot.addWidget(panel)
    panel._agent_turn_active = True

    panel._begin_assistant_stream("Thinking")
    panel._on_notification({
        "params": {
            "update": {
                "sessionUpdate": "tool_call",
                "toolCallId": "tool-1",
                "title": "Run PowerShell",
            }
        }
    })
    panel._on_notification({
        "params": {
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "tool-1",
                "title": "Run PowerShell",
                "status": "completed",
            }
        }
    })

    widget = panel.conversation_view._widgets[-1]
    assert widget.role == "assistant"
    assert widget._status == "Thinking"
    assert widget._streaming is True

    panel._on_notification({
        "params": {
            "update": {
                "sessionUpdate": "agent_thought_chunk",
                "content": {"type": "text", "text": "Inspecting the result."},
            }
        }
    })
    panel._on_notification({
        "params": {
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "The next step is complete."},
            }
        }
    })

    assert panel.conversation_view._widgets[-1] is widget
    assert widget.thinking_body.toPlainText() == "Inspecting the result."
    assert widget.body.toPlainText() == "The next step is complete."
