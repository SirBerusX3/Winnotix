#!/usr/bin/env python3
"""Regenerate resources/free_tv_catalogue.json.

The Free-TV repo publishes ~98 per-country playlists alongside its combined one,
but nothing machine-readable that lists them. This walks a checkout (or the live
repo) and writes the catalogue Winnotix ships.

    python tools/generate_catalogue.py --repo IPTVrepo       # local checkout
    python tools/generate_catalogue.py --fetch               # from GitHub

The catalogue is a convenience index, not a source of truth: Winnotix always
fetches the playlist itself at the recorded URL, so a stale channel count is
cosmetic. Re-run this when the repo adds or drops countries.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "resources" / "free_tv_catalogue.json"

RAW_BASE = "https://raw.githubusercontent.com/Free-TV/IPTV/master/"
API_LISTING = "https://api.github.com/repos/Free-TV/IPTV/contents/playlists?ref=master"

GROUP_TITLE = re.compile(r'group-title="([^"]*)"')
COUNTRY = re.compile(r'tvg-country="([^"]*)"')


def display_name(text: str, filename: str) -> str:
    """Prefer the playlist's own group title -- it has the right casing.

    The filename would give "usa" and "uk"; the group titles say "USA" and "UK".
    """
    titles = GROUP_TITLE.findall(text)
    if titles:
        # The per-country files use one group throughout.
        return max(set(titles), key=titles.count)
    stem = filename.removeprefix("playlist_").removesuffix(".m3u8")
    return stem.replace("_", " ").title()


def country_code(text: str, name: str) -> str:
    """Majority tvg-country, falling back to matching the display name.

    Not every per-country playlist tags its channels -- Lebanon's do not -- so
    the name match still earns its place.
    """
    codes = [c.upper() for c in COUNTRY.findall(text) if c.strip()]
    if codes:
        return max(set(codes), key=codes.count)
    sys.path.insert(0, str(ROOT))
    from winnotix.core.countries import code_for_name
    return code_for_name(name) or ""


def entry_for(filename: str, text: str) -> dict:
    name = display_name(text, filename)
    return {
        "name": name,
        "code": country_code(text, name),
        "file": filename,
        "url": f"{RAW_BASE}playlists/{filename}",
        "channels": text.count("#EXTINF"),
    }


def from_local(repo: Path) -> list[dict]:
    folder = repo / "playlists"
    if not folder.is_dir():
        raise SystemExit(f"no playlists/ directory in {repo}")
    entries = []
    for path in sorted(folder.glob("playlist_*.m3u8")):
        entries.append(entry_for(path.name, path.read_text(encoding="utf-8",
                                                           errors="ignore")))
    return entries


def from_network() -> list[dict]:
    import urllib.request

    def get(url: str) -> str:
        request = urllib.request.Request(url, headers={"User-Agent": "winnotix"})
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read().decode("utf-8", errors="ignore")

    listing = json.loads(get(API_LISTING))
    entries = []
    for item in sorted(listing, key=lambda i: i["name"]):
        name = item["name"]
        if not (name.startswith("playlist_") and name.endswith(".m3u8")):
            continue
        print(f"  {name}", file=sys.stderr)
        entries.append(entry_for(name, get(RAW_BASE + "playlists/" + name)))
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--repo", type=Path, default=ROOT / "IPTVrepo",
                        help="path to a Free-TV/IPTV checkout (default: ./IPTVrepo)")
    source.add_argument("--fetch", action="store_true",
                        help="read from github.com instead of a local checkout")
    args = parser.parse_args()

    entries = from_network() if args.fetch else from_local(args.repo)
    entries = [e for e in entries if e["channels"] > 0]
    entries.sort(key=lambda e: e["name"].lower())

    payload = {
        "source": "https://github.com/Free-TV/IPTV",
        "combined_url": RAW_BASE + "playlist.m3u8",
        "note": "Per-country playlists. Channel counts are indicative; the "
                "playlist itself is always fetched fresh at its url.",
        "playlists": entries,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")

    without_code = [e["name"] for e in entries if not e["code"]]
    print(f"wrote {OUT.relative_to(ROOT)}: {len(entries)} playlists, "
          f"{sum(e['channels'] for e in entries)} channels")
    if without_code:
        print(f"  no country code for: {', '.join(without_code)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
