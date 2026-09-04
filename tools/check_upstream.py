#!/usr/bin/env python3
"""Report whether upstream Hypnotix has changed the files Winnotix carries.

Winnotix is not a fork, so GitHub's "N commits ahead/behind" badge does not
apply -- and it would be the wrong signal anyway. Upstream's commits are mostly
translations, packaging and its GTK UI, none of which exists here. What matters
is the small surface actually carried across:

    usr/lib/hypnotix/xtream.py   copied byte-identical
    usr/lib/hypnotix/common.py   five lines changed, listed in roadmap.md section 3

A commit touching either is a real decision -- merge it, or record why not. A
commit touching anything else is noise to this project, and saying so is the
point of this script rather than counting commits.

    python tools/check_upstream.py            # human-readable report
    python tools/check_upstream.py --json     # machine-readable

Exits 0 whether or not upstream moved; a non-zero exit means the check itself
failed. Callers decide what to do about drift -- see
.github/workflows/upstream.yml, which opens an issue only when a carried file
changes.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPSTREAM_URL = "https://github.com/linuxmint/hypnotix.git"
SUBMODULE = "hypnotix"

#: The only upstream files this project carries. Everything else was rewritten
#: or dropped, so a change to it is not a merge decision here.
CARRIED = (
    "usr/lib/hypnotix/common.py",
    "usr/lib/hypnotix/xtream.py",
)


def git(*args: str, cwd: Path | str | None = None) -> str:
    result = subprocess.run(["git", *args], cwd=str(cwd or ROOT),
                            capture_output=True, text=True, check=True)
    return result.stdout.strip()


def pinned_commit() -> str:
    """The submodule gitlink, read without needing the submodule checked out."""
    line = git("ls-tree", "HEAD", SUBMODULE)
    if not line:
        raise SystemExit(f"no {SUBMODULE} entry in HEAD -- is this the right repo?")
    # 160000 commit <sha>\t<path>
    return line.split()[2]


def upstream_head() -> str:
    line = git("ls-remote", UPSTREAM_URL, "HEAD")
    if not line:
        raise SystemExit("could not read upstream HEAD")
    return line.split()[0]


def _history_dir(stack) -> Path:
    """A checkout with enough history to diff two commits.

    The local submodule when it is present, since fetching it is cheaper than
    cloning; otherwise a temporary blobless clone, which is what CI gets.
    """
    local = ROOT / SUBMODULE
    if (local / ".git").exists() or (local / ".git").is_file():
        try:
            git("fetch", "--quiet", "origin", cwd=local)
            return local
        except subprocess.CalledProcessError:
            pass    # offline, or the remote moved: fall through to a clone
    tmp = stack.enter_context(tempfile.TemporaryDirectory())
    git("clone", "--quiet", "--filter=blob:none", "--no-checkout",
        UPSTREAM_URL, tmp)
    return Path(tmp)


def compare() -> dict:
    """What upstream has done since the pin."""
    import contextlib

    pinned = pinned_commit()
    head = upstream_head()
    if pinned == head:
        return {"pinned": pinned, "upstream": head, "behind": 0,
                "carried_changed": [], "other_changed": 0, "level": True}

    with contextlib.ExitStack() as stack:
        history = _history_dir(stack)
        behind = int(git("rev-list", "--count", f"{pinned}..{head}", cwd=history))
        changed = git("diff", "--name-only", pinned, head, cwd=history).splitlines()

    carried = [path for path in changed if path in CARRIED]
    return {
        "pinned": pinned,
        "upstream": head,
        "behind": behind,
        "carried_changed": carried,
        "other_changed": len(changed) - len(carried),
        "level": False,
    }


def describe(state: dict) -> str:
    """One line for a human, saying what it means rather than what it counted."""
    if state["level"]:
        return f"level with upstream ({state['pinned'][:7]})"
    behind = state["behind"]
    plural = "" if behind == 1 else "s"
    if state["carried_changed"]:
        names = ", ".join(Path(p).name for p in state["carried_changed"])
        return (f"upstream is {behind} commit{plural} ahead and changed {names} "
                f"-- a merge decision")
    return (f"upstream is {behind} commit{plural} ahead, none of it in the files "
            f"this project carries")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    state = compare()
    if args.json:
        print(json.dumps(state, indent=2))
    else:
        print(describe(state))
        if state["carried_changed"]:
            for path in state["carried_changed"]:
                print(f"  changed: {path}")

    # For the workflow: only a carried file is worth interrupting anyone about.
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"carried_changed={'true' if state['carried_changed'] else 'false'}\n")
            handle.write(f"behind={state['behind']}\n")
            handle.write(f"summary={describe(state)}\n")
            handle.write(f"upstream={state['upstream']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
