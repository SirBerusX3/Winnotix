"""Tests for genre routing (winnotix/core/genres.py)."""

from __future__ import annotations

import json

import pytest

from winnotix.core.common import (
    MOVIES_GROUP,
    SERIES_GROUP,
    TV_GROUP,
    Provider,
)
from winnotix.core.genres import (
    GenreIndex,
    normalise_id,
    routed_groups,
    series_channels,
    series_total,
)

from .conftest import write_m3u


@pytest.fixture
def index():
    return GenreIndex({
        "Drama.uk": "series",
        "Films.uk": "movies",
        "Cine.es": "movies",
    })


def _provider_with(manager, tmp_path, providers_dir, body):
    provider = Provider("p", None)
    provider.path = str(write_m3u(tmp_path / "p.m3u", body))
    manager.load_channels(provider)
    return provider


# --------------------------------------------------------------------------
# Id normalisation
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("BBCOne.uk@SD", "BBCOne.uk"),      # iptv-org's published playlists
    ("BBCOne.uk@HD", "BBCOne.uk"),
    ("BBCOne.uk", "BBCOne.uk"),         # Free-TV, and the API itself
    ("  Spaced.uk@SD  ", "Spaced.uk"),
    ("", ""),
    (None, ""),
])
def test_normalise_id(raw, expected):
    assert normalise_id(raw) == expected


def test_feed_suffix_is_what_makes_the_join_work(index):
    """Without stripping @SD this matched 1 of 12,358 real entries."""
    class Ch:
        id = "Drama.uk@SD"
    assert index.kind_for(Ch()) == "series"


# --------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------

def test_classified_channels_move_into_typed_groups(manager, tmp_path,
                                                    providers_dir, index):
    provider = _provider_with(manager, tmp_path, providers_dir, """
#EXTINF:-1 tvg-id="News.uk" group-title="United Kingdom",News
http://x/1
#EXTINF:-1 tvg-id="Drama.uk" group-title="United Kingdom",Drama
http://x/2
#EXTINF:-1 tvg-id="Films.uk" group-title="United Kingdom",Films
http://x/3
""")
    assert len(provider.channels) == 3
    assert [g.group_type for g in provider.groups] == [TV_GROUP]

    result = index.route(provider)

    assert result.moved == 2
    assert result.by_kind == {"series": 1, "movies": 1}

    # The classified two leave the TV list; the unclassified one stays.
    assert [c.name for c in provider.channels] == ["News"]
    by_type = {g.group_type: g for g in provider.groups}
    assert [c.name for c in by_type[TV_GROUP].channels] == ["News"]
    assert [c.name for c in by_type[SERIES_GROUP].channels] == ["Drama"]
    assert [c.name for c in by_type[MOVIES_GROUP].channels] == ["Films"]

    # Routed groups keep the country name, so Series lays out like TV Channels.
    assert by_type[SERIES_GROUP].name == "United Kingdom"


def test_movies_reach_the_provider_movies_list(manager, tmp_path,
                                               providers_dir, index):
    """The landing tile and the "all movies" view both read provider.movies."""
    provider = _provider_with(manager, tmp_path, providers_dir, """
#EXTINF:-1 tvg-id="Films.uk" group-title="United Kingdom",Films
http://x/1
""")
    index.route(provider)
    assert [c.name for c in provider.movies] == ["Films"]


def test_series_channels_do_not_enter_provider_series(manager, tmp_path,
                                                      providers_dir, index):
    """provider.series holds Serie objects; a routed channel is not one.

    Pushing channels in there would break every consumer that expects
    .seasons/.episodes -- Blocklist.apply among them.
    """
    provider = _provider_with(manager, tmp_path, providers_dir, """
#EXTINF:-1 tvg-id="Drama.uk" group-title="United Kingdom",Drama
http://x/1
""")
    index.route(provider)

    assert provider.series == []
    assert [c.name for c in series_channels(provider)] == ["Drama"]
    assert series_total(provider) == 1


def test_routing_is_idempotent(manager, tmp_path, providers_dir, index):
    """Routing twice must not cascade through the groups it just created."""
    provider = _provider_with(manager, tmp_path, providers_dir, """
#EXTINF:-1 tvg-id="Drama.uk" group-title="United Kingdom",Drama
http://x/1
#EXTINF:-1 tvg-id="News.uk" group-title="United Kingdom",News
http://x/2
""")
    first = index.route(provider)
    groups_after_first = [(g.name, g.group_type) for g in provider.groups]
    movies_after_first = list(provider.movies)

    second = index.route(provider)

    assert first.moved == 1
    assert second.moved == 0
    assert [(g.name, g.group_type) for g in provider.groups] == groups_after_first
    assert provider.movies == movies_after_first


def test_emptied_country_group_is_dropped(manager, tmp_path, providers_dir, index):
    """A country of nothing but film would otherwise show as "Spain (0)"."""
    provider = _provider_with(manager, tmp_path, providers_dir, """
#EXTINF:-1 tvg-id="Cine.es" group-title="Spain",Cine
http://x/1
""")
    index.route(provider)

    types = [g.group_type for g in provider.groups]
    assert TV_GROUP not in types
    assert types == [MOVIES_GROUP]


def test_channels_are_grouped_per_country(manager, tmp_path, providers_dir, index):
    provider = _provider_with(manager, tmp_path, providers_dir, """
#EXTINF:-1 tvg-id="Films.uk" group-title="United Kingdom",UK Films
http://x/1
#EXTINF:-1 tvg-id="Cine.es" group-title="Spain",ES Films
http://x/2
""")
    index.route(provider)

    movie_groups = routed_groups(provider, MOVIES_GROUP)
    assert sorted(g.name for g in movie_groups) == ["Spain", "United Kingdom"]
    assert len(provider.movies) == 2


def test_unknown_ids_and_missing_ids_are_left_alone(manager, tmp_path,
                                                    providers_dir, index):
    provider = _provider_with(manager, tmp_path, providers_dir, """
#EXTINF:-1 tvg-id="Unlisted.uk" group-title="United Kingdom",Unlisted
http://x/1
#EXTINF:-1 group-title="United Kingdom",No Id At All
http://x/2
""")
    result = index.route(provider)

    assert result.moved == 0
    assert len(provider.channels) == 2
    assert [g.group_type for g in provider.groups] == [TV_GROUP]


def test_an_empty_index_is_a_no_op(manager, tmp_path, providers_dir):
    provider = _provider_with(manager, tmp_path, providers_dir, """
#EXTINF:-1 tvg-id="Drama.uk" group-title="United Kingdom",Drama
http://x/1
""")
    result = GenreIndex({}).route(provider)
    assert result.moved == 0
    assert len(provider.channels) == 1


def test_a_playlists_own_series_group_is_not_touched(manager, tmp_path,
                                                     providers_dir, index):
    """A "SERIES ..." name is a real series group; only TV groups are sources."""
    provider = _provider_with(manager, tmp_path, providers_dir, """
#EXTINF:-1 tvg-id="Drama.uk" group-title="SERIES Drama",Show S01 E01
http://x/1
""")
    assert provider.groups[0].group_type == SERIES_GROUP
    before = len(provider.series)

    result = index.route(provider)

    assert result.moved == 0
    assert len(provider.series) == before
    assert routed_groups(provider, SERIES_GROUP) == []


# --------------------------------------------------------------------------
# Reporting and loading
# --------------------------------------------------------------------------

def test_summary_names_both_destinations(manager, tmp_path, providers_dir, index):
    provider = _provider_with(manager, tmp_path, providers_dir, """
#EXTINF:-1 tvg-id="Films.uk" group-title="United Kingdom",Films
http://x/1
#EXTINF:-1 tvg-id="Cine.es" group-title="Spain",Cine
http://x/2
#EXTINF:-1 tvg-id="Drama.uk" group-title="United Kingdom",Drama
http://x/3
""")
    result = index.route(provider)
    assert result.summary() == "Sorted 2 to Movies, 1 to Series"


def test_summary_is_empty_when_nothing_moved():
    assert GenreIndex({}).route(Provider("p", None)).summary() == ""


def test_shipped_index_loads_and_classifies():
    """The index that ships with the app must be usable as-is."""
    loaded = GenreIndex.load()
    assert loaded, "the bundled genre index should not be empty"
    assert set(loaded.mapping.values()) == {"series", "movies"}

    # A real id from iptv-org, in the form its playlists actually carry.
    class Ch:
        id = "AMC.us@SD"
    assert loaded.kind_for(Ch()) == "movies"


def test_a_missing_index_is_not_fatal(tmp_path):
    assert GenreIndex.load(tmp_path / "absent.json").mapping == {}


def test_a_corrupt_index_is_not_fatal(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert GenreIndex.load(path).mapping == {}


def test_unknown_genre_values_are_ignored(tmp_path):
    path = tmp_path / "g.json"
    path.write_text(json.dumps(
        {"channels": {"A.uk": "series", "B.uk": "sports"}}), encoding="utf-8")
    assert GenreIndex.load(path).mapping == {"A.uk": "series"}
