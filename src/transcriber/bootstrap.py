"""Application composition root."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from transcriber import __version__
from transcriber.core.config import SettingsStore
from transcriber.core.logging_config import configure_logging
from transcriber.core.paths import AppPaths
from transcriber.models.downloader import ModelDownloader
from transcriber.models.hub_client import HuggingFaceHubClient
from transcriber.models.manager import ModelManager
from transcriber.models.registry import ModelRegistry
from transcriber.storage.database import Database
from transcriber.storage.history import HistoryRepository


def build_services():
    paths = AppPaths.discover().ensure()
    settings = SettingsStore(paths.settings)
    config = settings.load()
    if config.model_directory:
        paths = replace(paths, models=Path(config.model_directory).expanduser().resolve())
    if config.recording_directory:
        paths = replace(paths, recordings=Path(config.recording_directory).expanduser().resolve())
    paths.ensure()
    logger = configure_logging(paths.logs, os.environ.get("TRANSCRIBER_LOG_LEVEL", "INFO"))
    database = Database(paths.database)
    history = HistoryRepository(database)
    hub_token = os.environ.get("HF_TOKEN")
    hub = HuggingFaceHubClient(token=hub_token)
    registry = ModelRegistry(paths.models, paths.registry)
    downloader = ModelDownloader(
        hub, registry, paths.cache / "huggingface",
        max_concurrent=config.download_concurrency,
    )
    model_manager = ModelManager(registry, hub, downloader)
    logger.info("Transcriber %s initialized; data directory: %s", __version__, paths.data)
    return {
        "paths": paths, "settings": settings, "database": database,
        "history": history, "model_manager": model_manager, "logger": logger,
    }
