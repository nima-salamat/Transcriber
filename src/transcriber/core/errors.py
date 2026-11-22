"""Domain exceptions with actionable messages."""


class TranscriberError(Exception):
    """Base class for expected application failures."""


class EngineUnavailableError(TranscriberError):
    """Raised when an optional recognition engine is not installed."""


class ModelCompatibilityError(TranscriberError):
    """Raised when a model repository is not a valid Faster-Whisper model."""


class DownloadCancelled(TranscriberError):
    """Raised when a model download is cancelled by the user."""


class ActiveModelError(TranscriberError):
    """Raised when a caller tries to remove the model currently in use."""
