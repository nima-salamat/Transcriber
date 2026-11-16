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


def test_windows_cuda_wheel_directories_are_added_to_the_native_search_path(
    tmp_path, monkeypatch
):
    from transcriber.engines import cuda_runtime

    package_root = tmp_path / "nvidia"
    expected = []
    handles = []
    for package in ("cublas", "cuda_runtime", "cudnn"):
        binary_dir = package_root / package / "bin"
        binary_dir.mkdir(parents=True)
        (binary_dir / "runtime-test.dll").write_bytes(b"test")
        expected.append(str(binary_dir))

    monkeypatch.setattr(cuda_runtime, "_REGISTERED_DIRECTORIES", set())
    monkeypatch.setattr(cuda_runtime, "_DLL_DIRECTORY_HANDLES", [])
    monkeypatch.setattr(
        cuda_runtime.os,
        "add_dll_directory",
        lambda value: handles.append(value) or object(),
        raising=False,
    )
    environment = {"PATH": r"C:\Windows\System32"}
    registered = cuda_runtime.register_cuda_runtime_dll_directories(
        is_windows=True,
        search_paths=[str(tmp_path)],
        environ=environment,
    )

    assert registered == tuple(expected)
    assert environment["PATH"].split(";")[:3] == expected
    assert handles == expected

    # Repeated model loads must not accumulate duplicate PATH entries or handles.
    registered_again = cuda_runtime.register_cuda_runtime_dll_directories(
        is_windows=True,
        search_paths=[str(tmp_path)],
        environ=environment,
    )
    assert registered_again == ()
    assert environment["PATH"].split(";") == [*expected, r"C:\Windows\System32"]
    assert handles == expected


def test_all_nvidia_component_bin_directories_are_discovered(tmp_path):
    from transcriber.engines.cuda_runtime import find_windows_cuda_dll_directories

    nvidia_root = tmp_path / "nvidia"
    package_names = (
        "cublas",
        "cuda_runtime",
        "cudnn",
        "cuda_nvrtc",
        "nvjitlink",
        "nvfatbin",
    )
    expected = []
    for package in package_names:
        binary_dir = nvidia_root / package / "bin"
        binary_dir.mkdir(parents=True)
        (binary_dir / f"{package}.dll").write_bytes(b"test")
        expected.append(binary_dir)

    discovered = find_windows_cuda_dll_directories(
        [str(tmp_path)],
        environ={},
    )

    assert set(discovered) == set(expected)
    assert discovered.index(nvidia_root / "cublas" / "bin") < discovered.index(
        nvidia_root / "nvjitlink" / "bin"
    )


def test_cuda_toolkit_bin_from_environment_is_discovered(tmp_path):
    from transcriber.engines.cuda_runtime import find_windows_cuda_dll_directories

    toolkit_bin = tmp_path / "CUDA" / "v12.9" / "bin"
    toolkit_bin.mkdir(parents=True)
    (toolkit_bin / "cublas64_12.dll").write_bytes(b"test")

    discovered = find_windows_cuda_dll_directories(
        [],
        environ={"CUDA_PATH": str(toolkit_bin.parent)},
    )

    assert toolkit_bin in discovered


def test_cuda_bin_directory_from_path_is_discovered(tmp_path):
    from transcriber.engines.cuda_runtime import find_windows_cuda_dll_directories

    cuda_bin = tmp_path / "cuda-bin"
    cuda_bin.mkdir()
    (cuda_bin / "cublas64_12.dll").write_bytes(b"test")

    discovered = find_windows_cuda_dll_directories(
        [],
        environ={"PATH": str(cuda_bin)},
    )

    assert cuda_bin in discovered


def test_cuda_error_message_reports_runtime_probe_on_windows(tmp_path, monkeypatch):
    from transcriber.engines import cuda_runtime

    monkeypatch.setattr(cuda_runtime, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        cuda_runtime,
        "find_windows_cuda_dll_directories",
        lambda: (tmp_path,),
    )
    (tmp_path / "cublas64_12.dll").write_bytes(b"test")

    message = cuda_runtime.cuda_runtime_error_message(RuntimeError(CUDA_ERROR))

    assert "Python executable:" in message
    assert "cublas64_12.dll:" in message
    assert str(tmp_path / "cublas64_12.dll") in message
    assert "Visual C++" in message
