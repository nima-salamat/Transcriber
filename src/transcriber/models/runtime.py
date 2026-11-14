"""Resource-aware, lazy multi-model runtime manager.

This manager is intentionally generic: ASR, VAD, diarization and LLM adapters
can coexist when their adapters declare realistic resource estimates. The
existing Faster-Whisper application service remains a separate adapter until
its current single-active-model lifecycle is migrated behind this interface.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol


class ModelState(StrEnum):
    NOT_INSTALLED = "not_installed"
    INSTALLED = "installed"
    LOADING = "loading"
    LOADED = "loaded"
    RUNNING = "running"
    UNLOADING = "unloading"
    FAILED = "failed"


class ModelAdapter(Protocol):
    def load(self, spec: ModelSpec) -> Any: ...
    def unload(self, handle: Any) -> None: ...


@dataclass(slots=True)
class ModelSpec:
    model_id: str
    provider: str
    task: str
    runtime: str
    local_path: Path | None = None
    revision: str | None = None
    license: str | None = None
    size_bytes: int = 0
    required_ram_mb: int = 0
    required_vram_mb: int = 0
    languages: tuple[str, ...] = ()
    capabilities: frozenset[str] = frozenset()
    installed: bool = False
    quantization: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.model_id or not self.task or not self.runtime:
            raise ValueError("model_id, task and runtime are required")
        self.required_ram_mb = max(0, int(self.required_ram_mb))
        self.required_vram_mb = max(0, int(self.required_vram_mb))
        self.size_bytes = max(0, int(self.size_bytes))
        if self.local_path is not None:
            self.local_path = Path(self.local_path).expanduser()


@dataclass(slots=True)
class RuntimeEntry:
    spec: ModelSpec
    state: ModelState = ModelState.INSTALLED
    handle: Any = None
    pinned: bool = False
    active_calls: int = 0
    last_used: float = field(default_factory=time.monotonic)
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    ram_total_mb: int | None
    ram_available_mb: int | None
    vram_total_mb: int | None
    vram_available_mb: int | None


class ResourceMonitor:
    """Best-effort RAM/VRAM monitor. Unknown VRAM is never treated as unlimited."""

    def snapshot(self) -> ResourceSnapshot:
        ram_total = ram_available = None
        try:
            import psutil
            memory = psutil.virtual_memory()
            ram_total = int(memory.total // (1024 * 1024))
            ram_available = int(memory.available // (1024 * 1024))
        except ImportError:
            pass
        vram_total = vram_available = None
        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total,memory.free", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2, check=True,
            )
            rows = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            if rows:
                values = [[int(part.strip()) for part in row.split(",", 1)] for row in rows]
                vram_total = max(row[0] for row in values)
                vram_available = min(row[1] for row in values)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        return ResourceSnapshot(ram_total, ram_available, vram_total, vram_available)


class ResourceLimitError(RuntimeError):
    pass


class ModelRuntimeManager:
    def __init__(
        self,
        *,
        max_active_models: int = 2,
        ram_budget_mb: int = 8192,
        vram_budget_mb: int = 4096,
        monitor: ResourceMonitor | None = None,
        adapter_factory: Callable[[ModelSpec], ModelAdapter] | None = None,
    ):
        self.max_active_models = self._limit(max_active_models)
        self.ram_budget_mb = max(0, int(ram_budget_mb))
        self.vram_budget_mb = max(0, int(vram_budget_mb))
        self.monitor = monitor or ResourceMonitor()
        self.adapter_factory = adapter_factory
        self._entries: dict[str, RuntimeEntry] = {}
        self._adapters: dict[str, ModelAdapter] = {}
        self._lock = threading.RLock()
        # Loading one model can evict other models. Serialize this whole
        # transition so two concurrent requests cannot both pass the same
        # capacity check and exceed the configured RAM/VRAM/model budget.
        self._operation_lock = threading.RLock()

    @staticmethod
    def _limit(value: int) -> int:
        return max(1, min(10, int(value)))

    def configure(self, *, max_active_models: int | None = None,
                  ram_budget_mb: int | None = None, vram_budget_mb: int | None = None) -> None:
        with self._lock:
            if max_active_models is not None:
                self.max_active_models = self._limit(max_active_models)
            if ram_budget_mb is not None:
                self.ram_budget_mb = max(0, int(ram_budget_mb))
            if vram_budget_mb is not None:
                self.vram_budget_mb = max(0, int(vram_budget_mb))

    def register(self, spec: ModelSpec, adapter: ModelAdapter | None = None) -> None:
        with self._lock:
            if spec.model_id in self._entries:
                raise ValueError(f"Model already registered: {spec.model_id}")
            self._entries[spec.model_id] = RuntimeEntry(
                spec=spec, state=ModelState.INSTALLED if spec.installed else ModelState.NOT_INSTALLED,
            )
            if adapter is not None:
                self._adapters[spec.model_id] = adapter

    def remove(self, model_id: str) -> None:
        self.unload(model_id)
        with self._lock:
            self._entries.pop(model_id)
            self._adapters.pop(model_id, None)

    def pin(self, model_id: str, pinned: bool = True) -> None:
        with self._lock:
            self._get(model_id).pinned = bool(pinned)

    def state(self, model_id: str) -> ModelState:
        with self._lock:
            return self._get(model_id).state

    def status(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "model_id": entry.spec.model_id,
                    "task": entry.spec.task,
                    "runtime": entry.spec.runtime,
                    "state": entry.state.value,
                    "pinned": entry.pinned,
                    "active_calls": entry.active_calls,
                    "last_used": entry.last_used,
                    "error": entry.error,
                    "required_ram_mb": entry.spec.required_ram_mb,
                    "required_vram_mb": entry.spec.required_vram_mb,
                }
                for entry in self._entries.values()
            ]

    def load(self, model_id: str) -> Any:
        with self._operation_lock:
            return self._load_serialized(model_id)

    def _load_serialized(self, model_id: str) -> Any:
        with self._lock:
            entry = self._get(model_id)
            if entry.state in {ModelState.LOADED, ModelState.RUNNING}:
                entry.last_used = time.monotonic()
                return entry.handle
            if not entry.spec.installed:
                raise FileNotFoundError(f"Model is not installed: {model_id}")
            adapter = self._adapter_for(entry.spec)
            self._ensure_capacity(entry)
            entry.state = ModelState.LOADING
            entry.error = None
        try:
            handle = adapter.load(entry.spec)
        except Exception as exc:
            with self._lock:
                entry.state = ModelState.FAILED
                entry.error = f"{type(exc).__name__}: {exc}"
            raise
        with self._lock:
            entry.handle = handle
            entry.state = ModelState.LOADED
            entry.last_used = time.monotonic()
            return handle

    def unload(self, model_id: str) -> bool:
        with self._operation_lock:
            return self._unload_serialized(model_id)

    def _unload_serialized(self, model_id: str) -> bool:
        with self._lock:
            entry = self._get(model_id)
            if entry.state not in {ModelState.LOADED, ModelState.RUNNING, ModelState.FAILED}:
                return False
            if entry.active_calls:
                raise RuntimeError(f"Model is running and cannot be unloaded: {model_id}")
            adapter = self._adapter_for(entry.spec)
            handle = entry.handle
            entry.state = ModelState.UNLOADING
        try:
            if handle is not None:
                adapter.unload(handle)
        except Exception as exc:
            with self._lock:
                entry.state = ModelState.FAILED
                entry.error = f"{type(exc).__name__}: {exc}"
            raise
        with self._lock:
            entry.handle = None
            entry.state = ModelState.INSTALLED if entry.spec.installed else ModelState.NOT_INSTALLED
            entry.last_used = time.monotonic()
        return True

    @contextmanager
    def acquire(self, model_id: str) -> Iterator[Any]:
        # Prevent an unload/eviction between obtaining the handle and marking
        # it active. The operation lock is re-entrant, so the serialized load
        # path remains shared with ordinary load requests.
        with self._operation_lock:
            handle = self._load_serialized(model_id)
            with self._lock:
                entry = self._get(model_id)
                entry.active_calls += 1
                entry.state = ModelState.RUNNING
                entry.last_used = time.monotonic()
        try:
            yield handle
        finally:
            with self._lock:
                entry.active_calls = max(0, entry.active_calls - 1)
                entry.last_used = time.monotonic()
                entry.state = ModelState.RUNNING if entry.active_calls else ModelState.LOADED

    def _get(self, model_id: str) -> RuntimeEntry:
        try:
            return self._entries[model_id]
        except KeyError as exc:
            raise KeyError(f"Unknown model: {model_id}") from exc

    def _adapter_for(self, spec: ModelSpec) -> ModelAdapter:
        adapter = self._adapters.get(spec.model_id)
        if adapter is None and self.adapter_factory is not None:
            adapter = self.adapter_factory(spec)
            self._adapters[spec.model_id] = adapter
        if adapter is None:
            raise RuntimeError(f"No runtime adapter registered for {spec.runtime!r}")
        return adapter

    def _ensure_capacity(self, incoming: RuntimeEntry) -> None:
        loaded = [entry for entry in self._entries.values()
                  if entry.state in {ModelState.LOADED, ModelState.RUNNING}]
        projected_count = len(loaded) + 1
        ram_needed = sum(e.spec.required_ram_mb for e in loaded) + incoming.spec.required_ram_mb
        vram_needed = sum(e.spec.required_vram_mb for e in loaded) + incoming.spec.required_vram_mb
        snapshot = self.monitor.snapshot()
        ram_cap = self.ram_budget_mb
        vram_cap = self.vram_budget_mb
        if snapshot.ram_available_mb is not None:
            ram_cap = min(ram_cap, snapshot.ram_available_mb)
        if snapshot.vram_available_mb is not None:
            vram_cap = min(vram_cap, snapshot.vram_available_mb)
        # We do not assume unknown accelerator memory is free. Non-GPU specs remain eligible.
        over = lambda: projected_count > self.max_active_models or ram_needed > ram_cap or vram_needed > vram_cap
        while over():
            candidates = [entry for entry in loaded if not entry.pinned and entry.active_calls == 0
                          and entry.state == ModelState.LOADED]
            if not candidates:
                raise ResourceLimitError(
                    "Not enough model slots or memory. Unpin/unload another model, or increase the resource budget."
                )
            victim = min(candidates, key=lambda entry: entry.last_used)
            self.unload(victim.spec.model_id)
            loaded.remove(victim)
            projected_count -= 1
            ram_needed -= victim.spec.required_ram_mb
            vram_needed -= victim.spec.required_vram_mb
