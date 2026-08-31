"""Tests for the blocked-logo fallback.

The behaviour worth pinning is not "does it build a proxy URL" but the three
judgements around it: which failures deserve a second attempt, which do not, and
when to stop attempting a host directly at all. Getting the second one wrong
doubles the request count for every dead logo in a playlist, and public
playlists are full of them.

The LogoCache tests stub `requests.get` rather than touching a network, so they
can assert the exact sequence of URLs attempted.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from winnotix.core import logoproxy  # noqa: E402

IMGUR = "https://i.imgur.com/7oNe8xj.png"


# --------------------------------------------------------------------------
# URL handling
# --------------------------------------------------------------------------

def test_the_original_url_is_passed_whole_and_encoded():
    assert logoproxy.proxied(IMGUR) == (
        "https://external-content.duckduckgo.com/iu/"
        "?u=https%3A%2F%2Fi.imgur.com%2F7oNe8xj.png&f=1&nofb=1"
    )


def test_a_query_string_survives_the_round_trip():
    url = "https://cdn/logo?w=200&h=100"
    assert "%3Fw%3D200%26h%3D100" in logoproxy.proxied(url)


@pytest.mark.parametrize("url", [
    IMGUR,
    "http://cdn.example/logo",
    "https://cdn/logo-with-no-extension",
])
def test_ordinary_http_logos_can_be_proxied(url):
    assert logoproxy.is_proxyable(url)


@pytest.mark.parametrize("url", [
    "file:///C:/logos/bbc.png",          # already local
    "https://external-content.duckduckgo.com/iu/?u=x",  # not from itself
    "data:image/png;base64,AAAA",
    "",
])
def test_these_are_left_alone(url):
    assert not logoproxy.is_proxyable(url)


# --------------------------------------------------------------------------
# Refused vs. gone -- the distinction the whole design rests on
# --------------------------------------------------------------------------

@pytest.mark.parametrize("status", [403, 429, 451])
def test_access_denied_is_worth_asking_elsewhere(status):
    assert logoproxy.refused(status, "text/html")


def test_a_block_page_served_as_200_html_is_a_refusal():
    """A regional block is often a page, not an error status. Without this it
    would be written to the cache as a corrupt logo and only fail later, at
    decode time, where there is no longer anything to retry."""
    assert logoproxy.refused(200, "text/html; charset=utf-8")


@pytest.mark.parametrize("status", [404, 410, 500, 502])
def test_a_missing_or_broken_image_is_not_retried(status):
    assert not logoproxy.refused(status, "text/html")


@pytest.mark.parametrize("content_type", [
    "image/png",
    "image/svg+xml",
    "application/octet-stream",   # plenty of hosts serve real images like this
    "binary/octet-stream",
    None,                        # no header at all
    "",
])
def test_a_successful_image_is_never_treated_as_refused(content_type):
    assert not logoproxy.refused(200, content_type)


# --------------------------------------------------------------------------
# Learning which hosts refuse
# --------------------------------------------------------------------------

def test_a_host_is_tried_directly_until_it_has_refused_enough():
    health = logoproxy.HostHealth(attempts=3)
    for _ in range(2):
        health.record_refusal(IMGUR)
        assert not health.prefer_proxy(IMGUR)
    health.record_refusal(IMGUR)
    assert health.prefer_proxy(IMGUR)


def test_one_success_clears_a_host_for_good():
    """A transient 429 must not condemn a host that works."""
    health = logoproxy.HostHealth(attempts=1)
    health.record_refusal(IMGUR)
    assert health.prefer_proxy(IMGUR)
    health.record_success(IMGUR)
    assert not health.prefer_proxy(IMGUR)
    health.record_refusal(IMGUR)
    assert not health.prefer_proxy(IMGUR)


def test_refusals_are_counted_per_host_not_globally():
    health = logoproxy.HostHealth(attempts=2)
    health.record_refusal(IMGUR)
    health.record_refusal("https://i.imgur.com/other.png")
    assert health.prefer_proxy(IMGUR)
    assert not health.prefer_proxy("https://images.pluto.tv/a.png")


def test_forget_puts_every_host_back_to_direct():
    health = logoproxy.HostHealth(attempts=1)
    health.record_refusal(IMGUR)
    health.forget()
    assert not health.prefer_proxy(IMGUR)


# --------------------------------------------------------------------------
# LogoCache: the sequence of requests actually made
# --------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, status=200, content_type="image/png", body=b"\x89PNG\r\n"):
        self.status_code = status
        self.headers = {} if content_type is None else {"Content-Type": content_type}
        self._body = body

    def iter_content(self, size):
        yield self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeHttp:
    """Answers by host, and records every URL asked for, in order."""

    def __init__(self, **by_host):
        self.by_host = by_host
        self.urls: list[str] = []

    def __call__(self, url, **kwargs):
        self.urls.append(url)
        answer = self.by_host.get(logoproxy.host_of(url), FakeResponse())
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def cache(tmp_path):
    from tests.conftest import FakeSettings
    from winnotix.ui import logos

    made = logos.LogoCache(FakeSettings())
    made.dest = str(tmp_path / "logo.png")
    yield made
    made.shutdown()


def _http(monkeypatch, **by_host):
    from winnotix.ui import logos

    fake = FakeHttp(**by_host)
    monkeypatch.setattr(logos.requests, "get", fake)
    return fake


def test_a_working_host_never_reaches_the_proxy(cache, monkeypatch):
    http = _http(monkeypatch)
    assert cache._download(IMGUR, cache.dest) is True
    assert http.urls == [IMGUR]
    assert os.path.isfile(cache.dest)


def test_a_refused_logo_is_retried_through_the_proxy(cache, monkeypatch):
    http = _http(monkeypatch, **{"i.imgur.com": FakeResponse(403, "text/html")})
    assert cache._download(IMGUR, cache.dest) is True
    assert http.urls == [IMGUR, logoproxy.proxied(IMGUR)]
    assert os.path.isfile(cache.dest)


def test_a_connection_error_counts_as_refused(cache, monkeypatch):
    http = _http(monkeypatch, **{"i.imgur.com": OSError("connection reset")})
    assert cache._download(IMGUR, cache.dest) is True
    assert http.urls == [IMGUR, logoproxy.proxied(IMGUR)]


def test_a_404_is_not_retried_through_the_proxy(cache, monkeypatch):
    http = _http(monkeypatch, **{"i.imgur.com": FakeResponse(404, "text/html")})
    assert cache._download(IMGUR, cache.dest) is False
    assert http.urls == [IMGUR]
    assert not os.path.isfile(cache.dest)


def test_the_direct_attempt_is_dropped_once_a_host_is_known_to_refuse(cache, monkeypatch):
    """The point of HostHealth: three wasted round trips, not nine thousand."""
    http = _http(monkeypatch, **{"i.imgur.com": FakeResponse(403, "text/html")})
    for _ in range(logoproxy.DIRECT_ATTEMPTS):
        cache._download(IMGUR, cache.dest)
    direct = [u for u in http.urls if logoproxy.host_of(u) == "i.imgur.com"]
    assert len(direct) == logoproxy.DIRECT_ATTEMPTS

    http.urls.clear()
    assert cache._download(IMGUR, cache.dest) is True
    assert http.urls == [logoproxy.proxied(IMGUR)]


def test_turning_the_setting_off_stops_at_the_origin(cache, monkeypatch):
    cache.settings._values["proxy-blocked-logos"] = False
    http = _http(monkeypatch, **{"i.imgur.com": FakeResponse(403, "text/html")})
    assert cache._download(IMGUR, cache.dest) is False
    assert http.urls == [IMGUR]


def test_a_proxy_that_also_fails_is_just_a_failure(cache, monkeypatch):
    http = _http(monkeypatch, **{
        "i.imgur.com": FakeResponse(403, "text/html"),
        "external-content.duckduckgo.com": FakeResponse(502, "text/html"),
    })
    assert cache._download(IMGUR, cache.dest) is False
    assert http.urls == [IMGUR, logoproxy.proxied(IMGUR)]
    assert not os.path.isfile(cache.dest)


def test_a_failed_write_leaves_no_partial_file(cache, monkeypatch):
    class Exploding(FakeResponse):
        def iter_content(self, size):
            yield b"\x89PNG"
            raise OSError("disk full")

    _http(monkeypatch, **{"i.imgur.com": Exploding()})
    assert cache._download(IMGUR, cache.dest) is False
    assert not os.path.isfile(cache.dest)
    assert not os.path.isfile(cache.dest + ".part")


def test_reset_failures_lets_a_dead_logo_be_asked_for_again(cache, monkeypatch):
    http = _http(monkeypatch, **{"i.imgur.com": FakeResponse(404, "text/html")})
    cache.request(IMGUR, cache.dest)
    cache._pool.shutdown(wait=True)
    assert http.urls == [IMGUR]

    cache.reset_failures()
    assert cache._failed == set()
    assert not cache._hosts.prefer_proxy(IMGUR)


# --------------------------------------------------------------------------
# Sentinels: a refusal that arrives as a perfectly valid image
# --------------------------------------------------------------------------

# The real thing, as served to a UK address: 200, image/png, and a genuine
# 336x478 PNG saying the content is not viewable in your region.
BLOCK_IMAGE = b"\x89PNG\r\n" + b"blocked" * 4949
BLOCK_DIGEST = __import__("hashlib").sha256(BLOCK_IMAGE).hexdigest()


@pytest.fixture
def watch(monkeypatch):
    monkeypatch.setitem(
        logoproxy.SENTINELS, BLOCK_DIGEST, (len(BLOCK_IMAGE), "a test refusal"),
    )
    return logoproxy.SentinelWatch()


def test_the_shipped_imgur_sentinel_is_described_by_its_real_size():
    """Guards the constant against a careless edit: the size is the cheap
    pre-filter, so a wrong one silently disables the whole check."""
    assert len(logoproxy.SENTINELS) == 1
    (size, text), = logoproxy.SENTINELS.values()
    assert size == 34641
    assert "region" in text


def test_a_known_refusal_is_identified(watch):
    assert watch.identify(BLOCK_IMAGE) == "a test refusal"


def test_an_ordinary_logo_of_a_different_size_is_never_hashed(watch, monkeypatch):
    monkeypatch.setattr(
        logoproxy.hashlib, "sha256",
        lambda *a: pytest.fail("a size mismatch should settle it without hashing"),
    )
    assert watch.identify(b"\x89PNG\r\nsomething else entirely") is None


def test_same_size_different_bytes_is_still_a_logo(watch):
    assert watch.identify(b"x" * len(BLOCK_IMAGE)) is None


def test_a_repeated_image_is_learned_as_a_sentinel(watch, tmp_path):
    """The shipped digest is only what is known today. If a host starts
    answering every logo with some new image, that must be caught too."""
    body = b"\x89PNG\r\nrepeated"
    paths = []
    for n in range(logoproxy.LEARN_THRESHOLD - 1):
        path = tmp_path / f"{n}.png"
        path.write_bytes(body)
        paths.append(path)
        assert watch.inspect(f"https://cdn/{n}.png", body, str(path)) is None

    last = tmp_path / "last.png"
    last.write_bytes(body)
    assert watch.inspect("https://cdn/last.png", body, str(last)) is not None
    # The copies stored before we knew are deleted, not left to poison the cache.
    assert not any(p.exists() for p in paths)


def test_one_url_asked_for_repeatedly_is_not_a_sentinel(watch, tmp_path):
    """Two channels sharing one logo URL is normal and must not trip this."""
    body = b"\x89PNG\r\nshared"
    for n in range(logoproxy.LEARN_THRESHOLD + 2):
        path = tmp_path / f"{n}.png"
        path.write_bytes(body)
        assert watch.inspect("https://cdn/shared.png", body, str(path)) is None


def test_the_same_image_from_two_hosts_is_counted_separately(watch, tmp_path):
    body = b"\x89PNG\r\ntwohosts"
    for n in range(logoproxy.LEARN_THRESHOLD - 1):
        assert watch.inspect(f"https://a/{n}.png", body, str(tmp_path / f"a{n}")) is None
    assert watch.inspect("https://b/0.png", body, str(tmp_path / "b0")) is None


def test_purge_removes_cached_refusals_and_leaves_logos_alone(watch, tmp_path):
    (tmp_path / "blocked.png").write_bytes(BLOCK_IMAGE)
    (tmp_path / "also-blocked.png").write_bytes(BLOCK_IMAGE)
    (tmp_path / "real.png").write_bytes(b"\x89PNG\r\na real logo")
    same_size = b"y" * len(BLOCK_IMAGE)
    (tmp_path / "same-size.png").write_bytes(same_size)

    assert watch.purge(tmp_path) == 2
    assert not (tmp_path / "blocked.png").exists()
    assert not (tmp_path / "also-blocked.png").exists()
    assert (tmp_path / "real.png").read_bytes() == b"\x89PNG\r\na real logo"
    assert (tmp_path / "same-size.png").read_bytes() == same_size


def test_purge_survives_a_missing_directory(watch, tmp_path):
    assert watch.purge(tmp_path / "not-there") == 0


# --------------------------------------------------------------------------
# The sentinel path through LogoCache -- the bug this all exists for
# --------------------------------------------------------------------------

def test_a_block_image_is_not_cached_and_goes_to_the_proxy(cache, monkeypatch):
    """Before this, imgur's 200 image/png region-block was stored as the logo,
    and the cached file then short-circuited every later fetch."""
    monkeypatch.setitem(
        logoproxy.SENTINELS, BLOCK_DIGEST, (len(BLOCK_IMAGE), "a test refusal"),
    )
    cache._sentinels = logoproxy.SentinelWatch()
    real = b"\x89PNG\r\nthe actual logo"
    http = _http(monkeypatch, **{
        "i.imgur.com": FakeResponse(200, "image/png", BLOCK_IMAGE),
        "external-content.duckduckgo.com": FakeResponse(200, "image/png", real),
    })

    assert cache._download(IMGUR, cache.dest) is True
    assert http.urls == [IMGUR, logoproxy.proxied(IMGUR)]
    assert open(cache.dest, "rb").read() == real


def test_a_host_serving_block_images_stops_being_asked_directly(cache, monkeypatch):
    monkeypatch.setitem(
        logoproxy.SENTINELS, BLOCK_DIGEST, (len(BLOCK_IMAGE), "a test refusal"),
    )
    cache._sentinels = logoproxy.SentinelWatch()
    _http(monkeypatch, **{
        "i.imgur.com": FakeResponse(200, "image/png", BLOCK_IMAGE),
        logoproxy.PROXY_HOST: FakeResponse(200, "image/png", b"\x89PNG\r\nreal"),
    })
    for _ in range(logoproxy.DIRECT_ATTEMPTS):
        cache._download(IMGUR, cache.dest)
    assert cache._hosts.prefer_proxy(IMGUR)


def test_an_implausibly_large_body_is_refused_not_buffered(cache, monkeypatch):
    from winnotix.ui import logos

    class Firehose(FakeResponse):
        def iter_content(self, size):
            for _ in range(3):
                yield b"x" * logos.MAX_LOGO_BYTES

    _http(monkeypatch, **{"i.imgur.com": Firehose()})
    assert cache._download(IMGUR, cache.dest) is False
    assert not os.path.isfile(cache.dest)


def test_learning_does_not_grow_without_bound(watch, tmp_path, monkeypatch):
    """One entry per image would be megabytes on a 14,000-channel playlist."""
    monkeypatch.setattr(logoproxy, "LEARN_CAPACITY", 8)
    for n in range(20):
        watch.inspect(f"https://cdn/{n}.png", f"logo {n}".encode(), str(tmp_path / f"{n}"))
    assert len(watch._seen) <= 8
