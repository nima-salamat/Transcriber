"""Qt stylesheet generated from the central design-token palette."""

from __future__ import annotations

from transcriber.ui.design.tokens import get_tokens


def stylesheet(theme: str) -> str:
    c = get_tokens(theme).colors
    return f"""
    QWidget {{ color: {c['text']}; font-family: 'Segoe UI', 'Noto Sans', sans-serif; font-size: 13px; }}
    QMainWindow, QDialog {{ background: {c['window']}; }}
    QWidget#Root {{ background: {c['window']}; }}
    QFrame#Sidebar {{ background: {c['surface']}; border: 0; }}
    QFrame#Card {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 14px; }}
    QLabel#Muted {{ color: {c['muted']}; }}
    QLabel#PageTitle {{ font-size: 25px; font-weight: 650; }}
    QLabel#SectionTitle {{ font-size: 16px; font-weight: 620; }}
    QPushButton {{ background: {c['surface_2']}; border: 1px solid {c['border']}; border-radius: 9px; padding: 9px 14px; }}
    QPushButton:hover {{ border-color: {c['accent']}; }}
    QPushButton:focus {{ border: 2px solid {c['focus']}; }}
    QPushButton:disabled {{ color: {c['muted']}; background: {c['surface']}; }}
    QPushButton#Primary {{ background: {c['accent']}; color: white; border: none; font-weight: 600; }}
    QPushButton#Primary:hover {{ background: {c['accent_hover']}; }}
    QPushButton#Danger {{ background: {c['danger']}; color: white; border: none; }}
    QPushButton#Nav {{ text-align: left; padding: 11px 13px; border: 0; background: transparent; color: {c['muted']}; }}
    QPushButton#Nav:checked {{ background: {c['surface_2']}; color: {c['text']}; font-weight: 650; }}
    QPushButton#Nav:hover {{ background: {c['surface_2']}; }}
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ background: {c['input']}; border: 1px solid {c['border']}; border-radius: 8px; padding: 8px 10px; selection-background-color: {c['accent']}; }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border: 2px solid {c['focus']}; }}
    QComboBox::drop-down {{ border: 0; width: 25px; }}
    QProgressBar {{ background: {c['surface_2']}; border: 0; border-radius: 5px; height: 9px; text-align: center; }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: 5px; }}
    QSlider::groove:horizontal {{ height: 5px; background: {c['surface_2']}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ width: 13px; margin: -5px 0; border-radius: 6px; background: {c['accent']}; }}
    QStatusBar {{ background: {c['surface']}; color: {c['muted']}; border-top: 1px solid {c['border']}; }}
    QScrollArea {{ border: 0; background: transparent; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 3px 1px 3px 1px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 1px 3px 1px 3px; }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{ background: {c['border']}; border-radius: 4px; min-height: 34px; min-width: 34px; }}
    QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{ background: {c['muted']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; height: 0; border: 0; background: transparent; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
    QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 10px; }}
    QTabBar::tab {{ background: {c['surface_2']}; padding: 9px 15px; margin-right: 4px; border-radius: 7px; }}
    QTabBar::tab:selected {{ background: {c['accent']}; color: white; }}
    QDockWidget {{ font-weight: 600; }}
    QDockWidget::title {{ background: {c['surface']}; padding: 8px 12px; border-bottom: 1px solid {c['border']}; }}
    QTableWidget {{ gridline-color: {c['border']}; alternate-background-color: {c['surface']}; }}
    QHeaderView::section {{ background: {c['surface_2']}; color: {c['muted']}; border: 0; border-bottom: 1px solid {c['border']}; padding: 7px; }}
    QToolTip {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 5px; }}
    """
