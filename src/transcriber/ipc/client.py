"""Authenticated loopback/Unix-socket client for the running Transcriber GUI."""

from __future__ import annotations

import json
import socket
from pathlib import Path

from transcriber.ipc.protocol import encode_request


class IPCUnavailable(ConnectionError):
    pass


class LocalIPCClient:
    def __init__(self, endpoint_file: Path, *, timeout: float = 3.0):
        self.endpoint_file = Path(endpoint_file)
        self.timeout = float(timeout)

    def call(self, method: str, params: dict | None = None):
        try:
            endpoint = json.loads(self.endpoint_file.read_text(encoding="utf-8"))
            token = endpoint["token"]
            kind = endpoint["kind"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise IPCUnavailable("Transcriber GUI is not running or its local IPC endpoint is unavailable") from exc
        if not isinstance(token, str) or len(token) < 32:
            raise IPCUnavailable("The local IPC endpoint has an invalid authentication token")
        if kind == "unix":
            address = endpoint.get("address")
            if not isinstance(address, str):
                raise IPCUnavailable("Invalid local IPC endpoint")
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        elif kind == "tcp":
            # The Windows fallback binds only to loopback. A high-entropy token
            # authenticates each request; no LAN interface is ever exposed.
            address = ("127.0.0.1", int(endpoint["port"]))
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        else:
            raise IPCUnavailable("Unsupported local IPC transport")
        try:
            client.settimeout(self.timeout)
            client.connect(address)
            client.sendall(encode_request(method, params or {}, token))
            raw = bytearray()
            while not raw.endswith(b"\n"):
                chunk = client.recv(65536)
                if not chunk:
                    break
                raw.extend(chunk)
                if len(raw) > 1_048_576:
                    raise IPCUnavailable("IPC response is too large")
            if not raw:
                raise IPCUnavailable("Transcriber GUI closed the IPC connection")
            response = json.loads(raw.decode("utf-8"))
            if not response.get("ok"):
                raise IPCUnavailable(response.get("error", "Transcriber GUI rejected the request"))
            return response.get("result")
        except (OSError, ValueError, KeyError) as exc:
            if isinstance(exc, IPCUnavailable):
                raise
            raise IPCUnavailable(f"Transcriber GUI is not reachable: {exc}") from exc
        finally:
            client.close()
