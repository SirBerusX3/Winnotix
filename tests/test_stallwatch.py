"""Deciding when a stalled stream should be reopened.

The failure being watched for is one mpv does not report: an ad break replaces
the MPEG-TS program, the demuxer exposes it as a new track, mpv stays on the old
one and waits forever for a packet that is never sent. Measured on Pluto's South
Park, `time-pos` froze at 189.4 and had not moved 711 seconds later.

Detection is easy; restraint is the hard part. These pin the restraint.
"""

from __future__ import annotations

from winnotix.core import stallwatch
from winnotix.core.stallwatch import (
    GIVE_UP, RELOAD, REPORT, RESUMED, StallWatch)


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
        verdict = watch.sample(position)
        # RESUMED is healthy too: it is the watch withdrawing something it said.
        assert verdict in (None, RESUMED), f"healthy playback returned {verdict}"
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


# ---------------------------------------------------------------------------
# Live versus everything else
# ---------------------------------------------------------------------------

def test_a_film_is_reported_rather_than_reopened():
    """Reopening a film restarts it, which is worse than the stall it fixes.

    A live viewer loses nothing to a reload -- it rejoins at the live edge,
    where they already were. Someone an hour into a film loses the hour, on
    content that never had the ad-break fault in the first place.
    """
    clock = FakeClock()
    watch = watching(clock)
    watch.reset(live=False)
    position = play(watch, clock, 30)

    assert freeze(watch, clock, 30, position) == REPORT
    assert watch.attempts == 0, "nothing was reopened"


def test_a_film_is_told_about_once_rather_than_every_tick():
    clock = FakeClock()
    watch = watching(clock)
    watch.reset(live=False)
    position = play(watch, clock, 30)

    verdicts = []
    for _ in range(300):
        clock.advance(1.0)
        verdict = watch.sample(position)
        if verdict is not None:
            verdicts.append(verdict)

    assert verdicts == [REPORT], f"nagged: {verdicts}"


def test_a_film_that_recovers_can_be_reported_again_later():
    """Two separate stalls are two pieces of news, not one repeated."""
    clock = FakeClock()
    watch = watching(clock)
    watch.reset(live=False)
    position = play(watch, clock, 30)

    assert freeze(watch, clock, 30, position) == REPORT
    position = play(watch, clock, 60, start=position)
    assert freeze(watch, clock, 30, position) == REPORT


def test_live_is_still_reopened_after_the_distinction():
    """The default is live, so the ad-break fix is not lost to this change."""
    clock = FakeClock()
    watch = watching(clock)
    position = play(watch, clock, 30)
    assert freeze(watch, clock, 30, position) == RELOAD

    other = watching(FakeClock())
    other.reset(live=True)
    assert other.attempts == 0


# ---------------------------------------------------------------------------
# The rule the stall check has to obey
# ---------------------------------------------------------------------------

def test_the_stall_check_never_calls_into_mpv():
    """`mpv_get_property` is synchronous, and this runs on the GUI thread.

    Reading a property blocks the caller until mpv's core answers. Doing that
    once a second, from the thread that owns the window mpv renders into, is a
    deadlock waiting for its moment: the core can be waiting on the video
    output, the video output wants the GUI thread, and the GUI thread is inside
    libmpv. The two values are observed and pushed instead.

    Checked by reading the source rather than by calling the method, because
    importing winnotix.ui.main_window would load libmpv -- which the test
    workflow deliberately does not install (see .github/workflows/tests.yml).
    """
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent
              / "winnotix" / "ui" / "main_window.py").read_text(encoding="utf-8")

    function = next(
        (node for node in ast.walk(ast.parse(source))
         if isinstance(node, ast.FunctionDef) and node.name == "_check_for_stall"),
        None)
    assert function is not None, "_check_for_stall has been renamed or removed"

    reads = [node.attr for node in ast.walk(function)
             if isinstance(node, ast.Attribute)
             and node.attr in {"_get_property", "_set_property", "command", "wait_for_property"}]
    assert not reads, f"_check_for_stall calls into mpv synchronously: {reads}"


# ---------------------------------------------------------------------------
# Withdrawing what it said
# ---------------------------------------------------------------------------

def test_a_recovered_film_withdraws_the_message():
    """A status line outliving the problem describes a stopped stream as it plays.

    Reported from use: the message stayed up until the channel was reloaded,
    rather than clearing when playback came back.
    """
    clock = FakeClock()
    watch = watching(clock)
    watch.reset(live=False)
    position = play(watch, clock, 30)
    assert freeze(watch, clock, 30, position) == REPORT

    clock.advance(1.0)
    assert watch.sample(position + 1.0) == RESUMED


def test_the_withdrawal_is_said_once():
    clock = FakeClock()
    watch = watching(clock)
    watch.reset(live=False)
    position = play(watch, clock, 30)
    freeze(watch, clock, 30, position)

    verdicts = []
    for _ in range(30):
        clock.advance(1.0)
        position += 1.0
        verdict = watch.sample(position)
        if verdict is not None:
            verdicts.append(verdict)
    assert verdicts == [RESUMED]


def test_a_live_stream_that_was_given_up_on_withdraws_it_too():
    clock = FakeClock()
    watch = watching(clock)
    position = play(watch, clock, 30)
    for _ in range(400):
        clock.advance(1.0)
        if watch.sample(position) == GIVE_UP:
            break

    clock.advance(1.0)
    assert watch.sample(position + 1.0) == RESUMED


def test_nothing_is_withdrawn_when_nothing_was_said():
    """A reload alone is not something to withdraw -- the status moves on anyway."""
    clock = FakeClock()
    watch = watching(clock)
    position = play(watch, clock, 30)
    assert freeze(watch, clock, 30, position) == RELOAD

    clock.advance(1.0)
    assert watch.sample(position + 1.0) is None


def test_the_automatic_reopen_does_not_run_on_the_gui_thread():
    """`play()` is synchronous and reopening reinitialises the video output.

    On a core wedged retrying a dead stream that call can block, and blocking on
    the GUI thread freezes the window -- reported from use against BBC's DASH
    channels, where the status line said reconnecting and then the app locked
    up. Switching channels by hand has always done this and is recorded in
    roadmap.md section 11; doing it automatically, once per stall, is not
    something to leave on that thread.

    Read from source rather than called, for the reason given above.
    """
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent
              / "winnotix" / "ui" / "main_window.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    def function(name):
        return next((n for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef) and n.name == name), None)

    caller = function("_reload_stalled_channel")
    assert caller is not None, "_reload_stalled_channel has been renamed or removed"
    plays = [n.attr for n in ast.walk(caller)
             if isinstance(n, ast.Attribute) and n.attr in {"play", "loadfile", "command"}]
    assert not plays, f"_reload_stalled_channel reopens on the GUI thread: {plays}"

    worker = function("_reopen_off_thread")
    assert worker is not None, "_reopen_off_thread has been renamed or removed"
    decorators = [d.id for d in worker.decorator_list if isinstance(d, ast.Name)]
    assert "async_function" in decorators, (
        f"_reopen_off_thread is not on a worker thread: {decorators}")


def test_giving_up_stops_the_stream_rather_than_only_saying_so():
    """A stream left running is a demuxer left retrying, and a busy core.

    Reported from use: after a BBC DASH channel was given up on, backing out and
    choosing another channel selected it and then played nothing -- the old
    stream was still churning through its retry loop.
    """
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent
              / "winnotix" / "ui" / "main_window.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    check = next((n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "_check_for_stall"), None)
    assert check is not None

    # The give-up branch has to reach stop_playback, not merely set a status.
    calls = [n.func.attr for n in ast.walk(check)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    assert "stop_playback" in calls, f"giving up does not stop the stream: {calls}"


def test_stopping_does_not_run_on_the_gui_thread():
    """`stop` is a command too, and slowest exactly when the window must answer."""
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent
              / "winnotix" / "ui" / "main_window.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    stopper = next((n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "stop_playback"), None)
    assert stopper is not None
    direct = [n.attr for n in ast.walk(stopper)
              if isinstance(n, ast.Attribute) and n.attr in {"stop", "command"}]
    assert not direct, f"stop_playback stops on the GUI thread: {direct}"

    worker = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "_stop_off_thread"), None)
    assert worker is not None, "_stop_off_thread has been renamed or removed"
    assert "async_function" in [d.id for d in worker.decorator_list
                                if isinstance(d, ast.Name)]
