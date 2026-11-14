"""Atomic local model registry and guarded filesystem operations."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from transcriber.core.errors import ActiveModelError
from transcriber.models.compatibility import validate_faster_whisper_files, validate_repo_id


class ModelRegistry:
    def __init__(self, root: Path, registry_path: Path):
        self.root = Path(root).resolve()
        self.registry_path = Path(registry_path)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._models: dict[str, dict[str, Any]] = {}
        self.load()

    @staticmethod
    def directory_name(repo_id: str) -> str:
        repo_id = validate_repo_id(repo_id)
        return repo_id.replace("/", "--")

    def load(self) -> None:
        with self._lock:
            try:
                data = json.loads(self.registry_path.read_text(encoding="utf-8"))
                models = data.get("models", {}) if isinstance(data, dict) else {}
                self._models = {
                    validate_repo_id(key): value for key, value in models.items()
                    if isinstance(value, dict)
                }
            except FileNotFoundError:
                self._models = {}
            except (OSError, ValueError, TypeError):
                self._models = {}

    def _write(self) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".models-", suffix=".tmp", dir=self.registry_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"version": 1, "models": self._models}, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.registry_path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def list_installed(self, *, include_sizes: bool = True) -> list[dict[str, Any]]:
        with self._lock:
            result = []
            for repo_id, metadata in self._models.items():
                path = self.root / self.directory_name(repo_id)
                if path.is_dir() and not path.is_symlink():
                    item = dict(metadata)
                    item.update(
                        repo_id=repo_id, path=str(path),
                        size_bytes=self._size(path) if include_sizes else None,
                    )
                    result.append(item)
            return sorted(result, key=lambda item: item["repo_id"].casefold())

    @staticmethod
    def _size(path: Path) -> int:
        total = 0
        for item in path.rglob("*"):
            if item.is_file() and not item.is_symlink():
                try:
                    total += item.stat().st_size
                except OSError:
                    pass
        return total

    def register(self, repo_id: str, path: Path, *, revision: str,
                 files: list[str], license_name: str | None = None) -> None:
        repo_id = validate_repo_id(repo_id)
        raw_path = Path(path)
        if raw_path.is_symlink():
            raise ValueError("Installed model path cannot be a symbolic link")
        resolved = raw_path.resolve()
        if resolved.parent != self.root or not resolved.is_dir():
            raise ValueError("Installed model path must be a direct child of the managed model directory")
        manifest_path = resolved / ".transcriber-model.json"
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise ValueError("Validated model manifest is missing")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("Validated model manifest is unreadable") from exc
        if not isinstance(manifest, dict):
            raise ValueError("Validated model manifest must be a JSON object")
        if manifest.get("repo_id") != repo_id or manifest.get("revision") != revision:
            raise ValueError("Model manifest does not match the repository and pinned revision")
        report = validate_faster_whisper_files(files)
        if not report.compatible:
            raise ValueError(report.reason)
        with self._lock:
            previous = self._models.get(repo_id)
            self._models[repo_id] = {
                "revision": revision, "files": sorted(files), "license": license_name,
                "installed_at": datetime.now(UTC).isoformat(),
            }
            try:
                self._write()
            except Exception:
                if previous is None:
                    self._models.pop(repo_id, None)
                else:
                    self._models[repo_id] = previous
                raise

    def count_installed(self) -> int:
        """Count registered models without recursively scanning their files."""
        with self._lock:
            return sum(
                1 for repo_id in self._models
                if (self.root / self.directory_name(repo_id)).is_dir()
                and not (self.root / self.directory_name(repo_id)).is_symlink()
            )

    def get_path(self, repo_id: str) -> Path | None:
        repo_id = validate_repo_id(repo_id)
        path = self.root / self.directory_name(repo_id)
        manifest = path / ".transcriber-model.json"
        return path if (
            path.is_dir() and not path.is_symlink()
            and manifest.is_file() and not manifest.is_symlink()
        ) else None

    def delete(self, repo_id: str, *, active_model_id: str | None = None) -> None:
        repo_id = validate_repo_id(repo_id)
        if active_model_id and repo_id == active_model_id:
            raise ActiveModelError("Unload or switch away from this model before deleting it")
        with self._lock:
            path = self.root / self.directory_name(repo_id)
            if path.is_symlink():
                raise ValueError("Refusing to remove a symbolic link from the model directory")
            if not path.exists():
                self._models.pop(repo_id, None)
                self._write()
                return
            resolved = path.resolve()
            if resolved.parent != self.root:
                raise ValueError("Refusing to remove a path outside the managed model directory")
            staging = self.root / ".staging"
            staging.mkdir(parents=True, exist_ok=True)
            quarantine = staging / f"delete-{self.directory_name(repo_id)}-{os.getpid()}"
            if quarantine.exists():
                raise RuntimeError("A previous model deletion is still being recovered")
            path.rename(quarantine)
            previous = self._models.pop(repo_id, None)
            try:
                self._write()
            except Exception:
                if previous is not None:
                    self._models[repo_id] = previous
                quarantine.rename(path)
                raise
        shutil.rmtree(quarantine, ignore_errors=True)

