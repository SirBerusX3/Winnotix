"""Tests for the Gio.Settings stand-in (winnotix/core/settings.py).

Covers the seven methods upstream actually calls, plus the persistence
behaviour that GSettings gave us for free and this shim has to implement.
"""

from __future__ import annotations

import json

import pytest

from winnotix.core.settings import (
    DEFAULTS,
    UPSTREAM_KEYS,
    WINNOTIX_KEYS,
    SettingsShim,
)


@pytest.fixture
def settings_path(tmp_path):
    return tmp_path / "settings.json"


@pytest.fixture
def settings(settings_path):
    return SettingsShim(path=settings_path)


# --------------------------------------------------------------------------
# Schema fidelity
# --------------------------------------------------------------------------

def test_defaults_match_the_upstream_gschema(settings):
    """These six keys are org.x.hypnotix. Drifting from them breaks parity.

    Winnotix-only keys are listed separately in WINNOTIX_KEYS, so adding one is
    a deliberate act rather than accidental drift from upstream. `providers` is
    the one upstream *value* that deliberately differs -- see below.
    """
    assert UPSTREAM_KEYS == {
        "mpv-options",
        "user-agent",
        "http-referer",
        "active-provider",
        "providers",
        "use-local-ytdlp",
    }
    assert set(DEFAULTS) == UPSTREAM_KEYS | WINNOTIX_KEYS
    assert settings.get_string("mpv-options") == "hwdec=auto-safe"
    assert settings.get_string("user-agent") == "Mozilla/5.0"
    assert settings.get_string("http-referer") == ""
    assert settings.get_string("active-provider") == "Free-TV"
    assert settings.get_boolean("use-local-ytdlp") is False


def test_two_providers_ship_by_default(settings):
    """The one upstream value Winnotix deliberately differs on.

    Upstream ships Free-TV alone, which publishes no categories -- so the Movies
    and Series tiles start empty, and searching across providers has nothing to
    search. iptv-org's combined playlist rides along unopened: only the active
    provider loads at startup, and that is still Free-TV.
    """
    providers = settings.get_strv("providers")
    assert len(providers) == 2
    assert [p.split(":::")[0] for p in providers] == [
        "Free-TV", "iptv-org All countries"]
    assert settings.get_string("active-provider") == "Free-TV"


def test_the_default_providers_are_named_as_the_picker_would_name_them(settings):
    """Otherwise adding one from Browse country playlists makes a second copy
    of a provider that is already there."""
    from winnotix.core import catalogue

    combined = {e.provider_name: e.url for e in catalogue.load() if e.combined}
    for entry in settings.get_strv("providers"):
        name, _type, url = entry.split(":::")[:3]
        if name in combined:
            assert combined[name] == url


def test_the_theme_follows_windows_by_default(settings):
    """Which is what the app did before the setting existed."""
    from winnotix.ui.theme import THEME_CHOICES

    assert settings.get_string("theme") == "system"
    assert "theme" in WINNOTIX_KEYS
    assert settings.get_string("theme") in [value for value, _ in THEME_CHOICES]


def test_unplayable_streams_are_hidden_by_default(settings):
    """Most users want the takedown-slate streams gone without configuring it."""
    assert settings.get_boolean("hide-unplayable") is True


def test_default_provider_uses_the_triple_colon_format(settings):
    assert settings.get_strv("providers")[0].count(":::") == 5


# --------------------------------------------------------------------------
# Accessors
# --------------------------------------------------------------------------

def test_string_round_trip(settings):
    settings.set_string("user-agent", "Winnotix/1.0")
    assert settings.get_string("user-agent") == "Winnotix/1.0"


def test_boolean_round_trip(settings):
    settings.set_boolean("use-local-ytdlp", True)
    assert settings.get_boolean("use-local-ytdlp") is True


def test_strv_round_trip(settings):
    providers = ["A:::url:::http://a::::::", "B:::url:::http://b::::::"]
    settings.set_strv("providers", providers)
    assert settings.get_strv("providers") == providers


def test_strv_returns_a_copy_not_the_live_list(settings):
    """Mutating a returned list must not corrupt stored state."""
    got = settings.get_strv("providers")
    before = len(got)
    got.append("injected")
    assert len(settings.get_strv("providers")) == before


def test_reset_restores_the_schema_default(settings):
    settings.set_strv("providers", ["custom:::url:::http://x::::::"])
    settings.reset("providers")
    assert settings.get_strv("providers") == DEFAULTS["providers"]


def test_reset_does_not_alias_the_defaults_dict(settings):
    """A reset then a mutation must not rewrite DEFAULTS itself."""
    settings.reset("providers")
    settings.get_strv("providers").append("x")
    settings.set_strv("providers", settings.get_strv("providers") + ["y"])
    assert DEFAULTS["providers"] == [
        "Free-TV:::url:::https://raw.githubusercontent.com/Free-TV/IPTV/master/playlist.m3u8:::::::::",
        "iptv-org All countries:::url:::https://iptv-org.github.io/iptv/index.country.m3u:::::::::",
    ]


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------

def test_values_persist_across_instances(settings_path):
    first = SettingsShim(path=settings_path)
    first.set_string("user-agent", "Persisted/1.0")
    first.set_boolean("use-local-ytdlp", True)

    second = SettingsShim(path=settings_path)
    assert second.get_string("user-agent") == "Persisted/1.0"
    assert second.get_boolean("use-local-ytdlp") is True


def test_autosave_writes_on_every_set(settings, settings_path):
    settings.set_string("user-agent", "X")
    assert json.loads(settings_path.read_text(encoding="utf-8"))["user-agent"] == "X"


def test_autosave_can_be_disabled(settings_path):
    deferred = SettingsShim(path=settings_path, autosave=False)
    deferred.set_string("user-agent", "X")
    assert not settings_path.exists()
    deferred.save()
    assert json.loads(settings_path.read_text(encoding="utf-8"))["user-agent"] == "X"


def test_missing_file_falls_back_to_defaults(settings_path):
    assert not settings_path.exists()
    assert SettingsShim(path=settings_path).get_string("user-agent") == "Mozilla/5.0"


def test_corrupt_file_falls_back_to_defaults_without_raising(settings_path):
    """A truncated or hand-edited config must not stop the app starting."""
    settings_path.write_text("{ this is not json", encoding="utf-8")
    assert SettingsShim(path=settings_path).get_string("user-agent") == "Mozilla/5.0"


def test_partial_file_fills_gaps_from_defaults(settings_path):
    settings_path.write_text(json.dumps({"user-agent": "Only/1.0"}), encoding="utf-8")
    loaded = SettingsShim(path=settings_path)
    assert loaded.get_string("user-agent") == "Only/1.0"
    assert loaded.get_string("mpv-options") == "hwdec=auto-safe"


def test_unknown_keys_in_file_are_ignored(settings_path):
    settings_path.write_text(
        json.dumps({"user-agent": "X", "not-a-real-key": "junk"}), encoding="utf-8"
    )
    loaded = SettingsShim(path=settings_path)
    assert loaded.get_string("user-agent") == "X"
    assert "not-a-real-key" not in loaded._values


def test_save_creates_missing_parent_directories(tmp_path):
    nested = tmp_path / "a" / "b" / "settings.json"
    SettingsShim(path=nested).set_string("user-agent", "X")
    assert nested.exists()


def test_save_leaves_no_temporary_files_behind(settings, settings_path):
    settings.set_string("user-agent", "X")
    settings.set_string("user-agent", "Y")
    assert [p.name for p in settings_path.parent.iterdir()] == [settings_path.name]


def test_existing_config_survives_a_failed_write(settings, settings_path, monkeypatch):
    """Atomic replace: a crash mid-save must not truncate a good config."""
    settings.set_string("user-agent", "Good/1.0")

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("winnotix.core.settings.os.replace", boom)
    with pytest.raises(OSError):
        settings.set_string("user-agent", "Bad/2.0")

    reloaded = SettingsShim(path=settings_path)
    assert reloaded.get_string("user-agent") == "Good/1.0"
    assert [p.name for p in settings_path.parent.iterdir()] == [settings_path.name]


def test_non_ascii_values_round_trip(settings, settings_path):
    settings.set_string("user-agent", "Winnotix/1.0 (Café)")
    assert SettingsShim(path=settings_path).get_string("user-agent") == "Winnotix/1.0 (Café)"


# --------------------------------------------------------------------------
# Numeric accessors
#
# Not part of the seven upstream calls, but real Gio.Settings method names, so
# the shim keeps its shape rather than growing a bespoke API for the subtitle
# preferences.
# --------------------------------------------------------------------------

def test_doubles_round_trip(settings_path):
    settings = SettingsShim(settings_path)
    settings.set_double("subtitle-scale", 1.75)
    assert settings.get_double("subtitle-scale") == 1.75
    assert SettingsShim(settings_path).get_double("subtitle-scale") == 1.75


def test_ints_round_trip(settings_path):
    settings = SettingsShim(settings_path)
    settings.set_int("subtitle-position", 85)
    assert settings.get_int("subtitle-position") == 85
    assert SettingsShim(settings_path).get_int("subtitle-position") == 85


def test_a_corrupt_number_falls_back_to_the_default(settings_path):
    """A hand-edited settings.json should not stop the app starting."""
    settings_path.write_text(json.dumps({"subtitle-scale": "enormous"}),
                             encoding="utf-8")
    settings = SettingsShim(settings_path)
    assert settings.get_double("subtitle-scale") == DEFAULTS["subtitle-scale"]


def test_the_subtitle_defaults_match_mpv(settings_path):
    """1.0 and 100 are mpv's own sub-scale and sub-pos, so the defaults are a
    no-op until someone changes them."""
    settings = SettingsShim(settings_path)
    assert settings.get_double("subtitle-scale") == 1.0
    assert settings.get_int("subtitle-position") == 100
    # True is what the app did before the switch existed: mpv auto-selects a
    # track the stream marks as default, so this makes that undoable.
    assert settings.get_boolean("subtitles-visible") is True
