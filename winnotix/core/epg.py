"""Programme guide: XMLTV fetched from the guides a playlist declares.

Upstream Hypnotix has no guide at all. It stores a per-provider EPG URL --
``Provider.epg``, the sixth field of the ``:::`` format, and an entry box on the
Add-provider form -- and then never reads it. This module is what makes that
field mean something.

**Where guides come from.** The M3U standard puts them in the playlist itself:
``#EXTM3U x-tvg-url="...,..."``. Free-TV's playlist declares 101 gzipped XMLTV
files that way, mostly one per country (``epg_ripper_UK1.xml.gz``). iptv-org
declares none, and publishes none either -- its ``epg`` repository is a grabber
you run yourself, and its ``guides.json`` maps channels to scraper *sites*
rather than to XMLTV -- so an iptv-org provider borrows whatever guides the
user names in the provider's own EPG field, or goes without.

**Only what is needed is fetched.** The combined ``ALL_SOURCES`` guide is 191 MB
gzipped; a single country is 2.6 MB gz for 486 channels and 41,299 programmes.
So guides are selected by country and fetched when a group is opened, not up
front, and cached on disk between runs.

**Matching is the hard part, and it is partial by nature.** Guide ids and
playlist ids are unrelated schemes -- epgshare says ``BBC.One.West.HD.uk`` where
our playlists say ``BBCOne.uk`` -- so an id join matches 4 of 55 channels on the
Free-TV UK playlist (7%) and 4 of 310 on iptv-org's UK group (1%). Matching on
the guide's ``display-name`` instead lifts those to 36/55 (65%) and 55/310
(17%). The remainder genuinely are not in the guide: a UK broadcast EPG carries
486 real channels, while iptv-org's UK group is largely niche and diaspora
streams nobody publishes listings for. A channel with no match shows nothing,
which is the honest outcome -- there is no programme information to show.
"""

from __future__ import annotations

import gzip
import io
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from . import countries
from .paths import CACHE_DIR

EPG_CACHE = CACHE_DIR / "epg"

#: How long a downloaded guide is reused before being re-fetched. Listings move
#: slowly and a guide covers days, so this is about not re-downloading 2.6 MB
#: on every group change rather than about freshness.
CACHE_TTL_SECONDS = 6 * 60 * 60

#: Programmes outside this window are discarded while parsing. A guide file
#: holds days of listings and we only ever show now and next, so keeping the
#: lot would cost memory for nothing.
KEEP_BEFORE = timedelta(hours=2)
KEEP_AFTER = timedelta(hours=36)

#: Both spellings appear in the wild; Free-TV uses the first.
_TVG_URL = re.compile(r'(?:x-tvg-url|url-tvg)\s*=\s*"(.*?)"', re.IGNORECASE)

#: epg_ripper_UK1.xml.gz -> UK. Only used to avoid downloading 101 files when
#: one will do; a guide whose name does not match this is simply never
#: auto-selected, and can still be used if named explicitly.
_GUIDE_COUNTRY = re.compile(r"epg_ripper_([A-Za-z]{2})\d*\.xml", re.IGNORECASE)

#: Resolution and status markers playlists append to channel names.
_NAME_NOISE = re.compile(r"\(.*?\)|\[.*?\]")
#: Quality qualifiers that a guide and a playlist disagree about constantly.
_QUALITY = re.compile(r"\b(hd|sd|uhd|fhd|4k|hevc|h265|1080p|720p|480p)\b", re.IGNORECASE)


def normalise_id(tvg_id: str | None) -> str:
    """Strip iptv-org's feed suffix -- BBCOne.uk@SD -> BBCOne.uk."""
    if not tvg_id:
        return ""
    return tvg_id.split("@", 1)[0].strip()


def normalise_name(name: str | None) -> str:
    """Reduce a channel name to something two sources might agree on."""
    if not name:
        return ""
    text = _NAME_NOISE.sub(" ", name)
    text = _QUALITY.sub(" ", text)
    return re.sub(r"[^a-z0-9]", "", text.lower())


def guide_urls(playlist_path: str | Path | None, provider=None) -> list[str]:
    """Every guide this provider knows about, provider's own field first.

    The provider field is deliberately first: it is the user's explicit choice,
    and for an iptv-org provider it is the only source there is.
    """
    urls: list[str] = []
    epg = (getattr(provider, "epg", "") or "").strip()
    if epg:
        urls.extend(part.strip() for part in epg.split(",") if part.strip())
    urls.extend(playlist_guide_urls(playlist_path))
    seen, unique = set(), []
    for url in urls:
        if url not in seen and url.lower().startswith(("http://", "https://")):
            seen.add(url)
            unique.append(url)
    return unique


def playlist_guide_urls(playlist_path: str | Path | None) -> list[str]:
    """Read x-tvg-url out of a cached playlist's #EXTM3U header."""
    if not playlist_path:
        return []
    try:
        with open(playlist_path, "r", encoding="utf-8", errors="ignore") as handle:
            header = handle.readline()
    except OSError:
        return []
    if not header.startswith("#EXTM3U"):
        return []
    match = _TVG_URL.search(header)
    if match is None:
        return []
    return [part.strip() for part in match.group(1).split(",") if part.strip()]


@lru_cache(maxsize=1)
def _iso_codes() -> frozenset:
    return frozenset(countries.country_codes().values())


def guide_country(url: str) -> str | None:
    """The ISO code a guide filename advertises, if it follows the convention.

    Guide filenames are *not* reliably ISO. Across the 101 guides Free-TV
    declares, 64 carry a two-letter code and exactly one of them is not an ISO
    code: `epg_ripper_UK1` for the United Kingdom, which ISO calls GB. Missing
    that one alias would silently cost the UK its listings, so a code that is
    not ISO is resolved as a name -- which is where `UK -> GB` already lives.
    """
    match = _GUIDE_COUNTRY.search(url.rsplit("/", 1)[-1])
    if match is None:
        return None
    code = match.group(1).upper()
    if code in _iso_codes():
        return code
    return countries.code_for_name(code)


def urls_for_country(urls, code: str | None) -> list[str]:
    """Guides that advertise `code`. Empty when none do, never everything."""
    if not code:
        return []
    code = code.upper()
    return [u for u in urls if guide_country(u) == code]


def _parse_time(value: str) -> datetime | None:
    """XMLTV time: 20260901183000 +0100, offset optional."""
    if not value:
        return None
    parts = value.strip().split()
    stamp = parts[0][:14]
    if len(stamp) < 14 or not stamp.isdigit():
        return None
    try:
        moment = datetime.strptime(stamp, "%Y%m%d%H%M%S")
    except ValueError:
        return None
    if len(parts) > 1 and len(parts[1]) == 5 and parts[1][0] in "+-":
        try:
            sign = 1 if parts[1][0] == "+" else -1
            offset = timedelta(hours=int(parts[1][1:3]), minutes=int(parts[1][3:5]))
            return moment.replace(tzinfo=timezone(sign * offset))
        except ValueError:
            pass
    return moment.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Programme:
    start: datetime
    stop: datetime | None
    title: str
    description: str = ""

    def covers(self, moment: datetime) -> bool:
        if moment < self.start:
            return False
        return self.stop is None or moment < self.stop

    def when(self) -> str:
        """"18:30 - 19:00", in the viewer's own time zone."""
        start = self.start.astimezone()
        if self.stop is None:
            return start.strftime("%H:%M")
        return f"{start.strftime('%H:%M')} - {self.stop.astimezone().strftime('%H:%M')}"


class Guide:
    """One parsed XMLTV document, indexed for lookup by id and by name."""

    def __init__(self) -> None:
        self.by_id: dict[str, str] = {}      # guide channel id -> itself
        self.by_name: dict[str, str] = {}    # normalised display name -> id
        self.programmes: dict[str, list[Programme]] = {}

    def __bool__(self) -> bool:
        return bool(self.programmes)

    @property
    def channel_count(self) -> int:
        return len(self.by_id)

    @property
    def programme_count(self) -> int:
        return sum(len(v) for v in self.programmes.values())

    # -- parsing -------------------------------------------------------

    @classmethod
    def parse(cls, xml: bytes, now: datetime | None = None) -> "Guide":
        """Parse XMLTV, keeping only programmes near `now`.

        iterparse and clear(), because these documents run to 20 MB and holding
        the whole tree to read a fraction of it is the obvious way to make a
        guide feel expensive.
        """
        guide = cls()
        now = now or datetime.now(timezone.utc)
        earliest, latest = now - KEEP_BEFORE, now + KEEP_AFTER

        try:
            for _event, element in ET.iterparse(io.BytesIO(xml), events=("end",)):
                if element.tag == "channel":
                    identifier = (element.get("id") or "").strip()
                    if identifier:
                        guide.by_id[identifier] = identifier
                        for display in element.findall("display-name"):
                            key = normalise_name(display.text or "")
                            if key:
                                guide.by_name.setdefault(key, identifier)
                    element.clear()
                elif element.tag == "programme":
                    start = _parse_time(element.get("start") or "")
                    if start is None:
                        element.clear()
                        continue
                    stop = _parse_time(element.get("stop") or "")
                    if (stop or start) < earliest or start > latest:
                        element.clear()
                        continue
                    channel = (element.get("channel") or "").strip()
                    title = (element.findtext("title") or "").strip()
                    if channel and title:
                        guide.programmes.setdefault(channel, []).append(Programme(
                            start=start,
                            stop=stop,
                            title=title,
                            description=(element.findtext("desc") or "").strip(),
                        ))
                    element.clear()
        except ET.ParseError as exc:
            print(f"[winnotix] ignoring malformed guide: {exc}")
            return cls()

        for entries in guide.programmes.values():
            entries.sort(key=lambda p: p.start)
        return guide

    # -- lookup --------------------------------------------------------

    def key_for(self, channel) -> str | None:
        """The guide's id for a playlist channel: by id first, then by name."""
        identifier = normalise_id(getattr(channel, "id", None))
        if identifier and identifier in self.by_id:
            return identifier
        key = normalise_name(getattr(channel, "name", None))
        if key and key in self.by_name:
            return self.by_name[key]
        return None

    def now_next(self, channel, moment: datetime | None = None):
        """(current, next) for a channel, either of which may be None."""
        key = self.key_for(channel)
        if key is None:
            return None, None
        moment = moment or datetime.now(timezone.utc)
        current = following = None
        for programme in self.programmes.get(key, ()):
            if programme.covers(moment):
                current = programme
            elif programme.start > moment:
                following = programme
                break
        return current, following


class EpgStore:
    """Downloads, caches and parses the guides a provider declares.

    Everything here is blocking. Call it from a worker thread -- the UI does.
    """

    def __init__(self, cache_dir: Path | None = None, ttl: int = CACHE_TTL_SECONDS,
                 user_agent: str = "winnotix") -> None:
        self.cache_dir = Path(cache_dir) if cache_dir is not None else EPG_CACHE
        self.ttl = ttl
        self.user_agent = user_agent
        self._guides: dict[str, Guide] = {}

    def cache_path(self, url: str) -> Path:
        name = re.sub(r"[^A-Za-z0-9._-]", "_", url.rsplit("/", 1)[-1]) or "guide"
        return self.cache_dir / name

    def _fresh(self, path: Path) -> bool:
        try:
            return (time.time() - path.stat().st_mtime) < self.ttl
        except OSError:
            return False

    def fetch(self, url: str) -> bytes | None:
        """Guide bytes, decompressed. Cached copy when it is still fresh."""
        path = self.cache_path(url)
        if self._fresh(path):
            try:
                return self._decompress(path.read_bytes())
            except OSError:
                pass
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = response.read()
        except (urllib.error.URLError, OSError, ValueError) as exc:
            print(f"[winnotix] could not fetch guide {url}: {exc}")
            # A stale copy beats no listings at all.
            try:
                return self._decompress(path.read_bytes())
            except OSError:
                return None
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            # .part then rename, so an interrupted download cannot be read back
            # as a truncated guide on the next run.
            part = path.with_suffix(path.suffix + ".part")
            part.write_bytes(raw)
            part.replace(path)
        except OSError as exc:
            print(f"[winnotix] could not cache guide {url}: {exc}")
        return self._decompress(raw)

    @staticmethod
    def _decompress(raw: bytes) -> bytes:
        if raw[:2] == b"\x1f\x8b":
            try:
                return gzip.decompress(raw)
            except (OSError, EOFError):
                return b""
        return raw

    def guide(self, url: str) -> Guide:
        """Parsed guide for one URL, memoised for the life of the store."""
        if url in self._guides:
            return self._guides[url]
        raw = self.fetch(url)
        guide = Guide.parse(raw) if raw else Guide()
        self._guides[url] = guide
        return guide

    def load_for(self, urls, code: str | None) -> list[Guide]:
        """Guides covering `code`, parsed. Empty when the country has none."""
        return [self.guide(url) for url in urls_for_country(urls, code)]

    def now_next(self, guides, channel, moment: datetime | None = None):
        """First guide that knows this channel wins."""
        for guide in guides:
            current, following = guide.now_next(channel, moment)
            if current is not None or following is not None:
                return current, following
        return None, None


def country_for_group(group) -> str | None:
    """The ISO code for a group, so its guide can be chosen."""
    if group is None:
        return None
    return countries.code_for_group(group)
