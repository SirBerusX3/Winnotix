# Winnotix — Hypnotix Windows Port Roadmap

> **Status:** Phases 0–2 complete; Phase 3 complete except for the three inherited upstream parsing
> defects in §5. This document is the *plan* and is kept as written except where the work proved it
> wrong — [changelog.md](changelog.md) is the record of what has actually been done. Phase 4 is
> built as a portable one-folder app (`python build.py package`); an installer remains optional.
> **Revision 2** — rewritten after auditing the actual upstream source. Revision 1 over-estimated
> the difficulty of MPV embedding and settings, and missed several real Linux dependencies.
> See [Appendix A](#appendix-a--what-changed-from-revision-1) for what changed and why.

---

## 1. Measured scope

These numbers come from the checked-out upstream tree at `hypnotix/` (linuxmint/hypnotix @ `0e0fa1c`, v5.6),
not from estimation.

| File | Lines | Porting verdict |
|---|---:|---|
| `hypnotix/usr/lib/hypnotix/mpv.py` | 1,872 | **Delete.** Vendored copy of jaseg's `python-mpv`. Replace with the PyPI package. |
| `hypnotix/usr/lib/hypnotix/xtream.py` | 937 | **Copy verbatim.** Zero GTK/GLib references. Pure `requests` + `json`. |
| `hypnotix/usr/lib/hypnotix/common.py` | 306 | **5 lines to change** (7, 14, 18, 34, 136). Everything else is portable. |
| `hypnotix/usr/lib/hypnotix/hypnotix.py` | 1,718 | **This is the port.** GTK app shell, 95 methods. |
| `hypnotix/usr/share/hypnotix/hypnotix.ui` | 3,064 | **Hand-rebuild.** Glade XML: 112 widget IDs, 16 stack pages. The bulk of the calendar time. |
| `hypnotix/usr/share/hypnotix/shortcuts.ui` | 97 | Trivial — a shortcuts cheat-sheet dialog. |
| `hypnotix/usr/share/hypnotix/hypnotix.css` | 8 | Trivial. |
| `hypnotix/po/*.po` | 60+ files | **Free.** Reusable as-is; only `bindtextdomain` needs repointing. |

**The honest summary:** roughly 2,000 lines of genuinely portable backend that needs ~5 lines of
change, and one GTK application shell (Python + Glade) that needs rewriting in PySide6.

### Target stack

- **Python 3.12+**
- **PySide6** (LGPL — compatible with our GPLv3 distribution)
- **PySide6.QtSvg** — required, not optional: flags, badges and the landing-page art are all SVG
- **python-mpv** from PyPI + bundled `libmpv-2.dll`
- **requests**, **unidecode**

---

## 2. Phase 0 — Derisking spike (do this first, before anything else)

**Goal:** a stream playing in a PySide6 window on Windows. Nothing else.

This phase exists to prove the one assumption the entire project rests on — that libmpv embeds
cleanly into a Qt widget on Windows — *before* committing weeks to a UI rewrite. It is deliberately
ugly and throwaway-tolerant.

### Tasks

1. Create `winnotix/` package skeleton alongside the vendored `hypnotix/` reference tree.
2. Copy `xtream.py` across unmodified.
3. Copy `common.py` across, applying the 5-line fix (see §3).
4. Write `SettingsShim` (see §3) — ~30 lines.
5. Bare `QMainWindow` + a `QWidget` with `setAttribute(Qt.WA_NativeWindow)` for video.
6. Instantiate MPV against that widget's HWND:

   ```python
   # GTK original — hypnotix.py:1639
   wid=str(self.mpv_drawing_area.get_window().get_xid())

   # Windows/Qt equivalent
   wid=str(int(self.video_widget.winId()))
   ```

7. Load the default Free-TV playlist (already the gschema default) and play the first channel.

### Exit criteria

Video and audio playing, in-window, from an M3U URL. If this works, everything after it is
known-quantity labour. If it does not, we find out in a weekend rather than in week six.

### Known gotcha

`winId()` must be called *after* the widget is shown and native — call it from `showEvent`, not
`__init__`, or you will embed into a handle that gets recreated. This is the Qt analogue of the
upstream `"realize"` signal handler at `hypnotix.py:276`.

---

## 3. Phase 1 — Backend, with minimal disturbance

**Goal:** `common.py` and `xtream.py` running on Windows with the smallest possible diff, so upstream
fixes stay easy to merge.

### The 5 lines in `common.py`

| Line | Current | Replacement |
|---:|---|---|
| 7 | `from gi.repository import GLib, GObject` | delete |
| 14 | `GLib.get_user_cache_dir()` → providers path | `%LOCALAPPDATA%\Winnotix\cache` |
| 18 | `GLib.get_user_cache_dir()` → favorites path | `%APPDATA%\Winnotix\favorites` |
| 34 | `GObject.idle_add(func, *args)` | Qt main-thread marshal (below) |
| 136 | `os.system("mkdir -p '%s'")` | `os.makedirs(path, exist_ok=True)` |

Line 136 is a genuine Windows bug, not just a style issue — POSIX single-quote quoting and `mkdir -p`
both fail under `cmd.exe`.

### Keep the decorators, swap their internals

`@async_function` (4 call sites) is plain `threading.Thread` — **already portable, leave it alone.**

`@idle_function` (12 call sites) is the only threading coupling. Replacing its *body* keeps all 12
call sites untouched:

```python
from PySide6.QtCore import QObject, Signal

class _MainThreadInvoker(QObject):
    _invoke = Signal(object, tuple)

    def __init__(self):
        super().__init__()
        self._invoke.connect(lambda fn, args: fn(*args))

_invoker = _MainThreadInvoker()   # constructed on the GUI thread

def idle_function(func):
    def wrapper(*args):
        _invoker._invoke.emit(func, args)
    return wrapper
```

A queued signal connection is the correct Qt equivalent of `GObject.idle_add` — it marshals to the
thread the receiver lives on. Do **not** use `QTimer.singleShot` from a worker thread for this.

### The settings shim — highest-leverage piece of the port

The entire GSettings schema is **six keys**: `mpv-options`, `user-agent`, `http-referer`,
`active-provider`, `providers`, `use-local-ytdlp`.

`common.py` only ever calls `self.settings.get_string(...)`. So a shim that mimics the `Gio.Settings`
method names lets the backend run **completely unmodified**:

```python
class SettingsShim:
    DEFAULTS = {
        "mpv-options": "hwdec=auto-safe",
        "user-agent": "Mozilla/5.0",
        "http-referer": "",
        "active-provider": "Free-TV",
        "providers": ["Free-TV:::url:::https://raw.githubusercontent.com/"
                      "Free-TV/IPTV/master/playlist.m3u8:::::::::"],
        "use-local-ytdlp": False,
    }

    def get_string(self, key) -> str: ...
    def set_string(self, key, value): ...
    def get_boolean(self, key) -> bool: ...
    def set_boolean(self, key, value): ...
    def get_strv(self, key) -> list[str]: ...
    def set_strv(self, key, value): ...
    def reset(self, key): ...          # hypnotix.py:1221 — restores the schema default
```

Seven methods, not six: upstream also calls `settings.reset("providers")` for the "reset providers"
flow. Call-site counts: `get_string` ×9, `set_string` ×2, `get_boolean` ×1, `set_boolean` ×1,
`get_strv` ×1, `set_strv` ×1, `reset` ×1.

Back it with `QSettings` or a JSON file — either is fine. Preserve the `:::`-delimited provider
string format so existing Hypnotix provider configs can be pasted straight in.

### Tests

Parsing is the part most worth testing and the easiest to test — no GUI required:

- M3U parsing against the `EXTINF` / `PARAMS` / `SERIES` regexes
- The series/season/episode grouping logic in `load_channels`
- Provider `get_info()` round-trip through the `:::` format
- Favorites load/save round-trip

---

## 4. Phase 2 — UI shell

**Goal:** navigable app, real data, real playback.

The Glade file maps onto Qt more directly than it might look. The upstream app is a stack-of-pages
design, which is exactly `QStackedWidget`.

### Widget translation table

| GTK (in `hypnotix.ui`) | PySide6 |
|---|---|
| `GtkStack` (×5, incl. the 16 named pages) | `QStackedWidget` |
| `GtkFlowBox` (×3 — categories, VOD, series) | `QListView` in `IconMode` + `QStandardItemModel` |
| `GtkListBox` (channel list) | `QListWidget` |
| `GtkHeaderBar` (×2) | `QToolBar` or a custom title widget |
| `GtkStackSwitcher` | `QTabBar` |
| `GtkSearchEntry` | `QLineEdit` with a clear action |
| `GtkDrawingArea` (`mpv_drawing_area`) | `QWidget` with `WA_NativeWindow` |
| `GtkSpinner` | `QProgressBar` (indeterminate) or a `QMovie` |
| `GtkComboBox` + `GtkListStore` | `QComboBox` |
| `GtkMenuButton` + `GtkMenu` | `QToolButton` + `QMenu` |

### The 16 pages to rebuild

`landing_page`, `categories_page`, `channels_page`, `channel_page`, `new_channel_page`,
`episodes_page`, `vod_page`, `player_page`, `providers_page`, `preferences_page`,
`add_page`, `delete_page`, `reset_page`, `empty_page`, `spinner_page`, plus the stream-info stack.

### Approach

Build these in **hand-written Python**, not Qt Designer `.ui` files. Rationale: the upstream app
already resolves 86 widgets by name through `builder.get_object()` in a loop
(`hypnotix.py:177-272`) — that indirection exists to work around Glade, and reproducing it in Qt
would import the awkwardness without the benefit. Explicit widget construction is more readable and
diffs better.

Do **not** chase visual parity with the Linux Mint theme at this stage. Working first, pretty later.

---

## 5. Phase 3 — Feature parity

Restore in descending order of value-per-unit-effort:

1. **Favorites** — backend already done in `common.py`; UI only
2. **Groups / categories** browsing
3. **Search & filtering** — uses `unidecode`, already cross-platform
4. **Stream info panel** — the `AUDIO_SAMPLE_FORMATS` map and mpv property observers port directly
5. **VOD & series browsing** — the largest single feature; `xtream.py` already supplies the data
6. **Provider management dialogs** — add/edit/delete/reset for URL, local file, and Xtream types
7. **Keyboard shortcuts** — replace `Gtk.AccelGroup` with `QShortcut`/`QAction`
8. **Logos & country flags** — see the `circle-flags-svg` dependency in §7
9. **Dark mode** — drop `XApp` entirely; use `QGuiApplication.styleHints().colorScheme()`
10. **i18n** — repoint `bindtextdomain` at a bundled locale dir; the 60+ existing `.po` files work as-is

**Done:** 1–9, plus the yt-dlp bootstrap (§7 #2) and visible playback-error feedback — pencilled in for Phase 5 polish, pulled
forward because public playlists rot fast enough that a silent failure is a parity gap, not polish.
**Still open:** 10 only, and the recommendation there is to drop it. Three corrections the work
forced:

- **Item 5 badly under-read the Xtream half.** "`xtream.py` already supplies the data" is true of the
  HTTP layer and the model classes, and false of everything joining them to a Provider. Upstream's
  own integration is six lines of glue carrying six defects — shared class-level state across
  providers, an authentication check that accepts rejected accounts, category ids resolved across
  stream-type namespaces that reuse them, an episode loop nested inside its season loop, a URL built
  from an un-normalised stream type, and a constructor that raises on a rejection payload. See the
  header of `winnotix/core/xtream_loader.py`. `xtream.py` itself stays byte-identical.
- **The yt-dlp item was mis-scoped as a port.** §7 #2 reads as three Linux calls to replace.
  The real defect is that upstream never puts its downloaded copy on PATH, so `use-local-ytdlp`
  has never done anything on any platform. Porting the bootstrap faithfully would have reproduced
  a feature that does not work. See the header of `winnotix/core/ytdlp.py`.
- **Item 10 is probably not worth doing.** The `.po` files key off upstream's Glade msgids; our UI
  strings are hand-written Qt and mostly will not match, so the catalogue is not the free win this
  list assumed. Recommend dropping it rather than half-translating the app.

### Known upstream defects (found by the Phase 1 test suite)

These are inherited bugs, not port regressions. They are pinned by `strict=True` xfail tests in
`tests/test_m3u.py`, so fixing one flips its test to a failure and forces a deliberate decision.
Fix them here in Phase 3, not during the port — changing parsing behaviour mid-port makes it
impossible to tell a port regression from an intentional improvement.

| Defect | Effect | Where |
|---|---|---|
| Extensionless logo URLs produce a cache path ending in the literal string `None` (`favorites-newsNone`) | Logo caching silently misbehaves for any playlist whose logo URLs lack a file extension — common in the wild | `common.py` `Channel.__init__`, the `ext` loop |
| The `SERIES` regex requires zero-padded numbers, so `Show S1E1` is not detected as a series | Single-digit seasons/episodes are listed as ordinary channels instead of grouping into a series | `common.py:SERIES` |
| A comma inside a channel name silently truncates it — `News, Sport and Weather` becomes `Sport and Weather` | Channel names lose their leading fragment; `EXTINF`'s greedy `params` group is the cause | `common.py:EXTINF` |

### HiDPI note

`get_surface_for_file()` (`hypnotix.py:414`) does manual cairo surface scaling for HiDPI. Qt handles
this natively — use `QIcon`/`QPixmap` with `devicePixelRatio`, and delete the manual scaling rather
than porting it.

---

## 6. Phase 4 — Packaging

**Goal:** an installable Windows app.

### Milestone definition

A single distributable that loads providers, lists channels, plays a stream, and persists settings
across restarts.

### Tasks

- PyInstaller spec, one-folder mode first (one-file complicates the DLL load path)
- **Bundle `libmpv-2.dll`** and ensure it is discoverable — this is the main packaging risk
- Bundle `resources/` (SVG art, badges, `countries.list`, vendored circle-flags, QSS)
- Bundle the compiled `.mo` locale files
- Create `%APPDATA%\Winnotix` and `%LOCALAPPDATA%\Winnotix\cache` on first run
- Ship `yt-dlp.exe` or point mpv at it via `script-opts=ytdl_hook-ytdl_path=`
- Decide portable vs. installed mode; an installer (Inno Setup / MSIX) can come later

### Storage layout

```
%APPDATA%\Winnotix\settings.json      # or QSettings registry
%APPDATA%\Winnotix\favorites\list
%LOCALAPPDATA%\Winnotix\cache\providers\
%LOCALAPPDATA%\Winnotix\cache\yt-dlp\
```

---

## 7. Linux dependencies — full inventory

Every one of these is a hard break on Windows. This list is the definitive checklist; revision 1 of
this roadmap was missing the first three.

| # | Location | Problem | Fix |
|---|---|---|---|
| 1 | `hypnotix.py:430` | Reads `/usr/share/circle-flags-svg/{code}.svg`. **Separate Debian package, NOT in this repo.** Flags fail silently without it. | Vendor the SVG set into `resources/flags/` |
| 2 | `hypnotix.py:655-656` | yt-dlp bootstrap shells out to `wget` and `chmod a+rx` | Download via `requests`; fetch `yt-dlp.exe`; drop `chmod` |
| 3 | `common.py:136` | `os.system("mkdir -p '%s'")` — POSIX quoting + `mkdir -p` | `os.makedirs(exist_ok=True)` |
| 4 | `hypnotix.py:334` | Hardcoded `/usr/bin/yt-dlp --version` | Resolve via `shutil.which` / bundled path |
| 5 | `hypnotix.py:336,650,657` | `~/.cache/hypnotix/yt-dlp` paths | `%LOCALAPPDATA%\Winnotix\cache\yt-dlp` |
| 6 | `hypnotix.py:15-16` | Forces X11 by clearing `WAYLAND_DISPLAY` | Delete |
| 7 | `hypnotix.py:23-25` | `gi.require_version` / `XApp` / GTK imports | Replaced by the Qt port |
| 8 | `hypnotix.py:35` | `setproctitle.setproctitle("hypnotix")` | Delete — no Windows equivalent needed |
| 9 | `hypnotix.py:38-40` | `LOCALE_DIR = "/usr/share/locale"` | Bundled `resources/locale` |
| 10 | `hypnotix.py:74` | `/usr/share/hypnotix/countries.list` | `resources/countries.list` (269 lines, in repo) |
| 11 | `hypnotix.py:152,840` | `/usr/share/hypnotix/*.ui` Glade files | Replaced by hand-written Qt |
| 12 | `hypnotix.py:164` | `/usr/share/hypnotix/hypnotix.css` | 8 lines → Qt QSS |
| 13 | `hypnotix.py:396-398,444,693` | `/usr/share/hypnotix/pictures/*` | `resources/pictures/` (in repo) |
| 14 | `common.py:14,18` | `GLib.get_user_cache_dir()` | `%LOCALAPPDATA%` / `%APPDATA%` |
| 15 | `common.py:34` | `GObject.idle_add` | Qt queued signal (§3) |
| 16 | schema `org.x.hypnotix` | `Gio.Settings` / GSettings backend | `SettingsShim` (§3) |
| 17 | `mpv.py:31-37` | Loads `mpv-1.dll` by name | Use current PyPI `python-mpv`, which handles `libmpv-2.dll` |

---

## 8. Licensing

- **Hypnotix is GPLv3.** Winnotix stays GPLv3. Preserve upstream copyright headers and attribution.
- **The vendored `mpv.py` is AGPLv3**, not GPLv3 — see its header. Keeping that file would make the
  whole application AGPL. Upstream `python-mpv` has since relicensed to GPLv2+/LGPLv2.1+, so
  **install it from PyPI and delete the vendored copy.** This is a licensing reason, not just a
  maintenance one.
- **PySide6 is LGPL** — fine for GPLv3 distribution. (PyQt6 is GPL/commercial; PySide6 is the
  cleaner choice here, which reinforces the framework decision independently of ergonomics.)
- `xtream.py` derives from pyxtream and py-xtream-codes — keep its attribution block intact.
- **Name the fork clearly.** "Winnotix" avoids implying a Linux Mint endorsement. Don't ship Mint
  branding or the Hypnotix icon set.

---

## 9. Effort estimate

| Phase | Estimate | Risk |
|---|---|---|
| 0 — Derisking spike | A weekend | **The only real unknown.** Resolved early by design. |
| 1 — Backend | 1–2 days | Low — it's ~5 lines plus a shim |
| 2 — UI shell | 3–5 days | Low-medium — volume, not difficulty |
| 3 — Feature parity | 2–4 weeks | Medium — VOD/series is the big one |
| 4 — Packaging | 1–3 days | Medium — libmpv DLL discovery is fiddly |
| 5 — Polish | Open-ended | Low |

**Realistically: a weekend to "it plays a channel," 4–8 weeks part-time to genuine parity.**

---

## 10. Framework decision (settled)

**Python + PySide6.** Reasons, in order:

1. Keeps ~2,000 lines of working Python backend that would otherwise need rewriting
2. LGPL, cleanly compatible with GPLv3 distribution
3. `python-mpv` already supports Windows; Qt HWND embedding is a well-trodden path
4. Qt handles HiDPI, theming and dark mode natively, deleting upstream workarounds

C++/Qt6 would be more native and faster, but discards the entire portable backend for a marginal
gain in an app that is I/O- and decode-bound — mpv does the heavy lifting either way. Electron is
rejected: embedding a real hardware-accelerated player is the app's whole purpose.

---

## 11. Parked — worth doing, not yet scheduled

### Code signing for the portable build

PyInstaller output has a shape antivirus heuristics dislike -- unsigned, self-extracting,
bundling an interpreter -- regardless of what it contains. This is not hypothetical here:
Norton spawned a 250 MB scanner process two seconds after `package` wrote the executable,
and the handle it took kept the terminated process alive long enough to block the next
build. What that costs a developer is an annoyance; what it costs someone downloading
`Winnotix-portable.zip` is a warning, or a silent quarantine.

Signing is the only real remedy. Windows SmartScreen also grants reputation to unsigned
binaries eventually, but on download volume this project will not have.

Worth checking before spending anything -- details and prices move, so treat these as
leads rather than facts:

- **SignPath Foundation** offers free code signing to open-source projects. Winnotix is
  GPLv3, so this is the first door to knock on.
- **Azure Trusted Signing** is the cheap commercial option, billed monthly rather than as
  a yearly certificate, though eligibility rules have changed more than once.
- A conventional **OV certificate** from a CA is the fallback. Since the CA/Browser Forum
  moved to requiring hardware-backed keys, the token or cloud HSM is part of the cost.

Whichever route, signing belongs in `build.py package` as a step after COLLECT, so an
unsigned build is never what gets distributed by accident.

### Route single-series channels into the Series category — **done, with the premise corrected**

> **Shipped as a genre sort, not a single-show sort.** The section below assumed iptv-org's
> per-channel categories would identify a channel looping one show. They do not — `categories` is a
> genre taxonomy, and nothing in the record marks a single-show channel. See `core/genres.py` and
> the changelog entry. What shipped moves 574 channels to Movies and 158 to Series on the bundled
> iptv-org catalogue, grouped by country, behind a Preferences switch that is off by default.
> The two open questions at the end of this section are answered underneath it.

For an M3U provider every group is a `TV_GROUP`, so the landing page's **Movies** and
**Series** tiles are permanently empty — those two only ever fill from an Xtream provider,
because `Group.__init__` decides the type by looking for the words "VOD" and "SERIES" in
the group name (`common.py:88-95`), and a country-grouped playlist never has them.

Plenty of channels in these playlists are not channels in any useful sense: they are a
single show on a loop — South Park, 90210, and hundreds like them. They belong under
Series, laid out the way TV Channels already lays out countries.

**This is probably not the hand-sorting job it looks like.** iptv-org already classifies
its channels, and publishes the classification two ways:

- `https://iptv-org.github.io/api/channels.json` — a `categories` array per channel
  (`series`, `movies`, `animation`, …), keyed by the same `tvg-id` our playlists carry
- `https://iptv-org.github.io/iptv/index.category.m3u` — the same data as a playlist,
  grouped by category

Either gives a `tvg-id` → category mapping, so the work is a catalogue-generation step
plus a routing rule, not a manual pass over 14,310 entries. `tools/` already has the
pattern for this in `generate_iptv_org_catalogue.py`.

Free-TV publishes no categories, so its channels would stay under TV unless matched
through iptv-org's ids, which most of them carry.

Open questions worth settling before starting: whether a "series" channel showing one
show on a loop should present as a series at all when there are no episodes to pick from,
and what the Movies tile does with a channel that is a 24/7 film rotation.

**Both answered by the code rather than by argument.** The `SERIES_GROUP` path drills into
`group.series` and opens seasons and episodes; the `MOVIES_GROUP` path is a poster grid that plays
on click. A channel has nothing to drill into, so both routed sets use the grid, and a routed item
arriving on the Series page is played rather than opened. A 24/7 film rotation is simply a channel
that shows films, which is what the Movies tile now means for an M3U provider — it is a genre
browse there and a VOD library for an Xtream provider, and the Preferences text draws that line.

**One thing the work found that this section did not anticipate.** Free-TV publishes no categories,
which was expected — but matching its channels through iptv-org's ids does not rescue it either:
only 9 of its 2,053 entries classify as series and 30 as movies. This is an iptv-org feature, and
the default provider gains almost nothing from it.

## Appendix A — What changed from revision 1

Revision 1 was written before auditing the source. Four material corrections:

1. **MPV embedding is not a Priority-4 risk — it is one line.** Revision 1 recommended a separate
   player window as the safer first step. That's unnecessary: `wid=str(int(widget.winId()))` is the
   whole change, and `mpv.py:31` shows the vendored library *already* has a Windows branch.
   Qt-embedded playback is Phase 0, not a late-stage risk.

2. **Settings is a 30-line shim, not a workstream.** The schema is six keys, and the backend only
   calls `get_string()`. Mimicking the `Gio.Settings` method names lets `common.py` run unmodified.

3. **Three Linux dependencies were missing** from revision 1's blocker list: the external
   `circle-flags-svg` package (#1 above — not in this repo, fails silently), the `wget`/`chmod`
   yt-dlp bootstrap (#2), and the POSIX `mkdir -p` shell-out in `common.py` (#3).

4. **A licensing hazard was missed:** the vendored `mpv.py` is AGPLv3.

One sequencing change: revision 1 opened with "extract a backend, define data models." But
`common.py` and `xtream.py` **already are** that backend, minus five lines — `xtream.py` has zero
GTK references. A large upfront refactor would burn a week before validating the project's single
riskiest assumption. Phase 0 now proves playback works before any architecture work begins.
