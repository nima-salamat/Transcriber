from __future__ import annotations

from transcriber.models.manager import ModelManager


def test_wake_model_list_contains_only_compatible_registered_vosk_models(monkeypatch):
    manager = object.__new__(ModelManager)
    installed = [
        {
            "repo_id": "vosk/vosk-model-small-fa-0.42",
            "path": "/models/vosk-model-small-fa-0.42",
            "runtime": "vosk",
            "compatible": True,
        },
        {
            "repo_id": "vosk/vosk-model-en-us-0.22",
            "path": "/models/vosk-model-en-us-0.22",
            "runtime": "vosk",
            "compatible": False,
        },
        {
            "repo_id": "Systran/faster-whisper-small",
            "path": "/models/faster-whisper-small",
            "runtime": "faster-whisper",
            "compatible": True,
        },
    ]
    monkeypatch.setattr(
        manager,
        "installed",
        lambda *, include_sizes=True: installed,
    )

    result = manager.installed_vosk_models(include_sizes=False)

    assert [item["repo_id"] for item in result] == ["vosk/vosk-model-small-fa-0.42"]
