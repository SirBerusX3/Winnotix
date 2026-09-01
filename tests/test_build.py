"""Tests for the packaging guard rails (build.py).

Only the signing gate is covered here. The rest of build.py drives PyInstaller,
pip and a 115 MB download, none of which belongs in a unit test -- but "an
unsigned build must not become a release by accident" is a rule, and a rule is
worth pinning.
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
