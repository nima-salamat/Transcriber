from __future__ import annotations

from concurrent.futures import Future

from transcriber.ui.main_window import MainThreadDispatcher
from transcriber.ui.components.assistant_panel import AssistantPanel


def test_cancelled_queued_dispatch_never_runs_handler():
    future = Future()
    assert future.cancel()
    called = []

    MainThreadDispatcher._execute(lambda _args: called.append(True), {}, future)

    assert called == []
    assert future.cancelled()


def test_dispatch_transitions_future_to_running_before_result():
    future = Future()
    MainThreadDispatcher._execute(lambda payload: payload["value"] + 1, {"value": 2}, future)

    assert future.running()
    assert future.result() == 3


def test_dispatch_propagates_handler_errors_without_invalid_future_state():
    future = Future()

    def fail(_payload):
        raise ValueError("invalid operation")

    MainThreadDispatcher._execute(fail, {}, future)

    try:
        future.result()
    except ValueError as exc:
        assert str(exc) == "invalid operation"
    else:
        raise AssertionError("The dispatcher must propagate handler errors")


def test_mcp_child_environment_excludes_secrets():
    environment = AssistantPanel._mcp_child_environment({
        "PATH": "/safe/bin",
        "SystemRoot": "C:\\Windows",
        "HF_TOKEN": "hf-secret",
        "HUGGINGFACE_HUB_TOKEN": "hub-secret",
        "OPENAI_API_KEY": "openai-secret",
        "TRANSCRIBER_IPC_TOKEN": "ipc-secret",
    })

    assert environment == {"PATH": "/safe/bin", "SystemRoot": "C:\\Windows"}
    assert not any("TOKEN" in key.upper() or "KEY" in key.upper() for key in environment)
