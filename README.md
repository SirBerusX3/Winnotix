# Winnotix

An IPTV player for Windows — a port of [Hypnotix](https://github.com/linuxmint/hypnotix), the Linux
Mint IPTV app, rebuilt on PySide6 with libmpv for playback.

**Status: early. Phase 0 complete** — libmpv renders live IPTV inside a PySide6 window with
hardware decoding, and the upstream playlist/provider backend runs unmodified on Windows. There is
not yet a real UI. See [roadmap.md](roadmap.md) for the plan and [changelog.md](changelog.md) for
what has actually been done.

## Why

Hypnotix is excellent and Linux-only. The IPTV logic is portable Python; only the GTK3 application
shell is tied to Linux. Winnotix keeps the former and replaces the latter.

## Running from source

Requires Python 3.12+ (developed on 3.14) and 7-Zip (only to unpack libmpv).

```powershell
git clone --recursive <this repo>
cd Winnotix
python build.py
```

That is the whole thing. `build.py` creates the virtualenv, installs
dependencies, downloads libmpv if it is missing, and launches the app. Every
step is skipped when it is already done, so later runs go straight to launching.

Or double-click **`Winnotix.bat`**.

### Other commands

| Command | What it does |
|---|---|
| `python build.py` | Set up anything missing, then launch |
| `python build.py setup` | Set up only, without launching |
| `python build.py test` | Run the test suite (arguments pass through to pytest) |
| `python build.py doctor` | Report what is and is not ready |
| `python build.py clean` | Remove caches; `--all` also removes `.venv` and libmpv |

If something misbehaves, `python build.py doctor` is the first thing to try.

If you already cloned without `--recursive`:

```powershell
git submodule update --init
```

## Layout

| Path | What it is |
|---|---|
| `winnotix/core/` | Platform-neutral backend: playlists, providers, Xtream, settings |
| `winnotix/ui/` | PySide6 interface |
| `hypnotix/` | Upstream Hypnotix, pinned as a submodule. **Read-only reference** — never edit |
| `vendor/libmpv/` | libmpv-2.dll (not committed; see its README) |
| `resources/flags/` | Country flags from [circle-flags](https://github.com/HatScripts/circle-flags) (MIT) |
| `tools/` | Maintenance scripts (playlist catalogue generation) |

`winnotix/core/xtream.py` is byte-identical to upstream. `winnotix/core/common.py` differs from
upstream in five places, all documented in its header.

## Playlists

The default provider is the combined [Free-TV/IPTV](https://github.com/Free-TV/IPTV) playlist —
about 2,000 channels, fetched live, so it stays current on its own.

That repo also publishes per-country playlists. **Providers → Browse Free-TV playlists** lists them
with flags and channel counts; picking one adds it as an ordinary provider. Loading the UK's 55
channels beats loading all 2,000 when you only want one country.

The index is generated, not hand-maintained — re-run it when the repo adds countries:

```powershell
python tools/generate_catalogue.py --fetch
```

## Unplayable streams

Public playlists rot. Dead entries usually announce themselves with a 404, but some answer normally
and play filler instead — a takedown notice, or a "watch on our website" slate. Those cannot be
detected automatically, so Winnotix keeps a small blocklist in `resources/blocklist.json` and hides
matching entries. It currently covers Pluto TV, which serves a takedown notice for every entry in
the default playlist.

Turn it off in Preferences, or add your own rules in `blocklist.json` inside `%APPDATA%\Winnotix`:

```json
{ "rules": [
  { "id": "my-rule", "reason": "plays an advert", "host_suffix": ".example.com" }
] }
```

A rule needs an `id` and a `reason`, plus `host_suffix` and/or `url_regex`. Reusing a built-in `id`
replaces that rule — set `"enabled": false` to switch one off.

## Licence

GPLv3 — see [LICENSE](LICENSE).

Winnotix is a derivative work of Hypnotix, © Linux Mint and contributors, forked at commit
`0e0fa1c` (v5.6). `winnotix/core/xtream.py` additionally derives from
[pyxtream](https://pypi.org/project/pyxtream) by Claudio Olmi; its attribution header is preserved.
Country flags in `resources/flags/` are from [circle-flags](https://github.com/HatScripts/circle-flags),
MIT licensed — see `resources/flags/LICENSE.md`.

Winnotix is not affiliated with or endorsed by Linux Mint.
