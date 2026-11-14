from __future__ import annotations

import pytest

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
