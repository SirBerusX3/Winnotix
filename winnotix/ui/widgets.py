"""Shared widgets: header bar, status/playback bar, tiles, channel list.

These reproduce upstream's GtkHeaderBar (title + subtitle + three button
groups), its status bar with the playback strip, and the FlowBox tiles used for
categories and providers.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QPalette
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
    """A FlowBox child: an optional flag and badges, then a label and a count.

    Upstream builds the same thing from a GtkBox of images plus a label
    (hypnotix.py:show_groups). A country flag is shown when the group resolves to
    one, and badges for language/genre words in its name.
    """

    def __init__(self, text: str, count: int | None = None,
                 flag: str | None = None, badges: list[str] | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Tile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        caption = text if count is None else f"{text} ({count})"
        self.setToolTip(caption)
        self.setMinimumWidth(190)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        icons_present = [p for p in ([flag] + list(badges or [])) if p]
        if not icons_present:
            # No artwork: let QPushButton lay the text out itself.
            self.setText(caption)
            return

        # Imported here rather than at module scope: pages imports widgets, so a
        # top-level import would be circular.
        from .pages import svg_file_pixmap

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 14, 8)
        row.setSpacing(6)
        for path in icons_present:
            image = QLabel()
            image.setPixmap(svg_file_pixmap(path, 18))
            image.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            row.addWidget(image)

        label = QLabel(caption)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row.addWidget(label, 1)
        self._has_layout = True

    def sizeHint(self) -> QSize:
        """Size to the content when we built our own layout.

        QPushButton does not adopt a child layout's size hint, so without this a
        long name like "Bosnia and Herzegovina" is clipped and loses its count.
        """
        if getattr(self, "_has_layout", False):
            hint = self.layout().sizeHint()
            return QSize(max(hint.width(), self.minimumWidth()), hint.height())
        return super().sizeHint()


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
        self._palette = palette

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

    #: Between a channel name and what is on it now.
    GUIDE_SEPARATOR = "   ·   "

    def apply_guide(self, lookup) -> int:
        """Show what is on now beside each row; returns how many matched.

        `lookup` takes a channel and returns (current, next) programmes, either
        of which may be None. A row with no listing is left exactly as it was:
        a guide covers a fraction of a public playlist, so a placeholder on
        every other row would be noise rather than information.

        The name is rebuilt from the channel each time rather than appended to,
        so refreshing on the hour cannot stack programmes onto a row.
        """
        matched = 0
        for index in range(self.count()):
            item = self.item(index)
            channel = item.data(Qt.ItemDataRole.UserRole)
            if channel is None:
                continue
            name = channel.name or "Unnamed channel"
            current, following = lookup(channel)
            if current is None:
                item.setText(name)
                item.setToolTip(name)
                continue
            matched += 1
            item.setText(f"{name}{self.GUIDE_SEPARATOR}{current.title}")
            tip = [name, f"Now    {current.when()}  {current.title}"]
            if following is not None:
                tip.append(f"Next   {following.when()}  {following.title}")
            item.setToolTip("\n".join(tip))
        return matched

    def channels(self) -> list:
        """The channels currently listed, in order."""
        found = []
        for index in range(self.count()):
            channel = self.item(index).data(Qt.ItemDataRole.UserRole)
            if channel is not None:
                found.append(channel)
        return found

    def apply_health(self, lookup) -> int:
        """Dim channels a check found dead, and say why when hovered.

        Dimmed, never hidden or removed. A check is one request at one moment,
        and a host that rate-limited us looks identical to one that died, so
        the row stays where it is and stays clickable -- the mark is a warning,
        not a verdict the user cannot overrule.

        `lookup` returns a health Result or None for "not checked".
        """
        marked = 0
        for index in range(self.count()):
            item = self.item(index)
            channel = item.data(Qt.ItemDataRole.UserRole)
            if channel is None:
                continue
            result = lookup(channel)
            if result is None or result.playable:
                item.setForeground(QBrush())        # back to the stylesheet colour
                continue
            marked += 1
            item.setForeground(QBrush(QColor(self._palette.text_dim)))
            detail = result.detail or "This channel did not respond."
            existing = item.toolTip() or (channel.name or "")
            item.setToolTip(f"{existing}\n\n{detail}")
        return marked

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
