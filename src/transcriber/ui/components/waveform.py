"""Lightweight cached-waveform timeline renderer (no per-paint audio decoding)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QWidget


class WaveformTimeline(QWidget):
    seek_requested = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.peaks: list[float] = []
        self.duration = 0.0
        self.position = 0.0
        self.markers: list[tuple[float, float, str]] = []
        self.setMinimumHeight(92)
        self.setMouseTracking(True)
        self.setToolTip("Click waveform to seek")

    def set_waveform(self, peaks, duration: float):
        self.peaks = [max(0.0, min(1.0, float(value))) for value in (peaks or [])]
        self.duration = max(0.0, float(duration))
        self.update()

    def set_position(self, seconds: float):
        self.position = max(0.0, min(self.duration, float(seconds))) if self.duration else 0.0
        self.update()

    def set_segments(self, segments):
        self.markers = [(max(0.0, item.start), max(item.start, item.end), item.id) for item in segments or []]
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        rect = self.rect().adjusted(10, 8, -10, -20)
        palette = self.palette()
        base = palette.color(self.backgroundRole())
        muted = palette.color(self.foregroundRole())
        accent = self.palette().highlight().color()
        painter.fillRect(self.rect(), base)
        mid = rect.center().y()
        if self.duration > 0 and self.markers:
            painter.setPen(QPen(accent, 1, Qt.DotLine))
            for start, end, _segment_id in self.markers:
                x1 = rect.left() + int(rect.width() * min(1.0, start / self.duration))
                x2 = rect.left() + int(rect.width() * min(1.0, end / self.duration))
                painter.drawLine(x1, rect.top(), x1, rect.bottom())
                painter.drawLine(x2, rect.top(), x2, rect.bottom())
        if self.peaks:
            painter.setPen(QPen(accent, 1))
            count = len(self.peaks)
            for x in range(max(1, rect.width())):
                index = min(count - 1, int(x / max(1, rect.width()) * count))
                amplitude = int(self.peaks[index] * rect.height() * 0.48)
                painter.drawLine(rect.left() + x, mid - amplitude, rect.left() + x, mid + amplitude)
        else:
            painter.setPen(QPen(muted, 1, Qt.DotLine))
            painter.drawLine(rect.left(), mid, rect.right(), mid)
        if self.duration:
            x = rect.left() + int(rect.width() * self.position / self.duration)
            painter.setPen(QPen(self.palette().highlight().color(), 2))
            painter.drawLine(x, rect.top() - 3, x, rect.bottom() + 4)
        painter.setPen(QPen(muted, 1))
        painter.drawText(rect.left(), self.height() - 3, self._clock(0))
        end_text = self._clock(self.duration)
        painter.drawText(rect.right() - painter.fontMetrics().horizontalAdvance(end_text), self.height() - 3, end_text)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.duration > 0:
            width = max(1, self.width() - 20)
            fraction = max(0.0, min(1.0, (event.position().x() - 10) / width))
            position = fraction * self.duration
            self.set_position(position)
            self.seek_requested.emit(position)
        super().mousePressEvent(event)

    @staticmethod
    def _clock(value):
        milliseconds = max(0, int(value * 1000))
        hours, remainder = divmod(milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds, _ms = divmod(remainder, 1000)
        return f"{hours:02}:{minutes:02}:{seconds:02}"
