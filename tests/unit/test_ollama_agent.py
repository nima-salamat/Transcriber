from __future__ import annotations

import json

import pytest

from transcriber.assistant.action_registry import ActionRegistry, ActionSpec
from transcriber.assistant.agent_protocol import PROTOCOL_ID
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
        thinking_callback = kwargs.get("on_thinking")
        if thinking_callback and response.get("thinking"):
            thinking_callback(response["thinking"])
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


def test_agent_stops_immediately_after_user_denies_an_action():
    call = _call()
    client = FakeOllamaClient([
        {"text": "", "tool_calls": [call], "metrics": {}},
    ])
    executions = []

    def deny(_name, _arguments):
        executions.append("attempted")
        raise PermissionDenied("The user denied this Agent action")

    agent = OllamaAgent(client, deny)
    result = agent.run(
        "qwen2.5:7b",
        [{"role": "user", "content": "Open Notepad"}],
        [{"type": "function", "function": {"name": "desktop.launch_app"}}],
    )

    assert executions == ["attempted"]
    assert result["permission_denied"] is True
    assert "I will not retry" in result["text"]
    assert len(client.calls) == 1
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
    actions.append({"name": "desktop.launch_app", "enabled": True, "destructive": False})
    tools = OllamaAgent.tools_for_registry(FakeRegistry(actions))
    names = {item["function"]["name"] for item in tools}

    # A command tool remains available alongside browser, desktop and Skill tools.
    assert names == {
        "browser.search", "system.run_command", "agent.skill_load", "desktop.launch_app"
    }
    command_tool = next(
        item["function"] for item in tools
        if item["function"]["name"] == "system.run_command"
    )
    assert "PowerShell command" in command_tool["description"]
    assert AgentPermission.BROWSER_CONTROL.value == "browser_control"
    assert AgentPermission.COMMAND_EXECUTION.value == "command_execution"


def test_agent_continues_through_multiple_tool_results_before_final_answer():
    client = FakeOllamaClient([
        {"text": "I will inspect the state.", "tool_calls": [_call("app.get_state", {})], "metrics": {}},
        {"text": "The state is ready; I will now inspect audio.", "tool_calls": [_call("audio.get_status", {})], "metrics": {}},
        {"text": "The audio is ready. Here is the result.", "tool_calls": [], "metrics": {}},
    ])
    executed = []
    agent = OllamaAgent(
        client,
        lambda name, arguments: executed.append((name, arguments)) or {
            "step": len(executed), "action": name
        },
    )

    result = agent.run(
        "qwen2.5:7b",
        [{"role": "user", "content": "Inspect the app and audio, then report."}],
        [{"type": "function", "function": {"name": "app.get_state"}},
         {"type": "function", "function": {"name": "audio.get_status"}}],
    )

    assert [name for name, _args in executed] == ["app.get_state", "audio.get_status"]
    assert result["tool_count"] == 2
    assert result["tool_rounds"] == 2
    assert result["text"] == "The audio is ready. Here is the result."
    assert client.calls[1]["messages"][-1]["role"] == "tool"
    assert client.calls[2]["messages"][-1]["role"] == "tool"


def test_browser_search_request_is_mapped_to_the_real_search_tool():
    request = (
        "Open Chrome/Edge and search for mobile phone prices "
        "using the browser automation skill."
    )

    assert OllamaAgent.is_action_request(request)
    assert OllamaAgent.is_browser_search_request(request)
    assert OllamaAgent.infer_browser_search_tool(
        request, ["browser.search", "browser.open"]
    ) == {
        "name": "browser.search",
        "arguments": {"query": "mobile phone prices", "engine": "google"},
    }
    assert OllamaAgent.infer_browser_search_tool(
        request, ["browser.open"]
    ) is None


def test_browser_search_fallback_executes_when_model_only_narrates():
    client = FakeOllamaClient([
        {"text": "I will open Chrome and search now.", "tool_calls": [], "metrics": {}},
        {"text": "I found the latest search results.", "tool_calls": [], "metrics": {}},
    ])
    executed = []
    chunks = []
    agent = OllamaAgent(
        client,
        lambda name, arguments: executed.append((name, arguments)) or {
            "url": "https://www.google.com/search?q=mobile+phone+prices",
            "title": "Google Search",
            "text": "Mobile phone prices results",
        },
    )

    result = agent.run(
        "qwen2.5:7b",
        [{"role": "user", "content": "Open Chrome and search for mobile phone prices."}],
        [{"type": "function", "function": {"name": "browser.search"}}],
        require_tool_call=True,
        fallback_tool_call={
            "name": "browser.search",
            "arguments": {"query": "mobile phone prices", "engine": "google"},
        },
        on_chunk=chunks.append,
    )

    assert executed == [(
        "browser.search", {"query": "mobile phone prices", "engine": "google"}
    )]
    assert result["tool_count"] == 1
    assert result["cancelled"] is False
    # The false first-turn narration is suppressed; the final answer is shown only
    # after the registered browser action has returned a result.
    assert chunks == ["I found the latest search results."]
    assert client.calls[1]["messages"][-1]["role"] == "tool"
    assert "Mobile phone prices results" in client.calls[1]["messages"][-1]["content"]


def test_action_request_reprompts_model_when_it_omits_tool_call():
    call = {
        "function": {
            "name": "browser.search",
            "arguments": {"query": "mobile phone prices", "engine": "google"},
        }
    }
    client = FakeOllamaClient([
        {"text": "I'll search that now.", "tool_calls": [], "metrics": {}},
        {"text": "", "tool_calls": [call], "metrics": {}},
        {"text": "Here are the results.", "tool_calls": [], "metrics": {}},
    ])
    executed = []
    agent = OllamaAgent(
        client,
        lambda name, args: executed.append((name, args)) or {"ok": True},
    )

    result = agent.run(
        "qwen2.5:7b",
        [{"role": "user", "content": "Open the browser and search for mobile prices."}],
        [{"type": "function", "function": {"name": "browser.search"}}],
        require_tool_call=True,
    )

    assert len(client.calls) == 3
    assert "Your previous message only described an action" in client.calls[1]["messages"][-1]["content"]
    assert len(executed) == 1
    assert result["text"] == "Here are the results."


def test_action_request_never_reports_success_after_two_narration_only_turns():
    client = FakeOllamaClient([
        {"text": "I am opening the browser.", "tool_calls": [], "metrics": {}},
        {"text": "I am searching now.", "tool_calls": [], "metrics": {}},
        {"text": "I can help with that.", "tool_calls": [], "metrics": {}},
    ])
    executed = []
    agent = OllamaAgent(client, lambda name, args: executed.append((name, args)))

    result = agent.run(
        "qwen2.5:7b",
        [{"role": "user", "content": "Open the browser and search for mobile prices."}],
        [{"type": "function", "function": {"name": "browser.search"}}],
        require_tool_call=True,
    )

    assert executed == []
    assert result["action_not_executed"] is True
    assert "No command, desktop, browser or Transcriber action was run" in result["text"]


def test_agent_detects_action_promises_but_not_normal_final_answers():
    assert OllamaAgent.response_promises_action(
        "I'll help you open Chrome and search for mobile phone prices."
    )
    assert OllamaAgent.response_promises_action("Opening the browser now.")
    assert OllamaAgent.response_promises_action("I will now run the command.")
    assert not OllamaAgent.response_promises_action(
        "I found three useful search results and compared the listed prices."
    )
    assert not OllamaAgent.response_promises_action(
        "Here is how to open Chrome from the Start menu."
    )


def test_agent_recovers_when_it_promises_a_second_action_without_calling_it():
    first_call = _call("browser.open", {"url": "https://example.com"})
    second_call = _call("browser.search", {"query": "mobile prices", "engine": "google"})
    client = FakeOllamaClient([
        {"text": "Opening the requested site.", "tool_calls": [first_call], "metrics": {}},
        {"text": "I'll now search for mobile prices.", "tool_calls": [], "metrics": {}},
        {"text": "Here are the mobile prices I found.", "tool_calls": [second_call], "metrics": {}},
        {"text": "I found several results. Here is the summary.", "tool_calls": [], "metrics": {}},
    ])
    executed = []
    agent = OllamaAgent(
        client,
        lambda name, args: executed.append((name, args)) or {"ok": True, "action": name},
    )
    result = agent.run(
        "qwen2.5:7b",
        [{"role": "user", "content": "Open the site, then search for mobile prices."}],
        [{"type": "function", "function": {"name": "browser.open"}},
         {"type": "function", "function": {"name": "browser.search"}}],
        require_tool_call=True,
    )

    assert [name for name, _args in executed] == ["browser.open", "browser.search"]
    assert result["tool_count"] == 2
    assert result["text"] == "I found several results. Here is the summary."
    assert "Your previous response described or promised an action" in client.calls[2]["messages"][-1]["content"]


def test_agent_forwards_live_thinking_chunks_and_supported_level_to_ollama():
    client = FakeOllamaClient([
        {
            "text": "The answer is 42.",
            "thinking": "Check the calculation first.",
            "tool_calls": [],
            "metrics": {},
        }
    ])
    thinking_chunks = []
    answer_chunks = []
    agent = OllamaAgent(client, lambda _name, _args: None)

    result = agent.run(
        "qwen3:8b",
        [{"role": "user", "content": "What is the answer?"}],
        [],
        think="medium",
        on_thinking=thinking_chunks.append,
        on_chunk=answer_chunks.append,
    )

    assert client.calls[0]["think"] == "medium"
    assert thinking_chunks == ["Check the calculation first."]
    assert answer_chunks == ["The answer is 42."]
    assert result["text"] == "The answer is 42."

def test_agent_executes_structured_host_action_then_returns_final_response():
    action_envelope = {
        "protocol": PROTOCOL_ID,
        "status": "continue",
        "response": "I am checking the project directory.",
        "action": {
            "name": "system.run_command",
            "arguments": {"command": "Get-ChildItem", "cwd": "C:/workspace"},
        },
        "done": False,
        "plan": [{"title": "Inspect the project", "status": "running"}],
    }
    final_envelope = {
        "protocol": PROTOCOL_ID,
        "status": "done",
        "response": "The project contains the expected source files.",
        "action": None,
        "done": True,
    }
    client = FakeOllamaClient([
        {"text": json.dumps(action_envelope), "tool_calls": [], "metrics": {}},
        {"text": json.dumps(final_envelope), "tool_calls": [], "metrics": {}},
    ])
    executed = []
    statuses = []
    chunks = []
    agent = OllamaAgent(
        client,
        lambda name, args: executed.append((name, args)) or {
            "exit_code": 0, "stdout": "src\\ntests", "stderr": "", "timed_out": False
        },
    )

    result = agent.run(
        "qwen3:8b",
        [{"role": "user", "content": "Inspect the project directory."}],
        [{"type": "function", "function": {
            "name": "system.run_command",
            "description": "Run PowerShell in the Python host.",
            "parameters": {"type": "object"},
        }}],
        require_tool_call=True,
        on_chunk=chunks.append,
        on_tool_status=statuses.append,
    )

    assert executed == [(
        "system.run_command", {"command": "Get-ChildItem", "cwd": "C:/workspace"}
    )]
    assert result["tool_count"] == 1
    assert result["agent_status"] == "done"
    assert result["text"] == "The project contains the expected source files."
    assert chunks == ["The project contains the expected source files."]
    assert any("I am checking the project directory." in value for value in statuses)
    tool_message = next(item for item in result["messages"] if item.get("role") == "tool")
    assert '"ok":true' in tool_message["content"]
    assert client.calls[1]["messages"][-1]["role"] == "tool"


def test_agent_reports_nonzero_power_shell_exit_code_as_failed_action():
    request = {
        "protocol": PROTOCOL_ID, "status": "continue",
        "response": "Running the test command.",
        "action": {"name": "system.run_command", "arguments": {"command": "pytest"}},
        "done": False,
    }
    final = {
        "protocol": PROTOCOL_ID, "status": "done",
        "response": "The test command failed with exit code 1.",
        "action": None, "done": True,
    }
    results = []
    client = FakeOllamaClient([
        {"text": json.dumps(request), "tool_calls": [], "metrics": {}},
        {"text": json.dumps(final), "tool_calls": [], "metrics": {}},
    ])
    agent = OllamaAgent(
        client,
        lambda _name, _args: {"exit_code": 1, "stdout": "", "stderr": "test failure"},
    )

    result = agent.run(
        "qwen3:8b",
        [{"role": "user", "content": "Run the tests."}],
        [{"type": "function", "function": {"name": "system.run_command"}}],
        require_tool_call=True,
        on_tool_result=results.append,
    )

    assert results and results[0]["ok"] is False
    assert '"ok":false' in next(
        item["content"] for item in result["messages"] if item.get("role") == "tool"
    )
    assert result["text"] == "The test command failed with exit code 1."


def test_agent_stops_after_structured_action_is_denied():
    request = {
        "protocol": PROTOCOL_ID, "status": "continue",
        "response": "Requesting permission to run the command.",
        "action": {"name": "system.run_command", "arguments": {"command": "Remove-Item x"}},
        "done": False,
    }
    client = FakeOllamaClient([
        {"text": json.dumps(request), "tool_calls": [], "metrics": {}},
        {"text": "This must not be requested.", "tool_calls": [], "metrics": {}},
    ])
    executions = []

    def deny(name, args):
        executions.append((name, args))
        raise PermissionDenied("approval denied")

    result = OllamaAgent(client, deny).run(
        "qwen3:8b",
        [{"role": "user", "content": "Run a command."}],
        [{"type": "function", "function": {"name": "system.run_command"}}],
        require_tool_call=True,
    )

    assert len(client.calls) == 1
    assert len(executions) == 1
    assert result["permission_denied"] is True


def test_action_request_recognizes_common_persian_execution_phrases():
    assert OllamaAgent.is_action_request("میخوام این پوشه رو بررسی کنی")
    assert OllamaAgent.is_action_request("لطفاً این دستور رو اجرا کن")
    assert OllamaAgent.is_action_request("می‌خوام برنامه رو باز کنی")
    assert not OllamaAgent.is_action_request("چگونه می‌توانم PowerShell را باز کنم؟")


def test_action_request_recognizes_general_powershell_and_terminal_tasks():
    assert OllamaAgent.is_action_request("Run this PowerShell command: Get-ChildItem")
    assert OllamaAgent.is_action_request("Please use PowerShell to list the files.")
    assert OllamaAgent.is_action_request("این دستور را در PowerShell اجرا کن")
    assert OllamaAgent.is_action_request("پاورشل رو اجرا کن")
    assert not OllamaAgent.is_action_request("How do I use PowerShell to list files?")

def test_action_request_recognizes_common_inspection_and_development_tasks():
    assert OllamaAgent.is_action_request("Please inspect the repository structure.")
    assert OllamaAgent.is_action_request("Check whether the tests pass.")
    assert OllamaAgent.is_action_request("Build the project.")
    assert OllamaAgent.is_action_request("Review the latest log file.")
    assert not OllamaAgent.is_action_request("How do I check the project structure?")



def test_power_shell_tool_exposure_tracks_the_user_command_execution_permission():
    registry = ActionRegistry(permissions={AgentPermission.READ_ONLY})
    registry.register(ActionSpec(
        name="system.run_command",
        description="General-purpose PowerShell command executor.",
        permission=AgentPermission.COMMAND_EXECUTION,
        handler=lambda arguments: {"exit_code": 0},
        required=("command",),
        requires_approval=True,
        background=True,
    ))

    assert "system.run_command" not in {
        item["function"]["name"] for item in OllamaAgent.tools_for_registry(registry)
    }

    # Toggling the real app permission immediately changes the tools sent to Ollama.
    registry.set_permission(AgentPermission.COMMAND_EXECUTION, True)
    tools = OllamaAgent.tools_for_registry(registry)
    command_tool = next(
        item["function"] for item in tools
        if item["function"]["name"] == "system.run_command"
    )

    assert command_tool["parameters"]["properties"]["command"]["maxLength"] == 16000
    assert command_tool["parameters"]["properties"]["timeout_seconds"]["maximum"] == 3600
    assert "general-purpose PowerShell" in command_tool["description"]
    assert "browser" in command_tool["description"].casefold()
    assert registry.describe(include_disabled=False)[0]["requires_approval"] is True
