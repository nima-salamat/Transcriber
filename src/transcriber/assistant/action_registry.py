"""Semantic application actions exposed to GUI, MCP and voice agents.

Only explicitly registered callables are invocable. This module never resolves
arbitrary attribute paths, shell commands, Python expressions or Qt widgets.
"""

from __future__ import annotations

import threading
from concurrent.futures import CancelledError
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from transcriber.assistant.permissions import DEFAULT_PERMISSIONS, AgentPermission, PermissionDenied


def _direct_dispatch(handler, arguments, cancel_event=None):
    if cancel_event is not None and cancel_event.is_set():
        raise CancelledError("Action cancelled before dispatch.")
    return handler(arguments)


@dataclass(frozen=True, slots=True)
class ActionSpec:
    name: str
    description: str
    permission: AgentPermission
    handler: Callable[[dict[str, Any]], Any] = field(compare=False, repr=False)
    required: tuple[str, ...] = ()
    destructive: bool = False
    requires_approval: bool = False
    background: bool = False
    cancellation_handler: Callable[[dict[str, Any], threading.Event], Any] | None = field(
        default=None, compare=False, repr=False
    )

    def public_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "permission": self.permission.value,
            "required": list(self.required),
            "destructive": self.destructive,
            "requires_approval": self.requires_approval,
            "background": self.background,
        }


class ActionRegistry:
    def __init__(
        self,
        *,
        permissions: set[AgentPermission] | frozenset[AgentPermission] | None = None,
        dispatcher: Callable[[Callable, dict[str, Any]], Any] | None = None,
        approval: Callable[[ActionSpec, dict[str, Any]], bool] | None = None,
        approval_dispatcher: Callable[[Callable, dict[str, Any]], Any] | None = None,
    ):
        self.permissions = set(DEFAULT_PERMISSIONS if permissions is None else permissions)
        self.dispatcher = dispatcher or _direct_dispatch
        self.approval_dispatcher = approval_dispatcher or self.dispatcher
        self.approval = approval
        self._actions: dict[str, ActionSpec] = {}
        self._lock = threading.RLock()

    def register(self, spec: ActionSpec) -> None:
        with self._lock:
            if spec.name in self._actions:
                raise ValueError(f"Action is already registered: {spec.name}")
            self._actions[spec.name] = spec

    def describe(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        with self._lock:
            values = list(self._actions.values())
        result = []
        for item in values:
            row = item.public_schema()
            row["enabled"] = item.permission in self.permissions
            if include_disabled or row["enabled"]:
                result.append(row)
        return result

    def execute(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        cancellation=None,
    ) -> Any:
        args = dict(arguments or {})
        cancel_event = (
            getattr(cancellation, "event", None)
            if cancellation is not None else None
        )
        if cancel_event is None and callable(getattr(cancellation, "is_set", None)):
            cancel_event = cancellation

        def ensure_active():
            cancelled = bool(getattr(cancellation, "cancelled", False))
            if cancelled or (cancel_event is not None and cancel_event.is_set()):
                raise CancelledError("Agent action was cancelled before completion.")

        ensure_active()
        with self._lock:
            spec = self._actions.get(name)
        if spec is None:
            raise KeyError(f"Unknown action: {name}")
        if spec.permission not in self.permissions:
            raise PermissionDenied(f"Agent permission is disabled: {spec.permission.value}")
        missing = [field for field in spec.required if field not in args]
        if missing:
            raise ValueError(f"Missing required arguments: {', '.join(missing)}")
        if spec.destructive and AgentPermission.DESTRUCTIVE_ACTIONS not in self.permissions:
            raise PermissionDenied("Destructive Agent permission is disabled")
        if spec.destructive or spec.requires_approval:
            if self.approval is None:
                raise PermissionDenied("This operation requires explicit user approval")
            approval_callback = lambda payload: self.approval(payload[0], payload[1])
            if cancel_event is None:
                approved = self.approval_dispatcher(approval_callback, (spec, args))
            else:
                approved = self.approval_dispatcher(
                    approval_callback, (spec, args), cancel_event
                )
            ensure_active()
            if not approved:
                raise PermissionDenied("The user denied this Agent action")
        # I/O-bound tools run on the caller's worker thread. Qt/domain handlers
        # still use the GUI dispatcher so they never touch widgets off-thread.
        ensure_active()
        if spec.background:
            if cancel_event is not None and spec.cancellation_handler is not None:
                result = spec.cancellation_handler(args, cancel_event)
            else:
                result = spec.handler(args)
        elif cancel_event is not None:
            result = self.dispatcher(spec.handler, args, cancel_event)
        else:
            result = self.dispatcher(spec.handler, args)
        ensure_active()
        return result

    def set_permission(self, permission: AgentPermission, enabled: bool) -> None:
        if permission == AgentPermission.READ_ONLY and not enabled:
            self.permissions.discard(permission)
            return
        if enabled:
            self.permissions.add(permission)
        else:
            self.permissions.discard(permission)
