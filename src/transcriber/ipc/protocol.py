"""Versioned JSON request/response helpers for authenticated local IPC."""

from __future__ import annotations

import json
import uuid

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 1_048_576


def encode_request(method: str, params: dict, token: str) -> bytes:
    payload = {
        "version": PROTOCOL_VERSION,
        "id": uuid.uuid4().hex,
        "method": method,
        "params": params,
        "token": token,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_MESSAGE_BYTES:
        raise ValueError("IPC request exceeds the maximum message size")
    return raw + b"\n"


def decode_request(raw: bytes) -> dict:
    if len(raw) > MAX_MESSAGE_BYTES:
        raise ValueError("IPC request exceeds the maximum message size")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != PROTOCOL_VERSION:
        raise ValueError("Unsupported IPC protocol version")
    if not isinstance(payload.get("id"), str) or len(payload["id"]) > 128:
        raise ValueError("Invalid IPC request ID")
    if not isinstance(payload.get("method"), str) or not isinstance(payload.get("params", {}), dict):
        raise ValueError("Malformed IPC request")
    if not isinstance(payload.get("token"), str):
        raise ValueError("Missing IPC authentication token")
    return payload


def encode_response(request_id: str, *, result=None, error: str | None = None) -> bytes:
    response = {"version": PROTOCOL_VERSION, "id": request_id, "ok": error is None}
    if error is None:
        response["result"] = result
    else:
        response["error"] = error[:1000]
    return json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
