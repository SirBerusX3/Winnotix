# Winnotix

An IPTV player for Windows — a port of [Hypnotix](https://github.com/linuxmint/hypnotix), the Linux
Mint IPTV app, rebuilt on PySide6 with libmpv for playback.

**Status: Phase 2 complete, Phase 3 well under way.** libmpv renders live IPTV inside a PySide6
window with hardware decoding, the upstream playlist/provider backend runs on Windows, and the UI is
rebuilt: categories, channels, VOD, series, favourites, search, provider management and both M3U and
Xtream providers. Still to come: yt-dlp bootstrapping and packaging. See [roadmap.md](roadmap.md)
for the plan and [changelog.md](changelog.md) for what has actually been done.

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
| `resources/*_catalogue.json` | Generated indexes of the per-country playlists |

`winnotix/core/xtream.py` is byte-identical to upstream, so everything Xtream needs beyond it lives
in `winnotix/core/xtream_loader.py` — including the six upstream defects that had to be worked
around, each documented in that file's header. `winnotix/core/common.py` differs from upstream in
five places, all documented in its header.

## Playlists

The default provider is the combined [Free-TV/IPTV](https://github.com/Free-TV/IPTV) playlist —
about 2,000 channels, fetched live, so it stays current on its own.

**Providers → Browse country playlists** lists 282 more from two sources, with flags and channel
counts. Picking one adds it as an ordinary provider; the source filter says which is which, since
most countries appear in both.

| Source | Playlists | Channels | The UK |
|---|---:|---:|---:|
| [Free-TV/IPTV](https://github.com/Free-TV/IPTV) | 96 | ~4,100 | 55 |
| [iptv-org/iptv](https://github.com/iptv-org/iptv) | 186 | ~25,600 | 310 |

Each source also offers its whole-world playlist as an *All countries* entry, listed first. Both are
grouped by country, so they land on the categories page as country tiles with flags — iptv-org's is
14,310 channels across 187 countries.

A note on which iptv-org URLs these point at. Its repository stores channels in `streams/`, split by
where each stream comes from (`uk.m3u`, `uk_pluto.m3u`, `uk_samsung.m3u`, …), and **those raw files
are not what Winnotix uses**: they carry no `group-title` and no `tvg-logo`, so they load as one
flat, logo-less list. Its CI publishes a processed playlist per country that merges every source
file for that country and adds both. For the UK that is 310 channels across 43 categories with 308
logos, against 183 ungrouped and logo-less in `streams/uk.m3u`.

The indexes are generated, not hand-maintained — re-run them when a repo adds countries:

```powershell
python tools/generate_catalogue.py --fetch
python tools/generate_iptv_org_catalogue.py
```

## Xtream providers

**Providers → Add** and pick *Xtream API*. The server URL is the panel root — `http://host:8080` —
with no `/player_api.php` or `/c` on the end; entering one of those is the usual cause of a provider
that will not connect, and Winnotix says so rather than reporting a generic authentication failure.

Live channels, movies and series load together; a series' seasons and episodes are a separate
request per series, so they are fetched the first time you open one. Listings are cached on disk for
eight hours — the header menu's refresh re-fetches them.

Provider entries use Hypnotix's own `:::` format, so an existing Linux provider list can be pasted
straight across.

## When a channel will not play

Public playlists rot, so this is normal rather than exceptional. Winnotix shows a banner over the
video area and asks the URL itself what went wrong: a 404, a 403 (usually a geo-block), an
unreachable host, a login page, or a playlist that loads while its video segments do not.

One case is worth knowing about because its mpv error is actively misleading. Some dead hosts answer
HTTP 200 with a whole HTTP error page as the body; mpv treats any `.m3u8` URL as a playlist even
without an `#EXTM3U` header, parses that page as one, and tries to open a "segment" whose name is a
line of HTML — producing errors like
`Failed to open http://host/itv1/<ADDRESS><A HREF="...">micro_httpd</A></ADDRESS>`. The playlist is
not corrupt and the URL is not malformed; the host simply has no stream on it.

## Streams that play the wrong thing

The failures above announce themselves. A smaller set does not: the stream answers normally and
plays filler — a takedown notice, or a "watch on our website" slate. Nothing in the response
distinguishes those, so Winnotix keeps a small blocklist in `resources/blocklist.json` and hides
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
MIT licensed — see `resources/flags/LICENSE.md`. The bundled playlist indexes describe playlists
published by [Free-TV/IPTV](https://github.com/Free-TV/IPTV) and
[iptv-org/iptv](https://github.com/iptv-org/iptv) (public domain, Unlicense); no playlist content is
redistributed here, only URLs.

Winnotix is not affiliated with or endorsed by Linux Mint.
