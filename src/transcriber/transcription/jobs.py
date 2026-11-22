"""Bounded job execution and lifecycle tracking."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class JobStatus(StrEnum):
    QUEUED = "Queued"
    RUNNING = "Running"
    SUCCEEDED = "Succeeded"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


@dataclass(slots=True)
class Job:
    job_id: str
    job_type: str
    status: JobStatus = JobStatus.QUEUED
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    started_at: str | None = None
    finished_at: str | None = None
    progress: float | None = None
    message: str = "Queued"
    error: str | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    result: Any = field(default=None, repr=False)


class JobQueue:
    """Small generic executor with a hard concurrency bound and cooperative cancel."""

    def __init__(self, max_workers: int = 2):
        self._executor = ThreadPoolExecutor(max_workers=max(1, min(max_workers, 8)),
                                            thread_name_prefix="transcriber-job")
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}
        self._futures: dict[str, Future] = {}
        self._closed = False

    def submit(self, job_type: str, function: Callable[[threading.Event, Callable[[float, str], None]], Any]) -> Job:
        with self._lock:
            if self._closed:
                raise RuntimeError("Job queue is shutting down")
            job = Job(job_id=str(uuid.uuid4()), job_type=job_type)
            self._jobs[job.job_id] = job

            def update(percent: float, message: str = "") -> None:
                with self._lock:
                    job.progress = max(0.0, min(100.0, float(percent)))
                    job.message = message or job.message

            def run():
                with self._lock:
                    if job.cancel_event.is_set():
                        job.status = JobStatus.CANCELLED
                        job.finished_at = datetime.now(UTC).isoformat()
                        return None
                    job.status = JobStatus.RUNNING
                    job.started_at = datetime.now(UTC).isoformat()
                    job.message = "Running"
                try:
                    result = function(job.cancel_event, update)
                    with self._lock:
                        job.result = result
                        job.status = JobStatus.CANCELLED if job.cancel_event.is_set() else JobStatus.SUCCEEDED
                        job.progress = 100.0 if job.status == JobStatus.SUCCEEDED else job.progress
                        job.message = job.status.value
                    return result
                except InterruptedError as exc:
                    with self._lock:
                        job.status = JobStatus.CANCELLED
                        job.message = str(exc) or "Cancelled"
                    return None
                except Exception as exc:
                    with self._lock:
                        job.status = JobStatus.FAILED
                        job.error = str(exc)
                        job.message = "Failed"
                    raise
                finally:
                    with self._lock:
                        job.finished_at = datetime.now(UTC).isoformat()

            self._futures[job.job_id] = self._executor.submit(run)
            return job

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}:
                return False
            job.cancel_event.set()
            future = self._futures.get(job_id)
            if future and future.cancel():
                job.status = JobStatus.CANCELLED
                job.finished_at = datetime.now(UTC).isoformat()
            return True

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def shutdown(self, wait: bool = True) -> None:
        with self._lock:
            self._closed = True
            for job in self._jobs.values():
                if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                    job.cancel_event.set()
        self._executor.shutdown(wait=wait, cancel_futures=True)
