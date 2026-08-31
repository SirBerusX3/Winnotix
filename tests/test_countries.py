"""Tests for country resolution, flags, badges and the playlist catalogues."""

from __future__ import annotations

import json
from collections import Counter

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
# The playlist catalogues
# --------------------------------------------------------------------------

def test_bundled_catalogues_load():
    entries = catalogue.load()
    assert len(entries) > 50
    assert all(e.name and e.url for e in entries)


def test_both_sources_are_bundled():
    assert catalogue.sources() == [catalogue.FREE_TV, catalogue.IPTV_ORG]
    by_source = Counter(e.source for e in catalogue.load())
    assert by_source[catalogue.FREE_TV] > 50
    assert by_source[catalogue.IPTV_ORG] > 100


@pytest.mark.parametrize(
    "source,prefix",
    [
        (catalogue.FREE_TV, "https://raw.githubusercontent.com/Free-TV/IPTV/master/"),
        (catalogue.IPTV_ORG, "https://iptv-org.github.io/iptv/"),
    ],
)
def test_catalogue_urls_point_at_their_own_source(source, prefix):
    entries = [e for e in catalogue.load() if e.source == source]
    assert entries
    for entry in entries:
        assert entry.url.startswith(prefix), entry.name


def test_each_source_offers_one_combined_playlist():
    """The whole-world playlist, so the picker can offer everything at once."""
    combined = [e for e in catalogue.load() if e.combined]
    assert {e.source for e in combined} == set(catalogue.sources())
    assert all(e.code == "" and e.channels > 1000 for e in combined)


def test_combined_playlists_sort_first():
    ordered = catalogue.order(catalogue.load())
    assert all(e.combined for e in ordered[:len(catalogue.sources())])
    assert not any(e.combined for e in ordered[len(catalogue.sources()):])


def test_provider_name_is_namespaced():
    """So two sources' entries for one country cannot collide as providers."""
    names = {e.provider_name for e in catalogue.load() if e.code == "GB"}
    assert names == {"Free-TV UK", "iptv-org United Kingdom"}


def test_the_same_country_is_found_in_both_sources():
    """iptv-org codes the UK "UK"; normalising to GB is what joins these up."""
    hits = catalogue.search("britain")
    assert {h.source for h in hits} == {catalogue.FREE_TV, catalogue.IPTV_ORG}


def test_search_can_be_restricted_to_one_source():
    hits = catalogue.search("", source=catalogue.IPTV_ORG)
    assert hits and all(h.source == catalogue.IPTV_ORG for h in hits)


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


def test_a_combined_playlist_does_not_match_a_country_search():
    """Searching "germany" should return Germany, not two whole-world lists."""
    assert not any(h.combined for h in catalogue.search("germany"))


def test_catalogue_search_no_match():
    assert catalogue.search("zzzznotacountry") == []


def test_catalogue_tolerates_a_missing_file(tmp_path):
    assert catalogue.load_file(tmp_path / "absent.json") == []


def test_catalogue_tolerates_a_corrupt_file(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    assert catalogue.load_file(bad) == []


def test_catalogue_skips_entries_without_a_url(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"playlists": [
        {"name": "Good", "url": "https://h/p.m3u8", "code": "GB", "channels": 5},
        {"name": "No URL", "code": "FR"},
        {"url": "https://h/x.m3u8"},
    ]}), encoding="utf-8")
    entries = catalogue.load_file(path)
    assert [e.name for e in entries] == ["Good"]


def test_loaded_entries_carry_their_source(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"playlists": [
        {"name": "All", "url": "https://h/all.m3u", "channels": 9, "combined": True},
        {"name": "Spain", "url": "https://h/es.m3u", "code": "ES", "channels": 3},
    ]}), encoding="utf-8")
    entries = catalogue.load_file(path, catalogue.IPTV_ORG)
    assert [(e.name, e.source, e.combined) for e in entries] == [
        ("All", catalogue.IPTV_ORG, True),
        ("Spain", catalogue.IPTV_ORG, False),
    ]
    assert entries[1].provider_name == "iptv-org Spain"


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


@pytest.mark.parametrize(
    "name,expected",
    [
        # iptv-org's combined playlist groups by country, using its own spellings.
        ("Democratic Republic of the Congo", "CD"),
        ("Republic of the Congo", "CG"),
        ("Vatican City", "VA"),
        ("Reunion", "RE"),
    ],
)
def test_iptv_org_country_names_resolve(name, expected):
    assert countries.code_for_name(name) == expected
    assert countries.flag_file(expected) is not None


# --------------------------------------------------------------------------
# Flag files a Windows checkout mangles
# --------------------------------------------------------------------------

def _stub(tmp_path, monkeypatch, name: str, body: bytes):
    """Stand up a flags/ directory holding one file with the given bytes."""
    flags = tmp_path / "flags"
    flags.mkdir()
    (flags / name).write_bytes(body)
    monkeypatch.setattr(countries, "resources_dir", lambda: tmp_path)
    countries.flag_file.cache_clear()
    return flags


def test_a_symlink_checked_out_as_text_is_not_offered_to_qt(tmp_path, monkeypatch):
    """circle-flags symlinks `bq.svg` to `bq-bo.svg`. Git on Windows writes the
    target's *name* into the file, and Qt logs 'Start tag expected' per lookup."""
    _stub(tmp_path, monkeypatch, "bq.svg", b"bq-bo.svg")
    assert countries.flag_file("bq") is None


def test_a_real_flag_is_still_found(tmp_path, monkeypatch):
    _stub(tmp_path, monkeypatch, "gb.svg", b'<svg xmlns="http://www.w3.org/2000/svg"/>')
    assert countries.flag_file("gb") is not None


def test_a_flag_with_an_xml_declaration_is_accepted(tmp_path, monkeypatch):
    _stub(tmp_path, monkeypatch, "fr.svg",
          b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg"/>')
    assert countries.flag_file("fr") is not None


def test_leading_whitespace_does_not_hide_a_valid_flag(tmp_path, monkeypatch):
    _stub(tmp_path, monkeypatch, "de.svg",
          b'\n\n   <svg xmlns="http://www.w3.org/2000/svg"/>')
    assert countries.flag_file("de") is not None


def test_no_bundled_flag_is_ever_handed_to_qt_broken():
    """The invariant that matters: `flag_file` either returns a real SVG or
    nothing. Ten codes in the vendored set point at flags that were never
    vendored, and until `tools/repair_flags.py --fetch` runs they are stubs --
    which must show as a missing flag, never as a parse error."""
    countries.flag_file.cache_clear()
    folder = countries.resources_dir() / "flags"
    offered = 0
    for path in folder.glob("*.svg"):
        result = countries.flag_file(path.stem)
        if result is None:
            continue
        offered += 1
        head = open(result, "rb").read(64).lstrip().lower()
        assert head.startswith(b"<svg") or head.startswith(b"<?xml"), path.name
    assert offered > 200, "the flag set looks empty; is resources/flags vendored?"
