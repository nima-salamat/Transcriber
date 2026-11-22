from __future__ import annotations

import time

from transcriber.transcription.jobs import JobQueue, JobStatus


def wait_for_terminal(queue, job_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        job = queue.get(job_id)
        if job and job.status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}:
            return job
        time.sleep(0.01)
    raise AssertionError("Job did not reach a terminal state")


def test_job_queue_tracks_progress_result_and_timestamps():
    queue = JobQueue(max_workers=1)
    try:
        job = queue.submit("test", lambda cancel, update: (update(50, "Halfway"), "done")[1])
        completed = wait_for_terminal(queue, job.job_id)
        assert completed.status is JobStatus.SUCCEEDED
        assert completed.progress == 100
        assert completed.result == "done"
        assert completed.started_at and completed.finished_at
    finally:
        queue.shutdown()


def test_job_queue_cancellation_is_cooperative():
    queue = JobQueue(max_workers=1)
    try:
        def run(cancel, update):
            while not cancel.is_set():
                time.sleep(0.005)
            raise InterruptedError("Stopped")
        job = queue.submit("long-task", run)
        assert queue.cancel(job.job_id)
        completed = wait_for_terminal(queue, job.job_id)
        assert completed.status is JobStatus.CANCELLED
    finally:
        queue.shutdown()


def test_job_queue_rejects_new_work_after_shutdown():
    queue = JobQueue(max_workers=1)
    queue.shutdown()
    try:
        queue.submit("too-late", lambda cancel, update: None)
    except RuntimeError as exc:
        assert "shutting down" in str(exc)
    else:
        raise AssertionError("Shutdown queue accepted a new job")
