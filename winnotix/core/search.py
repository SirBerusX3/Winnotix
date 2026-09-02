"""Search channels across every provider, not just the one that is open.

A country playlist runs to hundreds of rows and a combined one to thousands, so
the channel filter in the sidebar answers "where is BBC One in this list". This
answers the other question: "which of my providers has BBC One at all".

**Cached only, deliberately.** The index is built from the playlists already on
disk in ``%LOCALAPPDATA%\\Winnotix\\cache\\providers``, and a provider that has
never been opened is reported as missing rather than downloaded. Ticking a
checkbox is not consent to fetch 14 MB, which is what `iptv-org All countries`
costs; the UI offers to load a missing provider instead, so the cost is paid
where it can be seen.

**Built once, then queried in memory.** Parsing every cached playlist takes long
enough to be worth doing on a worker thread, and far too long to repeat on each
keystroke.

Two things this deliberately does not do:

- **It does not route by genre.** Routing moves a channel out of the TV list
  into Movies or Series, which is a browsing decision; a search should find a
  channel wherever it would otherwise have been filed.
- **It does apply the blocklist**, when the caller passes one. A result the app
  would refuse to list is a result that wastes a click.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Iterable

#: Xtream providers are not in the playlist cache -- their channels come from an
#: authenticated API, and reaching for them would mean a network round trip and
#: a password, which is exactly what "cached only" rules out.
XTREAM_TYPE = "xtream"


@dataclass(frozen=True)
class Hit:
    provider: str
    channel: Any

    @property
    def name(self) -> str:
        return self.channel.name or ""


class ChannelIndex:
    """Every channel in every cached provider, ready to be searched."""

    def __init__(self, hits: list[Hit], missing: list[str]) -> None:
        self.hits = hits
        #: Providers left out because nothing is cached for them yet. The UI
        #: names these rather than quietly returning fewer results.
        self.missing = missing
        # Matched against once per keystroke, so it is worth not lowercasing
        # every name again each time.
        self._needles = [(hit.name.lower(), hit) for hit in hits]

    def __len__(self) -> int:
        return len(self.hits)

    @property
    def providers(self) -> list[str]:
        """The providers actually represented, in the order they were indexed."""
        return list(dict.fromkeys(hit.provider for hit in self.hits))

    @classmethod
    def build(cls, providers: Iterable, load: Callable, *,
              blocklist=None) -> "ChannelIndex":
        """Index every provider whose playlist is already on disk.

        `load` parses a provider in place from `provider.path` -- in the app
        that is `Manager.load_channels`, which is used rather than a private
        parser so that a search finds exactly what opening the provider would.
        """
        hits: list[Hit] = []
        missing: list[str] = []
        for provider in providers:
            if getattr(provider, "type_id", "") == XTREAM_TYPE:
                missing.append(provider.name)
                continue
            if not provider.path or not os.path.exists(provider.path):
                missing.append(provider.name)
                continue
            copy = _fresh_copy(provider)
            try:
                load(copy)
            except Exception:
                # A truncated or half-written cache file is not worth failing
                # the whole search for; the provider simply goes unrepresented.
                missing.append(provider.name)
                continue
            if blocklist is not None:
                blocklist.apply(copy)
            for channel in copy.channels:
                if not channel.url:
                    continue
                # Tagged on the channel itself so that activating a result
                # knows which provider to switch to. These objects belong to
                # this index -- the live providers keep their own.
                channel.search_provider = provider.name
                hits.append(Hit(provider.name, channel))
        return cls(hits, missing)

    def search(self, term: str, limit: int = 300) -> list[Hit]:
        """Matches for `term`, best first, capped at `limit`.

        Ordering is by where the term appears: a channel whose name starts with
        it before one that merely contains it, so "bbc" leads with BBC One
        rather than with a channel that mentions the BBC halfway through.
        """
        needle = term.strip().lower()
        if not needle:
            return []
        starts, contains = [], []
        for name, hit in self._needles:
            position = name.find(needle)
            if position == 0:
                starts.append(hit)
            elif position > 0:
                contains.append(hit)
            if len(starts) >= limit:
                break
        return (starts + contains)[:limit]


def locate(provider, url: str):
    """Find `url` in a loaded provider, returning (channel, group).

    Searches the groups rather than `provider.channels`, because genre routing
    moves a channel *out* of that list: a title filed under Movies or Series is
    absent from `provider.channels` while still being present in the provider.
    Looking only there reported a routed result as "no longer in this provider"
    -- which, with routing on, is 1,356 of iptv-org's titles.

    Returns (None, None) when the playlist no longer carries the URL, which a
    refresh between building the index and opening a result would explain.
    """
    for group in provider.groups:
        for channel in group.channels:
            if channel.url == url:
                return channel, group
    # A channel with no group at all: possible for a playlist whose entries
    # carry no group-title, where upstream's parser groups by an empty name.
    for channel in provider.channels:
        if channel.url == url:
            return channel, None
    return None, None


def _fresh_copy(provider):
    """A throwaway Provider pointing at the same cache file.

    Parsing into the live provider would replace the channel list the user is
    looking at, and parsing into the *active* one would do it while they watch.
    """
    from .common import Provider

    copy = Provider(name=None, provider_info=provider.get_info())
    copy.path = provider.path
    return copy
