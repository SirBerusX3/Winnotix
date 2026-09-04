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
    QSlider,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..core import catalogue, countries, genres
from ..core.common import MOVIES_GROUP, SERIES_GROUP, TV_GROUP
from ..core.paths import resources_dir
from . import icons
from .flow_layout import SPANS_ROW
from .theme import THEME_CHOICES, Palette
from .video_widget import VideoWidget
from .widgets import (ChannelList, FlowPage, Tile, remember_icon, restyle_icons,
                      separator, tool_button)

# Poster tiles, and the space a poster actually gets inside one. A QLabel clips
# a pixmap wider than itself instead of shrinking it, and clips it centred, so
# an oversized poster loses both edges -- "Designated Survivor" rendered as
# "ESIGNAT / URVIVO". The scale target is therefore the tile width less the
# layout margins, derived here rather than named separately, so it cannot drift
# away from the tile again.
POSTER_TILE_SIZE = QSize(180, 230)
POSTER_TILE_MARGIN = 8
POSTER_IMAGE_HEIGHT = 150
POSTER_IMAGE_SIZE = QSize(
    POSTER_TILE_SIZE.width() - 2 * POSTER_TILE_MARGIN, POSTER_IMAGE_HEIGHT
)

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

    def retheme(self, palette: Palette) -> None:
        restyle_icons(self, palette)

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
            counts = (len(provider.channels), len(provider.movies),
                      genres.series_total(provider))

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
                # A routed group holds Channels, not Serie objects -- see
                # core/genres.py for why they are not pushed into provider.series.
                label = _remove_word("SERIES", group.name)
                count = len(group.series) or len(group.channels)
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

        # Sits above the list rather than behind a toggle in the header. A
        # country list runs to hundreds of rows -- iptv-org's UK is 310 -- and
        # a filter nobody knows about is one nobody uses. Ctrl+F still focuses
        # it, but finding it no longer depends on knowing the shortcut.
        self.channel_search = QLineEdit()
        self.channel_search.setPlaceholderText("Filter channels…")
        self.channel_search.setClearButtonEnabled(True)

        # Off by default, and hidden entirely with one provider, where it would
        # be a switch between a list and the same list.
        self.search_all_check = QCheckBox("Search all providers")
        self.search_all_check.setToolTip(
            "Search the playlists already downloaded for your other providers.\n"
            "A provider you have never opened is not downloaded to do this."
        )
        self.search_all_check.hide()
        # Availability is tracked rather than read back off the widget:
        # isVisible() is false whenever this page is not the one on screen,
        # which would silently turn the feature off while it is in use.
        self._search_all_available = False

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

        self.sidebar = QWidget()
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(8, 8, 0, 0)
        sidebar_layout.setSpacing(6)
        sidebar_layout.addWidget(self.channel_search)
        sidebar_layout.addWidget(self.search_all_check)
        sidebar_layout.addWidget(self.channel_list, 1)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(player)
        self.splitter.setStretchFactor(1, 1)
        # The sidebar carries two things once a guide is loaded -- the channel
        # and what is on it now -- so it opens wider than the name alone needs.
        # Still a splitter: anyone who wants the video wider can drag it back.
        self.splitter.setSizes([340, 810])

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

    def _on_favorite_toggled(self, checked: bool) -> None:
        remember_icon(self.favorite_button,
                      "star" if checked else "star_outline", self._palette)
        self.favorite_button.setToolTip(
            "Remove from favourites" if checked else "Add to favourites"
        )
        self.favorite_toggled.emit(checked)

    def set_favorite(self, is_favorite: bool) -> None:
        """Set the toggle without emitting favorite_toggled."""
        self.favorite_button.blockSignals(True)
        self.favorite_button.setChecked(is_favorite)
        remember_icon(self.favorite_button,
                      "star" if is_favorite else "star_outline", self._palette)
        self.favorite_button.blockSignals(False)

    def retheme(self, palette: Palette) -> None:
        self._palette = palette
        restyle_icons(self, palette)
        self.channel_list.retheme(palette)

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
        """Hides the filter with the list: on its own it would filter nothing."""
        self.sidebar.setVisible(visible)

    def set_search_all_available(self, available: bool) -> None:
        """Hidden with fewer than two providers; unticked when it goes away."""
        self._search_all_available = available
        if not available and self.search_all_check.isChecked():
            self.search_all_check.setChecked(False)
        self.search_all_check.setVisible(available)

    @property
    def searching_everywhere(self) -> bool:
        return self._search_all_available and self.search_all_check.isChecked()

    def clear_filter(self) -> None:
        """Called when the list is replaced -- a filter left over from the last
        list would silently hide most of the new one."""
        self.channel_search.clear()


class VodPage(QWidget):
    """Movie or series posters, with a filter over them.

    A grid filters as well as a list does -- better, if anything, since the
    tiles reflow to close the gaps rather than leaving a column of holes. The
    only thing it needed was for the flow layout to skip hidden tiles, which is
    what Qt's own layouts do anyway.

    Tiles are hidden and shown rather than rebuilt: a routed Movies grid runs to
    795 posters, and rebuilding that many widgets on every keystroke is the one
    way to make a filter feel slower than scrolling.
    """

    item_clicked = Signal(object)
    filtered = Signal(int, int)   # showing, total

    def __init__(self, logo_cache, parent=None) -> None:
        super().__init__(parent)
        self.logo_cache = logo_cache
        self._tiles: dict[str, list[QPushButton]] = {}
        #: Every poster, with the name it is matched on.
        self._posters: list[tuple[str, QPushButton]] = []
        logo_cache.logo_ready.connect(self._on_logo_ready)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter)

        self.flow_page = FlowPage(margin=14, spacing=12)

        top = QHBoxLayout()
        top.setContentsMargins(14, 10, 14, 0)
        top.addWidget(self.search)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addLayout(top)
        layout.addWidget(self.flow_page, 1)

    def show_items(self, items, noun: str = "titles") -> None:
        self.flow_page.clear()
        self._tiles.clear()
        self._posters.clear()
        # Cleared without a signal: the box is being reset for a new grid, not
        # edited by anyone, and letting it filter here would run over a grid
        # that is still being built.
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.search.setPlaceholderText(f"Filter {noun}…")
        for item in items:
            poster = self._poster(item)
            self.flow_page.add(poster)
            self._posters.append(((item.name or "").lower(), poster))

    def filter(self, text: str) -> int:
        """Hide the posters that do not match; returns how many are showing."""
        needle = text.strip().lower()
        showing = 0
        for name, poster in self._posters:
            hidden = bool(needle) and needle not in name
            poster.setHidden(hidden)
            showing += not hidden
        # The layout only re-runs when something asks it to, and visibility
        # changes on children are not something it notices by itself.
        self.flow_page.flow.invalidate()
        self.filtered.emit(showing, len(self._posters))
        return showing

    def _poster(self, item) -> QPushButton:
        button = QPushButton()
        button.setObjectName("Tile")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedSize(POSTER_TILE_SIZE)
        button.clicked.connect(lambda _checked=False, i=item: self.item_clicked.emit(i))

        image = QLabel()
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image.setFixedSize(POSTER_IMAGE_SIZE)
        pixmap = self.logo_cache.pixmap(item.logo_path, POSTER_IMAGE_SIZE)
        image.setPixmap(pixmap if pixmap is not None
                        else self.logo_cache.placeholder(POSTER_IMAGE_SIZE))

        label = QLabel(item.name or "")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        button.setToolTip(item.name or "")

        layout = QVBoxLayout(button)
        layout.setContentsMargins(*(POSTER_TILE_MARGIN,) * 4)
        layout.addWidget(image)
        layout.addWidget(label, 1)

        if item.logo_path:
            button.image_label = image
            self._tiles.setdefault(item.logo_path, []).append(button)
            self.logo_cache.request(item.logo, item.logo_path)
        return button

    def _on_logo_ready(self, logo_path: str) -> None:
        pixmap = self.logo_cache.pixmap(logo_path, POSTER_IMAGE_SIZE)
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
        remember_icon(browse_button, "providers", palette)
        browse_button.clicked.connect(self.browse_clicked)

        # A new install has one provider, and nothing here said that the
        # bundled indexes hold hundreds more playlists -- the button named the
        # action but not what it would find, so the larger of the two sources
        # went unnoticed. Counted rather than written down, so it cannot drift
        # from what is actually bundled.
        self.catalogue_hint = QLabel(self._catalogue_summary())
        self.catalogue_hint.setWordWrap(True)
        self.catalogue_hint.setProperty("dim", "true")
        # Same trap as the Preferences hints: a word-wrapped label reports a
        # height for a width it does not have, and the layout believes it.
        policy = self.catalogue_hint.sizePolicy()
        policy.setHeightForWidth(True)
        self.catalogue_hint.setSizePolicy(policy)
        # Measured against a width narrower than it will ever really have, so
        # the starting height is generous rather than short; the first resize
        # replaces it with the real one.
        self.catalogue_hint.setMinimumHeight(
            self.catalogue_hint.heightForWidth(FORM_WIDTH))

        add_button = QPushButton("  Add a new provider…")
        remember_icon(add_button, "plus", palette)
        add_button.clicked.connect(self.add_clicked)

        reset_button = QPushButton("  Reset to defaults…")
        remember_icon(reset_button, "reset", palette)
        reset_button.clicked.connect(self.reset_clicked)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(14, 4, 14, 10)
        buttons.addStretch(1)
        buttons.addWidget(browse_button)
        buttons.addWidget(add_button)
        buttons.addWidget(reset_button)

        # The hint gets a row of its own rather than a share of the button
        # row: it is a sentence, and competing with three buttons for width is
        # what would make it wrap badly or squash them.
        hint_row = QHBoxLayout()
        hint_row.setContentsMargins(14, 8, 14, 0)
        hint_row.addWidget(self.catalogue_hint, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.flow_page, 1)
        layout.addWidget(separator())
        layout.addLayout(hint_row)
        layout.addLayout(buttons)

    def resizeEvent(self, event):    # noqa: N802 -- Qt's spelling
        super().resizeEvent(event)
        width = self.catalogue_hint.width()
        if width > 0:
            self.catalogue_hint.setMinimumHeight(
                self.catalogue_hint.heightForWidth(width))

    def retheme(self, palette: Palette) -> None:
        self._palette = palette
        restyle_icons(self, palette)

    @staticmethod
    def _catalogue_summary() -> str:
        """One line naming every bundled source and what it holds."""
        entries = [e for e in catalogue.load() if not e.combined]
        if not entries:
            return ""
        parts = []
        for source in catalogue.sources():
            of_source = [e for e in entries if e.source == source]
            if of_source:
                parts.append(f"{source} ({len(of_source)} countries, "
                             f"{sum(e.channels for e in of_source):,} channels)")
        return "Bundled playlist indexes: " + ", ".join(parts) + "."

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
    A country usually appears in both, so each source's playlists sit under a
    heading naming it and counting what it holds. Before those headings existed
    the grouping was real but invisible -- iptv-org's 186 entries began after
    96 Free-TV tiles, with the source named only in a tooltip, so the larger
    collection was effectively only reachable through the source filter.
    Each source's whole-world playlist is offered first within its group.

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
        heading_shown = None
        for entry in matches:
            if entry.source != heading_shown:
                self.flow_page.add(self._source_heading(entry.source, matches))
                heading_shown = entry.source
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

    def _source_heading(self, source: str, matches: list) -> QLabel:
        """Names a source and says how much of it is on screen.

        The count is of what is showing, not of what is bundled, so it stays
        true while a search narrows the list.
        """
        shown = [e for e in matches if e.source == source]
        channels = sum(e.channels for e in shown if not e.combined)
        label = QLabel(f"{source} — {len(shown)} playlists, "
                       f"{channels:,} channels")
        label.setProperty("heading", "true")
        label.setProperty(SPANS_ROW, True)
        return label

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
    number_setting_changed = Signal(str, float)
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

        appearance_heading = QLabel("Appearance")
        appearance_heading.setProperty("heading", "true")

        self.theme_combo = QComboBox()
        for value, label in THEME_CHOICES:
            self.theme_combo.addItem(label, value)
        current = settings.get_string("theme")
        index = self.theme_combo.findData(current)
        self.theme_combo.setCurrentIndex(index if index >= 0 else 0)
        self.theme_combo.currentIndexChanged.connect(
            lambda _index: self.setting_changed.emit("theme",
                                                     self.theme_combo.currentData())
        )
        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Theme:"))
        theme_row.addWidget(self.theme_combo)
        theme_row.addStretch(1)

        theme_hint = QLabel(
            "Follow Windows uses the app colour mode from Windows settings, which "
            "is separate from the one Windows applies to its own shell. Light and "
            "Dark override it. The change applies at once — Winnotix used to need "
            "restarting for a Windows theme change to reach it, and no longer does."
        )
        theme_hint.setWordWrap(True)
        theme_hint.setProperty("dim", "true")

        playlist_heading = QLabel("Playlists")
        playlist_heading.setProperty("heading", "true")

        self.hide_unplayable_check = QCheckBox("Hide channels known to be unplayable")
        self.hide_unplayable_check.setChecked(settings.get_boolean("hide-unplayable"))
        self.hide_unplayable_check.toggled.connect(
            lambda checked: self.bool_setting_changed.emit("hide-unplayable", checked)
        )
        self.route_genre_check = QCheckBox("Sort film and drama channels into Movies and Series")
        self.route_genre_check.setChecked(settings.get_boolean("route-by-genre"))
        self.route_genre_check.toggled.connect(
            lambda checked: self.bool_setting_changed.emit("route-by-genre", checked)
        )
        route_hint = QLabel(
            "A country-grouped playlist puts everything under TV Channels, so the "
            "Movies and Series tiles stay empty. This sorts channels iptv-org "
            "classifies as film or drama into them, still grouped by country. It is "
            "a genre sort, not a list of single shows: Series holds channels like "
            "BBC Drama alongside ones that loop a single show, and Movies holds film "
            "channels rather than a video library. Channels it moves leave their "
            "country list under TV Channels."
        )
        route_hint.setWordWrap(True)
        route_hint.setProperty("dim", "true")

        self.show_epg_check = QCheckBox("Show what is on now, where a guide is published")
        self.show_epg_check.setChecked(settings.get_boolean("show-epg"))
        self.show_epg_check.toggled.connect(
            lambda checked: self.bool_setting_changed.emit("show-epg", checked)
        )
        epg_hint = QLabel(
            "A playlist can name its own programme guides, and Free-TV's does. "
            "Winnotix downloads only the guide for the country whose channels you "
            "are looking at, and shows the current and next programme beside a "
            "channel and while it plays. Coverage is partial and always will be: "
            "guide and playlist name channels differently, and most niche streams "
            "have no listings published at all. A channel with no match simply "
            "shows nothing. Add a guide URL to a provider under Providers → Edit."
        )
        epg_hint.setWordWrap(True)
        epg_hint.setProperty("dim", "true")

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

        subtitle_heading = QLabel("Subtitles")
        subtitle_heading.setProperty("heading", "true")

        self.subtitles_check = QCheckBox("Show subtitles when a stream carries them")
        self.subtitles_check.setChecked(settings.get_boolean("subtitles-visible"))
        self.subtitles_check.toggled.connect(
            lambda checked: self.bool_setting_changed.emit("subtitles-visible", checked)
        )
        subtitle_hint = QLabel(
            "Only subtitles the stream sends as their own track can be switched off "
            "or moved — mpv turns those on by itself when the stream marks one as "
            "default, which is why the switch exists. Subtitles burned into the "
            "picture are part of the video and nothing here affects them, and size "
            "and position apply to text subtitles rather than bitmap ones. Press V "
            "while watching to toggle, and F2 to see what the current stream offers."
        )
        subtitle_hint.setWordWrap(True)
        subtitle_hint.setProperty("dim", "true")

        self.subtitle_scale = QSlider(Qt.Orientation.Horizontal)
        self.subtitle_scale.setRange(50, 300)        # 0.5x to 3.0x
        self.subtitle_scale.setSingleStep(5)
        self.subtitle_scale.setPageStep(25)
        self.subtitle_scale.setValue(int(settings.get_double("subtitle-scale") * 100))
        self.subtitle_scale_label = QLabel()
        self.subtitle_scale.valueChanged.connect(self._on_subtitle_scale)

        # mpv's sub-pos is a percentage down the frame: 100 is the bottom edge,
        # 0 the top, and above 100 pushes it off-screen -- so the range stops there.
        self.subtitle_position = QSlider(Qt.Orientation.Horizontal)
        self.subtitle_position.setRange(0, 100)
        self.subtitle_position.setSingleStep(1)
        self.subtitle_position.setPageStep(10)
        self.subtitle_position.setValue(settings.get_int("subtitle-position"))
        self.subtitle_position_label = QLabel()
        self.subtitle_position.valueChanged.connect(self._on_subtitle_position)

        subtitle_form = QFormLayout()
        subtitle_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        scale_row = QHBoxLayout()
        scale_row.addWidget(self.subtitle_scale, 1)
        scale_row.addWidget(self.subtitle_scale_label)
        position_row = QHBoxLayout()
        position_row.addWidget(self.subtitle_position, 1)
        position_row.addWidget(self.subtitle_position_label)
        subtitle_form.addRow("Size", scale_row)
        subtitle_form.addRow("Height", position_row)
        self._update_subtitle_labels()

        layout.addLayout(form)
        layout.addWidget(mpv_hint)
        layout.addSpacing(10)
        layout.addWidget(separator())
        layout.addWidget(appearance_heading)
        layout.addLayout(theme_row)
        layout.addWidget(theme_hint)
        layout.addSpacing(10)
        layout.addWidget(separator())
        layout.addWidget(playlist_heading)
        layout.addWidget(self.hide_unplayable_check)
        layout.addWidget(hide_hint)
        layout.addSpacing(6)
        layout.addWidget(self.route_genre_check)
        layout.addWidget(route_hint)
        layout.addSpacing(6)
        layout.addWidget(self.show_epg_check)
        layout.addWidget(epg_hint)
        layout.addSpacing(6)
        layout.addWidget(self.hide_adult_check)
        layout.addWidget(adult_hint)
        layout.addSpacing(10)
        layout.addWidget(separator())
        layout.addWidget(subtitle_heading)
        layout.addWidget(self.subtitles_check)
        layout.addWidget(subtitle_hint)
        layout.addSpacing(6)
        layout.addLayout(subtitle_form)
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

        # A word-wrapped QLabel reports a sizeHint based on some notional width
        # rather than the one it actually gets, and a QVBoxLayout believes it --
        # so every hint on this page was clipped mid-sentence, losing the last
        # line or two of each explanation. The policy is what makes the layout
        # measure wrapped text at all; _fit_hints supplies the width to measure
        # against, which is not known until the page has been laid out.
        self._hints = []
        for label in host.findChildren(QLabel):
            if not label.wordWrap():
                continue
            policy = label.sizePolicy()
            policy.setHeightForWidth(True)
            label.setSizePolicy(policy)
            label.setMinimumHeight(label.heightForWidth(FORM_WIDTH))
            self._hints.append(label)

        self.setWidget(host)

    def resizeEvent(self, event):    # noqa: N802 -- Qt's spelling
        super().resizeEvent(event)
        self._fit_hints()

    def _fit_hints(self) -> None:
        """Re-measure the wrapped hints against the width they really have.

        Measuring against the column's maximum under-counts, because margins
        make the column narrower than that -- which left the longest hints
        clipped even after the size policy was corrected.
        """
        for label in getattr(self, "_hints", ()):
            width = label.width()
            if width > 0:
                label.setMinimumHeight(label.heightForWidth(width))

    # -- subtitles -----------------------------------------------------

    def set_theme(self, value: str) -> None:
        """Reflect a theme chosen elsewhere, without echoing it back."""
        index = self.theme_combo.findData(value)
        if index < 0:
            return
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(index)
        self.theme_combo.blockSignals(False)

    def _update_subtitle_labels(self) -> None:
        self.subtitle_scale_label.setText(f"{self.subtitle_scale.value() / 100:.2f}x")
        value = self.subtitle_position.value()
        where = "bottom" if value >= 100 else ("top" if value == 0 else f"{value}%")
        self.subtitle_position_label.setText(where)

    def _on_subtitle_scale(self, value: int) -> None:
        self._update_subtitle_labels()
        self.number_setting_changed.emit("subtitle-scale", value / 100)

    def _on_subtitle_position(self, value: int) -> None:
        self._update_subtitle_labels()
        self.number_setting_changed.emit("subtitle-position", float(value))

    def set_subtitles_visible(self, visible: bool) -> None:
        """Reflect a toggle made elsewhere -- the V key -- without echoing it back."""
        blocked = self.subtitles_check.blockSignals(True)
        self.subtitles_check.setChecked(visible)
        self.subtitles_check.blockSignals(blocked)

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
