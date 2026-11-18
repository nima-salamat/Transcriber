from __future__ import annotations

import json

import pytest

from transcriber.assistant.ollama_client import OllamaCancellation, OllamaCancelled, OllamaClient, OllamaError


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload

    def __iter__(self):
        return iter(self.payload.splitlines(keepends=True))


def test_ollama_base_url_requires_a_valid_http_url():
    with pytest.raises(ValueError, match="absolute http"):
        OllamaClient("localhost:11434")


def test_list_models_reads_installed_local_models(monkeypatch):
    payload = {
        "models": [
            {"name": "qwen2.5:7b", "size": 7_000_000_000, "details": {"family": "qwen2"}},
            {"model": "llama3.2:3b", "details": {"family": "llama"}},
        ]
    }
    monkeypatch.setattr(
        "transcriber.assistant.ollama_client.urlopen",
        lambda request, timeout: FakeResponse(json.dumps(payload).encode("utf-8")),
    )

    models = OllamaClient().list_models()

    assert [item["name"] for item in models] == ["llama3.2:3b", "qwen2.5:7b"]
    assert models[1]["family"] == "qwen2"


def test_load_model_uses_empty_chat_and_configured_keep_alive(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse(b'{"done":true,"done_reason":"load"}')

    monkeypatch.setattr("transcriber.assistant.ollama_client.urlopen", fake_urlopen)
    client = OllamaClient(timeout=12.0, model_load_timeout=840.0)

    result = client.load_model("qwen2.5:7b", keep_alive="1h")

    assert captured["url"].endswith("/api/chat")
    assert captured["timeout"] == 840.0
    assert captured["body"] == {
        "model": "qwen2.5:7b", "messages": [], "stream": False, "keep_alive": "1h"
    }
    assert result["done"] is True


def test_model_discovery_keeps_the_short_api_timeout(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return FakeResponse(b'{"models":[]}')

    monkeypatch.setattr("transcriber.assistant.ollama_client.urlopen", fake_urlopen)

    OllamaClient(timeout=18.0, model_load_timeout=840.0).list_models()

    assert captured["url"].endswith("/api/tags")
    assert captured["timeout"] == 18.0


def test_model_load_timeout_error_identifies_the_model_endpoint(monkeypatch):
    def fake_urlopen(request, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr("transcriber.assistant.ollama_client.urlopen", fake_urlopen)
    client = OllamaClient(timeout=5.0, model_load_timeout=17.0)

    with pytest.raises(OllamaError, match=r"/api/chat.*17"):
        client.load_model("qwen2.5:7b")


def test_chat_streams_tokens_and_preserves_conversation_messages(monkeypatch):
    captured = {}
    lines = [
        {"message": {"role": "assistant", "content": "Hello"}, "done": False},
        {"message": {"role": "assistant", "content": " there."}, "done": False},
        {"message": {"role": "assistant", "content": ""}, "done": True, "eval_count": 2},
    ]

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse("".join(json.dumps(item) + "\n" for item in lines).encode("utf-8"))

    monkeypatch.setattr("transcriber.assistant.ollama_client.urlopen", fake_urlopen)
    chunks = []
    result = OllamaClient().chat(
        "qwen2.5:7b",
        [{"role": "user", "content": "Say hello"}],
        on_chunk=chunks.append,
    )

    assert captured["body"]["stream"] is True
    assert captured["body"]["messages"] == [{"role": "user", "content": "Say hello"}]
    assert chunks == ["Hello", " there."]
    assert result["text"] == "Hello there."
    assert result["metrics"]["eval_count"] == 2



def test_chat_sends_function_schemas_and_preserves_tool_history(monkeypatch):
    captured = {}
    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        payload = {"message": {"role": "assistant", "content": "Done."}, "done": True}
        return FakeResponse((json.dumps(payload) + "\\n").encode("utf-8"))
    monkeypatch.setattr("transcriber.assistant.ollama_client.urlopen", fake_urlopen)
    tool = {"type": "function", "function": {"name": "desktop.launch_app", "parameters": {"type": "object"}}}
    history = [
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "desktop.launch_app", "arguments": {"app": "notepad"}}}]},
        {"role": "tool", "tool_name": "desktop.launch_app", "content": "{\\\"ok\\\":true}"},
        {"role": "user", "content": "Thanks"},
    ]

    result = OllamaClient().chat("qwen2.5:7b", history, tools=[tool])

    assert captured["body"]["tools"] == [tool]
    assert captured["body"]["messages"] == history
    assert result["text"] == "Done."
    assert result["tool_calls"] == []


def test_chat_collects_tool_calls_from_streaming_chunks(monkeypatch):
    call = {"function": {"name": "desktop.launch_app", "arguments": {"app": "notepad"}}}
    chunks = [
        {"message": {"role": "assistant", "content": "", "tool_calls": [call]}, "done": False},
        {"message": {"role": "assistant", "content": ""}, "done": True},
    ]
    payload = "".join(json.dumps(item) + "\\n" for item in chunks).encode("utf-8")
    monkeypatch.setattr(
        "transcriber.assistant.ollama_client.urlopen",
        lambda request, timeout: FakeResponse(payload),
    )

    result = OllamaClient().chat(
        "qwen2.5:7b", [{"role": "user", "content": "Open Notepad"}],
        tools=[{"type": "function", "function": {"name": "desktop.launch_app"}}],
    )

    assert result["tool_calls"] == [call]


def test_chat_cancellation_before_network_does_not_send_request(monkeypatch):
    def forbidden_urlopen(*_args, **_kwargs):
        raise AssertionError("a cancelled chat must not make a network request")
    monkeypatch.setattr("transcriber.assistant.ollama_client.urlopen", forbidden_urlopen)
    token = OllamaCancellation()
    token.cancel()

    with pytest.raises(OllamaCancelled):
        OllamaClient().chat("qwen2.5:7b", [{"role": "user", "content": "Hello"}], cancellation=token)


def test_cancellation_closes_an_attached_response():
    class Closable:
        closed = False
        def close(self):
            self.closed = True
    response = Closable()
    token = OllamaCancellation()

    token.attach(response)
    token.cancel()

    assert token.cancelled
    assert response.closed
def test_chat_reports_server_error(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeResponse(b'{"error":"model not found"}\n')

    monkeypatch.setattr("transcriber.assistant.ollama_client.urlopen", fake_urlopen)
    with pytest.raises(OllamaError, match="model not found"):
        OllamaClient().chat("missing:latest", [{"role": "user", "content": "Hi"}])
