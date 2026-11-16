"""Discovery and registration of CUDA DLLs installed as NVIDIA Python wheels.

CTranslate2 loads cuBLAS/cuDNN dynamically. On Windows, NVIDIA wheels place
runtime DLLs in separate site-packages/nvidia/<component>/bin directories.
All of those directories must be discoverable because a requested DLL can have
transitive dependencies in another NVIDIA component directory.
"""

from __future__ import annotations

import importlib.metadata
import os
import site
import sys
from collections.abc import MutableMapping, Sequence
from pathlib import Path

_DLL_DIRECTORY_HANDLES: list[object] = []
_REGISTERED_DIRECTORIES: set[str] = set()

# Keep the important search order deterministic. The remaining CUDA components
# (NVRTC, nvJitLink, NVFatbin, etc.) follow alphabetically.
_DIRECTORY_PRIORITY = {
    "cublas": 0,
    "cuda_runtime": 1,
    "cudnn": 2,
    "cuda_nvrtc": 3,
    "nvjitlink": 4,
}


def _normalise_path(value: str) -> str:
    return os.path.normcase(os.path.normpath(value.strip().strip('"')))


def _site_package_roots(search_paths: Sequence[str] | None) -> tuple[Path, ...]:
    values: list[str] = list(search_paths or ())
    if search_paths is None:
        values.extend(entry for entry in sys.path if entry)
        try:
            values.extend(site.getsitepackages())
        except (AttributeError, OSError):
            pass
        try:
            user_site = site.getusersitepackages()
            values.extend(user_site if isinstance(user_site, list) else [user_site])
        except (AttributeError, OSError):
            pass
        if os.name == "nt":
            values.append(str(Path(sys.prefix) / "Lib" / "site-packages"))

    roots: list[Path] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        root = Path(value).expanduser()
        try:
            normalised = _normalise_path(str(root))
        except (OSError, ValueError):
            continue
        if normalised not in seen and root.is_dir():
            seen.add(normalised)
            roots.append(root)
    return tuple(roots)


def find_windows_cuda_dll_directories(
    search_paths: Sequence[str] | None = None,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> tuple[Path, ...]:
    """Find NVIDIA wheel and CUDA Toolkit DLL directories for the active Python."""
    environment = os.environ if environ is None else environ
    candidates: list[Path] = []

    # Discover every installed NVIDIA component, not only cuBLAS/cuDNN. CUDA
    # libraries may load NVRTC, nvJitLink, or other DLLs as transitive dependencies.
    package_directories: list[tuple[str, Path]] = []
    for site_packages in _site_package_roots(search_paths):
        nvidia_root = site_packages / "nvidia"
        try:
            children = tuple(nvidia_root.iterdir()) if nvidia_root.is_dir() else ()
        except OSError:
            children = ()
        for package_root in children:
            binary_dir = package_root / "bin"
            try:
                if package_root.is_dir() and binary_dir.is_dir():
                    package_directories.append((package_root.name.casefold(), binary_dir))
            except OSError:
                continue

    package_directories.sort(
        key=lambda item: (_DIRECTORY_PRIORITY.get(item[0], 10), item[0])
    )
    candidates.extend(path for _name, path in package_directories)

    # A conventional CUDA Toolkit installation is not necessarily on PATH when
    # the application is launched from a shortcut or a GUI environment.
    toolkit_roots: list[Path] = []
    for key, value in environment.items():
        if (key == "CUDA_PATH" or key.startswith("CUDA_PATH_V12_")) and value.strip():
            toolkit_roots.append(Path(value.strip().strip('"')).expanduser())

    program_files = environment.get("ProgramFiles") or environment.get("PROGRAMFILES")
    if program_files:
        toolkit_root = Path(program_files) / "NVIDIA GPU Computing Toolkit" / "CUDA"
        try:
            toolkit_roots.extend(
                sorted(
                    (path for path in toolkit_root.glob("v12.*") if path.is_dir()),
                    reverse=True,
                )
            )
        except OSError:
            pass

    for root in toolkit_roots:
        candidates.append(root if root.name.casefold() == "bin" else root / "bin")

    # Some installations add CUDA to PATH without defining CUDA_PATH.
    # Keep only PATH entries that actually contain a core CUDA runtime DLL.
    path_sentinels = (
        "cublas64_12.dll",
        "cublasLt64_12.dll",
        "cudart64_12.dll",
        "cudnn64_9.dll",
    )
    for value in environment.get("PATH", "").split(";"):
        if not value.strip():
            continue
        path_directory = Path(value.strip().strip('"')).expanduser()
        try:
            if path_directory.is_dir() and any(
                (path_directory / filename).is_file() for filename in path_sentinels
            ):
                candidates.append(path_directory)
        except OSError:
            continue

    discovered: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
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
    """Make CUDA wheel and Toolkit DLLs visible to native Windows loaders.

    Both os.add_dll_directory and PATH are used. The returned handles are retained
    for the lifetime of this module because Windows removes a DLL directory when
    its handle is closed. PATH is also updated because native dependencies loaded
    by CTranslate2 may use the legacy LoadLibrary search behavior.
    """
    windows = os.name == "nt" if is_windows is None else bool(is_windows)
    if not windows:
        return ()

    environment = os.environ if environ is None else environ
    directories = find_windows_cuda_dll_directories(
        search_paths,
        environ=environment,
    )
    if not directories:
        return ()

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
                    # PATH remains a second discovery route for native loaders.
                    pass
            _REGISTERED_DIRECTORIES.add(normalised)
        if normalised not in existing:
            registered.append(value)
            existing.add(normalised)

    if registered:
        environment["PATH"] = separator.join([*registered, path_value]) if path_value else separator.join(registered)
    return tuple(registered)


def cuda_runtime_diagnostics() -> str:
    """Describe installed NVIDIA wheels and whether their core DLLs are discoverable."""
    directories = find_windows_cuda_dll_directories()
    required = (
        "cublas64_12.dll",
        "cublasLt64_12.dll",
        "cudart64_12.dll",
        "cudnn64_9.dll",
    )
    found: dict[str, str | None] = {
        name: next(
            (
                str(directory / name)
                for directory in directories
                if (directory / name).is_file()
            ),
            None,
        )
        for name in required
    }
    dll_status = "; ".join(
        f"{name}: {path if path else 'not found'}" for name, path in found.items()
    )
    package_names = (
        "nvidia-cublas-cu12",
        "nvidia-cuda-runtime-cu12",
        "nvidia-cuda-nvrtc-cu12",
        "nvidia-nvjitlink-cu12",
        "nvidia-cudnn-cu12",
    )
    package_status = []
    for name in package_names:
        try:
            version = importlib.metadata.version(name)
            package_status.append(f"{name}=={version}")
        except importlib.metadata.PackageNotFoundError:
            package_status.append(f"{name}: NOT INSTALLED")
    search_status = "; ".join(str(path) for path in directories[:8]) or "no CUDA DLL folders discovered"
    if len(directories) > 8:
        search_status += f"; and {len(directories) - 8} more"
    return (
        f"Python executable: {sys.executable}\n"
        f"Python prefix: {sys.prefix}\n"
        f"NVIDIA runtime packages: {'; '.join(package_status)}\n"
        f"Runtime DLL probe: {dll_status}\n"
        f"CUDA DLL search folders: {search_status}"
    )


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
    diagnostics = cuda_runtime_diagnostics() if os.name == "nt" else ""
    diagnostic_section = f"\n\n{diagnostics}" if diagnostics else ""
    return (
        "CUDA GPU initialization failed: Transcriber could not load the NVIDIA CUDA runtime required by Faster-Whisper.\n\n"
        f"Underlying error: {detail}{diagnostic_section}\n\n"
        "Faster-Whisper requires cuBLAS for CUDA 12 and cuDNN 9 for CUDA 12. "
        "Installing or updating only the NVIDIA display driver does not install these runtime DLLs.\n\n"
        "On Windows, install the optional runtime into the same Python environment that runs Transcriber:\n"
        '  python -m pip install -r requirements-windows-gpu.txt\n'
        '  (or, from the repository root: python -m pip install -e ".[asr,gpu]")\n\n'
        "Then completely restart Transcriber. The GPU extra installs the CUDA 12 "
        "cuBLAS/runtime, NVRTC, nvJitLink and cuDNN 9 wheels. Transcriber registers "
        "all NVIDIA wheel DLL folders and CUDA Toolkit folders before loading CTranslate2.\n"
        "The diagnostics above show which NVIDIA wheels and DLL files are visible to this exact Python environment.\n\n"
        "If the DLLs are reported as found but still cannot load, repair the Microsoft "
        "Visual C++ 2015–2022 x64 Redistributable and check for conflicting CUDA DLL versions.\n\n"
        "For immediate use, choose Settings → Recognition → Compute device → Automatic or CPU. "
        "Automatic mode can retry on CPU when a missing CUDA library is detected; an explicit "
        "CUDA GPU selection remains GPU-only."
    )
