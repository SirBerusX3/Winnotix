"""Tests for the packaging guard rails (build.py).

The signing gate and the version resource are covered here. The rest of
build.py drives PyInstaller, pip and a 115 MB download, none of which belongs
in a unit test -- but "an unsigned build must not become a release by accident"
is a rule, and a rule is worth pinning. The version resource is here for a
different reason: it is written once and then only ever read by Windows, so
nothing else would notice if it stopped matching the app.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build  # noqa: E402


@pytest.fixture
def exe(tmp_path):
    path = tmp_path / "Winnotix.exe"
    path.write_bytes(b"MZ")
    return path


def test_no_signing_command_means_unsigned_not_an_error(monkeypatch, exe):
    """Development builds are unsigned, and that must stay frictionless."""
    monkeypatch.delenv(build.SIGN_COMMAND_VAR, raising=False)
    assert build.sign_bundle(exe) is False


def test_a_command_without_the_placeholder_is_rejected(monkeypatch, exe):
    monkeypatch.setenv(build.SIGN_COMMAND_VAR, "signtool sign /fd SHA256")
    with pytest.raises(build.Failure) as caught:
        build.sign_bundle(exe)
    assert "{path}" in str(caught.value)


def test_the_executable_is_substituted_into_the_command(monkeypatch, exe):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return None

    monkeypatch.setenv(build.SIGN_COMMAND_VAR, "mysigner --file {path} --ts")
    monkeypatch.setattr(build, "run", fake_run)

    assert build.sign_bundle(exe) is True
    assert seen["cmd"] == ["mysigner", "--file", str(exe), "--ts"]


def test_a_failing_signer_fails_the_build(monkeypatch, exe):
    """A build that tried to sign and could not is exactly the one that must
    not quietly become a release."""
    import subprocess

    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setenv(build.SIGN_COMMAND_VAR, "mysigner {path}")
    monkeypatch.setattr(build, "run", fake_run)

    with pytest.raises(build.Failure) as caught:
        build.sign_bundle(exe)
    assert "signing failed" in str(caught.value)


def test_a_missing_signer_says_so_plainly(monkeypatch, exe):
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setenv(build.SIGN_COMMAND_VAR, "nosuchtool {path}")
    monkeypatch.setattr(build, "run", fake_run)

    with pytest.raises(build.Failure) as caught:
        build.sign_bundle(exe)
    assert "does not exist" in str(caught.value)


def test_package_offers_the_escape_hatch():
    """Without --allow-unsigned an unsigned archive would be impossible to build.

    Checked through the CLI rather than the parser object, because build.py
    constructs its parser inside main() and that is not worth rearranging for
    a test.
    """
    import subprocess

    result = subprocess.run(
        [sys.executable, str(Path(build.__file__)), "package", "--help"],
        capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert "--allow-unsigned" in result.stdout


# ---------------------------------------------------------------------------
# The version resource
# ---------------------------------------------------------------------------

def string_table(resource) -> dict[str, str]:
    """The StringFileInfo entries, flattened to a dict."""
    table = resource.kids[0].kids[0]
    return {entry.name: entry.val for entry in table.kids}


def test_the_version_is_read_from_the_package():
    """One source of truth: About and the executable must agree."""
    import winnotix

    assert build.read_version() == winnotix.__version__


def test_windows_always_gets_four_numbers():
    assert build.version_numbers("0.1.0") == (0, 1, 0, 0)
    assert build.version_numbers("1.2.3.4") == (1, 2, 3, 4)
    assert build.version_numbers("2") == (2, 0, 0, 0)


def test_a_version_with_no_numbers_is_an_error():
    with pytest.raises(build.Failure):
        build.version_numbers("alpha")


def test_the_resource_carries_the_version_in_both_forms():
    """The string is what Properties shows; the numbers are what Windows sorts
    on, and an installer or an updater compares."""
    resource = build.version_resource()
    version = build.read_version()

    assert string_table(resource)["FileVersion"] == version
    assert string_table(resource)["ProductVersion"] == version

    major, minor, patch, _ = build.version_numbers(version)
    assert resource.ffi.fileVersionMS == (major << 16) | minor
    assert resource.ffi.fileVersionLS == (patch << 16)


def test_the_fields_windows_actually_shows_are_filled_in():
    """FileDescription is the one Task Manager and the SmartScreen prompt use,
    and it is the field a blank version resource costs most."""
    fields = string_table(build.version_resource())

    assert fields["FileDescription"] == "Winnotix IPTV player"
    assert fields["OriginalFilename"] == "Winnotix.exe"
    assert "GPLv3" in fields["LegalCopyright"]


def test_the_language_and_the_translation_entry_agree():
    """A mismatch here is not an error -- Windows just reads neither of them."""
    resource = build.version_resource()
    language, charset = resource.kids[1].kids[0].kids

    assert resource.kids[0].kids[0].name == f"{language:04X}{charset:04X}"
