"""Segment-aware transcript editor with explicit preview and undo/redo."""

from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDoubleSpinBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QPushButton, QPlainTextEdit, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    QHeaderView,
)

from transcriber.editor.cleanup import apply_cleanup, preview_cleanup
from transcriber.editor.commands import CommandHistory
from transcriber.editor.document import TranscriptDocument
from transcriber.editor.search import replace as replace_text
from transcriber.editor.search import search as search_text
from transcriber.transcription.segments import TranscriptSegment
from transcriber.transcription.quality_report import build_quality_report
from transcriber.ui.widgets import Card, page_header, primary_button


class TranscriptEditorPage(QWidget):
    status_message = Signal(str)
    document_changed = Signal(object)
    seek_requested = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.document = TranscriptDocument()
        self.history = CommandHistory(self.document)
        self._busy_refresh = False
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)
        root.addWidget(page_header(
            "Transcript Editor",
            "Edit timestamped segments while preserving source timing and speaker metadata.",
        ))

        toolbar = Card()
        controls = QVBoxLayout(toolbar)
        row1 = QHBoxLayout()
        self.undo_button = QPushButton("Undo")
        self.undo_button.clicked.connect(self.undo)
        self.redo_button = QPushButton("Redo")
        self.redo_button.clicked.connect(self.redo)
        self.split_button = QPushButton("Split")
        self.split_button.clicked.connect(self.split_selected)
        self.merge_button = QPushButton("Merge selected")
        self.merge_button.clicked.connect(self.merge_selected)
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.delete_selected)
        for button in (self.undo_button, self.redo_button, self.split_button,
                       self.merge_button, self.delete_button):
            row1.addWidget(button)
        word_button = QPushButton("Edit word…")
        word_button.clicked.connect(self.edit_word)
        speaker_button = QPushButton("Set speaker…")
        speaker_button.clicked.connect(self.set_selected_speaker)
        bookmark_button = QPushButton("Bookmark")
        bookmark_button.clicked.connect(self.toggle_selected_bookmark)
        review_button = QPushButton("Mark reviewed")
        review_button.clicked.connect(self.mark_selected_reviewed)
        lock_button = QPushButton("Lock / unlock")
        lock_button.clicked.connect(self.toggle_selected_lock)
        note_button = QPushButton("Add note…")
        note_button.clicked.connect(self.add_selected_note)
        export_button = QPushButton("Export selected…")
        export_button.clicked.connect(self.export_selected)
        quality_button = QPushButton("Quality report")
        quality_button.clicked.connect(self.show_quality_report)
        compare_button = QPushButton("Compare original")
        compare_button.clicked.connect(self.compare_original)
        for button in (word_button, speaker_button, bookmark_button, review_button, lock_button, note_button,
                       export_button, quality_button, compare_button):
            row1.addWidget(button)
        row1.addStretch(1)
        controls.addLayout(row1)
        row2 = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Find text…")
        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText("Replace with…")
        self.regex_check = QCheckBox("Regex")
        find_button = QPushButton("Find")
        find_button.clicked.connect(self.find_matches)
        replace_button = QPushButton("Replace all")
        replace_button.clicked.connect(self.replace_all)
        row2.addWidget(self.search_input, 2)
        row2.addWidget(self.replace_input, 2)
        row2.addWidget(self.regex_check)
        row2.addWidget(find_button)
        row2.addWidget(replace_button)
        controls.addLayout(row2)
        row3 = QHBoxLayout()
        self.filler_check = QCheckBox("Suggest filler removal")
        self.filler_check.setChecked(False)
        self.repeat_check = QCheckBox("Repeated words")
        self.repeat_check.setChecked(True)
        self.punctuation_check = QCheckBox("Punctuation spacing")
        self.punctuation_check.setChecked(True)
        self.clean_button = QPushButton("Preview cleanup…")
        self.clean_button.clicked.connect(self.preview_text_cleanup)
        row3.addWidget(self.filler_check)
        row3.addWidget(self.repeat_check)
        row3.addWidget(self.punctuation_check)
        row3.addStretch(1)
        row3.addWidget(self.clean_button)
        controls.addLayout(row3)
        root.addWidget(toolbar)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "Start", "End", "Speaker", "Text", "Bookmark", "Reviewed", "Locked", "Words",
        ])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._table_item_changed)
        self.table.cellDoubleClicked.connect(self._seek_row)
        root.addWidget(self.table, 1)
        self.summary = QLabel("No transcript loaded")
        self.summary.setObjectName("Muted")
        root.addWidget(self.summary)

    def load_segments(self, segments, *, source_path=None, language=None, duration=0.0, original_text=None):
        cloned = deepcopy(list(segments or []))
        self.document = TranscriptDocument(
            segments=cloned, source_path=str(source_path) if source_path else None,
            language=language, duration=duration, original_text=original_text or "",
        )
        self.history = CommandHistory(self.document)
        self.refresh()

    def refresh(self):
        self._busy_refresh = True
        self.table.setRowCount(0)
        for segment in self.document.segments:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                f"{segment.start:.3f}", f"{segment.end:.3f}", segment.speaker or "",
                segment.text, "Yes" if segment.bookmarked else "No",
                "Yes" if segment.reviewed else "No", "Yes" if segment.locked else "No",
                str(len(segment.words or [])),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, segment.id)
                if segment.locked or col == 7:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if col in (4, 5, 6):
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, col, item)
        self._busy_refresh = False
        self.undo_button.setEnabled(self.history.can_undo)
        self.redo_button.setEnabled(self.history.can_redo)
        self.summary.setText(
            f"{len(self.document.segments)} segments · {len(self.document.text.split())} words · "
            f"revision {self.document.revision} · {sum(bool(s.is_edited) for s in self.document.segments)} edited"
        )

    def _selected_ids(self):
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        result = []
        for row in rows:
            item = self.table.item(row, 0)
            if item:
                result.append(item.data(Qt.UserRole))
        return result

    def _seek_row(self, row: int, _column: int):
        item = self.table.item(row, 0)
        if not item:
            return
        segment_id = item.data(Qt.UserRole)
        try:
            self.seek_requested.emit(float(self.document.get(segment_id).start))
        except (KeyError, TypeError, ValueError):
            return

    def _table_item_changed(self, item):
        if self._busy_refresh or item.column() not in (0, 1, 2, 3):
            return
        segment_id = item.data(Qt.UserRole)
        try:
            segment = self.document.get(segment_id)
            if item.column() == 0:
                changes = {"start": float(item.text())}
            elif item.column() == 1:
                changes = {"end": float(item.text())}
            elif item.column() == 2:
                changes = {"speaker": item.text().strip() or None}
            else:
                changes = {"text": item.text()}
            self.history.execute(self.document.update_segment, segment_id, **changes)
            self.refresh()
            self.document_changed.emit(self.document)
        except Exception as exc:
            QMessageBox.warning(self, "Invalid segment edit", str(exc))
            self.refresh()

    def _finish_change(self, description):
        self.refresh()
        self.document_changed.emit(self.document)
        self.status_message.emit(description)

    def undo(self):
        if self.history.undo():
            self._finish_change("Undo completed")

    def redo(self):
        if self.history.redo():
            self._finish_change("Redo completed")

    def split_selected(self):
        ids = self._selected_ids()
        if len(ids) != 1:
            QMessageBox.information(self, "Split segment", "Select exactly one segment.")
            return
        segment = self.document.get(ids[0])
        if segment.words:
            boundaries = [word.end for word in segment.words[:-1] if segment.start < word.end < segment.end]
            if not boundaries:
                QMessageBox.information(self, "Split segment", "No valid word-timestamp boundary is available.")
                return
            value, ok = QInputDialog.getDouble(self, "Split at time", "Split time (seconds):", boundaries[len(boundaries)//2], segment.start, segment.end, 3)
            if ok:
                self._run_edit(self.document.split_segment, segment.id, value, label="Segment split")
            return
        if len(segment.text) < 2:
            QMessageBox.information(self, "Split segment", "This segment needs at least two characters to split by text.")
            return
        index, ok = QInputDialog.getInt(self, "Split text", "Character index (1-based):", max(1, len(segment.text)//2), 1, len(segment.text)-1)
        if not ok:
            return
        value, ok = QInputDialog.getDouble(self, "Split timing", "Split time (seconds):", (segment.start + segment.end) / 2, segment.start + 0.001, segment.end - 0.001, 3)
        if ok:
            self._run_edit(self.document.split_segment_at_text, segment.id, index, value, label="Segment split")

    def merge_selected(self):
        ids = self._selected_ids()
        if len(ids) != 2:
            QMessageBox.information(self, "Merge segments", "Select exactly two segments.")
            return
        self._run_edit(self.document.merge_segments, ids[0], ids[1], label="Segments merged")

    def delete_selected(self):
        ids = self._selected_ids()
        if not ids:
            return
        if QMessageBox.question(self, "Delete segments", f"Delete {len(ids)} selected segment(s)?") != QMessageBox.Yes:
            return
        try:
            locked = [segment_id for segment_id in ids if self.document.get(segment_id).locked]
            if locked:
                raise PermissionError("Unlock selected segments before deleting them.")
            self.history.execute(self._delete_many, ids)
            self._finish_change(f"Deleted {len(ids)} segment(s)")
        except Exception as exc:
            QMessageBox.warning(self, "Delete failed", str(exc))

    def _run_edit(self, operation, *args, label="Updated"):
        try:
            self.history.execute(operation, *args)
            self._finish_change(label)
        except Exception as exc:
            QMessageBox.warning(self, "Edit failed", str(exc))

    def _delete_many(self, segment_ids):
        for segment_id in segment_ids:
            self.document.delete_segment(segment_id)

    def edit_word(self):
        ids = self._selected_ids()
        if len(ids) != 1:
            QMessageBox.information(self, "Edit word", "Select one segment with word timestamps.")
            return
        segment = self.document.get(ids[0])
        words = list(segment.words or [])
        if not words:
            QMessageBox.information(self, "Word timing unavailable", "This segment has no engine-provided word timestamps. Enable word timestamps for the next transcription.")
            return
        choices = [f"{index+1}. {word.start:.3f}–{word.end:.3f}  {word.text}" for index, word in enumerate(words)]
        chosen, ok = QInputDialog.getItem(self, "Select word", "Word:", choices, 0, False)
        if not ok:
            return
        index = choices.index(chosen)
        word = words[index]
        new_text, ok = QInputDialog.getText(self, "Edit word", "Text:", text=word.text)
        if not ok:
            return
        new_start, ok = QInputDialog.getDouble(self, "Edit word timing", "Start (seconds):", word.start, segment.start, segment.end, 3)
        if not ok:
            return
        new_end, ok = QInputDialog.getDouble(self, "Edit word timing", "End (seconds):", word.end, new_start, segment.end, 3)
        if ok:
            self._run_edit(self.document.update_word, segment.id, index, text=new_text, start=new_start, end=new_end,
                           label="Word updated")

    def set_selected_speaker(self):
        ids = self._selected_ids()
        if not ids:
            return
        current = self.document.get(ids[0]).speaker or ""
        speaker, ok = QInputDialog.getText(self, "Assign speaker", "Speaker name:", text=current)
        if ok:
            self._run_edit(self.document.set_speaker, ids, speaker.strip() or None, label="Speaker updated")

    def toggle_selected_bookmark(self):
        ids = self._selected_ids()
        if not ids:
            return
        bookmarked = not all(self.document.get(segment_id).bookmarked for segment_id in ids)
        self._run_edit(self._set_flag, ids, "bookmarked", bookmarked, label="Bookmark updated")

    def mark_selected_reviewed(self):
        ids = self._selected_ids()
        if ids:
            self._run_edit(self._set_flag, ids, "reviewed", True, label="Segments marked reviewed")

    def toggle_selected_lock(self):
        ids = self._selected_ids()
        if not ids:
            return
        locked = not all(self.document.get(segment_id).locked for segment_id in ids)
        # Lock flag is intentionally toggled outside update_segment, which protects locked content.
        self._run_edit(self._set_flag, ids, "locked", locked, label="Lock state updated")

    def _set_flag(self, ids, field, value):
        for segment_id in ids:
            segment = self.document.get(segment_id)
            setattr(segment, field, value)
            self.document.revision += 1

    def add_selected_note(self):
        ids = self._selected_ids()
        if len(ids) != 1:
            QMessageBox.information(self, "Segment note", "Select one segment.")
            return
        segment = self.document.get(ids[0])
        note, ok = QInputDialog.getMultiLineText(self, "Segment note", "Comment:", segment.comment or "")
        if ok:
            self._run_edit(self.document.update_segment, segment.id, comment=note, label="Comment saved")

    def export_selected(self):
        from pathlib import Path
        from PySide6.QtWidgets import QFileDialog
        from transcriber.transcription.exporters import export_transcript
        ids = set(self._selected_ids())
        if not ids:
            QMessageBox.information(self, "Export selected", "Select one or more segments first.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export selected segments", "selected-segments.srt", "SRT (*.srt);;VTT (*.vtt);;JSON (*.json);;Text (*.txt)")
        if not path:
            return
        target = Path(path)
        chosen = [item for item in self.document.segments if item.id in ids]
        try:
            export_transcript(target, format=target.suffix or ".srt", text=" ".join(item.text for item in chosen),
                              segments=chosen, include_timestamps=True, title=target.stem)
            self.status_message.emit(f"Exported {len(chosen)} segment(s)")
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))

    def find_matches(self):
        try:
            matches = search_text(self.document, self.search_input.text(), regex=self.regex_check.isChecked())
        except Exception as exc:
            QMessageBox.warning(self, "Search pattern error", str(exc))
            return
        self.table.clearSelection()
        rows = []
        for row in range(self.table.rowCount()):
            segment_id = self.table.item(row, 0).data(Qt.UserRole)
            if any(match.segment_id == segment_id for match in matches):
                self.table.selectRow(row)
                rows.append(row)
        if rows:
            self.table.scrollToItem(self.table.item(rows[0], 3))
        self.status_message.emit(f"Found {len(matches)} match(es)")

    def replace_all(self):
        query, replacement = self.search_input.text(), self.replace_input.text()
        try:
            matches = search_text(self.document, query, regex=self.regex_check.isChecked())
        except Exception as exc:
            QMessageBox.warning(self, "Search pattern error", str(exc))
            return
        if not matches:
            self.status_message.emit("No matches found")
            return
        if QMessageBox.question(self, "Replace text", f"Replace {len(matches)} occurrence(s)?") != QMessageBox.Yes:
            return
        try:
            self.history.execute(replace_text, self.document, query, replacement, regex=self.regex_check.isChecked())
            self._finish_change(f"Replaced {len(matches)} occurrence(s)")
        except Exception as exc:
            QMessageBox.warning(self, "Replace failed", str(exc))

    def preview_text_cleanup(self):
        actions = set()
        if self.filler_check.isChecked():
            actions.add("filler")
        if self.repeat_check.isChecked():
            actions.add("repeated")
        if self.punctuation_check.isChecked():
            actions.add("punctuation")
        if not actions:
            QMessageBox.information(self, "Cleanup", "Select at least one cleanup operation.")
            return
        changes = preview_cleanup(self.document, actions)
        if not changes:
            QMessageBox.information(self, "Cleanup preview", "No changes were suggested.")
            return
        lines = [f"{change.before}  →  {change.after}" for change in changes[:30]]
        if len(changes) > 30:
            lines.append(f"… and {len(changes) - 30} more")
        answer = QMessageBox.question(
            self, "Review cleanup preview",
            f"{len(changes)} segment(s) would change. Review suggestions below and apply?\n\n" + "\n".join(lines),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            try:
                self.history.execute(apply_cleanup, self.document, changes)
                self._finish_change(f"Applied cleanup to {len(changes)} segment(s)")
            except Exception as exc:
                QMessageBox.warning(self, "Cleanup failed", str(exc))

    def set_bookmark(self, segment_id: str, bookmarked: bool):
        self.history.execute(self.document.update_segment, segment_id, bookmarked=bookmarked)
        self._finish_change("Bookmark updated")

    def set_comment(self, segment_id: str, comment: str):
        self.history.execute(self.document.update_segment, segment_id, comment=comment)
        self._finish_change("Comment updated")

    def snapshot_segments(self):
        return deepcopy(self.document.segments)

    def show_quality_report(self):
        report = build_quality_report(
            segments=self.document.segments,
            language=self.document.language,
            duration=self.document.duration,
        )
        lines = [
            f"Language: {report.language or 'unknown'}",
            f"Audio duration: {report.audio_duration:.2f}s",
            f"Segments: {report.segment_count} · Words: {report.word_count} · Speakers: {report.speaker_count}",
            f"Silence gaps: {len(report.silence_regions)}",
            f"Word confidence: {report.mean_word_confidence:.3f}" if report.mean_word_confidence is not None else "Word confidence: not provided by the engine",
            f"Low-confidence words: {report.low_confidence_word_count}",
            f"Potential duplicate segments: {len(report.duplicate_segment_ids)}",
        ]
        lines.extend(f"{issue.severity.upper()} · {issue.message}" for issue in report.issues)
        QMessageBox.information(self, "Transcript quality report", "\n".join(lines))

    def compare_original(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Original vs edited transcript")
        dialog.resize(900, 520)
        layout = QVBoxLayout(dialog)
        columns = QHBoxLayout()
        original = QPlainTextEdit()
        original.setReadOnly(True)
        original.setPlainText(self.document.original_text)
        edited = QPlainTextEdit()
        edited.setReadOnly(True)
        edited.setPlainText(self.document.text)
        for label, widget in (("Original", original), ("Edited", edited)):
            panel = QVBoxLayout()
            panel.addWidget(QLabel(label))
            panel.addWidget(widget, 1)
            columns.addLayout(panel, 1)
        layout.addLayout(columns, 1)
        close = QPushButton("Close")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()
