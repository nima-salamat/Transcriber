from __future__ import annotations

import urllib.error

import pytest

from transcriber.models import vosk


def _offline_catalog(monkeypatch):
    catalog = vosk.VoskModelCatalog()

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("catalogue unavailable")

    monkeypatch.setattr(catalog, "list_models", unavailable)
    return catalog


def test_recommended_persian_returns_small_and_large_models_even_offline(monkeypatch):
    catalog = _offline_catalog(monkeypatch)

    models = catalog.curated("fa")

    assert [item.name for item in models] == [
        "vosk-model-small-fa-0.42",
        "vosk-model-fa-0.42",
    ]
    assert [item.model_type for item in models] == ["small", "big"]
    assert models[0].source == "huggingface"
    assert models[1].source == "official"
    assert models[0].size_bytes == 53_431_220
    assert models[1].size_bytes == 1_667_089_770
    assert models[0].checksum == "977cb5faa538f3a835ccfd35f5f6d8284b5c450b89c700b9bd4736b66536ad46"
    assert models[1].checksum == "c47c8e497e35e5e3a27cb71c4f0af275"


def test_offline_search_keeps_both_official_persian_models_and_hf_mirror(monkeypatch):
    catalog = _offline_catalog(monkeypatch)

    models = catalog.search(language="fa")

    names = {item.name for item in models}
    assert "vosk-model-small-fa-0.42" in names
    assert "vosk-model-fa-0.42" in names
    assert len([item for item in models if item.source == "huggingface"]) == 1


def test_pinned_huggingface_small_model_has_real_archive_size():
    model = vosk.VoskModelCatalog._huggingface_curated_models()[0]

    assert model.download_url == (
        "https://huggingface.co/localstack/vosk-models/resolve/134b459/"
        "vosk-model-small-fa-0.42.zip"
    )
    assert model.size_bytes == 53_431_220
    assert model.md5 == "cc2b18af256ffab2c44055f6a02ecb3d"
    assert model.sha256 == "977cb5faa538f3a835ccfd35f5f6d8284b5c450b89c700b9bd4736b66536ad46"
