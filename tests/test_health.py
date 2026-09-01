"""Tests for the ahead-of-time channel check (winnotix/core/health.py)."""

from __future__ import annotations

import json
import time

import pytest

from winnotix.core import health
from winnotix.core.health import (
    BLOCKED,
    DEAD,
    OK,
    UNREACHABLE,
    HealthCache,
    Result,
    classify,
    sweep,
)


class Ch:
    def __init__(self, url, name="A channel"):
        self.url = url
        self.name = name


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------

def test_a_manifest_that_loads_is_good_news_here():
    """The point of the module: streamcheck reads this as "off air", because
    there it means mpv already failed. Checked ahead of time it means alive."""
    state, detail = classify(200, "OK", "application/vnd.apple.mpegurl", b"#EXTM3U\n#EXT-X-VER")
    assert state == OK
    assert detail == ""

    from winnotix.core.streamcheck import describe_response
    assert describe_response(200, "OK", "application/vnd.apple.mpegurl",
                             b"#EXTM3U\n") != ""


def test_a_dash_manifest_is_alive_too():
    state, _ = classify(200, "OK", "application/dash+xml", b"<?xml?><MPD ...>")
    assert state == OK


@pytest.mark.parametrize("status,expected", [
    (403, BLOCKED),     # geo-blocking: alive, just not from here
    (404, DEAD),
    (410, DEAD),
    (500, DEAD),
])
def test_status_codes(status, expected):
    state, detail = classify(status, "", "", b"")
    assert state == expected
    assert detail


def test_a_403_is_not_treated_as_death():
    """A VPN or a different day changes it, so nothing is hidden on this."""
    assert Result(BLOCKED).playable is True
    assert Result(OK).playable is True
    assert Result(DEAD).playable is False
    assert Result(UNREACHABLE).playable is False


def test_an_http_response_inside_the_body_is_dead():
    state, detail = classify(200, "OK", "application/octet-stream",
                             b"HTTP/1.1 404 Not Found\r\nServer: micro_httpd\r\n")
    assert state == DEAD
    assert "404 Not Found" in detail


def test_a_login_page_is_dead():
    state, detail = classify(200, "OK", "text/html", b"<!doctype html><html><body>")
    assert state == DEAD
    assert detail


def test_unidentifiable_bytes_are_left_alone():
    """Deciding this would mean decoding video, which is not this module's job."""
    state, detail = classify(200, "OK", "application/octet-stream", b"\x47\x40\x11\x10")
    assert state == OK
    assert detail == ""


# --------------------------------------------------------------------------
# The cache
# --------------------------------------------------------------------------

def test_a_verdict_round_trips(tmp_path):
    cache = HealthCache(tmp_path / "h.json")
    cache.results["http://x/1"] = Result(DEAD, "gone", time.time())
    cache.save()

    reloaded = HealthCache(tmp_path / "h.json").load()
    assert reloaded.results["http://x/1"].state == DEAD
    assert reloaded.results["http://x/1"].detail == "gone"


def test_a_stale_verdict_is_not_reused(tmp_path):
    cache = HealthCache(tmp_path / "h.json", ttl=60)
    cache.results["http://x/1"] = Result(DEAD, "gone", time.time() - 600)
    assert cache.fresh("http://x/1") is None
    assert cache.get("http://x/1") is not None      # still remembered, just old


def test_a_fresh_verdict_is_reused(tmp_path):
    cache = HealthCache(tmp_path / "h.json", ttl=600)
    cache.results["http://x/1"] = Result(OK, "", time.time())
    assert cache.fresh("http://x/1").state == OK


def test_a_missing_cache_is_not_fatal(tmp_path):
    assert HealthCache(tmp_path / "absent.json").load().results == {}


def test_a_corrupt_cache_is_not_fatal(tmp_path):
    path = tmp_path / "h.json"
    path.write_text("{not json", encoding="utf-8")
    assert HealthCache(path).load().results == {}


def test_junk_entries_are_dropped_not_trusted(tmp_path):
    path = tmp_path / "h.json"
    path.write_text(json.dumps({"results": {
        "http://good": {"state": "dead", "detail": "d", "checked": 1},
        "http://bad": {"state": "banana"},
    }}), encoding="utf-8")
    loaded = HealthCache(path).load()
    assert set(loaded.results) == {"http://good"}


# --------------------------------------------------------------------------
# The sweep
# --------------------------------------------------------------------------

@pytest.fixture
def fake_probe(monkeypatch):
    """Verdict by URL, and a record of what was actually requested."""
    calls = []

    def probe(url, **kwargs):
        calls.append(url)
        if "dead" in url:
            return Result(DEAD, "gone", time.time())
        if "blocked" in url:
            return Result(BLOCKED, "geo", time.time())
        if "slow" in url:
            return Result(UNREACHABLE, "timeout", time.time())
        return Result(OK, "", time.time())

    monkeypatch.setattr(health, "probe", probe)
    return calls


def test_a_sweep_counts_each_outcome(tmp_path, fake_probe):
    cache = HealthCache(tmp_path / "h.json")
    channels = [Ch("http://ok/1"), Ch("http://dead/2"),
                Ch("http://blocked/3"), Ch("http://slow/4")]

    result = sweep(channels, cache)

    assert result.checked == 4
    assert (result.ok, result.dead, result.blocked, result.unreachable) == (1, 1, 1, 1)
    assert "1 dead" in result.summary()
    assert "1 geo-blocked" in result.summary()


def test_a_url_is_checked_once_however_many_channels_share_it(tmp_path, fake_probe):
    cache = HealthCache(tmp_path / "h.json")
    sweep([Ch("http://ok/1"), Ch("http://ok/1"), Ch("http://ok/1")], cache)
    assert fake_probe == ["http://ok/1"]


def test_channels_with_no_url_are_skipped(tmp_path, fake_probe):
    cache = HealthCache(tmp_path / "h.json")
    result = sweep([Ch(None), Ch("")], cache)
    assert fake_probe == []
    assert result.checked == 0


def test_a_fresh_verdict_is_reused_instead_of_re_requested(tmp_path, fake_probe):
    cache = HealthCache(tmp_path / "h.json", ttl=600)
    cache.results["http://ok/1"] = Result(OK, "", time.time())

    result = sweep([Ch("http://ok/1"), Ch("http://dead/2")], cache)

    assert fake_probe == ["http://dead/2"]
    assert result.reused == 1
    assert result.checked == 1
    assert result.ok == 1 and result.dead == 1


def test_the_sweep_is_written_to_disk(tmp_path, fake_probe):
    path = tmp_path / "h.json"
    sweep([Ch("http://dead/2")], HealthCache(path))
    assert HealthCache(path).load().results["http://dead/2"].state == DEAD


def test_progress_is_reported(tmp_path, fake_probe):
    seen = []
    sweep([Ch("http://ok/1"), Ch("http://ok/2")], HealthCache(tmp_path / "h.json"),
          progress=lambda done, total: seen.append((done, total)))
    assert seen == [(1, 2), (2, 2)]


def test_a_sweep_can_be_stopped_early(tmp_path, monkeypatch):
    """Stopping must cancel queued checks, not merely stop reading results.

    Written with a probe that actually blocks, because an instant one cannot
    tell the two apart -- which is how the first version of this passed while
    the sweep still sat through every outstanding request.
    """
    requested = []

    def slow_probe(url, **kwargs):
        requested.append(url)
        time.sleep(0.05)
        return Result(OK, "", time.time())

    monkeypatch.setattr(health, "probe", slow_probe)
    channels = [Ch(f"http://ok/{i}") for i in range(40)]

    started = time.monotonic()
    result = sweep(channels, HealthCache(tmp_path / "h.json"),
                   workers=2, should_stop=lambda: True)
    elapsed = time.monotonic() - started

    assert result.checked == 1              # stopped on the first result
    # 40 sequential 50ms probes would be 2s; two in flight is ~0.1s.
    assert len(requested) <= 4, requested
    assert elapsed < 1.0


def test_an_empty_sweep_says_nothing(tmp_path, fake_probe):
    result = sweep([], HealthCache(tmp_path / "h.json"))
    assert result.summary() == ""
