"""A native window for libmpv to render into.

Upstream hands mpv an X11 window id from a GtkDrawingArea (hypnotix.py:1639,
via the "realize" handler at hypnotix.py:276). The Windows equivalent is an HWND
from ``QWidget.winId()``.

The timing is the part that bites: a QWidget has no native handle until it is
shown, and requesting one early can cause Qt to recreate it later -- leaving mpv
drawing into a dead window (a black frame with audio playing). So the id is
published from ``showEvent``, which is the direct analogue of GTK's "realize".
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QWidget


class VideoWidget(QWidget):
    """Emits :attr:`wid_ready` once exactly, when the native handle exists."""

    wid_ready = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # WA_NativeWindow gives this widget its own HWND for mpv to target.
        # WA_DontCreateNativeAncestors stops Qt promoting the whole parent chain
        # to native windows, which costs performance and can break compositing.
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)

        # mpv paints this surface itself; letting Qt clear it too causes flicker.
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("black"))
        self.setPalette(palette)

        self.setMinimumSize(320, 180)
        self._wid: int | None = None

    @property
    def wid(self) -> int | None:
        return self._wid

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._wid is None:
            self._wid = int(self.winId())
            self.wid_ready.emit(self._wid)
