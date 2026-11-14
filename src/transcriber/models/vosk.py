"""Official Vosk model catalogue, compatibility inspection and safe ZIP installer."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from transcriber.models.downloader import (
    DownloadCancelled,
    DownloadPaused,
    DownloadProgress,
    DownloadStopped,
)
from transcriber.models.registry import ModelRegistry

MODEL_LIST_URL = "https://alphacephei.com/vosk/models/model-list.json"
MODEL_PAGE_URL = "https://alphacephei.com/vosk/models.html"
MODEL_HOST = "alphacephei.com"
_MODEL_NAME = re.compile(r"^vosk-model(?:-small)?-[a-z0-9][a-z0-9-]*$")
_MAX_ARCHIVE_ENTRIES = 20_000
_MAX_UNPACKED_BYTES = 32 * 1024**3
_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True, slots=True)
class VoskCompatibilityReport:
    compatible: bool
    missing_files: tuple[str, ...] = ()
    included_files: tuple[str, ...] = ()
    reason: str = ""
    runtime: str = "vosk"


@dataclass(frozen=True, slots=True)
class VoskModelInfo:
    repo_id: str
    name: str
    language: str
    language_name: str
    model_type: str
    size_bytes: int
    size_text: str
    md5: str
    url: str
    version: str
    obsolete: bool = False
    runtime: str = "vosk"
    provider: str = "Vosk"
    task: str = "automatic-speech-recognition"
    author: str = "AlphaCephei"
    description: str = ""

    @property
    def revision(self) -> str:
        return self.md5

    @property
    def license(self) -> None:
        # The official machine-readable catalogue does not publish license metadata.
        return None

    @property
    def downloads(self) -> None:
        return None

    @property
    def likes(self) -> None:
        return None

    @property
    def last_modified(self) -> None:
        return None

    @property
    def languages(self) -> tuple[str, ...]:
        return (self.language_name,)

    @property
    def metadata(self) -> dict:
        return {
            "runtime": "vosk",
            "model_name": self.name,
            "language": self.language,
            "language_name": self.language_name,
            "model_type": self.model_type,
            "size_bytes": self.size_bytes,
            "size_text": self.size_text,
            "md5": self.md5,
            "url": self.url,
            "version": self.version,
            "catalogue": MODEL_LIST_URL,
        }


def _normalise_model_name(value: str) -> str:
    name = str(value or "").strip()
    if name.startswith("vosk/"):
        name = name.split("/", 1)[1]
    if not _MODEL_NAME.fullmatch(name):
        raise ValueError("Invalid Vosk model name")
    return name


def _repo_id(name: str) -> str:
    return f"vosk/{_normalise_model_name(name)}"


def _safe_model_url(value: str, name: str) -> str:
    parsed = urlparse(str(value or ""))
    if (
        parsed.scheme != "https"
        or parsed.hostname != MODEL_HOST
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or parsed.path != f"/vosk/models/{name}.zip"
    ):
        raise ValueError("Vosk catalogue contains an unexpected model download URL")
    return value


def _parse_catalogue_entry(raw: object) -> VoskModelInfo | None:
    if not isinstance(raw, dict):
        return None
    try:
        name = _normalise_model_name(str(raw.get("name") or ""))
        language = str(raw.get("lang") or "").strip().casefold()
        language_name = str(raw.get("lang_text") or language).strip()
        model_type = str(raw.get("type") or "").strip().casefold()
        size_bytes = int(raw.get("size") or 0)
        size_text = str(raw.get("size_text") or "").strip()
        md5 = str(raw.get("md5") or "").strip().casefold()
        version = str(raw.get("version") or "").strip()
        obsolete = str(raw.get("obsolete", "false")).casefold() == "true"
        url = _safe_model_url(str(raw.get("url") or ""), name)
        if (
            not language
            or not language_name
            or model_type not in {"small", "big", "big-lgraph"}
            or size_bytes <= 0
            or not re.fullmatch(r"[0-9a-f]{32}", md5)
            or not version
        ):
            return None
        label = "Lightweight model" if model_type == "small" else "High-accuracy model"
        if model_type == "big-lgraph":
            label = "Large model with dynamic graph"
        description = (
            f"{language_name} · {label} · {size_text or f'{size_bytes:,} bytes'} · "
            f"Vosk API / Kaldi runtime"
        )
        return VoskModelInfo(
            repo_id=_repo_id(name),
            name=name,
            language=language,
            language_name=language_name,
            model_type=model_type,
            size_bytes=size_bytes,
            size_text=size_text or f"{size_bytes:,} bytes",
            md5=md5,
            url=url,
            version=version,
            obsolete=obsolete,
            description=description,
        )
    except (TypeError, ValueError, OverflowError):
        return None


class VoskModelCatalog:
    """Fetch the official model-list.json and expose only current Vosk API entries."""

    def __init__(self, *, timeout: float = 15.0, cache_seconds: float = 21_600):
        self.timeout = max(2.0, float(timeout))
        self.cache_seconds = max(0.0, float(cache_seconds))
        self._lock = threading.RLock()
        self._cached_at = 0.0
        self._models: tuple[VoskModelInfo, ...] = ()

    def list_models(self, *, include_obsolete: bool = False, refresh: bool = False) -> list[VoskModelInfo]:
        with self._lock:
            expired = time.monotonic() - self._cached_at >= self.cache_seconds
            should_fetch = refresh or not self._models or expired
        if should_fetch:
            request = urllib.request.Request(
                MODEL_LIST_URL,
                headers={"User-Agent": "Transcriber-Desktop/2.1 (+Vosk model catalogue)"},
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    if getattr(response, "status", 200) != 200:
                        raise RuntimeError(f"Vosk model catalogue returned HTTP {response.status}")
                    payload = response.read(4 * 1024 * 1024 + 1)
            except (OSError, urllib.error.URLError, TimeoutError) as exc:
                with self._lock:
                    if self._models:
                        return [
                            item for item in self._models
                            if include_obsolete or not item.obsolete
                        ]
                raise RuntimeError(f"Could not retrieve the official Vosk model catalogue: {exc}") from exc
            if len(payload) > 4 * 1024 * 1024:
                raise ValueError("Vosk model catalogue exceeds its 4 MiB safety limit")
            try:
                raw_models = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise ValueError("The official Vosk model catalogue is not valid UTF-8 JSON") from exc
            if not isinstance(raw_models, list):
                raise ValueError("The official Vosk model catalogue must contain a JSON array")
            parsed = tuple(
                model for model in (_parse_catalogue_entry(item) for item in raw_models)
                if model is not None
            )
            if not parsed:
                raise RuntimeError("The Vosk model catalogue did not contain any valid model entries")
            with self._lock:
                self._models = parsed
                self._cached_at = time.monotonic()
        with self._lock:
            models = list(self._models)
        if include_obsolete:
            return models
        return [item for item in models if not item.obsolete]

    def search(self, query: str = "", *, limit: int = 50) -> list[VoskModelInfo]:
        models = self.list_models()
        normalised = " ".join(str(query or "").casefold().split())
        if normalised:
            tokens = normalised.split()
            aliases = {
                "persian": "fa",
                "فارسی": "fa",
                "farsi": "fa",
                "فرسی": "fa",
                "english": "en",
            }
            tokens = [aliases.get(token, token) for token in tokens]
            models = [
                model for model in models
                if all(
                    token in " ".join((
                        model.name, model.language, model.language_name,
                        model.model_type, model.description,
                    )).casefold()
                    for token in tokens
                )
            ]
        return models[:max(1, min(int(limit), 200))]

    def inspect(self, model_id: str) -> tuple[VoskModelInfo, VoskCompatibilityReport]:
        name = _normalise_model_name(model_id)
        model = next(
            (item for item in self.list_models(include_obsolete=True) if item.name == name),
            None,
        )
        if model is None:
            raise KeyError(f"Vosk model is not present in the official catalogue: {name}")
        report = VoskCompatibilityReport(
            compatible=not model.obsolete,
            missing_files=("This model is marked obsolete in the official catalogue",) if model.obsolete else (),
            included_files=("official Vosk API catalogue entry", "HTTPS archive URL", "MD5 checksum"),
            reason=(
                "Listed by the official Vosk API catalogue. The downloaded ZIP's checksum and "
                "Vosk model directory layout will be verified before installation."
                if not model.obsolete else
                "The official catalogue marks this model as obsolete. It can be inspected but not installed."
            ),
        )
        return model, report

    def by_name(self, model_id: str, *, include_obsolete: bool = True) -> VoskModelInfo:
        name = _normalise_model_name(model_id)
        model = next(
            (
                item for item in self.list_models(include_obsolete=include_obsolete)
                if item.name == name
            ),
            None,
        )
        if model is None:
            raise KeyError(f"Vosk model is not available: {name}")
        return model


def validate_vosk_model_directory(path: str | Path) -> VoskCompatibilityReport:
    """Check the layout loaded by Vosk's Model constructor without loading weights into RAM."""
    root = Path(path).expanduser()
    if root.is_symlink() or not root.is_dir():
        return VoskCompatibilityReport(
            compatible=False, missing_files=("model directory",),
            reason="Vosk model path must be a real directory, not a symbolic link.",
        )
    root = root.resolve()

    def safe_file(relative: str) -> bool:
        candidate = root / relative
        try:
            return (
                not candidate.is_symlink()
                and candidate.is_file()
                and candidate.resolve().is_relative_to(root)
            )
        except (OSError, RuntimeError, ValueError):
            return False

    missing: list[str] = []
    v2 = safe_file("am/final.mdl") and safe_file("conf/model.conf")
    if v2:
        included = ["am/final.mdl", "conf/model.conf"]
        features = [name for name in ("conf/mfcc.conf", "conf/fbank.conf") if safe_file(name)]
        if not features:
            missing.append("conf/mfcc.conf or conf/fbank.conf")
        else:
            included.extend(features)
        graph_files = [
            name for name in ("graph/HCLG.fst", "graph/HCLr.fst", "graph/Gr.fst", "graph/words.txt")
            if safe_file(name)
        ]
        has_main_graph = safe_file("graph/HCLG.fst") or (
            safe_file("graph/HCLr.fst") and safe_file("graph/Gr.fst")
        )
        if not has_main_graph:
            missing.append("graph/HCLG.fst or graph/HCLr.fst + graph/Gr.fst")
        if not safe_file("graph/words.txt"):
            missing.append("graph/words.txt")
        included.extend(graph_files)
        layout = "Vosk v2 (am/conf/graph)"
    else:
        included = []
        if not safe_file("final.mdl"):
            missing.append("final.mdl or am/final.mdl")
        else:
            included.append("final.mdl")
        if not safe_file("mfcc.conf"):
            missing.append("mfcc.conf or conf/model.conf")
        else:
            included.append("mfcc.conf")
        has_main_graph = safe_file("HCLG.fst") or (
            safe_file("HCLr.fst") and safe_file("Gr.fst")
        )
        if not has_main_graph:
            missing.append("HCLG.fst or HCLr.fst + Gr.fst")
        if not safe_file("words.txt"):
            missing.append("words.txt")
        included.extend(
            name for name in ("HCLG.fst", "HCLr.fst", "Gr.fst", "words.txt")
            if safe_file(name)
        )
        layout = "Vosk v1 (legacy root-level)"

    if missing:
        return VoskCompatibilityReport(
            compatible=False, missing_files=tuple(missing),
            included_files=tuple(sorted(set(included))),
            reason=(
                "The directory does not contain the acoustic model, feature configuration and "
                "decoding graph expected by the Vosk API."
            ),
        )
    return VoskCompatibilityReport(
        compatible=True,
        included_files=tuple(sorted(set(included))),
        reason=f"Required files found for {layout}. Model weights are validated without loading them into RAM.",
    )


class VoskModelDownloader:
    """Download, checksum, safely extract and atomically register official Vosk ZIP archives."""

    def __init__(
        self, registry: ModelRegistry, catalog: VoskModelCatalog, *,
        job_repository=None, max_concurrent: int = 2, timeout: float = 30.0,
    ):
        self.registry = registry
        self.catalog = catalog
        self.job_repository = job_repository
        self.timeout = max(5.0, float(timeout))
        self._condition = threading.Condition(threading.RLock())
        self._max_concurrent = max(1, min(int(max_concurrent), 8))
        self._active: dict[str, threading.Event] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._pause_events: dict[str, threading.Event] = {}
        self._stop_events: dict[str, threading.Event] = {}
        self._job_ids: dict[str, str] = {}

    def set_max_concurrent(self, value: int) -> None:
        with self._condition:
            self._max_concurrent = max(1, min(int(value), 8))
            self._condition.notify_all()

    def list_jobs(self, limit: int = 500) -> list[dict]:
        if self.job_repository is None:
            return []
        return [
            item for item in self.job_repository.list(limit=limit)
            if (item.get("metadata") or {}).get("runtime") == "vosk"
        ]

    def _signal(self, model_id: str, kind: str) -> bool:
        with self._condition:
            events = {
                "cancel": self._cancel_events,
                "pause": self._pause_events,
                "stop": self._stop_events,
            }.get(kind)
            event = events.get(model_id) if events is not None else None
            if event is None:
                return False
            event.set()
            self._condition.notify_all()
            task_id = self._job_ids.get(model_id)
        if task_id and self.job_repository:
            self.job_repository.update(task_id, state=f"{kind}ling")
        return True

    def cancel(self, model_id: str) -> bool:
        return self._signal(model_id, "cancel")

    def pause(self, model_id: str) -> bool:
        return self._signal(model_id, "pause")

    def stop(self, model_id: str) -> bool:
        return self._signal(model_id, "stop")

    def cancel_all(self) -> int:
        with self._condition:
            events = list(self._cancel_events.values())
            for event in events:
                event.set()
            self._condition.notify_all()
            return len(events)

    @property
    def active_count(self) -> int:
        with self._condition:
            return len(self._active)

    def _enter_slot(
        self, model_id: str, cancel_event: threading.Event,
        pause_event: threading.Event, stop_event: threading.Event,
    ) -> None:
        with self._condition:
            while len(self._active) >= self._max_concurrent:
                if cancel_event.is_set():
                    raise DownloadCancelled("Queued Vosk download cancelled")
                if pause_event.is_set():
                    raise DownloadPaused("Queued Vosk download paused")
                if stop_event.is_set():
                    raise DownloadStopped("Queued Vosk download stopped")
                self._condition.wait(timeout=0.2)
            if cancel_event.is_set():
                raise DownloadCancelled("Vosk download cancelled before transfer")
            if pause_event.is_set():
                raise DownloadPaused("Vosk download paused before transfer")
            if stop_event.is_set():
                raise DownloadStopped("Vosk download stopped before transfer")
            self._active[model_id] = cancel_event

    def download(
        self, model_id: str, *, cancel_event: threading.Event | None = None,
        progress: Callable[[DownloadProgress], None] | None = None,
        task_id: str | None = None, metadata: dict | None = None,
    ) -> Path:
        model = self.catalog.by_name(model_id, include_obsolete=False)
        model_id = model.repo_id
        task_id = str(task_id or uuid.uuid4().hex)
        cancel_event = cancel_event or threading.Event()
        pause_event = threading.Event()
        stop_event = threading.Event()
        with self._condition:
            if model_id in self._cancel_events:
                raise RuntimeError(f"A Vosk download for {model.name} is already queued or active")
            self._cancel_events[model_id] = cancel_event
            self._pause_events[model_id] = pause_event
            self._stop_events[model_id] = stop_event
            self._job_ids[model_id] = task_id

        staging_root = self.registry.root / ".staging"
        cache_root = staging_root / "vosk-download-cache"
        cache_root.mkdir(parents=True, exist_ok=True)
        cache_key = hashlib.sha256((model.name + model.md5).encode("utf-8")).hexdigest()
        partial = cache_root / f"{cache_key}.zip.partial"
        staging = staging_root / f"vosk-{cache_key}-{task_id}"
        target = self.registry.root / self.registry.directory_name(model.repo_id)
        total = model.size_bytes
        downloaded = 0
        started = time.monotonic()
        job_metadata = {**model.metadata, **(metadata or {}), "runtime": "vosk"}

        def emit(state: str, message: str = "") -> None:
            nonlocal downloaded
            if progress:
                elapsed = max(0.001, time.monotonic() - started)
                progress(DownloadProgress(
                    state=state,
                    downloaded_bytes=downloaded,
                    total_bytes=total,
                    speed_bytes_per_second=downloaded / elapsed if downloaded else None,
                    message=message,
                ))
            if self.job_repository:
                self.job_repository.update(
                    task_id,
                    state=state.casefold(),
                    revision=model.md5,
                    downloaded_bytes=downloaded,
                    total_bytes=total,
                    metadata=job_metadata,
                )

        def check_events() -> None:
            if cancel_event.is_set():
                raise DownloadCancelled("Vosk model download cancelled")
            if pause_event.is_set():
                raise DownloadPaused("Vosk model download paused at a safe transfer boundary")
            if stop_event.is_set():
                raise DownloadStopped("Vosk model download stopped at a safe transfer boundary")

        try:
            if self.job_repository:
                self.job_repository.enqueue(
                    task_id, model.repo_id, model.md5, str(target), job_metadata,
                )
            emit("Queued", "Waiting for a model download slot")
            self._enter_slot(model_id, cancel_event, pause_event, stop_event)
            check_events()

            if partial.is_symlink() or staging.is_symlink():
                raise ValueError("Refusing to use a symbolic-link Vosk staging path")
            if target.exists() and self.registry.get_path(model.repo_id):
                report = validate_vosk_model_directory(target)
                if report.compatible:
                    emit("Installed", "A validated installation already exists")
                    return target
            if staging.exists():
                shutil.rmtree(staging)
            staging.mkdir(parents=False, exist_ok=False)

            downloaded = partial.stat().st_size if partial.is_file() else 0
            if downloaded > total:
                partial.unlink()
                downloaded = 0
            emit("Downloading", "Downloading official Vosk model archive")

            request_headers = {"User-Agent": "Transcriber-Desktop/2.1", "Accept": "application/zip"}
            if downloaded:
                request_headers["Range"] = f"bytes={downloaded}-"
            request = urllib.request.Request(model.url, headers=request_headers)
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status = getattr(response, "status", 200)
                if downloaded and status != 206:
                    downloaded = 0
                    partial.unlink(missing_ok=True)
                mode = "ab" if downloaded else "wb"
                with partial.open(mode) as stream:
                    while True:
                        check_events()
                        chunk = response.read(_CHUNK_SIZE)
                        if not chunk:
                            break
                        stream.write(chunk)
                        downloaded += len(chunk)
                        emit("Downloading", "Receiving Vosk model archive")
                    stream.flush()
                    os.fsync(stream.fileno())

            check_events()
            if downloaded != total:
                raise OSError(
                    f"Vosk archive size mismatch: expected {total:,} bytes, received {downloaded:,} bytes"
                )
            emit("Validating", "Verifying the official MD5 checksum")
            digest = hashlib.md5()
            with partial.open("rb") as archive_stream:
                while True:
                    check_events()
                    block = archive_stream.read(_CHUNK_SIZE)
                    if not block:
                        break
                    digest.update(block)
            if digest.hexdigest().casefold() != model.md5:
                partial.unlink(missing_ok=True)
                raise ValueError("Vosk archive checksum does not match the official catalogue")

            extract_root = staging / "extracted"
            extract_root.mkdir()
            with zipfile.ZipFile(partial, "r") as archive:
                entries = archive.infolist()
                if len(entries) > _MAX_ARCHIVE_ENTRIES:
                    raise ValueError("Vosk ZIP contains too many entries")
                unpacked_total = sum(item.file_size for item in entries if not item.is_dir())
                if unpacked_total > _MAX_UNPACKED_BYTES:
                    raise ValueError("Vosk ZIP expands beyond the 32 GiB safety limit")
                if shutil.disk_usage(self.registry.root).free < unpacked_total + 128 * 1024**2:
                    raise OSError("Not enough free disk space to extract and install this Vosk model")
                for entry in entries:
                    check_events()
                    raw_name = entry.filename
                    if "\\" in raw_name:
                        raise ValueError("Vosk ZIP entries with backslash paths are not accepted")
                    member = PurePosixPath(raw_name)
                    if (
                        member.is_absolute()
                        or not member.parts
                        or ".." in member.parts
                        or any(part.endswith(":") for part in member.parts)
                    ):
                        raise ValueError(f"Unsafe path in Vosk ZIP: {raw_name}")
                    mode_bits = entry.external_attr >> 16
                    if stat.S_ISLNK(mode_bits):
                        raise ValueError(f"Symbolic links are not allowed in Vosk ZIPs: {raw_name}")
                    destination = extract_root.joinpath(*member.parts)
                    if not destination.resolve().is_relative_to(extract_root.resolve()):
                        raise ValueError(f"ZIP entry escapes the staging directory: {raw_name}")
                    if entry.is_dir():
                        destination.mkdir(parents=True, exist_ok=True)
                        continue
                    if entry.flag_bits & 0x1:
                        raise ValueError("Encrypted Vosk ZIP entries are not supported")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    written = 0
                    with archive.open(entry, "r") as reader, destination.open("xb") as writer:
                        while True:
                            check_events()
                            chunk = reader.read(_CHUNK_SIZE)
                            if not chunk:
                                break
                            written += len(chunk)
                            if written > entry.file_size or written > _MAX_UNPACKED_BYTES:
                                raise ValueError("Vosk ZIP entry expanded beyond its declared size")
                            writer.write(chunk)
                    if written != entry.file_size:
                        raise ValueError(f"Vosk ZIP entry size mismatch: {raw_name}")

            check_events()
            candidates = [extract_root]
            candidates.extend(
                item for item in extract_root.iterdir()
                if item.is_dir() and not item.is_symlink()
            )
            model_root = next(
                (item for item in candidates if validate_vosk_model_directory(item).compatible),
                None,
            )
            if model_root is None:
                reports = [validate_vosk_model_directory(item) for item in candidates]
                missing = sorted({name for report in reports for name in report.missing_files})
                raise ValueError(
                    "The downloaded archive is not a compatible Vosk model directory. "
                    + "Missing: " + ", ".join(missing[:8])
                )
            report = validate_vosk_model_directory(model_root)
            files = sorted(
                item.relative_to(model_root).as_posix()
                for item in model_root.rglob("*")
                if item.is_file() and not item.is_symlink()
            )
            final_model = staging / "model"
            model_root.rename(final_model)
            manifest = {
                "repo_id": model.repo_id,
                "revision": model.md5,
                "engine": "vosk",
                "runtime": "vosk",
                "files": files,
                "language_code": model.language,
                "language_name": model.language_name,
                "model_name": model.name,
                "model_type": model.model_type,
                "license": None,
                "source": "official-vosk-catalogue",
                "catalogue_url": MODEL_LIST_URL,
                "archive_md5": model.md5,
            }
            (final_model / ".transcriber-model.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            emit("Installing", "Registering the validated Vosk model")
            backup = staging_root / f"{self.registry.directory_name(model.repo_id)}-previous-{task_id}"
            if backup.exists():
                shutil.rmtree(backup)
            if target.exists():
                target.rename(backup)
            try:
                final_model.rename(target)
                self.registry.register(
                    model.repo_id,
                    target,
                    revision=model.md5,
                    files=files,
                    license_name=None,
                    runtime="vosk",
                    metadata={
                        "language_code": model.language,
                        "language_name": model.language_name,
                        "model_name": model.name,
                        "model_type": model.model_type,
                        "archive_md5": model.md5,
                        "source": "official-vosk-catalogue",
                    },
                )
            except Exception:
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
                if backup.exists():
                    backup.rename(target)
                raise
            shutil.rmtree(backup, ignore_errors=True)
            partial.unlink(missing_ok=True)
            emit("Installed", f"Vosk model ready · {model.language_name} · {model.size_text}")
            return target
        except (DownloadPaused, DownloadStopped, DownloadCancelled) as exc:
            state = "Paused" if isinstance(exc, DownloadPaused) else (
                "Stopped" if isinstance(exc, DownloadStopped) else "Cancelled"
            )
            emit(state, str(exc))
            if self.job_repository:
                self.job_repository.update(
                    task_id, state=state.casefold(), revision=model.md5,
                    downloaded_bytes=downloaded, total_bytes=total, metadata=job_metadata,
                )
            raise
        except Exception as exc:
            message = str(exc)[:800]
            emit("Failed", message)
            if self.job_repository:
                self.job_repository.update(
                    task_id, state="failed", revision=model.md5,
                    downloaded_bytes=downloaded, total_bytes=total,
                    metadata=job_metadata, error=message,
                )
            raise RuntimeError(f"Could not install Vosk model {model.name}: {message}") from exc
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            with self._condition:
                self._active.pop(model_id, None)
                self._cancel_events.pop(model_id, None)
                self._pause_events.pop(model_id, None)
                self._stop_events.pop(model_id, None)
                self._job_ids.pop(model_id, None)
                self._condition.notify_all()
