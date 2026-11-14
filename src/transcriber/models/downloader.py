"""Pinned-revision Hub downloads with real byte progress, cancellation, and staging."""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from transcriber.core.errors import DownloadCancelled, ModelCompatibilityError
from transcriber.models.compatibility import require_faster_whisper_compatible, validate_repo_id
from transcriber.models.hub_client import HuggingFaceHubClient
from transcriber.models.registry import ModelRegistry

logger = logging.getLogger("transcriber.models.downloader")


@dataclass(frozen=True, slots=True)
class DownloadProgress:
    state: str
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed_bytes_per_second: float | None = None
    message: str = ""

    @property
    def percent(self) -> float | None:
        if not self.total_bytes:
            return None
        return min(100.0, self.downloaded_bytes / self.total_bytes * 100)

    @property
    def eta_seconds(self) -> float | None:
        if not self.speed_bytes_per_second or self.total_bytes is None:
            return None
        return max(0.0, (self.total_bytes - self.downloaded_bytes) / self.speed_bytes_per_second)


class ModelDownloader:
    def __init__(
        self, hub: HuggingFaceHubClient, registry: ModelRegistry, cache_dir: Path,
        *, max_concurrent: int = 2,
    ):
        self.hub = hub
        self.registry = registry
        self.cache_dir = Path(cache_dir)
        self._condition = threading.Condition(threading.RLock())
        self._active: dict[str, threading.Event] = {}
        self._pending: dict[str, threading.Event] = {}
        self._max_concurrent = max(1, min(int(max_concurrent), 8))

    def set_max_concurrent(self, value: int) -> None:
        with self._condition:
            self._max_concurrent = max(1, min(int(value), 8))
            self._condition.notify_all()

    def cancel(self, repo_id: str) -> bool:
        with self._condition:
            key = validate_repo_id(repo_id)
            event = self._active.get(key) or self._pending.get(key)
            if event is None:
                return False
            event.set()
            self._condition.notify_all()
            return True

    def cancel_all(self) -> int:
        """Request cancellation for active and queued downloads."""
        with self._condition:
            tasks = list(self._active.values()) + list(self._pending.values())
            for event in tasks:
                event.set()
            self._condition.notify_all()
            return len(tasks)

    @property
    def active_count(self) -> int:
        with self._condition:
            return len(self._active)

    @property
    def pending_count(self) -> int:
        with self._condition:
            return len(self._pending)

    def _enter_download_slot(self, repo_id: str, cancel_event: threading.Event) -> None:
        with self._condition:
            if repo_id in self._active or repo_id in self._pending:
                raise RuntimeError(f"A download for {repo_id} is already queued or active")
            if cancel_event.is_set():
                raise DownloadCancelled("Download cancelled before it entered the queue")
            self._pending[repo_id] = cancel_event
            while len(self._active) >= self._max_concurrent:
                if cancel_event.is_set():
                    self._pending.pop(repo_id, None)
                    self._condition.notify_all()
                    raise DownloadCancelled("Queued download cancelled by user")
                self._condition.wait(timeout=0.2)
            self._pending.pop(repo_id, None)
            if cancel_event.is_set():
                self._condition.notify_all()
                raise DownloadCancelled("Download cancelled before transfer")
            self._active[repo_id] = cancel_event

    def clear_cache(self) -> None:
        """Clear the shared Hub cache while preventing queued/new transfers from starting."""
        with self._condition:
            if self._active or self._pending:
                raise RuntimeError("Cannot clear the Hugging Face cache while downloads are queued or active")
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            shutil.rmtree(self.cache_dir, ignore_errors=False)
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def download(
        self, repo_id: str, *, revision: str | None = None,
        cancel_event: threading.Event | None = None,
        progress: Callable[[DownloadProgress], None] | None = None,
    ) -> Path:
        repo_id = validate_repo_id(repo_id)
        cancel_event = cancel_event or threading.Event()
        self._enter_download_slot(repo_id, cancel_event)
        task_id = uuid.uuid4().hex
        staging = self.registry.root / ".staging" / f"{self.registry.directory_name(repo_id)}-{task_id}"
        target = self.registry.root / self.registry.directory_name(repo_id)
        started = time.monotonic()
        downloaded = 0

        def emit(state: str, total: int | None = None, message: str = "") -> None:
            if progress:
                elapsed = max(0.001, time.monotonic() - started)
                progress(DownloadProgress(
                    state=state, downloaded_bytes=downloaded, total_bytes=total,
                    speed_bytes_per_second=downloaded / elapsed if downloaded else None,
                    message=message,
                ))

        try:
            emit("Inspecting", message="Reading repository metadata from Hugging Face")
            metadata = self.hub.inspect(repo_id, revision=revision)
            if not metadata.revision:
                raise RuntimeError("Hugging Face did not provide a pinned repository revision")
            file_names = [item.name for item in metadata.files]
            report = require_faster_whisper_compatible(file_names)
            chosen = list(report.included_files)
            size_by_name = {item.name: item.size for item in metadata.files}
            known_sizes = [size_by_name.get(name) for name in chosen]
            total = sum(value for value in known_sizes if value is not None) if all(
                value is not None for value in known_sizes
            ) else None
            if shutil.disk_usage(self.registry.root).free < (total or 0) + 64 * 1024 * 1024:
                raise OSError("Not enough free disk space for this model and staging overhead")
            if cancel_event.is_set():
                raise DownloadCancelled("Download cancelled before transfer")
            staging.mkdir(parents=True, exist_ok=False)
            emit("Downloading", total=total, message="Downloading pinned model files")

            try:
                from tqdm.auto import tqdm
                from huggingface_hub import hf_hub_download
            except ImportError as exc:
                raise RuntimeError("Install Faster-Whisper with pip install 'transcriber-desktop[asr]'") from exc

            class ProgressTqdm(tqdm):
                def update(self, n=1):
                    nonlocal downloaded
                    if cancel_event.is_set():
                        raise DownloadCancelled("Download cancelled by user")
                    result = super().update(n)
                    downloaded += max(0, int(n))
                    emit("Downloading", total=total)
                    return result

            # Use Hub's cache/resume mechanism; local_dir provides a staged working tree.
            for filename in chosen:
                if cancel_event.is_set():
                    raise DownloadCancelled("Download cancelled by user")
                hf_hub_download(
                    repo_id=repo_id, filename=filename, revision=metadata.revision,
                    cache_dir=str(self.cache_dir), local_dir=str(staging),
                    tqdm_class=ProgressTqdm,
                )
            if cancel_event.is_set():
                raise DownloadCancelled("Download cancelled by user")
            emit("Validating", total=total, message="Checking required model artefacts")
            installed_files = [item.relative_to(staging).as_posix() for item in staging.rglob("*") if item.is_file()]
            final_report = require_faster_whisper_compatible(installed_files)
            manifest = {
                "repo_id": repo_id, "revision": metadata.revision,
                "engine": "faster-whisper", "files": list(final_report.included_files),
                "license": metadata.license,
            }
            (staging / ".transcriber-model.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            backup = self.registry.root / ".staging" / f"{self.registry.directory_name(repo_id)}-previous-{task_id}"
            if target.exists():
                target.rename(backup)
            try:
                staging.rename(target)
                self.registry.register(
                    repo_id, target, revision=metadata.revision,
                    files=list(final_report.included_files), license_name=metadata.license,
                )
            except Exception:
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
                if backup.exists():
                    backup.rename(target)
                raise
            shutil.rmtree(backup, ignore_errors=True)
            emit("Installed", total=total, message="Model installed and validated")
            return target
        except DownloadCancelled:
            emit("Cancelled", message="Download cancelled; incomplete staging files removed")
            raise
        except ModelCompatibilityError:
            emit("Failed", message="Repository is not compatible with Faster-Whisper")
            raise
        except Exception as exc:
            logger.exception("Model download failed for %s", repo_id)
            emit("Failed", message=str(exc))
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            with self._condition:
                self._active.pop(repo_id, None)
                self._condition.notify_all()
