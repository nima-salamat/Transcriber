"""Pinned-revision Hub downloads with real byte progress, cancellation, and staging."""

from __future__ import annotations

import json
import logging
import re
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from transcriber.core.errors import DownloadCancelled, ModelCompatibilityError
from transcriber.models.compatibility import require_faster_whisper_compatible, validate_repo_id
from transcriber.models.hub_client import HuggingFaceHubClient
from transcriber.models.registry import ModelRegistry

logger = logging.getLogger("transcriber.models.downloader")


def _redact_error(message: str) -> str:
    """Remove common credential and signed-URL secret forms from diagnostics."""
    value = str(message)[:1000]
    value = re.sub(
        r"(?i)(authorization|access[_-]?token|api[_-]?key|password|token)\s*[:=]\s*[^,;\s]+",
        r"\1=[redacted]",
        value,
    )
    value = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", value)
    value = re.sub(r"(?i)(https?://)[^/@:\s]+:[^/@\s]+@", r"\1[redacted]@", value)
    value = re.sub(
        r"(?i)([?&](?:signature|sig|x-amz-signature|x-amz-credential|token|access_token)=)[^&\s]+",
        r"\1[redacted]",
        value,
    )
    return value

class DownloadPaused(Exception):
    """A user-requested pause reached a cancellable transfer boundary."""


class DownloadStopped(Exception):
    """A user-requested stop reached a cancellable transfer boundary."""


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
        *, max_concurrent: int = 2, job_repository=None,
    ):
        self.hub = hub
        self.registry = registry
        self.cache_dir = Path(cache_dir)
        self.job_repository = job_repository
        self._condition = threading.Condition(threading.RLock())
        self._active: dict[str, threading.Event] = {}
        self._pending: dict[str, threading.Event] = {}
        self._pause_events: dict[str, threading.Event] = {}
        self._stop_events: dict[str, threading.Event] = {}
        self._job_ids: dict[str, str] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._max_concurrent = max(1, min(int(max_concurrent), 8))

    def set_max_concurrent(self, value: int) -> None:
        with self._condition:
            self._max_concurrent = max(1, min(int(value), 8))
            self._condition.notify_all()

    def cancel(self, repo_id: str) -> bool:
        with self._condition:
            key = validate_repo_id(repo_id)
            event = self._cancel_events.get(key) or self._active.get(key) or self._pending.get(key)
            if event is None:
                return False
            event.set()
            task_id = self._job_ids.get(key)
            if task_id and self.job_repository:
                self.job_repository.update(task_id, state="cancelling")
            self._condition.notify_all()
            return True

    def pause(self, repo_id: str) -> bool:
        with self._condition:
            key = validate_repo_id(repo_id)
            event = self._pause_events.get(key)
            if event is None:
                return False
            event.set()
            task_id = self._job_ids.get(key)
            if task_id and self.job_repository:
                self.job_repository.update(task_id, state="pausing")
            self._condition.notify_all()
            return True

    def stop(self, repo_id: str) -> bool:
        with self._condition:
            key = validate_repo_id(repo_id)
            event = self._stop_events.get(key)
            if event is None:
                return False
            event.set()
            task_id = self._job_ids.get(key)
            if task_id and self.job_repository:
                self.job_repository.update(task_id, state="stopping")
            self._condition.notify_all()
            return True

    def list_jobs(self, limit: int = 500) -> list[dict]:
        return self.job_repository.list(limit=limit) if self.job_repository else []

    @staticmethod
    def _remove_path(path: Path) -> bool:
        """Remove one app-owned staging path without following symbolic links."""
        if path.is_symlink():
            path.unlink()
            return True
        if path.is_dir():
            shutil.rmtree(path)
            return True
        if path.is_file():
            path.unlink()
            return True
        return False

    def remove_download_artifacts(self, job: dict) -> int:
        """Delete this task's staging data and incomplete/revision-pinned HF cache.

        Hugging Face blobs shared with other model revisions are retained by the
        cache manager's delete strategy. Only incomplete files under this model's
        cache namespace are removed directly.
        """
        repo_id = validate_repo_id(str(job.get("repo_id") or ""))
        task_id = str(job.get("task_id") or "")
        if not task_id:
            raise ValueError("Download task identifier is missing.")

        with self._condition:
            if (
                repo_id in self._active or repo_id in self._pending
                or repo_id in self._cancel_events
            ):
                raise RuntimeError(f"Cannot delete files while {repo_id} is downloading.")

        removed_bytes = 0
        staging_root = self.registry.root / ".staging"
        staging = staging_root / f"{self.registry.directory_name(repo_id)}-{task_id}"
        if staging.parent == staging_root and self._remove_path(staging):
            removed_bytes += 1

        if not self.cache_dir.exists() or self.cache_dir.is_symlink():
            return removed_bytes

        try:
            from huggingface_hub import scan_cache_dir
        except ImportError:
            return removed_bytes

        cache_info = scan_cache_dir(cache_dir=self.cache_dir)
        repo_cache = self.cache_dir / f"models--{repo_id.replace('/', '--')}"
        blobs_dir = repo_cache / "blobs"
        for incomplete in cache_info.incomplete_files:
            partial = Path(incomplete.file_path)
            # The path must be an immediate file in this model's blobs folder.
            # This avoids touching incomplete downloads belonging to another repo.
            if partial.parent == blobs_dir and partial.name.endswith(".incomplete"):
                if partial.is_symlink():
                    partial.unlink()
                elif partial.is_file():
                    partial.unlink()
                    removed_bytes += 1

        revision = str(job.get("revision") or "").strip()
        if revision:
            matching = [
                revision_info.commit_hash
                for cached_repo in cache_info.repos
                if cached_repo.repo_id == repo_id
                for revision_info in cached_repo.revisions
                if revision_info.commit_hash == revision
            ]
            if matching:
                # The Hugging Face cache manager preserves any blob referenced by
                # another revision/repository.
                scan_cache_dir(cache_dir=self.cache_dir).delete_revisions(*matching).execute()
                removed_bytes += 1
        return removed_bytes

    def resume(self, task_id: str, *, progress=None, cancel_event=None) -> Path:
        if self.job_repository is None:
            raise RuntimeError("Persistent download history is unavailable.")
        job = self.job_repository.get(task_id)
        if job is None:
            raise KeyError(task_id)
        if job["state"] not in {"paused", "stopped", "failed"}:
            raise RuntimeError(f"Download cannot resume from state: {job['state']}")
        return self.download(
            job["repo_id"],
            revision=job.get("revision"),
            cancel_event=cancel_event,
            progress=progress,
            task_id=job["task_id"],
            metadata=job.get("metadata") or {},
        )

    def cancel_all(self) -> int:
        """Request cancellation for active and queued downloads."""
        with self._condition:
            tasks = list({id(event): event for event in self._cancel_events.values()}.values())
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

    def _enter_download_slot(
        self, repo_id: str, cancel_event: threading.Event,
        pause_event: threading.Event, stop_event: threading.Event,
    ) -> None:
        with self._condition:
            if repo_id in self._active or repo_id in self._pending:
                raise RuntimeError(f"A download for {repo_id} is already queued or active")
            if cancel_event.is_set():
                raise DownloadCancelled("Download cancelled before it entered the queue")
            if pause_event.is_set():
                raise DownloadPaused("Download paused before entering the transfer queue")
            if stop_event.is_set():
                raise DownloadStopped("Download stopped before entering the transfer queue")
            self._pending[repo_id] = cancel_event
            while len(self._active) >= self._max_concurrent:
                if cancel_event.is_set():
                    self._pending.pop(repo_id, None)
                    self._condition.notify_all()
                    raise DownloadCancelled("Queued download cancelled by user")
                if pause_event.is_set():
                    self._pending.pop(repo_id, None)
                    self._condition.notify_all()
                    raise DownloadPaused("Queued download paused by user")
                if stop_event.is_set():
                    self._pending.pop(repo_id, None)
                    self._condition.notify_all()
                    raise DownloadStopped("Queued download stopped by user")
                self._condition.wait(timeout=0.2)
            self._pending.pop(repo_id, None)
            if cancel_event.is_set():
                self._condition.notify_all()
                raise DownloadCancelled("Download cancelled before transfer")
            if pause_event.is_set():
                self._condition.notify_all()
                raise DownloadPaused("Download paused before transfer")
            if stop_event.is_set():
                self._condition.notify_all()
                raise DownloadStopped("Download stopped before transfer")
            self._active[repo_id] = cancel_event

    def clear_cache(self) -> None:
        """Clear the shared Hub cache while preventing queued/new transfers from starting."""
        with self._condition:
            if self._active or self._pending or self._cancel_events:
                raise RuntimeError("Cannot clear the Hugging Face cache while downloads are queued or active")
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            shutil.rmtree(self.cache_dir, ignore_errors=False)
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def download(
        self, repo_id: str, *, revision: str | None = None,
        cancel_event: threading.Event | None = None,
        progress: Callable[[DownloadProgress], None] | None = None,
        task_id: str | None = None, metadata: dict | None = None,
    ) -> Path:
        repo_id = validate_repo_id(repo_id)
        cancel_event = cancel_event or threading.Event()
        task_id = task_id or uuid.uuid4().hex
        pause_event = threading.Event()
        stop_event = threading.Event()
        with self._condition:
            if repo_id in self._pause_events or repo_id in self._active or repo_id in self._pending:
                raise RuntimeError(f"A download for {repo_id} is already queued or active")
            self._pause_events[repo_id] = pause_event
            self._stop_events[repo_id] = stop_event
            self._cancel_events[repo_id] = cancel_event
            self._job_ids[repo_id] = task_id

        staging = self.registry.root / ".staging" / f"{self.registry.directory_name(repo_id)}-{task_id}"
        target = self.registry.root / self.registry.directory_name(repo_id)
        started = time.monotonic()
        downloaded = 0
        last_saved_bytes = -1_048_576
        last_saved_time = 0.0
        last_saved_state = ""
        job_metadata = dict(metadata or {})
        pinned_revision = revision

        def emit(state: str, total: int | None = None, message: str = "") -> None:
            nonlocal last_saved_bytes, last_saved_time, last_saved_state
            if progress:
                elapsed = max(0.001, time.monotonic() - started)
                progress(DownloadProgress(
                    state=state,
                    downloaded_bytes=downloaded,
                    total_bytes=total,
                    speed_bytes_per_second=downloaded / elapsed if downloaded else None,
                    message=message,
                ))
            if self.job_repository:
                now = time.monotonic()
                if (
                    state != last_saved_state
                    or downloaded - last_saved_bytes >= 1_048_576
                    or now - last_saved_time >= 1.0
                ):
                    self.job_repository.update(
                        task_id,
                        state=state.casefold(),
                        revision=pinned_revision,
                        downloaded_bytes=downloaded,
                        total_bytes=total,
                        metadata=job_metadata,
                    )
                    last_saved_bytes = downloaded
                    last_saved_time = now
                    last_saved_state = state

        try:
            # Persist the job before waiting for a concurrency slot so a queued
            # download survives restart and can be explicitly resumed.
            if self.job_repository:
                self.job_repository.enqueue(
                    task_id, repo_id, revision, str(target), job_metadata,
                )
            emit("Queued", message="Waiting for an available download slot")
            self._enter_download_slot(repo_id, cancel_event, pause_event, stop_event)

            emit("Inspecting", message="Reading repository metadata from Hugging Face")
            inspected = self.hub.inspect(repo_id, revision=revision)
            if not inspected.revision:
                raise RuntimeError("Hugging Face did not provide a pinned repository revision")
            pinned_revision = inspected.revision
            job_metadata.update({
                "license": inspected.license,
                "task": inspected.task,
                "languages": list(inspected.languages or []),
                "file_count": len(inspected.files),
            })
            if self.job_repository:
                self.job_repository.update(
                    task_id, state="inspecting", revision=pinned_revision, metadata=job_metadata,
                )
            if cancel_event.is_set():
                raise DownloadCancelled("Download cancelled during inspection")
            if pause_event.is_set():
                raise DownloadPaused("Download paused after inspection")
            if stop_event.is_set():
                raise DownloadStopped("Download stopped after inspection")

            file_names = [item.name for item in inspected.files]
            report = require_faster_whisper_compatible(file_names)
            chosen = list(report.included_files)
            size_by_name = {item.name: item.size for item in inspected.files}
            known_sizes = [size_by_name.get(name) for name in chosen]
            total = sum(value for value in known_sizes if value is not None) if all(
                value is not None for value in known_sizes
            ) else None
            required_space = (total or 0) + 64 * 1024 * 1024
            if shutil.disk_usage(self.registry.root).free < required_space:
                raise OSError("Not enough free disk space for this model and staging overhead")
            if cancel_event.is_set():
                raise DownloadCancelled("Download cancelled before transfer")
            if pause_event.is_set():
                raise DownloadPaused("Download paused before transfer")
            if stop_event.is_set():
                raise DownloadStopped("Download stopped before transfer")

            if staging.is_symlink():
                raise ValueError("Refusing to use a symbolic-link staging directory.")
            if staging.exists():
                # A previous process may have exited before cleanup. Any
                # reusable partial blobs remain in the shared Hub cache.
                shutil.rmtree(staging)
            staging.mkdir(parents=True, exist_ok=False)
            emit("Downloading", total=total, message="Downloading pinned model files")
            try:
                from huggingface_hub import hf_hub_download
                from tqdm.auto import tqdm
            except ImportError as exc:
                raise RuntimeError(
                    "Install Faster-Whisper with pip install 'transcriber-desktop[asr]'"
                ) from exc

            class ProgressTqdm(tqdm):
                def update(self, n=1):
                    nonlocal downloaded
                    if pause_event.is_set():
                        raise DownloadPaused("Download paused by user")
                    if stop_event.is_set():
                        raise DownloadStopped("Download stopped by user")
                    if cancel_event.is_set():
                        raise DownloadCancelled("Download cancelled by user")
                    result = super().update(n)
                    downloaded += max(0, int(n))
                    emit("Downloading", total=total)
                    return result

            # The Hub cache is shared and revision-pinned. The disposable staging
            # directory is rebuilt on resume while cached file blobs are reused.
            for filename in chosen:
                if pause_event.is_set():
                    raise DownloadPaused("Download paused by user")
                if stop_event.is_set():
                    raise DownloadStopped("Download stopped by user")
                if cancel_event.is_set():
                    raise DownloadCancelled("Download cancelled by user")
                hf_hub_download(
                    repo_id=repo_id,
                    filename=filename,
                    revision=inspected.revision,
                    cache_dir=str(self.cache_dir),
                    local_dir=str(staging),
                    tqdm_class=ProgressTqdm,
                )
                # Count completed local artefacts too: a cache hit does not
                # generate network-byte callbacks but still completes work.
                downloaded = sum(
                    (staging / name).stat().st_size
                    for name in chosen[:chosen.index(filename) + 1]
                    if (staging / name).is_file()
                )
                emit("Downloading", total=total, message=f"Prepared {filename}")
            if pause_event.is_set():
                raise DownloadPaused("Download paused before validation")
            if stop_event.is_set():
                raise DownloadStopped("Download stopped before validation")
            if cancel_event.is_set():
                raise DownloadCancelled("Download cancelled before validation")

            emit("Validating", total=total, message="Checking required model artefacts")
            installed_files = [
                item.relative_to(staging).as_posix()
                for item in staging.rglob("*")
                if item.is_file()
            ]
            final_report = require_faster_whisper_compatible(installed_files)
            manifest = {
                "repo_id": repo_id,
                "revision": inspected.revision,
                "engine": "faster-whisper",
                "files": list(final_report.included_files),
                "license": inspected.license,
            }
            (staging / ".transcriber-model.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            emit("Installing", total=total, message="Atomically registering the validated model")
            backup = self.registry.root / ".staging" / (
                f"{self.registry.directory_name(repo_id)}-previous-{task_id}"
            )
            if target.exists():
                target.rename(backup)
            try:
                staging.rename(target)
                self.registry.register(
                    repo_id,
                    target,
                    revision=inspected.revision,
                    files=list(final_report.included_files),
                    license_name=inspected.license,
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
        except DownloadPaused:
            emit("Paused", message="Transfer paused; shared Hugging Face cache is preserved for resume")
            if self.job_repository:
                self.job_repository.update(task_id, state="paused", revision=pinned_revision)
            raise
        except DownloadStopped:
            emit("Stopped", message="Transfer stopped; shared Hugging Face cache is preserved")
            if self.job_repository:
                self.job_repository.update(task_id, state="stopped", revision=pinned_revision)
            raise
        except DownloadCancelled:
            emit("Cancelled", message="Download cancelled; shared Hugging Face cache is preserved")
            if self.job_repository:
                self.job_repository.update(task_id, state="cancelled", revision=pinned_revision)
            raise
        except ModelCompatibilityError:
            emit("Failed", message="Repository is not compatible with Faster-Whisper")
            if self.job_repository:
                self.job_repository.update(
                    task_id, state="failed", revision=pinned_revision,
                    error="Repository is not compatible with Faster-Whisper",
                )
            raise
        except Exception as exc:
            safe_message = _redact_error(str(exc))
            # Keep logs useful without recording arbitrary Hub exception text,
            # which may contain authorization headers or signed request URLs.
            logger.error("Model download failed for %s (%s)", repo_id, type(exc).__name__)
            emit("Failed", message=safe_message)
            if self.job_repository:
                self.job_repository.update(
                    task_id, state="failed", revision=pinned_revision, error=safe_message,
                )
            raise RuntimeError(safe_message) from exc
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            with self._condition:
                self._active.pop(repo_id, None)
                self._pending.pop(repo_id, None)
                self._pause_events.pop(repo_id, None)
                self._stop_events.pop(repo_id, None)
                self._cancel_events.pop(repo_id, None)
                self._job_ids.pop(repo_id, None)
                self._condition.notify_all()
