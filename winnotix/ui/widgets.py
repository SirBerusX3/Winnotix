"""Shared widgets: header bar, status/playback bar, tiles, channel list.

These reproduce upstream's GtkHeaderBar (title + subtitle + three button
groups), its status bar with the playback strip, and the FlowBox tiles used for
categories and providers.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import icons
from .flow_layout import FlowLayout
from .logos import TV_LOGO_SIZE
from .theme import Palette


def separator(orientation: Qt.Orientation = Qt.Orientation.Horizontal) -> QFrame:
    line = QFrame()
    line.setObjectName("Separator")
    if orientation == Qt.Orientation.Horizontal:
        line.setFixedHeight(1)
    else:
        line.setFixedWidth(1)
    return line


def tool_button(icon_name: str, tooltip: str, palette: Palette,
                checkable: bool = False, size: int = 20) -> QToolButton:
    button = QToolButton()
    button.setIcon(icons.icon(icon_name, palette.icon, size))
    button.setIconSize(QSize(size, size))
    button.setToolTip(tooltip)
    button.setCheckable(checkable)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setAutoRaise(True)
    return button


class HeaderBar(QWidget):
    """GtkHeaderBar equivalent: back, title/subtitle, search, fullscreen, menu."""

    back_clicked = Signal()
    search_toggled = Signal(bool)
    search_changed = Signal(str)
    fullscreen_clicked = Signal()

    def __init__(self, palette: Palette, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("HeaderBar")
        self._palette = palette

        self.back_button = tool_button("back", "Go back", palette)
        self.back_button.clicked.connect(self.back_clicked)

        self.title_label = QLabel("Winnotix")
        self.title_label.setObjectName("HeaderTitle")
        self.subtitle_label = QLabel("Watch TV")
        self.subtitle_label.setObjectName("HeaderSubtitle")

        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(0)
        titles.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignHCenter)
        titles.addWidget(self.subtitle_label, 0, Qt.AlignmentFlag.AlignHCenter)

        self.search_button = tool_button("search", "Search (Ctrl+F)", palette, checkable=True)
        self.search_button.toggled.connect(self._on_search_toggled)

        self.fullscreen_button = tool_button("fullscreen", "Fullscreen (F11)", palette)
        self.fullscreen_button.clicked.connect(self.fullscreen_clicked)

        self.menu_button = tool_button("menu", "Main menu", palette)
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu = QMenu(self)
        self.menu_button.setMenu(self.menu)

        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("Search channels…")
        self.search_entry.setClearButtonEnabled(True)
        self.search_entry.textChanged.connect(self.search_changed)
        self.search_entry.hide()

        top = QHBoxLayout()
        top.setContentsMargins(8, 6, 8, 6)
        top.setSpacing(4)
        top.addWidget(self.back_button)
        top.addStretch(1)
        top.addLayout(titles)
        top.addStretch(1)
        top.addWidget(self.search_button)
        top.addWidget(self.fullscreen_button)
        top.addWidget(self.menu_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(top)
        layout.addWidget(self.search_entry)

    def _on_search_toggled(self, checked: bool) -> None:
        self.search_entry.setVisible(checked)
        if checked:
            self.search_entry.setFocus()
        else:
            self.search_entry.clear()
        self.search_toggled.emit(checked)

    def set_titles(self, title: str, subtitle: str = "") -> None:
        self.title_label.setText(title)
        self.subtitle_label.setText(subtitle)
        self.subtitle_label.setVisible(bool(subtitle))

    def add_menu_action(self, text: str, icon_name: str, shortcut: str,
                        handler) -> QAction:
        action = QAction(icons.icon(icon_name, self._palette.icon), text, self)
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(handler)
        self.menu.addAction(action)
        return action


class StatusBar(QWidget):
    """Upstream's status bar plus the 'Currently playing' strip."""

    show_clicked = Signal()
    pause_clicked = Signal()
    stop_clicked = Signal()

    def __init__(self, palette: Palette, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("StatusBar")

        self.status_label = QLabel("")
        self.status_label.setObjectName("StatusLabel")

        self.playing_prefix = QLabel("Currently playing:")
        self.playing_prefix.setProperty("dim", "true")
        self.playback_label = QLabel("")
        self.playback_label.setObjectName("PlaybackLabel")

        self.show_button = tool_button("forward", "Back to the player", palette, size=18)
        self.show_button.clicked.connect(self.show_clicked)
        self.pause_button = tool_button("pause", "Pause", palette, size=18)
        self.pause_button.clicked.connect(self.pause_clicked)
        self.stop_button = tool_button("stop", "Stop", palette, size=18)
        self.stop_button.clicked.connect(self.stop_clicked)

        self.playback_bar = QWidget()
        self.playback_bar.setObjectName("PlaybackBar")
        playback = QHBoxLayout(self.playback_bar)
        playback.setContentsMargins(0, 0, 0, 0)
        playback.setSpacing(4)
        playback.addWidget(self.playing_prefix)
        playback.addWidget(self.playback_label)
        playback.addWidget(separator(Qt.Orientation.Vertical))
        playback.addWidget(self.show_button)
        playback.addWidget(self.pause_button)
        playback.addWidget(self.stop_button)
        self.playback_bar.hide()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(10)
        layout.addWidget(self.status_label, 1)
        layout.addWidget(self.playback_bar, 0)

        self._palette = palette

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def set_playing(self, name: str | None) -> None:
        if name:
            self.playback_label.setText(name)
            self.playback_bar.show()
        else:
            self.playback_bar.hide()

    def set_paused(self, paused: bool) -> None:
        self.pause_button.setIcon(
            icons.icon("play" if paused else "pause", self._palette.icon, 18)
        )
        self.pause_button.setToolTip("Resume" if paused else "Pause")


class Tile(QPushButton):
    """A FlowBox child: an icon or badge row plus a label and a count."""

    def __init__(self, text: str, count: int | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Tile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        label = text if count is None else f"{text} ({count})"
        self.setText(label)
        self.setToolTip(label)
        self.setMinimumWidth(190)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


class FlowPage(QScrollArea):
    """A scrolling area whose content reflows, standing in for a GtkFlowBox."""

    def __init__(self, margin: int = 14, spacing: int = 10, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._host = QWidget()
        self.flow = FlowLayout(self._host, margin=margin, spacing=spacing)
        self.setWidget(self._host)

    def clear(self) -> None:
        while self.flow.count():
            item = self.flow.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def add(self, widget: QWidget) -> None:
        self.flow.addWidget(widget)


class ChannelList(QListWidget):
    """The channel sidebar.

    Upstream builds one GtkListBoxRow widget per channel, which is why large
    playlists are slow to open. This uses plain items with icons instead, so a
    1,800-channel list is created in one pass and stays responsive, and asks the
    logo cache only for rows that are actually visible.
    """

    channel_activated = Signal(object)
    logos_needed = Signal(list)

    def __init__(self, logo_cache, palette: Palette, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.logo_cache = logo_cache

        # Mirrors the stylesheet on the widget palette. Redundant while the
        # stylesheet is applied, but it keeps the list readable if it is ever
        # shown without one (tests, or a future style that ignores ::item rules).
        widget_palette = self.palette()
        widget_palette.setColor(QPalette.ColorRole.Base, QColor(palette.surface))
        widget_palette.setColor(QPalette.ColorRole.Text, QColor(palette.text))
        widget_palette.setColor(QPalette.ColorRole.Highlight, QColor(palette.selection))
        widget_palette.setColor(QPalette.ColorRole.HighlightedText, QColor(palette.text))
        self.setPalette(widget_palette)

        self.setIconSize(TV_LOGO_SIZE)
        self.setUniformItemSizes(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.itemActivated.connect(self._emit_channel)
        self.itemClicked.connect(self._emit_channel)
        self.verticalScrollBar().valueChanged.connect(self._request_visible_logos)
        self._by_path: dict[str, list[QListWidgetItem]] = {}
        logo_cache.logo_ready.connect(self._on_logo_ready)

    def set_channels(self, channels) -> None:
        self.clear()
        self._by_path.clear()
        placeholder = self.logo_cache.placeholder(TV_LOGO_SIZE)
        for channel in channels:
            if not channel.url:
                continue
            item = QListWidgetItem(channel.name or "Unnamed channel")
            item.setData(Qt.ItemDataRole.UserRole, channel)
            item.setToolTip(channel.name or "")
            pixmap = self.logo_cache.pixmap(channel.logo_path, TV_LOGO_SIZE)
            item.setIcon(pixmap if pixmap is not None else placeholder)
            self.addItem(item)
            if channel.logo_path:
                self._by_path.setdefault(channel.logo_path, []).append(item)
        self._request_visible_logos()

    def visible_count(self) -> int:
        return sum(1 for i in range(self.count()) if not self.item(i).isHidden())

    def filter(self, text: str) -> int:
        needle = text.strip().lower()
        for index in range(self.count()):
            item = self.item(index)
            item.setHidden(bool(needle) and needle not in item.text().lower())
        self._request_visible_logos()
        return self.visible_count()

    def _emit_channel(self, item: QListWidgetItem) -> None:
        channel = item.data(Qt.ItemDataRole.UserRole)
        if channel is not None:
            self.channel_activated.emit(channel)

    def _request_visible_logos(self, *_args) -> None:
        """Fetch logos only for rows on screen, plus a screenful of lookahead."""
        if self.count() == 0:
            return
        top = self.indexAt(self.viewport().rect().topLeft())
        first = top.row() if top.isValid() else 0
        last = first + 40
        for index in range(max(0, first - 5), min(self.count(), last)):
            item = self.item(index)
            if item.isHidden():
                continue
            channel = item.data(Qt.ItemDataRole.UserRole)
            if channel is not None:
                self.logo_cache.request(channel.logo, channel.logo_path)

    def _on_logo_ready(self, logo_path: str) -> None:
        pixmap = self.logo_cache.pixmap(logo_path, TV_LOGO_SIZE)
        if pixmap is None:
            return
        for item in self._by_path.get(logo_path, []):
            item.setIcon(pixmap)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._request_visible_logos()
