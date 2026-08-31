"""Tests for country resolution, flags, badges and the playlist catalogue."""

from __future__ import annotations

import json

import pytest

from winnotix.core import catalogue, countries
from winnotix.core.common import Channel, Group

from .conftest import write_m3u


# --------------------------------------------------------------------------
# Parsing the attributes upstream ignores
# --------------------------------------------------------------------------

def test_channel_reads_country_id_and_number(providers_dir):
    channel = Channel(None, (
        '#EXTINF:-1 tvg-id="BBC1.uk" tvg-name="BBC One" tvg-country="GB" '
        'tvg-chno="101" group-title="UK",BBC One'
    ))
    assert channel.id == "BBC1.uk"
    assert channel.country == "GB"
    assert channel.channel_number == "101"


def test_country_is_upper_cased(providers_dir):
    channel = Channel(None, '#EXTINF:-1 tvg-country="gb",X')
    assert channel.country == "GB"


def test_missing_attributes_stay_none(providers_dir):
    """Upstream leaves Channel.id as None; entries without tags must still work."""
    channel = Channel(None, "#EXTINF:-1,Plain")
    assert channel.id is None
    assert channel.country is None
    assert channel.channel_number is None


def test_blank_attributes_are_ignored(providers_dir):
    channel = Channel(None, '#EXTINF:-1 tvg-country="  " tvg-id="",X')
    assert channel.country is None
    assert channel.id is None


# --------------------------------------------------------------------------
# Name matching
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name,expected",
    [
        ("Italy", "IT"),
        ("italy", "IT"),
        ("Germany", "DE"),
        # Aliases upstream's countries.list match cannot resolve.
        ("USA", "US"),
        ("UK", "GB"),
        ("Britain", "GB"),
        ("South Korea", "KR"),
        ("Czech Republic", "CZ"),
        # Noise words stripped.
        ("VOD Italy", "IT"),
        ("Italy TV", "IT"),
        ("SERIES Germany", "DE"),
        # Genuinely not countries.
        ("News", None),
        ("Documentaries (EN)", None),
        ("", None),
    ],
)
def test_code_for_name(name, expected):
    assert countries.code_for_name(name) == expected


# --------------------------------------------------------------------------
# Group resolution
# --------------------------------------------------------------------------

def _group(name, *countries_):
    group = Group(name)
    for code in countries_:
        channel = Channel(None, f'#EXTINF:-1 tvg-country="{code}",Ch')
        group.channels.append(channel)
    return group


def test_group_country_comes_from_its_channels(providers_dir):
    """Even when the name says nothing, the tags do."""
    group = _group("Entertainment", "FR", "FR", "FR")
    assert countries.code_for_group(group) == "FR"


def test_group_country_uses_the_majority(providers_dir):
    group = _group("Mixed", "DE", "DE", "DE", "AT")
    assert countries.code_for_group(group) == "DE"


def test_group_with_no_majority_falls_back_to_the_name(providers_dir):
    """A group whose channels disagree should not fly a misleading flag."""
    group = _group("Italy", "FR", "DE", "ES", "NL")
    assert countries.code_for_group(group) == "IT"  # from the name, not the tags


def test_group_without_tags_falls_back_to_the_name(providers_dir):
    group = Group("Portugal")
    group.channels.append(Channel(None, "#EXTINF:-1,Ch"))
    assert countries.code_for_group(group) == "PT"


def test_group_that_is_not_a_country_resolves_to_nothing(providers_dir):
    assert countries.code_for_group(Group("Weather")) is None


def test_group_country_survives_an_empty_group():
    assert countries.code_for_group(Group("News")) is None


# --------------------------------------------------------------------------
# Flags and badges
# --------------------------------------------------------------------------

def test_flag_file_resolves_for_a_bundled_code():
    path = countries.flag_file("GB")
    assert path is not None and path.endswith("gb.svg")


def test_flag_file_is_case_insensitive():
    assert countries.flag_file("gb") == countries.flag_file("GB")


def test_flag_file_returns_none_for_unknown_or_missing():
    assert countries.flag_file(None) is None
    assert countries.flag_file("") is None
    assert countries.flag_file("ZZ") is None


def test_every_catalogue_country_has_a_bundled_flag():
    """A picker entry without a flag would render as a blank square."""
    missing = [e.name for e in catalogue.load()
               if e.code and not countries.flag_file(e.code)]
    assert missing == []


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Documentaries (EN)", ["en"]),
        ("VOD Movies (EN)", ["movies", "en"]),
        ("News (ES)", ["news", "es"]),
        ("Italy", []),
        ("", []),
    ],
)
def test_badges_for_group(name, expected):
    assert countries.badges_for_group(name) == expected


def test_badge_files_exist_for_every_badge_word():
    for word in countries.BADGE_WORDS:
        assert countries.badge_file(word) is not None, word


# --------------------------------------------------------------------------
# The Free-TV catalogue
# --------------------------------------------------------------------------

def test_bundled_catalogue_loads():
    entries = catalogue.load()
    assert len(entries) > 50
    assert all(e.name and e.url for e in entries)


def test_catalogue_urls_point_at_the_free_tv_repo():
    for entry in catalogue.load():
        assert entry.url.startswith(
            "https://raw.githubusercontent.com/Free-TV/IPTV/master/playlists/"
        )


def test_provider_name_is_namespaced():
    """So a catalogue entry cannot silently collide with a hand-added provider."""
    entry = next(e for e in catalogue.load() if e.code == "GB")
    assert entry.provider_name == "Free-TV UK"


@pytest.mark.parametrize(
    "term,expected_code",
    [
        ("uk", "GB"),
        ("gb", "GB"),
        ("united kingdom", "GB"),   # the catalogue calls it "UK"
        ("britain", "GB"),
        ("usa", "US"),
        ("united states", "US"),
        ("america", "US"),
        ("germ", "DE"),             # partial name
    ],
)
def test_catalogue_search_finds_by_name_code_and_alias(term, expected_code):
    hits = catalogue.search(term)
    assert expected_code in {h.code for h in hits}, f"{term} -> {[h.name for h in hits]}"


def test_catalogue_search_empty_term_returns_everything():
    assert len(catalogue.search("")) == len(catalogue.load())


def test_catalogue_search_no_match():
    assert catalogue.search("zzzznotacountry") == []


def test_catalogue_tolerates_a_missing_file(tmp_path):
    assert catalogue.load(tmp_path / "absent.json") == []


def test_catalogue_tolerates_a_corrupt_file(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    assert catalogue.load(bad) == []


def test_catalogue_skips_entries_without_a_url(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"playlists": [
        {"name": "Good", "url": "https://h/p.m3u8", "code": "GB", "channels": 5},
        {"name": "No URL", "code": "FR"},
        {"url": "https://h/x.m3u8"},
    ]}), encoding="utf-8")
    entries = catalogue.load(path)
    assert [e.name for e in entries] == ["Good"]


# --------------------------------------------------------------------------
# End to end through the parser
# --------------------------------------------------------------------------

def test_parsed_group_gets_a_flag(manager, tmp_path, providers_dir):
    from winnotix.core.common import Provider

    provider = Provider("p", None)
    provider.path = str(write_m3u(tmp_path / "p.m3u", """
#EXTINF:-1 tvg-country="GB" group-title="UK",BBC One
http://h/1
#EXTINF:-1 tvg-country="GB" group-title="UK",ITV
http://h/2
"""))
    manager.load_channels(provider)

    group = provider.groups[0]
    code = countries.code_for_group(group)
    assert code == "GB"
    assert countries.flag_file(code) is not None
