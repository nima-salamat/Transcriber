"""QRunnable helpers with queued signals for safe worker-to-GUI communication."""

from __future__ import annotations

from threading import Lock
from uuid import uuid4

from PySide6.QtCore import QCoreApplication, QObject, QRunnable, Qt, Signal, Slot


class WorkerSignals(QObject):
    progress = Signal(object)
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class _WorkerSignalReaper(QObject):
    """Release worker signal objects on their owning (GUI) thread."""

    release = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.release.connect(self._release, Qt.QueuedConnection)

    @Slot(str)
    def _release(self, token):
        with _active_lock:
            signals = _active_signals.pop(token, None)
        if signals is not None:
            signals.deleteLater()


_active_lock = Lock()
_active_signals = {}
_reaper = None


def _get_reaper():
    global _reaper
    if _reaper is None:
        app = QCoreApplication.instance()
        if app is None:
            return None
        _reaper = _WorkerSignalReaper(app)
    return _reaper


class FunctionWorker(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()
        token = uuid4().hex
        reaper = _get_reaper()
        if reaper is not None:
            # QThreadPool may delete the QRunnable immediately after run().
            # Keep its parentless signal QObject alive until queued GUI slots drain.
            with _active_lock:
                _active_signals[token] = self.signals
            self.signals.finished.connect(
                lambda worker_token=token, owner=reaper: owner.release.emit(worker_token)
            )
        self.setAutoDelete(True)

    @Slot()
    def run(self):
        try:
            result = self.function(self.signals.progress.emit)
            self.signals.result.emit(result)
        except Exception as exc:
            self.signals.error.emit(str(exc))
        finally:
            self.signals.finished.emit()
