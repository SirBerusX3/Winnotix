"""Work out which country a channel group belongs to, for flags and badges.

Upstream infers this by lower-casing a group's name and comparing it against
`countries.list` (hypnotix.py:show_groups). That works only when the group name
is exactly a country name, so "Italy" matches but "VOD Italy" and "USA" do not.

The Free-TV playlist now tags most channels with `tvg-country`, an ISO 3166-1
alpha-2 code -- 1,788 of 2,059 entries -- so the group's country can be read from
its own channels instead of guessed from its name. That is tried first, with the
name match kept as a fallback.

Worth being straight about the payoff: on the Free-TV playlist this changes
almost nothing, because its groups are already named exactly after countries, so
upstream's match resolves 87 of 95 TV groups on its own. The tag path earns its
place on playlists whose group names are not country names ("UK | Entertainment"
from an Xtream provider, say), and the alias/noise-word handling below adds one
more group ("VOD Italy"). The visible win is the bundled flags themselves, which
upstream gets from a Debian package that has no Windows equivalent.
"""

from __future__ import annotations

from collections import Counter
from functools import lru_cache

from .paths import resources_dir

# Badge artwork bundled from upstream (resources/pictures/badges).
BADGE_WORDS = ("de", "en", "es", "fr", "it", "movies", "music", "news")

# Names that appear in playlists but not in countries.list, or that differ from
# it. Upstream misses every one of these.
NAME_ALIASES = {
    "usa": "US",
    "us": "US",
    "united states": "US",
    "uk": "GB",
    "united kingdom": "GB",
    "great britain": "GB",
    "britain": "GB",
    "england": "GB",
    "scotland": "GB",
    "wales": "GB",
    "america": "US",
    "holland": "NL",
    "netherlands": "NL",
    "south korea": "KR",
    "korea": "KR",
    "north korea": "KP",
    "russia": "RU",
    "czechia": "CZ",
    "czech republic": "CZ",
    "vietnam": "VN",
    "uae": "AE",
    "hong kong": "HK",
    "macau": "MO",
    "macao": "MO",
    "taiwan": "TW",
    "bosnia and herzegovina": "BA",
    "north macedonia": "MK",
    "macedonia": "MK",
    "moldova": "MD",
    "turkiye": "TR",
    "turkey": "TR",
    "iran": "IR",
    "syria": "SY",
    "venezuela": "VE",
    "bolivia": "BO",
    "tanzania": "TZ",
    "laos": "LA",
    # iptv-org's country names, where they differ from countries.list. Its
    # combined playlist groups by country, so an unmatched name costs a flag on
    # a tile. Reunion is not in countries.list at all.
    "democratic republic of the congo": "CD",
    "republic of the congo": "CG",
    "vatican city": "VA",
    "reunion": "RE",
}

# Words to strip before matching a group name against a country name.
_NOISE = {"vod", "series", "tv", "channels", "hd", "sd"}


@lru_cache(maxsize=1)
def country_codes() -> dict[str, str]:
    """Map lower-cased country name -> ISO code, from the bundled countries.list."""
    mapping: dict[str, str] = {}
    path = resources_dir() / "countries.list"
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or ":" not in line:
                    continue
                code, name = line.split(":", 1)
                mapping[name.strip().lower()] = code.strip().upper()
    except OSError as exc:
        print(f"[winnotix] could not read {path}: {exc}")
    mapping.update({name: code.upper() for name, code in NAME_ALIASES.items()})
    return mapping


@lru_cache(maxsize=512)
def code_for_name(name: str) -> str | None:
    """Resolve a group name to an ISO code, the way upstream tries to."""
    if not name:
        return None
    cleaned = name.lower().replace("(", " ").replace(")", " ").strip()
    codes = country_codes()
    if cleaned in codes:
        return codes[cleaned]
    # "VOD Italy" and "Italy TV" should still resolve to Italy.
    words = [w for w in cleaned.split() if w not in _NOISE]
    if words:
        stripped = " ".join(words)
        if stripped in codes:
            return codes[stripped]
    return None


def code_for_group(group) -> str | None:
    """The country of a group: whatever most of its channels say they are.

    Falls back to matching the group's name when the playlist carries no
    `tvg-country` tags.
    """
    tally = Counter(
        channel.country
        for channel in getattr(group, "channels", [])
        if getattr(channel, "country", None)
    )
    if tally:
        code, hits = tally.most_common(1)[0]
        # A group whose channels disagree is not really a country group; require
        # a clear majority before flying a flag over it.
        if hits * 2 >= sum(tally.values()):
            return code.upper()
    return code_for_name(getattr(group, "name", ""))


@lru_cache(maxsize=512)
def flag_file(code: str | None) -> str | None:
    """Path to the bundled circle-flag SVG for an ISO code, if we have one."""
    if not code:
        return None
    path = resources_dir() / "flags" / f"{code.lower()}.svg"
    return str(path) if path.is_file() else None


def badges_for_group(name: str) -> list[str]:
    """Upstream's badge logic: whole words in the group name with badge art."""
    if not name:
        return []
    words = name.lower().replace("(", " ").replace(")", " ").split()
    seen: list[str] = []
    for word in words:
        if word in BADGE_WORDS and word not in seen:
            seen.append(word)
    return seen


def badge_file(word: str) -> str | None:
    path = resources_dir() / "pictures" / "badges" / f"{word}.svg"
    return str(path) if path.is_file() else None
