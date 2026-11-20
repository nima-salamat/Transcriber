"""Safe Markdown rendering for untrusted assistant messages."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QImage, QTextDocument
from PySide6.QtWidgets import QFrame, QSizePolicy, QTextBrowser


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
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.anchorClicked.connect(self._open_clicked_link)

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
        self.setMarkdown(_safe_markdown(markdown))
        self.refresh_document_size()

    def refresh_document_size(self):
        width = max(220, self.viewport().width())
        self.document().setTextWidth(width)
        height = int(self.document().documentLayout().documentSize().height()) + 18
        height = max(34, min(1800, height))
        self.setMinimumHeight(height)
        self.setMaximumHeight(height)
