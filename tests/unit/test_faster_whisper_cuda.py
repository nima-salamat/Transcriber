from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from transcriber.engines import faster_whisper as engine_module
from transcriber.engines.cuda_runtime import is_missing_cuda_library_error
from transcriber.transcription.segments import TranscriptionOptions


CUDA_ERROR = "Library cublas64_12.dll is not found or cannot be loaded"


def _install_fake_runtime(monkeypatch, *, fail_during="iteration"):
    calls = []

    class FakeWhisperModel:
        def __init__(self, model_path, *, device, compute_type, cpu_threads, num_workers):
            self.device = device
            self.compute_type = compute_type
            calls.append((device, compute_type))
            if device == "cuda" and fail_during == "load":
                raise RuntimeError(CUDA_ERROR)

        def transcribe(self, _path, **_kwargs):
            info = SimpleNamespace(
                duration=1.0, language="en", language_probability=0.99
            )

            def segments():
                if self.device == "cuda" and fail_during == "iteration":
                    raise RuntimeError(CUDA_ERROR)
                yield SimpleNamespace(start=0.0, end=1.0, text="hello", words=[])

            return segments(), info

    faster_whisper = ModuleType("faster_whisper")
    faster_whisper.WhisperModel = FakeWhisperModel
    ctranslate2 = ModuleType("ctranslate2")
    ctranslate2.get_cuda_device_count = lambda: 1
    monkeypatch.setitem(sys.modules, "faster_whisper", faster_whisper)
    monkeypatch.setitem(sys.modules, "ctranslate2", ctranslate2)
    monkeypatch.setattr(
        engine_module, "register_cuda_runtime_dll_directories", lambda: ()
    )
    return calls


@pytest.mark.parametrize("failure_phase", ["load", "iteration"])
def test_automatic_device_retries_cpu_for_missing_cuda_runtime(
    tmp_path, monkeypatch, failure_phase
):
    calls = _install_fake_runtime(monkeypatch, fail_during=failure_phase)
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"not decoded by the fake engine")

    engine = engine_module.FasterWhisperEngine(
        model_dir, device="auto", compute_type="float16"
    )
    result = engine.transcribe(audio, TranscriptionOptions())

    assert result.text == "hello"
    assert calls == [("cuda", "float16"), ("cpu", "int8")]
    assert engine._resolved_device == "cpu"


def test_explicit_cuda_reports_install_instructions_instead_of_silent_cpu_fallback(
    tmp_path, monkeypatch
):
    calls = _install_fake_runtime(monkeypatch, fail_during="iteration")
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"not decoded by the fake engine")

    engine = engine_module.FasterWhisperEngine(
        model_dir, device="cuda", compute_type="float16"
    )
    with pytest.raises(RuntimeError, match="CUDA GPU initialization") as error:
        engine.transcribe(audio, TranscriptionOptions())

    message = str(error.value)
    assert "nvidia-cublas-cu12" in message or ".[asr,gpu]" in message
    assert "cuDNN 9" in message
    assert calls == [("cuda", "float16")]


def test_cuda_library_detector_does_not_match_unrelated_transcription_errors():
    assert is_missing_cuda_library_error(RuntimeError(CUDA_ERROR))
    assert not is_missing_cuda_library_error(RuntimeError("Invalid audio stream"))
    assert not is_missing_cuda_library_error(RuntimeError("CUDA out of memory"))
