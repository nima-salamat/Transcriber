"""Curated optional model entries with separate code and weight licensing."""

from __future__ import annotations

from transcriber.models.runtime import ModelSpec

BUILTIN_MODELS = (
    ModelSpec(
        model_id="vosk-model-small-fa-0.42", provider="Vosk", task="asr", runtime="vosk",
        size_bytes=53 * 1024**2, required_ram_mb=350, languages=("fa",),
        capabilities=frozenset({"streaming", "offline", "language-detection"}),
        installed=False, license="Apache-2.0 (model weights; verify at download time)",
        metadata={"source": "https://alphacephei.com/vosk/models", "recommended_for": "Persian local command recognition", "wake_phrase": False},
    ),
    ModelSpec(
        model_id="openwakeword-custom", provider="openWakeWord", task="wake-word", runtime="onnx",
        size_bytes=0, required_ram_mb=90, languages=("en",), capabilities=frozenset({"wake-word", "local"}),
        installed=False, license="Code: Apache-2.0; model weights: check each model license separately",
        metadata={"source": "https://github.com/dscripka/openWakeWord", "persian_support": "not assumed; requires a tested custom model"},
    ),
)
