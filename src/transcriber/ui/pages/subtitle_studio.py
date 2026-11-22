"""Subtitle editor with import/export, editable timings and validation."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
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
        self.setObjectName("SubtitleStudioPage")
        self.segments: list[TranscriptSegment] = []
        self._busy = False

        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 10, 12)
        root.setSpacing(12)

        scroll = QScrollArea(self)
        scroll.setObjectName("SubtitleStudioScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("SubtitleStudioContent")
        page = QVBoxLayout(content)
        page.setContentsMargins(0, 0, 8, 2)
        page.setSpacing(13)

        page.addWidget(page_header(
            "Subtitles & timing",
            "Shape each cue, fine-tune its timing, check readability and export SRT, WebVTT, ASS or SSA.",
        ))

        metrics = QHBoxLayout()
        metrics.setSpacing(10)

        def metric_card(caption: str, initial: str):
            card = Card()
            card.setObjectName("SubtitleMetricCard")
            metric_layout = QVBoxLayout(card)
            metric_layout.setContentsMargins(16, 11, 16, 11)
            metric_layout.setSpacing(3)
            caption_label = QLabel(caption)
            caption_label.setObjectName("SubtitleMetricCaption")
            value_label = QLabel(initial)
            value_label.setObjectName("SubtitleMetricValue")
            metric_layout.addWidget(caption_label)
            metric_layout.addWidget(value_label)
            metrics.addWidget(card, 1)
            return value_label

        self.cues_value = metric_card("SUBTITLE CUES", "0")
        self.words_value = metric_card("WORDS", "0")
        self.duration_value = metric_card("LAST CUE", "—")
        page.addLayout(metrics)

        actions_card = Card()
        actions_card.setObjectName("SubtitleToolbar")
        actions_layout = QHBoxLayout(actions_card)
        actions_layout.setContentsMargins(10, 9, 10, 9)
        actions_layout.setSpacing(7)
        self.import_button = QPushButton("Import")
        self.import_button.setObjectName("SubtitleToolButton")
        self.import_button.clicked.connect(self.import_file)
        self.add_button = QPushButton("Add cue")
        self.add_button.setObjectName("SubtitleToolButton")
        self.add_button.clicked.connect(self.add_cue)
        self.delete_button = QPushButton("Delete selected")
        self.delete_button.setObjectName("SubtitleDeleteButton")
        self.delete_button.clicked.connect(self.delete_selected)
        self.validate_button = QPushButton("Validate track")
        self.validate_button.setObjectName("SubtitleToolButton")
        self.validate_button.clicked.connect(self.validate)
        self.export_button = primary_button("Export subtitles…")
        self.export_button.setObjectName("SubtitleExportButton")
        self.export_button.clicked.connect(self.export_file)
        actions_layout.addWidget(self.import_button)
        actions_layout.addWidget(self.add_button)
        actions_layout.addWidget(self.delete_button)
        actions_layout.addStretch(1)
        actions_layout.addWidget(self.validate_button)
        actions_layout.addWidget(self.export_button)
        page.addWidget(actions_card)

        timing_card = Card()
        timing_layout = QVBoxLayout(timing_card)
        timing_layout.setContentsMargins(16, 13, 16, 14)
        timing_layout.setSpacing(10)
        timing_heading = QHBoxLayout()
        timing_title = QLabel("Timing adjustments")
        timing_title.setObjectName("TranscriptionSectionTitle")
        timing_hint = QLabel("Apply a consistent offset or spacing across the full subtitle track")
        timing_hint.setObjectName("TranscriptionSectionHint")
        timing_heading.addWidget(timing_title)
        timing_heading.addSpacing(8)
        timing_heading.addWidget(timing_hint)
        timing_heading.addStretch(1)
        timing_layout.addLayout(timing_heading)

        timing_grid = QGridLayout()
        timing_grid.setHorizontalSpacing(14)
        timing_grid.setVerticalSpacing(4)

        shift_panel = QFrame()
        shift_panel.setObjectName("SubtitleTimingTool")
        shift_layout = QVBoxLayout(shift_panel)
        shift_layout.setContentsMargins(13, 10, 13, 10)
        shift_layout.setSpacing(7)
        shift_label = QLabel("Shift all timestamps")
        shift_label.setObjectName("SubtitleTimingTitle")
        shift_description = QLabel("Move every cue earlier or later")
        shift_description.setObjectName("SubtitleTimingDescription")
        shift_layout.addWidget(shift_label)
        shift_layout.addWidget(shift_description)
        shift_controls = QHBoxLayout()
        shift_controls.setSpacing(8)
        self.shift_seconds = QDoubleSpinBox()
        self.shift_seconds.setRange(-3600, 3600)
        self.shift_seconds.setDecimals(3)
        self.shift_seconds.setSingleStep(0.1)
        self.shift_seconds.setMinimumWidth(105)
        self.shift_seconds.setSuffix(" s")
        self.shift_button = QPushButton("Apply offset")
        self.shift_button.setObjectName("SubtitleTimingApply")
        self.shift_button.clicked.connect(self.shift_all)
        shift_controls.addWidget(self.shift_seconds, 1)
        shift_controls.addWidget(self.shift_button)
        shift_layout.addLayout(shift_controls)

        gap_panel = QFrame()
        gap_panel.setObjectName("SubtitleTimingTool")
        gap_layout = QVBoxLayout(gap_panel)
        gap_layout.setContentsMargins(13, 10, 13, 10)
        gap_layout.setSpacing(7)
        gap_label = QLabel("Minimum cue gap")
        gap_label.setObjectName("SubtitleTimingTitle")
        gap_description = QLabel("Prevent cues from running into one another")
        gap_description.setObjectName("SubtitleTimingDescription")
        gap_layout.addWidget(gap_label)
        gap_layout.addWidget(gap_description)
        gap_controls = QHBoxLayout()
        gap_controls.setSpacing(8)
        self.minimum_gap = QDoubleSpinBox()
        self.minimum_gap.setRange(0, 5)
        self.minimum_gap.setDecimals(3)
        self.minimum_gap.setValue(0.08)
        self.minimum_gap.setMinimumWidth(105)
        self.minimum_gap.setSuffix(" s")
        self.gap_button = QPushButton("Apply gap")
        self.gap_button.setObjectName("SubtitleTimingApply")
        self.gap_button.clicked.connect(self.apply_gap)
        gap_controls.addWidget(self.minimum_gap, 1)
        gap_controls.addWidget(self.gap_button)
        gap_layout.addLayout(gap_controls)

        timing_grid.addWidget(shift_panel, 0, 0)
        timing_grid.addWidget(gap_panel, 1, 0)
        timing_grid.setColumnStretch(0, 1)
        timing_layout.addLayout(timing_grid)
        right_workspace = QVBoxLayout()
        right_workspace.setSpacing(12)
        right_workspace.addWidget(timing_card)

        table_card = Card()
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(16, 14, 16, 16)
        table_layout.setSpacing(10)
        table_heading = QHBoxLayout()
        table_title = QLabel("Subtitle cues")
        table_title.setObjectName("TranscriptionSectionTitle")
        table_hint = QLabel("Select a row to remove it; double-click a cell to edit its value")
        table_hint.setObjectName("TranscriptionSectionHint")
        table_heading.addWidget(table_title)
        table_heading.addSpacing(8)
        table_heading.addWidget(table_hint)
        table_heading.addStretch(1)
        table_layout.addLayout(table_heading)

        self.empty_state = QLabel(
            "No subtitle cues yet\nImport an SRT or WebVTT file, or add a cue to start building your subtitle track."
        )
        self.empty_state.setObjectName("SubtitleEmptyState")
        self.empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state.setWordWrap(True)
        self.empty_state.setMinimumHeight(116)
        table_layout.addWidget(self.empty_state)

        self.table = QTableWidget(0, 5)
        self.table.setObjectName("SubtitleCueTable")
        self.table.setMinimumHeight(290)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(True)
        self.table.setShowGrid(False)
        self.table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.setHorizontalHeaderLabels(
            ["Start (s)", "End (s)", "Speaker", "Subtitle text", "Duration"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 104)
        self.table.setColumnWidth(1, 104)
        self.table.setColumnWidth(2, 128)
        self.table.setColumnWidth(4, 94)
        self.table.itemChanged.connect(self._item_changed)
        self.table.itemSelectionChanged.connect(self._update_action_state)
        table_layout.addWidget(self.table, 1)
        workspace = QHBoxLayout()
        workspace.setSpacing(14)
        workspace.addWidget(table_card, 3)
        workspace.addLayout(right_workspace, 2)

        report_card = Card()
        report_card.setObjectName("SubtitleReportCard")
        report_layout = QHBoxLayout(report_card)
        report_layout.setContentsMargins(14, 11, 14, 11)
        report_layout.setSpacing(10)
        self.report_mark = QLabel("•")
        self.report_mark.setObjectName("SubtitleReportMark")
        self.report_mark.setFixedSize(26, 26)
        self.report_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.report = QLabel(
            "Ready for review · Import a subtitle track or open a transcript from the Editor."
        )
        self.report.setObjectName("SubtitleValidationReport")
        self.report.setWordWrap(True)
        report_layout.addWidget(self.report_mark, 0, Qt.AlignmentFlag.AlignTop)
        report_layout.addWidget(self.report, 1)
        right_workspace.addWidget(report_card)
        right_workspace.addStretch(1)
        page.addLayout(workspace, 1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)
        self._update_action_state()
        self.refresh()

    def load_segments(self, segments):
        self.segments = deepcopy(list(segments or []))
        self.refresh()

    def refresh(self):
        self._busy = True
        self.table.setRowCount(0)
        ordered_segments = sorted(self.segments, key=lambda item: (item.start, item.end))
        for segment in ordered_segments:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                f"{segment.start:.3f}",
                f"{segment.end:.3f}",
                segment.speaker or "",
                segment.text,
                f"{max(0.0, segment.end-segment.start):.3f}",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, segment.id)
                if col == 4:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, col, item)
        self._busy = False

        has_segments = bool(self.segments)
        word_total = sum(len(item.text.split()) for item in self.segments)
        last_end = max((item.end for item in self.segments), default=0.0)
        minutes, seconds = divmod(max(0, int(last_end)), 60)
        self.cues_value.setText(f"{len(self.segments):,}")
        self.words_value.setText(f"{word_total:,}")
        self.duration_value.setText(
            f"{minutes:02d}:{seconds:02d}" if has_segments else "—"
        )
        self.table.setVisible(has_segments)
        self.empty_state.setVisible(not has_segments)
        self.report.setProperty("state", "")
        self.report.style().unpolish(self.report)
        self.report.style().polish(self.report)
        self.report_mark.setProperty("state", "")
        self.report_mark.style().unpolish(self.report_mark)
        self.report_mark.style().polish(self.report_mark)
        self.report_mark.setText("•")
        self.report.setText(
            f"{len(self.segments)} cues · {word_total} words · "
            f"last cue ends at {minutes:02d}:{seconds:02d}"
            if has_segments else
            "Ready for subtitles · Import a track or add a cue to begin."
        )
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
            self.report.setProperty("state", "success")
            self.report.style().unpolish(self.report)
            self.report.style().polish(self.report)
            self.report_mark.setProperty("state", "success")
            self.report_mark.style().unpolish(self.report_mark)
            self.report_mark.style().polish(self.report_mark)
            self.report_mark.setText("✓")
            self.report.setText(
                "Validation passed · No timing, overlap or reading-speed warnings were found."
            )
            self.status_message.emit("Subtitle validation passed")
            return

        counts = {}
        for issue in issues:
            counts[issue.severity] = counts.get(issue.severity, 0) + 1
        summary = ", ".join(
            f"{count} {severity.lower()}" for severity, count in sorted(counts.items())
        )
        lines = [
            f"{issue.severity.upper()} · {issue.code}: {issue.message}"
            for issue in issues[:12]
        ]
        if len(issues) > 12:
            lines.append(f"… and {len(issues) - 12} more issue(s)")
        self.report.setProperty("state", "warning")
        self.report.style().unpolish(self.report)
        self.report.style().polish(self.report)
        self.report_mark.setProperty("state", "warning")
        self.report_mark.style().unpolish(self.report_mark)
        self.report_mark.style().polish(self.report_mark)
        self.report_mark.setText("!")
        self.report.setText(
            f"{len(issues)} validation issue(s) · {summary}\n" + "\n".join(lines)
        )
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
