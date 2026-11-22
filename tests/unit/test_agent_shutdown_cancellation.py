"""Cancellation propagation for long-running Agent operations during app shutdown."""
from __future__ import annotations

import threading
import time
from concurrent.futures import CancelledError

from transcriber.assistant.operations import OperationManager


def _wait_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


def test_operation_cancel_propagates_to_the_running_action_handler():
    started = threading.Event()
    observed_cancel = threading.Event()

    def execute(_name, _arguments, cancel_event):
        started.set()
        if cancel_event.wait(timeout=3):
            observed_cancel.set()
            raise CancelledError("The running Agent action received cancellation.")
        return {"ok": True}

    manager = OperationManager(
        lambda _name, _arguments: {"ok": True},
        cancellable_action_handler=execute,
    )
    try:
        snapshot = manager.submit(
            "browser.search",
            {"query": "example"},
            idempotency_key="shutdown-cancel-001",
            deadline_seconds=30,
        )
        operation_id = snapshot["operation_id"]
        assert started.wait(2)

        cancelling = manager.cancel(operation_id)
        assert cancelling["cancellation_requested"] is True
        assert observed_cancel.wait(2)
        assert _wait_until(
            lambda: manager.get(operation_id)["state"] == "cancelled"
        )

        completed = manager.get(operation_id)
        assert completed["state"] == "cancelled"
        assert completed["cancellation_requested"] is True
    finally:
        manager.shutdown(wait=True)


def test_operation_manager_shutdown_signals_every_running_handler():
    started = threading.Event()
    observed_cancel = threading.Event()

    def execute(_name, _arguments, cancel_event):
        started.set()
        if cancel_event.wait(timeout=3):
            observed_cancel.set()
            raise CancelledError("Application shutdown cancelled the operation.")
        return None

    manager = OperationManager(
        lambda _name, _arguments: None,
        cancellable_action_handler=execute,
    )
    snapshot = manager.submit(
        "desktop.inspect",
        {},
        idempotency_key="shutdown-cancel-002",
        deadline_seconds=30,
    )
    assert started.wait(2)

    manager.shutdown(wait=False)

    assert observed_cancel.wait(2)
    assert _wait_until(
        lambda: manager.get(snapshot["operation_id"])["state"] == "cancelled"
    )
    assert manager.is_idle


def test_background_action_uses_its_cancellation_aware_handler():
    from threading import Event

    from transcriber.assistant.action_registry import ActionRegistry, ActionSpec
    from transcriber.assistant.permissions import AgentPermission

    observed = []
    registry = ActionRegistry(permissions={AgentPermission.READ_ONLY})
    registry.register(ActionSpec(
        name="system.run_command",
        description="A cancellable background command.",
        permission=AgentPermission.READ_ONLY,
        handler=lambda _args: (_ for _ in ()).throw(
            AssertionError("the non-cancellable handler must not run")
        ),
        background=True,
        cancellation_handler=lambda args, event: observed.append(
            (dict(args), event.is_set())
        ) or {"cancelled": event.is_set()},
    ))
    token = Event()

    result = registry.execute(
        "system.run_command", {"command": "echo ready"}, cancellation=token
    )

    assert observed == [({"command": "echo ready"}, False)]
    assert result == {"cancelled": False}
