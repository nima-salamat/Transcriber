"""Persistent multi-conversation storage for the local AI Assistant."""

from __future__ import annotations

import copy
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_MAX_SESSIONS = 100
_MAX_VISIBLE_MESSAGES = 400
_MAX_PROVIDER_MESSAGES = 300


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_copy(value: Any) -> Any:
    """Return a JSON-safe deep copy so Qt and provider objects never leak into storage."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


class ChatSessionStore:
    """Atomic, UTF-8 session storage with independent provider and display histories.

    A session stores the rendered conversation, the full Ollama tool-call context,
    and provider-specific metadata such as an OpenCode ACP session ID. Session files
    stay in the user's application data directory and are never uploaded.
    """

    VERSION = 1

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._document = self._read()

    def _read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"version": self.VERSION, "active_session_id": "", "sessions": []}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            # Preserve the original file. A fresh in-memory store is safer than
            # destroying a conversation file that may be recoverable by the user.
            return {"version": self.VERSION, "active_session_id": "", "sessions": []}
        if not isinstance(raw, dict) or not isinstance(raw.get("sessions"), list):
            return {"version": self.VERSION, "active_session_id": "", "sessions": []}
        sessions = []
        for item in raw["sessions"][-_MAX_SESSIONS:]:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            provider = str(item.get("provider") or "ollama")
            if provider not in {"ollama", "opencode"}:
                provider = "ollama"
            sessions.append({
                "id": str(item["id"])[:80],
                "provider": provider,
                "title": str(item.get("title") or "New chat")[:120],
                "created_at": str(item.get("created_at") or _now()),
                "updated_at": str(item.get("updated_at") or item.get("created_at") or _now()),
                "messages": self._normalize_messages(item.get("messages"), _MAX_VISIBLE_MESSAGES),
                "provider_messages": self._normalize_messages(
                    item.get("provider_messages"), _MAX_PROVIDER_MESSAGES
                ),
                "metadata": _json_copy(item.get("metadata") if isinstance(item.get("metadata"), dict) else {}),
            })
        active = str(raw.get("active_session_id") or "")
        if active not in {item["id"] for item in sessions}:
            active = sessions[-1]["id"] if sessions else ""
        return {"version": self.VERSION, "active_session_id": active, "sessions": sessions}

    @staticmethod
    def _normalize_messages(value: Any, limit: int) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        result = []
        for item in value[-limit:]:
            if isinstance(item, dict):
                try:
                    result.append(_json_copy(item))
                except (TypeError, ValueError):
                    continue
        return result

    def _write(self) -> None:
        payload = json.dumps(
            self._document, ensure_ascii=False, indent=2, separators=(",", ": ")
        )
        temporary = self.path.with_name(self.path.name + ".tmp")
        try:
            temporary.write_text(payload + "\n", encoding="utf-8")
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            os.replace(temporary, self.path)
        except OSError:
            temporary.unlink(missing_ok=True)
            raise

    def list_sessions(self, *, provider: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            values = self._document["sessions"]
            if provider:
                values = [item for item in values if item["provider"] == provider]
            return copy.deepcopy(sorted(values, key=lambda item: item["updated_at"], reverse=True))

    def get_session(self, session_id: str | None) -> dict[str, Any] | None:
        if not session_id:
            return None
        with self._lock:
            for item in self._document["sessions"]:
                if item["id"] == session_id:
                    return copy.deepcopy(item)
        return None

    def active_session(self) -> dict[str, Any] | None:
        with self._lock:
            return self.get_session(self._document["active_session_id"])

    @property
    def active_session_id(self) -> str:
        with self._lock:
            return str(self._document["active_session_id"])

    def create_session(
        self,
        provider: str,
        *,
        title: str = "New chat",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        selected_provider = str(provider or "ollama").casefold()
        if selected_provider not in {"ollama", "opencode"}:
            raise ValueError("Chat provider must be ollama or opencode.")
        with self._lock:
            now = _now()
            item = {
                "id": uuid.uuid4().hex,
                "provider": selected_provider,
                "title": str(title or "New chat")[:120],
                "created_at": now,
                "updated_at": now,
                "messages": [],
                "provider_messages": [],
                "metadata": _json_copy(metadata or {}),
            }
            self._document["sessions"].append(item)
            self._document["sessions"] = self._document["sessions"][-_MAX_SESSIONS:]
            self._document["active_session_id"] = item["id"]
            self._write()
            return copy.deepcopy(item)

    def set_active(self, session_id: str) -> None:
        with self._lock:
            if not any(item["id"] == session_id for item in self._document["sessions"]):
                raise KeyError(f"Unknown chat session: {session_id}")
            self._document["active_session_id"] = session_id
            self._write()

    def save_state(
        self,
        session_id: str,
        *,
        messages: list[dict[str, Any]] | None = None,
        provider_messages: list[dict[str, Any]] | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            item = next(
                (entry for entry in self._document["sessions"] if entry["id"] == session_id),
                None,
            )
            if item is None:
                raise KeyError(f"Unknown chat session: {session_id}")
            if messages is not None:
                item["messages"] = self._normalize_messages(messages, _MAX_VISIBLE_MESSAGES)
            if provider_messages is not None:
                item["provider_messages"] = self._normalize_messages(
                    provider_messages, _MAX_PROVIDER_MESSAGES
                )
            if title is not None and str(title).strip():
                item["title"] = str(title).strip()[:120]
            item["updated_at"] = _now()
            self._write()
            return copy.deepcopy(item)

    def update_metadata(self, session_id: str, **metadata: Any) -> dict[str, Any]:
        with self._lock:
            item = next(
                (entry for entry in self._document["sessions"] if entry["id"] == session_id),
                None,
            )
            if item is None:
                raise KeyError(f"Unknown chat session: {session_id}")
            item["metadata"].update(_json_copy(metadata))
            item["updated_at"] = _now()
            self._write()
            return copy.deepcopy(item)

    def delete_session(self, session_id: str) -> str | None:
        with self._lock:
            self._document["sessions"] = [
                item for item in self._document["sessions"] if item["id"] != session_id
            ]
            active = self._document["active_session_id"]
            if active == session_id:
                remaining = sorted(
                    self._document["sessions"],
                    key=lambda item: item["updated_at"],
                    reverse=True,
                )
                active = remaining[0]["id"] if remaining else ""
                self._document["active_session_id"] = active
            self._write()
            return active or None
