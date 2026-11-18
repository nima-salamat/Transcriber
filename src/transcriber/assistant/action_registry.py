"""Semantic application actions exposed to GUI, MCP and voice agents.

Only explicitly registered callables are invocable. This module never resolves
arbitrary attribute paths, shell commands, Python expressions or Qt widgets.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from transcriber.assistant.permissions import DEFAULT_PERMISSIONS, AgentPermission, PermissionDenied


@dataclass(frozen=True, slots=True)
class ActionSpec:
    name: str
    description: str
    permission: AgentPermission
    handler: Callable[[dict[str, Any]], Any] = field(compare=False, repr=False)
    required: tuple[str, ...] = ()
    destructive: bool = False
    requires_approval: bool = False

    def public_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "permission": self.permission.value,
            "required": list(self.required),
            "destructive": self.destructive,
            "requires_approval": self.requires_approval,
        }


class ActionRegistry:
    def __init__(
        self,
        *,
        permissions: set[AgentPermission] | frozenset[AgentPermission] | None = None,
        dispatcher: Callable[[Callable, dict[str, Any]], Any] | None = None,
        approval: Callable[[ActionSpec, dict[str, Any]], bool] | None = None,
    ):
        self.permissions = set(DEFAULT_PERMISSIONS if permissions is None else permissions)
        self.dispatcher = dispatcher or (lambda handler, arguments: handler(arguments))
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

    def execute(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        args = dict(arguments or {})
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
            approved = self.dispatcher(
                lambda payload: self.approval(payload[0], payload[1]),
                (spec, args),
            )
            if not approved:
                raise PermissionDenied("The user denied this Agent action")
        return self.dispatcher(spec.handler, args)

    def set_permission(self, permission: AgentPermission, enabled: bool) -> None:
        if permission == AgentPermission.READ_ONLY and not enabled:
            self.permissions.discard(permission)
            return
        if enabled:
            self.permissions.add(permission)
        else:
            self.permissions.discard(permission)
