# SignPath Foundation application — the details, and the outcome so far

Notes for applying at <https://signpath.org/apply>. Kept in the repo because the
answers are facts about the project, and a reviewer may ask for them again.

## Outcome: declined 2026-09-02, on visibility alone

Applied and declined the same day the project was first released. The reason
given was public visibility rather than anything about the software:

> The Foundation program is designed for projects that have already established
> a certain level of public trust and visibility [...] we look for external
> signals such as community adoption (GitHub stars, forks, contributors),
> external articles, independent references or discussions [...] This isn't a
> judgment on the quality or potential of your work.

They invited a reapplication once those signals exist. Nothing below needs
changing for that — the answers are the same, and the CI pipeline they would
have asked about now exists (`.github/workflows/release.yml`). What has to
change is the project's reach, which is not something a build script can fix.

**The other two routes are closed, not merely expensive.** Azure Artifact
Signing (formerly Trusted Signing) restricts *individual* identity validation to
the United States and Canada, and its organisation route wants three or more
years of verifiable tax history, so incorporating would not open it either. That
leaves a commercial OV certificate at roughly $215–220 a year with a hardware
token or cloud HSM — and worth knowing before buying one: SmartScreen builds
reputation per publisher, so a fresh OV certificate removes "unknown publisher"
without immediately removing the warning.

## The form

| Field | Answer |
|---|---|
| Project name | Winnotix |
| Repository | https://github.com/SirBerusX3/Winnotix |
| License | GPL-3.0 (OSI-approved, no commercial dual-licensing) |
| Download / release URL | https://github.com/SirBerusX3/Winnotix/releases/latest |
| Description | An IPTV player for Windows: a port of Hypnotix, the Linux Mint M3U/Xtream IPTV app, rebuilt on PySide6 with libmpv for playback. |
| Artifact to sign | `dist/Winnotix/Winnotix.exe` inside `Winnotix-portable.zip` (PyInstaller one-folder build) |

## How the eligibility conditions are met

- **No malware** — the app plays streams from playlists the user configures. It
  makes no network request that is not a playlist, a logo, a programme guide or
  the stream itself, and downloads no executable except yt-dlp, on request,
  from yt-dlp's own GitHub releases.
- **OSS license** — GPLv3, matching upstream Hypnotix. No dual licensing.
- **No proprietary code** — dependencies are PySide6 (LGPL), python-mpv
  (GPLv2+/LGPLv2.1+), requests, unidecode, and libmpv (LGPLv2.1+), which is
  redistributed as a DLL. Vendored assets: circle-flags (MIT, attribution in
  `resources/flags/LICENSE.md`) and upstream Hypnotix artwork (GPLv3).
  Upstream's AGPL-licensed vendored `mpv.py` is deliberately **not** used --
  python-mpv comes from PyPI instead. See roadmap.md §8.
- **Maintained** — active; see the commit history and changelog.md.
- **Released** — v0.1.0, link above.
- **Documented** — README.md describes what it does, and every release carries
  install notes.

## How the binary is built from source

One command, and it is the same command a maintainer runs:

```powershell
python build.py package --zip
```

`build.py` creates the virtualenv, installs pinned requirements, fetches
libmpv, and runs PyInstaller against `winnotix.spec` — which is hand-written and
in the repository, so what goes into the bundle is reviewable. `--zip` refuses
to produce a distributable archive from an unsigned build unless
`--allow-unsigned` is passed, which is how 0.1.0 was necessarily built.

Signing is already a step in that pipeline, waiting for a credential:
`build.py sign_bundle()` runs the command template in `WINNOTIX_SIGN_COMMAND`
against the built executable after COLLECT and before the archive is made, and
a configured command that fails fails the build.

## Still to decide with them

- Whether they want the build to run in GitHub Actions. There is no
  `.github/workflows` yet; the terms require a build that is verifiable from
  source rather than a specific CI, but SignPath's own connectors and its
  Pipeline Integrity checks are CI-oriented, so a workflow is likely what they
  will ask for.
- Every release needs manual approval for signing, per their terms — worth
  knowing before automating anything end to end.
