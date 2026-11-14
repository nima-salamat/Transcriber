"""Interactive, cached-peak waveform timeline used by recording and playback views."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class WaveformTimeline(QWidget):
    seek_requested = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.peaks: list[float] = []
        self.duration = 0.0
        self.position = 0.0
        self.markers: list[tuple[float, float, str]] = []
        self._interactive = False
        self.setMinimumHeight(112)
        self.setMouseTracking(True)
        self.setToolTip("Click or drag the waveform to choose a position")

    def set_waveform(self, peaks, duration: float):
        self.peaks = [max(0.0, min(1.0, float(value))) for value in (peaks or [])]
        self.duration = max(0.0, float(duration))
        self.position = min(self.position, self.duration) if self.duration else 0.0
        self.update()

    def set_duration(self, duration: float):
        self.duration = max(0.0, float(duration))
        self.position = min(self.position, self.duration) if self.duration else 0.0
        self.update()

    def set_interactive(self, enabled: bool):
        self._interactive = bool(enabled)
        self.setCursor(Qt.PointingHandCursor if self._interactive else Qt.ArrowCursor)

    def set_position(self, seconds: float):
        self.position = max(0.0, min(self.duration, float(seconds))) if self.duration else 0.0
        self.update()

    def set_segments(self, segments):
        self.markers = [
            (max(0.0, item.start), max(item.start, item.end), item.id)
            for item in segments or []
        ]
        self.update()

    def _position_from_x(self, x: float) -> float:
        left, width = 16.0, max(1.0, self.width() - 32.0)
        return max(0.0, min(1.0, (x - left) / width)) * self.duration

    def _seek_at(self, x: float):
        if self.duration <= 0:
            return
        position = self._position_from_x(x)
        self.set_position(position)
        self.seek_requested.emit(position)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        palette = self.palette()
        muted = palette.color(palette.ColorRole.PlaceholderText)
        accent = palette.color(palette.ColorRole.Highlight)
        text_color = palette.color(palette.ColorRole.Text)
        rect = self.rect().adjusted(16, 12, -16, -28)
        if rect.width() <= 0 or rect.height() <= 0:
            painter.end()
            return

        background = palette.color(palette.ColorRole.AlternateBase)
        background.setAlpha(90)
        painter.setPen(Qt.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 9, 9)
        center_y = rect.center().y()
        bar_width = 3
        if self.peaks:
            count = len(self.peaks)
            step = max(2.0, rect.width() / count)
            played_fraction = self.position / self.duration if self.duration else 1.0
            for index, peak in enumerate(self.peaks):
                x = rect.left() + (index + 0.5) * rect.width() / count
                height = max(2.0, peak * (rect.height() - 12))
                color = QColor(accent if index / count <= played_fraction else muted)
                color.setAlpha(220 if index / count <= played_fraction else 145)
                painter.setPen(Qt.NoPen)
                painter.setBrush(color)
                painter.drawRoundedRect(
                    int(x - min(bar_width, step) / 2),
                    int(center_y - height / 2),
                    max(2, int(min(bar_width, step))),
                    max(2, int(height)),
                    1.5,
                    1.5,
                )
        else:
            painter.setPen(QPen(muted, 1, Qt.DotLine))
            painter.drawLine(rect.left() + 8, center_y, rect.right() - 8, center_y)

        if self.duration > 0 and self.markers:
            painter.setPen(QPen(accent, 1, Qt.DotLine))
            for start, end, _segment_id in self.markers:
                x1 = rect.left() + int(rect.width() * min(1.0, start / self.duration))
                x2 = rect.left() + int(rect.width() * min(1.0, end / self.duration))
                painter.drawLine(x1, rect.top(), x1, rect.bottom())
                painter.drawLine(x2, rect.top(), x2, rect.bottom())

        if self.duration > 0:
            x = rect.left() + int(rect.width() * self.position / self.duration)
            painter.setPen(QPen(accent, 2))
            painter.drawLine(x, rect.top() - 3, x, rect.bottom() + 4)
            painter.setBrush(accent)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(x - 4, rect.top() - 7, 8, 8)

        painter.setPen(text_color)
        font = painter.font()
        font.setPointSize(max(8, font.pointSize() - 1))
        painter.setFont(font)
        painter.drawText(rect.left(), self.height() - 6, self._clock(0))
        end_text = self._clock(self.duration)
        painter.drawText(
            rect.right() - painter.fontMetrics().horizontalAdvance(end_text),
            self.height() - 6,
            end_text,
        )
        painter.end()

    def mousePressEvent(self, event):
        if self._interactive and event.button() == Qt.MouseButton.LeftButton:
            self._seek_at(event.position().x())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._interactive and event.buttons() & Qt.MouseButton.LeftButton:
            self._seek_at(event.position().x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    @staticmethod
    def _clock(value):
        milliseconds = max(0, int(value * 1000))
        hours, remainder = divmod(milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds, _ms = divmod(remainder, 1000)
        return f"{hours:02}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"
