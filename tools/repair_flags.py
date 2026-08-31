#!/usr/bin/env python3
"""Repair `resources/flags/`, which a Windows checkout mangles.

The upstream [circle-flags](https://github.com/HatScripts/circle-flags) set uses
**symlinks** for codes that share another country's flag: `uk.svg` points at
`gb.svg`, `sj.svg` at `no.svg`, and so on for 17 codes. Git on Windows, without
symlink support enabled, writes the *link target's filename* into the file as
plain text -- so `bq.svg` is nine bytes reading `bq-bo.svg`, and Qt reports
"Start tag expected" every time something asks for it.

    python tools/repair_flags.py            # fix what can be fixed locally
    python tools/repair_flags.py --fetch    # ...and download the rest

Two kinds of breakage, because the vendored set is partial:

* Seven point at a flag we do have (`uk` to `gb`), so the fix is local: copy the
  target's bytes over the stub. No network needed.
* Ten point at a flag that was never vendored -- subdivision and non-ISO codes
  like `bq-bo` (Bonaire), `sh-ac` (Ascension), `european_union`. Only `--fetch`
  can fix those, from upstream.

`countries.flag_file()` rejects a non-SVG file regardless, so an unrepaired
checkout loses a flag rather than spraying Qt errors. This script is what turns
the flag back on.
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLAGS = ROOT / "resources" / "flags"

#: Tried in order. The project has moved default branch before, and the flags
#: have lived at more than one path, so this guesses rather than assuming.
SOURCES = (
    "https://raw.githubusercontent.com/HatScripts/circle-flags/master/flags/{name}",
    "https://raw.githubusercontent.com/HatScripts/circle-flags/main/flags/{name}",
    "https://raw.githubusercontent.com/HatScripts/circle-flags/gh-pages/flags/{name}",
)


def is_svg(data: bytes) -> bool:
    head = data.lstrip()[:64].lower()
    return head.startswith(b"<svg") or head.startswith(b"<?xml")


def stubs() -> list[tuple[Path, str]]:
    """Files that hold a link target's name instead of SVG data."""
    found = []
    for path in sorted(FLAGS.glob("*.svg")):
        data = path.read_bytes()
        if is_svg(data):
            continue
        try:
            target = data.decode("utf-8").strip()
        except UnicodeDecodeError:
            continue        # broken some other way; not ours to guess about
        if target.endswith(".svg") and "\n" not in target:
            found.append((path, target))
    return found


def fetch(name: str, timeout: int = 30) -> bytes | None:
    for template in SOURCES:
        url = template.format(name=name)
        request = urllib.request.Request(url, headers={"User-Agent": "winnotix"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = response.read()
        except (urllib.error.URLError, OSError):
            continue
        if is_svg(data):
            return data
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fetch", action="store_true",
                        help="download flags whose target was never vendored")
    args = parser.parse_args()

    if not FLAGS.is_dir():
        raise SystemExit(f"no flags directory at {FLAGS}")

    broken = stubs()
    if not broken:
        print("All flags are valid SVG; nothing to repair.")
        return 0
    print(f"{len(broken)} flag file(s) hold a link target instead of SVG data.\n")

    local = remote = failed = 0
    for path, target in broken:
        source = FLAGS / target
        if source.is_file() and is_svg(source.read_bytes()):
            path.write_bytes(source.read_bytes())
            print(f"  {path.name:8s} <- {target}")
            local += 1
            continue
        if not args.fetch:
            print(f"  {path.name:8s} -- needs {target}, not vendored (use --fetch)")
            failed += 1
            continue
        data = fetch(target)
        if data is None:
            print(f"  {path.name:8s} -- could not download {target}")
            failed += 1
            continue
        path.write_bytes(data)
        print(f"  {path.name:8s} <- downloaded {target} ({len(data):,} bytes)")
        remote += 1

    print(f"\n{local} repaired locally, {remote} downloaded, {failed} still broken.")
    if failed and not args.fetch:
        print("Re-run with --fetch to download the rest.")
    elif failed:
        print("Those codes will simply have no flag, which the app handles.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
