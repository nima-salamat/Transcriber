from __future__ import annotations

import threading
from types import SimpleNamespace

import huggingface_hub
import pytest

from transcriber.core.errors import DownloadCancelled, ModelCompatibilityError
from transcriber.models.downloader import ModelDownloader
from transcriber.models.hub_client import HubFile
from transcriber.models.registry import ModelRegistry

MODEL_FILES = [
    HubFile("config.json", 3), HubFile("model.bin", 7),
    HubFile("tokenizer.json", 5), HubFile("vocabulary.txt", 5),
]


class FakeHub:
    def __init__(self, files=None):
        self.files = tuple(files if files is not None else MODEL_FILES)

    def inspect(self, repo_id, revision=None):
        return SimpleNamespace(
            repo_id=repo_id, revision="a1b2c3d4", files=self.files, license="mit",
        )


def fake_hf_download(repo_id, filename, revision, cache_dir, local_dir, tqdm_class):
    assert revision == "a1b2c3d4"
    bar = tqdm_class(total=next(item.size for item in MODEL_FILES if item.name == filename), disable=True)
    bar.update(bar.total)
    bar.close()
    target = __import__("pathlib").Path(local_dir) / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"x" * next(item.size for item in MODEL_FILES if item.name == filename))
    return str(target)


def test_download_installs_only_after_validation_and_reports_real_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", fake_hf_download)
    root = tmp_path / "models"
    registry = ModelRegistry(root, tmp_path / "registry.json")
    downloader = ModelDownloader(FakeHub(), registry, tmp_path / "cache")
    updates = []

    installed = downloader.download("publisher/model", progress=updates.append)

    assert installed.is_dir()
    assert (installed / "model.bin").stat().st_size == 7
    assert registry.get_path("publisher/model") == installed
    assert any(item.state == "Downloading" and item.downloaded_bytes > 0 for item in updates)
    assert updates[-1].state == "Installed"
    assert updates[-1].percent == 100


def test_download_cancellation_removes_staging_and_does_not_register_model(tmp_path, monkeypatch):
    def interrupting_download(repo_id, filename, revision, cache_dir, local_dir, tqdm_class):
        bar = tqdm_class(total=10, disable=True)
        bar.update(5)
        bar.close()
        target = __import__("pathlib").Path(local_dir) / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x" * 5)
        return str(target)

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", interrupting_download)
    registry = ModelRegistry(tmp_path / "models", tmp_path / "registry.json")
    downloader = ModelDownloader(FakeHub(), registry, tmp_path / "cache")
    cancelled = threading.Event()

    def progress(item):
        if item.state == "Downloading" and item.downloaded_bytes:
            cancelled.set()

    with pytest.raises(DownloadCancelled):
        downloader.download("publisher/model", cancel_event=cancelled, progress=progress)

    assert registry.get_path("publisher/model") is None
    assert list((tmp_path / "models" / ".staging").iterdir()) == []


def test_incompatible_hub_repository_is_rejected_before_any_download(tmp_path, monkeypatch):
    def should_not_download(**kwargs):
        raise AssertionError("Incompatible model must not be downloaded")

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", should_not_download)
    bad_hub = FakeHub([HubFile("config.json", 1), HubFile("pytorch_model.bin", 2)])
    registry = ModelRegistry(tmp_path / "models", tmp_path / "registry.json")
    downloader = ModelDownloader(bad_hub, registry, tmp_path / "cache")

    with pytest.raises(ModelCompatibilityError):
        downloader.download("publisher/model")
    assert registry.get_path("publisher/model") is None


def test_download_queue_is_bounded_and_cancelled_pending_job_never_starts(tmp_path, monkeypatch):
    first_started = threading.Event()
    allow_first_to_finish = threading.Event()
    downloads = []

    def blocking_download(repo_id, filename, revision, cache_dir, local_dir, tqdm_class):
        downloads.append((repo_id, filename))
        if repo_id == "publisher/first":
            first_started.set()
            assert allow_first_to_finish.wait(5)
        return fake_hf_download(repo_id, filename, revision, cache_dir, local_dir, tqdm_class)

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", blocking_download)
    registry = ModelRegistry(tmp_path / "models", tmp_path / "registry.json")
    downloader = ModelDownloader(FakeHub(), registry, tmp_path / "cache", max_concurrent=1)
    outcomes = {}

    def run(repo_id):
        try:
            outcomes[repo_id] = downloader.download(repo_id)
        except Exception as exc:  # captured for assertions in the main test thread
            outcomes[repo_id] = exc

    first = threading.Thread(target=run, args=("publisher/first",), daemon=True)
    second = threading.Thread(target=run, args=("publisher/second",), daemon=True)
    first.start()
    assert first_started.wait(5)
    second.start()

    try:
        for _ in range(50):
            if downloader.pending_count:
                break
            threading.Event().wait(0.02)
        assert downloader.active_count == 1
        assert downloader.pending_count == 1
        with pytest.raises(RuntimeError, match="Cannot clear"):
            downloader.clear_cache()
        assert downloader.cancel("publisher/second")
    finally:
        allow_first_to_finish.set()

    first.join(10)
    second.join(10)
    assert not first.is_alive() and not second.is_alive()
    assert isinstance(outcomes["publisher/first"], __import__("pathlib").Path)
    assert isinstance(outcomes["publisher/second"], DownloadCancelled)
    assert all(repo_id != "publisher/second" for repo_id, _ in downloads)
    assert registry.get_path("publisher/first") is not None
    assert registry.get_path("publisher/second") is None


def test_clear_cache_creates_missing_cache_directory(tmp_path):
    registry = ModelRegistry(tmp_path / "models", tmp_path / "registry.json")
    cache = tmp_path / "cache-does-not-exist"
    downloader = ModelDownloader(FakeHub(), registry, cache)

    downloader.clear_cache()

    assert cache.is_dir()
    assert list(cache.iterdir()) == []
