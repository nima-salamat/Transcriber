"""High-level model discovery, installation, active-model protection, and cleanup."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from transcriber.engines.faster_whisper import FasterWhisperEngine
from transcriber.engines.vosk import VoskEngine
from transcriber.models.compatibility import validate_faster_whisper_files, validate_repo_id
from transcriber.models.downloader import ModelDownloader
from transcriber.models.hub_client import HubModel, HuggingFaceHubClient
from transcriber.models.registry import ModelRegistry
from transcriber.models.vosk import (
    VoskModelCatalog,
    VoskModelDownloader,
    validate_vosk_model_directory,
)


class ModelManager:
    def __init__(
        self,
        registry: ModelRegistry,
        hub: HuggingFaceHubClient,
        downloader: ModelDownloader,
        *,
        vosk_catalog: VoskModelCatalog | None = None,
        vosk_downloader: VoskModelDownloader | None = None,
    ):
        self.registry = registry
        self.hub = hub
        self.downloader = downloader
        self.vosk_catalog = vosk_catalog or VoskModelCatalog()
        self.vosk_downloader = vosk_downloader or VoskModelDownloader(
            registry,
            self.vosk_catalog,
            job_repository=downloader.job_repository,
        )
        self._lock = threading.RLock()
        # Serialize model swaps/load/unload. A second worker must not detach a
        # model while the first worker is still materializing it in RAM.
        self._operation_lock = threading.RLock()
        self._active_model_id: str | None = None
        self._active_engine: FasterWhisperEngine | VoskEngine | None = None
        self._active_options: tuple | None = None
        self._active_runtime: str | None = None
        self._installing: set[str] = set()

    @property
    def active_downloads(self) -> int:
        with self._lock:
            return len(self._installing)

    def set_download_concurrency(self, value: int) -> None:
        self.downloader.set_max_concurrent(value)
        self.vosk_downloader.set_max_concurrent(value)

    @staticmethod
    def is_vosk_model_id(model_id: str) -> bool:
        return str(model_id).startswith(("vosk/", "vosk-hf/"))

    @property
    def job_repository(self):
        return self.downloader.job_repository

    def list_download_jobs(self, limit: int = 500) -> list[dict]:
        jobs = self.downloader.list_jobs(limit=limit)
        jobs.extend(self.vosk_downloader.list_jobs(limit=limit))
        jobs.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return jobs[:max(1, min(int(limit), 2000))]

    def pause_download(self, model_id: str) -> bool:
        return (
            self.vosk_downloader.pause(model_id)
            if self.is_vosk_model_id(model_id)
            else self.downloader.pause(model_id)
        )

    def stop_download(self, model_id: str) -> bool:
        return (
            self.vosk_downloader.stop(model_id)
            if self.is_vosk_model_id(model_id)
            else self.downloader.stop(model_id)
        )

    def cancel_download(self, model_id: str) -> bool:
        return (
            self.vosk_downloader.cancel(model_id)
            if self.is_vosk_model_id(model_id)
            else self.downloader.cancel(model_id)
        )

    def cancel_all_downloads(self) -> int:
        return self.downloader.cancel_all() + self.vosk_downloader.cancel_all()

    def clear_download_cache(self) -> None:
        # Keep the install reservation lock while the lower-level cache lock is held
        # so a new queued task cannot race the cleanup operation.
        with self._lock:
            if self._installing:
                raise RuntimeError("Cannot clear the model cache while downloads are queued or active")
            self.downloader.clear_cache()
            cache_root = self.registry.root / ".staging" / "vosk-download-cache"
            if cache_root.is_symlink():
                raise ValueError("Refusing to clear a symbolic-link Vosk download cache")
            if cache_root.exists():
                import shutil

                shutil.rmtree(cache_root)

    @property
    def active_model_id(self) -> str | None:
        with self._lock:
            return self._active_model_id

    def search(self, query: str = "", *, sort: str = "downloads", limit: int = 30) -> list[HubModel]:
        return self.hub.search(query, sort=sort, limit=limit)

    def search_vosk(
        self, query: str = "", *, limit: int = 50,
        language: str | None = None, source: str | None = None,
    ):
        return self.vosk_catalog.search(
            query, limit=limit, language=language, source=source,
        )

    def curated_vosk(self, language: str = "fa"):
        return self.vosk_catalog.curated(language)

    def inspect_vosk(self, model_id: str):
        return self.vosk_catalog.inspect(model_id)

    def inspect(self, repo_id: str):
        if self.is_vosk_model_id(repo_id):
            return self.inspect_vosk(repo_id)
        model = self.hub.inspect(validate_repo_id(repo_id))
        report = validate_faster_whisper_files(item.name for item in model.files)
        return model, report

    def install(
        self, repo_id: str, *, revision: str | None = None,
        cancel_event=None, progress=None, task_id: str | None = None,
        metadata: dict | None = None,
    ) -> Path:
        repo_id = validate_repo_id(repo_id)
        with self._lock:
            if repo_id == self._active_model_id:
                raise RuntimeError("Unload the active model before reinstalling it")
            if repo_id in self._installing:
                raise RuntimeError(f"A download for {repo_id} is already active")
            self._installing.add(repo_id)
        try:
            return self.downloader.download(
                repo_id, revision=revision, cancel_event=cancel_event,
                progress=progress, task_id=task_id, metadata=metadata,
            )
        finally:
            with self._lock:
                self._installing.discard(repo_id)

    def install_vosk(
        self, model_id: str, *, cancel_event=None, progress=None,
        task_id: str | None = None, metadata: dict | None = None,
    ) -> Path:
        model_id = str(model_id)
        if not self.is_vosk_model_id(model_id):
            model_id = "vosk/" + model_id
        with self._lock:
            if model_id == self._active_model_id:
                raise RuntimeError("Unload the active Vosk model before reinstalling it")
            if model_id in self._installing:
                raise RuntimeError(f"A download for {model_id} is already active")
            self._installing.add(model_id)
        try:
            return self.vosk_downloader.download(
                model_id,
                cancel_event=cancel_event,
                progress=progress,
                task_id=task_id,
                metadata=metadata,
            )
        finally:
            with self._lock:
                self._installing.discard(model_id)

    def resume_download(self, task_id: str, *, cancel_event=None, progress=None) -> Path:
        repository = self.job_repository
        if repository is None:
            raise RuntimeError("Persistent download history is unavailable.")
        job = repository.get(task_id)
        if job is None:
            raise KeyError(task_id)
        metadata = job.get("metadata") or {}
        if metadata.get("runtime") == "vosk" or self.is_vosk_model_id(job["repo_id"]):
            return self.install_vosk(
                job["repo_id"],
                cancel_event=cancel_event,
                progress=progress,
                task_id=job["task_id"],
                metadata=metadata,
            )
        return self.install(
            job["repo_id"], revision=job.get("revision"), cancel_event=cancel_event,
            progress=progress, task_id=job["task_id"], metadata=metadata,
        )

    def _publish_imported_directory(self, source: Path, repo_id: str) -> Path:
        """Validate and atomically register a local CTranslate2 model directory."""
        import hashlib
        import shutil
        import uuid

        repo_id = validate_repo_id(repo_id)
        if source.is_symlink() or not source.is_dir():
            raise ValueError("Choose a real local model directory, not a symbolic link.")
        root_files = [
            item.name for item in source.iterdir()
            if item.is_file() and not item.is_symlink()
        ]
        report = validate_faster_whisper_files(root_files)
        if not report.compatible:
            raise ValueError(
                report.reason + " Missing: " + ", ".join(report.missing_files)
            )
        target = self.registry.root / self.registry.directory_name(repo_id)
        if target.exists() or target.is_symlink():
            raise FileExistsError(
                f"A managed model already exists for {repo_id}; remove or rename it before importing."
            )
        staging_root = self.registry.root / ".staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        staging = staging_root / f"import-{uuid.uuid4().hex}"
        staging.mkdir(parents=False, exist_ok=False)
        digest = hashlib.sha256()
        try:
            total_size = sum((source / name).stat().st_size for name in report.included_files)
            if shutil.disk_usage(self.registry.root).free < total_size + 32 * 1024 * 1024:
                raise OSError("Not enough free disk space to import and validate this model.")
            for name in report.included_files:
                source_file = source / name
                if source_file.is_symlink() or not source_file.is_file() or source_file.parent != source:
                    raise ValueError(f"Model artefact is not a safe root-level file: {name}")
                destination = staging / name
                with source_file.open("rb") as reader, destination.open("xb") as writer:
                    while True:
                        chunk = reader.read(1024 * 1024)
                        if not chunk:
                            break
                        writer.write(chunk)
                        digest.update(name.encode("utf-8") + b"\0" + chunk)
            revision = "local-" + digest.hexdigest()
            manifest = {
                "repo_id": repo_id,
                "revision": revision,
                "engine": "faster-whisper",
                "files": list(report.included_files),
                "license": None,
                "source": "local-import",
            }
            (staging / ".transcriber-model.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            staging.rename(target)
            try:
                self.registry.register(
                    repo_id, target, revision=revision,
                    files=list(report.included_files), license_name=None,
                )
            except Exception:
                shutil.rmtree(target, ignore_errors=True)
                raise
            return target
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _publish_imported_vosk_directory(
        self, source: Path, repo_id: str, *, language_code: str | None = None,
    ) -> Path:
        """Copy a validated Vosk model tree into managed storage and register its runtime."""
        import hashlib
        import shutil
        import uuid

        if source.is_symlink() or not source.is_dir():
            raise ValueError("Choose a real Vosk model directory, not a symbolic link.")
        source = source.resolve(strict=True)
        report = validate_vosk_model_directory(source)
        if not report.compatible:
            raise ValueError(
                report.reason + " Missing: " + ", ".join(report.missing_files)
            )
        target = self.registry.root / self.registry.directory_name(repo_id)
        if target.exists() or target.is_symlink():
            raise FileExistsError(
                f"A managed model already exists for {repo_id}; remove or rename it before importing."
            )

        file_paths = []
        total_size = 0
        for item in source.rglob("*"):
            if item.is_symlink():
                raise ValueError(f"Vosk model contains a symbolic link: {item.relative_to(source)}")
            if item.is_file() and item.name != ".transcriber-model.json":
                resolved = item.resolve(strict=True)
                if not resolved.is_relative_to(source):
                    raise ValueError("Vosk model contains a file outside the selected directory.")
                file_paths.append(item)
                total_size += item.stat().st_size

        staging_root = self.registry.root / ".staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        staging = staging_root / f"vosk-import-{uuid.uuid4().hex}"
        staging.mkdir(parents=False, exist_ok=False)
        digest = hashlib.sha256()
        try:
            if shutil.disk_usage(self.registry.root).free < total_size + 64 * 1024 * 1024:
                raise OSError("Not enough free disk space to import and validate this Vosk model.")
            copied_files = []
            for source_file in file_paths:
                relative = source_file.relative_to(source)
                destination = staging / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                with source_file.open("rb") as reader, destination.open("xb") as writer:
                    while True:
                        chunk = reader.read(1024 * 1024)
                        if not chunk:
                            break
                        writer.write(chunk)
                        digest.update(relative.as_posix().encode("utf-8") + b"\\0" + chunk)
                copied_files.append(relative.as_posix())

            revision = "local-" + digest.hexdigest()
            manifest = {
                "repo_id": repo_id,
                "revision": revision,
                "engine": "vosk",
                "runtime": "vosk",
                "files": sorted(copied_files),
                "language_code": language_code,
                "language_name": None,
                "model_name": source.name,
                "model_type": "local-import",
                "license": None,
                "source": "local-import",
            }
            (staging / ".transcriber-model.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            staging.rename(target)
            try:
                self.registry.register(
                    repo_id,
                    target,
                    revision=revision,
                    files=copied_files,
                    license_name=None,
                    runtime="vosk",
                    metadata={
                        "language_code": language_code,
                        "model_name": source.name,
                        "source": "local-import",
                    },
                )
            except Exception:
                shutil.rmtree(target, ignore_errors=True)
                raise
            return target
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def import_vosk_directory(
        self, source: str | Path, repo_id: str, *, language_code: str | None = None,
    ) -> Path:
        repo_id = self._reserve_import(repo_id)
        try:
            path = Path(source).expanduser()
            if path.is_symlink():
                raise ValueError("Importing a symbolic-link directory is not allowed.")
            return self._publish_imported_vosk_directory(
                path.resolve(), repo_id, language_code=language_code,
            )
        finally:
            with self._lock:
                self._installing.discard(repo_id)

    def import_vosk_zip(
        self, archive_path: str | Path, repo_id: str, *, language_code: str | None = None,
    ) -> Path:
        """Safely extract a local ZIP and import its contained Vosk model tree."""
        import shutil
        import stat
        import uuid
        import zipfile
        from pathlib import PurePosixPath

        repo_id = self._reserve_import(repo_id)
        archive = Path(archive_path).expanduser()
        if archive.is_symlink() or not archive.is_file():
            with self._lock:
                self._installing.discard(repo_id)
            raise FileNotFoundError(f"Vosk ZIP archive does not exist: {archive}")

        staging_root = self.registry.root / ".staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        extraction = staging_root / f"vosk-zip-import-{uuid.uuid4().hex}"
        extraction.mkdir(parents=False, exist_ok=False)
        try:
            with zipfile.ZipFile(archive, "r") as package:
                entries = package.infolist()
                if len(entries) > 20_000:
                    raise ValueError("Vosk ZIP contains too many entries (maximum 20,000).")
                unpacked_total = sum(item.file_size for item in entries if not item.is_dir())
                if unpacked_total > 32 * 1024**3:
                    raise ValueError("Vosk ZIP expands beyond the 32 GiB import safety limit.")
                if shutil.disk_usage(self.registry.root).free < unpacked_total + 128 * 1024**2:
                    raise OSError("Not enough free disk space to extract this Vosk model.")
                extraction_root = extraction.resolve()
                for entry in entries:
                    raw_name = entry.filename
                    if "\\\\" in raw_name:
                        raise ValueError("ZIP entries with backslash paths are not accepted.")
                    member = PurePosixPath(raw_name)
                    if (
                        member.is_absolute()
                        or not member.parts
                        or ".." in member.parts
                        or any(part.endswith(":") for part in member.parts)
                    ):
                        raise ValueError(f"Unsafe Vosk ZIP path: {raw_name}")
                    if stat.S_ISLNK(entry.external_attr >> 16):
                        raise ValueError(f"Vosk ZIP symbolic links are not accepted: {raw_name}")
                    if entry.flag_bits & 0x1:
                        raise ValueError(f"Encrypted Vosk ZIP entries are not supported: {raw_name}")
                    destination = extraction.joinpath(*member.parts)
                    if not destination.resolve().is_relative_to(extraction_root):
                        raise ValueError(f"ZIP path escapes the import directory: {raw_name}")
                    if entry.is_dir():
                        destination.mkdir(parents=True, exist_ok=True)
                        continue
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    written = 0
                    with package.open(entry, "r") as reader, destination.open("xb") as writer:
                        while True:
                            chunk = reader.read(1024 * 1024)
                            if not chunk:
                                break
                            written += len(chunk)
                            if written > entry.file_size or written > 32 * 1024**3:
                                raise ValueError("Vosk ZIP entry expanded beyond its declared size.")
                            writer.write(chunk)
                    if written != entry.file_size:
                        raise ValueError(f"Vosk ZIP entry size mismatch: {raw_name}")

            directories = [extraction]
            directories.extend(
                item for item in extraction.rglob("*")
                if item.is_dir() and not item.is_symlink()
            )
            model_roots = [
                item for item in directories
                if validate_vosk_model_directory(item).compatible
            ]
            if len(model_roots) != 1:
                raise ValueError(
                    "The ZIP must contain exactly one valid Vosk model directory; "
                    f"found {len(model_roots)}."
                )
            return self._publish_imported_vosk_directory(
                model_roots[0], repo_id, language_code=language_code,
            )
        finally:
            shutil.rmtree(extraction, ignore_errors=True)
            with self._lock:
                self._installing.discard(repo_id)

    def _reserve_import(self, repo_id: str) -> str:
        repo_id = validate_repo_id(repo_id)
        with self._lock:
            if repo_id == self._active_model_id:
                raise RuntimeError("Unload the active model before replacing it with a local import.")
            if repo_id in self._installing:
                raise RuntimeError(f"A model operation for {repo_id} is already active.")
            self._installing.add(repo_id)
        return repo_id

    def import_directory(self, source: str | Path, repo_id: str) -> Path:
        """Import a local Faster-Whisper/CTranslate2 directory."""
        repo_id = self._reserve_import(repo_id)
        try:
            path = Path(source).expanduser()
            if path.is_symlink():
                raise ValueError("Importing a symbolic-link directory is not allowed.")
            return self._publish_imported_directory(path.resolve(), repo_id)
        finally:
            with self._lock:
                self._installing.discard(repo_id)

    def import_zip(self, archive_path: str | Path, repo_id: str) -> Path:
        """Safely extract and import a ZIP without path traversal or symlink entries."""
        repo_id = self._reserve_import(repo_id)
        try:
            return self._import_zip_contents(archive_path, repo_id)
        finally:
            with self._lock:
                self._installing.discard(repo_id)

    def _import_zip_contents(self, archive_path: str | Path, repo_id: str) -> Path:
        import shutil
        import stat
        import uuid
        import zipfile
        from pathlib import PurePosixPath

        archive = Path(archive_path).expanduser()
        if archive.is_symlink() or not archive.is_file():
            raise FileNotFoundError(f"Model ZIP archive does not exist: {archive}")
        staging_root = self.registry.root / ".staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        extraction = staging_root / f"zip-import-{uuid.uuid4().hex}"
        extraction.mkdir(parents=False, exist_ok=False)
        try:
            with zipfile.ZipFile(archive, "r") as package:
                entries = package.infolist()
                if len(entries) > 10_000:
                    raise ValueError("ZIP contains too many entries to import safely (maximum 10,000).")
                total_unpacked = sum(entry.file_size for entry in entries if not entry.is_dir())
                max_unpacked = 32 * 1024**3
                if total_unpacked > max_unpacked:
                    raise ValueError("ZIP expands beyond the 32 GB import safety limit.")
                if shutil.disk_usage(self.registry.root).free < total_unpacked + 64 * 1024 * 1024:
                    raise OSError("Not enough free disk space to extract and validate this model.")
                extraction_root = extraction.resolve()
                for entry in entries:
                    raw_name = entry.filename
                    if "\\" in raw_name:
                        raise ValueError("ZIP entries with backslash paths are not accepted.")
                    member = PurePosixPath(raw_name)
                    if (
                        member.is_absolute()
                        or not member.parts
                        or ".." in member.parts
                        or any(part.endswith(":") for part in member.parts)
                    ):
                        raise ValueError(f"Unsafe ZIP path: {raw_name}")
                    mode = entry.external_attr >> 16
                    if stat.S_ISLNK(mode):
                        raise ValueError(f"ZIP symbolic links are not accepted: {raw_name}")
                    destination = extraction.joinpath(*member.parts)
                    resolved = destination.resolve()
                    if not resolved.is_relative_to(extraction_root):
                        raise ValueError(f"ZIP path escapes the import directory: {raw_name}")
                    if entry.is_dir():
                        destination.mkdir(parents=True, exist_ok=True)
                        continue
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if entry.flag_bits & 0x1:
                        raise ValueError(f"Encrypted ZIP entries are not supported: {raw_name}")
                    actual_written = 0
                    with package.open(entry, "r") as reader, destination.open("xb") as writer:
                        while True:
                            chunk = reader.read(1024 * 1024)
                            if not chunk:
                                break
                            actual_written += len(chunk)
                            if actual_written > max_unpacked:
                                raise ValueError("ZIP expanded beyond the 32 GB import safety limit.")
                            writer.write(chunk)
                    if actual_written != entry.file_size:
                        raise ValueError(f"ZIP entry size mismatch: {raw_name}")

            source_root = extraction
            root_report = validate_faster_whisper_files(
                item.name for item in source_root.iterdir() if item.is_file()
            )
            if not root_report.compatible:
                directories = [
                    item for item in extraction.iterdir()
                    if item.is_dir() and not item.is_symlink()
                ]
                if len(directories) == 1 and not any(
                    item.is_file() for item in extraction.iterdir()
                ):
                    source_root = directories[0]
            return self._publish_imported_directory(source_root, repo_id)
        finally:
            shutil.rmtree(extraction, ignore_errors=True)

    def get_engine(self, repo_id: str, settings=None):
        repo_id = validate_repo_id(repo_id)
        with self._operation_lock, self._lock:
            if repo_id in self._installing:
                raise RuntimeError("Wait for model installation to finish before loading it")
            model_path = self.registry.get_path(repo_id)
            if model_path is None:
                raise FileNotFoundError(f"Model is not installed or its manifest is missing: {repo_id}")
            try:
                manifest = json.loads(
                    (model_path / ".transcriber-model.json").read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as exc:
                raise RuntimeError("Installed model manifest is missing or unreadable") from exc
            runtime = str(manifest.get("engine", manifest.get("runtime", "faster-whisper")))
            if runtime == "vosk":
                report = validate_vosk_model_directory(model_path)
                if not report.compatible:
                    raise RuntimeError(
                        "Installed Vosk model is incomplete or corrupted. "
                        + report.reason + " Missing: " + ", ".join(report.missing_files)
                    )
                options = (manifest.get("language_code"),)
                if (
                    self._active_engine
                    and self._active_model_id == repo_id
                    and self._active_runtime == runtime
                    and self._active_options == options
                ):
                    return self._active_engine
                if self._active_engine:
                    self._active_engine.unload()
                self._active_engine = VoskEngine(
                    model_path,
                    language=manifest.get("language_code"),
                )
                self._active_options = options
                self._active_runtime = runtime
                self._active_model_id = repo_id
                return self._active_engine

            if runtime != "faster-whisper":
                raise RuntimeError(f"Unsupported installed model runtime: {runtime}")
            files = manifest.get("files", [])
            report = validate_faster_whisper_files(files)
            if not report.compatible or any(
                (model_path / name).is_symlink() or not (model_path / name).is_file()
                for name in report.included_files
            ):
                raise RuntimeError(
                    "Installed model is incomplete or corrupted. Reinstall this model from Model Library."
                )
            options = (
                getattr(settings, "device", "auto"),
                getattr(settings, "compute_type", "int8"),
                getattr(settings, "cpu_threads", 0),
            )
            if (
                self._active_engine
                and self._active_model_id == repo_id
                and self._active_runtime == runtime
                and self._active_options == options
            ):
                return self._active_engine
            if self._active_engine:
                self._active_engine.unload()
            self._active_engine = FasterWhisperEngine(
                model_path, device=options[0], compute_type=options[1], cpu_threads=options[2],
            )
            self._active_options = options
            self._active_runtime = runtime
            self._active_model_id = repo_id
            return self._active_engine

    def load(self, repo_id: str, settings=None):
        """Materialize the selected runtime. Invoke from a background worker."""
        with self._operation_lock:
            engine = self.get_engine(repo_id, settings)
            engine.load()
            return engine

    def unload_active(self) -> None:
        with self._operation_lock, self._lock:
            if self._active_engine:
                self._active_engine.unload()
            self._active_engine = None
            self._active_model_id = None
            self._active_options = None
            self._active_runtime = None

    def set_active(self, repo_id: str | None) -> None:
        if repo_id is None:
            self.unload_active()
            return
        self.get_engine(repo_id)

    def installed(self, *, include_sizes: bool = True) -> list[dict]:
        """List installed models; full size scans should run in a worker thread."""
        results = []
        for item in self.registry.list_installed(include_sizes=include_sizes):
            path = Path(item["path"])
            registered_files = item.get("files") or []
            if include_sizes:
                actual_files = [
                    candidate.relative_to(path).as_posix()
                    for candidate in path.rglob("*")
                    if candidate.is_file() and not candidate.is_symlink()
                ]
            else:
                # Avoid an unbounded recursive filesystem scan in lightweight UI refreshes.
                actual_files = [
                    name for name in registered_files
                    if (path / name).is_file() and not (path / name).is_symlink()
                ]
            manifest_path = path / ".transcriber-model.json"
            manifest_ok = manifest_path.is_file() and not manifest_path.is_symlink()
            runtime = str(item.get("runtime") or "faster-whisper")
            item["runtime"] = runtime
            if not manifest_ok:
                compatible = False
                message = "Model manifest is missing or invalid; reinstall this model."
            elif runtime == "vosk":
                report = validate_vosk_model_directory(path)
                compatible = report.compatible
                message = report.reason
                if report.missing_files:
                    message += " Missing: " + ", ".join(report.missing_files)
            elif runtime == "faster-whisper":
                report = validate_faster_whisper_files(actual_files)
                compatible = report.compatible
                message = report.reason
            else:
                compatible = False
                message = f"Unsupported model runtime: {runtime}"
            item["compatible"] = compatible
            item["compatibility_message"] = message
            item["active"] = item["repo_id"] == self.active_model_id
            results.append(item)
        return results

    def delete(self, repo_id: str) -> None:
        with self._lock:
            if repo_id in self._installing:
                raise RuntimeError("Wait for the model download to finish before deleting it")
            active = self._active_model_id
        self.registry.delete(repo_id, active_model_id=active)
