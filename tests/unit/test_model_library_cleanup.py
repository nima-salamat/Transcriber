from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from transcriber.models import vosk
from transcriber.models.downloader import ModelDownloader
from transcriber.models.manager import ModelManager
from transcriber.models.registry import ModelRegistry
from transcriber.storage.database import Database
from transcriber.storage.downloads import DownloadRepository
from transcriber.ui.design.tokens import get_tokens
from transcriber.ui.pages.models import _card_frame_stylesheet


def _download_repository(tmp_path: Path) -> DownloadRepository:
    return DownloadRepository(Database(tmp_path / "history.sqlite3"))


def test_huggingface_cleanup_removes_only_its_partial_and_revision(tmp_path, monkeypatch):
    import huggingface_hub

    repo_id = "publisher/model"
    task_id = "task-123"
    revision = "a1b2c3d4"
    registry = ModelRegistry(tmp_path / "models", tmp_path / "registry.json")
    cache_dir = tmp_path / "hf-cache"
    repo_blobs = cache_dir / "models--publisher--model" / "blobs"
    other_blobs = cache_dir / "models--publisher--other" / "blobs"
    repo_blobs.mkdir(parents=True)
    other_blobs.mkdir(parents=True)
    own_partial = repo_blobs / "own.incomplete"
    other_partial = other_blobs / "other.incomplete"
    own_partial.write_bytes(b"unfinished-model")
    other_partial.write_bytes(b"other-model-data")

    staging = registry.root / ".staging" / "publisher--model-task-123"
    staging.mkdir(parents=True)
    (staging / "partial.bin").write_bytes(b"temporary")

    strategy_calls = []

    class FakeStrategy:
        def execute(self):
            strategy_calls.append("executed")

    revision_info = SimpleNamespace(commit_hash=revision)
    cached_repo = SimpleNamespace(repo_id=repo_id, revisions=[revision_info])
    cache_info = SimpleNamespace(
        incomplete_files=[
            SimpleNamespace(file_path=own_partial),
            SimpleNamespace(file_path=other_partial),
        ],
        repos=[cached_repo],
    )
    scanned = []

    def scan_cache_dir(*, cache_dir):
        scanned.append(Path(cache_dir))
        return cache_info

    monkeypatch.setattr(huggingface_hub, "scan_cache_dir", scan_cache_dir)
    # scan_cache_dir returns its cache info object; attach the cache API method.
    cache_info.delete_revisions = lambda *revisions: (
        strategy_calls.append(("revisions", revisions)) or FakeStrategy()
    )
    downloader = object.__new__(ModelDownloader)
    downloader.registry = registry
    downloader.cache_dir = cache_dir
    downloader._condition = threading.RLock()
    downloader._active = {}
    downloader._pending = {}
    downloader._cancel_events = {}

    removed = downloader.remove_download_artifacts({
        "repo_id": repo_id,
        "task_id": task_id,
        "revision": revision,
    })

    assert removed == 3
    assert not own_partial.exists()
    assert other_partial.read_bytes() == b"other-model-data"
    assert not staging.exists()
    assert ("revisions", (revision,)) in strategy_calls
    assert strategy_calls[-1] == "executed"
    assert scanned == [cache_dir, cache_dir]


def test_vosk_cleanup_removes_only_matching_partial_archive_and_staging(tmp_path):
    model_id = "vosk/vosk-model-small-fa-0.42"
    task_id = "task-vosk-1"
    checksum = "a" * 64
    algorithm = "sha256"
    key = hashlib.sha256((model_id + algorithm + checksum).encode("utf-8")).hexdigest()

    model_root = tmp_path / "models"
    model_root.mkdir()
    staging_root = model_root / ".staging"
    cache_root = staging_root / "vosk-download-cache"
    cache_root.mkdir(parents=True)
    partial = cache_root / f"{key}.zip.partial"
    partial.write_bytes(b"half-downloaded-archive")
    unrelated = cache_root / "unrelated.zip.partial"
    unrelated.write_bytes(b"keep-me")
    staging = staging_root / f"vosk-{key}-{task_id}"
    staging.mkdir()
    (staging / "extracted.part").write_bytes(b"partial")

    downloader = object.__new__(vosk.VoskModelDownloader)
    downloader.registry = SimpleNamespace(root=model_root)
    downloader._condition = threading.RLock()
    downloader._cancel_events = {}
    downloader._active = {}

    removed = downloader.remove_download_artifacts({
        "repo_id": model_id,
        "task_id": task_id,
        "revision": checksum,
        "metadata": {"checksum": checksum, "checksum_algorithm": algorithm},
    })

    assert removed == 2
    assert not partial.exists()
    assert not staging.exists()
    assert unrelated.read_bytes() == b"keep-me"


def test_model_manager_deletes_task_artifacts_before_removing_failed_history(tmp_path):
    repository = _download_repository(tmp_path)
    repository.enqueue("failed-task", "publisher/model", "rev-a", "/models/model")
    repository.update("failed-task", state="failed", error="test failure")
    cleanup_calls = []
    manager = object.__new__(ModelManager)
    manager.downloader = SimpleNamespace(
        job_repository=repository,
        remove_download_artifacts=lambda job: cleanup_calls.append(job["task_id"]),
    )
    manager.vosk_downloader = SimpleNamespace()
    manager._lock = threading.RLock()
    manager._installing = set()

    assert manager.remove_download_job("failed-task")
    assert cleanup_calls == ["failed-task"]
    assert repository.get("failed-task") is None


def test_model_manager_never_deletes_installed_model_artifacts_when_removing_history(tmp_path):
    repository = _download_repository(tmp_path)
    repository.enqueue("installed-task", "publisher/model", "rev-a", "/models/model")
    repository.update("installed-task", state="installed")
    cleanup_calls = []
    manager = object.__new__(ModelManager)
    manager.downloader = SimpleNamespace(
        job_repository=repository,
        remove_download_artifacts=lambda job: cleanup_calls.append(job["task_id"]),
    )
    manager.vosk_downloader = SimpleNamespace()
    manager._lock = threading.RLock()
    manager._installing = set()

    assert manager.remove_download_job("installed-task")
    assert cleanup_calls == []
    assert repository.get("installed-task") is None


def test_model_manager_rejects_removal_while_task_is_active(tmp_path):
    repository = _download_repository(tmp_path)
    repository.enqueue("active-task", "publisher/model", "rev-a", "/models/model")
    repository.update("active-task", state="downloading")
    manager = object.__new__(ModelManager)
    manager.downloader = SimpleNamespace(job_repository=repository)
    manager.vosk_downloader = SimpleNamespace()
    manager._lock = threading.RLock()
    manager._installing = set()

    with pytest.raises(RuntimeError, match="Cannot delete files while"):
        manager.remove_download_job("active-task")

    assert repository.get("active-task") is not None


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_model_card_stylesheets_have_balanced_qss_braces(theme):
    tokens = get_tokens(theme).colors
    for object_name, radius, accent in (
        ("DownloadTaskCard", 12, tokens["danger"]),
        ("InstalledModelCard", 13, tokens["success"]),
    ):
        stylesheet = _card_frame_stylesheet(object_name, tokens, accent, radius)
        assert stylesheet.count("{") == stylesheet.count("}")
        assert stylesheet.endswith("}")
        assert "}}" not in stylesheet
