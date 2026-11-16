"""Compact editor and importer for the Agent's Markdown prompt library."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from transcriber.assistant.prompt_library import PromptLibrary


class PromptLibraryDialog(QDialog):
    """Edit, import, copy or insert task-specific prompt files."""

    use_prompt = Signal(str)

    def __init__(self, library: PromptLibrary, parent: QWidget | None = None):
        super().__init__(parent)
        self.library = library
        self._loaded_filename: str | None = None
        self._dirty = False
        self.setWindowTitle("Agent prompt library")
        self.setMinimumSize(760, 520)

        root = QVBoxLayout(self)
        intro = QLabel(
            "The Agent uses one coordinator prompt and loads specialist Markdown files "
            "only when a task needs them. Edit the instructions here or import your own."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        body = QHBoxLayout()
        self.prompt_list = QListWidget()
        self.prompt_list.setMinimumWidth(205)
        self.prompt_list.itemSelectionChanged.connect(self._load_selected)
        body.addWidget(self.prompt_list)

        editor_column = QVBoxLayout()
        self.filename_label = QLabel("Select a prompt")
        self.filename_label.setObjectName("Muted")
        editor_column.addWidget(self.filename_label)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("Prompt instructions in Markdown…")
        self.editor.setTabChangesFocus(False)
        self.editor.textChanged.connect(self._mark_dirty)
        editor_column.addWidget(self.editor, 1)
        body.addLayout(editor_column, 1)
        root.addLayout(body, 1)

        actions = QHBoxLayout()
        self.import_clipboard_button = QPushButton("Import clipboard…")
        self.import_clipboard_button.clicked.connect(self.import_from_clipboard)
        self.import_file_button = QPushButton("Import file…")
        self.import_file_button.clicked.connect(self.import_from_file)
        self.open_folder_button = QPushButton("Open prompt folder")
        self.open_folder_button.clicked.connect(self.open_folder)
        self.copy_agent_button = QPushButton("Copy coordinator prompt")
        self.copy_agent_button.clicked.connect(self.copy_coordinator)
        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.save_current)
        self.use_button = QPushButton("Use selected prompt")
        self.use_button.setObjectName("Primary")
        self.use_button.clicked.connect(self.use_current)
        actions.addWidget(self.import_clipboard_button)
        actions.addWidget(self.import_file_button)
        actions.addWidget(self.open_folder_button)
        actions.addStretch(1)
        actions.addWidget(self.copy_agent_button)
        actions.addWidget(self.save_button)
        actions.addWidget(self.use_button)
        root.addLayout(actions)

        self.refresh()

    def _mark_dirty(self):
        self._dirty = True
        if self._loaded_filename:
            self.filename_label.setText(f"Editing · {self._loaded_filename}")

    def _confirm_discard(self) -> bool:
        if not self._dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved prompt changes",
            "Save your changes before switching to another prompt?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save_current()
        if answer == QMessageBox.StandardButton.Discard:
            self._dirty = False
            return True
        return False

    def refresh(self, select: str | None = None):
        if not self._confirm_discard():
            return
        self._loaded_filename = None
        self.prompt_list.blockSignals(True)
        self.prompt_list.clear()
        selected_row = 0
        for index, (filename, title) in enumerate(self.library.list_prompts()):
            self.prompt_list.addItem(title)
            self.prompt_list.item(index).setData(Qt.ItemDataRole.UserRole, filename)
            if filename == select:
                selected_row = index
        if self.prompt_list.count():
            self.prompt_list.setCurrentRow(selected_row)
        self.prompt_list.blockSignals(False)
        self._load_selected()

    def _selected_filename(self) -> str | None:
        item = self.prompt_list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _load_selected(self):
        filename = self._selected_filename()
        if filename == self._loaded_filename:
            return
        if not self._confirm_discard():
            self.prompt_list.blockSignals(True)
            for index in range(self.prompt_list.count()):
                if self.prompt_list.item(index).data(Qt.ItemDataRole.UserRole) == self._loaded_filename:
                    self.prompt_list.setCurrentRow(index)
                    break
            self.prompt_list.blockSignals(False)
            return
        if not filename:
            self._loaded_filename = None
            self.filename_label.setText("No prompt selected")
            self.editor.clear()
            self._dirty = False
            return
        try:
            content = self.library.read(filename)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Cannot read prompt", str(exc))
            return
        self.editor.blockSignals(True)
        self.editor.setPlainText(content)
        self.editor.blockSignals(False)
        self._loaded_filename = filename
        self._dirty = False
        self.filename_label.setText(filename)

    def save_current(self) -> bool:
        filename = self._loaded_filename or self._selected_filename()
        if not filename:
            return False
        try:
            self.library.save(filename, self.editor.toPlainText())
            self._loaded_filename = filename
            self._dirty = False
            self.filename_label.setText(f"Saved · {filename}")
            return True
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Cannot save prompt", str(exc))
            return False

    def import_from_clipboard(self):
        content = QApplication.clipboard().text()
        if not content.strip():
            QMessageBox.information(
                self, "Clipboard is empty", "Copy a prompt first, then import it."
            )
            return
        name, accepted = QInputDialog.getText(
            self, "Import prompt", "Name for this prompt:", text="Custom prompt"
        )
        if not accepted or not name.strip():
            return
        if not self._confirm_discard():
            return
        try:
            filename = self.library.import_prompt(name, content)
            self.refresh(filename)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Cannot import prompt", str(exc))

    def import_from_file(self):
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import Markdown prompt",
            str(self.library.directory),
            "Markdown files (*.md);;Text files (*.txt);;All files (*)",
        )
        if not path:
            return
        if not self._confirm_discard():
            return
        source = Path(path)
        try:
            filename = self.library.import_prompt(
                source.stem, source.read_text(encoding="utf-8")
            )
            self.refresh(filename)
        except (OSError, ValueError, UnicodeError) as exc:
            QMessageBox.warning(self, "Cannot import prompt", str(exc))

    def copy_coordinator(self):
        QApplication.clipboard().setText(self.library.bootstrap_prompt())
        self.filename_label.setText("Coordinator prompt copied to clipboard")

    def open_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.library.directory)))

    def use_current(self):
        if not self.save_current() and self._dirty:
            return
        content = self.editor.toPlainText().strip()
        if content:
            self.use_prompt.emit(content)
            self.accept()

    def closeEvent(self, event):
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()
