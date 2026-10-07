"""Dark theme stylesheet (PotPlayer-inspired).

A single global QSS applied to the QApplication. The palette is near-black
with thin separators and a yellow accent for the seek/volume handles,
matching PotPlayer's default skin. Widget object names set across the UI
are targeted for accents.
"""

from __future__ import annotations

# Core palette
_BG = "#101014"
_BG_ALT = "#17171b"
_PANEL = "#141418"
_LIST = "#0e0e12"
_BORDER = "#2a2a30"
_TEXT = "#d8d8dc"
_MUTED = "#8a8a92"
_ACCENT = "#e0c040"      # PotPlayer-ish yellow (seek/volume)
_SELECT = "#2b2b34"

DARK_QSS = f"""
* {{
    color: {_TEXT};
    font-size: 12px;
}}

QMainWindow, QWidget {{
    background-color: {_BG};
}}

QMenuBar {{
    background-color: {_BG_ALT};
    color: {_TEXT};
}}
QMenuBar::item:selected {{
    background-color: {_SELECT};
}}
QMenu {{
    background-color: {_PANEL};
    border: 1px solid {_BORDER};
}}
QMenu::item:selected {{
    background-color: {_ACCENT};
    color: #000000;
}}

/* ---- transport / icon buttons ---- */
QPushButton#iconButton {{
    background-color: transparent;
    border: none;
    padding: 4px;
    font-size: 14px;
    color: {_TEXT};
}}
QPushButton#iconButton:hover {{
    background-color: {_SELECT};
    border-radius: 3px;
}}
QPushButton#iconButton:checked {{
    color: {_ACCENT};
}}

/* ---- generic buttons ---- */
QPushButton {{
    background-color: {_BG_ALT};
    border: 1px solid {_BORDER};
    border-radius: 3px;
    padding: 3px 8px;
}}
QPushButton:hover {{
    background-color: {_SELECT};
}}
QPushButton:pressed {{
    background-color: {_ACCENT};
    color: #000000;
}}

/* ---- playlist toolbar buttons (ADD/DEL/SORT) ---- */
QPushButton#playlistToolButton {{
    background-color: {_BG_ALT};
    border: 1px solid {_BORDER};
    border-radius: 3px;
    padding: 4px 12px;
    font-weight: bold;
    color: {_MUTED};
}}
QPushButton#playlistToolButton:hover {{
    color: {_TEXT};
    background-color: {_SELECT};
}}

/* ---- control bar ---- */
QWidget#controlBar {{
    background-color: {_BG_ALT};
    border-top: 1px solid {_BORDER};
}}
QLabel#timeLabel {{
    color: {_ACCENT};
    font-family: monospace;
    font-size: 12px;
}}

/* ---- sliders ---- */
QSlider::groove:horizontal {{
    height: 4px;
    background: #33333a;
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {_ACCENT};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {_ACCENT};
    width: 10px;
    margin: -4px 0;
    border-radius: 5px;
}}
QSlider#seekSlider::handle:horizontal {{
    background: #f0f0f0;
}}

/* ---- now-playing overlay ---- */
QWidget#nowPlayingBar {{
    background-color: rgba(0, 0, 0, 120);
}}
QLabel#bigTime {{
    color: {_TEXT};
    font-size: 30px;
    font-weight: bold;
}}
QLabel#bigTimeTotal {{
    color: {_ACCENT};
    font-size: 15px;
    font-weight: bold;
}}
QLabel#nowPlayingTitle {{
    font-size: 14px;
    font-weight: bold;
}}
QLabel#nowPlayingTech {{
    color: {_MUTED};
    font-size: 11px;
}}
QLabel#albumArt {{
    font-size: 72px;
    color: #3a3a44;
    background-color: #0b0b0e;
}}

/* ---- playlist ---- */
QWidget#playlistPanel {{
    background-color: {_PANEL};
    border-left: 1px solid {_BORDER};
}}
QLabel#panelHeader {{
    font-weight: bold;
    font-size: 13px;
    color: {_TEXT};
    padding: 2px 0;
}}
QLabel#playlistTab {{
    background-color: {_BG_ALT};
    border: 1px solid {_BORDER};
    border-bottom: 2px solid {_ACCENT};
    padding: 4px 16px;
}}
QListView#playlistView {{
    background-color: {_LIST};
    border: 1px solid {_BORDER};
    outline: 0;
}}
/* Selection fill (also drawn by the delegate's palette highlight). The
   now-playing and keyboard-focus cues are drawn by _TrackDelegate so they
   stay visually distinct from this selection background. */
QListView::item:selected {{
    background-color: {_SELECT};
}}
QListView::item:hover {{
    background-color: #1c1c22;
}}

/* ---- inputs ---- */
QLineEdit, QTextEdit {{
    background-color: {_LIST};
    border: 1px solid {_BORDER};
    border-radius: 3px;
    padding: 4px;
    selection-background-color: {_ACCENT};
    selection-color: #000000;
}}

QComboBox {{
    background-color: {_BG_ALT};
    border: 1px solid {_BORDER};
    border-radius: 3px;
    padding: 3px 8px;
}}
QComboBox QAbstractItemView {{
    background-color: {_PANEL};
    selection-background-color: {_ACCENT};
    selection-color: #000000;
}}

QTableWidget {{
    background-color: {_LIST};
    gridline-color: {_BORDER};
    selection-background-color: {_SELECT};
}}
QHeaderView::section {{
    background-color: {_BG_ALT};
    padding: 4px;
    border: none;
}}

QSplitter::handle {{
    background-color: {_BORDER};
}}

QScrollBar:vertical {{
    background: {_PANEL};
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: {_BORDER};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
}}
"""
