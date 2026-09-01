"""Tests for the programme guide (winnotix/core/epg.py)."""

from __future__ import annotations

import gzip
from datetime import datetime, timedelta, timezone

import pytest

from winnotix.core import epg
from winnotix.core.epg import (
    EpgStore,
    Guide,
    guide_country,
    guide_urls,
    normalise_id,
    normalise_name,
    playlist_guide_urls,
    urls_for_country,
)


NOW = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)

SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<tv>
  <channel id="BBC.One.HD.uk">
    <display-name>BBC One HD</display-name>
    <display-name>BBC 1</display-name>
  </channel>
  <channel id="Channel.5.uk">
    <display-name>Channel 5</display-name>
  </channel>
  <programme start="20260901173000 +0000" stop="20260901182500 +0000" channel="Channel.5.uk">
    <title>5 News</title>
    <desc>The day's headlines.</desc>
  </programme>
  <programme start="20260901182500 +0000" stop="20260901190000 +0000" channel="Channel.5.uk">
    <title>Car Pound Cops</title>
  </programme>
  <programme start="20260901175000 +0000" stop="20260901190000 +0000" channel="BBC.One.HD.uk">
    <title>The News at Six</title>
  </programme>
  <programme start="20200101000000 +0000" stop="20200101010000 +0000" channel="Channel.5.uk">
    <title>Far Too Old</title>
  </programme>
</tv>
"""


@pytest.fixture
def guide():
    return Guide.parse(SAMPLE.encode("utf-8"), now=NOW)


class Ch:
    """A stand-in for common.Channel: the two attributes the guide reads."""

    def __init__(self, id=None, name=None):
        self.id = id
        self.name = name


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("BBCOne.uk@SD", "BBCOne.uk"),
    ("BBCOne.uk", "BBCOne.uk"),
    ("", ""),
    (None, ""),
])
def test_normalise_id(raw, expected):
    assert normalise_id(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("BBC One HD", "bbcone"),          # quality qualifiers differ between sources
    ("BBC.One.uk", "bbconeuk"),
    ("Channel 5", "channel5"),
    ("Aathavan TV (720p) [Not 24/7]", "aathavantv"),   # playlist noise
    ("GREAT! movies", "greatmovies"),
    ("", ""),
    (None, ""),
])
def test_normalise_name(raw, expected):
    assert normalise_name(raw) == expected


def test_normalisation_is_what_makes_the_two_sources_meet():
    """epgshare says "Channel 5"; the playlist says "Channel5.uk"."""
    assert normalise_name("Channel 5") == normalise_name("channel 5 HD")


# --------------------------------------------------------------------------
# Finding the guides
# --------------------------------------------------------------------------

def test_x_tvg_url_is_read_from_the_playlist_header(tmp_path):
    path = tmp_path / "p.m3u"
    path.write_text(
        '#EXTM3U x-tvg-url="https://e.example/a.xml.gz, https://e.example/b.xml.gz"\n'
        "#EXTINF:-1,One\nhttp://x/1\n", encoding="utf-8")
    assert playlist_guide_urls(path) == [
        "https://e.example/a.xml.gz", "https://e.example/b.xml.gz"]


def test_the_other_spelling_is_accepted_too(tmp_path):
    path = tmp_path / "p.m3u"
    path.write_text('#EXTM3U url-tvg="https://e.example/a.xml"\n', encoding="utf-8")
    assert playlist_guide_urls(path) == ["https://e.example/a.xml"]


def test_a_playlist_with_no_guide_yields_none(tmp_path):
    path = tmp_path / "p.m3u"
    path.write_text("#EXTM3U\n#EXTINF:-1,One\nhttp://x/1\n", encoding="utf-8")
    assert playlist_guide_urls(path) == []


def test_a_missing_playlist_is_not_fatal(tmp_path):
    assert playlist_guide_urls(tmp_path / "absent.m3u") == []
    assert playlist_guide_urls(None) == []


def test_the_providers_own_guide_comes_first(tmp_path):
    """It is the user's explicit choice, and iptv-org's only possible source."""
    path = tmp_path / "p.m3u"
    path.write_text('#EXTM3U x-tvg-url="https://e.example/from-playlist.xml"\n',
                    encoding="utf-8")

    class Provider:
        epg = "https://e.example/mine.xml"

    assert guide_urls(path, Provider()) == [
        "https://e.example/mine.xml", "https://e.example/from-playlist.xml"]


def test_guide_urls_dedupe_and_reject_non_http(tmp_path):
    path = tmp_path / "p.m3u"
    path.write_text('#EXTM3U x-tvg-url="https://e.example/a.xml, ftp://e/b.xml,'
                    ' https://e.example/a.xml"\n', encoding="utf-8")
    assert guide_urls(path, None) == ["https://e.example/a.xml"]


@pytest.mark.parametrize("url,expected", [
    # The one non-ISO code among the 64 Free-TV declares: ISO calls the UK "GB".
    ("https://epgshare01.online/epgshare01/epg_ripper_UK1.xml.gz", "GB"),
    ("https://epgshare01.online/epgshare01/epg_ripper_FR1.xml.gz", "FR"),
    ("https://epgshare01.online/epgshare01/epg_ripper_al1.xml.gz", "AL"),
    # Not a country at all -- never auto-selected, whatever the open group is.
    ("https://epgshare01.online/epgshare01/epg_ripper_ALL_SOURCES1.xml.gz", None),
    ("https://example.com/whatever.xml.gz", None),
])
def test_guide_country(url, expected):
    assert guide_country(url) == expected


def test_the_uk_alias_is_what_makes_uk_listings_work():
    """A group resolves to GB; the guide file says UK. Miss this and the UK,
    which has the best coverage of any country, silently gets nothing."""
    assert guide_country("https://e/epg_ripper_UK1.xml.gz") == "GB"
    assert urls_for_country(["https://e/epg_ripper_UK1.xml.gz"], "GB") == [
        "https://e/epg_ripper_UK1.xml.gz"]


def test_only_the_matching_country_is_selected():
    """One country is 2.6 MB; the combined guide is 191 MB gzipped."""
    urls = [
        "https://e/epg_ripper_UK1.xml.gz",
        "https://e/epg_ripper_FR1.xml.gz",
        "https://e/epg_ripper_ALL_SOURCES1.xml.gz",
    ]
    assert urls_for_country(urls, "GB") == ["https://e/epg_ripper_UK1.xml.gz"]
    assert urls_for_country(urls, "gb") == ["https://e/epg_ripper_UK1.xml.gz"]
    assert urls_for_country(urls, "FR") == ["https://e/epg_ripper_FR1.xml.gz"]
    # No guide for a country means no listings, never "download everything".
    assert urls_for_country(urls, "JP") == []
    assert urls_for_country(urls, None) == []


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def test_channels_and_display_names_are_indexed(guide):
    assert guide.channel_count == 2
    assert guide.by_name[normalise_name("BBC One HD")] == "BBC.One.HD.uk"
    assert guide.by_name[normalise_name("BBC 1")] == "BBC.One.HD.uk"


def test_programmes_far_outside_the_window_are_dropped(guide):
    """A guide holds days of listings; only now and next are ever shown."""
    titles = [p.title for p in guide.programmes["Channel.5.uk"]]
    assert "Far Too Old" not in titles
    assert titles == ["5 News", "Car Pound Cops"]


def test_malformed_xml_yields_an_empty_guide():
    assert not Guide.parse(b"<tv><channel id=")


def test_an_empty_document_is_falsey():
    assert not Guide.parse(b"<tv></tv>")


@pytest.mark.parametrize("stamp,expected_hour", [
    ("20260901183000 +0000", 18),
    ("20260901183000 +0100", 17),   # offsets are honoured, not ignored
    ("20260901183000 -0500", 23),
    ("20260901183000", 18),         # no offset: treated as UTC
])
def test_programme_times_honour_the_offset(stamp, expected_hour):
    xml = (f'<tv><programme start="{stamp}" channel="c"><title>T</title>'
           "</programme></tv>").encode()
    parsed = Guide.parse(xml, now=NOW)
    assert parsed.programmes["c"][0].start.astimezone(timezone.utc).hour == expected_hour


def test_a_programme_with_an_unparseable_time_is_skipped():
    xml = b'<tv><programme start="not-a-time" channel="c"><title>T</title></programme></tv>'
    assert not Guide.parse(xml, now=NOW)


# --------------------------------------------------------------------------
# Matching and lookup
# --------------------------------------------------------------------------

def test_an_exact_id_match_wins(guide):
    assert guide.key_for(Ch(id="Channel.5.uk")) == "Channel.5.uk"


def test_the_name_carries_it_when_the_id_does_not(guide):
    """The usual case: 4 of 55 match by id, 36 of 55 once names are tried."""
    assert guide.key_for(Ch(id="Channel5.uk", name="Channel 5")) == "Channel.5.uk"
    assert guide.key_for(Ch(id="BBCOne.uk", name="BBC One")) == "BBC.One.HD.uk"


def test_an_unknown_channel_matches_nothing(guide):
    assert guide.key_for(Ch(id="Nope.uk", name="Some Niche Stream")) is None
    assert guide.now_next(Ch(id="Nope.uk"), NOW) == (None, None)


def test_now_and_next(guide):
    current, following = guide.now_next(Ch(name="Channel 5"), NOW)
    assert current.title == "5 News"
    assert following.title == "Car Pound Cops"
    assert current.description == "The day's headlines."


def test_the_last_programme_has_no_next(guide):
    late = datetime(2026, 9, 1, 18, 30, tzinfo=timezone.utc)
    current, following = guide.now_next(Ch(name="Channel 5"), late)
    assert current.title == "Car Pound Cops"
    assert following is None


def test_a_gap_in_the_schedule_still_reports_what_is_next(guide):
    early = datetime(2026, 9, 1, 17, 0, tzinfo=timezone.utc)
    current, following = guide.now_next(Ch(name="Channel 5"), early)
    assert current is None
    assert following.title == "5 News"


def test_when_is_rendered_as_a_range(guide):
    current, _ = guide.now_next(Ch(name="Channel 5"), NOW)
    rendered = current.when()
    assert "-" in rendered and len(rendered.split("-")) == 2


# --------------------------------------------------------------------------
# Fetching and caching
# --------------------------------------------------------------------------

def test_a_gzipped_guide_is_decompressed(tmp_path, monkeypatch):
    store = EpgStore(cache_dir=tmp_path)
    packed = gzip.compress(SAMPLE.encode("utf-8"))

    class Response:
        def read(self_inner): return packed
        def __enter__(self_inner): return self_inner
        def __exit__(self_inner, *a): return False

    monkeypatch.setattr(epg.urllib.request, "urlopen", lambda *a, **k: Response())
    parsed = store.guide("https://e.example/epg_ripper_UK1.xml.gz")
    assert parsed.channel_count == 2


def test_a_fresh_cached_guide_is_not_re_downloaded(tmp_path, monkeypatch):
    store = EpgStore(cache_dir=tmp_path)
    url = "https://e.example/epg_ripper_UK1.xml.gz"
    store.cache_path(url).write_bytes(gzip.compress(SAMPLE.encode("utf-8")))

    def explode(*a, **k):
        raise AssertionError("should have used the cache")

    monkeypatch.setattr(epg.urllib.request, "urlopen", explode)
    assert store.guide(url).channel_count == 2


def test_a_stale_cached_guide_beats_no_listings(tmp_path, monkeypatch):
    """A guide is days of data; yesterday's copy is better than nothing."""
    store = EpgStore(cache_dir=tmp_path, ttl=0)     # everything is stale
    url = "https://e.example/epg_ripper_UK1.xml.gz"
    store.cache_path(url).write_bytes(gzip.compress(SAMPLE.encode("utf-8")))

    def offline(*a, **k):
        raise epg.urllib.error.URLError("no network")

    monkeypatch.setattr(epg.urllib.request, "urlopen", offline)
    assert store.guide(url).channel_count == 2


def test_a_failed_download_with_no_cache_yields_an_empty_guide(tmp_path, monkeypatch):
    store = EpgStore(cache_dir=tmp_path)

    def offline(*a, **k):
        raise epg.urllib.error.URLError("no network")

    monkeypatch.setattr(epg.urllib.request, "urlopen", offline)
    assert not store.guide("https://e.example/epg_ripper_UK1.xml.gz")


def test_a_guide_is_parsed_once_per_store(tmp_path, monkeypatch):
    store = EpgStore(cache_dir=tmp_path)
    url = "https://e.example/epg_ripper_UK1.xml.gz"
    store.cache_path(url).write_bytes(gzip.compress(SAMPLE.encode("utf-8")))
    monkeypatch.setattr(epg.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    assert store.guide(url) is store.guide(url)


def test_now_next_takes_the_first_guide_that_knows_the_channel(tmp_path):
    store = EpgStore(cache_dir=tmp_path)
    empty = Guide.parse(b"<tv></tv>")
    real = Guide.parse(SAMPLE.encode("utf-8"), now=NOW)
    current, _ = store.now_next([empty, real], Ch(name="Channel 5"), NOW)
    assert current.title == "5 News"


def test_now_next_with_no_guides_is_quiet(tmp_path):
    store = EpgStore(cache_dir=tmp_path)
    assert store.now_next([], Ch(name="Channel 5"), NOW) == (None, None)
