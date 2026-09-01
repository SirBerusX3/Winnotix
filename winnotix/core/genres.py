"""Route M3U channels into the Series and Movies tiles by genre.

For an M3U provider every group is a ``TV_GROUP``. ``Group.__init__`` decides
the type by looking for the words "VOD" and "SERIES" in the group name
(``common.py:88-95``), and a country-grouped playlist never has them, so the
landing page's Movies and Series tiles are permanently empty for both bundled
catalogues -- however much film and drama they actually contain. iptv-org
classifies its channels by the same ``tvg-id`` our playlists carry, which is
enough to fill them.

**This is a genre browse, not a single-show collection.** iptv-org's
``categories`` marks what a channel *shows*; nothing in its data marks "one show
on a loop", so the series set mixes Baywatch and Cops with AXN Asia and BBC
Drama, and the movies set is linear film channels rather than a video-on-demand
library. ``tools/generate_genres.py`` documents the measurement behind that.

Two details that are easy to get wrong:

* **The ids need normalising.** iptv-org's published playlists append a feed
  suffix -- ``BBCOne.uk@SD`` -- while its API keys on the bare ``BBCOne.uk``.
  Joining the two raw matches 1 of 12,358 entries; normalising first matches
  12,336. That happens here rather than in ``common.py:141`` so the parser stays
  at its five documented deviations from upstream.
* **Routing runs after the blocklist, never before.** 503 of the 689 channels
  iptv-org classifies as series are Pluto TV behind the ``jmp2.uk`` redirector,
  so routing first would fill a fresh page with takedown slates.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .common import MOVIES_GROUP, SERIES_GROUP, TV_GROUP, Group
from .paths import resources_dir

GENRES_NAME = "channel_genres.json"

#: The genre names in the index, and the upstream group type each routes into.
KINDS = {"series": SERIES_GROUP, "movies": MOVIES_GROUP}

#: Set on the Group objects this module creates. Distinguishes a group we
#: synthesised from one a playlist named "SERIES ..." itself, which already
#: carries real Serie objects and must not be counted as channels.
ROUTED_FLAG = "from_genre"


def normalise_id(tvg_id: str | None) -> str:
    """Strip iptv-org's feed suffix, so a playlist id matches an API id."""
    if not tvg_id:
        return ""
    return tvg_id.split("@", 1)[0].strip()


def routed_groups(provider, group_type: int) -> list:
    """The groups this module created for `group_type`, in playlist order."""
    return [group for group in provider.groups
            if group.group_type == group_type
            and getattr(group, ROUTED_FLAG, False)]


def series_channels(provider) -> list:
    """Channels routed into Series, which are Channels rather than Serie objects.

    The Series page shows ``provider.series`` for an Xtream provider, where a
    series really does have seasons and episodes. A routed channel has neither,
    so it is counted and displayed from its group instead of being pushed into
    ``provider.series``, which would break every consumer expecting a Serie.
    """
    channels = []
    for group in routed_groups(provider, SERIES_GROUP):
        channels.extend(group.channels)
    return channels


def series_total(provider) -> int:
    """What the landing tile counts: real series plus routed channels."""
    return len(provider.series) + len(series_channels(provider))


@dataclass
class RouteResult:
    moved: int = 0
    by_kind: Counter = field(default_factory=Counter)

    def summary(self) -> str:
        if not self.moved:
            return ""
        parts = [f"{count} to {kind.title()}"
                 for kind, count in self.by_kind.most_common()]
        return "Sorted " + ", ".join(parts)


class GenreIndex:
    """tvg-id -> "series" | "movies", loaded from the bundled index."""

    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self.mapping = mapping or {}

    def __bool__(self) -> bool:
        return bool(self.mapping)

    @classmethod
    def load(cls, path: Path | None = None) -> "GenreIndex":
        path = path if path is not None else resources_dir() / GENRES_NAME
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return cls({})
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[winnotix] ignoring unreadable genre index {path}: {exc}")
            return cls({})
        channels = data.get("channels") if isinstance(data, dict) else None
        if not isinstance(channels, dict):
            return cls({})
        return cls({str(k): str(v) for k, v in channels.items() if v in KINDS})

    def kind_for(self, channel) -> str | None:
        return self.mapping.get(normalise_id(getattr(channel, "id", None)))

    # -- routing -------------------------------------------------------

    def route(self, provider) -> RouteResult:
        """Move classified channels out of TV groups into typed parallels.

        In place, and idempotent: a group this module already created is never
        re-examined, so routing twice cannot cascade.
        """
        result = RouteResult()
        if not self.mapping:
            return result

        # Only groups the playlist itself produced as TV. A provider that
        # already has real Movies and Series -- any Xtream one -- is left alone.
        sources = [group for group in provider.groups
                   if group.group_type == TV_GROUP
                   and not getattr(group, ROUTED_FLAG, False)]
        if not sources:
            return result

        created: dict[tuple[str, str], Group] = {}
        moved: set[int] = set()

        for group in sources:
            keep = []
            for channel in group.channels:
                kind = self.kind_for(channel)
                if kind is None:
                    keep.append(channel)
                    continue
                target = created.get((group.name, kind))
                if target is None:
                    target = Group(group.name)
                    target.group_type = KINDS[kind]
                    setattr(target, ROUTED_FLAG, True)
                    created[(group.name, kind)] = target
                target.channels.append(channel)
                moved.add(id(channel))
                result.by_kind[kind] += 1
            group.channels = keep

        if not created:
            return result

        result.moved = sum(result.by_kind.values())

        provider.channels = [c for c in provider.channels if id(c) not in moved]
        for (_name, kind), group in created.items():
            provider.groups.append(group)
            if kind == "movies":
                provider.movies.extend(group.channels)

        # A country group whose every channel was film or drama would otherwise
        # show as "Name (0)" on the categories page.
        provider.groups = [group for group in provider.groups
                           if group.channels or group.series]
        return result
