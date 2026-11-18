from __future__ import annotations

import json

import pytest

from transcriber.assistant.chat_sessions import ChatSessionStore


def test_create_and_restore_multiple_provider_sessions(tmp_path):
    path = tmp_path / "assistant-sessions.json"
    store = ChatSessionStore(path)

    first = store.create_session("ollama", title="General chat")
    store.save_state(
        first["id"],
        messages=[{"role": "user", "text": "hello"}],
        provider_messages=[
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ],
    )
    store.update_metadata(first["id"], model="qwen2.5:7b")

    second = store.create_session("opencode", title="Project work")
    restored = ChatSessionStore(path)

    assert restored.active_session_id == second["id"]
    assert restored.get_session(first["id"])["messages"][0]["text"] == "hello"
    assert restored.get_session(first["id"])["provider_messages"][-1]["content"] == "hi"
    assert restored.get_session(first["id"])["metadata"]["model"] == "qwen2.5:7b"
    assert restored.get_session(second["id"])["provider"] == "opencode"


def test_switch_and_delete_sessions_updates_active_id(tmp_path):
    store = ChatSessionStore(tmp_path / "sessions.json")
    first = store.create_session("ollama")
    second = store.create_session("opencode")

    store.set_active(first["id"])
    assert store.active_session_id == first["id"]

    selected = store.delete_session(first["id"])
    assert selected == second["id"]
    assert store.active_session_id == second["id"]


def test_session_store_keeps_unicode_and_tool_call_objects(tmp_path):
    path = tmp_path / "sessions.json"
    store = ChatSessionStore(path)
    session = store.create_session("ollama")
    history = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "function": {
                    "name": "browser.search",
                    "arguments": {"query": "آزمایش هوش مصنوعی"},
                }
            }],
        },
        {"role": "tool", "tool_name": "browser.search", "content": '{"ok":true}'},
    ]

    store.save_state(
        session["id"],
        messages=[{"role": "user", "text": "سلام دنیا"}],
        provider_messages=history,
        title="گفتگوی فارسی",
    )
    raw = json.loads(path.read_text(encoding="utf-8"))
    restored = ChatSessionStore(path).active_session()

    assert "سلام دنیا" in path.read_text(encoding="utf-8")
    assert raw["sessions"][0]["title"] == "گفتگوی فارسی"
    assert restored["provider_messages"][0]["tool_calls"][0]["function"]["name"] == "browser.search"


def test_corrupt_session_file_is_not_overwritten_during_load(tmp_path):
    path = tmp_path / "sessions.json"
    path.write_text("{broken", encoding="utf-8")

    store = ChatSessionStore(path)

    assert store.active_session() is None
    assert path.read_text(encoding="utf-8") == "{broken"
    new = store.create_session("ollama")
    assert store.active_session_id == new["id"]


def test_unknown_session_operations_raise(tmp_path):
    store = ChatSessionStore(tmp_path / "sessions.json")
    with pytest.raises(KeyError):
        store.set_active("missing")
