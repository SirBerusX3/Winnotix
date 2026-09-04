"""Icon set.

Upstream draws its header and menu icons from XApp/Adwaita symbolic icon names
(`xsi-starred-symbolic`, `xsi-keyboard-shortcuts-symbolic`, ...). None of those
exist on Windows, and Qt's built-in standard pixmaps are a visually inconsistent
grab-bag, so the equivalents are drawn here instead.

They are stroke-based on a 24x24 grid, rendered at request time in whatever
colour the current theme asks for, so a single definition serves both light and
dark without shipping two sets of files.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from ..core.paths import resources_dir

#: The application mark, as opposed to the stroke icons below: a real file,
#: because it is artwork rather than a glyph. The .ico carries the whole 16..256
#: ladder, so Qt and Windows each take the size they want without rescaling.
#: Regenerate from assets/ with tools/generate_icons.py.
APP_ICON = "appicon.ico"

# Paths stroked with round caps/joins unless the entry is marked as filled.
_STROKE: dict[str, str] = {
    "back":             "M15 5 L8 12 L15 19",
    "forward":          "M9 5 L16 12 L9 19",
    "search":           "M11 5 A6 6 0 1 1 11 17 A6 6 0 1 1 11 5 M15.5 15.5 L20 20",
    "fullscreen":       "M4 9 V4 H9 M15 4 H20 V9 M20 15 V20 H15 M9 20 H4 V15",
    "fullscreen_exit":  "M9 4 V9 H4 M20 9 H15 V4 M15 20 V15 H20 M4 15 H9 V20",
    "menu":             "M4 7 H20 M4 12 H20 M4 17 H20",
    "plus":             "M12 5 V19 M5 12 H19",
    "reset":            "M20 12 A8 8 0 1 1 14.5 4.4 M20 4 V9 H15",
    "preferences":      "M4 7 H20 M4 12 H20 M4 17 H20 M9 4 V10 M15 9 V15 M9 14 V20",
    "providers":        "M4 5 H20 V9 H4 Z M4 11 H20 V15 H4 Z M4 17 H20 V21 H4 Z",
    # The header's theme button shows the theme it would switch *to*, so a sun
    # means "go light" and appears while the app is dark.
    "sun":              ("M12 7.5 A4.5 4.5 0 1 1 12 16.5 A4.5 4.5 0 1 1 12 7.5 "
                         "M12 2 V4 M12 20 V22 M2 12 H4 M20 12 H22 "
                         "M4.9 4.9 L6.4 6.4 M17.6 17.6 L19.1 19.1 "
                         "M19.1 4.9 L17.6 6.4 M6.4 17.6 L4.9 19.1"),
    "moon":             "M20.5 13.3 A8.5 8.5 0 1 1 10.7 3.5 A6.8 6.8 0 0 0 20.5 13.3 Z",
    "folder":           "M3 7 A1 1 0 0 1 4 6 H9 L11 8 H20 A1 1 0 0 1 21 9 V18 A1 1 0 0 1 20 19 H4 A1 1 0 0 1 3 18 Z",
    "info":             "M12 4 A8 8 0 1 1 12 20 A8 8 0 1 1 12 4 M12 11 V16 M12 8 V8.01",
    "keyboard":         "M3 7 H21 V17 H3 Z M7 11 H7.01 M11 11 H11.01 M15 11 H15.01 M8 14 H16",
    "exit":             "M14 5 H19 V19 H14 M11 8 L15 12 L11 16 M15 12 H4",
    "close":            "M6 6 L18 18 M18 6 L6 18",
    "tv":               "M4 7 H20 V18 H4 Z M8 3 L12 7 L16 3",
    "movies":           "M4 5 H20 V19 H4 Z M4 9 H20 M8 5 V9 M16 5 V9",
    "series":           "M4 4 H16 V16 H4 Z M8 8 H20 V20 H8 Z",
    "refresh":          "M20 12 A8 8 0 1 1 14.5 4.4 M20 4 V9 H15",
    "warning":          "M12 4 L21 19 H3 Z M12 10 V14 M12 17 V17.01",
}

_FILLED: dict[str, str] = {
    "play":  "M8 5 L19 12 L8 19 Z",
    "pause": "M8 5 H11 V19 H8 Z M13 5 H16 V19 H13 Z",
    "stop":  "M6 6 H18 V18 H6 Z",
    "star":  "M12 3.5 L14.6 9.2 L20.5 9.9 L16.1 14 L17.3 20 L12 17 L6.7 20 "
             "L7.9 14 L3.5 9.9 L9.4 9.2 Z",
}

# Outline variant of `star`, for the un-favourited state.
_STROKE["star_outline"] = _FILLED["star"]


def _svg(name: str, colour: str, width: float) -> bytes:
    if name in _FILLED and name != "star_outline":
        body = f'<path d="{_FILLED[name]}" fill="{colour}"/>'
    else:
        body = (
            f'<path d="{_STROKE[name]}" fill="none" stroke="{colour}" '
            f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"/>'
        )
    # width/height matter: without them QSvgRenderer.defaultSize() is unreliable,
    # and render() then draws at the wrong scale.
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="24" height="24" viewBox="0 0 24 24">{body}</svg>'
    ).encode("utf-8")


@lru_cache(maxsize=512)
def _pixmap(name: str, colour: str, size: int, width: float, dpr: float) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(_svg(name, colour, width)))
    pixmap = QPixmap(QSize(int(size * dpr), int(size * dpr)))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    # Always render into an explicit rect. The pixmap carries a devicePixelRatio,
    # so the painter's logical space is `size` square regardless of `dpr`.
    renderer.render(painter, QRectF(0.0, 0.0, float(size), float(size)))
    painter.end()
    return pixmap


def icon(name: str, colour: str = "#000000", size: int = 20, width: float = 1.8) -> QIcon:
    """Build a QIcon for `name` in `colour`.

    Results are cached, so calling this per-widget in a rebuild is cheap.
    """
    if name not in _STROKE and name not in _FILLED:
        raise KeyError(f"unknown icon: {name!r}")
    # 2.0 covers every display we care about; Qt downsamples cleanly for 1.0/1.25.
    return QIcon(_pixmap(name, colour, size, width, 2.0))


def available() -> list[str]:
    return sorted(set(_STROKE) | set(_FILLED))


@lru_cache(maxsize=1)
def app_icon() -> QIcon:
    """The Winnotix mark, for the window, the task bar, Alt-Tab and dialogs."""
    return QIcon(str(resources_dir() / APP_ICON))
