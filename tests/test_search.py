"""Tests for cross-provider channel search (core/search.py).

The index is built from what is already cached, so the cases worth pinning are
the ones about *what is not there*: a provider with no cache file, an Xtream
provider whose channels never touch the playlist cache, and a cache file that
cannot be parsed. Each has to leave the search working and say what it left out.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from winnotix.core.common import Provider  # noqa: E402
from winnotix.core.search import ChannelIndex, locate  # noqa: E402


PLAYLIST = """#EXTM3U
#EXTINF:-1 tvg-name="BBC One" tvg-logo="https://x/1.png" group-title="UK",BBC One
http://host/bbc-one
#EXTINF:-1 tvg-name="BBC Two" group-title="UK",BBC Two
http://host/bbc-two
#EXTINF:-1 tvg-name="Sky News BBC Simulcast" group-title="UK",Sky News BBC Simulcast
http://host/sky
"""

OTHER = """#EXTM3U
#EXTINF:-1 tvg-name="BBC One HD" group-title="GB",BBC One HD
http://other/bbc-one-hd
#EXTINF:-1 tvg-name="ITV 1" group-title="GB",ITV 1
http://other/itv
"""


def make_provider(tmp_path, name, text, type_id="url"):
    """A provider whose cache file exists, the way an opened one would."""
    provider = Provider(
        name=None,
        provider_info=f"{name}:::{type_id}:::http://example/{name}:::::::::",
    )
    path = tmp_path / f"{name}.m3u"
    path.write_text(text, encoding="utf-8")
    provider.path = str(path)
    return provider


def test_it_indexes_every_cached_provider(tmp_path, manager):
    providers = [make_provider(tmp_path, "one", PLAYLIST),
                 make_provider(tmp_path, "two", OTHER)]
    index = ChannelIndex.build(providers, manager.load_channels)

    assert len(index) == 5
    assert index.providers == ["one", "two"]
    assert index.missing == []


def test_a_result_remembers_which_provider_it_came_from(tmp_path, manager):
    """Activating a result has to know which provider to switch to."""
    providers = [make_provider(tmp_path, "one", PLAYLIST),
                 make_provider(tmp_path, "two", OTHER)]
    index = ChannelIndex.build(providers, manager.load_channels)

    hits = index.search("bbc one")
    assert [hit.provider for hit in hits] == ["one", "two"]
    assert [hit.channel.search_provider for hit in hits] == ["one", "two"]


def test_a_name_that_starts_with_the_term_comes_first(tmp_path, manager):
    """Otherwise "bbc" leads with a channel that merely mentions the BBC."""
    index = ChannelIndex.build([make_provider(tmp_path, "one", PLAYLIST)],
                               manager.load_channels)

    names = [hit.name for hit in index.search("bbc")]
    assert names[:2] == ["BBC One", "BBC Two"]
    assert names[-1] == "Sky News BBC Simulcast"


def test_an_empty_term_matches_nothing(tmp_path, manager):
    """Not everything: an empty box means "I have not searched yet"."""
    index = ChannelIndex.build([make_provider(tmp_path, "one", PLAYLIST)],
                               manager.load_channels)
    assert index.search("") == []
    assert index.search("   ") == []


def test_the_search_is_capped(tmp_path, manager):
    lines = ["#EXTM3U"]
    for number in range(50):
        lines += [f'#EXTINF:-1 tvg-name="Channel {number}",Channel {number}',
                  f"http://host/{number}"]
    index = ChannelIndex.build(
        [make_provider(tmp_path, "big", "\n".join(lines))], manager.load_channels)

    assert len(index.search("channel", limit=10)) == 10


def test_a_provider_with_nothing_cached_is_named_not_fetched(tmp_path, manager):
    """The whole point of cached-only: no network, and say what was skipped."""
    cached = make_provider(tmp_path, "one", PLAYLIST)
    never_opened = Provider(
        name=None, provider_info="two:::url:::http://example/two:::::::::")
    never_opened.path = str(tmp_path / "does-not-exist")

    index = ChannelIndex.build([cached, never_opened], manager.load_channels)

    assert index.missing == ["two"]
    assert len(index) == 3


def test_an_xtream_provider_is_skipped(tmp_path, manager):
    """Its channels come from an authenticated API, not the playlist cache."""
    xtream = make_provider(tmp_path, "paid", PLAYLIST, type_id="xtream")
    index = ChannelIndex.build([xtream], manager.load_channels)

    assert index.missing == ["paid"]
    assert len(index) == 0


def test_an_unreadable_cache_file_does_not_fail_the_search(tmp_path, manager):
    good = make_provider(tmp_path, "one", PLAYLIST)
    broken = make_provider(tmp_path, "two", OTHER)

    def load(provider):
        if provider.name == "two":
            raise OSError("half-written")
        manager.load_channels(provider)

    index = ChannelIndex.build([good, broken], load)
    assert index.missing == ["two"]
    assert len(index) == 3


def test_the_blocklist_is_applied_when_given(tmp_path, manager):
    """A result the app would refuse to list is a result that wastes a click."""
    class OnlyBBCOne:
        def apply(self, provider):
            provider.channels[:] = [c for c in provider.channels
                                    if c.name == "BBC One"]

    index = ChannelIndex.build([make_provider(tmp_path, "one", PLAYLIST)],
                               manager.load_channels, blocklist=OnlyBBCOne())
    assert [hit.name for hit in index.hits] == ["BBC One"]


def test_indexing_does_not_disturb_the_live_provider(tmp_path, manager):
    """It parses into a copy: the provider on screen keeps its channel list."""
    provider = make_provider(tmp_path, "one", PLAYLIST)
    manager.load_channels(provider)
    before = list(provider.channels)

    ChannelIndex.build([provider], manager.load_channels)

    assert provider.channels == before
    assert not any(hasattr(c, "search_provider") for c in provider.channels)


# --------------------------------------------------------------------------
# Finding a result again once its provider is loaded
# --------------------------------------------------------------------------

def test_locate_finds_a_channel_and_its_group(tmp_path, manager):
    provider = make_provider(tmp_path, "one", PLAYLIST)
    manager.load_channels(provider)

    channel, group = locate(provider, "http://host/bbc-two")
    assert channel.name == "BBC Two"
    assert group.name == "UK"


def test_locate_finds_a_channel_genre_routing_moved(tmp_path, manager):
    """Routing takes a title *out* of provider.channels and puts it in a group
    of its own, so looking only at provider.channels reported a routed search
    result as "no longer in this provider" -- 1,356 of iptv-org's titles."""
    from winnotix.core.common import Group

    provider = make_provider(tmp_path, "one", PLAYLIST)
    manager.load_channels(provider)

    moved = next(c for c in provider.channels if c.name == "BBC Two")
    provider.channels.remove(moved)
    provider.groups[0].channels.remove(moved)
    routed = Group("UK SERIES")
    routed.channels.append(moved)
    provider.groups.append(routed)

    channel, group = locate(provider, "http://host/bbc-two")
    assert channel is moved
    assert group is routed


def test_locate_returns_nothing_for_a_url_that_has_gone(tmp_path, manager):
    provider = make_provider(tmp_path, "one", PLAYLIST)
    manager.load_channels(provider)

    assert locate(provider, "http://host/removed-yesterday") == (None, None)
