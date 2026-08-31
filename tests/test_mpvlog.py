"""Throttling mpv's log output.

This runs on mpv's event thread, and `terminate()` joins that thread with no
timeout, so a backlog here is what makes closing the window hang -- see the
header of winnotix/core/mpvlog.py.
"""

from __future__ import annotations

from winnotix.core.mpvlog import LogThrottle


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# The four messages a BBC DASH channel repeats indefinitely while still playing.
STORM = [
    ("warn", "ffmpeg/demuxer", "dash: Failed to open fragment of playlist"),
    ("error", "curl", "HTTP error 404"),
    ("error", "curl", "transfer failed: Failed writing received data to disk/application"),
    ("error", "ffmpeg/demuxer", "dash: Error when loading first fragment of playlist"),
]


def test_the_first_occurrence_always_prints():
    throttle = LogThrottle(clock=FakeClock())
    line = throttle.line("error", "curl", "HTTP error 404")
    assert line == "[mpv/error] curl: HTTP error 404"


def test_repeats_inside_the_interval_are_held_back():
    clock = FakeClock()
    throttle = LogThrottle(interval=5.0, clock=clock)
    assert throttle.line("error", "curl", "HTTP error 404") is not None
    for _ in range(500):
        clock.advance(0.001)
        assert throttle.line("error", "curl", "HTTP error 404") is None
    assert throttle.suppressed_total() == 500


def test_a_repeat_after_the_interval_prints_with_a_count():
    clock = FakeClock()
    throttle = LogThrottle(interval=5.0, clock=clock)
    throttle.line("error", "curl", "HTTP error 404")
    for _ in range(3):
        throttle.line("error", "curl", "HTTP error 404")

    clock.advance(6.0)
    line = throttle.line("error", "curl", "HTTP error 404")
    assert line == "[mpv/error] curl: HTTP error 404  (+3 repeats suppressed)"
    assert throttle.suppressed_total() == 0


def test_one_suppressed_repeat_reads_correctly():
    clock = FakeClock()
    throttle = LogThrottle(interval=5.0, clock=clock)
    throttle.line("warn", "x", "y")
    throttle.line("warn", "x", "y")
    clock.advance(6.0)
    assert throttle.line("warn", "x", "y").endswith("(+1 repeat suppressed)")


def test_every_distinct_message_is_shown_at_least_once():
    """Throttling must not hide a *kind* of error -- only its repetitions."""
    clock = FakeClock()
    throttle = LogThrottle(interval=5.0, clock=clock)
    printed = [throttle.line(*message) for message in STORM]
    assert all(line is not None for line in printed)
    assert len({line for line in printed}) == len(STORM)


def test_an_alternating_storm_still_collapses():
    """Consecutive-duplicate suppression would not help here: the messages
    cycle. Counting per message is what makes the storm quiet."""
    clock = FakeClock()
    throttle = LogThrottle(interval=5.0, clock=clock)
    printed = 0
    for _ in range(1000):
        for message in STORM:
            clock.advance(0.001)
            if throttle.line(*message) is not None:
                printed += 1
    # 4 first appearances, plus one round per interval elapsed.
    assert printed < 20, printed
    assert throttle.suppressed_total() > 3000


def test_message_text_is_stripped():
    throttle = LogThrottle(clock=FakeClock())
    assert throttle.line("warn", "p", "  padded\n") == "[mpv/warn] p: padded"


def test_tracking_is_bounded():
    """A pathological stream must not grow the table without limit."""
    clock = FakeClock()
    throttle = LogThrottle(max_tracked=8, clock=clock)
    for i in range(200):
        clock.advance(0.01)
        throttle.line("error", "curl", f"unique message {i}")
    assert len(throttle._seen) <= 8


def test_the_oldest_entry_is_the_one_dropped():
    clock = FakeClock()
    throttle = LogThrottle(interval=1000.0, max_tracked=2, clock=clock)
    throttle.line("warn", "p", "first")
    clock.advance(1.0)
    throttle.line("warn", "p", "second")
    clock.advance(1.0)
    throttle.line("warn", "p", "third")          # evicts "first"

    # "second" is still tracked, so it stays suppressed inside the interval.
    assert throttle.line("warn", "p", "second") is None
    # "first" was forgotten, so it prints as though new.
    assert throttle.line("warn", "p", "first") is not None


def test_messages_differing_only_in_numbers_share_a_counter():
    """The worst offender is one message per segment, each textually unique:
    without masking, every one is a first occurrence and prints."""
    clock = FakeClock()
    throttle = LogThrottle(interval=5.0, clock=clock)
    base = ("error", "stream",
            "Failed to open https://host/i=svc/t=3840/b=96000/{}.m4s")

    first = throttle.line(base[0], base[1], base[2].format(465675009))
    assert first is not None
    for number in range(465675010, 465675110):
        clock.advance(0.01)
        assert throttle.line(base[0], base[1], base[2].format(number)) is None

    assert len(throttle._seen) == 1
    assert throttle.suppressed_total() == 100


def test_the_printed_line_keeps_the_real_numbers():
    """Masking is for the key only -- the segment number is the useful part."""
    throttle = LogThrottle(clock=FakeClock())
    line = throttle.line("error", "stream", "Failed to open .../465675009.m4s")
    assert "465675009" in line
    assert "#" not in line


# --------------------------------------------------------------------------
# Shutting mpv down
# --------------------------------------------------------------------------

import threading  # noqa: E402
import time  # noqa: E402

import pytest  # noqa: E402

from winnotix.core import mpvloader  # noqa: E402


class FakePlayer:
    """Stands in for MPV. `block` makes terminate() hang, as a stuck one does."""

    def __init__(self, block: bool = False, raises: bool = False) -> None:
        self.block = block
        self.raises = raises
        self.loglevel = "warn"
        self.unregistered = []
        self.terminated = threading.Event()

    def set_loglevel(self, level):
        self.loglevel = level

    def unregister_event_callback(self, callback):
        self.unregistered.append(callback)

    def terminate(self):
        if self.raises:
            raise RuntimeError("core already gone")
        if self.block:
            time.sleep(30)
        self.terminated.set()


def test_a_healthy_player_shuts_down_and_reports_success():
    player = FakePlayer()
    assert mpvloader.shutdown(player, timeout=5.0) is True
    assert player.terminated.is_set()


def test_a_stuck_player_gives_up_instead_of_blocking():
    """The reported bug: terminate() joins mpv's event thread with no timeout,
    so a player stuck in libmpv's retry loop froze the window on close."""
    player = FakePlayer(block=True)
    started = time.monotonic()
    assert mpvloader.shutdown(player, timeout=0.3) is False
    assert time.monotonic() - started < 3.0


def test_logging_is_silenced_before_terminating():
    """Nothing should be left in the queue for the event thread to drain."""
    player = FakePlayer(block=True)
    mpvloader.shutdown(player, timeout=0.1)
    assert player.loglevel == "no"


def test_the_event_callback_is_detached():
    player = FakePlayer()
    marker = object()
    mpvloader.shutdown(player, event_callback=marker, timeout=5.0)
    assert player.unregistered == [marker]


def test_no_callback_means_nothing_to_detach():
    player = FakePlayer()
    assert mpvloader.shutdown(player, timeout=5.0) is True
    assert player.unregistered == []


def test_a_player_that_raises_is_still_reported_as_finished():
    """A core that has already gone is not a reason to hold the window open."""
    player = FakePlayer(raises=True)
    assert mpvloader.shutdown(player, timeout=5.0) is True


def test_detach_failures_do_not_stop_the_shutdown():
    class Awkward(FakePlayer):
        def set_loglevel(self, level):
            raise RuntimeError("nope")

        def unregister_event_callback(self, callback):
            raise ValueError("never registered")

    player = Awkward()
    assert mpvloader.shutdown(player, event_callback=object(), timeout=5.0) is True
    assert player.terminated.is_set()
