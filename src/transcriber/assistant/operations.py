"""Bounded asynchronous execution and lifecycle tracking for Agent actions.

The operation ledger is intentionally process-local. It provides idempotent
submission and observable execution state while the desktop app is running;
it is not a durable job queue and does not claim to interrupt a handler that
has already started.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from dataclasses import dataclass, field as dataclass_field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class OperationState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


_TERMINAL_STATES = {
    OperationState.COMPLETED,
    OperationState.FAILED,
    OperationState.CANCELLED,
    OperationState.TIMED_OUT,
}
_SECRET_PATTERNS = (
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1[redacted]"),
    (re.compile(r"(?i)(access[_-]?token|refresh[_-]?token|api[_-]?key)(\s*[:=]\s*)[^\s,;]+"), r"\1\2[redacted]"),
)


@dataclass(slots=True)
class _Operation:
    operation_id: str
    request_id: str | None
    action: str
    arguments: dict[str, Any]
    idempotency_key: str
    fingerprint: str
    deadline_seconds: int
    created_at: str
    created_monotonic: float
    state: OperationState = OperationState.QUEUED
    updated_at: str = ""
    cancellation_requested: bool = False
    deadline_expired: bool = False
    result: Any = None
    error: str | None = None
    future: Future | None = None
    timer: threading.Timer | None = None
    cancel_event: threading.Event = dataclass_field(default_factory=threading.Event)


class OperationManager:
    """Run semantic actions off-thread with bounded admission and deduplication."""

    def __init__(
        self,
        action_handler: Callable[[str, dict[str, Any]], Any],
        *,
        max_workers: int = 4,
        max_outstanding: int = 128,
        history_limit: int = 512,
        cancellable_action_handler: Callable[[str, dict[str, Any], threading.Event], Any] | None = None,
    ) -> None:
        if not callable(action_handler):
            raise TypeError("action_handler must be callable")
        if cancellable_action_handler is not None and not callable(cancellable_action_handler):
            raise TypeError("cancellable_action_handler must be callable")
        self._handler = action_handler
        self._cancellable_handler = cancellable_action_handler
        self._max_outstanding = max(1, min(int(max_outstanding), 1024))
        self._history_limit = max(16, min(int(history_limit), 4096))
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, min(int(max_workers), 8)),
            thread_name_prefix="Transcriber-agent",
        )
        self._lock = threading.RLock()
        self._operations: dict[str, _Operation] = {}
        self._idempotency: dict[str, str] = {}
        self._closed = False

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(UTC).isoformat(timespec="milliseconds")

    @staticmethod
    def _validate_arguments(arguments: Any) -> dict[str, Any]:
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise ValueError("Action arguments must be a JSON object")
        try:
            raw = json.dumps(
                arguments, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Action arguments must contain JSON-compatible values") from exc
        if len(raw.encode("utf-8")) > 65_536:
            raise ValueError("Action arguments exceed the 64 KiB limit")

        def check_depth(value: Any, depth: int = 0) -> None:
            if depth > 8:
                raise ValueError("Action arguments exceed the maximum nesting depth")
            if isinstance(value, str) and len(value) > 16_384:
                raise ValueError("An action argument string exceeds the 16 KiB limit")
            if isinstance(value, dict):
                if len(value) > 128:
                    raise ValueError("An action argument object has too many keys")
                for key, item in value.items():
                    if not isinstance(key, str):
                        raise ValueError("Action argument object keys must be strings")
                    check_depth(key, depth + 1)
                    check_depth(item, depth + 1)
            elif isinstance(value, list):
                if len(value) > 256:
                    raise ValueError("An action argument array has too many items")
                for item in value:
                    check_depth(item, depth + 1)

        check_depth(arguments)
        # Copy through JSON so callers cannot mutate an accepted operation.
        return json.loads(raw)

    @staticmethod
    def _error_message(exc: BaseException) -> str:
        message = f"{type(exc).__name__}: {exc}"
        for pattern, replacement in _SECRET_PATTERNS:
            message = pattern.sub(replacement, message)
        return message[:1000]

    def _snapshot(self, item: _Operation) -> dict[str, Any]:
        snapshot: dict[str, Any] = {
            "operation_id": item.operation_id,
            "request_id": item.request_id,
            "action": item.action,
            "state": item.state.value,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "deadline_seconds": item.deadline_seconds,
            "cancellation_requested": item.cancellation_requested,
            "deadline_expired": item.deadline_expired,
        }
        if item.state == OperationState.COMPLETED or item.result is not None:
            snapshot["result"] = item.result
        if item.error:
            snapshot["error"] = item.error
        return snapshot

    def submit(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        request_id: str | None = None,
        idempotency_key: str | None = None,
        deadline_seconds: int = 120,
    ) -> dict[str, Any]:
        action = str(name).strip()
        if not action or len(action) > 128:
            raise ValueError("A valid action name is required")
        args = self._validate_arguments(arguments)
        if isinstance(deadline_seconds, bool) or not isinstance(deadline_seconds, int):
            raise ValueError("deadline_seconds must be an integer")
        if not 1 <= deadline_seconds <= 3600:
            raise ValueError("deadline_seconds must be between 1 and 3600")

        key = idempotency_key.strip() if isinstance(idempotency_key, str) else ""
        if not key and isinstance(request_id, str):
            key = request_id.strip()
        if not 8 <= len(key) <= 128:
            raise ValueError("An idempotency_key between 8 and 128 characters is required")

        encoded = json.dumps(
            {"action": action, "arguments": args},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        )
        fingerprint = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        now = time.monotonic()
        stamp = self._timestamp()

        with self._lock:
            if self._closed:
                raise RuntimeError("Operation manager is shutting down")
            existing_id = self._idempotency.get(key)
            if existing_id:
                existing = self._operations.get(existing_id)
                if existing is not None:
                    if existing.fingerprint != fingerprint:
                        raise ValueError("The idempotency_key was already used for a different action")
                    return self._snapshot(existing)

            active_count = sum(
                item.state not in _TERMINAL_STATES for item in self._operations.values()
            )
            if active_count >= self._max_outstanding:
                raise RuntimeError("The Agent operation queue is full; retry after an operation finishes")

            operation_id = uuid.uuid4().hex
            item = _Operation(
                operation_id=operation_id,
                request_id=request_id if isinstance(request_id, str) else None,
                action=action,
                arguments=args,
                idempotency_key=key,
                fingerprint=fingerprint,
                deadline_seconds=deadline_seconds,
                created_at=stamp,
                created_monotonic=now,
                updated_at=stamp,
            )
            self._operations[operation_id] = item
            self._idempotency[key] = operation_id
            try:
                item.future = self._executor.submit(self._run, operation_id)
                item.timer = threading.Timer(
                    deadline_seconds, self._expire, args=(operation_id,)
                )
                item.timer.daemon = True
                item.timer.start()
                item.future.add_done_callback(
                    lambda future, op_id=operation_id: self._finish(op_id, future)
                )
            except Exception:
                self._operations.pop(operation_id, None)
                self._idempotency.pop(key, None)
                raise
            self._trim_history_locked()
            return self._snapshot(item)

    def _run(self, operation_id: str) -> Any:
        with self._lock:
            item = self._operations.get(operation_id)
            if item is None or item.cancellation_requested or item.deadline_expired:
                raise CancelledError("Operation cancelled before execution")
            item.state = OperationState.RUNNING
            item.updated_at = self._timestamp()
            action, arguments = item.action, dict(item.arguments)
            cancel_event = item.cancel_event
        if self._cancellable_handler is not None:
            return self._cancellable_handler(action, arguments, cancel_event)
        return self._handler(action, arguments)

    def _finish(self, operation_id: str, future: Future) -> None:
        with self._lock:
            item = self._operations.get(operation_id)
            if item is None:
                return
            if item.timer is not None:
                item.timer.cancel()
                item.timer = None

            if future.cancelled():
                item.state = (
                    OperationState.TIMED_OUT if item.deadline_expired
                    else OperationState.CANCELLED
                )
                item.error = "Deadline elapsed before execution" if item.deadline_expired else None
            else:
                try:
                    result = future.result()
                    encoded = json.dumps(
                        result, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                    )
                    if len(encoded.encode("utf-8")) > 262_144:
                        raise ValueError("Action result exceeds the 256 KiB response limit")
                    item.result = json.loads(encoded)
                    if item.deadline_expired:
                        item.state = OperationState.TIMED_OUT
                        item.error = "Deadline elapsed; the running handler finished after the deadline"
                    else:
                        # A running handler cannot safely be killed. Report its actual
                        # outcome while preserving cancellation_requested for the caller.
                        item.state = OperationState.COMPLETED
                except CancelledError as exc:
                    item.state = (
                        OperationState.TIMED_OUT if item.deadline_expired
                        else OperationState.CANCELLED
                    )
                    item.error = self._error_message(exc) if item.deadline_expired else None
                except BaseException as exc:
                    item.state = OperationState.TIMED_OUT if item.deadline_expired else OperationState.FAILED
                    item.error = self._error_message(exc)
            item.updated_at = self._timestamp()
            self._trim_history_locked()

    def _expire(self, operation_id: str) -> None:
        with self._lock:
            item = self._operations.get(operation_id)
            if item is None or item.state in _TERMINAL_STATES:
                return
            # Avoid a false timeout when the handler has finished but its
            # completion callback is waiting to acquire this lock.
            if item.future is not None and item.future.done():
                return
            item.deadline_expired = True
            item.cancellation_requested = True
            item.cancel_event.set()
            if item.future is not None and item.future.cancel():
                item.state = OperationState.TIMED_OUT
                item.error = "Deadline elapsed before execution"
            else:
                item.state = OperationState.CANCELLING
            item.updated_at = self._timestamp()

    def get(self, operation_id: str) -> dict[str, Any]:
        with self._lock:
            item = self._operations.get(str(operation_id))
            if item is None:
                raise KeyError(f"Unknown operation: {operation_id}")
            return self._snapshot(item)

    def cancel(self, operation_id: str) -> dict[str, Any]:
        with self._lock:
            item = self._operations.get(str(operation_id))
            if item is None:
                raise KeyError(f"Unknown operation: {operation_id}")
            if item.state in _TERMINAL_STATES:
                return self._snapshot(item)
            item.cancellation_requested = True
            item.cancel_event.set()
            if item.future is not None and item.future.cancel():
                item.state = OperationState.CANCELLED
                item.error = None
                if item.timer is not None:
                    item.timer.cancel()
                    item.timer = None
            else:
                # Cancellation is cooperative once the action handler starts.
                item.state = OperationState.CANCELLING
            item.updated_at = self._timestamp()
            return self._snapshot(item)

    def list(self, *, limit: int = 50) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer")
        limit = max(1, min(limit, 200))
        with self._lock:
            items = sorted(
                self._operations.values(),
                key=lambda item: item.created_monotonic,
                reverse=True,
            )[:limit]
            return [self._snapshot(item) for item in items]

    def _trim_history_locked(self) -> None:
        if len(self._operations) <= self._history_limit:
            return
        removable = sorted(
            (item for item in self._operations.values() if item.state in _TERMINAL_STATES),
            key=lambda item: item.created_monotonic,
        )
        while len(self._operations) > self._history_limit and removable:
            item = removable.pop(0)
            self._operations.pop(item.operation_id, None)
            if self._idempotency.get(item.idempotency_key) == item.operation_id:
                self._idempotency.pop(item.idempotency_key, None)

    @property
    def is_idle(self) -> bool:
        """True only when every accepted operation future has actually finished."""
        with self._lock:
            return all(
                item.future is None or item.future.done()
                for item in self._operations.values()
            )

    def shutdown(self, *, wait: bool = False) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for item in self._operations.values():
                if item.timer is not None:
                    item.timer.cancel()
                    item.timer = None
                if item.state not in _TERMINAL_STATES:
                    item.cancellation_requested = True
                    item.cancel_event.set()
                    if item.future is not None and item.future.cancel():
                        item.state = OperationState.CANCELLED
                    else:
                        item.state = OperationState.CANCELLING
                    item.updated_at = self._timestamp()
        self._executor.shutdown(wait=wait, cancel_futures=True)
