"""Channel logo cache.

Upstream fires one HTTP request per channel the moment a list is shown
(hypnotix.py:534-543 -> download_channel_logos). On a 1,869-channel playlist
that is 1,869 requests for the ~15 rows actually on screen, which is why the
Linux app stalls on large providers.

Here, requests are issued only for rows the user can actually see, through
:meth:`LogoCache.request`. A small thread pool does the fetching and results
arrive back on the GUI thread. Cache paths and the on-disk format are unchanged,
so a cache populated by Hypnotix on Linux is still valid here.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import requests
from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap

from ..core.paths import resources_dir

# Upstream sizes: 64x32 for TV rows, 200x200 for VOD/series posters.
TV_LOGO_SIZE = QSize(64, 32)
POSTER_SIZE = QSize(200, 200)


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

    def _fetch(self, logo_url: str, logo_path: str) -> None:
        headers = {
            "User-Agent": self.settings.get_string("user-agent"),
            "Referer": self.settings.get_string("http-referer"),
        }
        try:
            response = requests.get(logo_url, headers=headers, timeout=10, stream=True)
            if response.status_code == 200:
                os.makedirs(os.path.dirname(logo_path), exist_ok=True)
                # Write to a temp name and rename, so a half-downloaded file is
                # never mistaken for a valid cache entry by a later run.
                tmp = logo_path + ".part"
                with open(tmp, "wb") as handle:
                    for chunk in response.iter_content(64 * 1024):
                        handle.write(chunk)
                os.replace(tmp, logo_path)
                self.logo_ready.emit(logo_path)
            else:
                with self._lock:
                    self._failed.add(logo_path)
        except Exception:
            with self._lock:
                self._failed.add(logo_path)
        finally:
            with self._lock:
                self._inflight.discard(logo_path)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
