"""OpenCode ACP subprocess client using JSON-RPC over newline-delimited stdio."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path, PureWindowsPath
from typing import Any

from transcriber.core.process import hidden_subprocess_creation_flags


class ACPError(RuntimeError):
    pass


def resolve_opencode_executable(
    executable: str | None = None,
    *,
    is_windows: bool | None = None,
) -> str:
    """Resolve OpenCode, including extensionless paths to Windows npm shims."""
    windows = os.name == "nt" if is_windows is None else bool(is_windows)
    configured = str(executable or "opencode").strip().strip('"')
    if not configured:
        configured = "opencode"
    expanded = os.path.expandvars(os.path.expanduser(configured))

    # npm installs both an extensionless shim and Windows command wrappers.
    # If Settings contains the extensionless path, prefer the .cmd/.exe wrapper
    # instead of passing the JavaScript shim to CreateProcess (WinError 193).
    if windows and not PureWindowsPath(expanded).suffix:
        is_explicit_path = (
            "\\" in expanded
            or "/" in expanded
            or PureWindowsPath(expanded).drive
        )
        if is_explicit_path:
            for suffix in (".cmd", ".bat", ".exe", ".ps1"):
                candidate = Path(expanded + suffix)
                if candidate.is_file():
                    return str(candidate)

            if Path(expanded).is_file():
                raise ACPError(
                    f"OpenCode points to an extensionless Windows script ({expanded}). "
                    "Select the adjacent opencode.cmd file in Settings → OpenCode executable."
                )

    # Bare commands must be resolved through PATH/PATHEXT, never from the
    # current project directory.
    return shutil.which(expanded) or expanded


def build_opencode_invocation(
    executable: str,
    arguments: list[str] | tuple[str, ...],
    *,
    is_windows: bool | None = None,
) -> tuple[list[str] | str, dict[str, Any]]:
    """Build a safe subprocess invocation for native executables and Windows shims."""
    windows = os.name == "nt" if is_windows is None else bool(is_windows)
    target = str(executable)
    suffix = PureWindowsPath(target).suffix.casefold() if windows else Path(target).suffix.casefold()
    args = [target, *(str(item) for item in arguments)]

    if windows and suffix in {".cmd", ".bat"}:
        # cmd/bat files are command scripts, not PE executables. Let cmd.exe
        # execute the quoted command line while keeping argv quoting consistent.
        return subprocess.list2cmdline(args), {"shell": True}

    if windows and suffix == ".ps1":
        powershell = shutil.which("pwsh") or shutil.which("powershell") or "powershell.exe"
        return [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            target,
            *(str(item) for item in arguments),
        ], {}

    return args, {}


class OpenCodeACPClient:
    def __init__(self, executable: str | None = None, *, cwd: Path | None = None,
                 on_notification: Callable[[dict[str, Any]], None] | None = None):
        self.executable = executable or "opencode"
        self.cwd = Path(cwd or Path.cwd()).expanduser().resolve()
        self.on_notification = on_notification
        self.process: subprocess.Popen | None = None
        self.session_id: str | None = None
        self.agent_capabilities: dict[str, Any] = {}
        self.config_options: list[dict[str, Any]] = []
        self._next_id = 0
        self._pending: dict[int, queue.Queue] = {}
        self._pending_lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._stderr_tail: list[str] = []
        self._closed = threading.Event()
        self._close_requested = threading.Event()

    @property
    def connected(self) -> bool:
        return self.process is not None and self.process.poll() is None

    @property
    def shutdown_complete(self) -> bool:
        if self.process is not None and self.process.poll() is None:
            return False
        current = threading.current_thread()
        return all(
            reader is None or reader is current or not reader.is_alive()
            for reader in (self._reader, self._stderr_reader)
        )

    @property
    def stderr_tail(self) -> str:
        return "".join(self._stderr_tail[-40:])

    def start(self, *, timeout: float = 20.0) -> dict[str, Any]:
        if self._close_requested.is_set():
            raise ACPError("OpenCode ACP startup was cancelled because the application is closing.")
        if self.connected:
            return self.agent_capabilities
        if not self.cwd.is_absolute() or not self.cwd.is_dir():
            raise ValueError(f"ACP working directory must exist and be absolute: {self.cwd}")
        resolved = resolve_opencode_executable(self.executable)
        command, launch_options = build_opencode_invocation(resolved, ["acp"])
        try:
            process = subprocess.Popen(
                command, cwd=self.cwd, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace", bufsize=1,
                creationflags=hidden_subprocess_creation_flags(),
                start_new_session=(os.name != "nt"),
                **launch_options,
            )
            self.process = process
            if self._close_requested.is_set():
                self.process = None
                self._terminate_process_tree(process)
                raise ACPError(
                    "OpenCode ACP startup was cancelled because the application is closing."
                )
        except OSError as exc:
            hint = ""
            if os.name == "nt" and getattr(exc, "winerror", None) == 193:
                hint = (
                    " Windows cannot execute this file directly. Choose the npm "
                    "opencode.cmd launcher, or leave the setting empty to resolve it from PATH."
                )
            raise ACPError(
                f"Could not start OpenCode ACP ({resolved}): {exc}.{hint}"
            ) from exc
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

    def set_config_options(self, options: Any) -> None:
        """Store the latest ACP session config options defensively."""
        if not isinstance(options, list):
            return
        self.config_options = [dict(item) for item in options if isinstance(item, dict)]

    def new_session(self, *, mcp_servers: list[dict[str, Any]] | None = None,
                    timeout: float = 20.0) -> str:
        self._require_connected()
        response = self.request("session/new", {
            "cwd": str(self.cwd),
            "mcpServers": mcp_servers or [],
        }, timeout=timeout)
        self.session_id = str(response["sessionId"])
        self.set_config_options(response.get("configOptions"))
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
        self.set_config_options(response.get("configOptions"))
        return response

    def set_config_option(self, config_id: str, value: str) -> dict[str, Any]:
        """Apply an ACP option (such as model) to the active conversation."""
        self._require_connected()
        if not self.session_id:
            raise ACPError("OpenCode has no active session for changing its model.")
        response = self.request("session/set_config_option", {
            "sessionId": self.session_id,
            "configId": str(config_id),
            "value": str(value),
        })
        self.set_config_options(response.get("configOptions"))
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

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Send a one-way JSON-RPC notification without an ID or response wait."""
        self._require_connected()
        message = {
            "jsonrpc": "2.0",
            "method": str(method),
            "params": params or {},
        }
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        try:
            with self._write_lock:
                process = self.process
                if process is None or process.poll() is not None or process.stdin is None:
                    raise ACPError("OpenCode ACP disconnected before the notification was sent.")
                process.stdin.write(payload + "\n")
                process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise ACPError(
                f"OpenCode ACP connection failed while sending {method}: {exc}"
            ) from exc

    def cancel(self, *, timeout: float = 3.0) -> None:
        """Cancel the foreground prompt using ACP's fire-and-forget notification."""
        # Keep timeout in the signature for compatibility with existing callers.
        # session/cancel is a notification: it has no JSON-RPC ID and no reply.
        if self.connected and self.session_id:
            self.notify("session/cancel", {"sessionId": self.session_id})

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

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen) -> None:
        """Terminate this ACP process and any MCP children it spawned."""
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=8,
                    creationflags=hidden_subprocess_creation_flags(),
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
        else:
            try:
                import signal
                os.killpg(process.pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                try:
                    process.terminate()
                except OSError:
                    pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    import signal
                    os.killpg(process.pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    try:
                        process.kill()
                    except OSError:
                        pass
        try:
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def close(self, *, terminate_timeout: float = 2.0) -> None:
        self._close_requested.set()
        process, self.process = self.process, None
        self._closed.set()
        if process is None:
            return
        try:
            with self._write_lock:
                if process.stdin:
                    process.stdin.close()
            process.wait(timeout=max(0.2, float(terminate_timeout)))
        except (OSError, subprocess.TimeoutExpired):
            self._terminate_process_tree(process)
        # The protocol reader releases every pending request with an ACPError
        # when stdout closes. Join readers so the client leaves no threads behind.
        current = threading.current_thread()
        for reader in (self._reader, self._stderr_reader):
            if reader is not None and reader is not current and reader.is_alive():
                reader.join(timeout=1.5)
        self.session_id = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_exc):
        self.close()
