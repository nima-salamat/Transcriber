"""Bounded Ollama tool-calling loop using Transcriber's explicit ActionRegistry.

The model never receives a shell or Python execution primitive. It can only
request actions registered by the desktop app, and the registry enforces
permissions and per-action user approval before handlers run.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any

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

    def run(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict],
        *,
        keep_alive: str = "30m",
        cancellation=None,
        on_chunk: Callable[[str], None] | None = None,
        on_tool_status: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        working = [dict(item) for item in messages]
        tool_count = 0
        tool_rounds = 0
        last_result: dict[str, Any] = {"text": "", "metrics": {}}

        for _round in range(self.max_rounds):
            if cancellation:
                cancellation.raise_if_cancelled()
            turn_chunks: list[str] = []

            def collect(chunk: str) -> None:
                turn_chunks.append(str(chunk))
                if on_chunk:
                    on_chunk(str(chunk))

            try:
                response = self.client.chat(
                    model, working, keep_alive=keep_alive, tools=tools,
                    cancellation=cancellation, on_chunk=collect,
                )
            except OllamaCancelled:
                partial = "".join(turn_chunks)
                if partial:
                    working.append({"role": "assistant", "content": partial})
                return {
                    "model": model, "text": partial, "messages": working,
                    "tool_count": tool_count, "tool_rounds": tool_rounds,
                    "cancelled": True, "metrics": last_result.get("metrics", {}),
                }

            last_result = response
            answer = str(response.get("text") or "")
            calls = response.get("tool_calls") or []
            assistant_message = {"role": "assistant", "content": answer}
            if calls:
                assistant_message["tool_calls"] = calls
            working.append(assistant_message)
            if not calls:
                return {
                    **response, "messages": working, "tool_count": tool_count,
                    "tool_rounds": tool_rounds, "cancelled": False,
                }

            tool_rounds += 1
            for call in calls:
                if cancellation and cancellation.cancelled:
                    return {
                        "model": model, "text": answer, "messages": working,
                        "tool_count": tool_count, "tool_rounds": tool_rounds,
                        "cancelled": True, "metrics": response.get("metrics", {}),
                    }
                tool_count += 1
                if tool_count > self.max_tool_calls:
                    working.append({
                        "role": "tool", "tool_name": "agent.limit",
                        "content": "Tool-call limit reached. Summarize the results already obtained.",
                    })
                    return {
                        "model": model, "text": answer, "messages": working,
                        "tool_count": tool_count - 1, "tool_rounds": tool_rounds,
                        "cancelled": False, "metrics": response.get("metrics", {}),
                    }
                name = "unknown"
                try:
                    name, arguments = self._call_details(call)
                    if on_tool_status:
                        on_tool_status(f"Running {name}…")
                    result = self.action_executor(name, arguments)
                    result_text = self._tool_result_text({"ok": True, "result": result})
                    status = f"Completed {name}"
                except Exception as exc:
                    result_text = self._tool_result_text({
                        "ok": False, "error": f"{type(exc).__name__}: {exc}",
                    })
                    status = f"Could not run {name}: {exc}"
                if on_tool_status:
                    on_tool_status(status)
                working.append({
                    "role": "tool",
                    "tool_name": str((call.get("function") or {}).get("name") or "unknown"),
                    "content": result_text,
                })

        return {
            "model": model,
            "text": "I reached the maximum number of tool-calling rounds. Tell me whether to continue.",
            "messages": working,
            "tool_count": tool_count,
            "tool_rounds": tool_rounds,
            "cancelled": False,
            "metrics": last_result.get("metrics", {}),
        }
