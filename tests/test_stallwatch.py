"""Deciding when a stalled stream should be reopened.

The failure being watched for is one mpv does not report: an ad break replaces
the MPEG-TS program, the demuxer exposes it as a new track, mpv stays on the old
one and waits forever for a packet that is never sent. Measured on Pluto's South
Park, `time-pos` froze at 189.4 and had not moved 711 seconds later.

Detection is easy; restraint is the hard part. These pin the restraint.
"""

from __future__ import annotations

from winnotix.core import stallwatch
from winnotix.core.stallwatch import GIVE_UP, RELOAD, StallWatch


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def watching(clock, **kwargs) -> StallWatch:
    return StallWatch(clock=clock, **kwargs)


def play(watch, clock, seconds: float, *, start: float = 0.0) -> float:
    """Advance the clock a second at a time with playback keeping up."""
    position = start
    for _ in range(int(seconds)):
        clock.advance(1.0)
        position += 1.0
        assert watch.sample(position) is None, "healthy playback asked for a reload"
    return position


def freeze(watch, clock, seconds: float, position: float):
    """Hold `time-pos` still, returning the first verdict that is not None."""
    for _ in range(int(seconds)):
        clock.advance(1.0)
        verdict = watch.sample(position)
        if verdict is not None:
            return verdict
    return None


# ---------------------------------------------------------------------------
# Not a stall
# ---------------------------------------------------------------------------

def test_playback_that_keeps_moving_is_left_alone():
    clock = FakeClock()
    watch = watching(clock)
    play(watch, clock, 120)
    assert watch.attempts == 0


def test_a_deliberate_pause_is_not_a_stall():
    """Reopening the stream under someone who pressed pause would be its own bug."""
    clock = FakeClock()
    watch = watching(clock)
    position = play(watch, clock, 10)
    for _ in range(60):
        clock.advance(1.0)
        assert watch.sample(position, paused=True) is None


def test_nothing_playing_is_not_a_stall():
    clock = FakeClock()
    watch = watching(clock)
    for _ in range(60):
        clock.advance(1.0)
        assert watch.sample(None) is None


def test_a_brief_hiccup_is_ridden_out():
    """A rebuffer shorter than the threshold must not cost the viewer a reconnect."""
    clock = FakeClock()
    watch = watching(clock)
    position = play(watch, clock, 10)
    assert freeze(watch, clock, stallwatch.STALL_SECONDS - 2, position) is None
    play(watch, clock, 5, start=position)
    assert watch.attempts == 0


# ---------------------------------------------------------------------------
# A stall
# ---------------------------------------------------------------------------

def test_a_stream_that_stops_is_reopened():
    clock = FakeClock()
    watch = watching(clock)
    position = play(watch, clock, 30)
    assert freeze(watch, clock, 30, position) == RELOAD
    assert watch.attempts == 1


def test_the_reload_is_given_time_to_work_before_it_is_judged():
    """Without the grace period a reopening stream reads as a fresh stall."""
    clock = FakeClock()
    watch = watching(clock)
    position = play(watch, clock, 30)
    assert freeze(watch, clock, 30, position) == RELOAD

    # Still frozen, but only briefly -- reopening a live stream is not instant.
    assert freeze(watch, clock, stallwatch.GRACE_SECONDS - 2, position) is None
    assert watch.attempts == 1


def test_a_stream_that_will_not_come_back_is_eventually_left_alone():
    clock = FakeClock()
    watch = watching(clock)
    position = play(watch, clock, 30)

    verdicts = []
    for _ in range(400):
        clock.advance(1.0)
        verdict = watch.sample(position)
        if verdict is not None:
            verdicts.append(verdict)

    assert verdicts.count(RELOAD) == stallwatch.MAX_ATTEMPTS
    assert verdicts.count(GIVE_UP) == 1, "giving up should be said once, not every tick"
    assert verdicts[-1] == GIVE_UP


def test_recovering_forgives_the_earlier_trouble():
    """An hour of viewing has several ad breaks, and each one recovers.

    Without this the attempt budget would be spent on the first three and the
    fourth would be abandoned, on a channel that reconnects perfectly every time.
    """
    clock = FakeClock()
    watch = watching(clock)
    position = play(watch, clock, 30)

    for _ in range(5):
        assert freeze(watch, clock, 30, position) == RELOAD
        assert watch.attempts == 1
        # The reload worked: the stream comes back at the live edge.
        position = play(watch, clock, stallwatch.SETTLE_SECONDS + 5, start=position + 20)
        assert watch.attempts == 0


def test_reset_clears_the_record():
    clock = FakeClock()
    watch = watching(clock)
    position = play(watch, clock, 30)
    assert freeze(watch, clock, 30, position) == RELOAD
    assert watch.attempts == 1

    watch.reset()
    assert watch.attempts == 0
    assert freeze(watch, clock, stallwatch.STALL_SECONDS - 2, position) is None


# ---------------------------------------------------------------------------
# The CA bundle
# ---------------------------------------------------------------------------

def test_mpv_is_given_a_ca_bundle_that_exists():
    """A fresh Windows trust store is missing roots these CDNs chain to."""
    from pathlib import Path

    from winnotix.core import mpvloader

    bundle = mpvloader.ca_bundle()
    assert bundle is not None, "certifi is a declared dependency"
    assert Path(bundle).is_file()
    assert "BEGIN CERTIFICATE" in Path(bundle).read_text(encoding="utf-8")
