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
    # Two providers, where upstream's schema has one. The deliberate divergence
    # from `org.x.hypnotix`, and the only one among the upstream keys.
    #
    # Free-TV alone is what a new install used to get, and it publishes almost
    # no metadata: no categories, so the Movies and Series tiles stay empty, and
    # 9 series across its whole 2,053-entry catalogue. iptv-org's combined
    # playlist is 14,310 channels with categories and guides. Leaving it out
    # meant a new user had to find it through Browse country playlists, where
    # nothing had told them to look -- and with one provider, searching across
    # providers has nothing to search.
    #
    # It costs nothing until it is opened: only the active provider loads at
    # startup, and that stays Free-TV, whose playlist is 550 KB against
    # iptv-org's 14 MB. The name matches what the picker would have called it
    # (catalogue.CatalogueEntry.provider_name), so adding it from there finds
    # this one already present rather than making a second copy.
    "providers": [
        "Free-TV:::url:::https://raw.githubusercontent.com/Free-TV/IPTV/master/playlist.m3u8:::::::::",
        "iptv-org All countries:::url:::https://iptv-org.github.io/iptv/index.country.m3u:::::::::",
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
    # Off by default: it moves channels out of the country lists they were
    # published in, which is a visible change to a playlist the user chose.
    # See core/genres.py.
    "route-by-genre": False,
    # Subtitles. mpv already auto-selects a track a stream marks as default, so
    # True is what the app did before these existed; the switch is what makes
    # that undoable. Scale and position are mpv's own defaults, and only affect
    # text subtitles -- a bitmap DVB track ignores them. See ui/main_window.
    "subtitles-visible": True,
    "subtitle-scale": 1.0,
    "subtitle-position": 100,
    # On by default: guides are named by the playlist itself, so this is the
    # same trust boundary as its streams and logos, and nothing is fetched
    # until a country's channel list is opened. See core/epg.py.
    "show-epg": True,
}

# Keys upstream's org.x.hypnotix schema does not have. Kept separate so the
# tests can still assert we have not drifted from upstream on the shared ones.
WINNOTIX_KEYS = {"hide-unplayable", "hide-adult-content", "proxy-blocked-logos",
                 "route-by-genre", "show-epg", "subtitles-visible",
                 "subtitle-scale", "subtitle-position"}
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

    def get_double(self, key: str) -> float:
        try:
            return float(self._values.get(key, DEFAULTS.get(key, 0.0)))
        except (TypeError, ValueError):
            return float(DEFAULTS.get(key, 0.0) or 0.0)

    def set_double(self, key: str, value: float) -> None:
        self._set(key, float(value))

    def get_int(self, key: str) -> int:
        try:
            return int(self._values.get(key, DEFAULTS.get(key, 0)))
        except (TypeError, ValueError):
            return int(DEFAULTS.get(key, 0) or 0)

    def set_int(self, key: str, value: int) -> None:
        self._set(key, int(value))

    def get_strv(self, key: str) -> list[str]:
        value = self._values.get(key, DEFAULTS.get(key, []))
        return list(value) if isinstance(value, (list, tuple)) else []

    def set_strv(self, key: str, value: list[str]) -> None:
        self._set(key, [str(v) for v in value])

    def reset(self, key: str) -> None:
        default = DEFAULTS.get(key)
        self._set(key, list(default) if isinstance(default, list) else default)
