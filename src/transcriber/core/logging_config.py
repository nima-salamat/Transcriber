"""Rotating application logging with conservative secret redaction."""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

_SECRET = re.compile(
    r"(?i)(?P<hf>\bhf_[A-Za-z0-9]{16,}\b)"
    r"|(?P<key>\b(?:access_token|token)\s*[=:]\s*|authorization\s*[:=]\s*bearer\s+)"
    r"(?P<value>[^\s,;\"']+)"
)


def _redact_secret(match: re.Match[str]) -> str:
    if match.group("hf"):
        return "[REDACTED]"
    return f"{match.group('key')}[REDACTED]"


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record)
        return _SECRET.sub(_redact_secret, rendered)


def configure_logging(log_dir: Path, level: str = "INFO") -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("transcriber")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False
    if not logger.handlers:
        handler = RotatingFileHandler(
            log_dir / "transcriber.log", maxBytes=2_000_000, backupCount=4, encoding="utf-8"
        )
        handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
        console = logging.StreamHandler()
        console.setFormatter(RedactingFormatter("%(levelname)s: %(message)s"))
        logger.addHandler(console)
    return logger
