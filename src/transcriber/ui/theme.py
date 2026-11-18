"""Qt stylesheet generated from the central semantic design-token palette."""

from __future__ import annotations

from transcriber.ui.design.tokens import get_tokens


def stylesheet(theme: str) -> str:
    c = get_tokens(theme).colors
    return f"""
    QWidget {{
        color: {c['text']};
        font-family: 'Segoe UI', 'Noto Sans', sans-serif;
        font-size: 13px;
        outline: none;
    }}
    QMainWindow, QDialog {{ background: {c['window']}; }}
    QWidget#Root {{ background: {c['window']}; }}
    QFrame#Sidebar {{ background: {c['surface']}; border: 0; }}
    QFrame#Card {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 15px;
    }}
    QLabel#Muted {{ color: {c['muted']}; }}
    QLabel#PageTitle {{ font-size: 26px; font-weight: 700; }}
    QLabel#SectionTitle {{ font-size: 16px; font-weight: 650; }}
    QLabel#AssistantTitle {{ font-size: 17px; font-weight: 700; }}
    QLabel#AssistantEyebrow {{ color: {c['muted']}; font-size: 10px; font-weight: 750; letter-spacing: 1px; }}
    QLabel#AssistantProject {{ font-size: 12px; font-weight: 600; }}
    QLabel#AssistantStatus {{
        color: {c['muted']};
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        padding: 5px 8px;
        font-size: 10px;
        font-weight: 650;
    }}
    QLabel#AssistantStatus[state="connected"] {{
        color: {c['success']};
        border-color: {c['success']};
    }}
    QLabel#AssistantStatus[state="connecting"] {{ color: {c['warning']}; }}
    QLabel#AssistantStatus[state="error"] {{ color: {c['danger']}; border-color: {c['danger']}; }}
    QFrame#AssistantContext, QFrame#AssistantComposer, QFrame#AssistantVoicePanel,
    QFrame#AssistantSettingsCard {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 12px;
    }}
    QFrame#VoiceHero {{
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 18px;
    }}
    QLabel#AssistantSectionTitle {{ font-size: 14px; font-weight: 700; }}
    QWidget#AssistantConversationPage, QWidget#AssistantSettingsPage,
    QWidget#AssistantSettingsContent {{ background: transparent; }}
    QScrollArea#AssistantSettingsScroll {{ background: transparent; border: 0; }}
    QPushButton#AssistantSettingsButton {{
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 12px;
        padding: 0;
        font-size: 20px;
        min-width: 36px;
        max-width: 40px;
        min-height: 36px;
        max-height: 40px;
    }}
    QPushButton#AssistantSettingsButton:hover {{
        background: {c['surface_hover']};
        border-color: {c['accent']};
    }}
    QTextBrowser#AssistantChat {{
        background: {c['window']};
        border: 1px solid {c['border']};
        border-radius: 12px;
        padding: 5px;
        selection-background-color: {c['accent']};
    }}
    QPlainTextEdit#AssistantPrompt {{
        background: transparent;
        border: 0;
        padding: 4px;
    }}
    QPlainTextEdit#AssistantPrompt:focus {{ border: 0; }}
    QPushButton {{
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 9px;
        padding: 9px 14px;
        min-height: 18px;
    }}
    QPushButton:hover {{ border-color: {c['accent']}; background: {c['surface_hover']}; }}
    QPushButton:pressed {{ background: {c['surface_hover']}; }}
    QPushButton:focus {{ border: 2px solid {c['focus']}; }}
    QPushButton:disabled {{ color: {c['muted']}; background: {c['surface']}; border-color: {c['border']}; }}
    QPushButton#Primary {{
        background: {c['accent']};
        color: white;
        border: 0;
        font-weight: 700;
    }}
    QPushButton#Primary:hover {{ background: {c['accent_hover']}; }}
    QPushButton#Danger {{ background: {c['danger']}; color: white; border: 0; }}
    QPushButton#Subtle {{ background: transparent; border: 1px solid {c['border']}; }}
    QPushButton#Subtle:hover {{ background: {c['surface_hover']}; }}
    QPushButton#Suggestion {{
        min-height: 14px;
        padding: 6px 8px;
        border-radius: 8px;
        font-size: 11px;
        font-weight: 600;
        background: {c['surface_2']};
    }}
    QPushButton#Disclosure {{
        background: transparent;
        border: 0;
        text-align: left;
        color: {c['muted']};
        padding: 6px 2px;
        font-weight: 600;
    }}
    QPushButton#QuickAction {{
        text-align: left;
        padding: 11px 13px;
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        font-weight: 600;
    }}
    QPushButton#Nav {{
        text-align: left;
        padding: 11px 13px;
        border: 0;
        border-radius: 9px;
        background: transparent;
        color: {c['muted']};
    }}
    QPushButton#Nav:checked {{
        background: {c['surface_2']};
        color: {c['text']};
        font-weight: 700;
    }}
    QPushButton#Nav:hover {{ background: {c['surface_2']}; color: {c['text']}; }}
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {c['input']};
        border: 1px solid {c['border']};
        border-radius: 9px;
        padding: 8px 10px;
        selection-background-color: {c['accent']};
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
    QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 1px solid {c['focus']};
    }}
    QComboBox::drop-down {{ border: 0; width: 27px; }}
    QComboBox QAbstractItemView {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        selection-background-color: {c['surface_hover']};
        outline: 0;
        padding: 4px;
    }}
    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {c['border']};
        border-radius: 5px;
        background: {c['input']};
    }}
    QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
    QCheckBox::indicator:hover {{ border-color: {c['focus']}; }}
    QRadioButton {{ spacing: 8px; }}
    QProgressBar {{
        background: {c['surface_2']};
        border: 0;
        border-radius: 5px;
        height: 9px;
        text-align: center;
    }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: 5px; }}
    QSlider::groove:horizontal {{ height: 5px; background: {c['surface_2']}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ width: 14px; margin: -5px 0; border-radius: 7px; background: {c['accent']}; }}
    QListWidget, QTreeWidget {{
        background: transparent;
        border: 0;
        outline: 0;
        padding: 3px;
    }}
    QListWidget::item, QTreeWidget::item {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        padding: 11px 12px;
        margin: 3px 1px;
    }}
    QListWidget::item:hover, QTreeWidget::item:hover {{ background: {c['surface_hover']}; }}
    QListWidget::item:selected, QTreeWidget::item:selected {{
        background: {c['surface_2']};
        border-color: {c['accent']};
        color: {c['text']};
    }}
    QStatusBar {{
        background: {c['surface']};
        color: {c['muted']};
        border-top: 1px solid {c['border']};
        padding: 2px 8px;
    }}
    QScrollArea {{ border: 0; background: transparent; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 3px 1px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 1px 3px; }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
        background: {c['border']};
        border-radius: 4px;
        min-height: 34px;
        min-width: 34px;
    }}
    QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{ background: {c['muted']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0; height: 0; border: 0; background: transparent;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
    QTabWidget::pane {{
        border: 1px solid {c['border']};
        border-radius: 11px;
        top: -1px;
    }}
    QTabBar::tab {{
        background: transparent;
        padding: 9px 15px;
        margin-right: 4px;
        border: 0;
        border-bottom: 2px solid transparent;
        color: {c['muted']};
    }}
    QTabBar::tab:selected {{
        color: {c['text']};
        border-bottom-color: {c['accent']};
        font-weight: 700;
    }}
    QDockWidget {{ font-weight: 650; }}
    /* Inspector uses an explicit LTR splitter: drag its handle left to widen. */
    QSplitter#WorkspaceSplitter::handle:horizontal {{
        background: {c['border']};
        width: 6px;
    }}
    QSplitter#WorkspaceSplitter::handle:horizontal:hover {{
        background: {c['accent']};
    }}
    QMainWindow::separator {{
        background: {c['border']};
        width: 6px;
        height: 5px;
    }}
    QMainWindow::separator:hover {{
        background: {c['accent']};
    }}
    QDockWidget::title {{
        background: {c['surface']};
        padding: 9px 13px;
        border-bottom: 1px solid {c['border']};
    }}
    QTableWidget {{
        gridline-color: {c['border']};
        alternate-background-color: {c['surface']};
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        selection-background-color: {c['surface_hover']};
    }}
    QHeaderView::section {{
        background: {c['surface_2']};
        color: {c['muted']};
        border: 0;
        border-bottom: 1px solid {c['border']};
        padding: 9px;
        font-weight: 650;
    }}
    QMenu {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        padding: 5px;
    }}
    QMenu::item {{ padding: 8px 24px 8px 12px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {c['surface_hover']}; }}
    QToolTip {{
        background: {c['surface']};
        color: {c['text']};
        border: 1px solid {c['border']};
        padding: 6px 8px;
    }}
    """