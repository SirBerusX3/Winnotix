#!/usr/bin/env python3
"""Winnotix developer launcher.

Run with your system Python -- it bootstraps everything else itself:

    python build.py            # set up whatever is missing, then launch
    python build.py setup      # set up only
    python build.py test       # run the test suite
    python build.py package    # build the portable app into dist/
    python build.py doctor     # report what is and is not ready
    python build.py clean      # remove caches and build artefacts

Setup means: create .venv, install requirements when they have changed, and
fetch libmpv if it is absent. Each step is skipped when it is already done, so
`python build.py` on an existing checkout goes straight to launching.

`package` produces a portable one-folder build in dist/Winnotix -- no installer,
nothing written outside the folder at build time. See winnotix.spec for what goes
into it and why.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
VENDOR_MPV = ROOT / "vendor" / "libmpv"
STAMP = VENV / ".winnotix-deps"

REQUIREMENTS = ROOT / "requirements.txt"
REQUIREMENTS_DEV = ROOT / "requirements-dev.txt"

SPEC = ROOT / "winnotix.spec"
DIST = ROOT / "dist" / "Winnotix"

MPV_RELEASES = "https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/latest"
MPV_DLL_NAMES = ("libmpv-2.dll", "mpv-2.dll", "mpv-1.dll")

IS_WINDOWS = os.name == "nt"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

class Failure(RuntimeError):
    """A problem worth reporting cleanly rather than as a traceback."""


def say(message: str) -> None:
    print(f"  {message}")


def step(message: str) -> None:
    print(f"\n==> {message}")


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kwargs)


def requirements_digest() -> str:
    digest = hashlib.sha256()
    for path in (REQUIREMENTS, REQUIREMENTS_DEV):
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def find_mpv_dll() -> Path | None:
    for name in MPV_DLL_NAMES:
        candidate = VENDOR_MPV / name
        if candidate.is_file():
            return candidate
    return None


def find_7zip() -> str | None:
    for name in ("7z", "7za", "7zr"):
        found = shutil.which(name)
        if found:
            return found
    if IS_WINDOWS:
        for guess in (r"C:\Program Files\7-Zip\7z.exe",
                      r"C:\Program Files (x86)\7-Zip\7z.exe"):
            if Path(guess).is_file():
                return guess
    return None


# ---------------------------------------------------------------------------
# Setup steps
# ---------------------------------------------------------------------------

def ensure_venv() -> None:
    if venv_python().is_file():
        say(f"virtualenv present: {VENV}")
        return
    step(f"Creating virtualenv at {VENV}")
    run([sys.executable, "-m", "venv", str(VENV)])
    say("created")


def ensure_dependencies(include_dev: bool = True) -> None:
    digest = requirements_digest()
    if STAMP.is_file() and STAMP.read_text(encoding="utf-8").strip() == digest:
        say("dependencies up to date")
        return

    step("Installing dependencies")
    python = str(venv_python())
    run([python, "-m", "pip", "install", "--upgrade", "pip", "--quiet"])
    args = [python, "-m", "pip", "install", "--quiet", "-r", str(REQUIREMENTS)]
    if include_dev and REQUIREMENTS_DEV.is_file():
        args += ["-r", str(REQUIREMENTS_DEV)]
    run(args)
    STAMP.write_text(digest, encoding="utf-8")
    say("installed")


def ensure_libmpv(refresh: bool = False) -> None:
    existing = find_mpv_dll()
    if existing and not refresh:
        size_mb = existing.stat().st_size / (1024 * 1024)
        say(f"libmpv present: {existing.name} ({size_mb:.1f} MB)")
        return

    if not IS_WINDOWS:
        say("not Windows — install libmpv through your package manager")
        return

    step("Fetching libmpv")
    seven_zip = find_7zip()
    if seven_zip is None:
        raise Failure(
            "libmpv is missing and 7-Zip was not found, so the archive cannot be\n"
            "  extracted. Install 7-Zip (winget install 7zip.7zip) and re-run, or\n"
            "  follow the manual steps in vendor/libmpv/README.md."
        )

    say("looking up the latest shinchiro build…")
    request = urllib.request.Request(
        MPV_RELEASES, headers={"User-Agent": "winnotix-build"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)

    asset = next(
        (a for a in release.get("assets", [])
         if a["name"].startswith("mpv-dev-x86_64-") and a["name"].endswith(".7z")),
        None,
    )
    if asset is None:
        raise Failure(
            f"no mpv-dev-x86_64 asset in release {release.get('tag_name')!r};\n"
            "  fetch it manually — see vendor/libmpv/README.md"
        )

    say(f"downloading {asset['name']} ({asset['size'] / 1e6:.0f} MB)…")
    VENDOR_MPV.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / asset["name"]
        request = urllib.request.Request(
            asset["browser_download_url"], headers={"User-Agent": "winnotix-build"}
        )
        with urllib.request.urlopen(request, timeout=300) as response, \
                open(archive, "wb") as handle:
            shutil.copyfileobj(response, handle)

        say("extracting…")
        run([seven_zip, "x", str(archive), f"-o{tmp}", "-y"],
            stdout=subprocess.DEVNULL)

        for name in MPV_DLL_NAMES:
            found = next(Path(tmp).rglob(name), None)
            if found is not None:
                shutil.copy2(found, VENDOR_MPV / name)
                say(f"installed {name} -> {VENDOR_MPV}")
                return

    raise Failure("the archive contained no libmpv DLL; see vendor/libmpv/README.md")


def setup(refresh_mpv: bool = False, include_dev: bool = True) -> None:
    step("Checking environment")
    ensure_venv()
    ensure_dependencies(include_dev=include_dev)
    ensure_libmpv(refresh=refresh_mpv)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_setup(args) -> int:
    setup(refresh_mpv=args.refresh_mpv)
    print("\nReady. Launch with:  python build.py")
    return 0


def cmd_run(args) -> int:
    setup()
    step("Launching Winnotix")
    # Not check=True: a non-zero exit from the app is the app's news, not a
    # failure of the launcher, and shouldn't produce a traceback here.
    return subprocess.run([str(venv_python()), "-m", "winnotix", *args.extra]).returncode


def cmd_test(args) -> int:
    setup()
    step("Running tests")
    return subprocess.run(
        [str(venv_python()), "-m", "pytest", *args.extra], cwd=ROOT
    ).returncode


def cmd_package(args) -> int:
    setup()

    python = str(venv_python())
    check = subprocess.run([python, "-m", "PyInstaller", "--version"],
                           capture_output=True, text=True)
    if check.returncode != 0:
        raise Failure(
            "PyInstaller is not installed in the venv.\n"
            "  It is listed in requirements-dev.txt, so:  python build.py setup"
        )
    say(f"PyInstaller {check.stdout.strip()}")

    if not SPEC.is_file():
        raise Failure(f"missing {SPEC.name}")

    # PyInstaller deletes the previous dist/ before rebuilding, and Windows will
    # not let it delete a running executable. Left to itself that surfaces as a
    # PermissionError traceback from deep inside shutil; worse, the delete is
    # partial, so the previous build is destroyed *and* not replaced.
    previous = DIST / "Winnotix.exe"
    if previous.is_file():
        try:
            with open(previous, "r+b"):
                pass
        except OSError:
            raise Failure(
                f"{previous} is in use, so the previous build cannot be replaced.\n"
                "  Close Winnotix and run this again."
            ) from None

    step("Packaging")
    # --noconfirm: overwrite a previous dist/ without prompting, since this is
    # run repeatedly. --clean: discard PyInstaller's own analysis cache, which
    # otherwise keeps stale copies of files the spec no longer bundles.
    run([python, "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC)],
        cwd=str(ROOT))

    exe = DIST / "Winnotix.exe"
    if not exe.is_file():
        raise Failure(f"PyInstaller reported success but {exe} is missing")

    total = sum(f.stat().st_size for f in DIST.rglob("*") if f.is_file())
    count = sum(1 for f in DIST.rglob("*") if f.is_file())
    say(f"built {DIST.relative_to(ROOT)}  ({count:,} files, "
        f"{total / (1024 * 1024):.0f} MB)")

    # The two bundled trees the app resolves at run time. Their absence is the
    # failure this build is most likely to have, and the one that would
    # otherwise show up as missing flags and a dead player rather than an error.
    for probe, label in ((Path("_internal/resources/countries.list"), "resources"),
                         (Path("_internal/vendor/libmpv"), "libmpv")):
        target = DIST / probe
        found = target.exists() and (not target.is_dir() or any(target.iterdir()))
        say(f"{label:<10} {'bundled' if found else 'MISSING — ' + str(probe)}")

    if args.zip:
        step("Compressing")
        archive = shutil.make_archive(str(ROOT / "dist" / "Winnotix-portable"),
                                      "zip", root_dir=str(DIST.parent),
                                      base_dir=DIST.name)
        size = Path(archive).stat().st_size / (1024 * 1024)
        say(f"{Path(archive).relative_to(ROOT)}  ({size:.0f} MB)")

    print(f"\nPortable build ready. Run it with:  {exe}")
    return 0


def cmd_doctor(args) -> int:
    step("Winnotix environment")
    ok = True

    print(f"  {'repo':<18} {ROOT}")
    print(f"  {'system python':<18} {sys.version.split()[0]} ({sys.executable})")

    if venv_python().is_file():
        version = subprocess.run(
            [str(venv_python()), "--version"], capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        ).stdout.strip()
        print(f"  {'venv python':<18} {version}")
    else:
        print(f"  {'venv python':<18} MISSING — run: python build.py setup")
        ok = False

    dll = find_mpv_dll()
    if dll is not None:
        print(f"  {'libmpv':<18} {dll.name} "
              f"({dll.stat().st_size / (1024 * 1024):.1f} MB)")
    else:
        print(f"  {'libmpv':<18} MISSING — run: python build.py setup")
        ok = False

    check = (subprocess.run([str(venv_python()), "-m", "PyInstaller", "--version"],
                            capture_output=True, text=True)
             if venv_python().is_file() else None)
    if check is not None and check.returncode == 0:
        print(f"  {'PyInstaller':<18} {check.stdout.strip()}")
    else:
        print(f"  {'PyInstaller':<18} not installed (only needed for: package)")

    seven = find_7zip()
    print(f"  {'7-Zip':<18} {seven or 'not found (only needed to fetch libmpv)'}")

    if venv_python().is_file():
        probe = subprocess.run(
            [str(venv_python()), "-c",
             "import PySide6, mpv, requests; "
             "print(PySide6.__version__)"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=ROOT,
            env={**os.environ, "PATH": f"{VENDOR_MPV}{os.pathsep}{os.environ.get('PATH', '')}"},
        )
        if probe.returncode == 0:
            print(f"  {'PySide6':<18} {probe.stdout.strip()}")
            print(f"  {'imports':<18} OK (PySide6, python-mpv, requests)")
        else:
            tail = (probe.stderr.strip().splitlines() or ["unknown error"])[-1]
            print(f"  {'imports':<18} FAILED — {tail}")
            ok = False

    if (ROOT / ".git").exists():
        # Explicit UTF-8: git emits it, but Python would otherwise decode with
        # the console codepage and mangle anything non-ASCII in a commit subject.
        head = subprocess.run(
            ["git", "log", "-1", "--format=%h %s"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=ROOT,
        ).stdout.strip()
        if head:
            print(f"  {'git HEAD':<18} {head}")

    print("\n  " + ("Everything looks ready." if ok
                    else "Something is missing — see above."))
    return 0 if ok else 1


def cmd_clean(args) -> int:
    step("Cleaning")
    removed = 0
    for pattern in ("**/__pycache__", "**/*.pyc", ".pytest_cache", "build", "dist"):
        for path in ROOT.glob(pattern):
            if VENV in path.parents or path == VENV:
                continue
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
            removed += 1
    say(f"removed {removed} item(s)")

    if args.all:
        for path, label in ((VENV, "virtualenv"), (VENDOR_MPV, "libmpv")):
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
                say(f"removed {label}")
    else:
        say("kept .venv and vendor/libmpv (use --all to remove them too)")
    return 0


# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="build.py",
        description="Set up and launch Winnotix.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="With no command, sets up anything missing and launches the app.",
    )
    sub = parser.add_subparsers(dest="command")

    p_setup = sub.add_parser("setup", help="create the venv, install deps, fetch libmpv")
    p_setup.add_argument("--refresh-mpv", action="store_true",
                         help="re-download libmpv even if present")
    p_setup.set_defaults(func=cmd_setup)

    p_run = sub.add_parser("run", help="set up if needed, then launch (default)")
    p_run.add_argument("extra", nargs=argparse.REMAINDER,
                       help="arguments passed through to the app")
    p_run.set_defaults(func=cmd_run)

    p_test = sub.add_parser("test", help="run the test suite")
    p_test.add_argument("extra", nargs=argparse.REMAINDER,
                        help="arguments passed through to pytest")
    p_test.set_defaults(func=cmd_test)

    p_package = sub.add_parser("package",
                               help="build the portable app into dist/Winnotix")
    p_package.add_argument("--zip", action="store_true",
                           help="also produce dist/Winnotix-portable.zip")
    p_package.set_defaults(func=cmd_package)

    sub.add_parser("doctor", help="report what is and is not ready").set_defaults(
        func=cmd_doctor)

    p_clean = sub.add_parser("clean", help="remove caches and build artefacts")
    p_clean.add_argument("--all", action="store_true",
                         help="also remove .venv and vendor/libmpv")
    p_clean.set_defaults(func=cmd_clean)

    # parse_known_args, not parse_args: argparse matches leading options against
    # the top-level parser before a subcommand's REMAINDER positional sees them,
    # so `build.py test -q` would otherwise fail on an unrecognised -q.
    args, unknown = parser.parse_known_args(argv)
    if args.command is None:
        args, unknown = parser.parse_known_args(["run", *(argv or [])])

    if hasattr(args, "extra"):
        extra = [*args.extra, *unknown]
        # A leading "--" is the caller separating our flags from theirs.
        args.extra = extra[1:] if extra[:1] == ["--"] else extra
    elif unknown:
        parser.error(f"unrecognized arguments: {' '.join(unknown)}")

    try:
        return args.func(args)
    except Failure as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"\nERROR: command failed ({exc.returncode}): "
              f"{' '.join(str(part) for part in exc.cmd)}", file=sys.stderr)
        return exc.returncode
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
