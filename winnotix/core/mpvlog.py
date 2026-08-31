"""Throttling for mpv's log output.

mpv hands every log line to its client on **its own event thread**, and
python-mpv calls our handler synchronously from that thread's loop. Two things
follow, and the second is not obvious:

1. A live stream that plays while some of its representations fail can emit the
   same handful of messages thousands of times a minute. A BBC DASH channel does
   exactly this -- it plays, while `dash: Failed to open fragment of playlist`
   and `curl: HTTP error 404` repeat indefinitely.

2. `MPV.terminate()` calls `_mpv_terminate_destroy()` and then joins the event
   thread **with no timeout** (mpv.py:1171-1173). That thread only leaves its
   loop on the SHUTDOWN event, so it must first drain everything queued ahead of
   it -- running our handler, and a console write, for each one. A backlog of
   thousands of messages is therefore not just noise on screen: it is why
   closing the window appears to hang.

So the handler must stay cheap. This keeps one counter per distinct message and
prints each at most once per interval, with a note of what was suppressed, which
collapses a repeating storm to a trickle while still showing every *kind* of
error exactly as mpv reported it.

Numbers are masked when forming the key, because the worst offender is
`stream: Failed to open .../465675009.m4s` -- one message per segment, each
textually unique and so, unmasked, each a first occurrence that prints. Masking
digits makes the whole run share one counter. The line printed is always mpv's
real text, numbers included.
"""

from __future__ import annotations

import re
import time

# Long enough to collapse a storm, short enough that a slowly recurring problem
# still shows up while someone is watching the console.
DEFAULT_INTERVAL = 5.0

# A misbehaving stream produces few distinct messages; the cap is only there so
# a pathological one cannot grow this without bound.
MAX_TRACKED = 256

# Segment numbers, byte counts, timestamps: what varies between otherwise
# identical messages.
_DIGITS = re.compile(r"\d+")


class LogThrottle:
    """Decide whether an mpv log line should be printed, and with what suffix."""

    def __init__(self, interval: float = DEFAULT_INTERVAL,
                 max_tracked: int = MAX_TRACKED, clock=time.monotonic) -> None:
        self.interval = interval
        self.max_tracked = max_tracked
        self._clock = clock
        # key -> [suppressed since last print, when last printed]
        self._seen: dict[tuple[str, str, str], list] = {}

    def line(self, level: str, prefix: str, text: str) -> str | None:
        """The line to print, or None to stay quiet.

        The first occurrence of a message always prints, so nothing is hidden
        that has not already been shown once.
        """
        text = text.strip()
        key = (level, prefix, _DIGITS.sub("#", text))
        now = self._clock()

        entry = self._seen.get(key)
        if entry is None:
            if len(self._seen) >= self.max_tracked:
                self._forget_oldest()
            self._seen[key] = [0, now]
            return f"[mpv/{level}] {prefix}: {text}"

        suppressed, last = entry
        if now - last < self.interval:
            entry[0] = suppressed + 1
            return None

        entry[0] = 0
        entry[1] = now
        line = f"[mpv/{level}] {prefix}: {text}"
        if suppressed:
            line += f"  (+{suppressed} repeat{'s' if suppressed != 1 else ''} suppressed)"
        return line

    def _forget_oldest(self) -> None:
        oldest = min(self._seen, key=lambda k: self._seen[k][1])
        del self._seen[oldest]

    def suppressed_total(self) -> int:
        """How many lines have been held back but not yet reported."""
        return sum(entry[0] for entry in self._seen.values())
