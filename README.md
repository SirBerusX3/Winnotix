# Winnotix

An IPTV player for Windows — a port of [Hypnotix](https://github.com/linuxmint/hypnotix), the Linux
Mint IPTV app, rebuilt on PySide6 with libmpv for playback.

**Status: phases 0–4 complete.** libmpv renders live IPTV inside a PySide6 window with hardware
decoding, the upstream playlist/provider backend runs on Windows, and the UI is rebuilt: categories,
channels, VOD, series, favourites, search, provider management and both M3U and Xtream providers.
yt-dlp downloads on demand from Preferences, and `python build.py package` produces a portable
one-folder app. The one deliberate omission is translation — the reasoning is in
[roadmap.md](roadmap.md) §5. See [changelog.md](changelog.md) for what has actually been done.

## Why

Hypnotix is excellent and Linux-only. The IPTV logic is portable Python; only the GTK3 application
shell is tied to Linux. Winnotix keeps the former and replaces the latter.

## Running from source

Requires Python 3.12+ (developed on 3.14) and 7-Zip (only to unpack libmpv).

```powershell
git clone --recursive https://github.com/SirBerusX3/Winnotix.git
cd Winnotix
python build.py
```

The `--recursive` matters: `hypnotix/` is a submodule holding the upstream reference tree, and a
plain clone leaves it empty.

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
| `python build.py package` | Build the portable app into `dist/Winnotix`; `--zip` also writes `dist/Winnotix-portable.zip` |
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

## Film and drama channels

For an M3U provider every group is a TV group — Hypnotix decides the type from the group *name*,
looking for the words "VOD" and "SERIES", and a country-grouped playlist has neither. So the landing
page's **Movies** and **Series** tiles sit empty however much film and drama the playlist carries.

**Preferences → Playlists → Sort film and drama channels** fills them, using iptv-org's per-channel
classification joined on the `tvg-id` the playlist already carries. On the bundled iptv-org
catalogue that is **574 channels into Movies across 79 countries and 158 into Series across 37**,
laid out as country tiles exactly like TV Channels.

It is a **genre** sort, and worth knowing what that means before turning it on:

- **Series holds two unlike things.** Channels that loop a single show — Baywatch, Cops, Degrassi —
  sit beside ordinary drama channels like BBC Drama, AXN Asia and Fox Life. iptv-org records what a
  channel *shows*; nothing in its data marks a single-show channel, so the two cannot be separated.
- **Movies means film channels, not a film library.** AMC, Nova Cinema, Cinecanal. For an Xtream
  provider the same tile is a real video-on-demand library, which is a different thing.
- **Channels move rather than being copied**, so a sorted channel leaves its country list under TV
  Channels. That is why the setting is off by default.
- **Ambiguous channels are left alone** — 138 channels are tagged both series and movies, and those
  stay where the playlist put them.
- Free-TV gains almost nothing: only 9 of its 2,053 entries classify as series and 30 as movies.

The index is generated, not hand-maintained — re-run it when iptv-org reclassifies:

```powershell
python tools/generate_genres.py
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

Two cases are worth knowing about, because mpv's own errors mislead on both.

**HTML apparently glued onto a URL.** Some dead hosts answer HTTP 200 with a whole HTTP error page
as the body; mpv treats any `.m3u8` URL as a playlist even without an `#EXTM3U` header, parses that
page as one, and tries to open a "segment" whose name is a line of HTML — producing errors like
`Failed to open http://host/itv1/<ADDRESS><A HREF="...">micro_httpd</A></ADDRESS>`. The playlist is
not corrupt and the URL is not malformed; the host simply has no stream on it.

**A flood of fragment 404s on a `.mpd`.** mpv's DASH demuxer works out the live edge by arithmetic on
the manifest's clock, and on some live manifests it overshoots and requests segments that do not
exist yet — 404 per fragment until it gives up at 100. The channel often keeps playing throughout.
Repeated messages are collapsed in the terminal (`… (+74 repeats suppressed)`), so the log stays
readable and, more importantly, closing the window stays responsive. If the same channel has an HLS
URL, prefer it: HLS lists its segments instead of calculating them.
Many BBC regional channels are affected. Most have an HLS equivalent: swap `vs-cmaf-pushb` for
`vs-hls-pushb` and `.mpd` for `.m3u8`, then add it with the **+** button on the landing page. That
works for the `pc_hd_abr_v2` and `iptv_hd_abr_v1` profiles; the `hevc_*` ones are DASH-only and
404 on the HLS host, so pick a non-HEVC entry.

## Streams that play the wrong thing

The failures above announce themselves. A smaller set does not: the stream answers normally and
plays filler — a takedown notice, or a "watch on our website" slate. Nothing in the response
distinguishes those, so Winnotix keeps a small blocklist in `resources/blocklist.json` and hides
matching entries. It currently covers Pluto TV, which serves a takedown notice for every entry in
the default playlist.

Pluto needs two rules, not one. Free-TV links its stitcher directly, so a `.pluto.tv` host rule
catches those — but iptv-org links through a redirector, `jmp2.uk`, and a host rule matches the URL
as written rather than where it lands. That accounts for **2,342 of the 14,307 entries** in
iptv-org's combined playlist; a sample of 60 resolved 59 to `stitcher-ipv4.pluto.tv` and none
anywhere else, so the redirector is blocked by host too. Resolving thousands of URLs at load time to
find this out would be far more expensive than naming the host.

Turn it off in Preferences, or add your own rules in `blocklist.json` inside `%APPDATA%\Winnotix`:

```json
{ "rules": [
  { "id": "my-rule", "reason": "plays an advert", "host_suffix": ".example.com" }
] }
```

A rule needs an `id` and a `reason`, plus `host_suffix` and/or `url_regex`. Reusing a built-in `id`
replaces that rule — set `"enabled": false` to switch one off.

## Channel logos

imgur withdrew from the United Kingdom in September 2025 and now serves a "not viewable in your
region" image to UK addresses — with HTTP 200 and a valid `Content-Type`, so nothing about the
response says it is a refusal. That is not a long-tail problem for an IPTV client: imgur hosts 71%
of Free-TV's channel logos and 54% of iptv-org's, so a UK user sees a placeholder on most of the app,
and each refusal gets cached as though it were the real logo.

Winnotix recognises that image by content hash and retries the same URL through DuckDuckGo's image
proxy, which fetches it from outside the blocked region. **The direct fetch is always tried first**,
so outside an affected region no third party is ever contacted, and only the logo's address is ever
sent. Only refusals are retried — a 404 means the image is genuinely gone and is left alone.

Turn it off in **Preferences → Channel logos** if you would rather Winnotix talked to nobody but the
playlist's own hosts. Caches written before this existed are cleaned once at startup.

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
