import os
import sys
import threading
from io import BytesIO

from PySide6 import QtWidgets, QtCore, QtGui, QtPrintSupport
from PySide6.QtCore import Qt, Slot, QUrl
from PySide6.QtGui import QTextCharFormat, QBrush, QColor
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

import speech_recognition as sr
from pydub import AudioSegment


class TitleBar(QtWidgets.QWidget):  
    """
    A custom title bar for the main window. It displays the title and window control buttons
    (minimize and close) and supports dragging the window.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setFixedHeight(35)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        self.titleLabel = QtWidgets.QLabel("Audio Transcriber", self)
        self.titleLabel.setAlignment(Qt.AlignCenter)

        # Create the minimize button.
        self.minimizeButton = QtWidgets.QPushButton(self)
        self.minimizeButton.setFixedSize(16, 16)
        self.minimizeButton.setObjectName("minimizeButton")
        self.minimizeButton.clicked.connect(self.parent.showMinimized)

        # Create the close button.
        self.closeButton = QtWidgets.QPushButton(self)
        self.closeButton.setFixedSize(16, 16)
        self.closeButton.setObjectName("closeButton")
        self.closeButton.clicked.connect(self.parent.close)

        # Layout: left side holds the control buttons.
        leftLayout = QtWidgets.QHBoxLayout()
        leftLayout.setSpacing(8)
        leftLayout.addWidget(self.closeButton)
        leftLayout.addWidget(self.minimizeButton)
        leftLayout.addStretch()

        layout.addLayout(leftLayout)
        layout.addWidget(self.titleLabel)
        layout.addStretch()

        # Apply an Apple-inspired style.
        self.setStyleSheet("""
            TitleBar {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f8f8f8, stop:1 #eaeaea);
            }
            QLabel {
                font-size: 14px;
                color: #333333;
            }
            QPushButton#closeButton {
                background-color: #ff605c;
                border-radius: 8px;
                border: none;
            }
            QPushButton#minimizeButton {
                background-color: #ffbd44;
                border-radius: 8px;
                border: none;
            }
            QPushButton#closeButton:hover, QPushButton#minimizeButton:hover {
                border: 1px solid rgba(0, 0, 0, 0.2);
            }
        """)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        self.oldPos = event.globalPos()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        delta = event.globalPos() - self.oldPos
        self.parent.move(self.parent.x() + delta.x(), self.parent.y() + delta.y())
        self.oldPos = event.globalPos()


class HighlighterTextEdit(QtWidgets.QTextEdit):
    """
    A QTextEdit subclass that pops up a menu after text selection.
    It supports toggling highlight on the selected text.
    """

    def __init__(self, parent_window, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent_window = parent_window

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        super().mouseReleaseEvent(event)
        cursor = self.textCursor()
        if cursor.hasSelection():
            # Check if the selection is already highlighted.
            current_format = cursor.charFormat()
            if current_format.property(QtGui.QTextFormat.UserProperty) == "highlighted":
                action_label = "Remove highlight"
            else:
                action_label = "Highlight selected text"

            rect = self.cursorRect(cursor)
            global_pos = self.mapToGlobal(rect.bottomRight())
            menu = QtWidgets.QMenu(self)
            action = menu.addAction(action_label)
            chosen = menu.exec(global_pos)
            if chosen == action:
                if action_label == "Highlight selected text":
                    self.highlightSelection()
                else:
                    self.dehighlightSelection()

    def highlightSelection(self):
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return
        fmt = QTextCharFormat()
        fmt.setProperty(QtGui.QTextFormat.UserProperty, "highlighted")
        if self.parent_window.dark_mode:
            fmt.setBackground(QBrush(QColor("#3a81c3")))  # Blue for dark mode.
        else:
            fmt.setBackground(QBrush(QColor("#fcd116")))  # Soft yellow for light mode.
        cursor.mergeCharFormat(fmt)
        self.setTextCursor(cursor)

    def dehighlightSelection(self):
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return
        fmt = QTextCharFormat()
        # Remove highlight by setting a transparent background and clearing the custom property.
        fmt.setBackground(QColor(0, 0, 0, 0))
        fmt.setProperty(QtGui.QTextFormat.UserProperty, "")
        cursor.mergeCharFormat(fmt)
        # Clear the selection to bring focus back.
        cursor.clearSelection()
        self.setTextCursor(cursor)


class FindDialog(QtWidgets.QDialog):
    """
    A larger find dialog that shows the transcription text with highlighted search results.
    The highlighting occurs only within this dialog.
    """

    def __init__(self, main_text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Find in Transcription")
        self.setFixedSize(600, 400)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # Search input field.
        self.search_input = QtWidgets.QLineEdit(self)
        self.search_input.setPlaceholderText("Enter text to find...")
        self.search_input.textChanged.connect(self.highlight_matches)
        layout.addWidget(self.search_input)

        # Text display area: shows a copy of the transcription.
        self.text_display = QtWidgets.QTextEdit(self)
        self.text_display.setReadOnly(True)
        self.text_display.setPlainText(main_text)
        layout.addWidget(self.text_display)

        # Close button.
        close_btn = QtWidgets.QPushButton("Close", self)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def highlight_matches(self):
        query = self.search_input.text()
        extraSelections = []
        self.text_display.setExtraSelections(extraSelections)
        if not query:
            return

        text = self.text_display.toPlainText()
        pos = 0
        while True:
            pos = text.lower().find(query.lower(), pos)
            if pos == -1:
                break
            selection = QtWidgets.QTextEdit.ExtraSelection()
            selection.format.setBackground(QtGui.QColor("yellow"))
            selection.format.setProperty(QtGui.QTextFormat.FullWidthSelection, True)
            cursor = self.text_display.textCursor()
            cursor.setPosition(pos)
            cursor.movePosition(
                QtGui.QTextCursor.Right, QtGui.QTextCursor.KeepAnchor, len(query)
            )
            selection.cursor = cursor
            extraSelections.append(selection)
            pos += len(query)
        self.text_display.setExtraSelections(extraSelections)


class SettingsPopup(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setModal(True)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.Dialog)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setFixedSize(320, 360)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        # Toggle button for dark mode.
        self.theme_btn = QtWidgets.QPushButton()
        self.theme_btn.setCheckable(True)
        self.theme_btn.clicked.connect(self.toggle_theme)
        layout.addWidget(self.theme_btn)

        # Checkbox for Live Speech to Text.
        self.live_speech_checkbox = QtWidgets.QCheckBox("Live Speech to Text", self)
        # When toggled in settings, call parent's toggle_live_speech_main so that both controls are in sync.
        self.live_speech_checkbox.toggled.connect(
            lambda checked: self.parent.toggle_live_speech_main(checked)
        )
        layout.addWidget(self.live_speech_checkbox)

        # Scrollable list of shortcut keys.
        shortcuts_list = QtWidgets.QListWidget(self)
        shortcuts = [
            "Ctrl+O: Open file",
            "Ctrl+S: Save transcription",
            "Ctrl+F: Find text",
            "Ctrl+M: Mute/Unmute audio",
            "Ctrl+P: Print transcription",
            "Ctrl+B: Play/Pause audio",
            "Ctrl+T: Transcribe",
            "Ctrl+G: Toggle Settings",
            "Ctrl+Shift+C: Copy All Text",
            "Ctrl+H: Highlight selection",
            "Ctrl+J: Remove highlight",
        ]
        for sc in shortcuts:
            shortcuts_list.addItem(sc)
        shortcuts_list.setMinimumHeight(120)
        scroll_area = QtWidgets.QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(shortcuts_list)
        layout.addWidget(scroll_area)

        # Close button.
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self.update_theme_style(dark=False)
        self.update_theme_button()

    def update_theme_style(self, dark: bool):
        if dark:
            style = """
            QDialog {
                background-color: rgba(28,28,30,0.95);
                border-radius: 10px;
            }
            QPushButton, QCheckBox {
                background-color: #2c2c2e;
                border: 1px solid #3a3a3c;
                border-radius: 5px;
                padding: 8px;
                color: #ffffff;
            }
            QPushButton:hover, QCheckBox:hover {
                background-color: #3a3a3c;
            }
            QListWidget, QLabel {
                color: #ffffff;
            }
            """
        else:
            style = """
            QDialog {
                background-color: rgba(250,250,250,0.95);
                border-radius: 10px;
            }
            QPushButton, QCheckBox {
                background-color: #f8f8f8;
                border: 1px solid #dcdcdc;
                border-radius: 5px;
                padding: 8px;
                color: #333333;
            }
            QPushButton:hover, QCheckBox:hover {
                background-color: #eaeaea;
            }
            QListWidget, QLabel {
                color: #333333;
            }
            """
        self.setStyleSheet(style)

    def update_theme_button(self):
        if self.parent.dark_mode:
            self.theme_btn.setText("🌙 Dark Mode")
            self.theme_btn.setChecked(True)
        else:
            self.theme_btn.setText("☀️ Light Mode")
            self.theme_btn.setChecked(False)

    def toggle_theme(self):
        self.parent.toggle_theme()
        self.update_theme_style(self.parent.dark_mode)
        self.update_theme_button()


class AudioTranscriber(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint)
        self.dark_mode = False
        self.current_file = ""
        self.prev_volume = 50  # used for mute toggle
        self.live_speech_enabled = False
        self.live_speech_listener = None
        self.initUI()
        self.apply_light_theme()
        self.settings_popup = SettingsPopup(self)
        self.adjust_size_to_screen()
        self.setupMediaPlayer()
        self.init_shortcuts()
        self.find_dialog = None  # Created on demand

    def initUI(self):
        main_widget = QtWidgets.QWidget()
        main_layout = QtWidgets.QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Title bar.
        self.title_bar = TitleBar(self)
        main_layout.addWidget(self.title_bar)

        content_widget = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(content_widget)
        content_layout.setContentsMargins(20, 20, 20, 20)

        # Header layout: Settings button.
        header_layout = QtWidgets.QHBoxLayout()
        self.settings_btn = QtWidgets.QPushButton("⚙️ Settings")
        self.settings_btn.clicked.connect(self.show_settings_popup)
        header_layout.addWidget(self.settings_btn)
        header_layout.addStretch()
        content_layout.addLayout(header_layout)

        # File selection layout.
        file_layout = QtWidgets.QHBoxLayout()
        self.open_btn = QtWidgets.QPushButton("🎵 Open MP3 File")
        self.open_btn.clicked.connect(self.open_file)
        file_layout.addWidget(self.open_btn)
        self.file_label = QtWidgets.QLabel("No file selected")
        file_layout.addWidget(self.file_label)
        # --- New: Live Speech Toggle Button ---
        self.live_speech_btn = QtWidgets.QPushButton("Start Live Speech")
        self.live_speech_btn.clicked.connect(lambda: self.toggle_live_speech_main())
        file_layout.addWidget(self.live_speech_btn)
        file_layout.addStretch()
        content_layout.addLayout(file_layout)

        # Copy and Save actions.
        action_layout = QtWidgets.QHBoxLayout()
        self.copy_btn = QtWidgets.QPushButton("📋 Copy Text")
        self.copy_btn.clicked.connect(self.copy_text)
        self.save_btn = QtWidgets.QPushButton("💾 Save Transcription")
        self.save_btn.clicked.connect(self.save_text)
        action_layout.addWidget(self.copy_btn)
        action_layout.addWidget(self.save_btn)
        action_layout.addStretch()
        content_layout.addLayout(action_layout)

        # Transcription output.
        self.text_output = HighlighterTextEdit(self)
        self.text_output.setReadOnly(True)
        self.text_output.setPlaceholderText("Transcription will appear here...")
        content_layout.addWidget(self.text_output)

        # --- Sound Control Panel ---
        self.sound_panel = self.createSoundControlPanel()
        content_layout.addWidget(self.sound_panel)

        # Transcribe button.
        self.transcribe_btn = QtWidgets.QPushButton("🎤 Transcribe")
        self.transcribe_btn.clicked.connect(self.start_transcription)
        content_layout.addWidget(self.transcribe_btn)

        main_layout.addWidget(content_widget)

        self.status_bar = QtWidgets.QStatusBar()
        self.setStatusBar(self.status_bar)
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                background-color: transparent;
            }
            QProgressBar::chunk {
                background-color: #007aff;
            }
        """)
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.progress_bar, stretch=1)

        self.setCentralWidget(main_widget)

    def init_shortcuts(self):
        # Shortcut for Find (Ctrl+F) opens the find dialog.
        find_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+F"), self)
        find_shortcut.activated.connect(self.show_find_dialog)
        # Shortcut for Open (Ctrl+O)
        open_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+O"), self)
        open_shortcut.activated.connect(self.open_file)
        # Shortcut for Save (Ctrl+S)
        save_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+S"), self)
        save_shortcut.activated.connect(self.save_text)
        # Shortcut for Mute (Ctrl+M)
        mute_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+M"), self)
        mute_shortcut.activated.connect(self.toggle_mute)
        # Shortcut for Print (Ctrl+P)
        print_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+P"), self)
        print_shortcut.activated.connect(self.print_text)
        # Shortcut for Play/Pause (Ctrl+B)
        play_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+B"), self)
        play_shortcut.activated.connect(self.toggle_play_stop)
        # Shortcut for Transcription (Ctrl+T)
        transcribe_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+T"), self)
        transcribe_shortcut.activated.connect(self.start_transcription)
        # Shortcut for toggling Settings (Ctrl+G)
        settings_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+G"), self)
        settings_shortcut.activated.connect(self.toggle_settings_popup)
        # Shortcut for Copy All (Ctrl+Shift+C)
        copy_all_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+Shift+C"), self)
        copy_all_shortcut.activated.connect(self.copy_all_text)
        # Shortcut for Highlight selection (Ctrl+H)
        highlight_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+H"), self)
        highlight_shortcut.activated.connect(self.highlight_selection)
        # Shortcut for Remove highlight (Ctrl+J)
        dehighlight_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+J"), self)
        dehighlight_shortcut.activated.connect(self.dehighlight_selection)

    def setupMediaPlayer(self):
        self.media_player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.media_player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.5)
        self.media_player.positionChanged.connect(self.position_changed)
        self.media_player.durationChanged.connect(self.duration_changed)

    def createSoundControlPanel(self):
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        self.play_stop_btn = QtWidgets.QPushButton("Play ")
        self.play_stop_btn.clicked.connect(self.toggle_play_stop)
        self.position_slider = QtWidgets.QSlider(Qt.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.sliderMoved.connect(self.set_position)
        self.volume_slider = QtWidgets.QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(50)
        self.volume_slider.valueChanged.connect(self.set_volume)
        layout.addWidget(self.play_stop_btn)
        layout.addWidget(self.position_slider)
        layout.addWidget(QtWidgets.QLabel("Volume"))
        layout.addWidget(self.volume_slider)
        return panel

    def position_changed(self, position):
        self.position_slider.setValue(position)

    def duration_changed(self, duration):
        self.position_slider.setRange(0, duration)

    def set_position(self, position):
        self.media_player.setPosition(position)

    def set_volume(self, volume):
        self.audio_output.setVolume(volume / 100.0)

    def toggle_play_stop(self):
        if not self.current_file:
            self.status_bar.showMessage("No file loaded.", 3000)
            return
        if self.media_player.source().toLocalFile() != self.current_file:
            self.media_player.setSource(QUrl.fromLocalFile(self.current_file))
        if self.media_player.playbackState() == QMediaPlayer.PlayingState:
            self.media_player.pause()
            self.play_stop_btn.setText("Play ")
            self.status_bar.showMessage("Paused", 2000)
        else:
            self.media_player.play()
            self.play_stop_btn.setText("Pause")
            self.status_bar.showMessage("Playing", 2000)

    def toggle_mute(self):
        if self.volume_slider.value() == 0:
            self.volume_slider.setValue(self.prev_volume)
            self.status_bar.showMessage("Unmuted", 2000)
        else:
            self.prev_volume = self.volume_slider.value()
            self.volume_slider.setValue(0)
            self.status_bar.showMessage("Muted", 2000)
        self.set_volume(self.volume_slider.value())

    def print_text(self):
        printer = QtPrintSupport.QPrinter(QtPrintSupport.QPrinter.HighResolution)
        dialog = QtPrintSupport.QPrintDialog(printer, self)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            self.text_output.document().print_(printer)

    def show_settings_popup(self):
        self.apply_blur_effect()
        self.settings_popup.update_theme_button()
        self.settings_popup.update_theme_style(self.dark_mode)
        center_point = self.mapToGlobal(self.rect().center())
        popup_rect = self.settings_popup.frameGeometry()
        popup_rect.moveCenter(center_point)
        self.settings_popup.move(popup_rect.topLeft())
        self.settings_popup.exec()
        self.remove_blur_effect()

    def toggle_settings_popup(self):
        if self.settings_popup.isVisible():
            self.settings_popup.close()
        else:
            self.show_settings_popup()

    def apply_blur_effect(self):
        blur_effect = QtWidgets.QGraphicsBlurEffect(self.centralWidget())
        blur_effect.setBlurRadius(10)
        self.centralWidget().setGraphicsEffect(blur_effect)
        self.centralWidget().setAutoFillBackground(True)

    def remove_blur_effect(self):
        self.centralWidget().setGraphicsEffect(None)
        self.centralWidget().setAutoFillBackground(False)

    def open_file(self):
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open MP3 File", "", "MP3 Files (*.mp3)"
        )
        if file_path:
            self.current_file = file_path
            self.file_label.setText(os.path.basename(self.current_file))
            self.status_bar.showMessage("File loaded successfully", 3000)
        else:
            self.status_bar.showMessage("No file selected", 3000)

    def start_transcription(self):
        if not self.current_file:
            self.status_bar.showMessage("Please select an MP3 file first!", 3000)
            return
        self.text_output.clear()
        self.status_bar.showMessage("Transcribing...")
        self.transcribe_btn.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(True)
        thread = threading.Thread(target=self.transcribe_audio)
        thread.start()

    def transcribe_audio(self):
        try:
            recognizer = sr.Recognizer()
            audio = AudioSegment.from_mp3(self.current_file)
            buffer = BytesIO()
            audio.export(buffer, format="wav")
            buffer.seek(0)
            with sr.AudioFile(buffer) as source:
                audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data)
            self.update_text_output(text, error=False)
        except Exception as e:
            self.update_text_output(str(e), error=True)
        QtCore.QMetaObject.invokeMethod(
            self.transcribe_btn,
            "setEnabled",
            QtCore.Qt.QueuedConnection,
            QtCore.Q_ARG(bool, True),
        )
        QtCore.QMetaObject.invokeMethod(
            self, "finish_transcription_ui", QtCore.Qt.QueuedConnection
        )

    @Slot()
    def finish_transcription_ui(self):
        self.progress_bar.setVisible(False)
        self.status_bar.showMessage("")

    def update_text_output(self, text, error=False):
        def update():
            if error:
                self.text_output.setTextColor(Qt.red)
                self.status_bar.showMessage("Error occurred during transcription", 5000)
            else:
                self.text_output.setTextColor(
                    Qt.black if not self.dark_mode else Qt.white
                )
                self.status_bar.showMessage("")
            self.text_output.setPlainText(text)

        QtCore.QMetaObject.invokeMethod(
            self.text_output,
            "setPlainText",
            QtCore.Qt.QueuedConnection,
            QtCore.Q_ARG(str, text),
        )

    def copy_text(self):
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(self.text_output.textCursor().selectedText())
        self.status_bar.showMessage("Selected text copied to clipboard!", 2000)

    def copy_all_text(self):
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(self.text_output.toPlainText())
        self.status_bar.showMessage("All text copied to clipboard!", 2000)

    def save_text(self):
        text = self.text_output.toPlainText()
        if not text:
            self.status_bar.showMessage("No transcription to save.", 3000)
            return
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Transcription", "", "Text Files (*.txt)"
        )
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(text)
                self.status_bar.showMessage("Transcription saved.", 3000)
            except Exception as e:
                self.status_bar.showMessage(f"Error saving file: {e}", 3000)
        else:
            self.status_bar.showMessage("Save canceled.", 3000)

    def show_find_dialog(self):
        if self.find_dialog is None:
            self.find_dialog = FindDialog(self.text_output.toPlainText(), self)
        else:
            self.find_dialog.text_display.setPlainText(self.text_output.toPlainText())
        self.find_dialog.show()
        self.find_dialog.raise_()
        self.find_dialog.activateWindow()

    def highlight_all_occurrences(self, term):
        extraSelections = []
        self.text_output.setExtraSelections(extraSelections)
        text = self.text_output.toPlainText()
        pos = 0
        while True:
            pos = text.lower().find(term.lower(), pos)
            if pos == -1:
                break
            selection = QtWidgets.QTextEdit.ExtraSelection()
            selection.format.setBackground(QtGui.QColor("yellow"))
            selection.format.setProperty(QtGui.QTextFormat.FullWidthSelection, True)
            cursor = self.text_output.textCursor()
            cursor.setPosition(pos)
            cursor.movePosition(
                QtGui.QTextCursor.Right, QtGui.QTextCursor.KeepAnchor, len(term)
            )
            selection.cursor = cursor
            extraSelections.append(selection)
            pos += len(term)
        self.text_output.setExtraSelections(extraSelections)

    def toggle_theme(self):
        self.dark_mode = not self.dark_mode
        if self.dark_mode:
            self.apply_dark_theme()
        else:
            self.apply_light_theme()
        self.update_highlight_colors()

    def update_highlight_colors(self):
        doc = self.text_output.document()
        block = doc.firstBlock()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                fragment = it.fragment()
                if fragment.isValid():
                    fmt = fragment.charFormat()
                    if fmt.property(QtGui.QTextFormat.UserProperty) == "highlighted":
                        new_fmt = QtGui.QTextCharFormat(fmt)
                        if self.dark_mode:
                            new_fmt.setBackground(QColor("#3a81c3"))
                        else:
                            new_fmt.setBackground(QColor("#fcd116"))
                        cursor = QtGui.QTextCursor(doc)
                        cursor.setPosition(fragment.position())
                        cursor.setPosition(
                            fragment.position() + fragment.length(),
                            QtGui.QTextCursor.KeepAnchor,
                        )
                        cursor.mergeCharFormat(new_fmt)
                it += 1
            block = block.next()

    def apply_dark_theme(self):
        dark_stylesheet = """
        QMainWindow {
            background-color: #1c1c1e;
        }
        QWidget {
            background-color: #1c1c1e;
            color: #ffffff;
        }
        QPushButton {
            background-color: #2c2c2e;
            border: 1px solid #3a3a3c;
            border-radius: 5px;
            padding: 8px;
            color: #ffffff;
        }
        QPushButton:hover {
            background-color: #3a3a3c;
        }
        QTextEdit {
            background-color: #2c2c2e;
            border: 1px solid #3a3a3c;
            border-radius: 5px;
            padding: 10px;
            color: #ffffff;
        }
        QLabel {
            color: #ffffff;
        }
        QStatusBar {
            background-color: #2c2c2e;
        }
        """
        self.setStyleSheet(dark_stylesheet)
        self.title_bar.setStyleSheet("""
            TitleBar {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2c2c2e, stop:1 #1c1c1e);
            }
            QLabel {
                font-size: 14px;
                color: #ffffff;
            }
            QPushButton#closeButton {
                background-color: #ff605c;
                border-radius: 8px;
                border: none;
            }
            QPushButton#minimizeButton {
                background-color: #ffbd44;
                border-radius: 8px;
                border: none;
            }
            QPushButton#closeButton:hover, QPushButton#minimizeButton:hover {
                border: 1px solid rgba(255, 255, 255, 0.6);
            }
        """)

    def apply_light_theme(self):
        light_stylesheet = """
        QMainWindow {
            background-color: #ffffff;
        }
        QWidget {
            background-color: #ffffff;
            color: #333333;
        }
        QPushButton {
            background-color: #f8f8f8;
            border: 1px solid #dcdcdc;
            border-radius: 5px;
            padding: 8px;
            color: #333333;
        }
        QPushButton:hover {
            background-color: #eaeaea;
        }
        QTextEdit {
            background-color: #ffffff;
            border: 1px solid #dcdcdc;
            border-radius: 5px;
            padding: 10px;
            color: #333333;
        }
        QLabel {
            color: #333333;
        }
        QStatusBar {
            background-color: #f8f8f8;
        }
        """
        self.setStyleSheet(light_stylesheet)
        self.title_bar.setStyleSheet("""
            TitleBar {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f8f8f8, stop:1 #eaeaea);
            }
            QLabel {
                font-size: 14px;
                color: #333333;
            }
            QPushButton#closeButton {
                background-color: #ff605c;
                border-radius: 8px;
                border: none;
            }
            QPushButton#minimizeButton {
                background-color: #ffbd44;
                border-radius: 8px;
                border: none;
            }
            QPushButton#closeButton:hover, QPushButton#minimizeButton:hover {
                border: 1px solid rgba(0, 0, 0, 0.2);
            }
        """)

    def adjust_size_to_screen(self):
        screen = QtGui.QGuiApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            new_width = int(available.width() * 0.7)
            new_height = int(available.height() * 0.7)
            self.resize(new_width, new_height)

    def handle_screen_change(self, screen):
        available = screen.availableGeometry()
        new_width = int(available.width() * 0.7)
        new_height = int(available.height() * 0.7)
        self.resize(new_width, new_height)

    def showEvent(self, event):
        if self.windowHandle() is not None:
            self.windowHandle().screenChanged.connect(self.handle_screen_change)
        super().showEvent(event)

    # Helper methods for new shortcuts.
    def highlight_selection(self):
        self.text_output.highlightSelection()

    def dehighlight_selection(self):
        self.text_output.dehighlightSelection()

    # Methods for Live Speech-to-Text on the main page.
    def toggle_live_speech_main(self, enabled=None):
        # If an explicit value is provided (from settings checkbox), use it.
        # Otherwise, toggle based on current state (for main-page button).
        if enabled is None:
            enabled = not self.live_speech_enabled
        if enabled and not self.live_speech_enabled:
            self.start_live_speech()
            self.live_speech_enabled = True
            self.live_speech_btn.setText("Stop Live Speech")
            self.status_bar.showMessage("Live speech started", 2000)
        elif not enabled and self.live_speech_enabled:
            self.stop_live_speech()
            self.live_speech_enabled = False
            self.live_speech_btn.setText("Start Live Speech")
            self.status_bar.showMessage("Live speech stopped", 2000)

    def start_live_speech(self):
        if self.live_speech_listener is None:
            self.recognizer_live = sr.Recognizer()
            self.microphone = sr.Microphone()
            try:
                with self.microphone as source:
                    self.recognizer_live.adjust_for_ambient_noise(source)
            except Exception:
                pass
            self.live_speech_listener = self.recognizer_live.listen_in_background(
                self.microphone, self.live_speech_callback
            )

    def live_speech_callback(self, recognizer, audio):
        try:
            text = recognizer.recognize_google(audio)
            QtCore.QMetaObject.invokeMethod(
                self.text_output,
                "append",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(str, text),
            )
        except Exception:
            pass

    def stop_live_speech(self):
        if self.live_speech_listener is not None:
            self.live_speech_listener(wait_for_stop=False)
            self.live_speech_listener = None


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    window = AudioTranscriber()
    window.show()
    sys.exit(app.exec())
