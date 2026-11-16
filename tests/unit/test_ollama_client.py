from __future__ import annotations

import io
import json

import pytest

from transcriber.assistant.ollama_client import OllamaClient, OllamaError


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
        return FakeResponse(b'{"done":true,"done_reason":"load"}')

    monkeypatch.setattr("transcriber.assistant.ollama_client.urlopen", fake_urlopen)
    client = OllamaClient()

    result = client.load_model("qwen2.5:7b", keep_alive="1h")

    assert captured["url"].endswith("/api/chat")
    assert captured["body"] == {
        "model": "qwen2.5:7b", "messages": [], "stream": False, "keep_alive": "1h"
    }
    assert result["done"] is True


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


def test_chat_reports_server_error(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeResponse(b'{"error":"model not found"}\n')

    monkeypatch.setattr("transcriber.assistant.ollama_client.urlopen", fake_urlopen)
    with pytest.raises(OllamaError, match="model not found"):
        OllamaClient().chat("missing:latest", [{"role": "user", "content": "Hi"}])
