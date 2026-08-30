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
