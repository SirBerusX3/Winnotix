# Changelog

All notable changes to Winnotix are recorded here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning will follow [Semantic Versioning](https://semver.org/) once there is a release to version.

Winnotix is a Windows port of [Hypnotix](https://github.com/linuxmint/hypnotix) by Linux Mint,
forked at upstream `0e0fa1c` (v5.6). Licensed GPLv3.

---

## [Unreleased]

### Added

- **iptv-org playlists, as a second catalogue source** (`resources/iptv_org_catalogue.json`,
  `tools/generate_iptv_org_catalogue.py`). [iptv-org/iptv](https://github.com/iptv-org/iptv) is a far
  larger collection than Free-TV — 186 per-country playlists against 96, and 1,465 US channels
  against Free-TV's 2,059 worldwide. The picker (Providers → *Browse country playlists*) now lists
  both, with a source filter, since most countries appear in each.
  - **The raw `streams/*.m3u` files are deliberately not what we point at.** That is where the
    repository keeps channels, split by where each stream comes from — `uk.m3u`, `uk_pluto.m3u`,
    `uk_samsung.m3u`, and 121 more service-specific files. They carry no `group-title` and no
    `tvg-logo`: parsed, `streams/uk.m3u` gives **183 channels, 0 groups, 0 logos**.
  - iptv-org's CI publishes a processed playlist per country that merges every source file for that
    country and adds both. Parsed, `countries/uk.m3u` gives **310 channels, 43 categories, 308
    logos**. So the merge the per-service files need is one iptv-org already does, and does better
    than we could locally — which also answers whether to merge or filter them: they arrive merged.
  - **Each source's whole-world playlist is offered too**, as an *All countries* entry listed first.
    iptv-org's `index.country.m3u` is 14,310 channels grouped by country, so it lands on the
    categories page as 187 country tiles — 186 of which resolve to a bundled flag. Four aliases were
    needed for names `countries.list` spells differently or omits: Democratic Republic of the Congo,
    Republic of the Congo, Vatican City, and Réunion.
  - iptv-org codes the United Kingdom `UK`, where ISO 3166-1 and our flag set say `GB`. The
    generator normalises to our code, so searching "britain" finds both sources' UK entries and the
    flag lookup succeeds. Provider names stay distinct — "Free-TV UK" and "iptv-org United Kingdom".
  - **The blocklist correctly leaves these alone.** iptv-org routes Pluto through `jmp2.uk`
    redirectors that carry the device parameters Pluto's stitcher wants; sampling one resolved to a
    real manifest with no `ptv_takedownslates`. The shipped rule matches `.pluto.tv` hosts in the
    playlist, which these are not, so it removes 0 entries from an iptv-org playlist — correct, not
    a gap.
  - Nothing is vendored: `newIPTVrepo/` is gitignored like the existing Free-TV snapshot. The
    catalogue records URLs only, and playlists are always fetched live.
  - Covered by tests for source tagging, combined-entry ordering, cross-source search and the
    picker's source filter. **Suite is now 223 passing, 2 xfailed.**
- **Xtream API providers.** `xtream.py` (937 lines, byte-identical to upstream) was copied across in
  Phase 1 and imported by nothing; the app refused Xtream providers outright. It is now wired up:
  live channels, movies, series and categories all load, and a series' seasons and episodes are
  fetched on first open, on a worker thread rather than upstream's blocking call behind a wait
  cursor.
  - The integration lives in `winnotix/core/xtream_loader.py`, not in `xtream.py`, so the latter
    stays byte-comparable with upstream. That file's header documents each deviation.
  - **`XTream.load_iptv()` is not used.** Its request methods, its JSON disk cache and its 8-hour
    freshness threshold, and all five model classes are upstream's and used as-is — but the grouping
    is ours, because Xtream namespaces category ids *per stream type* while `load_iptv` resolves
    them against one flat list of all three. Live category 3 and VOD category 3 are unrelated, so
    upstream files movies under whichever TV category sorted first.
  - **Six upstream defects had to be handled** for Xtream to work at all. Four are pinned by tests
    in `tests/test_xtream.py` that name the defect they cover:
    1. `XTream` keeps `state`, `auth_data`, `groups`, `channels`, `movies`, `series` and
       `catch_all_group` on the **class**, never rebinding them in `__init__`. A second Xtream
       provider therefore finds `state["authenticated"]` already true, skips authentication, reads
       the never-reassigned class-level `auth_data` — `{}` — and reports a failure it never
       attempted. `XtreamSession` gives each session its own.
    2. `authenticate()` counts any HTTP 200 carrying a `user_info` object as success. Panels answer
       wrong credentials, expired subscriptions and bans with exactly that shape, so a dead account
       looks connected and then quietly loads nothing.
    3. The per-stream-type category collision above.
    4. `get_series_info_by_id()` nests its episode loop inside its season loop, giving **every
       season a copy of every episode** in the series; and its `Episode` reads `cover` off the
       *season* dict handed to it as `series_info`, losing the series to a `KeyError` when a season
       omits it. Our replacement also drives off the `episodes` map rather than `seasons`, because
       panels routinely return `"seasons": []` alongside a full episode list — upstream shows
       nothing at all for those.
    5. `Channel` normalises the odd `created_live` / `radio_streams` stream types for its type check
       but then builds the URL from the raw value, producing `…/created_live/user/pass/1.ts`.
    6. `authenticate()` calls `r.json()` and indexes `user_info["username"]` unguarded, so an HTML
       error page or the `{"user_info": {"auth": 0}}` most panels answer a bad password with raises
       `ValueError`/`KeyError` straight out of the constructor rather than leaving `auth_data` empty
       for the caller's check.
  - **Failures say what went wrong.** Upstream's entire error path is
    `print("XTREAM Authentication Failed")`, which covers a typo'd URL, a refused connection, an
    expired subscription and a panel that is not Xtream at all. Each now gets its own status-bar
    message, including the common mistake of entering the URL with `/player_api.php` or `/c` on the
    end. On success the status bar reports the account's expiry and connection count.
  - Categories an Xtream panel advertises but has no streams for are dropped rather than listed as
    "Name (0)", matching what the blocklist already does. The catch-all group is called
    *Uncategorised* rather than upstream's `xEverythingElse` — the leading `x` was there to sort it
    last, and we sort explicitly.
  - New setting `hide-adult-content` (default off, matching upstream) with a Preferences toggle.
    pyxtream has always supported it; upstream hardcodes it `False` at its one call site
    (`hypnotix.py:1543`) and never exposes it. It only affects Xtream live channels — M3U playlists
    carry no such marking.
  - **Xtream tests** (`tests/test_xtream.py`, 33 tests) run against a fake panel that answers
    `player_api.php` the way a real one does — including reused category ids and a season-keyed
    episode map — so the whole path is covered with no network and no credentials.
  - Verified end to end through a real `MainWindow` against that fake panel: provider loads, session
    is cached, episodes are fetched on a worker thread and delivered back to the GUI thread, seasons
    partition correctly. **Not yet verified against a live Xtream account** — that needs
    credentials we do not have.
- **Playback failures are visible, and explained** (`winnotix/core/streamcheck.py`). Upstream never
  notices a failed open: mpv logs `Failed to open …` and the GUI carries on showing the channel as
  though it were playing. Winnotix now listens for mpv's `end-file` error, shows a banner over the
  video area and a status-bar line, and then makes **one** request to the URL — on the failure path
  only — to say what actually came back.
  - Distinguishes a 404, a 403 (flagged as the geo-block it usually is), an unreachable host, a
    login or captive-portal page, a valid manifest whose segments are gone, and a server that
    answers HTTP 200 with an entire second HTTP response as the body.
  - That last case is not hypothetical — it is the ITV 1 entry in the Free-TV UK playlist, and it
    produces mpv errors that look like a corrupted playlist. See *Investigated* below.
  - **Tests** (`tests/test_streamcheck.py`) classify each case from a captured response, including
    the verbatim one that host returns, with no network.
- **Reload Provider (Ctrl+R).** Upstream has no manual reload — it re-downloads on a timer, every
  5 minutes for M3U and every 2 hours for Xtream (`hypnotix.py:150,1564`). Reloading a large playlist
  unprompted is exactly the stall lazy logo loading was added to avoid, so this is on demand instead.
  It also gives Xtream's eight-hour listing cache a way to be busted without editing the provider.
- **Country flags on category tiles.** Upstream gets these from `circle-flags-svg`, a Debian package
  with no Windows equivalent, so they have never worked here. 265 ISO-country SVGs are now bundled
  from [HatScripts/circle-flags](https://github.com/HatScripts/circle-flags) (MIT), covering all 86
  country codes the Free-TV playlist uses. Language and genre badges from upstream's own artwork are
  shown alongside.
- **`tvg-country`, `tvg-id` and `tvg-chno` are now parsed.** Upstream reads only `tvg-name`,
  `tvg-logo` and `group-title`, leaving `Channel.id` permanently `None`, though the Free-TV playlist
  supplies all three — `tvg-country` on 1,788 of 2,059 entries. A group's country is taken from a
  majority of its channels' tags, falling back to upstream's name matching.
  - Being straight about the payoff: on the Free-TV playlist this changes almost nothing, because its
    groups are already named exactly after countries, so upstream's match resolves 87 of 95 TV groups
    on its own. Aliases and noise-word stripping add one more (`VOD Italy`). The tag path earns its
    place on playlists whose groups are not named after countries. **The visible win is the flags.**
- **Free-TV playlist picker** (`winnotix/core/catalogue.py`, Providers → *Browse Free-TV playlists*).
  The repo publishes ~95 per-country playlists next to the combined one, but nothing listing them, so
  `tools/generate_catalogue.py` generates `resources/free_tv_catalogue.json` from a checkout or from
  GitHub. Picking one creates an ordinary provider pointing at that URL — nothing about it is special
  afterwards, and the playlist is always fetched fresh.
  - Loading the UK's 55 channels instead of the combined 2,059 is dramatically faster.
  - Search matches name, ISO code, or a country name that resolves to one, so "united kingdom" and
    "britain" both find the playlist the repo calls "UK".
- **Blocklist for streams that resolve but do not play** (`winnotix/core/filters.py`,
  `resources/blocklist.json`). Some entries answer with HTTP 200 and a valid HLS manifest whose
  content is filler — a takedown notice or a "watch on our website" slate. Nothing in the playlist
  or the response distinguishes those from a working stream, so they have to be named.
  - Ships one rule: **Pluto TV**. Investigation of the Free-TV playlist found **131 entries across
    two `*.pluto.tv` stitcher hosts**, and 13 of 13 sampled — across all four groups they appear in
    — returned a ~25-second clip whose segments are named `ptv_takedownslates`. It affects live
    channels as well as movies, not just the VOD entries. On the default playlist this removes 131
    entries: movies 181 → 53, channels 1869 → 1866.
  - Rules live in data, not code, for two reasons: `common.py` stays comparable with upstream, and a
    rule can be retired without a release if Pluto restores stitcher access.
  - Users can add rules in `blocklist.json` in `%APPDATA%\Winnotix`. A user rule with the same `id`
    replaces the built-in one, so setting `"enabled": false` there switches a built-in rule off.
  - Groups emptied by filtering are dropped rather than left showing "Name (0)"; series lose blocked
    episodes and are dropped when nothing is left.
  - New setting `hide-unplayable` (default on) with a Preferences toggle. The status bar reports what
    was hidden and why.
- **Phase 2 — the real UI.** All of upstream's stack pages rebuilt in PySide6, keeping Hypnotix's
  layout and, crucially, its navigation model: there is no page stack, just a single `back_page` that
  each page sets as it is entered. That is what makes Back behave the way Hypnotix users expect —
  Back from a movie returns to the VOD grid, not to wherever you arrived from.
  - `ui/theme.py` — light/dark palettes and stylesheet. Replaces upstream's 8-line CSS *and* its
    XApp dark-mode integration, which has no Windows equivalent;
    `QGuiApplication.styleHints().colorScheme()` supplies the OS preference directly. Linux Mint's
    green accent is kept deliberately: it is part of the app still reading as Hypnotix.
  - `ui/icons.py` — 25 icons drawn as inline SVG. Upstream uses XApp/Adwaita symbolic icon names
    that do not exist on Windows. Rendered per-request in the theme's colour, so one definition
    serves light and dark.
  - `ui/flow_layout.py` — height-for-width wrapping layout, standing in for `GtkFlowBox`, which Qt
    has no equivalent of. Used by the categories, VOD and providers pages.
  - `ui/logos.py` — logo cache. Cache paths and on-disk format match upstream, so a cache populated
    by Hypnotix on Linux stays valid.
  - `ui/widgets.py` — header bar (back / title+subtitle / search / fullscreen / menu), status bar
    with the "Currently playing" strip, tiles, and the channel sidebar.
  - `ui/pages.py` — landing, categories, channels+player, VOD, episodes, providers, provider add and
    edit, delete and reset confirmations, new channel, preferences, spinner.
  - `ui/main_window.py` — navigation, playback, provider CRUD, favourites, search, fullscreen, menu,
    and a stream-information dialog.
- **UI tests** (`tests/test_ui.py`) — run under Qt's offscreen platform, no display and no network.
  Cover the provider form's conditional fields, provider round-tripping, group-name cleanup and the
  flow layout's wrapping arithmetic.
- **Country and catalogue tests** (`tests/test_countries.py`) — attribute parsing, name aliases,
  group resolution including the no-majority case, flag coverage for every catalogue entry, badge
  artwork, and catalogue search. **Suite is now 156 passing, 2 xfailed.**
- **Blocklist tests** (`tests/test_filters.py`) — host/regex matching, removal across every
  collection, group and series cleanup, malformed-rule tolerance, and a check that the *shipped*
  rule really matches both real Pluto hosts and nothing else.
- Bundled `resources/` — the landing-page artwork, badges, `countries.list` and the generic channel
  logo, copied from upstream.

### Changed

- **The playlist picker is no longer Free-TV-only.** `catalogue.py` loads one index per source and
  tags every entry with it, so `provider_name` is `"<source> <name>"` and two sources' entries for
  one country cannot collide as providers. `load(path)` became `load_file(path, source)`; `load()`
  now takes no arguments and returns every source's entries. The Free-TV generator also emits an
  *All countries* entry, so both sources offer their combined playlist the same way.
- **Seasons sort numerically and keep their own names.** The episodes page sorted season and episode
  keys as strings, putting season 10 before season 2, and labelled every season `Season %s` from its
  key as upstream does. That reads correctly for M3U playlists, whose keys are numbers, but an
  Xtream panel names its own seasons and some of those are not numbers at all ("Specials"). Episode
  tiles now carry the episode title as their tooltip.
- **Channel logos load lazily.** Upstream issues one HTTP request per channel the moment a list is
  shown (`hypnotix.py:534-543`), so a 1,869-channel playlist fires 1,869 requests for the ~15 rows
  actually on screen — the reason large providers stall on Linux. Winnotix requests only what is
  visible, plus a screenful of lookahead, through a small thread pool.
- **The channel sidebar uses plain list items rather than one widget per channel.** Upstream builds a
  `GtkListBoxRow` per channel; using items keeps an 1,800-channel list responsive.
- Logo downloads write to a `.part` file and rename, so an interrupted download is never mistaken
  for a valid cache entry on the next run.

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

- `QSvgRenderer.render()` was called without an explicit target rect in both `icons.py` and
  `pages.svg_pixmap`, so it used the SVG's default size and drew fragments in the corner at the
  wrong scale. Every icon and the landing artwork were affected.
- Landing tiles collapsed and clipped their own labels: a `QPushButton` does not adopt a child
  layout's size hint, so the tiles are now sized explicitly.
- Child `QLabel`s inside tiles inherited the generic `QWidget` background rule and painted an opaque
  rectangle over the tile surface.
- Category tiles clipped long names once they carried a flag — "Bosnia and Herzegovina" lost its
  channel count. Same root cause as the landing tiles: `QPushButton` ignores a child layout's size
  hint, so `Tile` now overrides `sizeHint()`.
- Note: the three upstream defects below are *not* fixed. They are inherited from Hypnotix and
  deliberately left in place until Phase 3, so a parsing change cannot be confused with a port
  regression.

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

### Investigated, no change needed

- **The HTML in mpv's "Failed to open" error is not in the playlist, and ITV 1 is simply dead.**
  Playing ITV 1 produced
  `Failed to open http://45.14.84.37/itv1/<ADDRESS><A HREF="http://www.acme.com/software/micro_httpd/">micro_httpd</A></ADDRESS>`,
  which reads as though the playlist author had glued HTML onto the URL. It had not: the entry is
  plain `http://45.14.84.37/itv1/index.m3u8`, verified in both the combined and UK playlists.
  - That host answers **HTTP 200** with `Content-Type: application/octet-stream` whose *body* is a
    complete second HTTP response — a micro_httpd `404 Not Found` page, status line and headers
    included. (The host is not an IPTV server at all: `/itv1/` serves a "Redirect To Login Page"
    from some embedded device.)
  - mpv treats any `.m3u8` URL as a playlist even with no `#EXTM3U` header, so it parsed that error
    page as one, took its last non-comment line — `<ADDRESS>…micro_httpd…</ADDRESS>` — as a relative
    entry, and resolved it against `http://45.14.84.37/itv1/`. Hence the HTML in the URL.
  - **So sanitising the URL would fix nothing** — there is no stream at that address, and the same
    four entries (ITV 1–4) all point at the same dead host. Not blocklisted either: the blocklist is
    for streams that resolve *and play filler*, which cannot be detected automatically, whereas this
    can be, and public playlists rot too fast to enumerate by hand. The fix is the failure reporting
    added above, which now says *"The server answered 200 Ok, but the body is another HTTP response
    — 'HTTP/1.1 404 Not Found'. There is no stream at that address."*
- **The M3U playlists are not stale.** The default provider URL is a live pointer to
  `Free-TV/IPTV@master`, which the repo's own README still names as the URL to use, and it updates
  weekly. A fetch on 2026-08-31 was byte-identical to a checkout of the repo (modulo line endings),
  so Hypnotix's dormancy has never affected playlist freshness.
- **We are not behind upstream Hypnotix either** — pinned at `0e0fa1c`, dated 2026-08-25. Two commits
  landed that day, both cosmetic; substantive work did stop around 2026-02-11.
- **Upstream stores a per-provider EPG URL but never uses it.** It is a form field that saves and
  reloads; there is no programme guide in Hypnotix at all.
- **Our cached playlist is written with CRLF**, 4,119 bytes larger than the source — exactly one byte
  per line. Upstream's `get_playlist` opens the cache in text mode, so Python translates `
` on
  Windows. Harmless, since parsing strips, but it means the cache is not byte-comparable with the
  source. Left alone to avoid a sixth deviation in `common.py`.

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
