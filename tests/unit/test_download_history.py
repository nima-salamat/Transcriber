from __future__ import annotations

import pytest
from types import SimpleNamespace

from transcriber.storage.database import Database
from transcriber.storage.downloads import DownloadRepository


def _repository(tmp_path):
    return DownloadRepository(Database(tmp_path / "download-history.sqlite3"))


@pytest.mark.parametrize("state", ["failed", "cancelled", "paused", "stopped", "installed"])
def test_terminal_download_task_can_be_removed_from_history(tmp_path, state):
    repository = _repository(tmp_path)
    repository.enqueue("task-1", "publisher/model", "revision-a", "/models/model")
    repository.update("task-1", state=state, error="failure details" if state == "failed" else None)

    assert repository.delete("task-1") is True
    assert repository.get("task-1") is None


@pytest.mark.parametrize(
    "state",
    ["queued", "inspecting", "downloading", "validating", "installing", "pausing", "stopping", "cancelling"],
)
def test_active_download_task_cannot_be_removed(tmp_path, state):
    repository = _repository(tmp_path)
    repository.enqueue("task-1", "publisher/model", "revision-a", "/models/model")
    repository.update("task-1", state=state)

    with pytest.raises(RuntimeError, match="Cannot remove a download"):
        repository.delete("task-1")

    assert repository.get("task-1") is not None


def test_removing_missing_download_task_is_idempotent(tmp_path):
    repository = _repository(tmp_path)

    assert repository.delete("missing-task") is False



def test_model_manager_reads_shared_download_ledger_once(tmp_path):
    from transcriber.models.manager import ModelManager

    repository = _repository(tmp_path)
    repository.enqueue("hub-task", "publisher/model", "rev-a", "/models/hub")
    repository.enqueue(
        "vosk-task", "vosk/vosk-model-small-fa-0.42", "checksum-b",
        "/models/vosk", {"runtime": "vosk"},
    )
    manager = object.__new__(ModelManager)
    manager.downloader = SimpleNamespace(job_repository=repository)
    manager.vosk_downloader = SimpleNamespace(
        list_jobs=lambda: [job for job in repository.list() if job["metadata"].get("runtime") == "vosk"]
    )

    jobs = manager.list_download_jobs()

    assert [job["task_id"] for job in jobs] == ["vosk-task", "hub-task"]


def test_model_manager_removes_history_entry_without_deleting_model_files(tmp_path):
    from transcriber.models.manager import ModelManager

    repository = _repository(tmp_path)
    repository.enqueue("failed-task", "publisher/model", "rev-a", "/models/model")
    repository.update("failed-task", state="failed", error="test failure")
    manager = object.__new__(ModelManager)
    manager.downloader = SimpleNamespace(job_repository=repository)

    assert manager.remove_download_job("failed-task")
    assert repository.get("failed-task") is None
