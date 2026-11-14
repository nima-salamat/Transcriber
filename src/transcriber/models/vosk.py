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
class VoskArchiveFile:
    name: str
    size: int | None


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
    download_url: str
    version: str
    obsolete: bool = False
    runtime: str = "vosk"
    source: str = "official"
    source_repo: str | None = None
    source_file: str | None = None
    source_revision: str | None = None
    sha256: str | None = None
    license_name: str | None = None
    provider: str = "Vosk"
    task: str = "automatic-speech-recognition"
    author: str = "AlphaCephei"
    description: str = ""

    @property
    def files(self) -> tuple[VoskArchiveFile, ...]:
        return (VoskArchiveFile(f"{self.name}.zip", self.size_bytes),)

    @property
    def checksum(self) -> str:
        return self.sha256 or self.md5

    @property
    def checksum_algorithm(self) -> str:
        return "sha256" if self.sha256 else "md5"

    @property
    def revision(self) -> str:
        return self.checksum

    @property
    def license(self) -> str | None:
        return self.license_name

    @property
    def source_label(self) -> str:
        if self.source == "huggingface":
            return f"Hugging Face · {self.source_repo}"
        return "Official Vosk catalogue"

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
            "sha256": self.sha256,
            "checksum": self.checksum,
            "checksum_algorithm": self.checksum_algorithm,
            "url": self.url,
            "download_url": self.download_url,
            "version": self.version,
            "source": self.source,
            "source_repo": self.source_repo,
            "source_file": self.source_file,
            "source_revision": self.source_revision,
            "license_name": self.license_name,
            "catalogue": MODEL_LIST_URL if self.source == "official" else None,
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


def _validate_archive_source(model: VoskModelInfo) -> str:
    """Only permit the official Vosk host or a pinned, curated Hugging Face mirror."""
    parsed = urlparse(model.download_url)
    if model.source == "official":
        return _safe_model_url(model.download_url, model.name)
    if model.source == "huggingface":
        expected_path = (
            f"/{model.source_repo}/resolve/{model.source_revision}/{model.source_file}"
        )
        if (
            parsed.scheme != "https"
            or parsed.hostname != "huggingface.co"
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or parsed.query
            or parsed.fragment
            or not model.source_repo
            or not model.source_file
            or not model.source_revision
            or parsed.path != expected_path
        ):
            raise ValueError(
                "Vosk mirror URL does not match its pinned Hugging Face repository, revision and file"
            )
        return model.download_url
    raise ValueError(f"Unsupported Vosk download source: {model.source!r}")


def _download_vosk_archive(
    url: str,
    partial: Path,
    *,
    timeout: float,
    downloaded: int,
    total: int | None,
    check_events: Callable[[], None],
    progress: Callable[[int, int | None, str], None],
) -> tuple[int, int | None]:
    """Download a Vosk ZIP with safe resume and recovery from stale HTTP Range state."""
    if downloaded and total is not None and downloaded == total and partial.is_file():
        # The previous attempt may have completed the archive but failed before validation.
        return downloaded, total

    for attempt in range(2):
        check_events()
        headers = {
            "User-Agent": "Transcriber-Desktop/2.1",
            "Accept": "application/zip",
        }
        if downloaded:
            headers["Range"] = f"bytes={downloaded}-"
        request = urllib.request.Request(url, headers=headers)

        try:
            response = urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code != 416 or not downloaded:
                raise
            content_range = str(exc.headers.get("Content-Range", "") if exc.headers else "")
            match = re.fullmatch(r"bytes\s+\*/(\d+)", content_range.strip(), re.IGNORECASE)
            remote_size = int(match.group(1)) if match else None
            exc.close()

            if (
                remote_size is not None
                and remote_size == downloaded
                and (total is None or total == remote_size)
                and partial.is_file()
            ):
                return downloaded, total if total is not None else remote_size

            # A stale/oversized partial file is not resumable. Discard it and retry once
            # without Range so the server sends a clean full response.
            partial.unlink(missing_ok=True)
            downloaded = 0
            progress(downloaded, total, "The saved partial download was rejected; restarting from the beginning")
            continue

        with response:
            status = int(getattr(response, "status", getattr(response, "code", 200)) or 200)
            response_headers = getattr(response, "headers", None)
            content_range = str(
                response_headers.get("Content-Range", "") if response_headers else ""
            )
            append = False

            if status == 206:
                match = re.fullmatch(
                    r"bytes\s+(\d+)-(\d+)/(\d+|\*)",
                    content_range.strip(),
                    re.IGNORECASE,
                )
                range_start = int(match.group(1)) if match else None
                range_total = (
                    int(match.group(3))
                    if match and match.group(3) != "*"
                    else None
                )
                if range_start != downloaded:
                    if attempt == 0:
                        partial.unlink(missing_ok=True)
                        downloaded = 0
                        progress(
                            downloaded, total,
                            "The server returned an inconsistent byte range; restarting the download",
                        )
                        continue
                    raise OSError("Vosk server returned an invalid Content-Range response")
                append = downloaded > 0
                if range_total is not None:
                    if total is not None and total != range_total:
                        partial.unlink(missing_ok=True)
                        downloaded = 0
                        progress(
                            downloaded, total,
                            "The archive size changed at source; discarding the old partial download",
                        )
                        if attempt == 0:
                            continue
                        raise OSError(
                            f"Vosk archive size changed at source: expected {total:,} bytes, "
                            f"server reports {range_total:,} bytes"
                        )
                    total = range_total if total is None else total
            elif status == 200:
                if downloaded:
                    # Some hosts ignore Range and return the entire archive. Never append
                    # a full response to an old partial file.
                    partial.unlink(missing_ok=True)
                    downloaded = 0
                raw_length = (
                    response_headers.get("Content-Length")
                    if response_headers else None
                )
                try:
                    response_length = int(raw_length) if raw_length is not None else None
                except (TypeError, ValueError):
                    response_length = None
                if response_length is not None and response_length > 0:
                    if total is not None and total != response_length:
                        raise OSError(
                            f"Vosk archive size changed at source: expected {total:,} bytes, "
                            f"server reports {response_length:,} bytes"
                        )
                    total = response_length if total is None else total
            else:
                raise OSError(f"Vosk archive server returned unexpected HTTP status {status}")

            mode = "ab" if append else "wb"
            exceeded_expected_size = False
            with partial.open(mode) as stream:
                while True:
                    check_events()
                    chunk = response.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    if total is not None and downloaded + len(chunk) > total:
                        exceeded_expected_size = True
                        break
                    stream.write(chunk)
                    downloaded += len(chunk)
                    progress(downloaded, total, "Receiving Vosk model archive")
                stream.flush()
                os.fsync(stream.fileno())

            if exceeded_expected_size:
                partial.unlink(missing_ok=True)
                raise OSError(
                    f"Vosk archive exceeded its expected size of {total:,} bytes; "
                    "the source may be pointing to a different model"
                )

        return downloaded, total

    raise OSError("Vosk archive could not be resumed; retry the download")


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
            url=MODEL_PAGE_URL,
            download_url=url,
            version=version,
            obsolete=obsolete,
            description=description,
            license_name="Apache-2.0" if language == "fa" else None,
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
        self._hub_models: tuple[VoskModelInfo, ...] | None = None

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

    @staticmethod
    def _pinned_persian_official_models() -> tuple[VoskModelInfo, ...]:
        """Known-good official Farsi 0.42 entries used when the live catalogue is offline."""
        return (
            VoskModelInfo(
                repo_id="vosk/vosk-model-small-fa-0.42",
                name="vosk-model-small-fa-0.42",
                language="fa",
                language_name="Farsi",
                model_type="small",
                size_bytes=53_431_220,
                size_text="51.0 MiB",
                md5="cc2b18af256ffab2c44055f6a02ecb3d",
                url=MODEL_PAGE_URL,
                download_url="https://alphacephei.com/vosk/models/vosk-model-small-fa-0.42.zip",
                version="0.42",
                license_name="Apache-2.0",
                description=(
                    "Persian / Farsi · lightweight Vosk / Kaldi model · 51.0 MiB · "
                    "official AlphaCephei release for desktop and mobile use."
                ),
            ),
            VoskModelInfo(
                repo_id="vosk/vosk-model-fa-0.42",
                name="vosk-model-fa-0.42",
                language="fa",
                language_name="Farsi",
                model_type="big",
                size_bytes=1_667_089_770,
                size_text="1.6 GiB",
                md5="c47c8e497e35e5e3a27cb71c4f0af275",
                url=MODEL_PAGE_URL,
                download_url="https://alphacephei.com/vosk/models/vosk-model-fa-0.42.zip",
                version="0.42",
                license_name="Apache-2.0",
                description=(
                    "Persian / Farsi · large-vocabulary Vosk / Kaldi model · 1.6 GiB · "
                    "official AlphaCephei release with a larger decoding vocabulary."
                ),
            ),
        )

    @staticmethod
    def _huggingface_curated_models() -> tuple[VoskModelInfo, ...]:
        """Pinned Vosk ZIP mirrors whose files are validated after extraction."""
        return (
            VoskModelInfo(
                repo_id="vosk-hf/localstack-vosk-model-small-fa-0.42",
                name="vosk-model-small-fa-0.42",
                language="fa",
                language_name="Farsi / Persian",
                model_type="small",
                # Exact LFS blob size from the pinned Hugging Face file; do not
                # leave this unknown or let a redirect redefine the model's size.
                size_bytes=53_431_220,
                size_text="51.0 MiB · 53.4 MB",
                md5="cc2b18af256ffab2c44055f6a02ecb3d",
                url=(
                    "https://huggingface.co/localstack/vosk-models/blob/134b459/"
                    "vosk-model-small-fa-0.42.zip"
                ),
                download_url=(
                    "https://huggingface.co/localstack/vosk-models/resolve/134b459/"
                    "vosk-model-small-fa-0.42.zip"
                ),
                version="0.42",
                source="huggingface",
                source_repo="localstack/vosk-models",
                source_file="vosk-model-small-fa-0.42.zip",
                source_revision="134b459",
                sha256="977cb5faa538f3a835ccfd35f5f6d8284b5c450b89c700b9bd4736b66536ad46",
                license_name="Apache-2.0 (upstream Vosk model)",
                author="LocalStack",
                description=(
                    "Persian / Farsi · lightweight Vosk / Kaldi model · 51.0 MiB (53.4 MB). "
                    "Pinned Hugging Face ZIP mirror with a fixed 53,431,220-byte archive size, "
                    "SHA-256 verification and Vosk directory-layout validation."
                ),
            ),
        )

    def list_all_models(
        self, *, include_obsolete: bool = False, include_huggingface: bool = True,
        refresh: bool = False,
    ) -> list[VoskModelInfo]:
        try:
            models = self.list_models(
                include_obsolete=include_obsolete, refresh=refresh,
            )
        except RuntimeError:
            # Keep the two known-good current Persian models discoverable even when
            # AlphaCephei's live catalogue cannot be reached. The Hugging Face mirror
            # is added below as a separately identifiable download source.
            with self._lock:
                models = [
                    item for item in self._models
                    if include_obsolete or not item.obsolete
                ]
            if not models and not include_obsolete:
                models.extend(self._pinned_persian_official_models())
            elif not models and include_obsolete:
                models.extend(self._pinned_persian_official_models())
        if include_huggingface:
            with self._lock:
                if self._hub_models is None:
                    self._hub_models = self._huggingface_curated_models()
                mirrors = self._hub_models
            models.extend(mirrors)
        return models

    def search(
        self,
        query: str = "",
        *,
        limit: int = 50,
        language: str | None = None,
        source: str | None = None,
    ) -> list[VoskModelInfo]:
        models = self.list_all_models()
        selected_language = str(language or "").strip().casefold()
        if selected_language and selected_language not in {"all", "*"}:
            aliases = {
                "persian": "fa", "farsi": "fa", "فارسی": "fa", "ایرانی": "fa",
                "english": "en", "german": "de", "french": "fr", "spanish": "es",
                "arabic": "ar", "russian": "ru", "chinese": "cn", "hindi": "hi",
                "italian": "it", "turkish": "tr",
            }
            selected_language = aliases.get(selected_language, selected_language)
            models = [item for item in models if item.language.casefold().startswith(selected_language)]
        selected_source = str(source or "").strip().casefold()
        if selected_source in {"official", "huggingface"}:
            models = [item for item in models if item.source == selected_source]

        normalised = " ".join(str(query or "").casefold().split())
        if normalised:
            tokens = normalised.split()
            aliases = {
                "persian": "fa", "farsi": "fa", "فارسی": "fa", "ایرانی": "fa",
                "english": "en", "german": "de", "french": "fr",
                "spanish": "es", "vosk": "", "model": "", "مدل": "",
                "speech": "", "recognition": "", "asr": "",
            }
            tokens = [aliases.get(token, token) for token in tokens]
            tokens = [token for token in tokens if token]
            models = [
                model for model in models
                if all(
                    token in " ".join((
                        model.name, model.repo_id, model.language, model.language_name,
                        model.model_type, model.description, model.source_repo or "",
                    )).casefold()
                    for token in tokens
                )
            ]
        models.sort(key=lambda item: (
            item.language != "fa",
            item.source != "official",
            item.model_type != "small",
            item.size_bytes if item.size_bytes else 10**18,
            item.name.casefold(),
        ))
        return models[:max(1, min(int(limit), 200))]

    def curated(self, language: str = "fa") -> list[VoskModelInfo]:
        """Return the two actively recommended Persian models, not obsolete variants."""
        selected = str(language or "").strip().casefold()
        if selected in {"fa", "farsi", "persian", "فارسی", "ایرانی"}:
            try:
                official = {
                    item.name: item
                    for item in self.list_models(include_obsolete=False)
                    if item.language.casefold() == "fa"
                }
            except RuntimeError:
                official = {
                    item.name: item
                    for item in self._pinned_persian_official_models()
                }
            mirror = self._huggingface_curated_models()
            small_mirror = next(
                item for item in mirror
                if item.name == "vosk-model-small-fa-0.42"
            )
            large_official = official.get("vosk-model-fa-0.42")
            if large_official is None:
                large_official = next(
                    item for item in self._pinned_persian_official_models()
                    if item.name == "vosk-model-fa-0.42"
                )
            # Exactly two choices: lightweight HF mirror and the full-size official model.
            return [small_mirror, large_official]
        models = self.search(language=selected, limit=100)
        models.sort(key=lambda item: (
            item.model_type != "small",
            item.size_bytes if item.size_bytes else 10**18,
            item.source != "official",
            item.name.casefold(),
        ))
        return models

    def inspect(self, model_id: str) -> tuple[VoskModelInfo, VoskCompatibilityReport]:
        model = self.by_name(model_id, include_obsolete=True)
        report = VoskCompatibilityReport(
            compatible=not model.obsolete,
            missing_files=("This model is marked obsolete in the official catalogue",) if model.obsolete else (),
            included_files=(
                "official Vosk API catalogue entry" if model.source == "official"
                else f"Hugging Face archive · {model.source_repo}"
            , "HTTPS ZIP source", f"{model.checksum_algorithm.upper()} checksum"),
            reason=(
                f"Listed by {model.source_label}. The ZIP checksum and Vosk model directory "
                "layout will be verified before installation."
                if not model.obsolete else
                "The official catalogue marks this model as obsolete. It can be inspected but not installed."
            ),
        )
        return model, report

    def by_name(self, model_id: str, *, include_obsolete: bool = True) -> VoskModelInfo:
        lookup = str(model_id or "").strip()
        models = self.list_all_models(include_obsolete=include_obsolete)
        found = next(
            (
                item for item in models
                if lookup in {item.repo_id, item.name}
                or lookup == f"vosk/{item.name}"
            ),
            None,
        )
        if found is None:
            raise KeyError(f"Vosk model is not available: {lookup}")
        return found



def _iter_vosk_model_roots(root: Path, *, max_depth: int = 8):
    """Yield real directories in an extracted archive without following symlinks."""
    root_depth = len(root.parts)
    for current, directories, _files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        depth = len(current_path.parts) - root_depth
        if depth >= max_depth:
            directories[:] = []
        else:
            directories[:] = sorted(
                name for name in directories
                if not (current_path / name).is_symlink()
            )
        yield current_path


def _validate_vosk_model_root(root: Path) -> VoskCompatibilityReport:
    """Check one candidate against the layouts actually loaded by Vosk API."""
    try:
        root = root.resolve(strict=True)
    except (OSError, RuntimeError):
        return VoskCompatibilityReport(
            compatible=False,
            missing_files=("model directory",),
            reason="Vosk model directory cannot be resolved safely.",
        )

    def has_file(relative: str) -> bool:
        candidate = root / relative
        try:
            return (
                not candidate.is_symlink()
                and candidate.is_file()
                and candidate.resolve(strict=True).is_relative_to(root)
            )
        except (OSError, RuntimeError, ValueError):
            return False

    included: list[str] = []
    missing: list[str] = []
    has_v2_marker = has_file("am/final.mdl") or has_file("conf/model.conf")
    if has_v2_marker:
        layout = "Vosk v2"
        for required in ("am/final.mdl", "conf/model.conf"):
            if has_file(required):
                included.append(required)
            else:
                missing.append(required)

        feature_configs = [
            name for name in ("conf/mfcc.conf", "conf/fbank.conf")
            if has_file(name)
        ]
        if feature_configs:
            included.extend(feature_configs)
        else:
            missing.append("conf/mfcc.conf or conf/fbank.conf")

        if has_file("graph/HCLG.fst"):
            included.append("graph/HCLG.fst")
        elif has_file("graph/HCLr.fst") and has_file("graph/Gr.fst"):
            included.extend(("graph/HCLr.fst", "graph/Gr.fst"))
            if has_file("graph/disambig_tid.int"):
                included.append("graph/disambig_tid.int")
            else:
                missing.append("graph/disambig_tid.int")
        else:
            missing.append("graph/HCLG.fst or graph/HCLr.fst + graph/Gr.fst")

        # Vosk first tries the symbol table embedded in the FST. words.txt is
        # only needed for models whose graph does not contain output symbols.
        if has_file("graph/words.txt"):
            included.append("graph/words.txt")
    else:
        layout = "legacy Vosk"
        for required in ("final.mdl",):
            if has_file(required):
                included.append(required)
            else:
                missing.append(required)

        feature_configs = [
            name for name in ("mfcc.conf", "fbank.conf") if has_file(name)
        ]
        if feature_configs:
            included.extend(feature_configs)
        else:
            missing.append("mfcc.conf or fbank.conf")

        if has_file("HCLG.fst"):
            included.append("HCLG.fst")
        elif has_file("HCLr.fst") and has_file("Gr.fst"):
            included.extend(("HCLr.fst", "Gr.fst"))
            if has_file("disambig_tid.int"):
                included.append("disambig_tid.int")
            else:
                missing.append("disambig_tid.int")
        else:
            missing.append("HCLG.fst or HCLr.fst + Gr.fst")

        if has_file("words.txt"):
            included.append("words.txt")

    if missing:
        return VoskCompatibilityReport(
            compatible=False,
            missing_files=tuple(missing),
            included_files=tuple(sorted(set(included))),
            reason=(
                f"The candidate directory does not satisfy the {layout} model layout "
                "used by Vosk API."
            ),
        )
    return VoskCompatibilityReport(
        compatible=True,
        included_files=tuple(sorted(set(included))),
        reason=(
            f"Vosk API {layout} model structure found. "
            "Model weights are not loaded during inspection."
        ),
    )


def _find_vosk_model_directory(
    path: str | Path,
) -> tuple[Path | None, VoskCompatibilityReport]:
    """Find the real model root, even when the ZIP adds several wrapper folders."""
    root = Path(path).expanduser()
    if root.is_symlink() or not root.is_dir():
        return None, VoskCompatibilityReport(
            compatible=False,
            missing_files=("model directory",),
            reason="Vosk model path must be a real directory, not a symbolic link.",
        )
    try:
        root = root.resolve(strict=True)
    except (OSError, RuntimeError):
        return None, VoskCompatibilityReport(
            compatible=False,
            missing_files=("model directory",),
            reason="Vosk model directory cannot be resolved safely.",
        )

    best_path: Path | None = None
    best_report: VoskCompatibilityReport | None = None
    best_score: tuple[int, int] | None = None
    for candidate in _iter_vosk_model_roots(root):
        report = _validate_vosk_model_root(candidate)
        if report.compatible:
            return candidate, report
        score = (len(report.missing_files), -len(report.included_files))
        if best_score is None or score < best_score:
            best_path, best_report, best_score = candidate, report, score

    return best_path, best_report or VoskCompatibilityReport(
        compatible=False,
        missing_files=("Vosk model files",),
        reason="No model directory was found in the extracted archive.",
    )


def validate_vosk_model_directory(path: str | Path) -> VoskCompatibilityReport:
    """Validate a Vosk directory or archive root, including nested model folders."""
    _model_root, report = _find_vosk_model_directory(path)
    return report


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
            state = {"cancel": "cancelling", "pause": "pausing", "stop": "stopping"}[kind]
            self.job_repository.update(task_id, state=state)
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
        if metadata:
            expected = str(
                metadata.get("checksum") or metadata.get("sha256")
                or metadata.get("md5") or metadata.get("revision") or ""
            ).strip().casefold()
            if expected and expected != model.revision.casefold():
                raise RuntimeError(
                    "The Vosk catalogue revision/checksum changed since this download was created. "
                    "Start a fresh install after inspecting the updated entry."
                )
            expected_size = metadata.get("size_bytes")
            if expected_size not in (None, "", 0, "0"):
                try:
                    expected_size = int(expected_size)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise RuntimeError("The saved Vosk model size is invalid; inspect the model again.") from exc
                if expected_size != model.size_bytes:
                    raise RuntimeError(
                        "The selected Vosk model size no longer matches its inspected catalogue entry. "
                        "Inspect the model again before downloading."
                    )
            expected_url = str(metadata.get("download_url") or "").strip()
            if expected_url and expected_url != model.download_url:
                raise RuntimeError(
                    "The selected Vosk download URL no longer matches its inspected catalogue entry. "
                    "Inspect the model again before downloading."
                )
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
        cache_key = hashlib.sha256(
            (model.repo_id + model.checksum_algorithm + model.revision).encode("utf-8")
        ).hexdigest()
        partial = cache_root / f"{cache_key}.zip.partial"
        staging = staging_root / f"vosk-{cache_key}-{task_id}"
        target = self.registry.root / self.registry.directory_name(model.repo_id)
        total = model.size_bytes or None
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
                    revision=model.revision,
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
            archive_url = _validate_archive_source(model)
            if self.job_repository:
                self.job_repository.enqueue(
                    task_id, model.repo_id, model.revision, str(target), job_metadata,
                )
            emit("Queued", f"Waiting for a model download slot · {model.source_label}")
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
            if total is not None and downloaded > total:
                partial.unlink()
                downloaded = 0
            emit("Downloading", f"Downloading Vosk model archive from {model.source_label}")

            def report_transfer(current: int, current_total: int | None, message: str) -> None:
                nonlocal downloaded, total
                downloaded = current
                if current_total is not None:
                    total = current_total
                emit("Downloading", message)

            downloaded, total = _download_vosk_archive(
                archive_url,
                partial,
                timeout=self.timeout,
                downloaded=downloaded,
                total=total,
                check_events=check_events,
                progress=report_transfer,
            )

            check_events()
            if total is not None and downloaded != total:
                raise OSError(
                    f"Vosk archive size mismatch: expected {total:,} bytes, received {downloaded:,} bytes"
                )
            if total is None:
                total = downloaded
            emit(
                "Validating",
                f"Verifying {model.checksum_algorithm.upper()} checksum from {model.source_label}",
            )
            digest = hashlib.new(model.checksum_algorithm)
            with partial.open("rb") as archive_stream:
                while True:
                    check_events()
                    block = archive_stream.read(_CHUNK_SIZE)
                    if not block:
                        break
                    digest.update(block)
            if digest.hexdigest().casefold() != model.checksum.casefold():
                partial.unlink(missing_ok=True)
                raise ValueError(
                    f"Vosk archive {model.checksum_algorithm.upper()} checksum does not match its trusted catalogue entry"
                )

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
                "revision": model.revision,
                "engine": "vosk",
                "runtime": "vosk",
                "files": files,
                "language_code": model.language,
                "language_name": model.language_name,
                "model_name": model.name,
                "model_type": model.model_type,
                "license": model.license,
                "source": model.source,
                "source_repo": model.source_repo,
                "source_file": model.source_file,
                "source_revision": model.source_revision,
                "catalogue_url": MODEL_LIST_URL if model.source == "official" else model.url,
                "archive_checksum": model.checksum,
                "archive_checksum_algorithm": model.checksum_algorithm,
                "archive_md5": model.md5 or None,
                "archive_sha256": model.sha256,
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
                    revision=model.revision,
                    files=files,
                    license_name=model.license,
                    runtime="vosk",
                    metadata={
                        "language_code": model.language,
                        "language_name": model.language_name,
                        "model_name": model.name,
                        "model_type": model.model_type,
                        "archive_checksum": model.checksum,
                        "archive_checksum_algorithm": model.checksum_algorithm,
                        "archive_md5": model.md5 or None,
                        "archive_sha256": model.sha256,
                        "source": model.source,
                        "source_repo": model.source_repo,
                        "license_name": model.license,
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
                    task_id, state=state.casefold(), revision=model.revision,
                    downloaded_bytes=downloaded, total_bytes=total, metadata=job_metadata,
                )
            raise
        except Exception as exc:
            message = str(exc)[:800]
            emit("Failed", message)
            if self.job_repository:
                self.job_repository.update(
                    task_id, state="failed", revision=model.revision,
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
