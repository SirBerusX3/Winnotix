"""Tests for UI logic that can be checked without a display.

Runs under Qt's offscreen platform, so there is no window and no network. These
cover the pieces where a silent regression would be easy to miss: the provider
form's conditional fields, the group-name cleanup, and the flow layout's
wrapping arithmetic.
"""

from __future__ import annotations

import os

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
# Catalogue picker
# --------------------------------------------------------------------------

@pytest.fixture
def catalogue_page(qapp):
    from winnotix.ui.pages import CataloguePage

    page = CataloguePage()
    yield page
    page.deleteLater()


def test_the_picker_lists_every_source_by_default(catalogue_page):
    from winnotix.core import catalogue

    assert catalogue_page.selected_source is None
    assert catalogue_page.flow_page.flow.count() == len(catalogue.load())
    for label in catalogue.sources():
        assert label in catalogue_page.summary.text()


def test_the_source_filter_narrows_the_picker(catalogue_page):
    from winnotix.core import catalogue

    catalogue_page.source_combo.setCurrentIndex(
        catalogue_page.source_combo.findData(catalogue.IPTV_ORG)
    )
    expected = sum(1 for e in catalogue.load() if e.source == catalogue.IPTV_ORG)
    assert catalogue_page.selected_source == catalogue.IPTV_ORG
    assert catalogue_page.flow_page.flow.count() == expected
    assert catalogue.FREE_TV not in catalogue_page.summary.text()


def test_searching_the_picker_spans_both_sources(catalogue_page):
    catalogue_page.search_entry.setText("britain")
    assert catalogue_page.flow_page.flow.count() == 2
    assert "2 of" in catalogue_page.summary.text()


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
