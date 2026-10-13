"""Dark theme: palette tokens + one stylesheet applied app-wide."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

BG = "#0E1014"
SURFACE = "#161920"
SURFACE_2 = "#1D2129"
SURFACE_3 = "#252A34"
BORDER = "#2A2F3A"
TEXT = "#E7EAF0"
MUTED = "#8B93A5"
ACCENT = "#7C8CFF"
ACCENT_HOVER = "#93A0FF"
DANGER = "#FF6B6B"
WARNING = "#F5B94A"
SUCCESS = "#4ADE80"

STYLESHEET = f"""
* {{
    font-size: 13px;
    color: {TEXT};
    outline: none;
}}
QMainWindow, QDialog, #Root {{ background: {BG}; }}
QWidget#Sidebar {{ background: {SURFACE}; border-right: 1px solid {BORDER}; }}
QLabel#AppTitle {{ font-size: 18px; font-weight: 700; padding: 4px 8px 16px 8px; }}
QLabel#PageTitle {{ font-size: 20px; font-weight: 650; }}
QLabel#Muted, QLabel[muted="true"] {{ color: {MUTED}; }}
QLabel#SectionLabel {{ color: {MUTED}; font-size: 11px; font-weight: 600; letter-spacing: 1px; }}

QPushButton#NavButton {{
    text-align: left; padding: 9px 12px; border: none; border-radius: 8px;
    background: transparent; color: {MUTED}; font-weight: 500;
}}
QPushButton#NavButton:hover {{ background: {SURFACE_2}; color: {TEXT}; }}
QPushButton#NavButton:checked {{ background: {SURFACE_3}; color: {TEXT}; }}

QFrame#Card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#Banner {{ background: #2A2416; border: 1px solid #4A3B1C; border-radius: 10px; }}
QFrame#Banner QLabel {{ color: {WARNING}; }}

QPushButton {{
    background: {SURFACE_3}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 7px 14px; font-weight: 500;
}}
QPushButton:hover {{ background: #2D3340; }}
QPushButton:pressed {{ background: #20242D; }}
QPushButton:disabled {{ color: #59606E; background: {SURFACE_2}; }}
QPushButton#Primary {{ background: {ACCENT}; border: none; color: #0B0D12; font-weight: 650; padding: 10px 22px; }}
QPushButton#Primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#Primary[running="true"] {{ background: {DANGER}; color: #170A0A; }}
QPushButton#Danger {{ color: {DANGER}; }}
QToolButton {{ background: {SURFACE_3}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px; }}
QToolButton:hover {{ background: #2D3340; }}

QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QKeySequenceEdit, QFontComboBox {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 6px 10px; min-height: 20px; selection-background-color: {ACCENT};
}}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover {{ border-color: #3A4150; }}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QKeySequenceEdit:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 4px;
    selection-background-color: {SURFACE_3};
}}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 34px; height: 18px; border-radius: 9px; background: {SURFACE_3}; border: 1px solid {BORDER};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QSlider::groove:horizontal {{ height: 4px; background: {SURFACE_3}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; background: {TEXT};
}}

QProgressBar {{
    background: {SURFACE_3}; border: none; border-radius: 3px; height: 6px; max-height: 6px; text-align: center;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}

QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {SURFACE_3}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}

QMenu {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {SURFACE_3}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}
QToolTip {{ background: {SURFACE_3}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 6px; padding: 4px 8px; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")  # consistent base on every OS; QSS does the rest
    pal = QPalette()
    for role, color in [
        (QPalette.ColorRole.Window, BG),
        (QPalette.ColorRole.Base, SURFACE_2),
        (QPalette.ColorRole.AlternateBase, SURFACE),
        (QPalette.ColorRole.Text, TEXT),
        (QPalette.ColorRole.WindowText, TEXT),
        (QPalette.ColorRole.ButtonText, TEXT),
        (QPalette.ColorRole.Button, SURFACE_3),
        (QPalette.ColorRole.Highlight, ACCENT),
        (QPalette.ColorRole.HighlightedText, "#0B0D12"),
        (QPalette.ColorRole.PlaceholderText, MUTED),
        (QPalette.ColorRole.ToolTipBase, SURFACE_3),
        (QPalette.ColorRole.ToolTipText, TEXT),
    ]:
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)
