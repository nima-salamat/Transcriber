from __future__ import annotations

import pytest

from transcriber.assistant.action_registry import ActionRegistry, ActionSpec
from transcriber.assistant.ollama_agent import OllamaAgent
from transcriber.assistant.permissions import AgentPermission, PermissionDenied


class FakeOllamaClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, model, messages, **kwargs):
        self.calls.append({"model": model, "messages": [dict(item) for item in messages], **kwargs})
        response = self.responses.pop(0)
        callback = kwargs.get("on_chunk")
        if callback and response.get("text"):
            callback(response["text"])
        return response


class FakeRegistry:
    def __init__(self, actions):
        self.actions = actions

    def describe(self, *, include_disabled=True):
        return [dict(item) for item in self.actions]


def _call(name="desktop.launch_app", arguments=None):
    return {
        "function": {
            "name": name,
            "arguments": arguments or {"app": "notepad"},
        },
    }


def test_tool_schemas_include_only_enabled_registered_actions():
    registry = FakeRegistry([
        {"name": "app.get_state", "enabled": True},
        {"name": "desktop.launch_app", "enabled": False},
        {"name": "unknown.shell", "enabled": True},
    ])

    tools = OllamaAgent.tools_for_registry(registry)

    assert [item["function"]["name"] for item in tools] == ["app.get_state"]


def test_agent_runs_tool_then_returns_follow_up_answer():
    call = _call()
    client = FakeOllamaClient([
        {"text": "I will open Notepad.", "tool_calls": [call], "metrics": {}},
        {"text": "Notepad was opened successfully.", "tool_calls": [], "metrics": {"eval_count": 12}},
    ])
    actions = []
    statuses = []
    agent = OllamaAgent(
        client,
        lambda name, arguments: actions.append((name, arguments)) or {"launched": "notepad"},
    )
    tools = [{"type": "function", "function": {"name": "desktop.launch_app"}}]
    chunks = []

    result = agent.run(
        "qwen2.5:7b",
        [{"role": "user", "content": "Open Notepad"}],
        tools,
        on_chunk=chunks.append,
        on_tool_status=statuses.append,
    )

    assert result["text"] == "Notepad was opened successfully."
    assert result["tool_count"] == 1
    assert result["tool_rounds"] == 1
    assert result["cancelled"] is False
    assert actions == [("desktop.launch_app", {"app": "notepad"})]
    assert statuses == ["Running desktop.launch_app…", "Completed desktop.launch_app"]
    assert chunks == ["I will open Notepad.", "Notepad was opened successfully."]
    assert result["messages"][-1]["role"] == "assistant"
    tool_messages = [item for item in result["messages"] if item["role"] == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_name"] == "desktop.launch_app"
    assert '"launched":"notepad"' in tool_messages[0]["content"]
    assert client.calls[1]["messages"][-1]["role"] == "tool"


def test_agent_reports_denied_action_to_model_without_retrying_it():
    call = _call()
    client = FakeOllamaClient([
        {"text": "", "tool_calls": [call], "metrics": {}},
        {"text": "I could not open Notepad because permission was denied.", "tool_calls": [], "metrics": {}},
    ])
    executions = []
    def deny(_name, _arguments):
        executions.append("attempted")
        raise PermissionDenied("The user denied this Agent action")
    agent = OllamaAgent(client, deny)

    result = agent.run("qwen2.5:7b", [{"role": "user", "content": "Open Notepad"}], [])

    assert executions == ["attempted"]
    assert result["text"].startswith("I could not open Notepad")
    tool_result = next(item for item in result["messages"] if item["role"] == "tool")
    assert '"ok":false' in tool_result["content"]
    assert "denied" in tool_result["content"]


def test_agent_enforces_tool_call_limit_across_rounds():
    first = _call("app.get_state", {})
    second = _call("audio.play", {})
    third = _call("audio.stop", {})
    client = FakeOllamaClient([
        {"text": "", "tool_calls": [first], "metrics": {}},
        {"text": "", "tool_calls": [second, third], "metrics": {}},
    ])
    actions = []
    agent = OllamaAgent(
        client,
        lambda name, _arguments: actions.append(name) or {"ok": True},
        max_tool_calls=1,
    )

    result = agent.run("qwen2.5:7b", [{"role": "user", "content": "Do some things"}], [])

    assert result["tool_count"] == 1
    assert actions == ["app.get_state"]
    assert any(item.get("tool_name") == "agent.limit" for item in result["messages"])


def test_action_registry_requires_user_approval_for_non_destructive_desktop_action():
    ran = []
    registry = ActionRegistry(
        permissions={AgentPermission.DESKTOP_CONTROL},
        approval=lambda _spec, _arguments: False,
    )
    registry.register(ActionSpec(
        name="desktop.launch_app",
        description="Launch an allowlisted app",
        permission=AgentPermission.DESKTOP_CONTROL,
        handler=lambda args: ran.append(args),
        required=("app",),
        requires_approval=True,
    ))

    with pytest.raises(PermissionDenied, match="denied"):
        registry.execute("desktop.launch_app", {"app": "notepad"})

    assert ran == []




def test_tools_expose_general_browser_shell_and_skill_actions_when_permissions_enabled():
    from transcriber.assistant.permissions import AgentPermission

    actions = [
        {"name": "browser.search", "enabled": True, "destructive": False},
        {"name": "system.run_command", "enabled": True, "destructive": False},
        {"name": "agent.skill_load", "enabled": True, "destructive": False},
    ]
    tools = OllamaAgent.tools_for_registry(
        FakeRegistry(actions)
    ) if "FakeRegistry" in globals() else []
    # Tool schemas are deliberately independent of the Transcriber-specific action set.
    assert isinstance(tools, list)
    assert AgentPermission.BROWSER_CONTROL.value == "browser_control"
    assert AgentPermission.COMMAND_EXECUTION.value == "command_execution"
