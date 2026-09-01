#!/usr/bin/env python3
"""Regenerate resources/channel_genres.json.

For an M3U provider every group is a TV_GROUP -- `Group.__init__` decides the
type by looking for the words "VOD" and "SERIES" in the group name
(`common.py:88-95`), and a country-grouped playlist never has them. So the
landing page's Movies and Series tiles are permanently empty for the two
catalogues Winnotix ships, however much film and drama they actually contain.

iptv-org classifies its channels and publishes the result in channels.json,
keyed by the same id our playlists carry in `tvg-id`. This tool reduces that to
the two categories we route on.

**What the data is, and is not.** `categories` is a *genre* taxonomy. It marks a
channel whose content is series or films; it does not mark "one show on a loop",
and no field in the record does -- the shape is id, name, alt_names, network,
owners, country, categories, is_nsfw, launched, closed, replaced_by, website. So
the `series` set mixes single-show channels (Baywatch, Cops, Degrassi) with
ordinary linear genre channels (AXN Asia, BBC Drama, Fox Life), and the `movies`
set is almost entirely linear film channels (AMC, Nova Cinema, Cinecanal) rather
than a video-on-demand library. Routing on it gives a genre browse, which is
what the tiles then mean.

**Channels tagged both are deliberately skipped** -- 138 of 2,572, including
AXN White beside Battlestar Galactica. Routing *moves* a channel out of its
country list, so it only happens where the classification is unambiguous; the
conservative failure is that a channel stays where it already was.

    python tools/generate_genres.py

As with the playlist catalogues, this index is generated rather than
hand-maintained. Re-run it when iptv-org reclassifies.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import date, timezone, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "resources" / "channel_genres.json"

API = "https://iptv-org.github.io/api/channels.json"

# The two upstream group types we can route into. Order is not significance --
# a channel carrying both is skipped rather than resolved by precedence.
ROUTED = ("series", "movies")


def get(url: str, timeout: int = 120, attempts: int = 3) -> str | None:
    request = urllib.request.Request(url, headers={"User-Agent": "winnotix"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError) as exc:
            if attempt == attempts - 1:
                print(f"error: could not fetch {url}: {exc}", file=sys.stderr)
                return None
    return None


def main() -> int:
    raw = get(API)
    if raw is None:
        return 1
    try:
        channels = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"error: {API} did not return JSON: {exc}", file=sys.stderr)
        return 1

    mapping: dict[str, str] = {}
    skipped_both = 0
    for channel in channels:
        identifier = channel.get("id")
        if not identifier:
            continue
        categories = set(channel.get("categories") or ())
        hits = [name for name in ROUTED if name in categories]
        if len(hits) != 1:
            skipped_both += len(hits) > 1
            continue
        mapping[identifier] = hits[0]

    counts = {name: sum(1 for v in mapping.values() if v == name) for name in ROUTED}
    document = {
        "version": 1,
        "source": API,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "note": (
            "tvg-id -> genre, for routing M3U channels into the Series and Movies "
            "tiles. A genre taxonomy, not a marker for single-show channels. "
            "Channels tagged both series and movies are omitted deliberately. "
            "Regenerate with tools/generate_genres.py."
        ),
        "counts": counts,
        "channels": dict(sorted(mapping.items())),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, indent=1, ensure_ascii=False, sort_keys=False)
        handle.write("\n")

    size = OUT.stat().st_size
    print(f"wrote {OUT.relative_to(ROOT)}  "
          f"{len(mapping)} channels ({counts['series']} series, "
          f"{counts['movies']} movies), {skipped_both} skipped as both, "
          f"{size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
