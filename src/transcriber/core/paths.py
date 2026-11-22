"""Cross-platform application directories.

The TRANSCRIBER_HOME override is intentionally useful for tests and portable
installations. Normal installs use the OS conventions supplied by platformdirs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import (
    user_cache_dir,
    user_config_dir,
    user_data_dir,
    user_log_dir,
    user_music_dir,
)

APP_NAME = "transcriber"


@dataclass(frozen=True, slots=True)
class AppPaths:
    config: Path
    data: Path
    cache: Path
    logs: Path
    models: Path
    recordings: Path
    database: Path
    settings: Path
    registry: Path

    @classmethod
    def discover(cls, app_name: str = APP_NAME) -> AppPaths:
        override = os.environ.get("TRANSCRIBER_HOME")
        if override:
            root = Path(override).expanduser().resolve()
            config, data, cache, logs = (
                root / "config", root / "data", root / "cache", root / "logs"
            )
            recordings = root / "recordings"
        else:
            config = Path(user_config_dir(app_name, appauthor=False))
            data = Path(user_data_dir(app_name, appauthor=False))
            cache = Path(user_cache_dir(app_name, appauthor=False))
            logs = Path(user_log_dir(app_name, appauthor=False))
            music_directory = user_music_dir()
            recordings = Path(music_directory or user_data_dir(app_name, appauthor=False)) / "Transcriber Recordings"
        return cls(
            config=config,
            data=data,
            cache=cache,
            logs=logs,
            models=data / "models",
            recordings=recordings,
            database=data / "transcripts.sqlite3",
            settings=config / "settings.json",
            registry=config / "models.json",
        )

    def ensure(self) -> AppPaths:
        for directory in (
            self.config, self.data, self.cache, self.logs, self.models,
            self.recordings, self.models / ".staging",
        ):
            directory.mkdir(parents=True, exist_ok=True)
        return self
