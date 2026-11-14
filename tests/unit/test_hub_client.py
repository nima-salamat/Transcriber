from __future__ import annotations

from types import SimpleNamespace

from transcriber.models.hub_client import HuggingFaceHubClient


def test_model_metadata_normalizes_description_tags_files_and_unknowns():
    info = SimpleNamespace(
        id="publisher/model", sha="abc123", card_data=SimpleNamespace(to_dict=lambda: {
            "description": "A local ASR model", "license": "mit",
        }),
        siblings=[SimpleNamespace(rfilename="model.bin", size=10, lfs=None)],
        tags=["pipeline_tag:automatic-speech-recognition", "language:fa"],
        pipeline_tag="automatic-speech-recognition", downloads=42, likes=7,
        last_modified="2026-01-01T00:00:00Z", author="publisher",
    )
    model = HuggingFaceHubClient._metadata(info)
    assert model.repo_id == "publisher/model"
    assert model.revision == "abc123"
    assert model.license == "mit"
    assert model.languages == ("fa",)
    assert model.files[0].size == 10
    assert model.url == "https://huggingface.co/publisher/model"
