"""User-local authenticated IPC server.

Unix uses a private domain socket. Windows uses a loopback-only ephemeral TCP
port protected by a 256-bit token file created with user-only permissions.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import threading
from pathlib import Path
from typing import Any, Callable

from transcriber.ipc.protocol import decode_request, encode_response


class LocalIPCServer:
    def __init__(self, endpoint_file: Path, handler: Callable[[str, dict[str, Any]], Any]):
        self.endpoint_file = Path(endpoint_file)
        self.handler = handler
        self.token = secrets.token_urlsafe(48)
        self.listener: socket.socket | None = None
        self.thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._socket_path: Path | None = None

    def start(self) -> None:
        if self.listener:
            return
        self.endpoint_file.parent.mkdir(parents=True, exist_ok=True)
        if hasattr(socket, "AF_UNIX"):
            self._socket_path = self.endpoint_file.with_suffix(".sock")
            try:
                self._socket_path.unlink(missing_ok=True)
            except OSError:
                pass
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(self._socket_path))
            os.chmod(self._socket_path, 0o600)
            endpoint = {"kind": "unix", "address": str(self._socket_path), "token": self.token}
        else:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            listener.bind(("127.0.0.1", 0))
            endpoint = {"kind": "tcp", "port": listener.getsockname()[1], "token": self.token}
        listener.listen(8)
        listener.settimeout(0.5)
        self.listener = listener
        temporary = self.endpoint_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(endpoint), encoding="utf-8")
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, self.endpoint_file)
        self._stop.clear()
        self.thread = threading.Thread(target=self._serve, name="Transcriber-local-ipc", daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set() and self.listener:
            try:
                client, _address = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    def _handle(self, client: socket.socket) -> None:
        with client:
            client.settimeout(4.0)
            buffer = bytearray()
            try:
                while not buffer.endswith(b"\n"):
                    chunk = client.recv(65536)
                    if not chunk:
                        raise ValueError("Incomplete IPC request")
                    buffer.extend(chunk)
                    if len(buffer) > 1_048_576:
                        raise ValueError("IPC request too large")
                payload = decode_request(bytes(buffer).rstrip(b"\n"))
                if not secrets.compare_digest(payload["token"], self.token):
                    raise PermissionError("IPC authentication failed")
                result = self.handler(payload["method"], payload.get("params", {}))
                response = encode_response(payload["id"], result=result)
            except Exception as exc:
                request_id = "unknown"
                try:
                    request_id = payload.get("id", request_id)  # type: ignore[possibly-undefined]
                except Exception:
                    pass
                response = encode_response(request_id, error=f"{type(exc).__name__}: {exc}")
            try:
                client.sendall(response)
            except OSError:
                pass

    def close(self) -> None:
        self._stop.set()
        if self.listener:
            try:
                self.listener.close()
            except OSError:
                pass
            self.listener = None
        if self.thread:
            self.thread.join(timeout=2)
            self.thread = None
        self.endpoint_file.unlink(missing_ok=True)
        if self._socket_path:
            self._socket_path.unlink(missing_ok=True)
            self._socket_path = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_exc):
        self.close()
