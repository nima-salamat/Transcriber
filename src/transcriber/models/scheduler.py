"""Stable priority scheduler for model and audio jobs.

Real-time and interactive work can jump ahead of batch/background jobs. The
scheduler is intentionally runtime-agnostic; adapters decide how to invoke a
model and receive a cooperative cancellation Event.
"""

from __future__ import annotations

import itertools
import queue
import threading
import uuid
from concurrent.futures import Future
from concurrent.futures import CancelledError
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any, Callable


class JobPriority(IntEnum):
    WAKE_WORD = 0
    ACTIVE_VOICE_COMMAND = 10
    LIVE_TRANSCRIPTION = 20
    INTERACTIVE_INFERENCE = 30
    TRANSCRIPTION = 40
    BATCH = 50
    MODEL_MAINTENANCE = 60


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class ScheduledJob:
    job_id: str
    priority: JobPriority
    callback: Callable[[threading.Event], Any] = field(repr=False)
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    future: Future = field(default_factory=Future, repr=False)
    status: JobStatus = JobStatus.QUEUED
    error: str | None = None


class PriorityModelScheduler:
    """Bounded worker pool with stable priority order and cooperative cancel."""

    def __init__(self, workers: int = 1):
        self._queue: queue.PriorityQueue = queue.PriorityQueue()
        self._sequence = itertools.count()
        self._jobs: dict[str, ScheduledJob] = {}
        self._lock = threading.RLock()
        self._closed = False
        self._threads = [
            threading.Thread(target=self._worker, name=f"Transcriber-model-{index + 1}", daemon=True)
            for index in range(max(1, min(8, int(workers))))
        ]
        for thread in self._threads:
            thread.start()

    def submit(self, callback: Callable[[threading.Event], Any], *,
               priority: JobPriority = JobPriority.TRANSCRIPTION) -> ScheduledJob:
        if not callable(callback):
            raise TypeError("callback must be callable")
        with self._lock:
            if self._closed:
                raise RuntimeError("The model scheduler is shut down")
            job = ScheduledJob(uuid.uuid4().hex, JobPriority(priority), callback)
            self._jobs[job.job_id] = job
            self._queue.put((int(job.priority), next(self._sequence), job))
            return job

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
                return False
            job.cancel_event.set()
            if job.status == JobStatus.QUEUED:
                job.status = JobStatus.CANCELLED
                job.future.cancel()
            return True

    def status(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {"job_id": job.job_id, "priority": job.priority.name.lower(),
                 "status": job.status.value, "error": job.error}
                for job in self._jobs.values()
            ]

    def _worker(self) -> None:
        while True:
            _priority, _sequence, job = self._queue.get()
            try:
                if job is None:
                    return
                with self._lock:
                    if self._closed and job.status == JobStatus.QUEUED:
                        job.cancel_event.set()
                        job.status = JobStatus.CANCELLED
                    if job.status == JobStatus.CANCELLED or job.cancel_event.is_set():
                        if not job.future.done():
                            job.future.cancel()
                        continue
                    job.status = JobStatus.RUNNING
                    job.future.set_running_or_notify_cancel()
                try:
                    result = job.callback(job.cancel_event)
                    if job.cancel_event.is_set():
                        with self._lock:
                            job.status = JobStatus.CANCELLED
                        if not job.future.done():
                            job.future.set_exception(CancelledError("Job cancelled during execution"))
                    else:
                        with self._lock:
                            job.status = JobStatus.COMPLETED
                        job.future.set_result(result)
                except Exception as exc:
                    with self._lock:
                        job.status = JobStatus.FAILED
                        job.error = f"{type(exc).__name__}: {exc}"
                    job.future.set_exception(exc)
            finally:
                self._queue.task_done()

    def shutdown(self, *, cancel_pending: bool = True, wait: bool = True) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if cancel_pending:
                for job in self._jobs.values():
                    if job.status == JobStatus.QUEUED:
                        job.cancel_event.set()
                        job.status = JobStatus.CANCELLED
                        job.future.cancel()
            for _ in self._threads:
                self._queue.put((10**9, next(self._sequence), None))
        if wait:
            for thread in self._threads:
                thread.join(timeout=5)
