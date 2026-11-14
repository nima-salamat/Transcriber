"""Snapshot-based undo/redo history for transcript editing operations."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass

from transcriber.editor.document import TranscriptDocument
from transcriber.transcription.segments import TranscriptSegment


@dataclass(slots=True)
class _Snapshot:
    segments: list[TranscriptSegment]
    revision: int
    text_override: str | None


class CommandHistory:
    def __init__(self, document: TranscriptDocument, limit: int = 100):
        self.document = document
        self.limit = max(1, int(limit))
        self._undo: list[_Snapshot] = []
        self._redo: list[_Snapshot] = []

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def execute(self, operation: Callable, *args, **kwargs):
        before = self._snapshot()
        result = operation(*args, **kwargs)
        self._undo.append(before)
        self._undo = self._undo[-self.limit:]
        self._redo.clear()
        return result

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._snapshot())
        self._restore(self._undo.pop())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._snapshot())
        self._restore(self._redo.pop())
        return True

    def snapshot(self) -> _Snapshot:
        return _Snapshot(
            deepcopy(self.document.segments),
            self.document.revision,
            self.document.text_override,
        )

    def record_snapshot(self, snapshot: _Snapshot) -> None:
        """Record a pre-edit state captured before a debounced external edit."""
        current = self.snapshot()
        if (
            snapshot.revision == current.revision
            and snapshot.text_override == current.text_override
            and snapshot.segments == current.segments
        ):
            return
        self._undo.append(snapshot)
        self._undo = self._undo[-self.limit:]
        self._redo.clear()

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()

    def _snapshot(self) -> _Snapshot:
        return self.snapshot()

    def _restore(self, snapshot: _Snapshot) -> None:
        self.document.segments = deepcopy(snapshot.segments)
        self.document.text_override = snapshot.text_override
        self.document.revision = snapshot.revision
        self.document.validate()
