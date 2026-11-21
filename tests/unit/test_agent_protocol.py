from __future__ import annotations

import json

from transcriber.assistant.agent_protocol import PROTOCOL_ID, parse_agent_decision


def _envelope(**overrides):
    value = {
        "protocol": PROTOCOL_ID,
        "status": "continue",
        "response": "Inspecting the workspace.",
        "action": {
            "name": "system.run_command",
            "arguments": {"command": "Get-ChildItem", "timeout_seconds": 20},
        },
        "done": False,
        "plan": [{"title": "Inspect files", "status": "running"}],
    }
    value.update(overrides)
    return value


def test_parse_agent_continue_envelope_and_plan():
    decision = parse_agent_decision(json.dumps(_envelope()))

    assert decision is not None
    assert decision.status == "continue"
    assert decision.done is False
    assert decision.response == "Inspecting the workspace."
    assert decision.action == {
        "name": "system.run_command",
        "arguments": {"command": "Get-ChildItem", "timeout_seconds": 20},
    }
    assert decision.plan == ({"title": "Inspect files", "status": "running"},)


def test_parse_agent_envelope_with_markdown_fence_and_surrounding_text():
    raw = "The next host action is:\n```json\n" + json.dumps(_envelope()) + "\n```"
    decision = parse_agent_decision(raw)

    assert decision is not None
    assert decision.action["name"] == "system.run_command"


def test_parse_agent_final_envelope():
    decision = parse_agent_decision(json.dumps({
        "protocol": PROTOCOL_ID,
        "status": "done",
        "response": "The requested work was verified.",
        "action": None,
        "done": True,
    }))

    assert decision is not None
    assert decision.status == "done"
    assert decision.done is True
    assert decision.action is None


def test_parse_agent_waiting_and_blocked_states():
    needs_input = parse_agent_decision(json.dumps({
        "protocol": PROTOCOL_ID, "status": "needs_input",
        "response": "Which project folder should I use?",
        "action": None, "done": False,
    }))
    blocked = parse_agent_decision(json.dumps({
        "protocol": PROTOCOL_ID, "status": "blocked",
        "response": "Command execution permission is disabled.",
        "action": None, "done": True,
    }))

    assert needs_input and needs_input.done is False
    assert blocked and blocked.done is True


def test_parser_rejects_invalid_or_ambiguous_control_messages():
    assert parse_agent_decision("I'll run the command now.") is None
    assert parse_agent_decision(json.dumps(_envelope(protocol="other"))) is None
    assert parse_agent_decision(json.dumps(_envelope(done=True))) is None
    assert parse_agent_decision(json.dumps(_envelope(action={
        "name": "system.run_command", "arguments": "not-an-object"
    }))) is None
    assert parse_agent_decision(json.dumps(_envelope(status="unknown"))) is None
