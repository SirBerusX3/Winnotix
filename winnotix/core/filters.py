"""Exclude streams that resolve but do not play what they advertise.

Public IPTV playlists rot. The easy failures announce themselves -- a 404, a
refused connection -- and mpv reports those. The awkward ones return HTTP 200
and a perfectly valid HLS manifest whose content is a filler clip: a takedown
notice, a "watch on our website" slate, a geo-block card. Nothing in the
playlist or the response distinguishes those from a working stream, so they have
to be named.

Rules live in data (resources/blocklist.json), not in code, for two reasons:
the parser in common.py stays byte-comparable with upstream Hypnotix, and a rule
can be added or retired without a release. Users can override or extend the
built-in set from their own blocklist.json in the Winnotix data directory.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .paths import DATA_DIR, resources_dir

USER_BLOCKLIST_NAME = "blocklist.json"


@dataclass(frozen=True)
class Rule:
    id: str
    reason: str
    host_suffix: str = ""
    url_regex: str = ""
    enabled: bool = True
    verified: str = ""
    notes: str = ""
    _compiled: re.Pattern | None = field(default=None, compare=False, repr=False)

    @classmethod
    def from_dict(cls, data: dict) -> "Rule":
        if not data.get("id"):
            raise ValueError("blocklist rule needs an 'id'")
        if not data.get("host_suffix") and not data.get("url_regex"):
            raise ValueError(
                f"blocklist rule {data['id']!r} needs host_suffix or url_regex"
            )
        pattern = None
        if data.get("url_regex"):
            pattern = re.compile(data["url_regex"], re.IGNORECASE)
        return cls(
            id=data["id"],
            reason=data.get("reason", ""),
            host_suffix=data.get("host_suffix", "").lower(),
            url_regex=data.get("url_regex", ""),
            enabled=bool(data.get("enabled", True)),
            verified=data.get("verified", ""),
            notes=data.get("notes", ""),
            _compiled=pattern,
        )

    def matches(self, url: str | None) -> bool:
        if not url or not self.enabled:
            return False
        if self.host_suffix:
            host = urlparse(url).hostname or ""
            host = host.lower()
            # ".pluto.tv" should match both "pluto.tv" and "a.b.pluto.tv".
            bare = self.host_suffix.lstrip(".")
            if host == bare or host.endswith(self.host_suffix):
                return True
        if self._compiled is not None and self._compiled.search(url):
            return True
        return False


@dataclass
class FilterResult:
    removed: int = 0
    by_rule: Counter = field(default_factory=Counter)
    reasons: dict[str, str] = field(default_factory=dict)

    def summary(self) -> str:
        """One line naming why things were hidden, for the status bar."""
        if not self.removed:
            return ""
        parts = [
            f"{count} {self.reasons.get(rule_id, rule_id)}"
            for rule_id, count in self.by_rule.most_common()
        ]
        return f"Hid {self.removed} unplayable: " + "; ".join(parts)


class Blocklist:
    def __init__(self, rules: list[Rule] | None = None) -> None:
        self.rules = rules or []

    # -- loading -------------------------------------------------------

    @staticmethod
    def _read(path: Path) -> list[dict]:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return []
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[winnotix] ignoring unreadable blocklist {path}: {exc}")
            return []
        rules = data.get("rules") if isinstance(data, dict) else data
        return rules if isinstance(rules, list) else []

    @classmethod
    def load(cls, bundled: Path | None = None, user: Path | None = None) -> "Blocklist":
        bundled = bundled if bundled is not None else resources_dir() / "blocklist.json"
        user = user if user is not None else DATA_DIR / USER_BLOCKLIST_NAME

        merged: dict[str, Rule] = {}
        for path in (bundled, user):
            for raw in cls._read(path):
                try:
                    rule = Rule.from_dict(raw)
                except (ValueError, re.error) as exc:
                    print(f"[winnotix] skipping bad blocklist rule in {path}: {exc}")
                    continue
                merged[rule.id] = rule  # user entries replace built-ins by id
        return cls(list(merged.values()))

    # -- matching ------------------------------------------------------

    def match(self, url: str | None) -> Rule | None:
        for rule in self.rules:
            if rule.matches(url):
                return rule
        return None

    def apply(self, provider) -> FilterResult:
        """Drop blocked channels from a loaded provider, in place."""
        result = FilterResult()
        if not any(rule.enabled for rule in self.rules):
            return result

        # Gather every channel object once. The same Channel instance appears in
        # several collections, so matching per-collection would count it twice.
        everything = set(provider.channels) | set(provider.movies)
        for group in provider.groups:
            everything.update(group.channels)
        for serie in provider.series:
            everything.update(serie.episodes)

        blocked: dict[object, Rule] = {}
        for channel in everything:
            rule = self.match(channel.url)
            if rule is not None:
                blocked[channel] = rule
        if not blocked:
            return result

        result.removed = len(blocked)
        result.by_rule = Counter(rule.id for rule in blocked.values())
        result.reasons = {rule.id: rule.reason for rule in blocked.values()}

        def keep(items):
            return [item for item in items if item not in blocked]

        provider.channels = keep(provider.channels)
        provider.movies = keep(provider.movies)

        for serie in provider.series:
            serie.episodes = keep(serie.episodes)
            for season in list(serie.seasons.values()):
                season.episodes = {
                    name: episode
                    for name, episode in season.episodes.items()
                    if episode not in blocked
                }
            serie.seasons = {
                name: season
                for name, season in serie.seasons.items()
                if season.episodes
            }

        live_series = [serie for serie in provider.series if serie.episodes]
        dead_series = set(provider.series) - set(live_series)
        provider.series = live_series

        for group in provider.groups:
            group.channels = keep(group.channels)
            group.series = [s for s in group.series if s not in dead_series]

        # A group emptied by filtering would otherwise show as "Name (0)".
        provider.groups = [
            group for group in provider.groups if group.channels or group.series
        ]
        return result
