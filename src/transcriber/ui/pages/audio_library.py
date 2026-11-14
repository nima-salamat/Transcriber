"""Persistent local audio library with independent recording history."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from transcriber.ui.widgets import Card, page_header, primary_button
from transcriber.ui.workers import FunctionWorker


def _format_size(value: int | None) -> str:
    if value is None:
        return "Unknown size"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return "Unknown size"


def _format_duration(value: float | None) -> str:
    seconds = max(0, int(float(value or 0)))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"


class AudioLibraryPage(QWidget):
    open_audio = Signal(str)
    status_message = Signal(str)

    def __init__(self, paths, history, thread_pool, recording_history=None, parent=None):
        super().__init__(parent)
        self.paths = paths
        self.history = history
        self.thread_pool = thread_pool
        self.recording_history = recording_history
        self._generation = 0
        self._worker: FunctionWorker | None = None
        self._recordings: dict[str, dict] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        layout.addWidget(page_header(
            "Audio library",
            "Saved recordings are indexed independently from transcripts. Removing a transcript does not remove its source audio.",
        ))
        card = Card()
        inner = QVBoxLayout(card)
        inner.setContentsMargins(12, 12, 12, 12)
        self.items = QListWidget()
        self.items.setAlternatingRowColors(True)
        self.items.itemDoubleClicked.connect(self.open_selected_item)
        self.items.setContextMenuPolicy(Qt.CustomContextMenu)
        self.items.customContextMenuRequested.connect(self._show_context_menu)
        inner.addWidget(self.items, 1)
        buttons = QVBoxLayout()
        refresh = QPushButton("Refresh library")
        refresh.clicked.connect(self.refresh)
        open_file = primary_button("Open / transcribe selected")
        open_file.clicked.connect(self.open_selected)
        folder = QPushButton("Show default recordings folder")
        folder.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.paths.recordings)))
        )
        buttons.addWidget(refresh)
        buttons.addWidget(open_file)
        buttons.addWidget(folder)
        inner.addLayout(buttons)
        layout.addWidget(card, 1)
        self.refresh()

    def refresh(self):
        self._generation += 1
        generation = self._generation
        paths = self.paths
        history = self.history
        recording_history = self.recording_history

        def load(_emit):
            source_paths = {
                str(Path(row["source_path"]).expanduser().resolve())
                for row in history.list(limit=1000)
                if row.get("source_path")
            }
            result = []
            registered_paths = set()
            if recording_history is not None:
                for record in recording_history.list(limit=2000):
                    file_path = Path(record["file_path"]).expanduser().resolve()
                    key = str(file_path)
                    registered_paths.add(key)
                    result.append((key, file_path.is_file(), "recording", record))
            for source in source_paths:
                if source not in registered_paths:
                    result.append((source, Path(source).is_file(), "source", None))

            # Keep discovering files from older versions that predate the
            # persistent recording ledger. Their locations are never moved.
            legacy_roots = {Path(paths.recordings)}
            legacy_root = Path(paths.data) / "recordings"
            if legacy_root != Path(paths.recordings):
                legacy_roots.add(legacy_root)
            for directory in legacy_roots:
                if not directory.is_dir():
                    continue
                for media_path in sorted(directory.glob("*"), key=lambda item: item.name.casefold()):
                    if not media_path.is_file():
                        continue
                    key = str(media_path.resolve())
                    if key not in registered_paths and key not in source_paths:
                        result.append((key, True, "legacy", None))
            return sorted(result, key=lambda row: (
                row[3]["recorded_at"] if row[3] else "",
                Path(row[0]).name.casefold(),
            ), reverse=True)

        worker = FunctionWorker(load)
        worker.signals.result.connect(lambda rows, current=generation: self._apply_rows(current, rows))
        worker.signals.error.connect(
            lambda message: self.status_message.emit(f"Could not scan audio library: {message}")
        )
        self._worker = worker
        self.thread_pool.start(worker)

    def _apply_rows(self, generation: int, rows):
        if generation != self._generation:
            return
        self.items.clear()
        self._recordings.clear()
        for source, exists, kind, record in rows:
            path = Path(source)
            if record:
                self._recordings[str(record["id"])] = record
                state = "available" if exists else "missing file"
                label = (
                    f"Recording  ·  {_format_duration(record.get('duration'))}  ·  "
                    f"{str(record.get('format') or 'unknown').upper()}  ·  "
                    f"{_format_size(record.get('file_size'))}  ·  {state}"
                )
            elif kind == "source":
                label = "Transcript source  ·  available" if exists else "Transcript source  ·  missing"
            else:
                label = "Legacy recording  ·  available" if exists else "Legacy recording  ·  missing"
            item = QListWidgetItem(f"{path.name}  ·  {label}")
            item.setData(Qt.UserRole, str(path))
            item.setData(Qt.UserRole + 1, kind)
            item.setData(Qt.UserRole + 2, str(record["id"]) if record else "")
            item.setToolTip(str(path))
            self.items.addItem(item)

    def open_selected_item(self, item):
        source = item.data(Qt.UserRole)
        if source:
            self.open_audio.emit(str(source))

    def open_selected(self):
        item = self.items.currentItem()
        if item:
            self.open_selected_item(item)

    def _show_context_menu(self, position):
        item = self.items.itemAt(position)
        if item is None:
            return
        self.items.setCurrentItem(item)
        source = Path(str(item.data(Qt.UserRole)))
        kind = str(item.data(Qt.UserRole + 1) or "")
        recording_id = str(item.data(Qt.UserRole + 2) or "")
        menu = QMenu(self)
        menu.addAction("Open / transcribe", lambda: self.open_audio.emit(str(source)))
        menu.addAction("Reveal in folder", lambda: self._reveal(source))
        menu.addAction("Copy path", lambda: QApplication.clipboard().setText(str(source)))
        menu.addAction("Details", lambda: self._show_details(source, recording_id))
        if kind == "recording" and recording_id and self.recording_history is not None:
            menu.addSeparator()
            menu.addAction("Rename recording…", lambda: self._rename(recording_id))
            menu.addAction("Delete recording…", lambda: self._delete(recording_id))
        menu.exec(self.items.viewport().mapToGlobal(position))

    @staticmethod
    def _reveal(path: Path):
        folder = path.parent if path.is_file() or not path.exists() else path
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _show_details(self, path: Path, recording_id: str):
        record = self._recordings.get(recording_id) if recording_id else None
        lines = [
            f"File: {path.name}",
            f"Path: {path}",
            f"Status: {'Available' if path.is_file() else 'Missing'}",
        ]
        if record:
            lines.extend([
                f"Recorded: {record.get('recorded_at') or 'Unknown'}",
                f"Duration: {_format_duration(record.get('duration'))}",
                f"Size: {_format_size(record.get('file_size'))}",
                f"Format: {str(record.get('format') or 'unknown').upper()}",
                f"Input device: {record.get('device_name') or 'Unknown'}",
            ])
            if record.get("device_id"):
                lines.append(f"Device ID: {record['device_id']}")
        QMessageBox.information(self, "Audio details", "\n".join(lines))

    def _rename(self, recording_id: str):
        record = self._recordings.get(recording_id)
        if not record:
            return
        new_name, accepted = QInputDialog.getText(
            self, "Rename recording", "Filename:", text=str(record["filename"])
        )
        if not accepted or not new_name.strip():
            return
        try:
            new_path = self.recording_history.rename(recording_id, new_name)
        except Exception as exc:
            QMessageBox.warning(self, "Could not rename recording", str(exc))
            return
        self.status_message.emit(f"Recording renamed to {new_path.name}")
        self.refresh()

    def _delete(self, recording_id: str):
        record = self._recordings.get(recording_id)
        if not record:
            return
        path = Path(record["file_path"])
        try:
            references = self.recording_history.references_to(path)
        except Exception as exc:
            QMessageBox.warning(self, "Could not inspect transcript references", str(exc))
            return
        warning = ""
        if references:
            names = "\n".join(f"• {item['title']}" for item in references[:5])
            remaining = f"\n…and {len(references) - 5} more" if len(references) > 5 else ""
            warning = (
                f"\n\n{len(references)} transcript(s) reference this audio. "
                "Those transcripts will remain, but their source audio will become unavailable:\n"
                f"{names}{remaining}"
            )
        answer = QMessageBox.question(
            self,
            "Delete recording and audio file?",
            f"Delete {path.name} from the recording library and remove the audio file?{warning}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.recording_history.delete(recording_id, delete_file=True)
        except Exception as exc:
            QMessageBox.warning(self, "Could not delete recording", str(exc))
            return
        self.status_message.emit(f"Recording deleted: {path.name}")
        self.refresh()
