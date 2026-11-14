"""Compact design system shared by all pages."""

DARK = {
    "window": "#101319", "surface": "#181e27", "surface_2": "#202936",
    "text": "#edf2f7", "muted": "#9aa8b8", "border": "#2b3745",
    "accent": "#75a7ff", "accent_hover": "#8bb6ff", "danger": "#ef6470",
    "success": "#4cc69a", "input": "#141a22",
}
LIGHT = {
    "window": "#f4f6f9", "surface": "#ffffff", "surface_2": "#edf1f6",
    "text": "#1e2937", "muted": "#64748b", "border": "#dbe2eb",
    "accent": "#326ed5", "accent_hover": "#245bb7", "danger": "#d94350",
    "success": "#17845f", "input": "#ffffff",
}


def stylesheet(theme: str) -> str:
    c = LIGHT if theme == "light" else DARK
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
    QPushButton:disabled {{ color: {c['muted']}; background: {c['surface']}; }}
    QPushButton#Primary {{ background: {c['accent']}; color: white; border: none; font-weight: 600; }}
    QPushButton#Primary:hover {{ background: {c['accent_hover']}; }}
    QPushButton#Danger {{ background: {c['danger']}; color: white; border: none; }}
    QPushButton#Nav {{ text-align: left; padding: 11px 13px; border: 0; background: transparent; color: {c['muted']}; }}
    QPushButton#Nav:checked {{ background: {c['surface_2']}; color: {c['text']}; font-weight: 650; }}
    QPushButton#Nav:hover {{ background: {c['surface_2']}; }}
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {{ background: {c['input']}; border: 1px solid {c['border']}; border-radius: 8px; padding: 8px 10px; selection-background-color: {c['accent']}; }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border-color: {c['accent']}; }}
    QComboBox::drop-down {{ border: 0; width: 25px; }}
    QProgressBar {{ background: {c['surface_2']}; border: 0; border-radius: 5px; height: 9px; text-align: center; }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: 5px; }}
    QSlider::groove:horizontal {{ height: 5px; background: {c['surface_2']}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ width: 13px; margin: -5px 0; border-radius: 6px; background: {c['accent']}; }}
    QStatusBar {{ background: {c['surface']}; color: {c['muted']}; border-top: 1px solid {c['border']}; }}
    QScrollArea {{ border: 0; background: transparent; }}
    QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 10px; }}
    QTabBar::tab {{ background: {c['surface_2']}; padding: 9px 15px; margin-right: 4px; border-radius: 7px; }}
    QTabBar::tab:selected {{ background: {c['accent']}; color: white; }}
    QToolTip {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 5px; }}
    """
