"""Small, dependency-free client for a local Ollama server.

Uses Ollama's documented /api/tags and /api/chat endpoints. Network I/O is
performed by callers from a worker thread, never from the Qt GUI thread.
"""

from __future__ import annotations

import http.client
import json
import socket
import ssl
from collections.abc import Callable, Iterable
from threading import Event, Lock
from urllib.parse import urlsplit
from urllib.request import Request


class _ManagedHTTPResponse:
    """Keep the HTTP connection available so cancellation can interrupt header reads."""

    def __init__(self, connection, response):
        self._connection = connection
        self._response = response

    @property
    def sock(self):
        return self._connection.sock

    def read(self, *args, **kwargs):
        return self._response.read(*args, **kwargs)

    def __iter__(self):
        return iter(self._response)

    def close(self):
        try:
            self._response.close()
        finally:
            self._connection.close()


class OllamaError(RuntimeError):
    """An Ollama server, protocol, or model error."""


class OllamaCancelled(OllamaError):
    """A local chat generation was cancelled by the user."""


class OllamaCancellation:
    """Thread-safe cancellation token that also closes an active streaming response."""

    def __init__(self):
        self._event = Event()
        self._lock = Lock()
        self._response = None

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def event(self):
        """Expose the cancellation event to permission-aware action dispatchers."""
        return self._event

    def attach(self, response) -> None:
        with self._lock:
            self._response = response
            cancelled = self._event.is_set()
        if cancelled:
            self._close_response(response)

    def detach(self, response) -> None:
        with self._lock:
            if self._response is response:
                self._response = None

    @staticmethod
    def _close_response(response) -> None:
        """Interrupt a blocking HTTP read before closing its response object.

        HTTPResponse.close() alone may not wake a thread blocked in socket.makefile
        while Ollama is generating a long response. Shutting down the underlying
        socket first makes the blocked iterator/read return promptly.
        """
        candidates = [response]
        seen = set()
        while candidates:
            current = candidates.pop()
            if current is None or id(current) in seen:
                continue
            seen.add(id(current))
            sock = (
                current if isinstance(current, socket.socket)
                else getattr(current, "sock", None) or getattr(current, "_sock", None)
            )
            if sock is not None:
                shutdown = getattr(sock, "shutdown", None)
                if callable(shutdown):
                    try:
                        shutdown(socket.SHUT_RDWR)
                    except (OSError, ValueError):
                        pass
            for attribute in ("fp", "raw", "buffer", "_sock", "sock"):
                nested = getattr(current, attribute, None)
                if nested is not None and id(nested) not in seen:
                    candidates.append(nested)

        close = getattr(response, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    def cancel(self) -> None:
        self._event.set()
        with self._lock:
            response = self._response
        if response is not None:
            self._close_response(response)

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise OllamaCancelled("Generation stopped by the user.")


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

    def _open(
        self,
        request: Request,
        *,
        timeout: float | None = None,
        cancellation: OllamaCancellation | None = None,
    ):
        request_timeout = self.timeout if timeout is None else max(1.0, float(timeout))
        parsed = urlsplit(request.full_url)
        connection = None
        managed = None
        succeeded = False
        try:
            if parsed.scheme == "https":
                connection = http.client.HTTPSConnection(
                    parsed.hostname, parsed.port, timeout=request_timeout,
                    context=ssl.create_default_context(),
                )
            else:
                connection = http.client.HTTPConnection(
                    parsed.hostname, parsed.port, timeout=request_timeout,
                )

            # Attach before request()/getresponse(). A cold Ollama model may delay
            # HTTP headers until it is resident in RAM/VRAM. Attaching only after
            # headers arrive leaves this entire first-load interval uncancellable.
            if cancellation:
                cancellation.raise_if_cancelled()
                cancellation.attach(connection)

            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            connection.request(
                request.get_method(), path, body=request.data,
                headers=dict(request.header_items()),
            )
            if cancellation:
                cancellation.raise_if_cancelled()

            response = connection.getresponse()
            managed = _ManagedHTTPResponse(connection, response)
            if cancellation:
                cancellation.attach(managed)
                cancellation.raise_if_cancelled()

            if response.status >= 400:
                detail = managed.read().decode("utf-8", errors="replace")
                raise OllamaError(
                    f"Ollama returned HTTP {response.status}: {detail[:1200]}"
                )

            succeeded = True
            return managed
        except OllamaCancelled:
            raise
        except TimeoutError as exc:
            if cancellation and cancellation.cancelled:
                raise OllamaCancelled("Ollama request was cancelled.") from exc
            raise OllamaError(
                f"Ollama request to {request.full_url} timed out after {request_timeout:g}s."
            ) from exc
        except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
            if cancellation and cancellation.cancelled:
                raise OllamaCancelled("Ollama request was cancelled.") from exc
            raise OllamaError(
                f"Cannot reach Ollama at {self.base_url} while requesting "
                f"{request.full_url} ({exc}). Start Ollama and verify its URL."
            ) from exc
        finally:
            if not succeeded and connection is not None:
                if cancellation:
                    cancellation.detach(managed)
                    cancellation.detach(connection)
                try:
                    if managed is not None:
                        managed.close()
                    else:
                        connection.close()
                except Exception:
                    pass

    def _json_request(
        self,
        method: str,
        endpoint: str,
        payload: dict | None = None,
        *,
        timeout: float | None = None,
        cancellation: OllamaCancellation | None = None,
    ):
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            f"{self.base_url}{endpoint}",
            data=body,
            method=method,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        request_timeout = self.timeout if timeout is None else max(1.0, float(timeout))
        response = None
        try:
            if cancellation:
                cancellation.raise_if_cancelled()
            response = self._open(request, timeout=request_timeout, cancellation=cancellation)
            if cancellation:
                cancellation.attach(response)
            raw = response.read()
        except OllamaCancelled:
            raise
        except OllamaError:
            if cancellation and cancellation.cancelled:
                raise OllamaCancelled("Ollama model loading was cancelled.")
            raise
        except TimeoutError as exc:
            if cancellation and cancellation.cancelled:
                raise OllamaCancelled("Ollama model loading was cancelled.") from exc
            raise OllamaError(
                f"Ollama timed out while reading {endpoint} after {request_timeout:g}s."
            ) from exc
        except (OSError, ValueError) as exc:
            if cancellation and cancellation.cancelled:
                raise OllamaCancelled("Ollama model loading was cancelled.") from exc
            raise OllamaError(f"Ollama request to {endpoint} failed: {exc}") from exc
        finally:
            if cancellation and response is not None:
                cancellation.detach(response)
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OllamaError("Ollama returned invalid JSON.") from exc
        if isinstance(data, dict) and data.get("error"):
            raise OllamaError(str(data["error"]))
        return data

    def list_models(
        self, *, cancellation: OllamaCancellation | None = None
    ) -> list[dict[str, str]]:
        data = self._json_request("GET", "/api/tags", cancellation=cancellation)
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

    def show_model(
        self, model: str, *, cancellation: OllamaCancellation | None = None
    ) -> dict:
        """Read /api/show metadata, including the model's supported thinking controls."""
        selected = str(model or "").strip()
        if not selected:
            raise ValueError("Select an installed Ollama model first.")
        result = self._json_request(
            "POST", "/api/show", {"model": selected}, cancellation=cancellation
        )
        return result if isinstance(result, dict) else {}

    @staticmethod
    def thinking_option(show_result: dict | None) -> bool | str | None:
        """Choose a supported thinking value, preferring the model's advertised default."""
        metadata = show_result.get("thinking") if isinstance(show_result, dict) else None
        if not isinstance(metadata, dict):
            return None
        values = metadata.get("values")
        if not isinstance(values, list) or not values:
            return None
        default = metadata.get("default")
        if isinstance(default, (bool, str)) and default in values and default is not False:
            return default
        if True in values:
            return True
        named = next((value for value in values if isinstance(value, str) and value), None)
        return named

    def load_model(
        self,
        model: str,
        *,
        keep_alive: str = "30m",
        timeout: float | None = None,
        cancellation: OllamaCancellation | None = None,
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
            cancellation=cancellation,
        )

    def chat(
        self,
        model: str,
        messages: Iterable[dict],
        *,
        keep_alive: str = "30m",
        on_chunk: Callable[[str], None] | None = None,
        on_thinking: Callable[[str], None] | None = None,
        tools: Iterable[dict] | None = None,
        cancellation: OllamaCancellation | None = None,
        think: bool | str | None = None,
        timeout: float = 900.0,
    ) -> dict:
        """Stream a chat turn, including tool-call messages supported by Ollama."""
        selected = str(model or "").strip()
        if not selected:
            raise ValueError("Select an installed Ollama model first.")

        normalized = []
        for item in messages:
            role = str(item.get("role") or "")
            if role not in {"system", "user", "assistant", "tool"}:
                continue
            message = {"role": role, "content": str(item.get("content") or "")}
            if role == "tool" and item.get("tool_name"):
                message["tool_name"] = str(item["tool_name"])
            if role == "assistant" and item.get("tool_calls"):
                message["tool_calls"] = item["tool_calls"]
            if role == "assistant" and item.get("thinking"):
                message["thinking"] = str(item["thinking"])
            normalized.append(message)
        if not normalized:
            raise ValueError("A chat message is required.")

        tool_list = [item for item in (tools or []) if isinstance(item, dict)]
        payload_data = {
            "model": selected,
            "messages": normalized,
            "stream": True,
            "keep_alive": keep_alive,
        }
        if tool_list:
            payload_data["tools"] = tool_list
        if think is not None:
            payload_data["think"] = think
        payload = json.dumps(payload_data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = Request(
            f"{self.base_url}/api/chat",
            data=payload,
            method="POST",
            headers={"Accept": "application/x-ndjson", "Content-Type": "application/json"},
        )
        chunks: list[str] = []
        thinking_chunks: list[str] = []
        tool_calls: list[dict] = []
        final: dict = {}
        response = None
        try:
            if cancellation:
                cancellation.raise_if_cancelled()
            response = self._open(request, timeout=timeout, cancellation=cancellation)
            if cancellation:
                cancellation.attach(response)
            for raw_line in response:
                if cancellation:
                    cancellation.raise_if_cancelled()
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
                thinking = str(message.get("thinking") or "")
                if thinking:
                    thinking_chunks.append(thinking)
                    if on_thinking:
                        on_thinking(thinking)
                chunk = str(message.get("content") or "")
                if chunk:
                    chunks.append(chunk)
                    if on_chunk:
                        on_chunk(chunk)
                for call in message.get("tool_calls") or []:
                    if isinstance(call, dict) and call not in tool_calls:
                        tool_calls.append(call)
                if item.get("done"):
                    final = item
        except OllamaCancelled:
            raise
        except OllamaError:
            if cancellation and cancellation.cancelled:
                raise OllamaCancelled("Generation stopped by the user.")
            raise
        except TimeoutError as exc:
            if cancellation and cancellation.cancelled:
                raise OllamaCancelled("Generation stopped by the user.") from exc
            raise OllamaError(
                f"Ollama chat stream for '{selected}' was idle for too long "
                f"(socket timeout {timeout:g}s)."
            ) from exc
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            if cancellation and cancellation.cancelled:
                raise OllamaCancelled("Generation stopped by the user.") from exc
            raise OllamaError(f"Ollama chat stream failed: {exc}") from exc
        finally:
            if cancellation and response is not None:
                cancellation.detach(response)
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass

        final_message = final.get("message") or {}
        for call in final_message.get("tool_calls") or []:
            if isinstance(call, dict) and call not in tool_calls:
                tool_calls.append(call)
        if not final and not chunks and not tool_calls:
            raise OllamaError("Ollama closed the chat stream without returning a response.")
        return {
            "model": selected,
            "text": "".join(chunks),
            "thinking": "".join(thinking_chunks),
            "tool_calls": tool_calls,
            "done": bool(final.get("done", False)),
            "done_reason": final.get("done_reason"),
            "metrics": {
                key: final[key]
                for key in ("total_duration", "load_duration", "prompt_eval_count", "eval_count")
                if key in final
            },
        }
