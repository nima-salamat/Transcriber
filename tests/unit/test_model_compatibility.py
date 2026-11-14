from __future__ import annotations

import pytest

from transcriber.models.compatibility import (
    required_model_files,
    validate_faster_whisper_files,
    validate_repo_id,
)


def test_accepts_root_level_ctranslate2_artifacts():
    names = ["config.json", "model.bin", "tokenizer.json", "vocabulary.json", "README.md"]
    result = validate_faster_whisper_files(names)
    assert result.compatible
    assert set(result.included_files) == set(names)


def test_rejects_transformers_checkpoint_and_nested_model_artifacts():
    result = validate_faster_whisper_files([
        "config.json", "pytorch_model.bin", "tokenizer.json", "model/model.bin",
    ])
    assert not result.compatible
    assert "model.bin" in result.missing_files
    assert "vocabulary.txt or vocabulary.json" in result.missing_files


def test_ignores_path_traversal_and_unrecognized_files():
    names = required_model_files([
        "../model.bin", "/absolute/model.bin", "weights/model.bin", "script.py", "model.bin",
    ])
    assert names == ["model.bin"]


@pytest.mark.parametrize("repo_id", ["owner/model", "A_org/model.v2", "user-1/model_3"])
def test_validates_hub_repository_identifiers(repo_id):
    assert validate_repo_id(repo_id) == repo_id


@pytest.mark.parametrize("repo_id", ["", "model", "owner/../outside", "https://host/a/b", "-bad/name"])
def test_rejects_non_repository_identifiers(repo_id):
    with pytest.raises(ValueError):
        validate_repo_id(repo_id)
