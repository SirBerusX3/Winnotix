"""Tests for the Gio.Settings stand-in (winnotix/core/settings.py).

Covers the seven methods upstream actually calls, plus the persistence
behaviour that GSettings gave us for free and this shim has to implement.
"""

from __future__ import annotations

import json

import pytest

from winnotix.core.settings import DEFAULTS, SettingsShim


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
    """These six keys are org.x.hypnotix. Drifting from them breaks parity."""
    assert set(DEFAULTS) == {
        "mpv-options",
        "user-agent",
        "http-referer",
        "active-provider",
        "providers",
        "use-local-ytdlp",
    }
    assert settings.get_string("mpv-options") == "hwdec=auto-safe"
    assert settings.get_string("user-agent") == "Mozilla/5.0"
    assert settings.get_string("http-referer") == ""
    assert settings.get_string("active-provider") == "Free-TV"
    assert settings.get_boolean("use-local-ytdlp") is False
    assert len(settings.get_strv("providers")) == 1


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
    got.append("injected")
    assert len(settings.get_strv("providers")) == 1


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
        "Free-TV:::url:::https://raw.githubusercontent.com/Free-TV/IPTV/master/playlist.m3u8:::::::::"
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
