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
    assert models[0].source == "official"
    assert models[1].source == "official"
    assert models[0].size_bytes == 53_431_220
    assert models[1].size_bytes == 1_667_089_770
    assert models[0].checksum == "cc2b18af256ffab2c44055f6a02ecb3d"
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



@pytest.mark.parametrize(
    "metadata",
    [
        {"size_bytes": 1_667_089_770},
        {"download_url": "https://alphacephei.com/vosk/models/vosk-model-fa-0.42.zip"},
    ],
)
def test_downloader_rejects_model_size_or_url_changed_after_inspection(tmp_path, metadata):
    from transcriber.models.registry import ModelRegistry

    model = vosk.VoskModelCatalog._huggingface_curated_models()[0]

    class Catalog:
        @staticmethod
        def by_name(_model_id, *, include_obsolete=False):
            return model

    downloader = vosk.VoskModelDownloader(
        ModelRegistry(tmp_path / "models", tmp_path / "registry.json"),
        Catalog(),
    )

    with pytest.raises(RuntimeError, match="no longer matches"):
        downloader.download(model.repo_id, metadata=metadata)



def _model(
    name: str,
    language: str,
    language_name: str,
    model_type: str,
    size_bytes: int,
    source: str = "official",
):
    return vosk.VoskModelInfo(
        repo_id=f"vosk/{name}",
        name=name,
        language=language,
        language_name=language_name,
        model_type=model_type,
        size_bytes=size_bytes,
        size_text=f"{size_bytes:,} bytes",
        md5="0" * 32,
        url=vosk.MODEL_PAGE_URL,
        download_url=f"https://alphacephei.com/vosk/models/{name}.zip",
        version="0.42",
        source=source,
    )


def test_curated_vosk_recommendations_are_dynamic_and_size_ranked(monkeypatch):
    catalog = vosk.VoskModelCatalog()
    catalogue_entries = [
        _model("vosk-model-en-us-0.22", "en", "English", "big", 1_800_000_000),
        _model("vosk-model-small-pt-0.3", "pt", "Portuguese", "small", 32_000_000),
        _model("vosk-model-small-tr-0.3", "tr", "Turkish", "small", 37_000_000),
        _model("vosk-model-small-fa-0.42", "fa", "Farsi", "small", 53_431_220),
    ]
    monkeypatch.setattr(
        catalog, "list_all_models",
        lambda **_kwargs: list(catalogue_entries),
    )

    models = catalog.curated("")

    assert [item.name for item in models] == [
        "vosk-model-small-pt-0.3",
        "vosk-model-small-tr-0.3",
        "vosk-model-small-fa-0.42",
        "vosk-model-en-us-0.22",
    ]
    assert models[0].size_bytes < 53_431_220
    assert len(models) == len(catalogue_entries)
