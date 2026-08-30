# Changelog

All notable changes to Winnotix are recorded here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning will follow [Semantic Versioning](https://semver.org/) once there is a release to version.

Winnotix is a Windows port of [Hypnotix](https://github.com/linuxmint/hypnotix) by Linux Mint,
forked at upstream `0e0fa1c` (v5.6). Licensed GPLv3.

---

## [Unreleased]

### Added

- **Phase 0 complete — libmpv plays IPTV inside a PySide6 window on Windows.** The project's
  riskiest assumption is now validated. Verified live: Free-TV playlist → 1,869 channels, 97 groups,
  181 movies parsed; H.264 1280×720 decoded via **d3d11va** hardware decoding on the `gpu-next` VO,
  clock advancing, frames confirmed on screen by window capture rather than by property read alone.
- `winnotix/core/paths.py` — Windows storage locations. Roaming `%APPDATA%\Winnotix` for settings and
  favourites; local `%LOCALAPPDATA%\Winnotix\cache` for provider playlists, which can run to hundreds
  of MB and should not follow the user between machines. PyInstaller-aware via `sys._MEIPASS`.
- `winnotix/core/settings.py` — `SettingsShim`, a JSON-backed stand-in for `Gio.Settings`. Atomic
  write-and-rename so a crash mid-save cannot truncate a good config. Preserves the `:::` provider
  format, so a provider list can be pasted straight across from a Linux Hypnotix install.
- `winnotix/core/mainthread.py` — Qt equivalent of `GObject.idle_add`, via a queued signal onto a
  GUI-thread `QObject`.
- `winnotix/core/mpvloader.py` — resolves libmpv before `import mpv` (python-mpv binds the DLL at
  import time), using both `os.add_dll_directory` and `%PATH%`.
- `winnotix/core/common.py` — ported from upstream with the five planned changes and nothing else.
- `winnotix/core/xtream.py` — copied byte-identical from upstream (SHA-256 verified). Zero changes.
- `winnotix/ui/video_widget.py`, `winnotix/ui/main_window.py`, `winnotix/__main__.py` — throwaway
  Phase 0 shell. Run with `python -m winnotix`.
- `vendor/libmpv/libmpv-2.dll` — mpv v0.41.0, from the shinchiro `mpv-winbuild-cmake` release
  `20260830` (`mpv-dev-x86_64-*.7z`), the standard Windows libmpv source. Gitignored.
- `.venv` (Python 3.14.7), `requirements.txt`, `.gitignore`.

- **Phase 1 — backend test suite.** 60 tests (58 passing, 2 documenting upstream bugs) over M3U
  parsing, group/series detection, logo cache paths, provider `:::` round-tripping, favourites, and
  the settings shim. Runs in ~0.4s with no GUI and no network. `pytest.ini`, `requirements-dev.txt`.
- Repository initialised: GPLv3 `LICENSE`, `README.md`, `.gitattributes` (pins `*.py`/`*.md` to LF
  so our blobs stay bit-identical to upstream's despite `core.autocrlf=true`), and upstream
  `hypnotix/` pinned as a submodule at `0e0fa1c`.

### Fixed

- Nothing yet — the three defects below are inherited from upstream and deliberately left in place
  until Phase 3, so that a parsing change cannot be confused with a port regression.

### Known upstream defects (found by the Phase 1 tests)

Each is pinned by a `strict=True` xfail test, so fixing one flips its test to a failure and forces
a deliberate decision rather than passing silently.

- **Extensionless logo URLs yield a cache path ending in the literal string `None`** — e.g.
  `favorites-newsNone`. The extension-sniffing loop in `Channel.__init__` leaves `ext` as `None` and
  interpolates it straight into the filename. Affects any playlist whose logo URLs lack an extension,
  which is common.
- **The `SERIES` regex requires zero-padded numbers.** `Show S01E01` groups correctly; `Show S1E1`
  does not and is listed as an ordinary channel.
- **A comma inside a channel name silently truncates it.** `News, Sport and Weather` is stored as
  `Sport and Weather` — `EXTINF`'s greedy `params` group swallows everything up to the last comma.

### Verified

- **PySide6 6.11.2 installs and runs on Python 3.14.7** via the `cp310-abi3` wheel — this was an open
  risk given how new 3.14 is, and it is now closed.
- **The MPV embed really is a one-line change**, as roadmap revision 2 predicted:
  `wid=str(int(widget.winId()))`. No separate player window needed.
- **The five-line `common.py` port is sufficient** — it parsed a real 1,869-channel playlist on
  Windows with no further modification.

### Discovered during Phase 0

- **The settings shim needs seven methods, not six.** Upstream also calls `settings.reset()`
  (`hypnotix.py:1221`) for the reset-providers flow. `roadmap.md` §3 corrected.
- **libmpv-2.dll is 114.8 MB unstripped.** Fine for development, too large to ship as-is —
  Phase 4 should strip it or source a stripped build. Added to the packaging risk list.
- **`LC_NUMERIC` must be forced to `"C"` after `QApplication` construction.** Qt adopts the system
  locale on startup; on a comma-decimal locale libmpv then misparses its own float options. Not a
  theoretical concern — it is why `__main__.py` calls `setlocale` where it does.
- **`winId()` timing confirmed as a real hazard**, not just a caution. It is taken in `showEvent`;
  requesting the handle in `__init__` risks Qt recreating it and leaving mpv drawing into a dead
  window — audio with a black frame.
- **mpv logs `ytdl_hook` errors when yt-dlp is absent.** Harmless for direct HLS/M3U8 streams, which
  is most IPTV, but noisy and will break any source that needs extraction. Phase 3/4 work item.
- **Dead and geo-blocked streams are common in public playlists** — the first Free-TV channel 404s.
  The Phase 0 shell just walks past them silently; the real UI needs visible playback-error feedback.
  Reinforces the "better provider error reporting" item in Phase 5.

### Planning

- **Roadmap revision 2** (`roadmap.md`) — rewritten against an audit of the actual upstream source
  rather than assumptions. Four material corrections to revision 1:
  - MPV embedding downgraded from a major risk to a one-line change
    (`wid=str(int(widget.winId()))`); moved from Priority 4 to Phase 0.
  - Settings port downgraded from a workstream to a ~30-line `Gio.Settings`-shaped shim; the
    schema is only six keys, so `common.py` can run unmodified.
  - Three previously unlisted Linux dependencies added to the blocker inventory: the external
    `circle-flags-svg` package (not vendored in the repo, fails silently), the `wget`/`chmod`
    yt-dlp bootstrap, and the POSIX `mkdir -p` shell-out in `common.py:136`.
  - Licensing hazard identified: the vendored `mpv.py` is **AGPLv3**, not GPLv3. Must be replaced
    with the PyPI `python-mpv` package rather than kept.
- Framework decision settled: **Python + PySide6** (LGPL, keeps ~2,000 lines of portable backend).
- Upstream Hypnotix v5.6 checked out under `hypnotix/` as a read-only reference tree.

---

## Conventions for this file

Group entries under these headings, omitting any that are empty:

- **Added** — new features
- **Changed** — changes to existing behaviour
- **Deprecated** — soon-to-be-removed features
- **Removed** — features removed in this release
- **Fixed** — bug fixes
- **Security** — vulnerability fixes
- **Planning** — roadmap/architecture decisions made before code exists (Winnotix-specific)

Notes:

- Keep `[Unreleased]` at the top; cut it to a dated version heading at release time.
- Record *why* a decision changed, not just *what* changed — the reasoning is the valuable part
  when merging future upstream Hypnotix releases.
- Note any divergence from upstream Hypnotix behaviour explicitly, so parity gaps stay visible.
