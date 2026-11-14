"""Validated JSON settings with atomic persistence."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AppSettings:
    theme: str = "dark"
    language: str = "system"
    default_engine: str = "faster-whisper"
    default_model: str = "Systran/faster-whisper-small"
    default_language: str = "auto"
    device: str = "auto"
    compute_type: str = "int8"
    cpu_threads: int = 0
    beam_size: int = 5
    vad_filter: bool = True
    word_timestamps: bool = False
    local_only: bool = True
    cloud_consent: bool = False
    model_directory: str | None = None
    recording_directory: str | None = None
    retain_source_audio: bool = True
    download_concurrency: int = 2
    geometry: str | None = None
    last_page: str = "home"

    def validate(self) -> None:
        self.theme = str(self.theme)
        self.language = str(self.language or "system")
        self.default_engine = str(self.default_engine)
        self.default_model = str(self.default_model)
        self.default_language = str(self.default_language or "auto")
        self.device = str(self.device)
        self.compute_type = str(self.compute_type)
        try:
            self.cpu_threads = int(self.cpu_threads)
        except (TypeError, ValueError):
            self.cpu_threads = 0
        try:
            self.beam_size = int(self.beam_size)
        except (TypeError, ValueError):
            self.beam_size = 5
        try:
            self.download_concurrency = int(self.download_concurrency)
        except (TypeError, ValueError):
            self.download_concurrency = 2
        def as_bool(value, default: bool) -> bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, int) and value in (0, 1):
                return bool(value)
            if isinstance(value, str):
                normalized = value.strip().casefold()
                if normalized in {"true", "1", "yes", "on"}:
                    return True
                if normalized in {"false", "0", "no", "off"}:
                    return False
            return default

        self.local_only = as_bool(self.local_only, True)
        self.cloud_consent = as_bool(self.cloud_consent, False)
        self.retain_source_audio = as_bool(self.retain_source_audio, True)
        self.word_timestamps = as_bool(self.word_timestamps, False)
        if self.theme not in {"dark", "light", "system"}:
            self.theme = "dark"
        if self.device not in {"auto", "cpu", "cuda"}:
            self.device = "auto"
        if self.compute_type not in {"default", "int8", "int8_float16", "float16", "float32"}:
            self.compute_type = "int8"
        self.cpu_threads = max(0, min(int(self.cpu_threads), 256))
        self.beam_size = max(1, min(int(self.beam_size), 20))
        self.download_concurrency = max(1, min(int(self.download_concurrency), 4))
        if self.default_engine not in {"faster-whisper", "google-cloud"}:
            self.default_engine = "faster-whisper"


class SettingsStore:
    """Thread-safe settings store; malformed files are preserved for recovery."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._settings = AppSettings()

    @property
    def settings(self) -> AppSettings:
        with self._lock:
            return AppSettings(**asdict(self._settings))

    def load(self) -> AppSettings:
        with self._lock:
            if self.path.exists():
                try:
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                    if not isinstance(raw, dict):
                        raise ValueError("Settings root must be a JSON object")
                    allowed = {item.name for item in fields(AppSettings)}
                    values = {key: value for key, value in raw.items() if key in allowed}
                    self._settings = AppSettings(**values)
                except (OSError, ValueError, TypeError):
                    # Keep the corrupt file intact so the user can inspect/recover it.
                    self._settings = AppSettings()
            try:
                self._settings.validate()
            except (TypeError, ValueError, OverflowError):
                self._settings = AppSettings()
                self._settings.validate()
            return self.settings

    def update(self, **changes: Any) -> AppSettings:
        with self._lock:
            current = asdict(self._settings)
            allowed = {item.name for item in fields(AppSettings)}
            current.update({k: v for k, v in changes.items() if k in allowed})
            candidate = AppSettings(**current)
            candidate.validate()
            self._atomic_write(asdict(candidate))
            self._settings = candidate
            return self.settings

    def save(self) -> None:
        with self._lock:
            self._settings.validate()
            self._atomic_write(asdict(self._settings))

    def _atomic_write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
