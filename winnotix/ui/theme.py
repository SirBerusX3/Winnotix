"""Palette and stylesheet.

Replaces two upstream pieces: the 8-line hypnotix.css, and the XApp dark-mode
integration (`XApp.GtkWindow` / the dark-mode preference), which has no Windows
equivalent. Qt reports the OS light/dark preference directly via
`QGuiApplication.styleHints().colorScheme()`, so the whole XApp dependency is
replaced by reading that.

The green accent is deliberate: it is Linux Mint's, and keeping it is part of
the app still reading as Hypnotix. Everything around it is neutral so the window
does not look foreign on a Windows desktop.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication


@dataclass(frozen=True)
class Palette:
    dark: bool
    window: str
    surface: str
    surface_alt: str
    border: str
    text: str
    text_dim: str
    accent: str
    accent_text: str
    selection: str
    danger: str

    @property
    def icon(self) -> str:
        return self.text

    @property
    def icon_dim(self) -> str:
        return self.text_dim


LIGHT = Palette(
    dark=False,
    window="#f4f4f2",
    surface="#ffffff",
    surface_alt="#ececea",
    border="#d6d5d1",
    text="#22262a",
    text_dim="#6d7278",
    accent="#69a637",
    accent_text="#ffffff",
    selection="#e4f0d8",
    danger="#c0392b",
)

DARK = Palette(
    dark=True,
    window="#1f2124",
    surface="#282a2e",
    surface_alt="#303338",
    border="#3c4045",
    text="#e6e7e8",
    text_dim="#9aa0a6",
    accent="#8fbc5a",
    accent_text="#16210a",
    selection="#3a4a2c",
    danger="#e57368",
)


def current_palette() -> Palette:
    """Follow the OS light/dark preference."""
    try:
        scheme = QGuiApplication.styleHints().colorScheme()
    except (AttributeError, RuntimeError):
        return LIGHT
    return DARK if scheme == Qt.ColorScheme.Dark else LIGHT


def stylesheet(p: Palette) -> str:
    return f"""
QWidget {{
    background-color: {p.window};
    color: {p.text};
    font-size: 10pt;
}}

/* ---- header bar -------------------------------------------------- */
#HeaderBar {{
    background-color: {p.surface};
    border-bottom: 1px solid {p.border};
}}
#HeaderTitle   {{ font-size: 11pt; font-weight: 600; }}
#HeaderSubtitle{{ font-size:  9pt; color: {p.text_dim}; }}
#HeaderBar QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 5px;
}}
#HeaderBar QToolButton:hover   {{ background: {p.surface_alt}; border-color: {p.border}; }}
#HeaderBar QToolButton:pressed {{ background: {p.border}; }}
#HeaderBar QToolButton:checked {{ background: {p.selection}; border-color: {p.accent}; }}
#HeaderBar QToolButton:disabled{{ background: transparent; }}

/* ---- status / playback bar --------------------------------------- */
#StatusBar {{
    background-color: {p.surface};
    border-top: 1px solid {p.border};
}}
#StatusLabel   {{ color: {p.text_dim}; }}
#PlaybackLabel {{ font-weight: 600; }}
#PlaybackBar QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 4px;
}}
#PlaybackBar QToolButton:hover {{ background: {p.surface_alt}; border-color: {p.border}; }}

/* ---- landing page ------------------------------------------------ */
#ProviderName {{ font-size: 15pt; font-weight: 600; }}
#LandingTile {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: 8px;
    padding: 18px 26px;
}}
#LandingTile:hover:enabled  {{ border-color: {p.accent}; background-color: {p.surface_alt}; }}
#LandingTile:pressed        {{ background-color: {p.selection}; }}
#LandingTile:disabled       {{ color: {p.text_dim}; border-color: {p.border}; }}

/* Child labels inherit the generic QWidget background otherwise, which paints
   an opaque rectangle over the tile surface. */
#LandingTile QLabel, #Tile QLabel, QPushButton QLabel {{
    background: transparent;
    border: none;
}}

/* ---- category / provider tiles ----------------------------------- */
#Tile {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: 6px;
    padding: 10px 14px;
    text-align: left;
}}
#Tile:hover   {{ border-color: {p.accent}; background-color: {p.surface_alt}; }}
#Tile:pressed {{ background-color: {p.selection}; }}
#TileCount {{ color: {p.text_dim}; }}

/* ---- channel sidebar ---------------------------------------------
   Colours also set on the widget palette in widgets.ChannelList: the
   windows11 style paints item views itself and ignores these rules. */
QListWidget#Sidebar {{
    background-color: {p.surface};
    border: none;
    border-right: 1px solid {p.border};
    outline: none;
}}
QListWidget#Sidebar::item {{
    padding: 5px 8px;
    border: none;
    border-radius: 4px;
    color: {p.text};
}}
QListWidget#Sidebar::item:hover    {{ background-color: {p.surface_alt}; }}
QListWidget#Sidebar::item:selected {{
    background-color: {p.selection};
    color: {p.text};
}}

/* ---- player ------------------------------------------------------ */
#PlayerInfoBar {{
    background-color: {p.surface};
    border-bottom: 1px solid {p.border};
}}
#ChannelTitle {{ font-size: 12pt; font-weight: 600; }}
#ChannelUrl   {{ color: {p.text_dim}; font-size: 8pt; }}
#PlayerMessage {{
    background-color: {p.surface};
    border-bottom: 1px solid {p.border};
    color: {p.danger};
    padding: 8px 12px;
}}

/* ---- forms ------------------------------------------------------- */
QLineEdit, QComboBox {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: 4px;
    padding: 5px 7px;
    selection-background-color: {p.accent};
    selection-color: {p.accent_text};
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {p.accent}; }}
QLineEdit:disabled {{ color: {p.text_dim}; background-color: {p.surface_alt}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{
    /* The windows11 style's own arrow disappears once we restyle the box, so
       draw a simple chevron from a border triangle instead. */
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {p.text_dim};
    width: 0; height: 0;
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    selection-background-color: {p.selection};
    selection-color: {p.text};
}}

QPushButton {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: 4px;
    padding: 6px 16px;
}}
QPushButton:hover    {{ background-color: {p.surface_alt}; }}
QPushButton:pressed  {{ background-color: {p.border}; }}
QPushButton:disabled {{ color: {p.text_dim}; }}
QPushButton[accent="true"] {{
    background-color: {p.accent};
    color: {p.accent_text};
    border-color: {p.accent};
    font-weight: 600;
}}
QPushButton[accent="true"]:hover {{ background-color: {p.accent}; }}
QPushButton[danger="true"] {{ color: {p.danger}; }}

QLabel[dim="true"]     {{ color: {p.text_dim}; }}
QLabel[heading="true"]  {{ font-size: 12pt; font-weight: 600; }}
QLabel[season="true"]   {{ font-size: 13pt; font-weight: bold; }}

/* ---- misc -------------------------------------------------------- */
QScrollArea, QScrollArea > QWidget > QWidget {{ background-color: {p.window}; }}
QScrollBar:vertical   {{ background: transparent; width: 11px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {p.border}; border-radius: 5px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {p.text_dim}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 0; }}
QScrollBar::handle:horizontal {{
    background: {p.border}; border-radius: 5px; min-width: 28px;
}}

QMenu {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    padding: 4px;
}}
QMenu::item {{ padding: 6px 26px 6px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background-color: {p.selection}; color: {p.text}; }}
QMenu::item:disabled {{ color: {p.text_dim}; }}
QMenu::separator {{ height: 1px; background: {p.border}; margin: 4px 8px; }}

QToolTip {{
    background-color: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
    padding: 4px;
}}

#Separator {{ background-color: {p.border}; }}
"""
