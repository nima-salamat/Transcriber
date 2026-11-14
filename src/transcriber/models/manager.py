"""High-level model discovery, installation, active-model protection, and cleanup."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from transcriber.models.compatibility import validate_repo_id, validate_faster_whisper_files
from transcriber.models.downloader import ModelDownloader
from transcriber.models.hub_client import HuggingFaceHubClient, HubModel
from transcriber.models.registry import ModelRegistry
from transcriber.engines.faster_whisper import FasterWhisperEngine


class ModelManager:
    def __init__(self, registry: ModelRegistry, hub: HuggingFaceHubClient,
                 downloader: ModelDownloader):
        self.registry = registry
        self.hub = hub
        self.downloader = downloader
        self._lock = threading.RLock()
        # Serialize model swaps/load/unload. A second worker must not detach a
        # model while the first worker is still materializing it in RAM.
        self._operation_lock = threading.RLock()
        self._active_model_id: str | None = None
        self._active_engine: FasterWhisperEngine | None = None
        self._active_options: tuple | None = None
        self._installing: set[str] = set()

    @property
    def active_downloads(self) -> int:
        with self._lock:
            return len(self._installing)

    def set_download_concurrency(self, value: int) -> None:
        self.downloader.set_max_concurrent(value)

    def clear_download_cache(self) -> None:
        # Keep the install reservation lock while the lower-level cache lock is held
        # so a new queued task cannot race the cleanup operation.
        with self._lock:
            if self._installing:
                raise RuntimeError("Cannot clear the model cache while downloads are queued or active")
            self.downloader.clear_cache()

    @property
    def active_model_id(self) -> str | None:
        with self._lock:
            return self._active_model_id

    def search(self, query: str = "", *, sort: str = "downloads", limit: int = 30) -> list[HubModel]:
        return self.hub.search(query, sort=sort, limit=limit)

    def inspect(self, repo_id: str) -> tuple[HubModel, object]:
        model = self.hub.inspect(validate_repo_id(repo_id))
        report = validate_faster_whisper_files(item.name for item in model.files)
        return model, report

    def install(self, repo_id: str, *, revision: str | None = None,
                cancel_event=None, progress=None) -> Path:
        repo_id = validate_repo_id(repo_id)
        with self._lock:
            if repo_id == self._active_model_id:
                raise RuntimeError("Unload the active model before reinstalling it")
            if repo_id in self._installing:
                raise RuntimeError(f"A download for {repo_id} is already active")
            self._installing.add(repo_id)
        try:
            return self.downloader.download(repo_id, revision=revision,
                                            cancel_event=cancel_event, progress=progress)
        finally:
            with self._lock:
                self._installing.discard(repo_id)

    def get_engine(self, repo_id: str, settings=None) -> FasterWhisperEngine:
        repo_id = validate_repo_id(repo_id)
        with self._operation_lock, self._lock:
            if repo_id in self._installing:
                raise RuntimeError("Wait for model installation to finish before loading it")
            model_path = self.registry.get_path(repo_id)
            if model_path is None:
                raise FileNotFoundError(f"Model is not installed or its manifest is missing: {repo_id}")
            manifest = json.loads((model_path / ".transcriber-model.json").read_text(encoding="utf-8"))
            files = manifest.get("files", [])
            report = validate_faster_whisper_files(files)
            if not report.compatible or any(
                (model_path / name).is_symlink() or not (model_path / name).is_file()
                for name in report.included_files
            ):
                raise RuntimeError("Installed model is incomplete or corrupted. Reinstall it from Model Library.")
            options = (
                getattr(settings, "device", "auto"),
                getattr(settings, "compute_type", "int8"),
                getattr(settings, "cpu_threads", 0),
            )
            if self._active_engine and self._active_model_id == repo_id and self._active_options == options:
                return self._active_engine
            if self._active_engine:
                self._active_engine.unload()
            self._active_engine = FasterWhisperEngine(
                model_path, device=options[0], compute_type=options[1], cpu_threads=options[2],
            )
            self._active_options = options
            self._active_model_id = repo_id
            return self._active_engine

    def load(self, repo_id: str, settings=None) -> FasterWhisperEngine:
        """Materialize the model in memory. Invoke from a background worker."""
        with self._operation_lock:
            engine = self.get_engine(repo_id, settings)
            engine.load()
            return engine

    def unload_active(self) -> None:
        with self._operation_lock, self._lock:
            if self._active_engine:
                self._active_engine.unload()
            self._active_engine = None
            self._active_model_id = None
            self._active_options = None

    def set_active(self, repo_id: str | None) -> None:
        if repo_id is None:
            self.unload_active()
            return
        self.get_engine(repo_id)

    def installed(self, *, include_sizes: bool = True) -> list[dict]:
        """List installed models; full size scans should run in a worker thread."""
        results = []
        for item in self.registry.list_installed(include_sizes=include_sizes):
            path = Path(item["path"])
            registered_files = item.get("files") or []
            if include_sizes:
                actual_files = [
                    candidate.relative_to(path).as_posix()
                    for candidate in path.rglob("*")
                    if candidate.is_file() and not candidate.is_symlink()
                ]
            else:
                # Avoid an unbounded recursive filesystem scan in lightweight UI refreshes.
                actual_files = [
                    name for name in registered_files
                    if (path / name).is_file() and not (path / name).is_symlink()
                ]
            report = validate_faster_whisper_files(actual_files)
            manifest_path = path / ".transcriber-model.json"
            manifest_ok = manifest_path.is_file() and not manifest_path.is_symlink()
            item["compatible"] = report.compatible and manifest_ok
            item["compatibility_message"] = (
                report.reason if manifest_ok else "Model manifest is missing or invalid; reinstall this model."
            )
            item["active"] = item["repo_id"] == self.active_model_id
            results.append(item)
        return results

    def delete(self, repo_id: str) -> None:
        with self._lock:
            if repo_id in self._installing:
                raise RuntimeError("Wait for the model download to finish before deleting it")
            active = self._active_model_id
        self.registry.delete(repo_id, active_model_id=active)
