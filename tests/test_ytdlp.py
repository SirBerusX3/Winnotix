"""Tests for yt-dlp discovery, selection and download.

The part worth pinning hardest is :func:`apply_preference`. Upstream's
equivalent downloads a binary and never puts it anywhere mpv looks, so the
setting silently does nothing; a regression here would look exactly like
that -- no error, just yt-dlp never being used.

Nothing here runs yt-dlp or reaches the network.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from winnotix.core import ytdlp


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """Redirect the download directory, and start from a known PATH."""
    folder = tmp_path / "yt-dlp"
    folder.mkdir()
    monkeypatch.setattr(ytdlp, "YTDLP_DIR", folder)
    monkeypatch.setenv("PATH", str(tmp_path / "elsewhere"))
    return folder


def _same(a, b) -> bool:
    """Compare paths as Windows does. `shutil.which` returns the extension in
    PATHEXT's case, so a literal == against `yt-dlp.exe` fails on `.EXE`."""
    return os.path.normcase(str(a)) == os.path.normcase(str(b))


def _install(folder: Path, body: bytes = b"MZ fake binary") -> Path:
    path = folder / ytdlp.BINARY_NAME
    path.write_bytes(body)
    return path


# --------------------------------------------------------------------------
# Selecting which copy mpv will find
# --------------------------------------------------------------------------

def test_choosing_the_local_copy_puts_it_where_mpv_looks(cache):
    """mpv's ytdl_hook runs `yt-dlp` by name, so the directory must be on PATH.
    Upstream never does this, which is why its downloaded copy is never used."""
    _install(cache)
    chosen = ytdlp.apply_preference(True)
    assert chosen == str(cache / ytdlp.BINARY_NAME)
    assert str(cache) in os.environ["PATH"].split(os.pathsep)


def test_declining_the_local_copy_takes_it_back_off_the_path(cache):
    _install(cache)
    ytdlp.apply_preference(True)
    ytdlp.apply_preference(False)
    assert str(cache) not in os.environ["PATH"].split(os.pathsep)


def test_asking_for_a_copy_that_was_never_downloaded_changes_nothing(cache):
    assert ytdlp.apply_preference(True) is None
    assert str(cache) not in os.environ["PATH"].split(os.pathsep)


def test_applying_repeatedly_does_not_stack_path_entries(cache):
    """It is called on startup, on every toggle and after every download."""
    _install(cache)
    for _ in range(5):
        ytdlp.apply_preference(True)
    assert os.environ["PATH"].split(os.pathsep).count(str(cache)) == 1


def test_the_local_copy_is_not_mistaken_for_a_system_install(cache, monkeypatch):
    """With our directory on PATH, a plain `which` finds our own copy and would
    report it as the user's."""
    _install(cache)
    ytdlp.apply_preference(True)
    assert ytdlp.system_path() is None


def test_a_real_system_install_is_still_found_alongside_ours(cache, tmp_path):
    elsewhere = tmp_path / "system"
    elsewhere.mkdir()
    _install(elsewhere)
    os.environ["PATH"] = os.pathsep.join([str(elsewhere), os.environ["PATH"]])
    _install(cache)

    ytdlp.apply_preference(True)
    assert _same(ytdlp.system_path(), elsewhere / ytdlp.BINARY_NAME)
    # ...and ours is the one that wins, because it is earlier on PATH.
    assert os.environ["PATH"].split(os.pathsep)[0] == str(cache)


def test_the_system_copy_is_chosen_when_the_setting_is_off(cache, tmp_path):
    elsewhere = tmp_path / "system"
    elsewhere.mkdir()
    _install(elsewhere)
    os.environ["PATH"] = str(elsewhere)
    _install(cache)
    assert _same(ytdlp.apply_preference(False), elsewhere / ytdlp.BINARY_NAME)


# --------------------------------------------------------------------------
# Version reporting
# --------------------------------------------------------------------------

def test_a_missing_binary_has_no_version():
    assert ytdlp.version(None) is None
    assert ytdlp.version("this-does-not-exist-anywhere") is None


def test_a_binary_that_fails_has_no_version(monkeypatch):
    class Done:
        returncode = 1
        stdout = "boom"

    monkeypatch.setattr(ytdlp.subprocess, "run", lambda *a, **k: Done())
    assert ytdlp.version("yt-dlp") is None


def test_the_reported_version_is_the_trimmed_output(monkeypatch):
    class Done:
        returncode = 0
        stdout = "2025.08.11\n"

    monkeypatch.setattr(ytdlp.subprocess, "run", lambda *a, **k: Done())
    assert ytdlp.version("yt-dlp") == "2025.08.11"


# --------------------------------------------------------------------------
# Downloading
# --------------------------------------------------------------------------

BODY = b"MZ" + b"yt-dlp" * 500
DIGEST = hashlib.sha256(BODY).hexdigest()


class FakeResponse:
    def __init__(self, body=BODY, status=200, text=None):
        self.status_code = status
        self.content = body
        self.text = text if text is not None else ""
        self.headers = {"Content-Length": str(len(body))}
        self._body = body

    def iter_content(self, size):
        for i in range(0, len(self._body), size):
            yield self._body[i:i + size]

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _serve(monkeypatch, binary=None, sums="present"):
    """Answer the two URLs download() fetches."""
    sums_text = {
        "present": f"{DIGEST}  {ytdlp.BINARY_NAME}\ndeadbeef  something-else\n",
        "wrong": f"{'0' * 64}  {ytdlp.BINARY_NAME}\n",
        "other-assets-only": "deadbeef  some-other-file\n",
    }.get(sums)

    def fake_get(url, **kwargs):
        if url.endswith(ytdlp.CHECKSUMS_NAME):
            if sums is None:
                raise OSError("no network")
            return FakeResponse(b"", text=sums_text)
        return binary if binary is not None else FakeResponse()

    monkeypatch.setattr(ytdlp.requests, "get", fake_get)


def test_a_verified_download_lands_in_the_cache(cache, monkeypatch):
    _serve(monkeypatch)
    result = ytdlp.download()
    assert result.verified is True
    assert result.path == cache / ytdlp.BINARY_NAME
    assert result.path.read_bytes() == BODY


def test_a_download_that_does_not_match_its_checksum_is_discarded(cache, monkeypatch):
    _serve(monkeypatch, sums="wrong")
    with pytest.raises(ytdlp.ChecksumMismatch):
        ytdlp.download()
    assert not (cache / ytdlp.BINARY_NAME).exists()
    assert not (cache / (ytdlp.BINARY_NAME + ".part")).exists()


def test_an_unavailable_checksum_list_still_downloads_but_says_so(cache, monkeypatch):
    """Refusing to install because github's sums file 404ed would be worse than
    installing and reporting it -- but the caller has to be able to tell."""
    _serve(monkeypatch, sums=None)
    result = ytdlp.download()
    assert result.verified is False
    assert result.path.read_bytes() == BODY


def test_a_checksum_list_without_our_asset_counts_as_unverified(cache, monkeypatch):
    _serve(monkeypatch, sums="other-assets-only")
    assert ytdlp.download().verified is False


def test_a_failed_transfer_leaves_no_partial_binary(cache, monkeypatch):
    class Truncated(FakeResponse):
        def iter_content(self, size):
            yield b"MZ"
            raise OSError("connection reset")

    _serve(monkeypatch, binary=Truncated())
    with pytest.raises(OSError):
        ytdlp.download()
    assert not (cache / ytdlp.BINARY_NAME).exists()
    assert not (cache / (ytdlp.BINARY_NAME + ".part")).exists()


def test_an_existing_copy_survives_a_failed_update(cache, monkeypatch):
    """An update that fails must not take the working copy with it."""
    _install(cache, b"the copy that already works")

    class Truncated(FakeResponse):
        def iter_content(self, size):
            yield b"MZ"
            raise OSError("connection reset")

    _serve(monkeypatch, binary=Truncated())
    with pytest.raises(OSError):
        ytdlp.download()
    assert (cache / ytdlp.BINARY_NAME).read_bytes() == b"the copy that already works"


def test_progress_is_reported_while_downloading(cache, monkeypatch):
    _serve(monkeypatch)
    seen: list[tuple[int, int]] = []
    ytdlp.download(on_progress=lambda done, total: seen.append((done, total)))
    assert seen
    assert seen[-1] == (len(BODY), len(BODY))
    assert [d for d, _ in seen] == sorted(d for d, _ in seen)
