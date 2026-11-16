"""Small, dependency-free client for a local Ollama server.

Uses Ollama's documented /api/tags and /api/chat endpoints. Network I/O is
performed by callers from a worker thread, never from the Qt GUI thread.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class OllamaError(RuntimeError):
    """An Ollama server, protocol, or model error."""


class OllamaClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        *,
        timeout: float = 20.0,
        model_load_timeout: float = 900.0,
    ):
        self.base_url = self._normalize_base_url(base_url)
        self.timeout = max(1.0, float(timeout))
        # Loading a cold model can take minutes on consumer hardware. Keep this
        # separate from the short API discovery timeout.
        self.model_load_timeout = max(self.timeout, float(model_load_timeout))

    @staticmethod
    def _normalize_base_url(value: str) -> str:
        base_url = str(value or "").strip().rstrip("/")
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Ollama URL must be an absolute http:// or https:// URL.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Ollama URL must not contain credentials, a query, or a fragment.")
        if parsed.path not in {"", "/"}:
            raise ValueError("Enter the Ollama server base URL without an API path.")
        return base_url

    def _open(self, request: Request, *, timeout: float | None = None):
        request_timeout = self.timeout if timeout is None else max(1.0, float(timeout))
        try:
            return urlopen(request, timeout=request_timeout)
        except HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                detail = str(exc)
            raise OllamaError(f"Ollama returned HTTP {exc.code}: {detail[:1200]}") from exc
        except URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, TimeoutError):
                raise OllamaError(
                    f"Ollama timed out while opening {request.full_url} "
                    f"(waited {request_timeout:g}s). Check that the local Ollama server is responsive."
                ) from exc
            raise OllamaError(
                f"Cannot reach Ollama at {self.base_url} while requesting "
                f"{request.full_url} ({reason}). Start Ollama and verify its URL."
            ) from exc
        except TimeoutError as exc:
            raise OllamaError(
                f"Ollama request to {request.full_url} timed out after {request_timeout:g}s."
            ) from exc

    def _json_request(
        self,
        method: str,
        endpoint: str,
        payload: dict | None = None,
        *,
        timeout: float | None = None,
    ):
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            f"{self.base_url}{endpoint}",
            data=body,
            method=method,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        request_timeout = self.timeout if timeout is None else max(1.0, float(timeout))
        try:
            with self._open(request, timeout=request_timeout) as response:
                raw = response.read()
        except OllamaError:
            raise
        except TimeoutError as exc:
            raise OllamaError(
                f"Ollama timed out while reading {endpoint} after {request_timeout:g}s."
            ) from exc
        except (OSError, ValueError) as exc:
            raise OllamaError(f"Ollama request to {endpoint} failed: {exc}") from exc
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OllamaError("Ollama returned invalid JSON.") from exc
        if isinstance(data, dict) and data.get("error"):
            raise OllamaError(str(data["error"]))
        return data

    def list_models(self) -> list[dict[str, str]]:
        data = self._json_request("GET", "/api/tags")
        raw_models = data.get("models", []) if isinstance(data, dict) else []
        models = []
        for item in raw_models:
            if not isinstance(item, dict):
                continue
            details = item.get("details")
            if not isinstance(details, dict):
                details = {}
            name = str(item.get("name") or item.get("model") or "").strip()
            if name:
                models.append({
                    "name": name,
                    "size": str(item.get("size") or ""),
                    "modified_at": str(item.get("modified_at") or ""),
                    "family": str(details.get("family") or ""),
                    "parameter_size": str(details.get("parameter_size") or ""),
                    "quantization": str(details.get("quantization_level") or ""),
                })
        return sorted(models, key=lambda item: item["name"].casefold())

    def load_model(
        self,
        model: str,
        *,
        keep_alive: str = "30m",
        timeout: float | None = None,
    ) -> dict:
        selected = str(model or "").strip()
        if not selected:
            raise ValueError("Select an installed Ollama model first.")
        # Ollama responds only after a cold model has been loaded. This can take
        # much longer than /api/tags, so use a dedicated, generous timeout.
        # Do not unload on disconnect: another local application may share Ollama.
        return self._json_request(
            "POST",
            "/api/chat",
            {"model": selected, "messages": [], "stream": False, "keep_alive": keep_alive},
            timeout=self.model_load_timeout if timeout is None else timeout,
        )

    def chat(
        self,
        model: str,
        messages: Iterable[dict[str, str]],
        *,
        keep_alive: str = "30m",
        on_chunk: Callable[[str], None] | None = None,
        timeout: float = 900.0,
    ) -> dict:
        selected = str(model or "").strip()
        if not selected:
            raise ValueError("Select an installed Ollama model first.")
        normalized = [
            {"role": str(item["role"]), "content": str(item.get("content") or "")}
            for item in messages
            if item.get("role") in {"system", "user", "assistant"}
        ]
        if not normalized:
            raise ValueError("A chat message is required.")
        payload = json.dumps(
            {
                "model": selected,
                "messages": normalized,
                "stream": True,
                "keep_alive": keep_alive,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            f"{self.base_url}/api/chat",
            data=payload,
            method="POST",
            headers={"Accept": "application/x-ndjson", "Content-Type": "application/json"},
        )
        chunks: list[str] = []
        final: dict = {}
        try:
            with self._open(request, timeout=timeout) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else str(raw_line)
                    if not line.strip():
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise OllamaError("Ollama sent a malformed streaming response.") from exc
                    if item.get("error"):
                        raise OllamaError(str(item["error"]))
                    message = item.get("message") or {}
                    chunk = str(message.get("content") or "")
                    if chunk:
                        chunks.append(chunk)
                        if on_chunk:
                            on_chunk(chunk)
                    if item.get("done"):
                        final = item
        except OllamaError:
            raise
        except TimeoutError as exc:
            raise OllamaError(
                f"Ollama chat stream for '{selected}' was idle for too long "
                f"(socket timeout {timeout:g}s)."
            ) from exc
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise OllamaError(f"Ollama chat stream failed: {exc}") from exc
        if not final and not chunks:
            raise OllamaError("Ollama closed the chat stream without returning a response.")
        return {
            "model": selected,
            "text": "".join(chunks),
            "done": bool(final.get("done", False)),
            "done_reason": final.get("done_reason"),
            "metrics": {
                key: final[key]
                for key in ("total_duration", "load_duration", "prompt_eval_count", "eval_count")
                if key in final
            },
        }
