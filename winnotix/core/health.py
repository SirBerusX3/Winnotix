"""Check ahead of time whether a channel's address still serves something.

`streamcheck.diagnose` runs on the failure path: mpv has already given up, and
the question is *why*. This module asks a different question -- which of these
channels is worth trying at all -- and the difference matters more than it
looks.

**The same response means opposite things in the two cases.** A manifest that
loads is, on the failure path, bad news: the address is good, so whatever broke
is further in, and `describe_response` says the channel is off air. Checked
ahead of time it is the *good* outcome -- the address answers and serves a
manifest, which is as much as can be known without decoding video. So the
verdict here is computed separately, and `describe_response` is borrowed only
to word a failure once one has been established.

**A 403 is not death.** It is usually geo-blocking, which means the channel is
alive and simply not available from here -- a VPN or a different day may change
it. It is reported as its own state rather than folded into "dead", and nothing
is hidden on the strength of it.

**Nothing is deleted or hidden automatically.** A check is one request at one
moment against a host that may be rate-limiting; being wrong about a channel
the user wanted is worse than leaving a dead row in the list. Results mark rows
and are cached, and what to do about them stays the user's choice.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import requests

from .paths import CACHE_DIR
from .streamcheck import DASH_TYPES, HTML_MARKERS, SNIFF_BYTES, describe_response

HEALTH_PATH = CACHE_DIR / "health.json"

OK = "ok"
DEAD = "dead"
BLOCKED = "blocked"
UNREACHABLE = "unreachable"

#: A verdict older than this is re-checked. Playlists rot over weeks, not
#: minutes, and re-testing a dead host hourly would be rude as well as useless.
DEFAULT_TTL = 7 * 24 * 60 * 60

#: Deliberately modest. These are other people's servers, and a playlist can
#: point hundreds of channels at one of them.
DEFAULT_WORKERS = 8

#: Long enough for a slow origin, short enough that a wall of dead hosts does
#: not take all afternoon.
DEFAULT_TIMEOUT = (4.0, 6.0)


@dataclass(frozen=True)
class Result:
    state: str
    detail: str = ""
    checked: float = 0.0

    @property
    def playable(self) -> bool:
        """Blocked counts as playable: it is alive, just not from here."""
        return self.state in (OK, BLOCKED)

    def to_dict(self) -> dict:
        return {"state": self.state, "detail": self.detail, "checked": self.checked}

    @classmethod
    def from_dict(cls, data: dict) -> "Result | None":
        state = data.get("state")
        if state not in (OK, DEAD, BLOCKED, UNREACHABLE):
            return None
        return cls(state=state,
                   detail=str(data.get("detail") or ""),
                   checked=float(data.get("checked") or 0.0))


def classify(status: int, reason: str, content_type: str, body: bytes) -> tuple[str, str]:
    """Verdict and, where it is bad news, the sentence explaining it."""
    head = (body or b"")[:SNIFF_BYTES]
    stripped = head.lstrip()
    lowered = stripped.lower()
    kind = (content_type or "").split(";")[0].strip().lower()

    if status == 403:
        return BLOCKED, describe_response(status, reason, content_type, body)
    if status >= 400:
        return DEAD, describe_response(status, reason, content_type, body)

    # A manifest is the good answer here, unlike on the failure path.
    if stripped.startswith(b"#EXTM3U"):
        return OK, ""
    if kind in DASH_TYPES or b"<mpd" in lowered:
        return OK, ""

    # A whole HTTP response inside a 200 body, a login page, or plain text:
    # there is no stream at that address whatever the status line says.
    if stripped.startswith(b"HTTP/"):
        return DEAD, describe_response(status, reason, content_type, body)
    if kind.startswith("text/html") or any(m in lowered for m in HTML_MARKERS):
        return DEAD, describe_response(status, reason, content_type, body)
    if kind.startswith("text/"):
        return DEAD, describe_response(status, reason, content_type, body)

    # Anything else that answered 2xx: bytes we cannot identify without
    # decoding them, which is not this module's job. Treat as alive.
    return OK, ""


def probe(url: str, *, user_agent: str = "", referer: str = "",
          timeout=DEFAULT_TIMEOUT) -> Result:
    """One request, one verdict. Never raises."""
    if not url:
        return Result(DEAD, "No address.", time.time())
    headers = {}
    if user_agent:
        headers["User-Agent"] = user_agent
    if referer:
        headers["Referer"] = referer
    try:
        with requests.get(url, headers=headers, timeout=timeout, stream=True) as response:
            body = next(response.iter_content(SNIFF_BYTES), b"")
            state, detail = classify(
                response.status_code,
                response.reason or "",
                response.headers.get("Content-Type", ""),
                body,
            )
            return Result(state, detail, time.time())
    except requests.exceptions.Timeout:
        return Result(UNREACHABLE, "The server did not answer in time.", time.time())
    except requests.exceptions.SSLError:
        return Result(UNREACHABLE,
                      "The server's HTTPS certificate could not be verified.", time.time())
    except requests.exceptions.ConnectionError:
        return Result(UNREACHABLE,
                      "Could not reach the server — the host is down or the address "
                      "is wrong.", time.time())
    except requests.exceptions.RequestException as exc:
        return Result(UNREACHABLE, f"Could not reach the server: {exc}", time.time())


class HealthCache:
    """Verdicts by URL, kept on disk so a second pass costs nothing."""

    def __init__(self, path: Path | None = None, ttl: int = DEFAULT_TTL) -> None:
        self.path = Path(path) if path is not None else HEALTH_PATH
        self.ttl = ttl
        self.results: dict[str, Result] = {}

    def load(self) -> "HealthCache":
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return self
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[winnotix] ignoring unreadable health cache {self.path}: {exc}")
            return self
        entries = data.get("results") if isinstance(data, dict) else None
        if isinstance(entries, dict):
            for url, raw in entries.items():
                if isinstance(raw, dict):
                    result = Result.from_dict(raw)
                    if result is not None:
                        self.results[url] = result
        return self

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"version": 1,
                       "results": {u: r.to_dict() for u, r in self.results.items()}}
            tmp = self.path.with_suffix(".part")
            with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, indent=1)
            tmp.replace(self.path)
        except OSError as exc:
            print(f"[winnotix] could not write health cache: {exc}")

    def fresh(self, url: str) -> Result | None:
        result = self.results.get(url)
        if result is None:
            return None
        if self.ttl and (time.time() - result.checked) > self.ttl:
            return None
        return result

    def get(self, url: str) -> Result | None:
        return self.results.get(url)


@dataclass
class Sweep:
    """What a pass found."""
    checked: int = 0
    reused: int = 0
    ok: int = 0
    dead: int = 0
    blocked: int = 0
    unreachable: int = 0

    def note(self, state: str) -> None:
        setattr(self, state, getattr(self, state) + 1)

    def summary(self) -> str:
        if not (self.checked or self.reused):
            return ""
        parts = [f"{self.ok} playable"]
        if self.dead:
            parts.append(f"{self.dead} dead")
        if self.unreachable:
            parts.append(f"{self.unreachable} unreachable")
        if self.blocked:
            parts.append(f"{self.blocked} geo-blocked")
        return ", ".join(parts)


def sweep(channels, cache: HealthCache, *, user_agent: str = "", referer: str = "",
          workers: int = DEFAULT_WORKERS, timeout=DEFAULT_TIMEOUT,
          progress=None, should_stop=None) -> Sweep:
    """Check every channel, reusing fresh verdicts. Blocking; run off the GUI thread.

    `progress(done, total)` is called as results land. `should_stop()` is
    consulted between results: checks still queued are cancelled, and the
    handful already in flight are left to finish, so stopping costs one
    timeout rather than one per remaining channel. It cannot be instant --
    a request already sent cannot be unsent -- but it is bounded by `workers`
    instead of by the length of the list.
    """
    result = Sweep()
    urls, seen = [], set()
    for channel in channels:
        url = getattr(channel, "url", None)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)

    pending = []
    for url in urls:
        cached = cache.fresh(url)
        if cached is not None:
            result.reused += 1
            result.note(cached.state)
        else:
            pending.append(url)

    total = len(pending)
    if not total:
        if progress:
            progress(0, 0)
        return result

    def run(url):
        return url, probe(url, user_agent=user_agent, referer=referer, timeout=timeout)

    # Explicit futures rather than pool.map: map submits everything at once and
    # the context manager then waits for all of it, so a "stop" would still sit
    # through every outstanding timeout. cancel_futures drops what has not
    # started, which is the only part that can honestly be cancelled.
    done = 0
    stopped = False
    pool = ThreadPoolExecutor(max_workers=max(1, workers))
    try:
        futures = [pool.submit(run, url) for url in pending]
        for future in as_completed(futures):
            url, verdict = future.result()
            done += 1
            cache.results[url] = verdict
            result.checked += 1
            result.note(verdict.state)
            if progress:
                progress(done, total)
            if should_stop is not None and should_stop():
                stopped = True
                break
    finally:
        pool.shutdown(wait=not stopped, cancel_futures=True)
    cache.save()
    return result
