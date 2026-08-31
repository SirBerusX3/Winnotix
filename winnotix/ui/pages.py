"""The stack pages.

One class per page in upstream's GtkStack, keeping the same layout and the same
navigation relationships. Pages own their widgets and emit signals; MainWindow
owns the data and does the wiring, so no page reaches into another.

Written by hand rather than loaded from .ui files: upstream already resolves 86
widgets by name through builder.get_object() in a loop (hypnotix.py:177-272),
an indirection that exists only to work around Glade. Reproducing it in Qt would
import the awkwardness without the benefit.
"""

from __future__ import annotations

from collections import Counter
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..core import catalogue, countries
from ..core.common import MOVIES_GROUP, SERIES_GROUP, TV_GROUP
from ..core.paths import resources_dir
from . import icons
from .logos import POSTER_SIZE
from .theme import Palette
from .video_widget import VideoWidget
from .widgets import ChannelList, FlowPage, Tile, separator, tool_button

PROVIDER_TYPE_URL = "url"
PROVIDER_TYPE_LOCAL = "local"
PROVIDER_TYPE_XTREAM = "xtream"

PROVIDER_TYPES = [
    (PROVIDER_TYPE_URL, "M3U URL"),
    (PROVIDER_TYPE_LOCAL, "Local M3U File"),
    (PROVIDER_TYPE_XTREAM, "Xtream API"),
]


# Forms read badly stretched across a 1200px window; upstream's Glade grids are
# similarly constrained by their container.
FORM_WIDTH = 620


def _form_body(*sections) -> QWidget:
    """Stack layouts into one width-limited, centred column."""
    inner = QVBoxLayout()
    inner.setContentsMargins(0, 0, 0, 0)
    inner.setSpacing(12)
    for section in sections:
        if isinstance(section, QWidget):
            inner.addWidget(section)
        else:
            inner.addLayout(section)
    body = QWidget()
    body.setLayout(inner)
    body.setMaximumWidth(FORM_WIDTH)
    return body


@lru_cache(maxsize=512)
def svg_file_pixmap(path: str | None, size: int) -> QPixmap:
    """Render an SVG file at `size`, DPI-aware. Cached; flags repeat a lot."""
    pixmap = QPixmap(int(size * 2), int(size * 2))
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(Qt.GlobalColor.transparent)
    if path and Path(path).is_file():
        renderer = QSvgRenderer(str(path))
        # Without an explicit target rect, render() uses the SVG's default size
        # and draws into the corner at the wrong scale.
        renderer.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer.render(painter, QRectF(0.0, 0.0, float(size), float(size)))
        painter.end()
    return pixmap


def svg_pixmap(name: str, size: int) -> QPixmap:
    """Render one of the bundled pictures/ SVGs."""
    return svg_file_pixmap(str(resources_dir() / "pictures" / name), size)


class LandingPage(QWidget):
    """Provider name, four quick actions, and the TV / Movies / Series tiles."""

    tv_clicked = Signal()
    movies_clicked = Signal()
    series_clicked = Signal()
    favorites_clicked = Signal()
    preferences_clicked = Signal()
    providers_clicked = Signal()
    new_channel_clicked = Signal()

    def __init__(self, palette: Palette, parent=None) -> None:
        super().__init__(parent)

        self.provider_label = QLabel("No provider selected")
        self.provider_label.setObjectName("ProviderName")

        actions = QHBoxLayout()
        actions.setSpacing(4)
        for icon_name, tip, signal in (
            ("plus", "Add a channel to favourites", self.new_channel_clicked),
            ("star", "Favourites", self.favorites_clicked),
            ("preferences", "Preferences", self.preferences_clicked),
            ("providers", "Manage providers", self.providers_clicked),
        ):
            button = tool_button(icon_name, tip, palette)
            button.clicked.connect(signal)
            actions.addWidget(button)

        header = QHBoxLayout()
        header.addWidget(self.provider_label)
        header.addStretch(1)
        header.addLayout(actions)

        self.tv_button = self._tile("tv.svg", "TV Channels (0)", self.tv_clicked)
        self.movies_button = self._tile("movies.svg", "Movies (0)", self.movies_clicked)
        self.series_button = self._tile("series.svg", "Series (0)", self.series_clicked)

        tiles = QHBoxLayout()
        tiles.setSpacing(18)
        tiles.addStretch(1)
        for button in (self.tv_button, self.movies_button, self.series_button):
            tiles.addWidget(button)
        tiles.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 22)
        layout.addLayout(header)
        layout.addStretch(1)
        layout.addLayout(tiles)
        layout.addStretch(2)

    def _tile(self, svg: str, text: str, signal) -> QPushButton:
        # A QPushButton does not adopt a child layout's size hint, so the tile is
        # sized explicitly; otherwise it collapses and clips its own label.
        button = QPushButton()
        button.setObjectName("LandingTile")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedSize(QSize(228, 244))
        button.clicked.connect(signal)

        image = QLabel()
        image.setPixmap(svg_pixmap(svg, 132))
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        inner = QVBoxLayout(button)
        inner.setContentsMargins(14, 18, 14, 18)
        inner.setSpacing(14)
        inner.addWidget(image, 1)
        inner.addWidget(label, 0)
        button.label = label
        return button

    def update_provider(self, provider) -> None:
        if provider is None:
            self.provider_label.setText("No provider selected")
            counts = (0, 0, 0)
        else:
            self.provider_label.setText(provider.name)
            counts = (len(provider.channels), len(provider.movies), len(provider.series))

        for button, text, count in (
            (self.tv_button, "TV Channels", counts[0]),
            (self.movies_button, "Movies", counts[1]),
            (self.series_button, "Series", counts[2]),
        ):
            button.label.setText(f"{text} ({count})")
            button.setEnabled(count > 0)


class CategoriesPage(FlowPage):
    """Groups for the current content type."""

    category_clicked = Signal(object)  # Group, or None for "all"

    def show_groups(self, provider, content_type: int) -> bool:
        self.clear()
        found = False
        for group in provider.groups:
            if group.group_type != content_type:
                continue
            found = True
            if content_type == TV_GROUP:
                label, count = group.name, len(group.channels)
            elif content_type == MOVIES_GROUP:
                label, count = _remove_word("VOD", group.name), len(group.channels)
            else:
                label, count = _remove_word("SERIES", group.name), len(group.series)
            tile = Tile(
                label,
                count,
                flag=countries.flag_file(countries.code_for_group(group)),
                badges=[countries.badge_file(w)
                        for w in countries.badges_for_group(group.name)],
            )
            tile.clicked.connect(lambda _checked=False, g=group: self.category_clicked.emit(g))
            self.add(tile)
        return found


def _remove_word(word: str, text: str) -> str:
    """Upstream strips the VOD/SERIES marker from group names before display."""
    return " ".join(part for part in text.split() if part != word).strip() or text


class ChannelsPage(QWidget):
    """Channel sidebar beside the player, matching upstream's channels_page."""

    channel_activated = Signal(object)
    favorite_toggled = Signal(bool)

    def __init__(self, palette: Palette, logo_cache, parent=None) -> None:
        super().__init__(parent)
        self._palette = palette

        self.channel_list = ChannelList(logo_cache, palette)
        self.channel_list.setMinimumWidth(210)
        self.channel_list.channel_activated.connect(self.channel_activated)

        self.name_label = QLabel("")
        self.name_label.setObjectName("ChannelTitle")
        self.url_label = QLabel("")
        self.url_label.setObjectName("ChannelUrl")
        self.url_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self.favorite_button = tool_button("star_outline", "Add to favourites", palette,
                                           checkable=True)
        self.favorite_button.toggled.connect(self._on_favorite_toggled)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(self.name_label)
        titles.addWidget(self.url_label)

        info_bar = QWidget()
        info_bar.setObjectName("PlayerInfoBar")
        info_layout = QHBoxLayout(info_bar)
        info_layout.setContentsMargins(12, 8, 12, 8)
        info_layout.addLayout(titles, 1)
        info_layout.addWidget(self.favorite_button)
        self.info_bar = info_bar

        # A failed stream leaves a black video area and nothing else, so the
        # reason is shown over it rather than only in the status bar.
        self.message_label = QLabel("")
        self.message_label.setObjectName("PlayerMessage")
        self.message_label.setWordWrap(True)
        self.message_label.hide()

        self.video = VideoWidget()

        player = QWidget()
        player_layout = QVBoxLayout(player)
        player_layout.setContentsMargins(0, 0, 0, 0)
        player_layout.setSpacing(0)
        player_layout.addWidget(info_bar)
        player_layout.addWidget(self.message_label)
        player_layout.addWidget(self.video, 1)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.channel_list)
        self.splitter.addWidget(player)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([250, 900])

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

    def _on_favorite_toggled(self, checked: bool) -> None:
        self.favorite_button.setIcon(
            icons.icon("star" if checked else "star_outline", self._palette.icon)
        )
        self.favorite_button.setToolTip(
            "Remove from favourites" if checked else "Add to favourites"
        )
        self.favorite_toggled.emit(checked)

    def set_favorite(self, is_favorite: bool) -> None:
        """Set the toggle without emitting favorite_toggled."""
        self.favorite_button.blockSignals(True)
        self.favorite_button.setChecked(is_favorite)
        self.favorite_button.setIcon(
            icons.icon("star" if is_favorite else "star_outline", self._palette.icon)
        )
        self.favorite_button.blockSignals(False)

    def show_message(self, text: str) -> None:
        self.message_label.setText(text)
        self.message_label.setVisible(bool(text))

    def clear_message(self) -> None:
        self.message_label.clear()
        self.message_label.hide()

    def set_channel(self, channel) -> None:
        self.name_label.setText(channel.name or "")
        self.url_label.setText(channel.url or "")

    def set_sidebar_visible(self, visible: bool) -> None:
        self.channel_list.setVisible(visible)


class VodPage(FlowPage):
    """Movie or series posters."""

    item_clicked = Signal(object)

    def __init__(self, logo_cache, parent=None) -> None:
        super().__init__(margin=14, spacing=12, parent=parent)
        self.logo_cache = logo_cache
        self._tiles: dict[str, list[QPushButton]] = {}
        logo_cache.logo_ready.connect(self._on_logo_ready)

    def show_items(self, items) -> None:
        self.clear()
        self._tiles.clear()
        for item in items:
            self.add(self._poster(item))

    def _poster(self, item) -> QPushButton:
        button = QPushButton()
        button.setObjectName("Tile")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedSize(QSize(180, 230))
        button.clicked.connect(lambda _checked=False, i=item: self.item_clicked.emit(i))

        image = QLabel()
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image.setFixedHeight(150)
        pixmap = self.logo_cache.pixmap(item.logo_path, POSTER_SIZE)
        image.setPixmap(pixmap if pixmap is not None
                        else self.logo_cache.placeholder(POSTER_SIZE))

        label = QLabel(item.name or "")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        button.setToolTip(item.name or "")

        layout = QVBoxLayout(button)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(image)
        layout.addWidget(label, 1)

        if item.logo_path:
            button.image_label = image
            self._tiles.setdefault(item.logo_path, []).append(button)
            self.logo_cache.request(item.logo, item.logo_path)
        return button

    def _on_logo_ready(self, logo_path: str) -> None:
        pixmap = self.logo_cache.pixmap(logo_path, POSTER_SIZE)
        if pixmap is None:
            return
        for button in self._tiles.get(logo_path, []):
            try:
                button.image_label.setPixmap(pixmap)
            except RuntimeError:
                pass  # tile was cleared while the download was in flight


def _number_key(value):
    """Sort '2' before '10' -- season and episode keys are numeric strings."""
    text = str(value).strip()
    return (0, int(text), "") if text.isdigit() else (1, 0, text.lower())


class EpisodesPage(QScrollArea):
    """Seasons, each with its episodes, for one series."""

    episode_clicked = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._host = QWidget()
        self._layout = QVBoxLayout(self._host)
        self._layout.setContentsMargins(16, 16, 16, 16)
        self._layout.setSpacing(10)
        self.setWidget(self._host)

    def show_serie(self, serie) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        for season_name in sorted(serie.seasons, key=_number_key):
            season = serie.seasons[season_name]
            # Upstream labels every season "Season %s" % key (hypnotix.py:597).
            # That reads right for the M3U path, whose keys are numbers, but an
            # Xtream panel names its own seasons -- and some of those names are
            # not numbers at all ("Specials"), so a name is used when there is one.
            label = str(getattr(season, "name", "") or season_name)
            heading = QLabel(f"Season {label}" if label.isdigit() else label)
            heading.setProperty("season", "true")
            self._layout.addWidget(heading)

            row_host = QWidget()
            flow = FlowPage(margin=0, spacing=8)
            for episode_name in sorted(season.episodes, key=_number_key):
                episode = season.episodes[episode_name]
                tile = Tile(f"Episode {episode_name}")
                # Upstream's tooltip is the dict key, which for it was the
                # episode's title. Ours is the number, so show the real title.
                title = str(getattr(episode, "title", "") or "").strip()
                if title:
                    tile.setToolTip(title)
                tile.clicked.connect(
                    lambda _checked=False, e=episode: self.episode_clicked.emit(e)
                )
                flow.add(tile)
            flow.setMinimumHeight(64)
            inner = QVBoxLayout(row_host)
            inner.setContentsMargins(0, 0, 0, 0)
            inner.addWidget(flow)
            self._layout.addWidget(row_host)

        self._layout.addStretch(1)


class ProvidersPage(QWidget):
    """Provider list with add / reset actions."""

    provider_activated = Signal(object)
    provider_edit = Signal(object)
    provider_delete = Signal(object)
    add_clicked = Signal()
    browse_clicked = Signal()
    reset_clicked = Signal()

    def __init__(self, palette: Palette, parent=None) -> None:
        super().__init__(parent)
        self._palette = palette
        self.flow_page = FlowPage()

        browse_button = QPushButton("  Browse country playlists…")
        browse_button.setIcon(icons.icon("providers", palette.icon))
        browse_button.clicked.connect(self.browse_clicked)

        add_button = QPushButton("  Add a new provider…")
        add_button.setIcon(icons.icon("plus", palette.icon))
        add_button.clicked.connect(self.add_clicked)

        reset_button = QPushButton("  Reset to defaults…")
        reset_button.setIcon(icons.icon("reset", palette.icon))
        reset_button.clicked.connect(self.reset_clicked)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(14, 8, 14, 10)
        buttons.addStretch(1)
        buttons.addWidget(browse_button)
        buttons.addWidget(add_button)
        buttons.addWidget(reset_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.flow_page, 1)
        layout.addWidget(separator())
        layout.addLayout(buttons)

    def show_providers(self, providers, active_name: str) -> None:
        self.flow_page.clear()
        for provider in providers:
            card = QWidget()
            card.setObjectName("Tile")
            card.setFixedWidth(260)

            name = QPushButton(provider.name)
            name.setFlat(True)
            name.setCursor(Qt.CursorShape.PointingHandCursor)
            name.setStyleSheet("text-align: left; border: none; padding: 2px;")
            if provider.name == active_name:
                name.setText(f"{provider.name}  ✓")
            name.clicked.connect(
                lambda _checked=False, p=provider: self.provider_activated.emit(p)
            )

            edit = tool_button("preferences", "Edit", self._palette, size=16)
            edit.clicked.connect(
                lambda _checked=False, p=provider: self.provider_edit.emit(p)
            )
            delete = tool_button("close", "Delete", self._palette, size=16)
            delete.clicked.connect(
                lambda _checked=False, p=provider: self.provider_delete.emit(p)
            )

            row = QHBoxLayout(card)
            row.setContentsMargins(10, 6, 6, 6)
            row.addWidget(name, 1)
            row.addWidget(edit)
            row.addWidget(delete)
            self.flow_page.add(card)


class CataloguePage(QWidget):
    """Pick a per-country playlist, from any source Winnotix has an index for.

    Two are bundled: Free-TV (~96 playlists) and the much larger iptv-org (186).
    A country usually appears in both, so the source filter exists to make which
    is which obvious; entries are otherwise laid out in one flow, grouped by
    source. Each source's whole-world playlist is offered first.

    Choosing an entry just creates an ordinary provider pointing at that
    playlist's URL, so nothing about it is special afterwards.
    """

    entry_chosen = Signal(object)   # CatalogueEntry
    cancelled = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._entries = catalogue.load()

        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("Filter by country name or code…")
        self.search_entry.setClearButtonEnabled(True)
        self.search_entry.textChanged.connect(self._repopulate)

        self.source_combo = QComboBox()
        self.source_combo.addItem("All sources", None)
        for label in catalogue.sources():
            self.source_combo.addItem(label, label)
        self.source_combo.currentIndexChanged.connect(
            lambda _index: self._repopulate(self.search_entry.text())
        )

        self.summary = QLabel("")
        self.summary.setProperty("dim", "true")

        top = QHBoxLayout()
        top.setContentsMargins(14, 12, 14, 6)
        top.addWidget(self.search_entry, 1)
        top.addWidget(QLabel("Source:"))
        top.addWidget(self.source_combo)

        self.flow_page = FlowPage()

        back_button = QPushButton("Back")
        back_button.clicked.connect(self.cancelled)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(14, 6, 14, 10)
        bottom.addWidget(self.summary, 1)
        bottom.addWidget(back_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(top)
        layout.addWidget(self.flow_page, 1)
        layout.addWidget(separator())
        layout.addLayout(bottom)

        self._repopulate("")

    def reset(self) -> None:
        self.search_entry.clear()
        self._repopulate("")
        self.search_entry.setFocus()

    @property
    def selected_source(self) -> str | None:
        return self.source_combo.currentData()

    def _repopulate(self, term: str) -> None:
        self.flow_page.clear()
        matches = catalogue.order(
            catalogue.search(term, self._entries, source=self.selected_source)
        )
        for entry in matches:
            tile = Tile(
                entry.name,
                entry.channels,
                flag=countries.flag_file(entry.code),
            )
            # The name alone does not say which source a tile came from, and the
            # same country is usually in both.
            tile.setToolTip(f"{entry.provider_name} — {entry.channels} channels")
            tile.clicked.connect(
                lambda _checked=False, e=entry: self.entry_chosen.emit(e)
            )
            self.flow_page.add(tile)

        self.summary.setText(self._summary(term, matches))

    def _summary(self, term: str, matches: list) -> str:
        if not self._entries:
            return "No catalogue bundled — run the tools/generate_*_catalogue.py scripts."
        pool = [e for e in self._entries
                if not self.selected_source or e.source == self.selected_source]
        if term:
            return f"{len(matches)} of {len(pool)} playlists"
        counts = Counter(e.source for e in pool)
        breakdown = " + ".join(f"{n} {source}" for source, n in counts.items())
        total = sum(e.channels for e in pool)
        return f"{breakdown} — {total} channels in total"


class ProviderEditPage(QWidget):
    """Add or edit a provider — upstream's add_page."""

    accepted = Signal(dict)
    cancelled = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.name_entry = QLineEdit()
        self.type_combo = QComboBox()
        for type_id, label in PROVIDER_TYPES:
            self.type_combo.addItem(label, type_id)
        self.type_combo.currentIndexChanged.connect(self._update_visibility)

        self.url_entry = QLineEdit()
        self.path_entry = QLineEdit()
        self.browse_button = QPushButton("Browse…")
        self.browse_button.clicked.connect(self._browse)
        self.username_entry = QLineEdit()
        self.password_entry = QLineEdit()
        self.password_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.epg_entry = QLineEdit()

        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.addWidget(self.path_entry, 1)
        path_row.addWidget(self.browse_button)
        path_host = QWidget()
        path_host.setLayout(path_row)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("Name:", self.name_entry)
        form.addRow("Type:", self.type_combo)
        self.url_label = QLabel("URL:")
        form.addRow(self.url_label, self.url_entry)
        self.path_label = QLabel("Path:")
        form.addRow(self.path_label, path_host)
        self.username_label = QLabel("Username:")
        form.addRow(self.username_label, self.username_entry)
        self.password_label = QLabel("Password:")
        form.addRow(self.password_label, self.password_entry)
        self.epg_label = QLabel("EPG:")
        form.addRow(self.epg_label, self.epg_entry)

        self.ok_button = QPushButton("OK")
        self.ok_button.setProperty("accent", "true")
        self.ok_button.clicked.connect(self._accept)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.cancelled)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(self.ok_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 24, 30, 24)
        layout.addWidget(_form_body(form, buttons), 0,
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        layout.addStretch(1)

        self._path_host = path_host
        self._update_visibility()

    def _row_visible(self, label: QWidget, field: QWidget, visible: bool) -> None:
        label.setVisible(visible)
        field.setVisible(visible)

    def _update_visibility(self) -> None:
        type_id = self.type_combo.currentData()
        self._row_visible(self.url_label, self.url_entry, type_id != PROVIDER_TYPE_LOCAL)
        self._row_visible(self.path_label, self._path_host, type_id == PROVIDER_TYPE_LOCAL)
        is_xtream = type_id == PROVIDER_TYPE_XTREAM
        self._row_visible(self.username_label, self.username_entry, is_xtream)
        self._row_visible(self.password_label, self.password_entry, is_xtream)
        self._row_visible(self.epg_label, self.epg_entry, not is_xtream)

    def _browse(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "Open an M3U playlist", "", "M3U playlists (*.m3u *.m3u8);;All files (*)"
        )
        if path:
            self.path_entry.setText(path)

    def load(self, provider=None) -> None:
        """Populate for editing, or clear for a new provider."""
        if provider is None:
            self.name_entry.clear()
            self.type_combo.setCurrentIndex(0)
            for entry in (self.url_entry, self.path_entry, self.username_entry,
                          self.password_entry, self.epg_entry):
                entry.clear()
        else:
            self.name_entry.setText(provider.name)
            index = self.type_combo.findData(provider.type_id)
            self.type_combo.setCurrentIndex(max(0, index))
            if provider.type_id == PROVIDER_TYPE_LOCAL:
                self.path_entry.setText(provider.url)
                self.url_entry.clear()
            else:
                self.url_entry.setText(provider.url)
                self.path_entry.clear()
            self.username_entry.setText(provider.username)
            self.password_entry.setText(provider.password)
            self.epg_entry.setText(provider.epg)
        self._update_visibility()
        self.name_entry.setFocus()

    def _accept(self) -> None:
        type_id = self.type_combo.currentData()
        url = self.path_entry.text() if type_id == PROVIDER_TYPE_LOCAL else self.url_entry.text()
        self.accepted.emit({
            "name": self.name_entry.text().strip(),
            "type_id": type_id,
            "url": url.strip(),
            "username": self.username_entry.text().strip(),
            "password": self.password_entry.text().strip(),
            "epg": self.epg_entry.text().strip(),
        })


class ConfirmPage(QWidget):
    """Shared by upstream's delete_page and reset_page."""

    confirmed = Signal()
    cancelled = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.message = QLabel("")
        self.message.setProperty("heading", "true")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)

        no_button = QPushButton("No")
        no_button.clicked.connect(self.cancelled)
        self.yes_button = QPushButton("Yes")
        self.yes_button.setProperty("danger", "true")
        self.yes_button.clicked.connect(self.confirmed)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(no_button)
        buttons.addWidget(self.yes_button)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addStretch(1)
        layout.addWidget(self.message)
        layout.addSpacing(18)
        layout.addLayout(buttons)
        layout.addStretch(2)

    def ask(self, message: str) -> None:
        self.message.setText(message)


class NewChannelPage(QWidget):
    """Add a channel straight to favourites — upstream's new_channel_page."""

    accepted = Signal(dict)
    cancelled = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.name_entry = QLineEdit()
        self.url_entry = QLineEdit()
        self.logo_entry = QLineEdit()

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("Name:", self.name_entry)
        form.addRow("URL:", self.url_entry)
        form.addRow("Logo URL:", self.logo_entry)

        note = QLabel(
            "This channel will be added to your favourites.\n"
            "Note: if the logo is a local file, upload it somewhere and use its URL."
        )
        note.setProperty("dim", "true")
        note.setWordWrap(True)

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.cancelled)
        ok_button = QPushButton("OK")
        ok_button.setProperty("accent", "true")
        ok_button.clicked.connect(self._accept)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(ok_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 24, 30, 24)
        layout.addWidget(_form_body(form, note, buttons), 0,
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        layout.addStretch(1)

    def clear(self) -> None:
        for entry in (self.name_entry, self.url_entry, self.logo_entry):
            entry.clear()
        self.name_entry.setFocus()

    def _accept(self) -> None:
        self.accepted.emit({
            "name": self.name_entry.text().strip(),
            "url": self.url_entry.text().strip(),
            "logo": self.logo_entry.text().strip(),
        })


class PreferencesPage(QScrollArea):
    """User agent, referer, mpv options and yt-dlp."""

    setting_changed = Signal(str, str)
    bool_setting_changed = Signal(str, bool)
    ytdlp_update_clicked = Signal()

    def __init__(self, settings, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.settings = settings

        host = QWidget()
        outer = QVBoxLayout(host)
        outer.setContentsMargins(30, 24, 30, 24)
        column = QWidget()
        column.setMaximumWidth(FORM_WIDTH)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        outer.addWidget(column, 0,
                        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        outer.addStretch(1)

        self.useragent_entry = QLineEdit(settings.get_string("user-agent"))
        self.referer_entry = QLineEdit(settings.get_string("http-referer"))
        self.mpv_entry = QLineEdit(settings.get_string("mpv-options"))

        for key, entry in (
            ("user-agent", self.useragent_entry),
            ("http-referer", self.referer_entry),
            ("mpv-options", self.mpv_entry),
        ):
            entry.textChanged.connect(
                lambda text, k=key: self.setting_changed.emit(k, text)
            )

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("User agent:", self.useragent_entry)
        form.addRow("HTTP referer:", self.referer_entry)
        form.addRow("MPV options:", self.mpv_entry)

        mpv_hint = QLabel("Space-separated key=value pairs, e.g. hwdec=auto-safe osc=no")
        mpv_hint.setProperty("dim", "true")

        playlist_heading = QLabel("Playlists")
        playlist_heading.setProperty("heading", "true")

        self.hide_unplayable_check = QCheckBox("Hide channels known to be unplayable")
        self.hide_unplayable_check.setChecked(settings.get_boolean("hide-unplayable"))
        self.hide_unplayable_check.toggled.connect(
            lambda checked: self.bool_setting_changed.emit("hide-unplayable", checked)
        )
        hide_hint = QLabel(
            "Some streams answer normally but play a filler clip instead of the "
            "channel — a takedown notice or a “watch on our website” slate. These "
            "cannot be detected from the playlist, so they are listed by rule in "
            "resources/blocklist.json. Add your own rules in blocklist.json inside "
            "the Winnotix data folder."
        )
        hide_hint.setProperty("dim", "true")
        hide_hint.setWordWrap(True)

        self.hide_adult_check = QCheckBox("Hide adult channels (Xtream providers)")
        self.hide_adult_check.setChecked(settings.get_boolean("hide-adult-content"))
        self.hide_adult_check.toggled.connect(
            lambda checked: self.bool_setting_changed.emit("hide-adult-content", checked)
        )
        adult_hint = QLabel(
            "Applies to live channels an Xtream provider marks as adult. M3U "
            "playlists carry no such marking, so this does nothing for them."
        )
        adult_hint.setProperty("dim", "true")
        adult_hint.setWordWrap(True)

        logo_heading = QLabel("Channel logos")
        logo_heading.setProperty("heading", "true")

        self.logo_proxy_check = QCheckBox("Load blocked logos through an image proxy")
        self.logo_proxy_check.setChecked(settings.get_boolean("proxy-blocked-logos"))
        self.logo_proxy_check.toggled.connect(
            lambda checked: self.bool_setting_changed.emit("proxy-blocked-logos", checked)
        )
        logo_hint = QLabel(
            "Most playlists host their logos on imgur, which serves nothing to "
            "the United Kingdom — 71% of Free-TV's channels and 54% of "
            "iptv-org's. When a host refuses a logo, Winnotix asks DuckDuckGo's "
            "image proxy to fetch it instead, which it does from its own servers "
            "rather than yours. Only the logo address is sent, and only after a "
            "direct request has already failed. Turn this off to make Winnotix "
            "talk to nobody but the playlist's own hosts."
        )
        logo_hint.setProperty("dim", "true")
        logo_hint.setWordWrap(True)

        heading = QLabel("yt-dlp")
        heading.setProperty("heading", "true")
        ytdlp_hint = QLabel(
            "yt-dlp lets mpv play streams that need extraction, such as YouTube. "
            "Direct HLS and M3U8 streams do not need it."
        )
        ytdlp_hint.setProperty("dim", "true")
        ytdlp_hint.setWordWrap(True)

        self.ytdlp_system_label = QLabel("Checking…")
        self.ytdlp_system_label.setProperty("dim", "true")
        self.ytdlp_local_label = QLabel("Checking…")
        self.ytdlp_local_label.setProperty("dim", "true")

        self.ytdlp_local_check = QCheckBox("Use the copy Winnotix downloads")
        self.ytdlp_local_check.setChecked(settings.get_boolean("use-local-ytdlp"))
        self.ytdlp_local_check.toggled.connect(
            lambda checked: self.bool_setting_changed.emit("use-local-ytdlp", checked)
        )

        self.ytdlp_button = QPushButton("Download")
        self.ytdlp_button.clicked.connect(self.ytdlp_update_clicked)
        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.addWidget(self.ytdlp_button)
        button_row.addStretch(1)
        self.ytdlp_buttons = QWidget()
        self.ytdlp_buttons.setLayout(button_row)

        layout.addLayout(form)
        layout.addWidget(mpv_hint)
        layout.addSpacing(10)
        layout.addWidget(separator())
        layout.addWidget(playlist_heading)
        layout.addWidget(self.hide_unplayable_check)
        layout.addWidget(hide_hint)
        layout.addSpacing(6)
        layout.addWidget(self.hide_adult_check)
        layout.addWidget(adult_hint)
        layout.addSpacing(10)
        layout.addWidget(separator())
        layout.addWidget(logo_heading)
        layout.addWidget(self.logo_proxy_check)
        layout.addWidget(logo_hint)
        layout.addSpacing(10)
        layout.addWidget(separator())
        layout.addWidget(heading)
        layout.addWidget(ytdlp_hint)
        layout.addSpacing(6)
        layout.addWidget(self.ytdlp_system_label)
        layout.addWidget(self.ytdlp_local_label)
        layout.addSpacing(6)
        layout.addWidget(self.ytdlp_local_check)
        layout.addWidget(self.ytdlp_buttons)
        layout.addStretch(1)
        self.setWidget(host)

    # -- yt-dlp panel --------------------------------------------------

    def set_ytdlp_versions(self, system: str | None, local: str | None) -> None:
        """Report both copies, and name which button action now makes sense."""
        self.ytdlp_system_label.setText(
            f"On your system: {system}" if system else
            "On your system: not installed"
        )
        self.ytdlp_local_label.setText(
            f"Downloaded by Winnotix: {local}" if local else
            "Downloaded by Winnotix: none yet"
        )
        self.ytdlp_button.setText("Update" if local else "Download")

    def set_ytdlp_busy(self, message: str | None) -> None:
        """Disable the button while a download runs, and say what is happening."""
        self.ytdlp_button.setEnabled(message is None)
        if message is not None:
            self.ytdlp_local_label.setText(message)


class SpinnerPage(QWidget):
    """Shown while a provider is loading."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.label = QLabel("Loading…")
        self.label.setProperty("heading", "true")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail = QLabel("")
        self.detail.setProperty("dim", "true")
        self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.addStretch(1)
        layout.addWidget(self.label)
        layout.addWidget(self.detail)
        layout.addStretch(1)

    def set_message(self, message: str, detail: str = "") -> None:
        self.label.setText(message)
        self.detail.setText(detail)
