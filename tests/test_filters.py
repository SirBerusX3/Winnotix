"""Tests for the unplayable-stream blocklist (winnotix/core/filters.py)."""

from __future__ import annotations

import json

import pytest

from winnotix.core.common import Provider
from winnotix.core.filters import Blocklist, FilterResult, Rule

from .conftest import write_m3u


PLUTO_URL = (
    "http://service-stitcher.clusters.pluto.tv/stitch/hls/channel/"
    "5ba3fb9c4b078e0f37ad34e8/master.m3u8?terminate=false"
)


@pytest.fixture
def pluto_rule():
    return Rule.from_dict({
        "id": "pluto-tv-takedown",
        "reason": "Pluto TV serves a takedown notice",
        "host_suffix": ".pluto.tv",
    })


# --------------------------------------------------------------------------
# Rule matching
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "url,expected",
    [
        (PLUTO_URL, True),
        ("https://service-stitcher.clusters.pluto.tv/v1/stitch/embed/hls/x", True),
        ("https://cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv/x", True),
        ("https://pluto.tv/watch", True),          # the bare domain also matches
        ("https://notpluto.tv/stream.m3u8", False),  # must not match by substring
        ("https://example.com/pluto.tv/x.m3u8", False),  # path, not host
        ("https://tv.a2news.com/live/x.m3u8", False),
        (None, False),
        ("", False),
    ],
)
def test_host_suffix_matching(pluto_rule, url, expected):
    assert pluto_rule.matches(url) is expected


def test_url_regex_matching():
    rule = Rule.from_dict({
        "id": "r", "reason": "x", "url_regex": r"/placeholder/\d+\.m3u8",
    })
    assert rule.matches("https://h/placeholder/42.m3u8")
    assert not rule.matches("https://h/real/42.m3u8")


def test_regex_matching_is_case_insensitive():
    rule = Rule.from_dict({"id": "r", "reason": "x", "url_regex": "TAKEDOWN"})
    assert rule.matches("https://h/takedown/x.m3u8")


def test_disabled_rule_never_matches():
    rule = Rule.from_dict({
        "id": "r", "reason": "x", "host_suffix": ".pluto.tv", "enabled": False,
    })
    assert not rule.matches(PLUTO_URL)


def test_rule_requires_an_id():
    with pytest.raises(ValueError):
        Rule.from_dict({"reason": "x", "host_suffix": ".pluto.tv"})


def test_rule_requires_a_matcher():
    with pytest.raises(ValueError):
        Rule.from_dict({"id": "r", "reason": "x"})


# --------------------------------------------------------------------------
# Applying to a provider
# --------------------------------------------------------------------------

def _provider_with(manager, tmp_path, providers_dir, body):
    provider = Provider("p", None)
    provider.path = str(write_m3u(tmp_path / "p.m3u", body))
    manager.load_channels(provider)
    return provider


def test_blocked_channels_are_removed_everywhere(manager, tmp_path, providers_dir,
                                                 pluto_rule):
    provider = _provider_with(manager, tmp_path, providers_dir, f"""
#EXTINF:-1 group-title="News",Good One
http://good.example/1
#EXTINF:-1 group-title="News",Pluto Bad
{PLUTO_URL}
""")
    assert len(provider.channels) == 2

    result = Blocklist([pluto_rule]).apply(provider)

    assert result.removed == 1
    assert result.by_rule["pluto-tv-takedown"] == 1
    assert [c.name for c in provider.channels] == ["Good One"]
    assert [c.name for c in provider.groups[0].channels] == ["Good One"]


def test_each_channel_counted_once_despite_appearing_in_several_lists(
        manager, tmp_path, providers_dir, pluto_rule):
    """A Channel is shared between provider.channels and its group."""
    provider = _provider_with(manager, tmp_path, providers_dir, f"""
#EXTINF:-1 group-title="News",Pluto A
{PLUTO_URL}
#EXTINF:-1 group-title="News",Pluto B
{PLUTO_URL}2
""")
    result = Blocklist([pluto_rule]).apply(provider)
    assert result.removed == 2


def test_movies_are_filtered_too(manager, tmp_path, providers_dir, pluto_rule):
    provider = _provider_with(manager, tmp_path, providers_dir, f"""
#EXTINF:-1 group-title="VOD Movies",Pluto Film
{PLUTO_URL}
#EXTINF:-1 group-title="VOD Movies",Real Film
http://good.example/film
""")
    assert len(provider.movies) == 2
    Blocklist([pluto_rule]).apply(provider)
    assert [c.name for c in provider.movies] == ["Real Film"]


def test_emptied_groups_are_dropped(manager, tmp_path, providers_dir, pluto_rule):
    """A group left with nothing would otherwise render as 'Name (0)'."""
    provider = _provider_with(manager, tmp_path, providers_dir, f"""
#EXTINF:-1 group-title="AllBad",Pluto Only
{PLUTO_URL}
#EXTINF:-1 group-title="Mixed",Good
http://good.example/1
""")
    assert [g.name for g in provider.groups] == ["AllBad", "Mixed"]
    Blocklist([pluto_rule]).apply(provider)
    assert [g.name for g in provider.groups] == ["Mixed"]


def test_series_episodes_and_empty_series_are_cleaned(manager, tmp_path,
                                                      providers_dir, pluto_rule):
    provider = _provider_with(manager, tmp_path, providers_dir, f"""
#EXTINF:-1,Good Show S01E01
http://good.example/1
#EXTINF:-1,Good Show S01E02
{PLUTO_URL}
#EXTINF:-1,Dead Show S01E01
{PLUTO_URL}2
""")
    assert len(provider.series) == 2

    Blocklist([pluto_rule]).apply(provider)

    assert [s.name for s in provider.series] == ["Good Show"]
    good = provider.series[0]
    assert len(good.episodes) == 1
    assert list(good.seasons["01"].episodes) == ["01"]


def test_nothing_blocked_leaves_provider_untouched(manager, tmp_path,
                                                   providers_dir, pluto_rule):
    provider = _provider_with(manager, tmp_path, providers_dir, """
#EXTINF:-1 group-title="News",Good
http://good.example/1
""")
    result = Blocklist([pluto_rule]).apply(provider)
    assert result.removed == 0
    assert len(provider.channels) == 1
    assert len(provider.groups) == 1


def test_empty_blocklist_is_a_no_op(manager, tmp_path, providers_dir):
    provider = _provider_with(manager, tmp_path, providers_dir, f"""
#EXTINF:-1,Pluto
{PLUTO_URL}
""")
    result = Blocklist([]).apply(provider)
    assert result.removed == 0
    assert len(provider.channels) == 1


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def test_summary_is_empty_when_nothing_removed():
    assert FilterResult().summary() == ""


def test_summary_names_the_reason(manager, tmp_path, providers_dir, pluto_rule):
    provider = _provider_with(manager, tmp_path, providers_dir, f"""
#EXTINF:-1,Pluto
{PLUTO_URL}
""")
    result = Blocklist([pluto_rule]).apply(provider)
    assert result.summary() == "Hid 1 unplayable: 1 Pluto TV serves a takedown notice"


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def test_shipped_blocklist_loads_and_covers_pluto(tmp_path):
    """The rule that ships with the app must actually match real Pluto URLs.

    `user` points at a nonexistent path so the developer's own blocklist cannot
    influence the result.
    """
    blocklist = Blocklist.load(user=tmp_path / "no-user-rules.json")
    assert blocklist.rules, "the bundled blocklist should not be empty"

    matched = blocklist.match(PLUTO_URL)
    assert matched is not None
    assert matched.id == "pluto-tv-takedown"
    assert matched.reason

    # Both real Pluto hosts seen in the Free-TV playlist.
    assert blocklist.match(
        "https://service-stitcher.clusters.pluto.tv/v1/stitch/embed/hls/c/m.m3u8")
    assert blocklist.match(
        "https://cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv/x.m3u8")
    # And nothing else.
    assert blocklist.match("https://tv.a2news.com/live/smil:x.smil/playlist.m3u8") is None


def test_user_rules_are_merged(tmp_path):
    bundled = tmp_path / "bundled.json"
    bundled.write_text(json.dumps({"rules": [
        {"id": "a", "reason": "built-in", "host_suffix": ".a.example"},
    ]}), encoding="utf-8")
    user = tmp_path / "user.json"
    user.write_text(json.dumps({"rules": [
        {"id": "b", "reason": "mine", "host_suffix": ".b.example"},
    ]}), encoding="utf-8")

    blocklist = Blocklist.load(bundled=bundled, user=user)
    assert {r.id for r in blocklist.rules} == {"a", "b"}


def test_user_rule_can_disable_a_builtin(tmp_path):
    bundled = tmp_path / "bundled.json"
    bundled.write_text(json.dumps({"rules": [
        {"id": "a", "reason": "built-in", "host_suffix": ".a.example"},
    ]}), encoding="utf-8")
    user = tmp_path / "user.json"
    user.write_text(json.dumps({"rules": [
        {"id": "a", "reason": "built-in", "host_suffix": ".a.example",
         "enabled": False},
    ]}), encoding="utf-8")

    blocklist = Blocklist.load(bundled=bundled, user=user)
    assert blocklist.match("https://x.a.example/s.m3u8") is None


def test_missing_files_are_tolerated(tmp_path):
    blocklist = Blocklist.load(bundled=tmp_path / "nope.json",
                               user=tmp_path / "also-nope.json")
    assert blocklist.rules == []


def test_corrupt_file_does_not_raise(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    blocklist = Blocklist.load(bundled=bad, user=tmp_path / "nope.json")
    assert blocklist.rules == []


def test_a_bad_rule_does_not_discard_the_good_ones(tmp_path):
    bundled = tmp_path / "b.json"
    bundled.write_text(json.dumps({"rules": [
        {"id": "broken", "reason": "no matcher"},
        {"id": "fine", "reason": "ok", "host_suffix": ".ok.example"},
    ]}), encoding="utf-8")
    blocklist = Blocklist.load(bundled=bundled, user=tmp_path / "nope.json")
    assert {r.id for r in blocklist.rules} == {"fine"}


def test_invalid_regex_is_skipped(tmp_path):
    bundled = tmp_path / "b.json"
    bundled.write_text(json.dumps({"rules": [
        {"id": "bad-re", "reason": "x", "url_regex": "([unclosed"},
        {"id": "fine", "reason": "ok", "host_suffix": ".ok.example"},
    ]}), encoding="utf-8")
    blocklist = Blocklist.load(bundled=bundled, user=tmp_path / "nope.json")
    assert {r.id for r in blocklist.rules} == {"fine"}
