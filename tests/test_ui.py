"""Tests for UI logic that can be checked without a display.

Runs under Qt's offscreen platform, so there is no window and no network. These
cover the pieces where a silent regression would be easy to miss: the provider
form's conditional fields, the group-name cleanup, and the flow layout's
wrapping arithmetic.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolButton

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, QSize  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from winnotix.ui.flow_layout import FlowLayout  # noqa: E402
from winnotix.ui.pages import (  # noqa: E402
    PROVIDER_TYPE_LOCAL,
    PROVIDER_TYPE_URL,
    PROVIDER_TYPE_XTREAM,
    ProviderEditPage,
    _remove_word,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def edit_page(qapp):
    page = ProviderEditPage()
    yield page
    page.deleteLater()


# --------------------------------------------------------------------------
# Group name cleanup
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "word,text,expected",
    [
        ("VOD", "VOD Movies", "Movies"),
        ("SERIES", "EN SERIES", "EN"),
        ("VOD", "Movies", "Movies"),          # word absent: unchanged
        ("VOD", "VOD", "VOD"),                # would empty the label: keep original
        ("VOD", "VOD Action VOD", "Action"),  # every occurrence removed
    ],
)
def test_remove_word(word, text, expected):
    assert _remove_word(word, text) == expected


# --------------------------------------------------------------------------
# Provider form: conditional fields
# --------------------------------------------------------------------------

def _set_type(page, type_id):
    page.type_combo.setCurrentIndex(page.type_combo.findData(type_id))


def test_m3u_url_shows_url_and_epg_only(edit_page):
    _set_type(edit_page, PROVIDER_TYPE_URL)
    assert edit_page.url_entry.isVisibleTo(edit_page)
    assert edit_page.epg_entry.isVisibleTo(edit_page)
    assert not edit_page.username_entry.isVisibleTo(edit_page)
    assert not edit_page.password_entry.isVisibleTo(edit_page)


def test_local_file_shows_path_not_url(edit_page):
    _set_type(edit_page, PROVIDER_TYPE_LOCAL)
    assert edit_page.path_entry.isVisibleTo(edit_page)
    assert not edit_page.url_entry.isVisibleTo(edit_page)


def test_xtream_shows_credentials_not_epg(edit_page):
    _set_type(edit_page, PROVIDER_TYPE_XTREAM)
    assert edit_page.username_entry.isVisibleTo(edit_page)
    assert edit_page.password_entry.isVisibleTo(edit_page)
    assert not edit_page.epg_entry.isVisibleTo(edit_page)


def test_password_field_is_masked(edit_page):
    from PySide6.QtWidgets import QLineEdit
    assert edit_page.password_entry.echoMode() == QLineEdit.EchoMode.Password


# --------------------------------------------------------------------------
# Provider form: round-tripping
# --------------------------------------------------------------------------

def test_load_then_accept_round_trips_a_url_provider(edit_page, providers_dir):
    from winnotix.core.common import Provider

    # Built with join rather than hand-written separators: the format is six
    # fields, and miscounting the colons is easy and silent.
    info = ":::".join(["Name", "url", "http://host/p.m3u", "", "", "http://epg"])
    edit_page.load(Provider(None, info))

    captured = {}
    edit_page.accepted.connect(captured.update)
    edit_page._accept()

    assert captured["name"] == "Name"
    assert captured["type_id"] == PROVIDER_TYPE_URL
    assert captured["url"] == "http://host/p.m3u"
    assert captured["epg"] == "http://epg"


def test_local_provider_emits_path_as_url(edit_page, providers_dir):
    """A local provider stores its file path in the same `url` field."""
    from winnotix.core.common import Provider

    info = ":::".join(["Local", "local", r"C:\playlists\mine.m3u", "", "", ""])
    edit_page.load(Provider(None, info))
    assert edit_page.path_entry.text() == r"C:\playlists\mine.m3u"

    captured = {}
    edit_page.accepted.connect(captured.update)
    edit_page._accept()
    assert captured["url"] == r"C:\playlists\mine.m3u"


def test_load_none_clears_every_field(edit_page, providers_dir):
    from winnotix.core.common import Provider

    edit_page.load(Provider(
        None, ":::".join(["N", "xtream", "http://h", "u", "p", "e"])))
    edit_page.load(None)

    assert edit_page.name_entry.text() == ""
    assert edit_page.url_entry.text() == ""
    assert edit_page.username_entry.text() == ""
    assert edit_page.password_entry.text() == ""
    assert edit_page.epg_entry.text() == ""
    assert edit_page.type_combo.currentData() == PROVIDER_TYPE_URL


def test_accepted_payload_is_stripped(edit_page):
    edit_page.name_entry.setText("  Padded  ")
    edit_page.url_entry.setText("  http://host/p.m3u  ")

    captured = {}
    edit_page.accepted.connect(captured.update)
    edit_page._accept()
    assert captured["name"] == "Padded"
    assert captured["url"] == "http://host/p.m3u"


# --------------------------------------------------------------------------
# Flow layout
# --------------------------------------------------------------------------

def test_flow_layout_wraps_and_reports_height(qapp):
    host = QWidget()
    layout = FlowLayout(host, margin=0, spacing=10)
    for _ in range(6):
        child = QWidget()
        child.setFixedSize(QSize(100, 40))
        layout.addWidget(child)

    # 340px fits three 100px items plus two 10px gaps (320), not four (430).
    three_wide = layout.heightForWidth(340)
    assert three_wide == 40 * 2 + 10, three_wide

    # One per row: six rows.
    one_wide = layout.heightForWidth(100)
    assert one_wide == 40 * 6 + 10 * 5, one_wide


def test_flow_layout_places_items_left_to_right(qapp):
    host = QWidget()
    layout = FlowLayout(host, margin=0, spacing=10)
    children = []
    for _ in range(3):
        child = QWidget()
        child.setFixedSize(QSize(100, 40))
        layout.addWidget(child)
        children.append(child)

    layout.setGeometry(QRect(0, 0, 230, 200))
    assert children[0].geometry().topLeft().toTuple() == (0, 0)
    assert children[1].geometry().topLeft().toTuple() == (110, 0)
    # Third does not fit on the first row (330 > 230), so it wraps.
    assert children[2].geometry().topLeft().toTuple() == (0, 50)


def test_flow_layout_count_and_takeat(qapp):
    host = QWidget()
    layout = FlowLayout(host)
    for _ in range(3):
        layout.addWidget(QWidget())
    assert layout.count() == 3
    layout.takeAt(0)
    assert layout.count() == 2
    assert layout.itemAt(99) is None
    assert layout.takeAt(99) is None


# --------------------------------------------------------------------------
# Episodes page
# --------------------------------------------------------------------------

class _Season:
    def __init__(self, name, episodes):
        self.name = name
        self.episodes = episodes


class _Episode:
    def __init__(self, title):
        self.title = title
        self.name = title
        self.logo_path = None


class _Serie:
    def __init__(self, seasons):
        self.name = "A Show"
        self.seasons = seasons
        self.episodes = []


def _headings(page):
    from PySide6.QtWidgets import QLabel
    return [w.text() for w in page.widget().findChildren(QLabel)
            if w.property("season")]


def test_episode_seasons_sort_numerically(qapp):
    """Season 10 comes after season 2, which plain string sorting gets wrong."""
    from winnotix.ui.pages import EpisodesPage

    page = EpisodesPage()
    page.show_serie(_Serie({
        "2": _Season("2", {"1": _Episode("Two-One")}),
        "10": _Season("10", {"1": _Episode("Ten-One")}),
        "1": _Season("1", {"1": _Episode("One-One")}),
    }))
    assert _headings(page) == ["Season 1", "Season 2", "Season 10"]
    page.deleteLater()


def test_a_named_season_keeps_its_name(qapp):
    """M3U seasons are bare numbers and get upstream's "Season %s" label; an
    Xtream panel names its own, and some of those are not numbers at all."""
    from winnotix.ui.pages import EpisodesPage

    page = EpisodesPage()
    page.show_serie(_Serie({
        "1": _Season("Season 1", {"1": _Episode("Pilot")}),
        "0": _Season("Specials", {"1": _Episode("Behind the scenes")}),
    }))
    assert _headings(page) == ["Specials", "Season 1"]
    page.deleteLater()


def test_episode_tiles_show_the_title_as_a_tooltip(qapp):
    from winnotix.ui.pages import EpisodesPage
    from winnotix.ui.widgets import Tile

    page = EpisodesPage()
    page.show_serie(_Serie({"1": _Season("1", {"3": _Episode("The Finale")})}))
    tiles = page.widget().findChildren(Tile)
    assert [t.text() for t in tiles] == ["Episode 3"]
    assert tiles[0].toolTip() == "The Finale"
    page.deleteLater()


# --------------------------------------------------------------------------
# Playback failure banner
# --------------------------------------------------------------------------

@pytest.fixture
def channels_page(qapp):
    from winnotix.ui.logos import LogoCache
    from winnotix.ui.pages import ChannelsPage
    from winnotix.ui.theme import current_palette
    from tests.conftest import FakeSettings

    cache = LogoCache(FakeSettings())
    page = ChannelsPage(current_palette(), cache)
    yield page
    cache.shutdown()
    page.deleteLater()


def test_the_player_message_is_hidden_until_something_fails(channels_page):
    assert channels_page.message_label.isHidden()

    channels_page.show_message("ITV 1 would not play.")
    assert not channels_page.message_label.isHidden()
    assert channels_page.message_label.text() == "ITV 1 would not play."

    channels_page.clear_message()
    assert channels_page.message_label.isHidden()
    assert channels_page.message_label.text() == ""


def test_an_empty_message_hides_the_banner(channels_page):
    channels_page.show_message("something")
    channels_page.show_message("")
    assert channels_page.message_label.isHidden()


# --------------------------------------------------------------------------
# The channel filter
# --------------------------------------------------------------------------

class FakeChannel:
    def __init__(self, name):
        self.name = name
        self.url = f"http://host/{name}"
        self.logo = None
        self.logo_path = None
        self.id = None


def test_the_filter_is_on_screen_without_being_asked_for(channels_page):
    """It used to be a toggle button in the header, which is why nobody found
    it. Nothing should have to be pressed for it to exist."""
    assert not channels_page.channel_search.isHidden()
    assert "Filter" in channels_page.channel_search.placeholderText()


def test_typing_filters_the_list(channels_page):
    channels_page.channel_list.set_channels(
        [FakeChannel(n) for n in ("BBC One", "BBC Two", "ITV 1")]
    )
    assert channels_page.channel_list.filter("bbc") == 2
    assert channels_page.channel_list.filter("itv") == 1
    assert channels_page.channel_list.filter("") == 3


def test_a_new_list_arrives_unfiltered(channels_page):
    """A filter left over from the last country would hide most of the next
    one, with nothing on screen to explain where the channels went."""
    channels_page.channel_search.setText("bbc")
    channels_page.clear_filter()
    assert channels_page.channel_search.text() == ""


def test_hiding_the_sidebar_hides_the_filter_with_it(channels_page):
    """On its own it would filter a list nobody can see."""
    channels_page.set_sidebar_visible(False)
    assert channels_page.sidebar.isHidden()
    channels_page.set_sidebar_visible(True)
    assert not channels_page.sidebar.isHidden()


def test_search_all_is_hidden_until_there_are_two_providers(channels_page):
    """With one provider it would switch between a list and the same list."""
    assert channels_page.search_all_check.isHidden()
    assert channels_page.searching_everywhere is False

    channels_page.set_search_all_available(True)
    assert not channels_page.search_all_check.isHidden()


def test_search_all_survives_the_page_not_being_on_screen(channels_page):
    """It was read back off isVisible(), which is false whenever another page
    is showing -- so the search silently turned itself off mid-use."""
    channels_page.set_search_all_available(True)
    channels_page.search_all_check.setChecked(True)
    channels_page.hide()

    assert channels_page.searching_everywhere is True


def test_losing_a_provider_unticks_it(channels_page):
    channels_page.set_search_all_available(True)
    channels_page.search_all_check.setChecked(True)

    channels_page.set_search_all_available(False)
    assert channels_page.search_all_check.isChecked() is False
    assert channels_page.searching_everywhere is False


def test_a_result_row_names_the_provider_it_came_from(channels_page):
    """A name alone is ambiguous when the list is drawn from several playlists."""
    channel = FakeChannel("BBC One")
    channel.search_provider = "Free-TV UK"
    channels_page.channel_list.set_channels(
        [channel], suffix=lambda c: getattr(c, "search_provider", ""))

    item = channels_page.channel_list.item(0)
    assert item.text().startswith("BBC One")
    assert item.text().endswith("Free-TV UK")
    assert item.data(Qt.ItemDataRole.UserRole) is channel


def test_rows_are_unlabelled_without_a_suffix(channels_page):
    channels_page.channel_list.set_channels([FakeChannel("BBC One")])
    assert channels_page.channel_list.item(0).text() == "BBC One"


def test_the_header_no_longer_carries_a_search(qapp):
    from winnotix.ui.theme import current_palette
    from winnotix.ui.widgets import HeaderBar

    header = HeaderBar(current_palette())
    try:
        assert not hasattr(header, "search_button")
        assert not hasattr(header, "search_entry")
    finally:
        header.deleteLater()


# --------------------------------------------------------------------------
# Catalogue picker
# --------------------------------------------------------------------------

@pytest.fixture
def catalogue_page(qapp):
    from winnotix.ui.pages import CataloguePage

    page = CataloguePage()
    yield page
    page.deleteLater()


def picker_widgets(page):
    """What the picker put in its flow, split into headings and tiles."""
    from winnotix.ui.pages import Tile

    flow = page.flow_page.flow
    widgets = [flow.itemAt(i).widget() for i in range(flow.count())]
    tiles = [w for w in widgets if isinstance(w, Tile)]
    headings = [w.text() for w in widgets if not isinstance(w, Tile)]
    return headings, tiles


def test_the_picker_lists_every_source_by_default(catalogue_page):
    from winnotix.core import catalogue

    headings, tiles = picker_widgets(catalogue_page)
    assert catalogue_page.selected_source is None
    assert len(tiles) == len(catalogue.load())
    for label in catalogue.sources():
        assert label in catalogue_page.summary.text()
        assert any(text.startswith(label) for text in headings)


def test_every_source_gets_exactly_one_heading(catalogue_page):
    """The complaint this fixes: iptv-org's playlists began 96 tiles down with
    nothing on screen to say so, so the larger source looked absent."""
    from winnotix.core import catalogue

    headings, _ = picker_widgets(catalogue_page)
    assert len(headings) == len(catalogue.sources())
    assert [text.split(" — ")[0] for text in headings] == catalogue.sources()


def test_a_heading_counts_what_is_showing_under_it(catalogue_page):
    from winnotix.core import catalogue

    headings, _ = picker_widgets(catalogue_page)
    for source, text in zip(catalogue.sources(), headings):
        entries = [e for e in catalogue.load() if e.source == source]
        assert f"{len(entries)} playlists" in text
        channels = sum(e.channels for e in entries if not e.combined)
        assert f"{channels:,} channels" in text


def test_the_source_filter_narrows_the_picker(catalogue_page):
    from winnotix.core import catalogue

    catalogue_page.source_combo.setCurrentIndex(
        catalogue_page.source_combo.findData(catalogue.IPTV_ORG)
    )
    expected = sum(1 for e in catalogue.load() if e.source == catalogue.IPTV_ORG)
    headings, tiles = picker_widgets(catalogue_page)
    assert catalogue_page.selected_source == catalogue.IPTV_ORG
    assert len(tiles) == expected
    assert len(headings) == 1
    assert catalogue.FREE_TV not in catalogue_page.summary.text()


def test_searching_the_picker_spans_both_sources(catalogue_page):
    catalogue_page.search_entry.setText("britain")
    headings, tiles = picker_widgets(catalogue_page)
    assert len(tiles) == 2
    # One match each, so a heading each, and each counts only what it shows.
    assert len(headings) == 2
    assert all("1 playlists" in text for text in headings)
    assert "2 of" in catalogue_page.summary.text()


def test_the_providers_page_names_both_bundled_sources(qapp):
    """Manage providers shows one provider on a new install, which said nothing
    about the hundreds of playlists a click away."""
    from winnotix.core import catalogue
    from winnotix.ui.pages import ProvidersPage
    from winnotix.ui.theme import LIGHT

    page = ProvidersPage(LIGHT)
    try:
        hint = page.catalogue_hint.text()
        for label in catalogue.sources():
            assert label in hint
        assert "11,277 channels" in hint

        # The same wrapped-label trap the preferences hints hit -- asserted the
        # same way, on the policy and a starting height rather than on pixels.
        assert page.catalogue_hint.sizePolicy().hasHeightForWidth()
        assert page.catalogue_hint.minimumHeight() > 0
    finally:
        page.deleteLater()


# --------------------------------------------------------------------------
# Bundled artwork
# --------------------------------------------------------------------------

def test_the_app_icon_carries_the_sizes_windows_asks_for(qapp):
    from winnotix.ui.icons import app_icon

    icon = app_icon()
    assert not icon.isNull()
    sizes = {s.width() for s in icon.availableSizes()}
    # 16 for the title bar, 32 for the task bar, 256 for Alt-Tab and Explorer.
    assert {16, 32, 256} <= sizes


def test_the_placeholder_is_never_upscaled_onto_a_poster(qapp):
    """It was Hypnotix's own 22x22 logo, so a 200x200 VOD poster was a 9x
    upscale of a 22px image."""
    from PySide6.QtGui import QPixmap

    from winnotix.core.paths import resources_dir
    from winnotix.ui.pages import POSTER_IMAGE_SIZE

    pixmap = QPixmap(str(resources_dir() / "generic_tv_logo.png"))
    assert not pixmap.isNull()
    # Twice the poster, so it still downscales on a HiDPI screen.
    assert pixmap.width() >= POSTER_IMAGE_SIZE.width() * 2
    assert pixmap.height() >= POSTER_IMAGE_SIZE.height() * 2


def test_a_poster_is_scaled_to_fit_the_tile_that_shows_it():
    """A QLabel clips an oversized pixmap centred rather than shrinking it.

    POSTER_SIZE was 200x200 in logos.py while the tile was 180 wide with 8px
    margins, so every wide logo lost 18px off each edge -- "Anger Management
    Channel" arrived with both ends missing. Deriving one from the other is
    what stops that recurring, so assert the relationship, not the numbers.
    """
    from winnotix.ui.pages import (
        POSTER_IMAGE_SIZE,
        POSTER_TILE_MARGIN,
        POSTER_TILE_SIZE,
    )

    usable_width = POSTER_TILE_SIZE.width() - 2 * POSTER_TILE_MARGIN
    assert POSTER_IMAGE_SIZE.width() == usable_width
    assert POSTER_IMAGE_SIZE.width() <= POSTER_TILE_SIZE.width()
    # The label also has to leave room for the name beneath it.
    assert POSTER_IMAGE_SIZE.height() < POSTER_TILE_SIZE.height()


def test_posters_are_requested_at_the_size_they_are_shown(qapp, tmp_path):
    """The scale request and the label geometry must be the same size."""
    from PySide6.QtGui import QPixmap

    from tests.conftest import FakeSettings
    from winnotix.ui.logos import LogoCache
    from winnotix.ui.pages import POSTER_IMAGE_SIZE, VodPage

    # A deliberately over-wide logo: this is the shape that was being clipped.
    wide = tmp_path / "wide.png"
    QPixmap(900, 300).save(str(wide))

    class Item:
        name = "Wide Logo"
        logo = None
        logo_path = str(wide)

    page = VodPage(LogoCache(FakeSettings()))
    poster = page._poster(Item())
    shown = poster.image_label.pixmap()

    assert poster.image_label.size() == POSTER_IMAGE_SIZE
    assert shown.width() <= POSTER_IMAGE_SIZE.width()
    assert shown.height() <= POSTER_IMAGE_SIZE.height()


def test_we_no_longer_ship_hypnotix_own_logo():
    """Roadmap section 8: do not ship Mint branding or the Hypnotix icon set."""
    import hashlib

    from winnotix.core.paths import project_root, resources_dir

    upstream = project_root() / "hypnotix" / "usr" / "share" / "hypnotix" / "generic_tv_logo.png"
    if not upstream.is_file():
        pytest.skip("the vendored upstream tree is not present")
    ours = resources_dir() / "generic_tv_logo.png"
    assert (hashlib.sha256(ours.read_bytes()).hexdigest()
            != hashlib.sha256(upstream.read_bytes()).hexdigest())


def test_the_channel_list_shows_what_is_on_now(qapp):
    """Rows the guide covers gain the programme; rows it does not are untouched."""
    from datetime import datetime, timezone

    from tests.conftest import FakeSettings
    from winnotix.core.epg import Guide
    from winnotix.ui.logos import LogoCache
    from winnotix.ui.theme import current_palette
    from winnotix.ui.widgets import ChannelList

    xml = (
        '<tv><channel id="Channel.5.uk"><display-name>Channel 5</display-name>'
        "</channel>"
        '<programme start="20260901173000 +0000" stop="20260901182500 +0000"'
        ' channel="Channel.5.uk"><title>5 News</title></programme>'
        '<programme start="20260901182500 +0000" stop="20260901190000 +0000"'
        ' channel="Channel.5.uk"><title>Car Pound Cops</title></programme></tv>'
    ).encode()
    now = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)
    guide = Guide.parse(xml, now=now)

    class Ch:
        def __init__(self, name, url, id=None):
            self.name, self.url, self.id = name, url, id
            self.logo = self.logo_path = None

    listed = [Ch("Channel 5", "http://x/1"), Ch("Some Niche Stream", "http://x/2")]
    widget = ChannelList(LogoCache(FakeSettings()), current_palette())
    widget.set_channels(listed)

    matched = widget.apply_guide(lambda c: guide.now_next(c, now))

    assert matched == 1
    assert widget.item(0).text() == f"Channel 5{ChannelList.GUIDE_SEPARATOR}5 News"
    assert "Car Pound Cops" in widget.item(0).toolTip()
    # No listing means no marker at all, rather than a placeholder on every row.
    assert widget.item(1).text() == "Some Niche Stream"
    assert widget.item(1).toolTip() == "Some Niche Stream"


def test_reapplying_a_guide_does_not_stack_programmes_onto_a_row(qapp):
    """The row is rebuilt from the channel, so refreshing on the hour is safe."""
    from datetime import datetime, timezone

    from tests.conftest import FakeSettings
    from winnotix.core.epg import Guide
    from winnotix.ui.logos import LogoCache
    from winnotix.ui.theme import current_palette
    from winnotix.ui.widgets import ChannelList

    xml = (
        '<tv><channel id="C.uk"><display-name>Five</display-name></channel>'
        '<programme start="20260901173000 +0000" stop="20260901190000 +0000"'
        ' channel="C.uk"><title>News</title></programme></tv>'
    ).encode()
    now = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)
    guide = Guide.parse(xml, now=now)

    class Ch:
        def __init__(self):
            self.name, self.url, self.id = "Five", "http://x/1", None
            self.logo = self.logo_path = None

    widget = ChannelList(LogoCache(FakeSettings()), current_palette())
    widget.set_channels([Ch()])
    widget.apply_guide(lambda c: guide.now_next(c, now))
    widget.apply_guide(lambda c: guide.now_next(c, now))

    assert widget.item(0).text().count("News") == 1


def test_dead_channels_are_dimmed_not_removed(qapp):
    """A check is one request at one moment, so the row stays clickable."""
    from tests.conftest import FakeSettings
    from winnotix.core.health import BLOCKED, DEAD, OK, Result
    from winnotix.ui.logos import LogoCache
    from winnotix.ui.theme import current_palette
    from winnotix.ui.widgets import ChannelList

    class Ch:
        def __init__(self, name, url):
            self.name, self.url, self.id = name, url, None
            self.logo = self.logo_path = None

    verdicts = {
        "http://x/1": Result(OK),
        "http://x/2": Result(DEAD, "The server has nothing at that address."),
        "http://x/3": Result(BLOCKED, "geo-blocked"),
        "http://x/4": None,                       # never checked
    }
    listed = [Ch("Alive", "http://x/1"), Ch("Dead", "http://x/2"),
              Ch("Blocked", "http://x/3"), Ch("Unchecked", "http://x/4")]

    widget = ChannelList(LogoCache(FakeSettings()), current_palette())
    widget.set_channels(listed)
    assert [c.name for c in widget.channels()] == [c.name for c in listed]

    marked = widget.apply_health(lambda c: verdicts[c.url])

    # Only the dead one is marked: a 403 means alive-but-not-from-here.
    assert marked == 1
    assert widget.count() == 4, "nothing is removed"
    assert "nothing at that address" in widget.item(1).toolTip()
    assert widget.item(1).foreground().color() != widget.item(0).foreground().color()


def test_the_sidebar_stylesheet_does_not_fix_the_row_colour():
    """A `color` on QListWidget#Sidebar::item overrides setForeground().

    That is not theoretical: the channel check computed its dimming correctly
    and the stylesheet painted over it, so the marks were invisible while the
    unit test -- which read item data rather than what Qt paints -- passed.
    Normal rows take their colour from the widget palette instead.
    """
    import re

    from winnotix.ui.theme import current_palette, stylesheet

    css = stylesheet(current_palette())
    match = re.search(r"QListWidget#Sidebar::item \{(.*?)\}", css, re.S)
    assert match, "the sidebar item rule should still exist"
    assert "color:" not in match.group(1), match.group(1)


def _preferences(qapp):
    from tests.conftest import FakeSettings
    from winnotix.ui.pages import PreferencesPage

    class Settings(FakeSettings):
        def get_double(self, key):
            return {"subtitle-scale": 1.0}.get(key, 0.0)

        def get_int(self, key):
            return {"subtitle-position": 100}.get(key, 0)

    return PreferencesPage(Settings(subtitles_visible=True))


def test_the_subtitle_sliders_report_their_values(qapp):
    page = _preferences(qapp)
    seen = []
    page.number_setting_changed.connect(lambda k, v: seen.append((k, v)))

    page.subtitle_scale.setValue(150)
    page.subtitle_position.setValue(80)

    assert ("subtitle-scale", 1.5) in seen
    assert ("subtitle-position", 80.0) in seen
    assert page.subtitle_scale_label.text() == "1.50x"
    assert page.subtitle_position_label.text() == "80%"


def test_the_position_slider_cannot_push_subtitles_off_screen(qapp):
    """mpv's sub-pos is a percentage down the frame and accepts up to 150,
    which puts the text below the picture. The slider stops at the bottom."""
    page = _preferences(qapp)
    assert page.subtitle_position.maximum() == 100
    assert page.subtitle_position.minimum() == 0


def test_toggling_subtitles_elsewhere_does_not_echo_back(qapp):
    """The V key sets the preference and then syncs the checkbox; without
    blocking signals that would emit a change and toggle it straight back."""
    page = _preferences(qapp)
    emitted = []
    page.bool_setting_changed.connect(lambda k, v: emitted.append((k, v)))

    page.set_subtitles_visible(False)

    assert page.subtitles_check.isChecked() is False
    assert emitted == []


def test_preference_hints_are_tall_enough_for_their_text(qapp):
    """Word-wrapped QLabels were clipped mid-sentence on the preferences page.

    A QVBoxLayout takes a wrapped label's sizeHint at face value, and that hint
    is computed for a width the label does not get, so the last line or two of
    every explanation was cut off. The fix is the size policy, so assert the
    policy rather than pixel heights.
    """
    page = _preferences(qapp)
    from PySide6.QtWidgets import QLabel

    wrapped = [w for w in page.widget().findChildren(QLabel) if w.wordWrap()]
    assert wrapped, "the preferences page should have explanatory hints"
    for label in wrapped:
        assert label.sizePolicy().hasHeightForWidth(), label.text()[:40]
        assert label.minimumHeight() > 0, label.text()[:40]


# --------------------------------------------------------------------------
# The flow layout's spanning rows
# --------------------------------------------------------------------------

def flow_fixture(qapp, widgets, width=400):
    """Lay `widgets` out in a FlowLayout of a known width."""
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QWidget
    from winnotix.ui.flow_layout import FlowLayout

    host = QWidget()
    layout = FlowLayout(host, margin=0, spacing=10)
    for widget in widgets:
        layout.addWidget(widget)
    layout.setGeometry(QRect(0, 0, width, 1000))
    return host


def tile_widget(width=100, height=40):
    from PySide6.QtWidgets import QWidget

    widget = QWidget()
    widget.setFixedSize(width, height)
    return widget


def spanning_label(text="Source"):
    from PySide6.QtWidgets import QLabel
    from winnotix.ui.flow_layout import SPANS_ROW

    label = QLabel(text)
    label.setProperty(SPANS_ROW, True)
    return label


def test_a_spanning_widget_is_given_the_whole_width(qapp):
    heading, first, second = spanning_label(), tile_widget(), tile_widget()
    host = flow_fixture(qapp, [heading, first, second])
    try:
        assert heading.width() == 400
        assert first.y() > heading.y(), "the tiles start a new row"
        assert second.y() == first.y(), "and then share it as usual"
        assert second.x() > first.x()
    finally:
        host.deleteLater()


def test_a_spanning_widget_starts_its_own_row(qapp):
    """Two tiles fit beside each other in 400px, so the heading has to be what
    breaks the row rather than the width running out."""
    first, heading, second = tile_widget(), spanning_label(), tile_widget()
    host = flow_fixture(qapp, [first, heading, second])
    try:
        assert heading.y() > first.y()
        assert second.y() > heading.y()
        assert heading.x() == first.x() == second.x()
    finally:
        host.deleteLater()


def test_ordinary_tiles_still_wrap_on_width(qapp):
    """The spanning path must not have changed the plain case."""
    tiles = [tile_widget() for _ in range(5)]
    host = flow_fixture(qapp, tiles)
    try:
        rows = sorted({tile.y() for tile in tiles})
        assert len(rows) == 2, "three fit per row at 100px + 10px spacing"
        assert sum(1 for t in tiles if t.y() == rows[0]) == 3
    finally:
        host.deleteLater()


# --------------------------------------------------------------------------
# Filtering the poster grid
# --------------------------------------------------------------------------

class FakeItem:
    def __init__(self, name):
        self.name = name
        self.logo = None
        self.logo_path = None


@pytest.fixture
def vod_page(qapp):
    from winnotix.ui.logos import LogoCache
    from winnotix.ui.pages import VodPage
    from tests.conftest import FakeSettings

    cache = LogoCache(FakeSettings())
    page = VodPage(cache)
    page.resize(900, 460)
    yield page
    cache.shutdown()
    page.deleteLater()


TITLES = ["South Park", "Star Trek", "Stargate SG-1", "The Office",
          "Star Wars: Clone Wars", "Gunsmoke"]


def test_the_grid_filters_like_the_list_does(vod_page):
    vod_page.show_items([FakeItem(name) for name in TITLES], "series")

    assert vod_page.filter("star") == 3
    assert vod_page.filter("") == len(TITLES)


def test_filtered_tiles_close_the_gaps_they_leave(vod_page):
    """The reason a grid was in doubt: hidden tiles must not hold their place.

    Qt's own layouts treat a hidden widget as empty; the flow layout did not,
    so a filtered grid would have kept a hole for every tile it hid.
    """
    vod_page.show_items([FakeItem(name) for name in TITLES], "series")
    vod_page.filter("star")
    # Nothing has painted this page, so ask the layout to run.
    vod_page.flow_page.flow.activate()

    showing = [tile for _, tile in vod_page._posters if not tile.isHidden()]
    assert len(showing) == 3
    # One row, starting at the left margin, evenly spaced.
    assert len({tile.y() for tile in showing}) == 1
    assert [tile.x() for tile in showing] == sorted(tile.x() for tile in showing)
    assert showing[0].x() == 14


def test_the_placeholder_names_what_is_being_filtered(vod_page):
    vod_page.show_items([FakeItem("A")], "movies")
    assert vod_page.search.placeholderText() == "Filter movies…"

    vod_page.show_items([FakeItem("A")], "series")
    assert vod_page.search.placeholderText() == "Filter series…"


def test_a_new_grid_arrives_unfiltered(vod_page):
    vod_page.show_items([FakeItem(name) for name in TITLES], "series")
    vod_page.filter("star")

    vod_page.show_items([FakeItem("Something Else")], "movies")
    assert vod_page.search.text() == ""
    assert not vod_page._posters[0][1].isHidden()


def test_the_filter_reports_what_it_is_showing(vod_page):
    seen = []
    vod_page.filtered.connect(lambda showing, total: seen.append((showing, total)))
    vod_page.show_items([FakeItem(name) for name in TITLES], "series")

    vod_page.filter("star")
    assert seen[-1] == (3, 6)


def test_a_hidden_widget_takes_no_space_in_the_flow(qapp):
    first, second, third = tile_widget(), tile_widget(), tile_widget()
    second.hide()
    host = flow_fixture(qapp, [first, second, third])
    try:
        # Third takes the slot the hidden one would have had, rather than
        # leaving a hole and starting a column further along.
        assert third.x() == first.x() + first.width() + 10
        assert third.y() == first.y()
    finally:
        host.deleteLater()


# --------------------------------------------------------------------------
# Changing theme without a restart
# --------------------------------------------------------------------------

def icon_pixels(widget):
    """The bytes of a widget's icon, so a recolour is observable."""
    from PySide6.QtCore import QSize

    return bytes(widget.icon().pixmap(QSize(20, 20)).toImage().constBits())


def test_palette_for_maps_the_setting(qapp):
    from winnotix.ui.theme import DARK, LIGHT, current_palette, palette_for

    assert palette_for("light") is LIGHT
    assert palette_for("dark") is DARK
    assert palette_for("system") is current_palette()
    # A hand-edited settings file is not a reason to fail.
    assert palette_for("chartreuse") is current_palette()


def test_a_remembered_icon_is_redrawn_for_a_new_palette(qapp):
    from winnotix.ui.theme import DARK, LIGHT
    from winnotix.ui.widgets import restyle_icons, tool_button

    button = tool_button("back", "Go back", LIGHT)
    before = icon_pixels(button)

    assert restyle_icons(button, DARK) == 1
    assert icon_pixels(button) != before, "the icon should have been recoloured"


def test_the_header_recolours_its_buttons_and_menu(qapp):
    from winnotix.ui.theme import DARK, LIGHT
    from winnotix.ui.widgets import HeaderBar

    header = HeaderBar(LIGHT)
    action = header.add_menu_action("About", "info", "F1", lambda: None)
    try:
        before = icon_pixels(header.back_button), icon_pixels(action)
        header.retheme(DARK)
        after = icon_pixels(header.back_button), icon_pixels(action)
        assert after[0] != before[0], "the back button"
        assert after[1] != before[1], "the menu action"
    finally:
        header.deleteLater()


def test_the_status_bar_keeps_the_icon_its_state_calls_for(qapp):
    """The pause button shows play or pause depending on playback, so a
    retheme has to redraw whichever it is currently showing."""
    from winnotix.ui.theme import DARK, LIGHT
    from winnotix.ui.widgets import StatusBar

    bar = StatusBar(LIGHT)
    try:
        bar.set_paused(True)
        paused_light = icon_pixels(bar.pause_button)
        bar.retheme(DARK)
        assert icon_pixels(bar.pause_button) != paused_light

        # And it is still the play icon, not reverted to pause.
        assert bar.pause_button.themed_icon[0] == "play"
        assert bar.pause_button.toolTip() == "Resume"
    finally:
        bar.deleteLater()


def test_the_favourite_star_survives_a_retheme_in_either_state(channels_page):
    from winnotix.ui.theme import DARK, LIGHT

    channels_page.set_favorite(True)
    assert channels_page.favorite_button.themed_icon[0] == "star"
    starred = icon_pixels(channels_page.favorite_button)

    channels_page.retheme(DARK if channels_page._palette is LIGHT else LIGHT)
    assert channels_page.favorite_button.themed_icon[0] == "star"
    assert icon_pixels(channels_page.favorite_button) != starred


def test_provider_cards_are_recoloured_too(qapp):
    """The per-card edit and delete buttons are built from the page's palette,
    which is the case a stylesheet alone would leave stale."""
    from winnotix.ui.pages import ProvidersPage
    from winnotix.ui.theme import DARK, LIGHT

    class FakeProvider:
        name = "Free-TV"

    page = ProvidersPage(LIGHT)
    try:
        page.show_providers([FakeProvider()], "Free-TV")
        buttons = [w for w in page.findChildren(QToolButton)
                   if getattr(w, "themed_icon", None)]
        assert buttons, "a provider card should carry themed buttons"
        before = [icon_pixels(b) for b in buttons]

        page.retheme(DARK)
        assert [icon_pixels(b) for b in buttons] != before
    finally:
        page.deleteLater()


def test_the_channel_list_re_applies_its_own_colours(qapp):
    from PySide6.QtGui import QPalette
    from winnotix.ui.logos import LogoCache
    from winnotix.ui.theme import DARK, LIGHT
    from winnotix.ui.widgets import ChannelList
    from tests.conftest import FakeSettings

    cache = LogoCache(FakeSettings())
    listing = ChannelList(cache, LIGHT)
    try:
        before = listing.palette().color(QPalette.ColorRole.Base).name()
        listing.retheme(DARK)
        after = listing.palette().color(QPalette.ColorRole.Base).name()
        assert before != after
        assert after.lower() == DARK.surface.lower()
    finally:
        cache.shutdown()
        listing.deleteLater()


def test_the_header_offers_the_theme_it_would_switch_to(qapp):
    """The button shows a sun while dark, because that is what clicking gives
    you -- showing the current theme instead would read as a status light."""
    from winnotix.ui.theme import DARK, LIGHT
    from winnotix.ui.widgets import HeaderBar

    header = HeaderBar(LIGHT)
    reference = HeaderBar(LIGHT)    # kept alive: its widgets are compared against
    try:
        assert header.theme_button.themed_icon[0] == "moon"
        assert "dark" in header.theme_button.toolTip()
        light_moon = icon_pixels(reference.theme_button)

        header.retheme(DARK)
        assert header.theme_button.themed_icon[0] == "sun"
        assert "light" in header.theme_button.toolTip()
        # And it is drawn in the new palette, not left in the old one.
        assert icon_pixels(header.theme_button) != light_moon
    finally:
        header.deleteLater()
        reference.deleteLater()


def test_the_theme_button_emits_rather_than_deciding(qapp):
    """The header does not know what the setting is; MainWindow owns that."""
    from winnotix.ui.theme import LIGHT
    from winnotix.ui.widgets import HeaderBar

    header = HeaderBar(LIGHT)
    fired = []
    header.theme_clicked.connect(lambda: fired.append(True))
    try:
        header.theme_button.click()
        assert fired == [True]
    finally:
        header.deleteLater()


def test_preferences_can_be_told_the_theme_without_echoing_it(qapp):
    """The header button changes the setting, so the combo has to follow --
    and must not emit that back as a fresh change."""
    page = _preferences(qapp)
    emitted = []
    page.setting_changed.connect(lambda key, value: emitted.append((key, value)))

    page.set_theme("dark")
    assert page.theme_combo.currentData() == "dark"
    assert emitted == []

    page.set_theme("not-a-theme")
    assert page.theme_combo.currentData() == "dark", "an unknown value is ignored"
