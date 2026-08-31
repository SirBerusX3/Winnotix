"""Fetching channel logos from hosts that refuse the user's region.

imgur withdrew from the United Kingdom in September 2025, so `i.imgur.com`
serves nothing to a UK address. For an IPTV client that is not a long-tail
problem: imgur hosts **71% of the logos in the Free-TV playlist (1,457 of
2,059 channels) and 54% of iptv-org's all-countries playlist (7,729 of
14,310)**, so a UK user sees the generic placeholder on most of the app.

iptv-org's own logo database has a non-imgur alternative for only 358 of them,
so picking a different URL does not fix this. Fetching the same URL from
somewhere else does: an image proxy makes the request from its own servers, and
the region of the machine running Winnotix stops mattering. Which proxy is not a
free choice -- imgur refuses most of them. See :data:`PROXY_TEMPLATE`.

Nothing else changes. The rewrite happens at the moment of the HTTP request, so
the on-disk cache path is still derived from the original URL by
`common.py:Channel.__init__` -- an existing cache stays valid, and turning the
proxy off orphans nothing.

Three deliberate limits:

* **The proxy is a fallback, never a rewrite.** The direct fetch is tried first,
  so a user whose region is not blocked never touches a third party at all.
* **Only refusals are retried.** A 404 means the image is genuinely gone and the
  proxy would 404 too; retrying it would double the requests for every dead logo
  in a playlist, and public playlists have plenty. See :func:`refused`.
* **A refusal is not always an error.** imgur answers a UK request with HTTP 200,
  `Content-Type: image/png`, and a real 336x478 PNG reading "Content not viewable
  in your region". Nothing about that response says no, so it is recognised by the
  bytes themselves -- see :class:`SentinelWatch`.
* **A host that keeps refusing is learned.** One wasted round trip per logo,
  across 9,000 imgur URLs, would trade one problem for another. After
  :data:`DIRECT_ATTEMPTS` refusals with no success, a host goes straight to the
  proxy for the rest of the session -- so the cost of the block is three wasted
  requests in total, not three thousand.
"""

from __future__ import annotations

import hashlib
import os
import threading
from urllib.parse import quote, urlsplit

#: DuckDuckGo's image proxy, which exists to fetch third-party images on a
#: reader's behalf -- exactly this problem. Reached over HTTPS and given only
#: the logo URL: no part of the user's playlist, provider or identity.
#:
#: **Not images.weserv.nl.** It was the obvious candidate and it does not work
#: here: imgur answers weserv's servers with a 404, so every URL form returns
#: the same error. Measured, all against the same imgur logo:
#:
#:     weserv (six URL forms)     404 -- imgur refuses its servers
#:     Google gadget proxy        404 -- discontinued
#:     allorigins, codetabs       522 -- both down
#:     corsproxy.io               401 -- now needs an API key
#:     web.archive.org            connection timeout
#:     i0.wp.com (Photon)         302 back to imgur, so no proxying at all
#:     DuckDuckGo                 200, a real 9,113-byte PNG
#:
#: imgur's own thumbnail forms (`_d.webp`, and the s/m size suffixes) serve the
#: block image too, so there is no way around this at the origin.
PROXY_HOST = "external-content.duckduckgo.com"
PROXY_TEMPLATE = "https://external-content.duckduckgo.com/iu/?u={url}&f=1&nofb=1"

#: Statuses meaning "you may not have this", as opposed to "this is not here".
#: 451 is the explicitly legal case; imgur's own block and most CDN geo-fences
#: answer 403. 429 is rate limiting, which asking from elsewhere also solves.
REFUSED_STATUSES = frozenset({403, 429, 451})

#: A block page served as 200 text/html is a likely shape for a regional block,
#: and would otherwise be written to the cache as a corrupt logo that only fails
#: later, at decode time. Only types that are definitely *not* an image are
#: listed: plenty of hosts serve real images as application/octet-stream, and
#: guessing wrong here would proxy requests that were working fine.
NON_IMAGE_TYPES = ("text/", "application/json", "application/xml")

#: Refusals from one host before the direct attempt is skipped for the session.
DIRECT_ATTEMPTS = 3

#: Images that are not logos: a host's stand-in for one it will not serve.
#: Keyed by SHA-256, with the size first so the common case -- a real logo, of
#: some other length -- is settled by a `len()` and never hashed at all.
#:
#: imgur's is what a UK user actually sees today. It arrives as a valid PNG with
#: a 200 status, so `refused()` cannot catch it and it is cached like any other
#: logo; 833 of 1,279 files in one real cache were byte-identical copies of it.
SENTINELS: dict[str, tuple[int, str]] = {
    "faa24ec881e6040655c187a681d6dc496eb8aa41e1bd0652a180b3a40b457187":
        (34641, "imgur's “Content not viewable in your region” image"),
}

#: Distinct URLs from one host that must return identical bytes before those
#: bytes are treated as a sentinel nobody has told us about. Four, because
#: playlists really do reuse one image across a broadcaster's regional feeds --
#: though normally at the same URL, which is not counted here.
LEARN_THRESHOLD = 4

#: Ceiling on the images tracked while learning. One entry per distinct image is
#: fine for a few thousand channels and wasteful for fifteen thousand, and the
#: only cost of forgetting is that a sentinel takes longer to spot.
LEARN_CAPACITY = 5000


def host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:      # malformed IPv6 literal, and similar
        return ""


def is_proxyable(url: str) -> bool:
    """Whether this URL could be fetched through the proxy at all.

    ``file://`` logos are already local, and the proxy cannot be asked to fetch
    from itself.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https"):
        return False
    host = (parts.hostname or "").lower()
    return bool(host) and host != PROXY_HOST


def proxied(url: str) -> str:
    """The same image, fetched by the proxy's servers rather than by us."""
    return PROXY_TEMPLATE.format(url=quote(url, safe=""))


def refused(status: int, content_type: str | None) -> bool:
    """Whether a completed response looks like access being denied.

    Distinguishing this from a plain 404 is the whole point: only a refusal is
    worth a second attempt from somewhere else.
    """
    if status in REFUSED_STATUSES:
        return True
    if status != 200:
        return False
    kind = (content_type or "").split(";")[0].strip().lower()
    return any(kind.startswith(prefix) for prefix in NON_IMAGE_TYPES)


class HostHealth:
    """Remembers which hosts refuse direct requests, so we stop asking them.

    Shared across the logo thread pool, hence the lock. A single success clears
    a host permanently for the session: a transient 429 should not condemn a
    host that works, and the user's connection may change under us.
    """

    def __init__(self, attempts: int = DIRECT_ATTEMPTS) -> None:
        self.attempts = attempts
        self._refusals: dict[str, int] = {}
        self._reachable: set[str] = set()
        self._lock = threading.Lock()

    def prefer_proxy(self, url: str) -> bool:
        host = host_of(url)
        with self._lock:
            if host in self._reachable:
                return False
            return self._refusals.get(host, 0) >= self.attempts

    def record_success(self, url: str) -> None:
        host = host_of(url)
        with self._lock:
            self._reachable.add(host)
            self._refusals.pop(host, None)

    def record_refusal(self, url: str) -> None:
        host = host_of(url)
        with self._lock:
            if host and host not in self._reachable:
                self._refusals[host] = self._refusals.get(host, 0) + 1

    def forget(self) -> None:
        """Drop everything learned, so every host is tried directly again."""
        with self._lock:
            self._refusals.clear()
            self._reachable.clear()


class SentinelWatch:
    """Recognises a host's stand-in image and keeps it out of the cache.

    :data:`SENTINELS` covers what is known today, so the first UK request for an
    imgur logo is already routed to the proxy. That alone would be brittle --
    the day imgur redraws that image, every logo silently turns back into a grey
    placeholder with nothing in the app to say why -- so anything a host repeats
    across :data:`LEARN_THRESHOLD` *different* URLs is promoted to a sentinel
    too. Real logos differ; a refusal is the same picture every time.

    Copies already written before the promotion are deleted, so the mistake
    lasts three logos rather than until the cache is cleared by hand.
    """

    def __init__(self, threshold: int = LEARN_THRESHOLD) -> None:
        self.threshold = threshold
        self._known = {d: text for d, (_, text) in SENTINELS.items()}
        self._sizes = {size for size, _ in SENTINELS.values()}
        self._seen: dict[tuple[str, str], set[str]] = {}
        self._stored: dict[tuple[str, str], set[str]] = {}
        self._lock = threading.Lock()

    def identify(self, data: bytes) -> str | None:
        """What this image is, if it is a known refusal rather than a logo."""
        with self._lock:
            if len(data) not in self._sizes:
                return None
            known = dict(self._known)
        return known.get(hashlib.sha256(data).hexdigest())

    def inspect(self, url: str, data: bytes, logo_path: str) -> str | None:
        """Called for every image downloaded. Returns why it is not a logo.

        A return value means the bytes must not be kept: they are a refusal
        wearing an image's clothes, and the caller should retry elsewhere.
        """
        found = self.identify(data)
        if found is not None:
            return found
        digest = hashlib.sha256(data).hexdigest()
        key = (host_of(url), digest)
        with self._lock:
            if len(self._seen) >= LEARN_CAPACITY:
                self._seen.clear()
                self._stored.clear()
            urls = self._seen.setdefault(key, set())
            urls.add(url)
            self._stored.setdefault(key, set()).add(logo_path)
            if len(urls) < self.threshold:
                return None
            self._known[digest] = f"{key[0]} returns this image for every logo"
            self._sizes.add(len(data))
            stale = self._stored.pop(key, set())
            self._seen.pop(key, None)
            text = self._known[digest]
        for path in stale:
            try:
                os.unlink(path)
            except OSError:
                pass        # already gone, or in use -- the next launch retries
        return text

    def purge(self, folder: "str | os.PathLike[str]") -> int:
        """Delete cached files that are really a refusal. Returns how many.

        Existing caches are full of them: nothing before this change could tell
        the difference, so they were stored as ordinary logos and then short-
        circuited every later fetch, because the file was on disk.
        """
        removed = 0
        try:
            entries = list(os.scandir(folder))
        except OSError:
            return 0
        for entry in entries:
            try:
                if not entry.is_file() or entry.stat().st_size not in self._sizes:
                    continue
                with open(entry.path, "rb") as handle:
                    data = handle.read()
                if self.identify(data) is None:
                    continue
                os.unlink(entry.path)
                removed += 1
            except OSError:
                continue
        return removed
