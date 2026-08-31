"""Channel logo cache.

Upstream fires one HTTP request per channel the moment a list is shown
(hypnotix.py:534-543 -> download_channel_logos). On a 1,869-channel playlist
that is 1,869 requests for the ~15 rows actually on screen, which is why the
Linux app stalls on large providers.

Here, requests are issued only for rows the user can actually see, through
:meth:`LogoCache.request`. A small thread pool does the fetching and results
arrive back on the GUI thread. Cache paths and the on-disk format are unchanged,
so a cache populated by Hypnotix on Linux is still valid here.

Requests that come back refused rather than missing are retried through an image
proxy -- what makes logos load at all from a region their host blocks. The
reasoning, and the limits on when it applies, are in `core/logoproxy.py`.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import requests
from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap

from ..core import logoproxy
from ..core.paths import PROVIDERS_PATH, resources_dir

# Upstream sizes: 64x32 for TV rows, 200x200 for VOD/series posters.
TV_LOGO_SIZE = QSize(64, 32)
POSTER_SIZE = QSize(200, 200)

# Outcomes of a single HTTP attempt. _GONE and _REFUSED are both failures, but
# only _REFUSED is worth asking someone else for -- see logoproxy.refused.
_OK, _REFUSED, _GONE = "ok", "refused", "gone"

# The body is held in memory to be hashed before it is stored, so it is worth a
# ceiling. The largest logo in the Free-TV and iptv-org playlists is under 300 KB.
MAX_LOGO_BYTES = 8 * 1024 * 1024


class LogoCache(QObject):
    """Loads channel logos from disk, fetching them on demand."""

    logo_ready = Signal(str)  # logo_path that just became available

    def __init__(self, settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._pixmaps: dict[tuple[str, int, int], QPixmap] = {}
        self._inflight: set[str] = set()
        self._failed: set[str] = set()
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="logo")
        self._placeholder: dict[tuple[int, int], QPixmap] = {}
        self._hosts = logoproxy.HostHealth()
        self._sentinels = logoproxy.SentinelWatch()

    # -- reading -------------------------------------------------------

    def placeholder(self, size: QSize) -> QPixmap:
        key = (size.width(), size.height())
        if key not in self._placeholder:
            path = resources_dir() / "generic_tv_logo.png"
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                pixmap = QPixmap(size)
                pixmap.fill(Qt.GlobalColor.transparent)
            self._placeholder[key] = pixmap.scaled(
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        return self._placeholder[key]

    def pixmap(self, logo_path: str | None, size: QSize) -> QPixmap | None:
        """Return a cached pixmap, or None if it is not on disk yet."""
        if not logo_path:
            return None
        key = (logo_path, size.width(), size.height())
        if key in self._pixmaps:
            return self._pixmaps[key]
        if not os.path.isfile(logo_path):
            return None
        pixmap = QPixmap(logo_path)
        if pixmap.isNull():
            # A truncated or HTML-error-page "image"; don't retry it.
            self._failed.add(logo_path)
            return None
        scaled = pixmap.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._pixmaps[key] = scaled
        return scaled

    def icon(self, logo_path: str | None, size: QSize) -> QIcon:
        pixmap = self.pixmap(logo_path, size)
        return QIcon(pixmap if pixmap is not None else self.placeholder(size))

    # -- fetching ------------------------------------------------------

    def request(self, logo_url: str | None, logo_path: str | None) -> None:
        """Fetch a logo if it is not cached. Safe to call repeatedly."""
        if not logo_url or not logo_path:
            return
        if logo_url.startswith("file://") or os.path.isfile(logo_path):
            return
        with self._lock:
            if logo_path in self._inflight or logo_path in self._failed:
                return
            self._inflight.add(logo_path)
        self._pool.submit(self._fetch, logo_url, logo_path)

    def reset_failures(self) -> None:
        """Forget every failure, so the next scroll retries them.

        Called when the proxy setting is toggled: the answer to "can this host
        be reached" has just changed, and making the user restart to find out
        would be a poor way to present a checkbox.
        """
        with self._lock:
            self._failed.clear()
        self._hosts.forget()

    def _fetch(self, logo_url: str, logo_path: str) -> None:
        try:
            saved = self._download(logo_url, logo_path)
        except Exception:
            saved = False
        if saved:
            self.logo_ready.emit(logo_path)
        else:
            with self._lock:
                self._failed.add(logo_path)
        with self._lock:
            self._inflight.discard(logo_path)

    def _download(self, logo_url: str, logo_path: str) -> bool:
        """Try the origin, then the proxy if the origin refused us."""
        proxy_allowed = (self.settings.get_boolean("proxy-blocked-logos")
                         and logoproxy.is_proxyable(logo_url))
        if proxy_allowed and self._hosts.prefer_proxy(logo_url):
            # Every direct request to this host has been refused so far, so
            # skip an attempt we already know the answer to.
            return self._attempt(logoproxy.proxied(logo_url), logo_path) == _OK

        outcome = self._attempt(logo_url, logo_path)
        if outcome == _OK:
            self._hosts.record_success(logo_url)
            return True
        if outcome == _GONE:
            return False        # a 404 is no more findable from elsewhere
        self._hosts.record_refusal(logo_url)
        if not proxy_allowed:
            return False
        return self._attempt(logoproxy.proxied(logo_url), logo_path) == _OK

    def _attempt(self, url: str, logo_path: str) -> str:
        headers = {
            "User-Agent": self.settings.get_string("user-agent"),
            "Referer": self.settings.get_string("http-referer"),
        }
        try:
            response = requests.get(url, headers=headers, timeout=10, stream=True)
        except Exception:
            # A connection reset or a timeout is indistinguishable from a block
            # at this level, and both are worth one attempt from elsewhere.
            return _REFUSED
        with response:
            if logoproxy.refused(response.status_code,
                                 response.headers.get("Content-Type")):
                return _REFUSED
            if response.status_code != 200:
                return _GONE
            try:
                data = self._read(response)
            except Exception:
                return _GONE

        # A 200 carrying a real PNG can still be a refusal -- see SentinelWatch.
        refusal = self._sentinels.inspect(url, data, logo_path)
        if refusal is not None:
            return _REFUSED
        try:
            self._save(data, logo_path)
        except OSError:
            return _GONE
        return _OK

    @staticmethod
    def _read(response) -> bytes:
        """Read the body, capped -- a logo is never megabytes, and a host that
        answers a logo request with something enormous is not to be trusted
        with the memory."""
        chunks, total = [], 0
        for chunk in response.iter_content(64 * 1024):
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_LOGO_BYTES:
                raise ValueError("logo is implausibly large")
        return b"".join(chunks)

    @staticmethod
    def _save(data: bytes, logo_path: str) -> None:
        os.makedirs(os.path.dirname(logo_path), exist_ok=True)
        # Write to a temp name and rename, so a half-written file is never
        # mistaken for a valid cache entry by a later run.
        tmp = logo_path + ".part"
        try:
            with open(tmp, "wb") as handle:
                handle.write(data)
            os.replace(tmp, logo_path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def purge_cached_refusals(self, folder=None) -> None:
        """Clear refusals that earlier versions cached as though they were logos.

        Called once at startup rather than from ``__init__``, so that
        constructing a LogoCache never touches the filesystem. Runs on the
        thread pool; only files whose size matches a known sentinel are hashed,
        so a large cache costs little more than a directory scan.
        """
        self._pool.submit(self._purge, PROVIDERS_PATH if folder is None else folder)

    def _purge(self, folder) -> None:
        removed = self._sentinels.purge(folder)
        if removed:
            print(f"[winnotix] dropped {removed} cached logos that were really "
                  f'"not available in your region" images')

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
