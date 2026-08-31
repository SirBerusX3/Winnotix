"""JSON-backed stand-in for ``Gio.Settings``.

Upstream stores config in the GSettings schema ``org.x.hypnotix`` -- six keys,
reproduced verbatim in :data:`DEFAULTS`. Because the backend only ever reaches
settings through the Gio method names, mimicking that small API surface lets
``common.py`` run against this class unmodified.

The methods below are exactly the ones upstream calls: get_string (9 call sites),
set_string (2), get_boolean (1), set_boolean (1), get_strv (1), set_strv (1) and
reset (1).

The ``:::``-delimited provider string format is preserved deliberately, so an
existing Hypnotix provider list can be pasted straight across from Linux.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .paths import SETTINGS_PATH

DEFAULTS: dict[str, Any] = {
    "mpv-options": "hwdec=auto-safe",
    "user-agent": "Mozilla/5.0",
    "http-referer": "",
    "active-provider": "Free-TV",
    "providers": [
        "Free-TV:::url:::https://raw.githubusercontent.com/Free-TV/IPTV/master/playlist.m3u8:::::::::"
    ],
    "use-local-ytdlp": False,
    # Not part of upstream's schema -- see WINNOTIX_KEYS below.
    "hide-unplayable": True,
    # pyxtream supports this; upstream hardcodes it False at its one call
    # site (hypnotix.py:1543) and never exposes it. Default matches upstream.
    "hide-adult-content": False,
    # On by default because it costs nothing where it is not needed: the proxy
    # is only ever reached after a host has refused a direct request. See
    # core/logoproxy.py.
    "proxy-blocked-logos": True,
}

# Keys upstream's org.x.hypnotix schema does not have. Kept separate so the
# tests can still assert we have not drifted from upstream on the shared ones.
WINNOTIX_KEYS = {"hide-unplayable", "hide-adult-content", "proxy-blocked-logos"}
UPSTREAM_KEYS = set(DEFAULTS) - WINNOTIX_KEYS


class SettingsShim:
    def __init__(self, path: Path | None = None, autosave: bool = True) -> None:
        self.path = Path(path) if path is not None else SETTINGS_PATH
        self.autosave = autosave
        self._values: dict[str, Any] = dict(DEFAULTS)
        self.load()

    # -- persistence ----------------------------------------------------

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                stored = json.load(handle)
        except FileNotFoundError:
            return
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[winnotix] ignoring unreadable settings at {self.path}: {exc}")
            return
        if isinstance(stored, dict):
            # Only adopt keys we know, so a downgrade cannot be poisoned by junk.
            self._values.update({k: v for k, v in stored.items() if k in DEFAULTS})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Write-and-rename: a crash mid-write must not truncate a good config.
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self._values, handle, indent=2)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _set(self, key: str, value: Any) -> None:
        self._values[key] = value
        if self.autosave:
            self.save()

    # -- Gio.Settings-compatible surface --------------------------------

    def get_string(self, key: str) -> str:
        return str(self._values.get(key, DEFAULTS.get(key, "")))

    def set_string(self, key: str, value: str) -> None:
        self._set(key, str(value))

    def get_boolean(self, key: str) -> bool:
        return bool(self._values.get(key, DEFAULTS.get(key, False)))

    def set_boolean(self, key: str, value: bool) -> None:
        self._set(key, bool(value))

    def get_strv(self, key: str) -> list[str]:
        value = self._values.get(key, DEFAULTS.get(key, []))
        return list(value) if isinstance(value, (list, tuple)) else []

    def set_strv(self, key: str, value: list[str]) -> None:
        self._set(key, [str(v) for v in value])

    def reset(self, key: str) -> None:
        default = DEFAULTS.get(key)
        self._set(key, list(default) if isinstance(default, list) else default)
