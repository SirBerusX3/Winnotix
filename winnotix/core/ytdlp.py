"""Finding, fetching and selecting yt-dlp.

mpv plays a direct stream URL itself. yt-dlp is what it calls when the URL is a
page rather than a stream -- a YouTube link in a playlist, most obviously. It is
optional, and most IPTV entries never need it, which is why nothing here is on
the playback path.

Upstream offers a choice between the system yt-dlp and a copy it downloads
(``use-local-ytdlp``), and roadmap section 7 lists three Linux dependencies in
that code: a ``wget``/``chmod`` bootstrap (#2), a hardcoded ``/usr/bin/yt-dlp``
(#4), and ``~/.cache`` paths (#5). All three are replaced here.

**A fourth problem is not a portability one.** Upstream downloads its local copy
to ``~/.cache/hypnotix/yt-dlp`` and then never tells mpv it exists: it passes
``ytdl=True`` and nothing else (hypnotix.py:1645), and mpv's ytdl_hook resolves
the binary *by name, through PATH*. So the downloaded copy is never the one that
runs, and the setting does nothing but consume disk. :func:`apply_preference`
is the missing half -- it puts the chosen copy where mpv will actually look.

Two smaller repairs to the same function: upstream's ``update_ytdlp`` calls
``os.chdir`` and never changes back, so the process working directory is
permanently moved by clicking a button in Preferences; and it verifies nothing
about what it downloaded. Here the download is checked against the SHA-256 the
release publishes, so a truncated transfer is an error rather than a broken
executable discovered later.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, NamedTuple

import requests

from .paths import YTDLP_DIR

#: The `latest` alias redirects to whatever the newest release is, so there is
#: no API call and no release parsing -- just a stable download URL.
RELEASE_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/"

#: Windows gets the standalone .exe; the POSIX name is here so the module stays
#: readable on the platform it was ported from, and so tests can force either.
BINARY_NAME = "yt-dlp.exe" if sys.platform == "win32" else "yt-dlp"

#: Published alongside every release, one `<sha256>  <filename>` per line.
CHECKSUMS_NAME = "SHA2-256SUMS"

#: Keeps a console window from flashing up when yt-dlp is asked its version.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class Downloaded(NamedTuple):
    path: Path
    #: False when the checksum list could not be fetched, so the transfer was
    #: not verified. The download still happened; the caller should say so.
    verified: bool


class ChecksumMismatch(Exception):
    """The bytes that arrived are not the bytes the release publishes."""


def local_path() -> Path:
    """Where our own copy lives, whether or not it has been downloaded."""
    return YTDLP_DIR / BINARY_NAME


def system_path() -> str | None:
    """A yt-dlp already on PATH, ignoring our own copy.

    Our directory may be on PATH -- :func:`apply_preference` puts it there -- so
    a plain `which` would find our copy and report it as the system one.
    """
    found = shutil.which("yt-dlp")
    if found and _same_dir(Path(found).parent, YTDLP_DIR):
        without = [p for p in _path_entries() if not _same_dir(Path(p), YTDLP_DIR)]
        found = shutil.which("yt-dlp", path=os.pathsep.join(without))
    return found


def version(path: str | os.PathLike[str] | None) -> str | None:
    """`yt-dlp --version`, or None if it is absent or will not run."""
    if path is None:
        return None
    try:
        done = subprocess.run(
            [str(path), "--version"],
            capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip() or None


def apply_preference(use_local: bool) -> str | None:
    """Put the chosen yt-dlp where mpv will find it. Returns the one in effect.

    mpv's ytdl_hook runs `yt-dlp` by name, so choosing our copy means putting
    its directory on PATH -- there is no mpv option that takes a path without
    also needing its escaping rules applied to a Windows one. Idempotent, and
    safe to call again whenever the setting or the download state changes.
    """
    entries = [p for p in _path_entries() if not _same_dir(Path(p), YTDLP_DIR)]
    chosen = None
    if use_local and local_path().is_file():
        entries.insert(0, str(YTDLP_DIR))
        chosen = str(local_path())
    os.environ["PATH"] = os.pathsep.join(entries)
    return chosen if chosen is not None else system_path()


def download(on_progress: Callable[[int, int], None] | None = None,
             timeout: int = 180) -> Downloaded:
    """Fetch the latest yt-dlp into :data:`YTDLP_DIR`, replacing any older copy.

    `on_progress` is called with (bytes so far, total bytes) -- total is 0 when
    the server sends no length. Called from a worker thread, so it must marshal
    anything it touches onto the GUI thread itself.
    """
    YTDLP_DIR.mkdir(parents=True, exist_ok=True)
    expected = _published_digest(timeout=min(timeout, 60))

    target = local_path()
    partial = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    try:
        with requests.get(RELEASE_URL + BINARY_NAME, stream=True,
                          timeout=timeout) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with open(partial, "wb") as handle:
                for chunk in response.iter_content(256 * 1024):
                    handle.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if on_progress is not None:
                        on_progress(done, total)

        actual = digest.hexdigest()
        if expected is not None and actual != expected:
            raise ChecksumMismatch(
                f"expected {expected}, got {actual} -- the download was not kept"
            )
        # Replacing a running executable fails on Windows, which is the right
        # outcome: better a clear error than a half-swapped binary.
        os.replace(partial, target)
    except BaseException:
        try:
            partial.unlink()
        except OSError:
            pass
        raise

    return Downloaded(target, expected is not None)


def _published_digest(timeout: int = 60) -> str | None:
    """The SHA-256 the release lists for our asset, or None if unavailable.

    Both files come from the same host over HTTPS, so this is an integrity
    check rather than a trust anchor: what it reliably catches is a truncated
    or corrupted transfer, which would otherwise become an executable that
    fails confusingly the first time mpv calls it.
    """
    try:
        response = requests.get(RELEASE_URL + CHECKSUMS_NAME, timeout=timeout)
        response.raise_for_status()
        text = response.text
    except Exception:
        return None
    for line in text.splitlines():
        parts = line.split()
        # `sha256  filename`, with a leading * on the name in binary-mode sums.
        if len(parts) == 2 and parts[1].lstrip("*") == BINARY_NAME:
            return parts[0].strip().lower()
    return None


def _path_entries() -> list[str]:
    return [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]


def _same_dir(a: Path, b: Path) -> bool:
    """Compare two directories as the platform would -- Windows ignores case."""
    try:
        return os.path.normcase(os.path.normpath(str(a))) == \
               os.path.normcase(os.path.normpath(str(b)))
    except (TypeError, ValueError):
        return False
