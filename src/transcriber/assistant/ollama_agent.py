"""Bounded Ollama tool-calling loop using Transcriber's explicit ActionRegistry.

The model never receives a shell or Python execution primitive. It can only
request actions registered by the desktop app, and the registry enforces
permissions and per-action user approval before handlers run.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from transcriber.assistant.agent_protocol import parse_agent_decision
from transcriber.assistant.ollama_client import OllamaCancelled

_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "app.get_state": {
        "description": "Read the current Transcriber page, audio, transcript and active model state.",
        "parameters": {"type": "object", "properties": {}},
    },
    "app.navigate": {
        "description": "Navigate to a page in Transcriber.",
        "parameters": {"type": "object", "properties": {
            "page": {"type": "string", "enum": [
                "home", "assistant", "transcription", "recording", "batch", "history",
                "editor", "subtitles", "models", "audio", "cleanup", "settings"
            ]},
        }, "required": ["page"]},
    },
    "editor.get_segments": {
        "description": "Read the current transcript segments and timestamps.",
        "parameters": {"type": "object", "properties": {}},
    },
    "editor.search": {
        "description": "Search the transcript for text.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Text to find"},
            "regex": {"type": "boolean", "description": "Use regular expressions"},
        }, "required": ["query"]},
    },
    "editor.update_segment": {
        "description": "Update text, timing, speaker or review metadata for one transcript segment.",
        "parameters": {"type": "object", "properties": {
            "segment_id": {"type": "string"},
            "changes": {"type": "object", "description": "Fields to update on the segment"},
        }, "required": ["segment_id", "changes"]},
    },
    "editor.split_segment": {
        "description": "Split a segment at a time boundary or text character index.",
        "parameters": {"type": "object", "properties": {
            "segment_id": {"type": "string"},
            "split_at": {"type": "number", "description": "Split point in seconds"},
            "character_index": {"type": "integer", "description": "Optional character index"},
        }, "required": ["segment_id", "split_at"]},
    },
    "editor.merge_segments": {
        "description": "Merge two adjacent transcript segments.",
        "parameters": {"type": "object", "properties": {
            "first_id": {"type": "string"},
            "second_id": {"type": "string"},
        }, "required": ["first_id", "second_id"]},
    },
    "editor.delete_segment": {
        "description": "Delete one transcript segment. This is destructive and requires explicit approval.",
        "parameters": {"type": "object", "properties": {
            "segment_id": {"type": "string"},
        }, "required": ["segment_id"]},
    },
    "editor.set_speaker": {
        "description": "Assign a speaker label to one or more transcript segments.",
        "parameters": {"type": "object", "properties": {
            "segment_ids": {"type": "array", "items": {"type": "string"}},
            "speaker": {"type": "string"},
        }, "required": ["segment_ids", "speaker"]},
    },
    "editor.replace": {
        "description": "Replace text in matching transcript segments.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "replacement": {"type": "string"},
            "regex": {"type": "boolean"},
        }, "required": ["query", "replacement"]},
    },
    "editor.undo": {
        "description": "Undo the most recent transcript edit.",
        "parameters": {"type": "object", "properties": {}},
    },
    "editor.redo": {
        "description": "Redo the most recently undone transcript edit.",
        "parameters": {"type": "object", "properties": {}},
    },
    "audio.get_status": {
        "description": "Read the loaded audio path, playback state and position.",
        "parameters": {"type": "object", "properties": {}},
    },
    "audio.seek": {
        "description": "Seek the current audio file to a specified time in seconds.",
        "parameters": {"type": "object", "properties": {
            "seconds": {"type": "number", "minimum": 0},
        }, "required": ["seconds"]},
    },
    "audio.play": {
        "description": "Play the currently loaded audio.",
        "parameters": {"type": "object", "properties": {}},
    },
    "audio.stop": {
        "description": "Stop the currently loaded audio.",
        "parameters": {"type": "object", "properties": {}},
    },
    "transcription.start": {
        "description": "Start transcription of the selected audio file.",
        "parameters": {"type": "object", "properties": {}},
    },
    "transcription.cancel": {
        "description": "Cancel the active transcription job.",
        "parameters": {"type": "object", "properties": {}},
    },
    "transcription.get_quality_report": {
        "description": "Calculate a quality report from the current transcript.",
        "parameters": {"type": "object", "properties": {}},
    },
    "subtitle.validate": {
        "description": "Check subtitle timing, overlaps and reading speed.",
        "parameters": {"type": "object", "properties": {}},
    },
    "subtitle.export": {
        "description": "Export subtitle cues to a supported file format.",
        "parameters": {"type": "object", "properties": {
            "format": {"type": "string", "enum": ["srt", "vtt", "ass", "ssa"]},
        }, "required": ["format"]},
    },
    "browser.open": {
        "description": "Open an HTTP or HTTPS website in the controlled Chrome/Edge browser and return its visible page content.",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "Absolute HTTP or HTTPS URL"},
        }, "required": ["url"]},
    },
    "browser.search": {
        "description": "Search the web in the controlled Chrome/Edge browser and return visible search results.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Search terms"},
            "engine": {"type": "string", "enum": ["google", "bing"]},
        }, "required": ["query"]},
    },
    "browser.snapshot": {
        "description": "Read the current controlled browser page and list visible links, buttons and form fields.",
        "parameters": {"type": "object", "properties": {}},
    },
    "browser.click": {
        "description": "Click a visible browser element by text, CSS selector or ARIA role. The user must approve the click.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"},
            "selector": {"type": "string"},
            "role": {"type": "string"},
        }},
    },
    "browser.fill": {
        "description": "Fill one browser form field by its label, placeholder or CSS selector. The user must approve the data submission step.",
        "parameters": {"type": "object", "properties": {
            "value": {"type": "string"},
            "selector": {"type": "string"},
            "label": {"type": "string"},
            "placeholder": {"type": "string"},
        }, "required": ["value"]},
    },
    "browser.press": {
        "description": "Press a limited browser keyboard key such as Enter or Tab. The user must approve the key action.",
        "parameters": {"type": "object", "properties": {
            "key": {"type": "string"},
            "selector": {"type": "string"},
        }, "required": ["key"]},
    },
    "browser.back": {
        "description": "Navigate back one page in the controlled browser.",
        "parameters": {"type": "object", "properties": {}},
    },
    "browser.screenshot": {
        "description": "Capture a screenshot of the current controlled browser tab and save it to the app's browser screenshots folder.",
        "parameters": {"type": "object", "properties": {}},
    },
    "browser.close": {
        "description": "Close the controlled browser and its dedicated profile window. User approval is required.",
        "parameters": {"type": "object", "properties": {}},
    },
    "system.run_command": {
        "description": "Request the Transcriber Python host to run a PowerShell command as the current Windows user. Python validates, requests approval and executes it; the model never runs shell commands. No elevation; output and runtime are bounded.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "PowerShell command or script"},
            "cwd": {"type": "string", "description": "Optional existing working directory"},
            "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120},
        }, "required": ["command"]},
    },
    "agent.skills_search": {
        "description": "Find matching installed Agent Skills for the user's task. This should be the first tool for multi-step browser, desktop, file, research or coding work.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "The user's complete task"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 8},
        }, "required": ["query"]},
    },
    "agent.skills_catalog": {
        "description": "List curated public Agent Skills that can be installed from GitHub.",
        "parameters": {"type": "object", "properties": {}},
    },
    "agent.skill_install": {
        "description": "Download and install a public GitHub Agent Skill folder. Use only when the user asked to install or download a skill; user approval is required.",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "Public GitHub folder URL containing SKILL.md"},
        }, "required": ["url"]},
    },
    "agent.skills_list": {
        "description": "List installed portable Agent Skills with their names and descriptions.",
        "parameters": {"type": "object", "properties": {}},
    },
    "agent.skill_load": {
        "description": "Load the full SKILL.md instructions for one installed Agent Skill when its description matches the task.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"},
        }, "required": ["name"]},
    },
    "agent.skill_read_resource": {
        "description": "Read a text resource from scripts/, references/ or assets/ inside an installed Agent Skill. This does not execute the file.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"},
            "path": {"type": "string"},
        }, "required": ["name", "path"]},
    },
    "desktop.launch_app": {
        "description": "Launch one built-in allowlisted Windows application. User approval is required.",
        "parameters": {"type": "object", "properties": {
            "app": {"type": "string", "enum": [
                "notepad", "calculator", "explorer", "task_manager", "paint", "terminal"
            ]},
        }, "required": ["app"]},
    },
    "desktop.run_preset": {
        "description": "Open a predefined desktop location or application. User approval is required.",
        "parameters": {"type": "object", "properties": {
            "preset": {"type": "string", "enum": [
                "downloads_folder", "documents_folder", "desktop_folder",
                "task_manager", "calculator", "notepad", "windows_settings",
                "network_config", "running_processes", "user_identity"
            ]},
        }, "required": ["preset"]},
    },
    "desktop.open_path": {
        "description": "Open an existing local file or folder. User approval is required.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Absolute local path"},
        }, "required": ["path"]},
    },
    "desktop.open_url": {
        "description": "Open an HTTP or HTTPS URL in the default browser. User approval is required.",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "HTTP or HTTPS URL"},
        }, "required": ["url"]},
    },
}


class OllamaAgent:
    """Run bounded tool calls and feed real action results back to the local model."""

    def __init__(
        self,
        client,
        action_executor: Callable[[str, dict[str, Any]], Any],
        *,
        max_rounds: int = 6,
        max_tool_calls: int = 8,
    ):
        self.client = client
        self.action_executor = action_executor
        self.max_rounds = max(1, min(int(max_rounds), 12))
        self.max_tool_calls = max(1, min(int(max_tool_calls), 24))

    @staticmethod
    def tools_for_registry(action_registry) -> list[dict[str, Any]]:
        """Expose only tools for actions whose permissions are currently enabled."""
        permissions = {
            getattr(item, "value", str(item))
            for item in getattr(action_registry, "permissions", set())
        }
        enabled = {
            row["name"]
            for row in action_registry.describe(include_disabled=False)
            if row.get("enabled")
            and (not row.get("destructive") or "destructive_actions" in permissions)
        }
        return [
            {"type": "function", "function": {
                "name": name,
                "description": schema["description"],
                "parameters": schema["parameters"],
            }}
            for name, schema in _TOOL_SCHEMAS.items()
            if name in enabled
        ]

    @staticmethod
    def _call_details(call: dict) -> tuple[str, dict[str, Any]]:
        function = call.get("function") or {}
        name = str(function.get("name") or "").strip()
        arguments = function.get("arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Tool {name or '(unknown)'} returned invalid JSON arguments") from exc
        if not isinstance(arguments, dict):
            raise ValueError(f"Tool {name or '(unknown)'} arguments must be an object")
        if not name:
            raise ValueError("Ollama returned a tool call without a function name")
        return name, arguments

    @staticmethod
    def _tool_result_text(value: Any) -> str:
        try:
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
        except (TypeError, ValueError):
            encoded = json.dumps({"result": str(value)}, ensure_ascii=False)
        return encoded[:24_000]

    @staticmethod
    def _action_result_ok(value: Any) -> bool:
        """Interpret host execution results, especially PowerShell exit codes."""
        if not isinstance(value, dict):
            return True
        if value.get("ok") is False or value.get("timed_out") is True:
            return False
        if value.get("cancelled") is True:
            return False
        if "exit_code" in value:
            try:
                return int(value["exit_code"]) == 0
            except (TypeError, ValueError):
                return False
        return True

    @staticmethod
    def is_action_request(prompt: str) -> bool:
        """Return True for clear requests to perform an action, not explain one."""
        value = " ".join(str(prompt or "").casefold().split())
        if not value or value.startswith((
            "how do i ", "how can i ", "how to ", "what is ", "explain ",
            "چطور ", "چگونه ", "معنی ", "توضیح بده ",
        )):
            return False
        cues = (
            "open ", "launch ", "run ", "execute ", "search for ", "search the web",
            "look up ", "browse ", "find online", "click ", "download ", "install ",
            "create ", "edit ", "delete ", "move ", "copy ", "rename ", "fill in ",
            "send ", "export ", "start ", "stop ", "play ", "navigate to ",
            "inspect ", "check ", "verify ", "review ", "read ", "list ",
            "test ", "build ", "compile ", "analyze ", "fix ", "update ",
            "configure ", "scan ", "fetch ", "query ", "run tests",
            "باز کن", "اجرا کن", "جستجو کن", "سرچ کن", "پیدا کن", "دانلود کن",
            "نصب کن", "ایجاد کن", "ویرایش کن", "حذف کن", "منتقل کن", "کپی کن",
            "بفرست", "شروع کن", "متوقف کن",
        )
        if any(cue in value for cue in cues):
            return True
        # Explicit Persian action verbs, without treating explanatory questions as actions.
        persian_action = (
            r"(?:لطفا|لطفاً)?\s*(?:برام|برای من)?\s*(?:باز کن|اجرا کن|ران کن|"
            r"بررسی کن|جستجو کن|سرچ کن|پیدا کن|نصب کن|دانلود کن|ایجاد کن|"
            r"ویرایش کن|حذف کن|منتقل کن|کپی کن|تغییر بده|راه‌اندازی کن|متوقف کن)",
            r"(?:میخوام|می‌خوام|می خواهم|میخواهم).{0,50}(?:انجام بدی|انجام بدهی|"
            r"بررسی کنی|اجرا کنی|باز کنی|بسازی|تغییر بدی|درست کنی|فیکس کنی)",
            r"(?:دستور|کامند|فرمان).{0,40}(?:اجرا|ران|انجام)",
        )
        return any(re.search(pattern, value) for pattern in persian_action)

    @staticmethod
    def is_browser_search_request(prompt: str) -> bool:
        value = " ".join(str(prompt or "").casefold().split())
        has_browser = any(term in value for term in (
            "browser", "chrome", "edge", "web", "internet", "مرورگر", "کروم", "اینترنت", "وب",
        ))
        has_search = any(term in value for term in (
            "search", "google", "look up", "browse for", "find online",
            "search for", "جستجو", "سرچ", "بگرد",
        ))
        return has_browser and has_search

    @classmethod
    def infer_browser_search_tool(
        cls, prompt: str, available_tool_names: list[str] | set[str] | tuple[str, ...]
    ) -> dict[str, Any] | None:
        """Build a safe, read-only browser.search fallback for an explicit search request."""
        if "browser.search" not in set(available_tool_names):
            return None
        if not cls.is_browser_search_request(prompt):
            return None
        value = str(prompt or "").strip()
        quoted = re.findall(r'["“”](.{2,400}?)["“”]', value)
        query = quoted[-1].strip() if quoted else ""
        if not query:
            patterns = (
                r"\b(?:search|look\s+up|google)\s+(?:(?:the\s+)?(?:web|internet|browser)\s+)?for\s+(.+?)(?:[.!?\n]|$)",
                r"\b(?:find|search)\s+(.+?)\s+(?:online|on\s+the\s+web)(?:[.!?\n]|$)",
                r"(?:جستجو|سرچ|بگرد)\s+(?:در\s+(?:وب|اینترنت)\s+)?(?:برای|درباره(?:ی)?|مورد)?\s*(.+?)(?:[.!؟\n]|$)",
                r"(.+?)\s+(?:را|رو)?\s*(?:جستجو|سرچ)\s*(?:کن|بکن)(?:[.!؟\n]|$)",
            )
            for pattern in patterns:
                match = re.search(pattern, value, flags=re.IGNORECASE)
                if match:
                    query = match.group(1).strip()
                    break
        query = re.sub(
            r"\s+(?:using|with)\s+(?:the\s+)?(?:browser|web)\s+automation\s+skill.*$",
            "", query, flags=re.IGNORECASE,
        ).strip(" \t\r\n\"'“”.,!?؛،")
        if not query:
            return None
        return {"name": "browser.search", "arguments": {"query": query, "engine": "google"}}

    @staticmethod
    def response_promises_action(text: str) -> bool:
        """Detect future-tense action promises that still need a real tool call."""
        value = " ".join(str(text or "").casefold().split())
        action_verbs = (
            "open", "launch", "run", "execute", "search", "browse", "click",
            "download", "install", "create", "edit", "delete", "move", "copy",
            "rename", "fill", "send", "export", "start", "stop", "play",
            "navigate", "inspect", "read", "check", "find", "load", "poll",
            "call", "continue",
        )
        promise_prefix = re.search(
            r"\b(?:i(?:'ll| will)|i am going to|i'm going to|let me|now i(?:'ll| will))"
            r"\s+(?:(?:now|next)\s+)?(?:(?:help you)\s+)?(" + "|".join(action_verbs) + r")\b",
            value,
        )
        progressive = (
            "opening the browser", "opening browser", "searching for ",
            "running the command", "executing the command", "i'm searching",
            "i am searching", "now searching", "now opening",
        )
        persian = (
            "الان باز می‌کنم", "الان باز میکنم", "الان جستجو می‌کنم",
            "الان جستجو میکنم", "الان اجرا می‌کنم", "الان اجرا میکنم",
            "دارم باز می‌کنم", "دارم باز میکنم", "در حال اجرا",
            "در حال جستجو", "بعدش اجرا می‌کنم", "بعدش اجرا میکنم",
        )
        return bool(promise_prefix) or any(phrase in value for phrase in (*progressive, *persian))

    def run(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict],
        *,
        keep_alive: str = "30m",
        cancellation=None,
        think: bool | str | None = None,
        require_tool_call: bool = False,
        fallback_tool_call: dict[str, Any] | None = None,
        on_chunk: Callable[[str], None] | None = None,
        on_thinking: Callable[[str], None] | None = None,
        on_tool_status: Callable[[str], None] | None = None,
        on_tool_result: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        working = [dict(item) for item in messages]
        tool_count = 0
        tool_rounds = 0
        recovery_attempts = 0
        fallback_attempted = False
        # Buffer Agent turns until the host-control envelope/native tool call is
        # classified, so raw JSON never flashes in the conversation.
        buffer_until_tool_decision = bool(tools or require_tool_call or fallback_tool_call)
        available_names = {
            str((item.get("function") or {}).get("name") or "")
            for item in tools if isinstance(item, dict)
        }
        last_result: dict[str, Any] = {"text": "", "metrics": {}}

        for _round in range(self.max_rounds):
            if cancellation and cancellation.cancelled:
                return {
                    "model": model,
                    "text": "",
                    "messages": working,
                    "tool_count": tool_count,
                    "tool_rounds": tool_rounds,
                    "cancelled": True,
                    "metrics": last_result.get("metrics", {}),
                }
            turn_chunks: list[str] = []

            def collect(chunk: str) -> None:
                turn_chunks.append(str(chunk))
                # Preserve token streaming for ordinary conversation. Only
                # action turns are buffered so false execution promises can be
                # discarded before they are shown as progress.
                if on_chunk and not buffer_until_tool_decision:
                    on_chunk(str(chunk))

            try:
                response = self.client.chat(
                    model, working, keep_alive=keep_alive, tools=tools,
                    cancellation=cancellation, think=think, on_chunk=collect,
                    on_thinking=on_thinking,
                )
            except OllamaCancelled:
                partial = "".join(turn_chunks)
                if partial:
                    working.append({"role": "assistant", "content": partial})
                    if on_chunk and buffer_until_tool_decision:
                        on_chunk(partial)
                return {
                    "model": model, "text": partial, "messages": working,
                    "tool_count": tool_count, "tool_rounds": tool_rounds,
                    "cancelled": True, "metrics": last_result.get("metrics", {}),
                }

            last_result = response
            answer = str(response.get("text") or "")
            calls = response.get("tool_calls") or []
            decision_status = None

            # Some local models narrate an action instead of emitting native
            # tool_calls. Convert the strict control envelope into the same
            # registered-action path; only the Python host executes it.
            decision = parse_agent_decision(answer) if tools and not calls else None
            if decision is not None:
                decision_status = decision.status
                if decision.status == "continue" and decision.action is not None:
                    progress_parts = []
                    if decision.response:
                        progress_parts.append(decision.response)
                    if decision.plan:
                        plan_lines = [
                            f"{index + 1}. {item['title']} · {item['status']}"
                            for index, item in enumerate(decision.plan)
                        ]
                        progress_parts.append("Plan:\n" + "\n".join(plan_lines))
                    if progress_parts and on_tool_status:
                        on_tool_status("\n".join(progress_parts))
                    calls = [{
                        "function": {
                            "name": decision.action["name"],
                            "arguments": decision.action["arguments"],
                        }
                    }]
                    # Progress is an activity event, not assistant answer text.
                    answer = ""
                else:
                    answer = decision.response

            if not calls and fallback_tool_call and not fallback_attempted:
                fallback_name = str(fallback_tool_call.get("name") or "")
                fallback_arguments = fallback_tool_call.get("arguments") or {}
                if fallback_name in available_names and isinstance(fallback_arguments, dict):
                    # Some local models narrate the browser action but omit the
                    # function call. For a clear, read-only search request, issue
                    # the exact registered search action rather than treating that
                    # narration as success.
                    calls = [{
                        "function": {
                            "name": fallback_name,
                            "arguments": fallback_arguments,
                        }
                    }]
                    answer = ""
                    fallback_attempted = True

            promises_next_action = self.response_promises_action(answer)
            needs_execution = (
                require_tool_call
                and decision_status not in {"blocked", "needs_input"}
                and (tool_count == 0 or promises_next_action)
            )
            if not calls and needs_execution and recovery_attempts < 2:
                working.append({"role": "assistant", "content": answer})
                working.append({
                    "role": "user",
                    "content": (
                        "Your previous response described or promised an action, but no "
                        "corresponding execution-tool call was made. The task is still "
                        "outstanding. Do not send another plan or narration. Use one of the "
                        "enabled functions listed in the tools parameter now, inspect its "
                        "actual result, and only then decide whether to continue or finish. "
                        "If the next step is already complete, give the final factual answer. "
                        "If no available function can perform it, state exactly what remains "
                        "unexecuted."
                    ),
                })
                recovery_attempts += 1
                continue

            if not calls and needs_execution:
                if tool_count:
                    failure = (
                        "Some actions were executed, but the model promised another step "
                        "without calling a tool. That next step was not executed."
                    )
                    incomplete = True
                else:
                    failure = (
                        "I could not execute that request because the model did not call an "
                        "available action. No browser, desktop or command action was run."
                    )
                    incomplete = False
                working.append({"role": "assistant", "content": failure})
                if on_chunk:
                    on_chunk(failure)
                return {
                    "model": model, "text": failure, "messages": working,
                    "tool_count": tool_count, "tool_rounds": tool_rounds,
                    "cancelled": False, "action_not_executed": not bool(tool_count),
                    "incomplete": incomplete,
                    "metrics": response.get("metrics", {}),
                }

            if answer and on_chunk and buffer_until_tool_decision:
                on_chunk(answer)
            assistant_message = {"role": "assistant", "content": answer}
            thinking_text = str(response.get("thinking") or "")
            if thinking_text:
                assistant_message["thinking"] = thinking_text
            if calls:
                assistant_message["tool_calls"] = calls
            working.append(assistant_message)
            if not calls:
                return {
                    **response,
                    "text": answer,
                    "messages": working,
                    "tool_count": tool_count,
                    "tool_rounds": tool_rounds,
                    "cancelled": False,
                    "agent_status": decision_status or "done",
                    "blocked": decision_status == "blocked",
                    "needs_input": decision_status == "needs_input",
                }

            tool_rounds += 1
            for call_index, call in enumerate(calls):
                if cancellation and cancellation.cancelled:
                    return {
                        "model": model, "text": answer, "messages": working,
                        "tool_count": tool_count, "tool_rounds": tool_rounds,
                        "cancelled": True, "metrics": response.get("metrics", {}),
                    }
                tool_count += 1
                if tool_count > self.max_tool_calls:
                    limit_message = (
                        "I stopped because this request reached the configured tool-action limit. "
                        "The actions already completed are listed above; no additional actions were run."
                    )
                    working.append({
                        "role": "tool", "tool_name": "agent.limit",
                        "content": "Tool-call limit reached. No more actions may be run in this turn.",
                    })
                    working.append({"role": "assistant", "content": limit_message})
                    if on_chunk:
                        on_chunk(limit_message)
                    return {
                        "model": model, "text": limit_message, "messages": working,
                        "tool_count": tool_count - 1, "tool_rounds": tool_rounds,
                        "cancelled": False, "metrics": response.get("metrics", {}),
                    }
                name = "unknown"
                permission_blocked = False
                action_ok = False
                try:
                    name, arguments = self._call_details(call)
                    if on_tool_status:
                        on_tool_status(f"Running {name}…")
                    result = self.action_executor(name, arguments)
                    action_ok = self._action_result_ok(result)
                    result_text = self._tool_result_text({
                        "ok": action_ok, "action": name, "result": result,
                    })
                    status = (
                        f"Completed {name}" if action_ok
                        else f"Failed {name} · host returned an unsuccessful result"
                    )
                except Exception as exc:
                    permission_blocked = isinstance(exc, PermissionError)
                    result_text = self._tool_result_text({
                        "ok": False, "action": name,
                        "error": f"{type(exc).__name__}: {exc}",
                    })
                    status = f"Could not run {name}: {exc}"
                if on_tool_status:
                    on_tool_status(status)
                working.append({
                    "role": "tool",
                    "tool_name": str((call.get("function") or {}).get("name") or "unknown"),
                    "content": result_text,
                })
                if on_tool_result:
                    on_tool_result({
                        "name": name,
                        "ok": action_ok,
                        "content": result_text,
                    })
                if permission_blocked:
                    blocked_message = (
                        f"{name} was not executed because the required permission or "
                        "user approval was denied. I will not retry or bypass that decision."
                    )
                    for skipped_call in calls[call_index + 1:]:
                        skipped_name = str(
                            (skipped_call.get("function") or {}).get("name") or "unknown"
                        )
                        working.append({
                            "role": "tool",
                            "tool_name": skipped_name,
                            "content": self._tool_result_text({
                                "ok": False,
                                "error": (
                                    "Not executed because an earlier action was denied. "
                                    "No further actions were started."
                                ),
                            }),
                        })
                    working.append({"role": "assistant", "content": blocked_message})
                    if on_chunk:
                        on_chunk(blocked_message)
                    return {
                        "model": model,
                        "text": blocked_message,
                        "messages": working,
                        "tool_count": tool_count,
                        "tool_rounds": tool_rounds,
                        "cancelled": False,
                        "permission_denied": True,
                        "metrics": response.get("metrics", {}),
                    }
                if cancellation and cancellation.cancelled:
                    return {
                        "model": model,
                        "text": answer,
                        "messages": working,
                        "tool_count": tool_count,
                        "tool_rounds": tool_rounds,
                        "cancelled": True,
                        "metrics": response.get("metrics", {}),
                    }

        limit_message = (
            "I stopped because this request reached the maximum number of Agent rounds. "
            "The actions already completed are listed above."
        )
        working.append({"role": "assistant", "content": limit_message})
        if on_chunk:
            on_chunk(limit_message)
        return {
            "model": model,
            "text": limit_message,
            "messages": working,
            "tool_count": tool_count,
            "tool_rounds": tool_rounds,
            "cancelled": False,
            "metrics": last_result.get("metrics", {}),
        }
