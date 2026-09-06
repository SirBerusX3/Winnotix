"""Notice when a stream has stopped, and decide whether to reopen it.

Pluto TV -- and anything else that splices ads in server-side -- can change the
MPEG-TS program mid-stream. When it does, ffmpeg's HLS demuxer exposes the new
content as a *new track* rather than continuing the existing one, and mpv stays
selected on the track it started with. That track never receives another packet,
so playback simply stops: the picture holds its last frame, the buffer drains,
and mpv sits in `paused-for-cache` waiting for data that is never coming.

Measured against South Park on Pluto, reached through iptv-org's Canada list:
at 173s an ad bumper arrived as `--vid=4` alongside the show's `--vid=3`, mpv
stayed on `--vid=3`, and `time-pos` froze at 189.4. It had not moved 711 seconds
later, when the run ended -- while segments kept downloading with HTTP 206
throughout. Reopening the stream is the only cure, because that builds a fresh
demuxer on whatever program is current.

**Nothing reports this.** mpv believes it is still playing, so no END_FILE
reaches the handler that catches an ordinary failed open, and the app has no
other way to find out. Watching the clock is the whole of the detection.

Which makes this a question of *policy*, not of detection: `time-pos` standing
still is trivial to see, and the difficulty is in not acting on it too eagerly.
A live stream that hiccups for a second must be left alone. A user who pressed
pause must be left alone. A stream that is genuinely dead must not be reopened
forever. Those three judgements are what this class holds, and why it knows
nothing about mpv or Qt -- the policy is worth testing on its own.
"""

from __future__ import annotations

import time

#: Returned by :meth:`StallWatch.sample`.
RELOAD = "reload"
GIVE_UP = "give-up"

# How long `time-pos` must stand still before it counts as stopped rather than
# stuttering. Long enough to sit out a rebuffer on a slow connection; short
# enough that a viewer reads the recovery as a hiccup rather than a breakage.
STALL_SECONDS = 10.0

# After reopening, how long to let the stream find its feet before judging it
# again. Reopening a live HLS stream costs a manifest fetch and a segment.
GRACE_SECONDS = 12.0

# How long playback must run cleanly after a reload before earlier attempts are
# forgiven. Without this, an hour of viewing with a break every ten minutes
# would spend its whole attempt budget on the first three breaks and then give
# up on a stream that recovers perfectly every time.
SETTLE_SECONDS = 45.0

# Consecutive reloads before concluding the stream is not coming back. Three is
# enough to ride out a bad ad break and short enough not to hammer a dead host.
MAX_ATTEMPTS = 3

# `time-pos` is a float and a live stream reports it with some jitter, so
# "unchanged" needs a tolerance rather than an equality test.
POSITION_EPSILON = 0.01


class StallWatch:
    """Track playback position and say when the stream should be reopened."""

    def __init__(self, *, stall_seconds: float = STALL_SECONDS,
                 grace_seconds: float = GRACE_SECONDS,
                 settle_seconds: float = SETTLE_SECONDS,
                 max_attempts: int = MAX_ATTEMPTS,
                 clock=time.monotonic) -> None:
        self.stall_seconds = stall_seconds
        self.grace_seconds = grace_seconds
        self.settle_seconds = settle_seconds
        self.max_attempts = max_attempts
        self._clock = clock
        self.reset()

    @property
    def attempts(self) -> int:
        """Reloads issued since the last spell of healthy playback."""
        return self._attempts

    def reset(self) -> None:
        """Start over: a different channel, or playback stopped."""
        self._last_pos: float | None = None
        self._moved_at: float = self._clock()
        self._reloaded_at: float | None = None
        self._attempts = 0
        self._gave_up = False

    def sample(self, time_pos: float | None, *, paused: bool = False) -> str | None:
        """Feed one observation of `time-pos`. Returns an action, or None.

        Call this on a timer while a channel is playing. `paused` is mpv's own
        pause flag: a deliberate pause stops the clock too, and reopening the
        stream underneath someone who pressed pause would be its own bug.
        """
        now = self._clock()

        # Nothing playing, or paused on purpose. Neither is a stall, and the
        # clock restarts here so the idle spell is not counted as one.
        if time_pos is None or paused:
            self._last_pos = time_pos
            self._moved_at = now
            return None

        moved = (self._last_pos is None
                 or abs(time_pos - self._last_pos) > POSITION_EPSILON)
        self._last_pos = time_pos

        if moved:
            self._moved_at = now
            if (self._reloaded_at is not None
                    and now - self._reloaded_at >= self.settle_seconds):
                # It has played cleanly for a while: forget the earlier trouble.
                self._attempts = 0
                self._reloaded_at = None
                self._gave_up = False
            return None

        # Standing still. A reload already in flight gets its grace period
        # before the result is judged.
        if (self._reloaded_at is not None
                and now - self._reloaded_at < self.grace_seconds):
            return None

        if now - self._moved_at < self.stall_seconds:
            return None

        if self._attempts >= self.max_attempts:
            if self._gave_up:
                return None  # already said so; stay quiet until it recovers
            self._gave_up = True
            return GIVE_UP

        self._attempts += 1
        self._reloaded_at = now
        self._moved_at = now
        return RELOAD
