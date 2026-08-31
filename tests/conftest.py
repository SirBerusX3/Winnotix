"""Shared fixtures.

The backend reads its storage locations from module-level constants resolved at
import time, so tests redirect those constants rather than the environment --
patching %APPDATA% after import would have no effect.
"""

from __future__ import annotations

import pytest

from winnotix.core import common


@pytest.fixture
def providers_dir(tmp_path, monkeypatch):
    """Redirect the provider/logo cache at a temp dir for the duration of a test."""
    path = tmp_path / "providers"
    path.mkdir()
    monkeypatch.setattr(common, "PROVIDERS_PATH", str(path))
    return path


@pytest.fixture
def favorites_file(tmp_path, monkeypatch):
    path = tmp_path / "favorites" / "list"
    path.parent.mkdir(parents=True)
    monkeypatch.setattr(common, "FAVORITES_PATH", str(path))
    return path


class FakeSettings:
    """Minimal stand-in for SettingsShim: Manager's two lookups, and LogoCache's."""

    def __init__(self, **overrides):
        self._values = {
            "user-agent": "Mozilla/5.0",
            "http-referer": "",
            "proxy-blocked-logos": True,
        }
        self._values.update(overrides)

    def get_string(self, key):
        return self._values.get(key, "")

    def get_boolean(self, key):
        return bool(self._values.get(key, False))


@pytest.fixture
def manager(providers_dir):
    return common.Manager(FakeSettings())


def write_m3u(path, body: str):
    path.write_text("#EXTM3U\n" + body.strip() + "\n", encoding="utf-8")
    return path
