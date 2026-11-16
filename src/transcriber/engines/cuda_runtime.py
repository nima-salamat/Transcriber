"""Discovery and registration of CUDA DLLs installed as NVIDIA Python wheels.

CTranslate2 loads cuBLAS/cuDNN dynamically. On Windows, wheels place these DLLs
under site-packages/nvidia/*/bin, which is not normally part of the DLL search
path of an application launched from an IDE, shortcut, or packaged executable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import MutableMapping, Sequence

_DLL_DIRECTORY_HANDLES: list[object] = []
_REGISTERED_DIRECTORIES: set[str] = set()

_NVIDIA_RUNTIME_PACKAGES = ("cublas", "cuda_runtime", "cudnn")


def _normalise_path(value: str) -> str:
    return os.path.normcase(os.path.normpath(value.strip().strip('"')))


def find_windows_cuda_dll_directories(
    search_paths: Sequence[str] | None = None,
) -> tuple[Path, ...]:
    """Find CUDA DLL directories from NVIDIA wheels in the active Python environment."""
    discovered: list[Path] = []
    seen: set[str] = set()
    for entry in search_paths if search_paths is not None else sys.path:
        if not entry:
            continue
        site_packages = Path(entry)
        nvidia_root = site_packages / "nvidia"
        for package in _NVIDIA_RUNTIME_PACKAGES:
            candidate = nvidia_root / package / "bin"
            try:
                if not candidate.is_dir():
                    continue
                normalised = _normalise_path(str(candidate))
            except (OSError, ValueError):
                continue
            if normalised not in seen:
                seen.add(normalised)
                discovered.append(candidate)
    return tuple(discovered)


def register_cuda_runtime_dll_directories(
    *,
    is_windows: bool | None = None,
    search_paths: Sequence[str] | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Make NVIDIA wheel DLLs visible before CTranslate2 imports its native extension.

    Both os.add_dll_directory and PATH are used. The returned handles are retained
    for the lifetime of this module because Windows removes a DLL directory when
    its handle is closed.
    """
    windows = os.name == "nt" if is_windows is None else bool(is_windows)
    if not windows:
        return ()

    directories = find_windows_cuda_dll_directories(search_paths)
    if not directories:
        return ()

    environment = os.environ if environ is None else environ
    separator = ";"
    path_value = environment.get("PATH", "")
    existing = {
        _normalise_path(item)
        for item in path_value.split(separator)
        if item.strip()
    }

    add_dll_directory = getattr(os, "add_dll_directory", None)
    registered: list[str] = []
    for directory in directories:
        value = str(directory)
        normalised = _normalise_path(value)
        if normalised not in _REGISTERED_DIRECTORIES:
            if callable(add_dll_directory):
                try:
                    _DLL_DIRECTORY_HANDLES.append(add_dll_directory(value))
                except OSError:
                    # PATH is kept as a second discovery route for native loaders.
                    pass
            _REGISTERED_DIRECTORIES.add(normalised)
        if normalised not in existing:
            registered.append(value)
            existing.add(normalised)

    if registered:
        environment["PATH"] = separator.join([*registered, path_value]) if path_value else separator.join(registered)
    return tuple(registered)


def is_missing_cuda_library_error(error: BaseException) -> bool:
    """Return True only for missing CUDA shared-library errors, not generic GPU failures."""
    messages: list[str] = []
    pending: list[BaseException] = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        messages.append(str(current).casefold())
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)

    message = " ".join(messages)
    has_cuda_library_name = any(
        name in message for name in ("cublas", "cudnn", "cudart")
    )
    has_missing_library_phrase = any(
        phrase in message
        for phrase in (
            "not found",
            "cannot be loaded",
            "could not locate",
            "failed to load",
        )
    )
    return has_cuda_library_name and has_missing_library_phrase


def cuda_runtime_error_message(error: BaseException) -> str:
    """Build an actionable message for a CUDA runtime dependency failure."""
    detail = str(error).strip() or type(error).__name__
    return (
        "CUDA GPU initialization failed: Transcriber could not load the NVIDIA CUDA runtime required by Faster-Whisper.\n\n"
        f"Underlying error: {detail}\n\n"
        "Faster-Whisper requires cuBLAS for CUDA 12 and cuDNN 9 for CUDA 12. "
        "Installing or updating only the NVIDIA display driver does not install these runtime DLLs.\n\n"
        "On Windows, install the optional runtime into the same Python environment that runs Transcriber:\n"
        '  python -m pip install -e ".[asr,gpu]"\n\n'
        "Then completely restart Transcriber. The optional GPU extra installs the CUDA 12 "
        "cuBLAS/runtime and cuDNN 9 wheels; Transcriber adds their DLL directories to the "
        "Windows search path before loading CTranslate2.\n\n"
        "For immediate use, choose Settings → Recognition → Compute device → Automatic or CPU. "
        "Automatic mode can retry on CPU when a missing CUDA library is detected; an explicit "
        "CUDA GPU selection remains GPU-only."
    )
