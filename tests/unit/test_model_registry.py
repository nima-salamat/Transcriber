from __future__ import annotations

import json

import pytest

from transcriber.core.errors import ActiveModelError
from transcriber.models.registry import ModelRegistry

FILES = ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"]


def make_model(root, repo_id="publisher/model"):
    root.mkdir(parents=True, exist_ok=True)
    path = root / repo_id.replace("/", "--")
    path.mkdir(parents=True)
    for name in FILES:
        (path / name).write_bytes(b"model")
    (path / ".transcriber-model.json").write_text(
        json.dumps({"repo_id": repo_id, "revision": "abc123", "files": FILES}), encoding="utf-8"
    )
    return path


def test_registry_registration_and_restart_discovery(tmp_path):
    registry_path = tmp_path / "config" / "models.json"
    root = tmp_path / "models"
    root.mkdir()
    path = make_model(root)
    registry = ModelRegistry(root, registry_path)
    registry.register("publisher/model", path, revision="abc123", files=FILES, license_name="mit")

    loaded = ModelRegistry(root, registry_path)
    model = loaded.list_installed()[0]
    assert model["repo_id"] == "publisher/model"
    assert model["revision"] == "abc123"
    assert model["size_bytes"] == sum(item.stat().st_size for item in path.iterdir())
    assert loaded.count_installed() == 1


def test_registry_requires_manifest_and_compatible_files(tmp_path):
    root = tmp_path / "models"
    root.mkdir()
    bad = root / "publisher--bad"
    bad.mkdir()
    registry = ModelRegistry(root, tmp_path / "registry.json")
    with pytest.raises(ValueError, match="manifest"):
        registry.register("publisher/bad", bad, revision="abc", files=FILES)
    (bad / ".transcriber-model.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        registry.register("publisher/bad", bad, revision="abc", files=["pytorch_model.bin"])


def test_active_model_cannot_be_deleted_and_regular_delete_clears_registry(tmp_path):
    root = tmp_path / "models"
    root.mkdir()
    path = make_model(root)
    registry = ModelRegistry(root, tmp_path / "registry.json")
    registry.register("publisher/model", path, revision="abc123", files=FILES)
    with pytest.raises(ActiveModelError):
        registry.delete("publisher/model", active_model_id="publisher/model")
    registry.delete("publisher/model")
    assert not path.exists()
    assert registry.list_installed() == []


def test_registry_refuses_symlink_model_directory(tmp_path):
    root = tmp_path / "models"
    root.mkdir()
    external = make_model(tmp_path / "external")
    symlink = root / "publisher--model"
    symlink.symlink_to(external, target_is_directory=True)
    registry = ModelRegistry(root, tmp_path / "registry.json")
    with pytest.raises(ValueError):
        registry.register("publisher/model", symlink, revision="abc", files=FILES)
    with pytest.raises(ValueError):
        registry.delete("publisher/model")
