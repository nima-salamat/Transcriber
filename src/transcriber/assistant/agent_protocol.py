"""Strict, versioned control messages exchanged between the Ollama model and the Python host.

The model is a planner. It may request one registered action at a time; only the
application's Python ActionRegistry validates permissions and executes it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

PROTOCOL_ID = "transcriber.agent.v1"
_STATUSES = frozenset({"continue", "done", "blocked", "needs_input"})


@dataclass(frozen=True, slots=True)
class AgentDecision:
    status: str
    response: str
    action: dict[str, Any] | None
    done: bool
    plan: tuple[dict[str, str], ...] = ()


def parse_agent_decision(content: str) -> AgentDecision | None:
    """Parse a host-control envelope; never treat arbitrary prose as an action."""
    source = str(content or "").strip()
    if not source:
        return None
    fenced = re.search(r"\x60\x60\x60(?:json)?\s*(.*?)\s*\x60\x60\x60", source, re.I | re.S)
    candidates = [fenced.group(1).strip()] if fenced else []
    candidates.append(source)
    decoder = json.JSONDecoder()
    payload = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                payload = parsed
                break
        except (TypeError, json.JSONDecodeError):
            pass
        for match in re.finditer(r"\{", candidate):
            try:
                parsed, _end = decoder.raw_decode(candidate[match.start():])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and parsed.get("protocol") == PROTOCOL_ID:
                payload = parsed
                break
        if payload is not None:
            break
    if not isinstance(payload, dict) or payload.get("protocol") != PROTOCOL_ID:
        return None

    status, done, response, action = (
        payload.get("status"), payload.get("done"),
        payload.get("response"), payload.get("action"),
    )
    if status not in _STATUSES or not isinstance(done, bool) or not isinstance(response, str):
        return None

    normalized_action = None
    if status == "continue":
        if done or not isinstance(action, dict):
            return None
        name, arguments = action.get("name"), action.get("arguments")
        if not isinstance(name, str) or not name.strip() or not isinstance(arguments, dict):
            return None
        normalized_action = {"name": name.strip(), "arguments": arguments}
    else:
        expected_done = status in {"done", "blocked"}
        if done is not expected_done or action is not None or not response.strip():
            return None

    plan = []
    raw_plan = payload.get("plan", [])
    if isinstance(raw_plan, list):
        for item in raw_plan[:24]:
            if isinstance(item, str) and item.strip():
                plan.append({"title": item.strip()[:240], "status": "pending"})
            elif isinstance(item, dict):
                title, state = item.get("title"), item.get("status", "pending")
                if isinstance(title, str) and title.strip() and isinstance(state, str):
                    plan.append({"title": title.strip()[:240], "status": state.strip()[:32] or "pending"})
    return AgentDecision(status, response.strip(), normalized_action, done, tuple(plan))
