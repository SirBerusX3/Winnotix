"""Tests for the ported M3U/provider layer (winnotix/core/common.py).

These pin down upstream Hypnotix's parsing behaviour so the Phase 2 UI rewrite
cannot silently change it. Where upstream has a genuine bug, the test documents
the current behaviour and says so -- fixing it is a deliberate later decision,
not something to do by accident while porting.
"""

from __future__ import annotations

import os

import pytest

from winnotix.core.common import (
    MOVIES_GROUP,
    SERIES_GROUP,
    TV_GROUP,
    Channel,
    Group,
    Provider,
    slugify,
)

from .conftest import write_m3u


# --------------------------------------------------------------------------
# EXTINF attribute parsing
# --------------------------------------------------------------------------

def test_parses_standard_extinf_attributes(providers_dir):
    channel = Channel(
        None,
        '#EXTINF:-1 tvg-id="bbc1" tvg-name="BBC One" tvg-logo="https://x/l.png" '
        'group-title="UK",BBC One HD',
    )
    assert channel.name == "BBC One"
    assert channel.logo == "https://x/l.png"
    assert channel.group_title == "UK"
    assert channel.title == "BBC One HD"


def test_falls_back_to_trailing_title_when_no_tvg_name(providers_dir):
    channel = Channel(None, "#EXTINF:-1,Plain Channel")
    assert channel.name == "Plain Channel"
    assert channel.title == "Plain Channel"
    assert channel.group_title is None


def test_tvg_name_wins_over_trailing_title(providers_dir):
    channel = Channel(None, '#EXTINF:-1 tvg-name="Canonical",Display Name')
    assert channel.name == "Canonical"
    assert channel.title == "Display Name"


def test_blank_attributes_are_ignored(providers_dir):
    channel = Channel(None, '#EXTINF:-1 tvg-name="   " tvg-logo="",Fallback Name')
    assert channel.name == "Fallback Name"
    assert channel.logo is None


def test_group_title_separators_are_normalised(providers_dir):
    """Semicolons become spaces and doubled spaces collapse -- upstream behaviour."""
    channel = Channel(None, '#EXTINF:-1 group-title="A;B  C",X')
    assert channel.group_title == "A B C"


def test_negative_and_positive_durations_both_parse(providers_dir):
    assert Channel(None, "#EXTINF:-1,Live").name == "Live"
    assert Channel(None, "#EXTINF:1234,Recorded").name == "Recorded"


def test_commas_in_channel_name_lose_the_leading_fragment(providers_dir):
    """UPSTREAM QUIRK: a comma inside the channel name silently truncates it.

    EXTINF's `params` group is greedy, so in "#EXTINF:-1,News, Sport and Weather"
    it swallows "News," and `title` captures only what follows. `name` then falls
    back to the last comma-separated fragment, so "News, " is dropped from both.
    Documented rather than fixed -- see roadmap Phase 3.
    """
    channel = Channel(None, "#EXTINF:-1,News, Sport and Weather")
    assert channel.name == "Sport and Weather"
    assert channel.title == " Sport and Weather"


# --------------------------------------------------------------------------
# Logo cache paths
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "logo,expected_suffix",
    [
        ("https://x/logo.png", ".png"),
        ("https://x/logo.jpg", ".jpg"),
        ("https://x/logo.gif", ".gif"),
        ("https://x/logo.JPEG", ".jpg"),  # .jpeg is normalised to .jpg
        ("https://x/logo.PNG", ".png"),   # extension match is case-insensitive
    ],
)
def test_logo_path_extension_handling(providers_dir, logo, expected_suffix):
    channel = Channel(None, f'#EXTINF:-1 tvg-name="News" tvg-logo="{logo}",News')
    assert channel.logo_path.endswith(expected_suffix)
    assert os.path.dirname(channel.logo_path) == str(providers_dir)


def test_local_file_logo_is_used_directly(providers_dir):
    channel = Channel(None, '#EXTINF:-1 tvg-name="X" tvg-logo="file:///tmp/a.png",X')
    assert channel.logo_path == "/tmp/a.png"


def test_logo_path_is_namespaced_by_provider(providers_dir):
    provider = Provider("My Provider", None)
    channel = Channel(provider, '#EXTINF:-1 tvg-name="News" tvg-logo="https://x/l.png",News')
    assert os.path.basename(channel.logo_path) == "myprovider-news.png"


def test_logo_path_uses_favorites_namespace_when_no_provider(providers_dir):
    channel = Channel(None, '#EXTINF:-1 tvg-name="News" tvg-logo="https://x/l.png",News')
    assert os.path.basename(channel.logo_path) == "favorites-news.png"


@pytest.mark.xfail(
    reason="UPSTREAM BUG: extensionless logo URLs produce a path ending in the "
           "literal string 'None'. Common in real playlists. See roadmap Phase 3.",
    strict=True,
)
def test_extensionless_logo_url_should_not_produce_literal_none(providers_dir):
    channel = Channel(None, '#EXTINF:-1 tvg-name="News" tvg-logo="https://cdn/logo",News')
    assert not channel.logo_path.endswith("None")


def test_extensionless_logo_current_behaviour_is_documented(providers_dir):
    """Companion to the xfail above: this is what actually happens today."""
    channel = Channel(None, '#EXTINF:-1 tvg-name="News" tvg-logo="https://cdn/logo",News')
    assert os.path.basename(channel.logo_path) == "favorites-newsNone"


# --------------------------------------------------------------------------
# Groups
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name,expected",
    [
        ("UK Entertainment", TV_GROUP),
        ("VOD Movies", MOVIES_GROUP),
        ("EN SERIES", SERIES_GROUP),
        ("VODMovies", TV_GROUP),      # substring alone does not qualify
        ("vod movies", TV_GROUP),     # match is case-sensitive, on whole words
    ],
)
def test_group_type_detection(name, expected):
    assert Group(name).group_type == expected


# --------------------------------------------------------------------------
# Provider round-tripping
# --------------------------------------------------------------------------

def test_provider_info_round_trips(providers_dir):
    info = "Name:::xtream:::http://h:8080:::user:::pass:::http://epg"
    provider = Provider(None, info)
    assert provider.name == "Name"
    assert provider.type_id == "xtream"
    assert provider.url == "http://h:8080"
    assert provider.username == "user"
    assert provider.password == "pass"
    assert provider.epg == "http://epg"
    assert provider.get_info() == info


def test_provider_round_trips_the_default_free_tv_entry(providers_dir):
    """The shipped default must survive a load/save cycle unchanged."""
    from winnotix.core.settings import DEFAULTS

    info = DEFAULTS["providers"][0]
    assert Provider(None, info).get_info() == info


def test_provider_path_is_slugified(providers_dir):
    provider = Provider("Free-TV!", None)
    assert os.path.basename(provider.path) == "freetv"


def test_slugify_strips_non_alphanumerics_and_lowercases():
    assert slugify("Free-TV 42!") == "freetv42"


# --------------------------------------------------------------------------
# Playlist loading
# --------------------------------------------------------------------------

def test_check_playlist_requires_both_markers(manager, tmp_path, providers_dir):
    provider = Provider("p", None)

    provider.path = str(write_m3u(tmp_path / "good.m3u", '#EXTINF:-1,A\nhttp://a/s'))
    assert manager.check_playlist(provider) is True

    bad = tmp_path / "bad.m3u"
    bad.write_text("not a playlist", encoding="utf-8")
    provider.path = str(bad)
    assert manager.check_playlist(provider) is False


def test_check_playlist_false_for_missing_file(manager, providers_dir):
    provider = Provider("p", None)
    provider.path = str(providers_dir / "does-not-exist")
    assert manager.check_playlist(provider) is False


def test_load_channels_groups_and_counts(manager, tmp_path, providers_dir):
    provider = Provider("p", None)
    provider.path = str(write_m3u(tmp_path / "p.m3u", """
#EXTINF:-1 group-title="News",BBC News
http://host/1
#EXTINF:-1 group-title="News",Sky News
http://host/2
#EXTINF:-1 group-title="VOD Movies",Some Film
http://host/3
#EXTINF:-1,Ungrouped Channel
http://host/4
"""))
    manager.load_channels(provider)

    assert [g.name for g in provider.groups] == ["News", "VOD Movies"]
    assert len(provider.movies) == 1
    # Two grouped TV channels plus the ungrouped one.
    assert [c.name for c in provider.channels] == [
        "BBC News", "Sky News", "Ungrouped Channel",
    ]


def test_load_channels_reuses_a_group_seen_earlier(manager, tmp_path, providers_dir):
    """Non-contiguous entries for one group must not create a duplicate Group."""
    provider = Provider("p", None)
    provider.path = str(write_m3u(tmp_path / "p.m3u", """
#EXTINF:-1 group-title="News",A
http://host/1
#EXTINF:-1 group-title="Sport",B
http://host/2
#EXTINF:-1 group-title="News",C
http://host/3
"""))
    manager.load_channels(provider)

    assert [g.name for g in provider.groups] == ["News", "Sport"]
    news = next(g for g in provider.groups if g.name == "News")
    assert [c.name for c in news.channels] == ["A", "C"]


def test_load_channels_skips_placeholder_and_extra_urls(manager, tmp_path, providers_dir):
    provider = Provider("p", None)
    provider.path = str(write_m3u(tmp_path / "p.m3u", """
#EXTINF:-1,*** Placeholder ***
http://host/skip
#EXTINF:-1,Real Channel
http://host/first
http://host/second-url-ignored
"""))
    manager.load_channels(provider)

    assert [c.name for c in provider.channels] == ["Real Channel"]
    assert provider.channels[0].url == "http://host/first"


def test_load_channels_ignores_comment_lines(manager, tmp_path, providers_dir):
    provider = Provider("p", None)
    provider.path = str(write_m3u(tmp_path / "p.m3u", """
#EXTVLCOPT:http-user-agent=Mozilla
#EXTINF:-1,A
http://host/1
"""))
    manager.load_channels(provider)
    assert len(provider.channels) == 1


def test_load_channels_handles_bad_encoding(manager, tmp_path, providers_dir):
    """Real playlists contain mojibake; parsing must not raise."""
    path = tmp_path / "p.m3u"
    path.write_bytes(b"#EXTM3U\n#EXTINF:-1,Caf\xe9 TV\nhttp://host/1\n")
    provider = Provider("p", None)
    provider.path = str(path)
    manager.load_channels(provider)
    assert len(provider.channels) == 1


# --------------------------------------------------------------------------
# Series detection
# --------------------------------------------------------------------------

def test_series_episodes_are_grouped(manager, tmp_path, providers_dir):
    provider = Provider("p", None)
    provider.path = str(write_m3u(tmp_path / "p.m3u", """
#EXTINF:-1 group-title="EN SERIES",Breaking Bad S01E01
http://host/1
#EXTINF:-1 group-title="EN SERIES",Breaking Bad S01E02
http://host/2
#EXTINF:-1 group-title="EN SERIES",Breaking Bad S02E01
http://host/3
"""))
    manager.load_channels(provider)

    assert len(provider.series) == 1
    serie = provider.series[0]
    assert serie.name == "Breaking Bad"
    assert sorted(serie.seasons) == ["01", "02"]
    assert len(serie.episodes) == 3
    assert sorted(serie.seasons["01"].episodes) == ["01", "02"]


def test_series_matching_is_case_insensitive(manager, tmp_path, providers_dir):
    provider = Provider("p", None)
    provider.path = str(write_m3u(tmp_path / "p.m3u", """
#EXTINF:-1,Some Show s02e10
http://host/1
"""))
    manager.load_channels(provider)
    assert provider.series[0].name == "Some Show"


def test_episode_label_retains_trailing_title(manager, tmp_path, providers_dir):
    """Upstream keeps everything after the episode number as part of the label."""
    provider = Provider("p", None)
    provider.path = str(write_m3u(tmp_path / "p.m3u", """
#EXTINF:-1,Breaking Bad S05E14 Ozymandias
http://host/1
"""))
    manager.load_channels(provider)
    assert list(provider.series[0].seasons["05"].episodes) == ["14 Ozymandias"]


@pytest.mark.xfail(
    reason="UPSTREAM LIMITATION: the SERIES regex requires zero-padded numbers, "
           "so 'Show S1E1' is treated as an ordinary channel. See roadmap Phase 3.",
    strict=True,
)
def test_single_digit_season_episode_should_be_detected(manager, tmp_path, providers_dir):
    provider = Provider("p", None)
    provider.path = str(write_m3u(tmp_path / "p.m3u", """
#EXTINF:-1,Show S1E1
http://host/1
"""))
    manager.load_channels(provider)
    assert len(provider.series) == 1


def test_non_series_names_are_left_alone(manager, tmp_path, providers_dir):
    provider = Provider("p", None)
    provider.path = str(write_m3u(tmp_path / "p.m3u", """
#EXTINF:-1,Movie (2019)
http://host/1
"""))
    manager.load_channels(provider)
    assert provider.series == []


# --------------------------------------------------------------------------
# Favourites
# --------------------------------------------------------------------------

def test_favorites_round_trip(manager, favorites_file):
    entries = ["BBC One", "Café TV", "Channel 4"]
    manager.save_favorites(entries)
    assert manager.load_favorites() == entries


def test_favorites_save_replaces_rather_than_appends(manager, favorites_file):
    manager.save_favorites(["A", "B"])
    manager.save_favorites(["C"])
    assert manager.load_favorites() == ["C"]


def test_favorites_empty_list_round_trips(manager, favorites_file):
    manager.save_favorites([])
    assert manager.load_favorites() == []
