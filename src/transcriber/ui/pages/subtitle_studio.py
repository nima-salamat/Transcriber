"""Subtitle editor with import/export, editable timings and validation."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from transcriber.subtitles.formats import export_subtitles, parse_subtitles
from transcriber.subtitles.timing import apply_minimum_gap, shift_timestamps, validate_subtitles
from transcriber.transcription.segments import TranscriptSegment
from transcriber.ui.widgets import Card, page_header, primary_button


class SubtitleStudioPage(QWidget):
    status_message = Signal(str)
    segments_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.segments: list[TranscriptSegment] = []
        self._busy = False
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)
        root.addWidget(page_header(
            "Subtitles & timing", "Edit subtitle cue text and timing, validate readability, and export SRT, WebVTT, ASS or SSA. To correct recognized words in the transcript, use Transcript editor.",
        ))
        card = Card()
        toolbar = QVBoxLayout(card)
        row = QHBoxLayout()
        self.import_button = QPushButton("Import subtitles")
        self.import_button.clicked.connect(self.import_file)
        self.export_button = primary_button("Export…")
        self.export_button.clicked.connect(self.export_file)
        self.validate_button = QPushButton("Validate")
        self.validate_button.clicked.connect(self.validate)
        for button in (self.import_button, self.export_button, self.validate_button):
            row.addWidget(button)
        row.addStretch(1)
        toolbar.addLayout(row)

        cue_actions = QHBoxLayout()
        self.add_button = QPushButton("Add cue")
        self.add_button.clicked.connect(self.add_cue)
        self.delete_button = QPushButton("Delete selected")
        self.delete_button.clicked.connect(self.delete_selected)
        cue_actions.addWidget(self.add_button)
        cue_actions.addWidget(self.delete_button)
        cue_actions.addStretch(1)
        toolbar.addLayout(cue_actions)

        row2 = QHBoxLayout()
        self.shift_seconds = QDoubleSpinBox()
        self.shift_seconds.setRange(-3600, 3600)
        self.shift_seconds.setDecimals(3)
        self.shift_seconds.setSingleStep(0.1)
        shift_button = QPushButton("Shift all timings")
        shift_button.clicked.connect(self.shift_all)
        self.shift_button = shift_button
        self.minimum_gap = QDoubleSpinBox()
        self.minimum_gap.setRange(0, 5)
        self.minimum_gap.setDecimals(3)
        self.minimum_gap.setValue(0.08)
        gap_button = QPushButton("Apply minimum gap")
        gap_button.clicked.connect(self.apply_gap)
        self.gap_button = gap_button
        row2.addWidget(QLabel("Offset (s)"))
        row2.addWidget(self.shift_seconds)
        row2.addWidget(shift_button)
        row2.addSpacing(20)
        row2.addWidget(QLabel("Minimum gap (s)"))
        row2.addWidget(self.minimum_gap)
        row2.addWidget(gap_button)
        row2.addStretch(1)
        toolbar.addLayout(row2)
        root.addWidget(card)

        self.empty_state = QLabel("No subtitle cues yet. Import a subtitle file or add a cue to get started.")
        self.empty_state.setObjectName("PageEmptyState")
        self.empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state.setWordWrap(True)
        self.empty_state.setMinimumHeight(150)
        root.addWidget(self.empty_state)

        self.table = QTableWidget(0, 5)
        self.table.setMinimumHeight(180)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setHorizontalHeaderLabels(["Start (s)", "End (s)", "Speaker", "Text", "Duration"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._item_changed)
        self.table.itemSelectionChanged.connect(self._update_action_state)
        root.addWidget(self.table, 1)
        self.report = QLabel("Import a subtitle file or open a transcript from the Editor.")
        self.report.setWordWrap(True)
        self.report.setObjectName("Muted")
        root.addWidget(self.report)
        self._update_action_state()
        self.refresh()

    def load_segments(self, segments):
        self.segments = deepcopy(list(segments or []))
        self.refresh()

    def refresh(self):
        self._busy = True
        self.table.setRowCount(0)
        for segment in sorted(self.segments, key=lambda item: (item.start, item.end)):
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [f"{segment.start:.3f}", f"{segment.end:.3f}", segment.speaker or "", segment.text,
                      f"{max(0.0, segment.end-segment.start):.3f}"]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, segment.id)
                if col == 4:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, col, item)
        self._busy = False
        has_segments = bool(self.segments)
        self.table.setVisible(has_segments)
        self.empty_state.setVisible(not has_segments)
        self.report.setText(f"{len(self.segments)} cues · {sum(len(item.text.split()) for item in self.segments)} words")
        self._update_action_state()

    def _update_action_state(self):
        has_segments = bool(self.segments)
        self.export_button.setEnabled(has_segments)
        self.validate_button.setEnabled(has_segments)
        self.shift_button.setEnabled(has_segments)
        self.gap_button.setEnabled(has_segments)
        self.delete_button.setEnabled(bool(self.table.selectionModel().selectedRows()))

    def _item_changed(self, item):
        if self._busy or item.column() == 4:
            return
        segment_id = item.data(Qt.UserRole)
        target = next((segment for segment in self.segments if segment.id == segment_id), None)
        if target is None:
            return
        try:
            if item.column() == 0:
                target.start = max(0.0, float(item.text()))
            elif item.column() == 1:
                target.end = float(item.text())
            elif item.column() == 2:
                target.speaker = item.text().strip() or None
            elif item.column() == 3:
                target.text = item.text()
                target.words = []
            target.is_edited = True
            if target.end <= target.start:
                raise ValueError("End time must be greater than start time")
            self.refresh()
            self.segments_changed.emit(deepcopy(self.segments))
        except Exception as exc:
            QMessageBox.warning(self, "Invalid cue", str(exc))
            self.refresh()

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import subtitles", "", "Subtitle files (*.srt *.vtt *.ass *.ssa)")
        if not path:
            return
        try:
            self.load_segments(parse_subtitles(Path(path)))
            self.status_message.emit(f"Imported {Path(path).name}")
        except Exception as exc:
            QMessageBox.critical(self, "Subtitle import failed", str(exc))

    def export_file(self):
        if not self.segments:
            QMessageBox.information(self, "No subtitles", "Add or import subtitle cues first.")
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Export subtitles", "subtitles.srt",
            "SubRip (*.srt);;WebVTT (*.vtt);;Advanced SubStation Alpha (*.ass);;SubStation Alpha (*.ssa)",
        )
        if not path:
            return
        suffix = {"SubRip (*.srt)": ".srt", "WebVTT (*.vtt)": ".vtt",
                  "Advanced SubStation Alpha (*.ass)": ".ass", "SubStation Alpha (*.ssa)": ".ssa"}.get(selected_filter, ".srt")
        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(suffix)
        try:
            export_subtitles(target, self.segments)
            self.status_message.emit(f"Exported {target.name}")
        except Exception as exc:
            QMessageBox.critical(self, "Subtitle export failed", str(exc))

    def validate(self):
        issues = validate_subtitles(self.segments)
        if not issues:
            self.report.setText("Validation passed: no timing, overlap or reading-speed warnings.")
            return
        counts = {}
        for issue in issues:
            counts[issue.severity] = counts.get(issue.severity, 0) + 1
        lines = [f"{issue.severity.upper()} · {issue.code}: {issue.message}" for issue in issues[:25]]
        if len(issues) > 25:
            lines.append(f"… {len(issues) - 25} more issue(s)")
        self.report.setText(f"{len(issues)} issue(s) · {counts}\n" + "\n".join(lines))
        self.status_message.emit(f"Subtitle validation: {len(issues)} issue(s)")

    def shift_all(self):
        self.segments = shift_timestamps(self.segments, self.shift_seconds.value())
        self.refresh()
        self.segments_changed.emit(deepcopy(self.segments))
        self.status_message.emit("Subtitle timing shifted")

    def apply_gap(self):
        self.segments = apply_minimum_gap(self.segments, self.minimum_gap.value())
        self.refresh()
        self.segments_changed.emit(deepcopy(self.segments))
        self.status_message.emit("Minimum gap applied")

    def add_cue(self):
        last = max((item.end for item in self.segments), default=0.0)
        cue = TranscriptSegment(last, last + 2.0, "New subtitle")
        self.segments.append(cue)
        self.refresh()
        self.segments_changed.emit(deepcopy(self.segments))

    def delete_selected(self):
        rows = {index.row() for index in self.table.selectionModel().selectedRows()}
        ids = {self.table.item(row, 0).data(Qt.UserRole) for row in rows}
        if ids:
            self.segments = [item for item in self.segments if item.id not in ids]
            self.refresh()
            self.segments_changed.emit(deepcopy(self.segments))
