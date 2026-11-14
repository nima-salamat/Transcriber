"""OpenCode ACP subprocess client using JSON-RPC over newline-delimited stdio."""

from __future__ import annotations

import json
import queue
import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any


class ACPError(RuntimeError):
    pass


class OpenCodeACPClient:
    def __init__(self, executable: str | None = None, *, cwd: Path | None = None,
                 on_notification: Callable[[dict[str, Any]], None] | None = None):
        self.executable = executable or shutil.which("opencode") or "opencode"
        self.cwd = Path(cwd or Path.cwd()).expanduser().resolve()
        self.on_notification = on_notification
        self.process: subprocess.Popen | None = None
        self.session_id: str | None = None
        self.agent_capabilities: dict[str, Any] = {}
        self._next_id = 0
        self._pending: dict[int, queue.Queue] = {}
        self._pending_lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._stderr_tail: list[str] = []
        self._closed = threading.Event()

    @property
    def connected(self) -> bool:
        return self.process is not None and self.process.poll() is None

    @property
    def stderr_tail(self) -> str:
        return "".join(self._stderr_tail[-40:])

    def start(self, *, timeout: float = 20.0) -> dict[str, Any]:
        if self.connected:
            return self.agent_capabilities
        if not self.cwd.is_absolute() or not self.cwd.is_dir():
            raise ValueError(f"ACP working directory must exist and be absolute: {self.cwd}")
        resolved = shutil.which(self.executable) or self.executable
        try:
            self.process = subprocess.Popen(
                [resolved, "acp"], cwd=self.cwd, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            raise ACPError(f"Could not start OpenCode ACP ({resolved}): {exc}") from exc
        self._closed.clear()
        self._reader = threading.Thread(target=self._read_stdout, name="OpenCode-ACP-reader", daemon=True)
        self._stderr_reader = threading.Thread(target=self._read_stderr, name="OpenCode-ACP-stderr", daemon=True)
        self._reader.start()
        self._stderr_reader.start()
        try:
            initialized = self.request("initialize", {
                "protocolVersion": 1,
                "clientInfo": {"name": "Transcriber", "version": "2.1"},
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                    "_meta": {"terminal-auth": False},
                },
            }, timeout=timeout)
        except Exception:
            # A failed handshake must not leave a hidden opencode process alive.
            self.close()
            raise
        self.agent_capabilities = initialized.get("agentCapabilities", {})
        return self.agent_capabilities

    def new_session(self, *, mcp_servers: list[dict[str, Any]] | None = None,
                    timeout: float = 20.0) -> str:
        self._require_connected()
        response = self.request("session/new", {
            "cwd": str(self.cwd),
            "mcpServers": mcp_servers or [],
        }, timeout=timeout)
        self.session_id = str(response["sessionId"])
        return self.session_id

    def load_session(self, session_id: str, *, mcp_servers: list[dict[str, Any]] | None = None,
                     timeout: float = 20.0) -> dict[str, Any]:
        self._require_connected()
        response = self.request("session/load", {
            "sessionId": session_id,
            "cwd": str(self.cwd),
            "mcpServers": mcp_servers or [],
        }, timeout=timeout)
        self.session_id = session_id
        return response

    def prompt(self, text: str, *, timeout: float | None = None) -> dict[str, Any]:
        self._require_connected()
        if not self.session_id:
            self.new_session()
        if not text.strip():
            raise ValueError("Prompt cannot be empty")
        return self.request("session/prompt", {
            "sessionId": self.session_id,
            "prompt": [{"type": "text", "text": text}],
        }, timeout=timeout)

    def cancel(self, *, timeout: float = 3.0) -> None:
        if self.connected and self.session_id:
            self.request("session/cancel", {"sessionId": self.session_id}, timeout=timeout)

    def request(self, method: str, params: dict[str, Any] | None = None,
                *, timeout: float | None = 20.0) -> dict[str, Any]:
        self._require_connected()
        with self._pending_lock:
            self._next_id += 1
            request_id = self._next_id
            response_queue: queue.Queue = queue.Queue(maxsize=1)
            self._pending[request_id] = response_queue
        message = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
        try:
            payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
            with self._write_lock:
                assert self.process and self.process.stdin
                self.process.stdin.write(payload + "\n")
                self.process.stdin.flush()
            result = response_queue.get(timeout=timeout)
        except queue.Empty as exc:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise TimeoutError(f"OpenCode ACP request timed out: {method}") from exc
        except (BrokenPipeError, OSError) as exc:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise ACPError(f"OpenCode ACP connection failed during {method}: {exc}") from exc
        if "error" in result:
            error = result["error"]
            raise ACPError(f"OpenCode ACP {method} failed ({error.get('code')}): {error.get('message')}")
        return result.get("result", {})

    def _read_stdout(self) -> None:
        process = self.process
        if not process or not process.stdout:
            return
        try:
            for line in process.stdout:
                if not line.strip():
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    self._stderr_tail.append(f"[invalid ACP stdout] {line[:500]}\n")
                    continue
                if "id" in message and ("result" in message or "error" in message):
                    with self._pending_lock:
                        waiter = self._pending.pop(message["id"], None)
                    if waiter:
                        waiter.put(message)
                elif self.on_notification:
                    try:
                        self.on_notification(message)
                    except Exception:
                        # UI observers are not allowed to kill the protocol reader.
                        pass
        finally:
            self._closed.set()
            with self._pending_lock:
                pending, self._pending = self._pending, {}
            for waiter in pending.values():
                try:
                    waiter.put_nowait({"error": {"code": -32000, "message": "ACP process closed"}})
                except queue.Full:
                    pass

    def _read_stderr(self) -> None:
        process = self.process
        if not process or not process.stderr:
            return
        for line in process.stderr:
            self._stderr_tail.append(line)
            self._stderr_tail = self._stderr_tail[-100:]

    def _require_connected(self) -> None:
        if not self.connected:
            detail = self.stderr_tail.strip()
            raise ACPError("OpenCode ACP is not connected" + (f": {detail}" if detail else ""))

    def close(self, *, terminate_timeout: float = 4.0) -> None:
        process, self.process = self.process, None
        if process is None:
            return
        self._closed.set()
        try:
            if process.stdin:
                process.stdin.close()
            process.wait(timeout=terminate_timeout)
        except (OSError, subprocess.TimeoutExpired):
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        self.session_id = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_exc):
        self.close()
