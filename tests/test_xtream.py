"""Xtream provider support, against a fake panel. No network, no GUI.

The fixtures below answer `player_api.php` the way a real panel does, including
the two things that make upstream's integration go wrong: category ids reused
across stream types, and a `get_series_info` payload whose episodes are keyed by
season. Each test that pins one of those names the defect it covers.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest
import requests

from winnotix.core import xtream, xtream_loader
from winnotix.core.common import MOVIES_GROUP, SERIES_GROUP, TV_GROUP, Provider

AUTH_OK = {
    "user_info": {
        "username": "user",
        "password": "pass",
        "auth": 1,
        "status": "Active",
        "exp_date": "1800000000",
        "active_cons": "1",
        "max_connections": "2",
    },
    "server_info": {"url": "panel.example.com", "port": "8080"},
}

# Live category 1 and VOD category 1 are unrelated -- this is what upstream's
# single flat group list cannot represent.
LIVE_CATEGORIES = [
    {"category_id": "1", "category_name": "News", "parent_id": 0},
    {"category_id": "2", "category_name": "Sport", "parent_id": 0},
    {"category_id": "7", "category_name": "Empty Shelf", "parent_id": 0},
]
VOD_CATEGORIES = [{"category_id": "1", "category_name": "Action", "parent_id": 0}]
SERIES_CATEGORIES = [{"category_id": "1", "category_name": "Drama", "parent_id": 0}]

LIVE_STREAMS = [
    {"stream_id": 101, "name": "News One", "stream_type": "live", "category_id": "1",
     "stream_icon": "http://panel.example.com/logos/news1.png", "added": "1", "is_adult": "0"},
    {"stream_id": 102, "name": "Sport One", "stream_type": "live", "category_id": "2",
     "stream_icon": "", "added": "1", "is_adult": "0"},
    {"stream_id": 103, "name": "Adults Only", "stream_type": "live", "category_id": "2",
     "stream_icon": "", "added": "1", "is_adult": "1"},
    {"stream_id": 104, "name": "", "stream_type": "live", "category_id": "1",
     "stream_icon": "", "added": "1", "is_adult": "0"},
    {"stream_id": 105, "name": "Homeless", "stream_type": "live", "category_id": "",
     "stream_icon": "", "added": "1", "is_adult": "0"},
    {"stream_id": 106, "name": "Radio Two", "stream_type": "created_live",
     "category_id": "2", "stream_icon": "", "added": "1", "is_adult": "0"},
]
VOD_STREAMS = [
    {"stream_id": 201, "name": "A Movie", "stream_type": "movie", "category_id": "1",
     "stream_icon": "", "container_extension": "mkv"},
]
SERIES_STREAMS = [
    {"series_id": 301, "name": "A Show", "cover": "http://panel.example.com/cover.png",
     "category_id": "1", "plot": "Things happen", "genre": "Drama",
     "youtube_trailer": ""},
]

# Two seasons, each with its own episodes. Upstream gives both seasons all four.
SERIES_INFO = {
    "seasons": [
        {"season_number": 1, "name": "Season 1", "air_date": "2020-01-01"},
        {"season_number": 2, "name": "Season 2", "air_date": "2021-01-01"},
    ],
    "episodes": {
        "1": [
            {"id": "9001", "episode_num": 1, "title": "Pilot",
             "container_extension": "mp4", "info": {}},
            {"id": "9002", "episode_num": 2, "title": "Second",
             "container_extension": "mp4", "info": {}},
        ],
        "2": [
            {"id": "9003", "episode_num": 1, "title": "Return",
             "container_extension": "mp4", "info": {}},
            {"id": "9004", "episode_num": 2, "title": "Finale",
             "container_extension": "mp4", "info": {}},
        ],
    },
}


class FakeResponse:
    def __init__(self, payload=None, status_code=200, reason="OK", body=None):
        self._payload = payload
        self._body = body
        self.status_code = status_code
        self.reason = reason

    @property
    def ok(self):
        return 200 <= self.status_code < 400

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload

    @property
    def text(self):
        return self._body if self._body is not None else json.dumps(self._payload)


class FakePanel:
    """Routes player_api.php by its `action` parameter, and counts requests."""

    def __init__(self, auth=AUTH_OK, series_info=SERIES_INFO):
        self.auth = auth
        self.series_info = series_info
        self.calls: list[str] = []
        self.responses = {
            "get_live_categories": LIVE_CATEGORIES,
            "get_live_streams": LIVE_STREAMS,
            "get_vod_categories": VOD_CATEGORIES,
            "get_vod_streams": VOD_STREAMS,
            "get_series_categories": SERIES_CATEGORIES,
            "get_series": SERIES_STREAMS,
        }

    def __call__(self, url, **kwargs):
        query = parse_qs(urlparse(url).query)
        action = query.get("action", [""])[0]
        self.calls.append(action or "authenticate")
        if not action:
            return FakeResponse(self.auth)
        if action == "get_series_info":
            return FakeResponse(self.series_info)
        if action in self.responses:
            return FakeResponse(self.responses[action])
        return FakeResponse(status_code=404, reason="Not Found")


@pytest.fixture
def panel(monkeypatch):
    fake = FakePanel()
    monkeypatch.setattr(xtream.requests, "get", fake)
    monkeypatch.setattr(xtream_loader.requests, "get", fake)
    return fake


@pytest.fixture
def provider(providers_dir):
    return Provider(
        name=None,
        provider_info="Panel:::xtream:::http://panel.example.com:8080:::user:::pass:::",
    )


def connect(provider, cache_path, **kwargs):
    return xtream_loader.connect(provider, cache_path=str(cache_path), **kwargs)


# ----------------------------------------------------------------------
# Connecting
# ----------------------------------------------------------------------


def test_connect_authenticates(panel, provider, providers_dir):
    session = connect(provider, providers_dir)
    assert session.auth_data["user_info"]["auth"] == 1
    assert session.authorization == {"username": "user", "password": "pass"}


def test_each_session_authenticates_independently(panel, provider, providers_dir):
    """Upstream defect 1: XTream keeps state on the class, so a second provider
    finds itself 'already authenticated' and then reports an auth failure."""
    first = connect(provider, providers_dir)
    second = Provider(name=None,
                      provider_info="Other:::xtream:::http://other.example.com:8080:::user:::pass:::")
    session = connect(second, providers_dir)

    assert session is not first
    assert session.auth_data, "second session authenticated against a shared flag"
    assert session.channels == [] and session.groups == []
    # The plain upstream class is what fails here, which is why we subclass it.
    assert xtream.XTream.state["authenticated"] is False


@pytest.mark.parametrize(
    "user_info, expected",
    [
        ({"auth": 0}, "rejected"),
        ({"auth": 1, "status": "Expired"}, "Expired"),
        ({"auth": 1, "status": "Banned"}, "Banned"),
    ],
)
def test_rejected_accounts_are_reported(monkeypatch, provider, providers_dir,
                                        user_info, expected):
    """Upstream defect 2: any HTTP 200 with user_info counts as success, so an
    expired or rejected account loads nothing and says nothing."""
    fake = FakePanel(auth={"user_info": user_info})
    monkeypatch.setattr(xtream.requests, "get", fake)
    monkeypatch.setattr(xtream_loader.requests, "get", fake)

    with pytest.raises(xtream_loader.XtreamError) as excinfo:
        connect(provider, providers_dir)
    assert expected.lower() in str(excinfo.value).lower()


def test_http_error_names_the_status(monkeypatch, provider, providers_dir):
    def failing(url, **kwargs):
        return FakeResponse(status_code=403, reason="Forbidden")

    monkeypatch.setattr(xtream.requests, "get", failing)
    monkeypatch.setattr(xtream_loader.requests, "get", failing)
    with pytest.raises(xtream_loader.XtreamError, match="403 Forbidden"):
        connect(provider, providers_dir)


def test_non_xtream_server_says_so(monkeypatch, provider, providers_dir):
    def html(url, **kwargs):
        return FakeResponse(payload=None, body="<html>hello</html>")

    monkeypatch.setattr(xtream.requests, "get", html)
    monkeypatch.setattr(xtream_loader.requests, "get", html)
    with pytest.raises(xtream_loader.XtreamError, match="player_api"):
        connect(provider, providers_dir)


def test_unreachable_server_says_so(monkeypatch, provider, providers_dir):
    def refuse(url, **kwargs):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(xtream.requests, "get", refuse)
    monkeypatch.setattr(xtream_loader.requests, "get", refuse)
    with pytest.raises(xtream_loader.XtreamError, match="Could not reach"):
        connect(provider, providers_dir)


@pytest.mark.parametrize(
    "info, expected",
    [
        ("Panel:::xtream::::::user:::pass:::", "no server URL"),
        ("Panel:::xtream:::panel.example.com:8080:::user:::pass:::", "http://"),
        ("Panel:::xtream:::http://panel.example.com:8080::::::pass:::", "username and a password"),
    ],
)
def test_bad_provider_details_fail_before_any_request(monkeypatch, providers_dir,
                                                      info, expected):
    def explode(url, **kwargs):
        raise AssertionError("should not have made a request")

    monkeypatch.setattr(xtream.requests, "get", explode)
    monkeypatch.setattr(xtream_loader.requests, "get", explode)
    with pytest.raises(xtream_loader.XtreamError, match=expected):
        connect(Provider(name=None, provider_info=info), providers_dir)


def test_account_summary_reads_expiry_and_connections():
    summary = xtream_loader.account_summary(AUTH_OK)
    assert "expires 2027-01-15" in summary
    assert "1 of 2 connections in use" in summary


def test_account_summary_handles_a_lifetime_account():
    assert "no expiry" in xtream_loader.account_summary({"user_info": {"exp_date": None}})


# ----------------------------------------------------------------------
# Loading
# ----------------------------------------------------------------------


@pytest.fixture
def loaded(panel, provider, providers_dir):
    session = connect(provider, providers_dir)
    result = xtream_loader.load(provider, session)
    return provider, session, result


def group_named(provider, name):
    return next(g for g in provider.groups if g.name == name)


def test_load_fills_the_provider(loaded):
    provider, _session, result = loaded
    assert [c.name for c in provider.channels] == [
        "News One", "Sport One", "Adults Only", "Homeless", "Radio Two"
    ]
    assert [m.name for m in provider.movies] == ["A Movie"]
    assert [s.name for s in provider.series] == ["A Show"]
    assert result.channels == 5 and result.movies == 1 and result.series == 1


def test_a_stream_with_no_name_is_skipped(loaded):
    _provider, _session, result = loaded
    assert result.skipped_unnamed == 1


def test_vod_categories_do_not_collide_with_live_ones(loaded):
    """Upstream defect 3: category ids are namespaced per stream type, but
    upstream resolves them against one flat list, so a movie in VOD category 1
    is filed under whichever live category happens to share the id."""
    provider, _session, _result = loaded
    news = group_named(provider, "News")
    action = group_named(provider, "Action")

    assert news.group_type == TV_GROUP
    assert action.group_type == MOVIES_GROUP
    assert [c.name for c in news.channels] == ["News One"]
    assert [c.name for c in action.channels] == ["A Movie"]


def test_series_land_in_their_own_group(loaded):
    provider, _session, _result = loaded
    drama = group_named(provider, "Drama")
    assert drama.group_type == SERIES_GROUP
    assert [s.name for s in drama.series] == ["A Show"]
    assert drama.channels == []


def test_a_stream_with_no_category_falls_into_uncategorised(loaded):
    provider, _session, _result = loaded
    catch_all = group_named(provider, xtream_loader.UNCATEGORISED)
    assert [c.name for c in catch_all.channels] == ["Homeless"]


def test_categories_with_no_streams_are_dropped(loaded):
    provider, _session, _result = loaded
    assert "Empty Shelf" not in [g.name for g in provider.groups]


def test_created_live_streams_get_a_usable_url(loaded):
    """Upstream defect 5: Channel normalises `created_live` for its type check
    but builds the URL from the raw value, giving .../created_live/..."""
    provider, _session, _result = loaded
    radio = next(c for c in provider.channels if c.name == "Radio Two")
    assert radio.url == "http://panel.example.com:8080/live/user/pass/106.ts"


def test_movie_urls_use_the_container_extension(loaded):
    provider, _session, _result = loaded
    assert provider.movies[0].url == "http://panel.example.com:8080/movie/user/pass/201.mkv"


def test_hiding_adult_content_drops_marked_channels(panel, provider, providers_dir):
    session = connect(provider, providers_dir, hide_adult_content=True)
    result = xtream_loader.load(provider, session)
    assert "Adults Only" not in [c.name for c in provider.channels]
    assert result.skipped_adult == 1
    assert "1 adult" in result.summary()


def test_a_malformed_stream_does_not_lose_the_rest(monkeypatch, provider, providers_dir):
    fake = FakePanel()
    fake.responses["get_live_streams"] = [
        {"stream_id": 1, "name": "Good", "stream_type": "live", "category_id": "1",
         "stream_icon": "", "added": "1"},
        {"stream_id": 2, "name": "No extension", "stream_type": "movie",
         "category_id": "1", "stream_icon": ""},  # container_extension missing
        "not even a dict",
    ]
    monkeypatch.setattr(xtream.requests, "get", fake)
    monkeypatch.setattr(xtream_loader.requests, "get", fake)

    session = connect(provider, providers_dir)
    result = xtream_loader.load(provider, session)
    assert [c.name for c in provider.channels] == ["Good"]
    assert result.skipped_malformed == 2


def test_a_missing_listing_is_an_error_not_an_empty_provider(monkeypatch, provider,
                                                             providers_dir):
    fake = FakePanel()
    del fake.responses["get_vod_streams"]  # 404s instead
    monkeypatch.setattr(xtream.requests, "get", fake)
    monkeypatch.setattr(xtream_loader.requests, "get", fake)

    session = connect(provider, providers_dir)
    with pytest.raises(xtream_loader.XtreamError, match="VOD listing"):
        xtream_loader.load(provider, session)


# ----------------------------------------------------------------------
# The disk cache
# ----------------------------------------------------------------------


def test_a_second_load_comes_from_the_cache(panel, provider, providers_dir):
    session = connect(provider, providers_dir)
    xtream_loader.load(provider, session)
    before = list(panel.calls)

    xtream_loader.load(provider, session)
    assert panel.calls == before, "cached listings should not be re-requested"


def test_refresh_bypasses_the_cache(panel, provider, providers_dir):
    session = connect(provider, providers_dir)
    xtream_loader.load(provider, session)
    before = len(panel.calls)

    xtream_loader.load(provider, session, refresh=True)
    assert len(panel.calls) == before + 6  # categories + streams, three types


# ----------------------------------------------------------------------
# Seasons and episodes
# ----------------------------------------------------------------------


def test_each_season_holds_only_its_own_episodes(loaded):
    """Upstream defect 4: the episode loop is nested inside the season loop, so
    every season ends up with every episode in the series."""
    provider, session, _result = loaded
    serie = provider.series[0]
    total = xtream_loader.load_series(session, serie)

    assert total == 4
    assert sorted(serie.seasons) == ["1", "2"]
    assert sorted(serie.seasons["1"].episodes) == ["1", "2"]
    assert [e.title for e in serie.seasons["1"].episodes.values()] == ["Pilot", "Second"]
    assert [e.title for e in serie.seasons["2"].episodes.values()] == ["Return", "Finale"]


def test_episode_urls_are_playable(loaded):
    provider, session, _result = loaded
    serie = provider.series[0]
    xtream_loader.load_series(session, serie)
    assert serie.seasons["1"].episodes["1"].url == "http://panel.example.com:8080/series/user/pass/9001.mp4"


def test_seasons_take_the_panels_own_names(loaded):
    provider, session, _result = loaded
    serie = provider.series[0]
    xtream_loader.load_series(session, serie)
    assert serie.seasons["1"].name == "Season 1"


def test_episodes_survive_an_empty_seasons_array(monkeypatch, provider, providers_dir):
    """Panels routinely send `"seasons": []` with a full episodes map. Upstream
    drives its loop off `seasons`, so those series show nothing at all."""
    info = dict(SERIES_INFO, seasons=[])
    fake = FakePanel(series_info=info)
    monkeypatch.setattr(xtream.requests, "get", fake)
    monkeypatch.setattr(xtream_loader.requests, "get", fake)

    session = connect(provider, providers_dir)
    xtream_loader.load(provider, session)
    serie = provider.series[0]
    assert xtream_loader.load_series(session, serie) == 4
    assert serie.seasons["1"].name == "1"


def test_a_season_without_a_cover_still_loads(monkeypatch, provider, providers_dir):
    """Upstream reads `cover` off the season dict it passes as `series_info`,
    so a season without one loses the whole series to a KeyError."""
    info = dict(SERIES_INFO,
                seasons=[{"season_number": 1, "name": "Season 1"}],
                episodes={"1": SERIES_INFO["episodes"]["1"]})
    fake = FakePanel(series_info=info)
    monkeypatch.setattr(xtream.requests, "get", fake)
    monkeypatch.setattr(xtream_loader.requests, "get", fake)

    session = connect(provider, providers_dir)
    xtream_loader.load(provider, session)
    serie = provider.series[0]
    assert xtream_loader.load_series(session, serie) == 2
    # The series' own cover is used, which is what upstream meant to read.
    assert serie.seasons["1"].episodes["1"].logo == "http://panel.example.com/cover.png"


def test_an_untitled_episode_gets_a_label(monkeypatch, provider, providers_dir):
    info = dict(SERIES_INFO, episodes={
        "1": [{"id": "9001", "episode_num": 3, "title": "", "info": {}}]
    })
    fake = FakePanel(series_info=info)
    monkeypatch.setattr(xtream.requests, "get", fake)
    monkeypatch.setattr(xtream_loader.requests, "get", fake)

    session = connect(provider, providers_dir)
    xtream_loader.load(provider, session)
    serie = provider.series[0]
    xtream_loader.load_series(session, serie)
    episode = serie.seasons["1"].episodes["3"]
    assert episode.title == "Episode 3"
    assert episode.url.endswith("9001.mp4")  # container_extension defaulted


def test_a_series_with_no_episodes_reports_it(monkeypatch, provider, providers_dir):
    fake = FakePanel(series_info={"seasons": [], "episodes": {}})
    monkeypatch.setattr(xtream.requests, "get", fake)
    monkeypatch.setattr(xtream_loader.requests, "get", fake)

    session = connect(provider, providers_dir)
    xtream_loader.load(provider, session)
    with pytest.raises(xtream_loader.XtreamError, match="no episodes"):
        xtream_loader.load_series(session, provider.series[0])
