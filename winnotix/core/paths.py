"""Windows storage locations for Winnotix.

Replaces upstream Hypnotix's ``GLib.get_user_cache_dir()`` (common.py:14,18) and
the hardcoded ``/usr/share/...`` paths scattered through hypnotix.py.

Roaming vs local split matters here: playlists can be hundreds of megabytes, so
cached provider data goes in %LOCALAPPDATA% where it will not follow the user
between machines. Settings and favourites are small and worth roaming.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Winnotix"


def _env_dir(var: str, fallback: Path) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else fallback


DATA_DIR = _env_dir("APPDATA", Path.home() / "AppData" / "Roaming") / APP_NAME
CACHE_DIR = _env_dir("LOCALAPPDATA", Path.home() / "AppData" / "Local") / APP_NAME / "cache"

PROVIDERS_PATH = CACHE_DIR / "providers"
FAVORITES_PATH = DATA_DIR / "favorites" / "list"
SETTINGS_PATH = DATA_DIR / "settings.json"
YTDLP_DIR = CACHE_DIR / "yt-dlp"


def project_root() -> Path:
    """Root for bundled files, whether running from source or frozen.

    PyInstaller unpacks one-file bundles to a temp dir exposed as ``sys._MEIPASS``;
    one-folder bundles sit next to the executable.
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        return Path(meipass) if meipass else Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]


def vendor_dir() -> Path:
    return project_root() / "vendor"


def resources_dir() -> Path:
    return project_root() / "resources"


def ensure_dirs() -> None:
    """Create the writable app directories. Safe to call repeatedly."""
    for directory in (
        DATA_DIR,
        CACHE_DIR,
        PROVIDERS_PATH,
        FAVORITES_PATH.parent,
        YTDLP_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)
