"""Validated JSON settings with atomic persistence."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AppSettings:
    theme: str = "dark"
    language: str = "system"
    default_engine: str = "faster-whisper"
    default_model: str = "Systran/faster-whisper-small"
    vosk_default_model: str = ""
    default_language: str = "auto"
    device: str = "auto"
    audio_input_device_id: str = ""
    audio_output_device_id: str = ""
    compute_type: str = "int8"
    cpu_threads: int = 0
    beam_size: int = 5
    vad_filter: bool = True
    word_timestamps: bool = False
    local_only: bool = True
    cloud_consent: bool = False
    google_cloud_project: str = ""
    google_cloud_location: str = "eu"
    google_cloud_model: str = "chirp_3"
    model_directory: str | None = None
    recording_directory: str | None = None
    retain_source_audio: bool = True
    download_concurrency: int = 2
    geometry: str | None = None
    window_state: str | None = None
    sidebar_collapsed: bool = False
    sidebar_visible: bool = True
    inspector_visible: bool = True
    timeline_visible: bool = True
    opencode_path: str | None = None
    opencode_project_directory: str | None = None
    opencode_session_id: str | None = None
    agent_permissions: list[str] = field(default_factory=lambda: [
        "read_only", "edit_content", "command_execution"
    ])
    # Incremented by validate() after one-time permission migrations. Keeping
    # it persisted allows users to intentionally disable shell access later.
    agent_permissions_version: int = 0
    wake_phrase: str = "transcriber"
    wake_model_directory: str | None = None
    wake_enabled: bool = False
    voice_auto_submit: bool = False
    voice_asr_model: str = ""
    chat_provider: str = "opencode"
    assistant_agent_mode: bool = True
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = ""
    ollama_keep_alive: str = "30m"
    voice_silence_seconds: float = 1.5
    voice_auto_sleep_seconds: int = 30
    max_active_models: int = 2
    ram_budget_mb: int = 8192
    vram_budget_mb: int = 4096
    last_page: str = "home"

    def validate(self) -> None:
        self.theme = str(self.theme)
        self.language = str(self.language or "system")
        self.default_engine = str(self.default_engine)
        self.default_model = str(self.default_model)
        self.vosk_default_model = str(self.vosk_default_model or "")
        self.default_language = str(self.default_language or "auto")
        self.device = str(self.device)
        self.audio_input_device_id = str(self.audio_input_device_id or "")[:512]
        self.audio_output_device_id = str(self.audio_output_device_id or "")[:512]
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

        self.sidebar_collapsed = as_bool(self.sidebar_collapsed, False)
        self.sidebar_visible = as_bool(self.sidebar_visible, True)
        self.inspector_visible = as_bool(self.inspector_visible, True)
        self.timeline_visible = as_bool(self.timeline_visible, True)
        self.wake_enabled = as_bool(self.wake_enabled, False)
        self.voice_auto_submit = as_bool(self.voice_auto_submit, False)
        self.assistant_agent_mode = as_bool(self.assistant_agent_mode, True)
        try:
            self.voice_auto_sleep_seconds = int(self.voice_auto_sleep_seconds)
        except (TypeError, ValueError):
            self.voice_auto_sleep_seconds = 30
        try:
            self.max_active_models = int(self.max_active_models)
            self.ram_budget_mb = int(self.ram_budget_mb)
            self.vram_budget_mb = int(self.vram_budget_mb)
        except (TypeError, ValueError):
            self.max_active_models, self.ram_budget_mb, self.vram_budget_mb = 2, 8192, 4096
        self.voice_auto_sleep_seconds = max(5, min(600, self.voice_auto_sleep_seconds))
        try:
            self.voice_silence_seconds = float(self.voice_silence_seconds)
        except (TypeError, ValueError):
            self.voice_silence_seconds = 1.5
        if not (0.5 <= self.voice_silence_seconds <= 8.0):
            self.voice_silence_seconds = 1.5
        self.max_active_models = max(1, min(10, self.max_active_models))
        self.ram_budget_mb = max(0, min(1_048_576, self.ram_budget_mb))
        self.vram_budget_mb = max(0, min(1_048_576, self.vram_budget_mb))
        self.wake_phrase = " ".join(str(self.wake_phrase or "transcriber").split())[:80]
        self.voice_asr_model = str(self.voice_asr_model or "").strip()[:256]
        self.chat_provider = str(self.chat_provider or "opencode").strip().casefold()
        if self.chat_provider not in {"opencode", "ollama"}:
            self.chat_provider = "opencode"
        self.ollama_base_url = str(self.ollama_base_url or "http://127.0.0.1:11434").strip().rstrip("/")[:512]
        if not self.ollama_base_url.startswith(("http://", "https://")):
            self.ollama_base_url = "http://127.0.0.1:11434"
        self.ollama_model = str(self.ollama_model or "").strip()[:256]
        self.ollama_keep_alive = str(self.ollama_keep_alive or "30m").strip()[:32]
        if not self.ollama_keep_alive:
            self.ollama_keep_alive = "30m"
        self.opencode_path = str(self.opencode_path) if self.opencode_path else None
        self.opencode_project_directory = str(self.opencode_project_directory) if self.opencode_project_directory else None
        self.opencode_session_id = str(self.opencode_session_id) if self.opencode_session_id else None
        valid_permissions = {
            "read_only", "edit_content", "modify_settings", "audio_capture",
            "file_export", "model_management", "destructive_actions", "desktop_control",
            "browser_control", "command_execution",
        }
        raw_permissions = (
            self.agent_permissions
            if isinstance(self.agent_permissions, list)
            else ["read_only", "edit_content", "command_execution"]
        )
        try:
            permission_version = max(0, int(self.agent_permissions_version))
        except (TypeError, ValueError):
            permission_version = 0
        if permission_version < 1:
            # Desktop and browser automation remain opt-in. PowerShell is
            # available by default only because every command has mandatory
            # per-invocation confirmation in MainWindow._approve_agent_action.
            # Older versions shipped an implicit five-permission default; a
            # previous development build also temporarily wrote read/edit only.
            legacy_implicit = {
                "read_only", "edit_content", "desktop_control",
                "browser_control", "command_execution",
            }
            if set(raw_permissions) in (
                legacy_implicit,
                {"read_only", "edit_content"},
            ):
                raw_permissions = ["read_only", "edit_content", "command_execution"]
            permission_version = 1
        self.agent_permissions = list(dict.fromkeys(
            str(value) for value in raw_permissions if str(value) in valid_permissions
        ))
        self.agent_permissions_version = permission_version
        self.wake_model_directory = str(self.wake_model_directory) if self.wake_model_directory else None
        self.local_only = as_bool(self.local_only, True)
        self.cloud_consent = as_bool(self.cloud_consent, False)
        self.google_cloud_project = str(self.google_cloud_project or "").strip()[:128]
        self.google_cloud_location = str(self.google_cloud_location or "eu").strip().casefold()[:64]
        self.google_cloud_model = str(self.google_cloud_model or "chirp_3").strip()
        if not self.google_cloud_location or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-" for ch in self.google_cloud_location):
            self.google_cloud_location = "eu"
        if self.google_cloud_model not in {"chirp_3", "long", "short"}:
            self.google_cloud_model = "chirp_3"
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
        if self.default_engine not in {"faster-whisper", "google-cloud", "vosk"}:
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
