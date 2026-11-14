"""Local recordings library with an embedded waveform player."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt, QUrl, Signal, QSize
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from transcriber.audio.player import AudioPlayer
from transcriber.audio.waveform import build_waveform
from transcriber.ui.components.waveform import WaveformTimeline
from transcriber.ui.design.icon_registry import IconRegistry
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
        self._waveform_generation = 0
        self._worker: FunctionWorker | None = None
        self._waveform_worker: FunctionWorker | None = None
        self._recordings: dict[str, dict] = {}
        self._rows: list[tuple[str, bool, str, dict | None]] = []
        self._selected_path: Path | None = None
        self._selected_recording_id = ""
        self.icons = IconRegistry()
        self.player = AudioPlayer(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        heading = QHBoxLayout()
        heading.addWidget(page_header(
            "Recordings",
            "Your local audio takes, ready to listen to, review or send to transcription.",
        ), 1)
        self.count_label = QLabel("0 recordings")
        self.count_label.setObjectName("Muted")
        heading.addWidget(self.count_label, 0, Qt.AlignBottom)
        layout.addLayout(heading)

        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search recordings by name or folder…")
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(220)
        self.search_timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda: self.search_timer.start())
        search_row.addWidget(self.search, 1)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setIcon(self.icons.icon("activity", size=17))
        self.refresh_button.clicked.connect(self.refresh)
        search_row.addWidget(self.refresh_button)
        folder = QPushButton("Open folder")
        folder.setIcon(self.icons.icon("projects", size=17))
        folder.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.paths.recordings)))
        )
        search_row.addWidget(folder)
        layout.addLayout(search_row)

        columns = QHBoxLayout()
        columns.setSpacing(14)

        list_card = Card()
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(12, 12, 12, 12)
        list_heading = QLabel("ALL RECORDINGS")
        list_heading.setStyleSheet("font-size: 10px; font-weight: 800; letter-spacing: 1px;")
        list_layout.addWidget(list_heading)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setMinimumWidth(310)
        self.scroll.setMaximumWidth(460)
        self.list_body = QWidget()
        self.list_layout = QVBoxLayout(self.list_body)
        self.list_layout.setContentsMargins(0, 0, 4, 0)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(self.list_body)
        list_layout.addWidget(self.scroll, 1)
        columns.addWidget(list_card, 1)

        self.player_card = Card()
        player_layout = QVBoxLayout(self.player_card)
        player_layout.setContentsMargins(20, 18, 20, 18)
        player_layout.setSpacing(13)

        player_top = QHBoxLayout()
        player_top.addWidget(QLabel("NOW PLAYING"))
        player_top.addStretch(1)
        self.player_status = QLabel("Choose a recording")
        self.player_status.setObjectName("Muted")
        player_top.addWidget(self.player_status)
        player_layout.addLayout(player_top)

        self.player_title = QLabel("Select a recording")
        self.player_title.setObjectName("PageTitle")
        self.player_title.setWordWrap(True)
        self.player_title.setStyleSheet("font-size: 21px; font-weight: 720;")
        player_layout.addWidget(self.player_title)

        self.player_metadata = QLabel("Your selected recording will appear here.")
        self.player_metadata.setObjectName("Muted")
        self.player_metadata.setWordWrap(True)
        player_layout.addWidget(self.player_metadata)

        self.player_waveform = WaveformTimeline()
        self.player_waveform.setMinimumHeight(170)
        self.player_waveform.set_interactive(True)
        self.player_waveform.seek_requested.connect(
            lambda seconds: self.player.seek(int(seconds * 1000))
        )
        player_layout.addWidget(self.player_waveform, 1)

        time_row = QHBoxLayout()
        self.position_label = QLabel("00:00")
        self.position_label.setStyleSheet("font-size: 24px; font-weight: 700;")
        self.position_label.setObjectName("RecordingTimer")
        time_row.addWidget(self.position_label)
        time_row.addStretch(1)
        self.duration_label = QLabel("/ 00:00")
        self.duration_label.setObjectName("Muted")
        time_row.addWidget(self.duration_label)
        player_layout.addLayout(time_row)

        transport = QHBoxLayout()
        transport.addStretch(1)
        self.skip_back_button = QPushButton()
        self.skip_back_button.setIcon(self.icons.icon("skip_back", size=18))
        self.skip_back_button.setIconSize(QSize(18, 18))
        self.skip_back_button.setToolTip("Back 15 seconds")
        self.skip_back_button.setFixedSize(42, 42)
        self.skip_back_button.clicked.connect(lambda: self._skip(-15))
        transport.addWidget(self.skip_back_button)
        self.play_button = QPushButton()
        self.play_button.setIcon(self.icons.icon("play", size=20))
        self.play_button.setIconSize(QSize(20, 20))
        self.play_button.setMinimumSize(56, 48)
        self.play_button.setObjectName("Primary")
        self.play_button.setToolTip("Play recording")
        self.play_button.clicked.connect(self.player.play_pause)
        transport.addWidget(self.play_button)
        self.skip_forward_button = QPushButton()
        self.skip_forward_button.setIcon(self.icons.icon("skip_forward", size=18))
        self.skip_forward_button.setIconSize(QSize(18, 18))
        self.skip_forward_button.setToolTip("Forward 15 seconds")
        self.skip_forward_button.setFixedSize(42, 42)
        self.skip_forward_button.clicked.connect(lambda: self._skip(15))
        transport.addWidget(self.skip_forward_button)
        transport.addStretch(1)
        player_layout.addLayout(transport)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setObjectName("Divider")
        player_layout.addWidget(divider)

        actions = QHBoxLayout()
        self.transcribe_button = primary_button("Open in transcriber")
        self.transcribe_button.clicked.connect(self.open_selected)
        actions.addWidget(self.transcribe_button, 1)
        self.reveal_button = QPushButton("Show in folder")
        self.reveal_button.clicked.connect(self._reveal_selected)
        actions.addWidget(self.reveal_button)
        player_layout.addLayout(actions)

        secondary = QHBoxLayout()
        self.rename_button = QPushButton("Rename")
        self.rename_button.clicked.connect(self._rename_selected)
        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("Danger")
        self.delete_button.clicked.connect(self._delete_selected)
        secondary.addStretch(1)
        secondary.addWidget(self.rename_button)
        secondary.addWidget(self.delete_button)
        player_layout.addLayout(secondary)
        columns.addWidget(self.player_card, 2)
        layout.addLayout(columns, 1)

        self._set_player_enabled(False)
        self.player.position_changed.connect(self._on_position_changed)
        self.player.duration_changed.connect(self._on_duration_changed)
        self.player.playback_changed.connect(self._on_playback_changed)
        self.player.status_changed.connect(self.player_status.setText)
        self.player.error_occurred.connect(
            lambda message: self.status_message.emit(f"Playback error: {message}")
        )
        self.refresh()

    def refresh(self):
        self._generation += 1
        generation = self._generation
        paths = self.paths
        history = self.history
        recording_history = self.recording_history
        query = self.search.text().strip().casefold()

        def load(_emit):
            source_paths = {
                str(Path(row["source_path"]).expanduser().resolve())
                for row in history.list(limit=1000)
                if row.get("source_path")
            }
            result = []
            registered_paths = set()
            if recording_history is not None:
                for record in recording_history.list(query, limit=2000):
                    file_path = Path(record["file_path"]).expanduser().resolve()
                    key = str(file_path)
                    registered_paths.add(key)
                    result.append((key, file_path.is_file(), "recording", record))
            for source in source_paths:
                if source not in registered_paths:
                    path = Path(source)
                    if not query or query in path.name.casefold() or query in str(path).casefold():
                        result.append((source, path.is_file(), "source", None))

            legacy_roots = {Path(paths.recordings), Path(paths.data) / "recordings"}
            for directory in legacy_roots:
                if not directory.is_dir():
                    continue
                for media_path in directory.glob("*"):
                    if not media_path.is_file():
                        continue
                    key = str(media_path.resolve())
                    if key in registered_paths or key in source_paths:
                        continue
                    if query and query not in media_path.name.casefold() and query not in key.casefold():
                        continue
                    result.append((key, True, "legacy", None))
            return sorted(result, key=lambda row: (
                row[3]["recorded_at"] if row[3] else "",
                Path(row[0]).name.casefold(),
            ), reverse=True)

        worker = FunctionWorker(load)
        worker.signals.result.connect(lambda rows, current=generation: self._apply_rows(current, rows))
        worker.signals.error.connect(
            lambda message: self.status_message.emit(f"Could not scan recordings: {message}")
        )
        self._worker = worker
        self.thread_pool.start(worker)

    def _apply_rows(self, generation: int, rows):
        if generation != self._generation:
            return
        self._rows = rows
        self._recordings.clear()
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        available = sum(1 for _path, exists, _kind, _record in rows if exists)
        self.count_label.setText(f"{available} available · {len(rows)} total")
        for source, exists, kind, record in rows:
            path = Path(source)
            if record:
                self._recordings[str(record["id"])] = record
            self._add_recording_card(path, exists, kind, record)
        self.list_layout.addStretch(1)
        if self._selected_path:
            selected = str(self._selected_path)
            if not any(row[0] == selected and row[1] for row in rows):
                self.player.clear_source()
                self._selected_path = None
                self._selected_recording_id = ""
                self._set_player_enabled(False)
                self.player_title.setText("Select a recording")
                self.player_metadata.setText("Your selected recording will appear here.")

    def _add_recording_card(self, path: Path, exists: bool, kind: str, record: dict | None):
        card = QFrame()
        card.setObjectName("RecordingListCard")
        card.setFrameShape(QFrame.StyledPanel)
        row = QHBoxLayout(card)
        row.setContentsMargins(10, 9, 10, 9)
        row.setSpacing(10)

        play = QPushButton()
        play.setIcon(self.icons.icon("play", size=16))
        play.setIconSize(QSize(16, 16))
        play.setFixedSize(34, 34)
        play.setEnabled(exists)
        play.setToolTip("Play this recording")
        play.clicked.connect(lambda _checked=False, p=path, r=record: self._select_recording(p, r, True))
        row.addWidget(play)

        detail = QVBoxLayout()
        detail.setSpacing(3)
        title = QPushButton(path.stem)
        title.setFlat(True)
        title.setCursor(Qt.PointingHandCursor)
        title.setStyleSheet("text-align: left; border: none; padding: 0; font-weight: 700;")
        title.setEnabled(exists)
        title.clicked.connect(lambda _checked=False, p=path, r=record: self._select_recording(p, r, False))
        detail.addWidget(title)
        if record:
            meta = (
                f"{_format_duration(record.get('duration'))}  ·  "
                f"{_format_size(record.get('file_size'))}  ·  "
                f"{str(record.get('recorded_at') or '')[:10]}"
            )
        else:
            meta = "Audio file" if kind == "source" else "Older recording"
        if not exists:
            meta += "  ·  File missing"
        info = QLabel(meta)
        info.setObjectName("Muted")
        info.setWordWrap(True)
        detail.addWidget(info)
        row.addLayout(detail, 1)
        card.setStyleSheet(
            "QFrame#RecordingListCard { border: 1px solid palette(mid); border-radius: 10px; "
            "background: palette(base); }"
            "QFrame#RecordingListCard:hover { background: palette(alternate-base); }"
        )
        card.setContextMenuPolicy(Qt.CustomContextMenu)
        card.customContextMenuRequested.connect(
            lambda position, c=card, p=path, k=kind, r=record: self._show_context_menu(c, position, p, k, r)
        )
        self.list_layout.addWidget(card)

    def _select_recording(self, path: Path, record: dict | None, auto_play: bool = False):
        path = Path(path).expanduser().resolve()
        if not path.is_file():
            QMessageBox.warning(self, "Recording unavailable", f"The audio file is missing:
{path}")
            return
        self._selected_path = path
        self._selected_recording_id = str(record["id"]) if record else ""
        self.player.set_source(str(path))
        self.player_title.setText(path.stem)
        if record:
            metadata = [
                str(record.get("recorded_at") or "")[:16].replace("T", " "),
                _format_duration(record.get("duration")),
                _format_size(record.get("file_size")),
                str(record.get("format") or path.suffix.lstrip(".")).upper(),
            ]
            if record.get("device_name"):
                metadata.append(str(record["device_name"]))
            self.player_metadata.setText("  ·  ".join(value for value in metadata if value))
        else:
            self.player_metadata.setText(str(path.parent))
        self.player_waveform.set_waveform([], float(record.get("duration") or 0) if record else 0.0)
        self.player_waveform.set_position(0.0)
        self.position_label.setText("00:00")
        self.duration_label.setText(f"/ {_format_duration(record.get('duration') if record else 0)}")
        self._set_player_enabled(True)

        self._waveform_generation += 1
        generation = self._waveform_generation
        worker = FunctionWorker(
            lambda _emit: build_waveform(path, self.paths.cache / "waveforms")
        )
        worker.signals.result.connect(
            lambda peaks, current=generation, source=path: self._apply_waveform(current, source, peaks)
        )
        worker.signals.error.connect(
            lambda message, current=generation: self._waveform_failed(current, message)
        )
        self._waveform_worker = worker
        self.thread_pool.start(worker)
        if auto_play:
            self.player.play_pause()

    def _apply_waveform(self, generation: int, path: Path, peaks):
        if generation != self._waveform_generation or self._selected_path != path:
            return
        duration = self.player.player.duration() / 1000.0
        self.player_waveform.set_waveform(peaks, duration)

    def _waveform_failed(self, generation: int, message: str):
        if generation == self._waveform_generation:
            self.player_status.setText("Waveform unavailable")
            self.status_message.emit(f"Could not build waveform: {message}")

    def _set_player_enabled(self, enabled: bool):
        for widget in (
            self.play_button, self.skip_back_button, self.skip_forward_button,
            self.transcribe_button, self.reveal_button, self.rename_button, self.delete_button,
        ):
            widget.setEnabled(enabled)

    def _on_position_changed(self, value: int):
        seconds = max(0, int(value)) / 1000.0
        self.player_waveform.set_position(seconds)
        self.position_label.setText(_format_duration(seconds))

    def _on_duration_changed(self, value: int):
        seconds = max(0, int(value)) / 1000.0
        self.player_waveform.set_duration(seconds)
        self.duration_label.setText(f"/ {_format_duration(seconds)}")

    def _on_playback_changed(self, playing: bool):
        self.play_button.setIcon(self.icons.icon("pause" if playing else "play", size=20))
        self.play_button.setToolTip("Pause playback" if playing else "Play recording")

    def _skip(self, seconds: int):
        current = self.player.player.position()
        duration = self.player.player.duration()
        self.player.seek(max(0, min(duration, current + seconds * 1000)))

    def open_selected(self):
        if self._selected_path and self._selected_path.is_file():
            self.open_audio.emit(str(self._selected_path))

    def _reveal_selected(self):
        if self._selected_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._selected_path.parent)))

    def _show_context_menu(self, card, position, path: Path, kind: str, record: dict | None):
        menu = QMenu(self)
        menu.addAction("Play", lambda: self._select_recording(path, record, True))
        menu.addAction("Open in transcriber", lambda: self.open_audio.emit(str(path)))
        menu.addAction("Reveal in folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent))))
        menu.addAction("Copy path", lambda: QApplication.clipboard().setText(str(path)))
        if kind == "recording" and record and self.recording_history is not None:
            menu.addSeparator()
            menu.addAction("Rename…", lambda: self._rename_recording(str(record["id"])))
            menu.addAction("Delete…", lambda: self._delete_recording(str(record["id"])))
        menu.exec(card.mapToGlobal(position))

    def _rename_selected(self):
        if self._selected_recording_id:
            self._rename_recording(self._selected_recording_id)

    def _rename_recording(self, recording_id: str):
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
        if self._selected_recording_id == recording_id:
            self.player.set_source(str(new_path))
            self._selected_path = new_path
            self.player_title.setText(new_path.stem)
        self.status_message.emit(f"Recording renamed to {new_path.name}")
        self.refresh()

    def _delete_selected(self):
        if self._selected_recording_id:
            self._delete_recording(self._selected_recording_id)
        elif self._selected_path:
            QMessageBox.information(
                self, "Managed source audio",
                "This file is referenced by a transcript but is not a managed recording. "
                "Open its folder to manage it without breaking transcript references.",
            )

    def _delete_recording(self, recording_id: str):
        record = self._recordings.get(recording_id)
        if not record or self.recording_history is None:
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
            self.player.stop()
            self.recording_history.delete(recording_id, delete_file=True)
        except Exception as exc:
            QMessageBox.warning(self, "Could not delete recording", str(exc))
            return
        if self._selected_recording_id == recording_id:
            self.player.clear_source()
            self._selected_path = None
            self._selected_recording_id = ""
            self._set_player_enabled(False)
            self.player_title.setText("Select a recording")
            self.player_metadata.setText("Your selected recording will appear here.")
            self.player_waveform.set_waveform([], 0.0)
        self.status_message.emit(f"Recording deleted: {path.name}")
        self.refresh()

    def shutdown(self):
        self.player.shutdown()
