"""Locate libmpv before ``import mpv``.

python-mpv resolves and loads the shared library at *import* time, so the search
path has to be arranged first -- there is no second chance after the import.

Upstream's vendored mpv.py looked for ``mpv-1.dll`` only (mpv.py:31). The PyPI
package accepts ``mpv-1.dll``, ``mpv-2.dll`` or ``libmpv-2.dll``; current Windows
builds ship the last of those, which is why the vendored copy had to go.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Iterator

from .paths import vendor_dir

DLL_NAMES = ("libmpv-2.dll", "mpv-2.dll", "mpv-1.dll")


def _candidate_dirs() -> Iterator[Path]:
    yield vendor_dir() / "libmpv"
    if getattr(sys, "frozen", False):
        yield Path(sys.executable).parent


def _register_dll_dir() -> Path | None:
    """Make a bundled libmpv discoverable. Returns the directory used, if any."""
    for directory in _candidate_dirs():
        if any((directory / name).is_file() for name in DLL_NAMES):
            # add_dll_directory governs the actual load; PATH is what
            # ctypes.util.find_library searches, and python-mpv uses both.
            os.add_dll_directory(str(directory))
            os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
            return directory
    return None


def load_mpv():
    """Import and return the ``mpv`` module, or raise with an actionable message."""
    found = _register_dll_dir()
    try:
        import mpv  # noqa: PLC0415 -- must follow the DLL path setup above
    except OSError as exc:
        searched = ", ".join(str(d) for d in _candidate_dirs())
        raise OSError(
            f"Could not load libmpv. Searched: {searched}\n"
            f"Place libmpv-2.dll in {vendor_dir() / 'libmpv'} -- Windows builds come "
            "from https://github.com/shinchiro/mpv-winbuild-cmake/releases "
            "(the 'mpv-dev-x86_64-*.7z' asset).\n"
            f"Original error: {exc}"
        ) from exc

    if found is None:
        # Loaded from somewhere on the system PATH rather than our vendor dir.
        print(f"[winnotix] libmpv loaded from system PATH, not {vendor_dir() / 'libmpv'}")
    return mpv


# Measured: a healthy stream terminates in 0.06s, so this is ample headroom --
# while one stuck in libmpv's retry loop never returns at all.
SHUTDOWN_TIMEOUT = 1.5


def shutdown(player, *, event_callback=None, timeout: float = SHUTDOWN_TIMEOUT) -> bool:
    """Stop `player`, giving up after `timeout`. True if it actually stopped.

    `MPV.terminate()` destroys the handle and then joins mpv's event thread with
    **no timeout** (mpv.py:1171-1173). That thread leaves its loop only on the
    SHUTDOWN event, so it must first drain everything queued ahead of it, running
    the client's handlers for each. A stream that has been logging thousands of
    errors -- a live DASH channel that plays while some of its representations
    404 does exactly that -- leaves a backlog big enough for the join to look
    like a hang. Worse, a player stuck inside libmpv's own retry loop never
    reaches SHUTDOWN at all: measured against one, `terminate()` had still not
    returned after 30 seconds.

    So: silence the log at its source and detach the event callback first, which
    leaves the queue nothing to do, then terminate on a throwaway thread and stop
    waiting after `timeout`. Whatever is left goes away with the process.
    """
    detachers = [lambda: player.set_loglevel("no")]
    if event_callback is not None:
        detachers.append(lambda: player.unregister_event_callback(event_callback))
    for detach in detachers:
        try:
            detach()
        except Exception:
            pass  # already shutting down, or never registered

    finished = threading.Event()

    def stop() -> None:
        try:
            player.terminate()
        except Exception:
            pass
        finally:
            finished.set()

    threading.Thread(target=stop, name="mpv-shutdown", daemon=True).start()
    return finished.wait(timeout)
