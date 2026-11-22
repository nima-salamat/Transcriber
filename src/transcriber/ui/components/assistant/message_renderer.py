"""Safe Markdown rendering for untrusted assistant messages."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QImage, QTextCursor, QTextDocument, QTextOption
from PySide6.QtWidgets import QFrame, QSizePolicy, QTextBrowser, QTextEdit


def _safe_markdown(source: str) -> str:
    """Remove image embedding and active HTML from untrusted model Markdown."""
    value = str(source or "")
    value = re.sub(
        r"!\[([^\]]*)\]\((?:https?|file|ftp):[^\)]*\)",
        lambda match: f"[Image omitted: {match.group(1) or 'embedded content'}]",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"<\s*(script|iframe|object|embed|style)\b[^>]*>.*?<\s*/\s*\1\s*>",
        "[embedded content omitted]",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return value


class SafeMarkdownBrowser(QTextBrowser):
    """A QTextBrowser which never fetches remote or local images from assistant output."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setSearchPaths([])
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        text_option = self.document().defaultTextOption()
        text_option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.document().setDefaultTextOption(text_option)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.anchorClicked.connect(self._open_clicked_link)
        self._stream_size_timer = QTimer(self)
        self._stream_size_timer.setSingleShot(True)
        self._stream_size_timer.setInterval(45)
        self._stream_size_timer.timeout.connect(self.refresh_document_size)

    def loadResource(self, resource_type, name):
        if resource_type == QTextDocument.ResourceType.ImageResource:
            return QImage()
        url = QUrl(name)
        if url.isValid() and url.scheme().casefold() not in {"qrc"}:
            return QImage()
        return super().loadResource(resource_type, name)

    def _open_clicked_link(self, url: QUrl):
        if url.scheme().casefold() in {"http", "https", "mailto"}:
            QDesktopServices.openUrl(url)

    def set_markdown(self, markdown: str):
        self._stream_size_timer.stop()
        self.setMarkdown(_safe_markdown(markdown))
        self.refresh_document_size()

    def append_plain_text(self, text: str):
        """Append streamed text directly to the existing document, without setMarkdown()."""
        value = str(text or "")
        if not value:
            return
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(value)
        self.setTextCursor(cursor)
        self._stream_size_timer.start()

    def refresh_document_size(self):
        width = max(1, self.viewport().width())
        self.document().setTextWidth(width)
        height = int(self.document().documentLayout().documentSize().height()) + 18
        height = max(34, min(1800, height))
        if self.minimumHeight() != height:
            self.setMinimumHeight(height)
        if self.maximumHeight() != height:
            self.setMaximumHeight(height)
