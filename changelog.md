# Changelog

All notable changes to Winnotix are recorded here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning will follow [Semantic Versioning](https://semver.org/) once there is a release to version.

Winnotix is a Windows port of [Hypnotix](https://github.com/linuxmint/hypnotix) by Linux Mint,
forked at upstream `0e0fa1c` (v5.6). Licensed GPLv3.

---

## [Unreleased]

### Added

- **Pluto TV is unblocked: 2,342 channels back, and Series goes from 157 to 558**
  (`resources/blocklist.json`). Both Pluto rules said in their own notes to retire them if Pluto
  restored third-party stitcher access. It has. On 31 August every sampled entry returned an HLS
  manifest whose segments were named `ptv_takedownslates`; today a fresh sample of 53 — 13 targeted
  and 40 random, following each master manifest through to its media playlist — returned real
  `hls_*.ts` segments, with no slates at all. Reported from use before it was measured.
  - **The two sources link Pluto identically**, which was worth checking since one appeared to work
    and the other not: both go through `jmp2.uk` to `stitcher-ipv4.pluto.tv`. Free-TV has 8 such
    entries, iptv-org 2,342. Nothing about the links differs — what changed is Pluto.
  - The effect on `iptv-org All countries`: 11,239 TV channels become 12,957, Movies 572 → 795,
    Series 157 → 558. Most of what iptv-org classifies as series was always Pluto, which is why
    that tile gains the most.
  - **Retired, not deleted.** The takedown lasted two days and could return; the rules keep their
    evidence and re-enabling one is a one-word edit. The tests that pinned "Pluto is blocked" now
    pin "Pluto is not blocked, and the rules would still match if switched back on" — so a rule
    cannot rot silently while it is off.

- **The Movies and Series grids filter too** (`winnotix/ui/pages.py`, `winnotix/ui/flow_layout.py`).
  A grid filters as well as a list does — better, since the tiles reflow to close the gaps instead
  of leaving a column of holes. It needed one thing: the flow layout now treats a hidden tile as
  taking no space, which is what Qt's own layouts do and what the grid would otherwise have got
  wrong.
  - Tiles are hidden and shown rather than rebuilt. A routed Movies grid runs to 795 posters, and
    rebuilding that many widgets per keystroke is the one way to make a filter feel slower than
    scrolling.
  - Ctrl+F now focuses whichever filter the current page has, and the placeholder names what it
    filters — "Filter movies…", "Filter series…".

- **Search every provider at once** (`winnotix/core/search.py`, and a checkbox under the channel
  filter). The filter answers "where is BBC One in this list"; this answers "which of my providers
  has BBC One at all", which is the question two providers create and neither list can answer.
  Results are labelled with the provider they came from, and opening one switches to that provider
  before it plays — the channel could be played from its URL alone, but everything around it, the
  list behind it and favourites and the guide, is scoped to the provider that is open.
  - **Cached only, deliberately.** It searches the playlists already in
    `%LOCALAPPDATA%\Winnotix\cache\providers`, and a provider that has never been opened is
    named as unsearched rather than downloaded. Ticking a checkbox is not consent to fetch 14 MB,
    which is what `iptv-org All countries` costs. Xtream providers are named too: their channels
    come from an authenticated API and are not in the playlist cache at all.
  - **Built once, then queried in memory.** Both of this author's providers together — 12,023
    channels after the blocklist, one of them iptv-org's whole world — parse from cache in 0.30 s,
    and a search of them takes 1.3 ms. That is why the index is built when the box is ticked and
    not on each keystroke, and why it needs no worker thread.
  - **The blocklist applies; genre routing does not.** A result the app would refuse to list is a
    result that wastes a click, but which tile a channel is filed under is a browsing decision and
    should not decide whether a search can find it.
  - Names that *start* with the term come first, so "bbc" leads with BBC One rather than with a
    channel that mentions the BBC halfway through.
  - Two bugs the work found, both by driving the real window rather than by reading it: the feature
    read its own state back off `isVisible()`, which is false whenever another page is on screen,
    so it turned itself off mid-use; and the list it restored on unticking was the one from before
    the search, which is the wrong provider's list once a result has switched providers.
  - **A third, found by asking whether the grids needed their own version of this.** They do not --
    because the index skips routing, a title that browses under Movies or Series is already in the
    search. But opening one looked it up in `provider.channels`, which is the one list routing takes
    it *out* of, so a routed result reported "no longer in this provider": 1,356 of iptv-org's
    titles with routing on. `search.locate()` now looks through the groups, where every channel is
    regardless of how it was filed.

- **The channel filter is on screen instead of behind a button**
  (`winnotix/ui/pages.py`, `winnotix/ui/widgets.py`, `winnotix/ui/main_window.py`). Searching a
  channel list has worked since Phase 3, but it lived behind a toggle in the header: you had to
  press Ctrl+F, or recognise the magnifier, before a field appeared. Reported as a missing feature,
  which is the clearest evidence a feature is missing. A country list runs to hundreds of rows --
  iptv-org's UK is 310 -- so the filter now sits above the list it filters, visible from the moment
  the list is.
  - Ctrl+F still works and now only moves focus. Escape clears the filter rather than closing it,
    since there is nothing left to close.
  - **A new list arrives unfiltered.** The old toggle cleared the filter when it was switched off;
    a field that stays on screen has to be cleared when the list underneath it is replaced, or the
    previous country's search would silently hide most of the next one.
  - The filter hides with the sidebar, where on its own it would filter a list nobody can see.
  - The header bar loses its search button and entry, so there is one search rather than two ways
    of reaching one.

- **The playlist picker now says where one source ends and the next begins**
  (`winnotix/ui/pages.py`, `winnotix/ui/flow_layout.py`). Two catalogues are bundled, and the
  picker has always listed both — but Free-TV's 96 entries came first, iptv-org's 186 began after
  them, and the only thing naming either was a tooltip. So the larger source read as absent unless
  someone found the Source filter at the top. Reported from use, not from the code.
  - **Each source gets a heading**: "iptv-org — 186 playlists, 11,277 channels". The count is of
    what is on screen, not of what is bundled, so it stays true while a search narrows the list.
  - **The Providers page names both sources and what they hold.** A new install shows one provider
    and a button labelled with an action rather than with what it would find. The line is counted
    from the bundled indexes rather than written down, so it cannot drift from them.
  - `order()` now groups by source, which puts each source's *All countries* entry under its own
    heading instead of both of them above every heading, where neither was explained.
  - The flow layout gained the one thing this needed: a widget marked `SPANS_ROW` takes a row to
    itself at full width. A grid of equal tiles otherwise has nowhere to put a label that
    introduces the tiles beneath it.
  - The hint is measured against the width it really gets — the same word-wrapped-`QLabel` trap
    the Preferences hints hit below, met here before it could clip anything.

- **A version resource on `Winnotix.exe`** (`build.py`, `winnotix.spec`). Properties → Details was
  blank and Task Manager showed the bare filename. That is worth fixing on its own, but the reason
  it is worth fixing *before* a release is that carrying no version information at all is one of
  the things shape-based antivirus heuristics count against a PyInstaller build — which this one
  already looks like in every other respect. It is not a substitute for signing; it is the free
  part of the same problem.
  - **The version is read from `winnotix/__init__.py`, not restated.** `build.version_resource()`
    parses it out rather than importing the package, because the system Python that runs `build.py`
    is not required to have PySide6 installed. About and the executable cannot drift apart.
  - Windows wants four numbers whatever the string says, so `0.1.0` becomes `(0, 1, 0, 0)`.
  - `FileDescription` is the field Task Manager and the SmartScreen prompt actually show, so it
    reads as a sentence — "Winnotix IPTV player" — rather than as a token.

- **Subtitle controls** (`winnotix/ui/main_window.py`, Preferences → Subtitles, **V**). Neither
  Winnotix nor upstream Hypnotix touched subtitles at all, which did not mean subtitles were off:
  mpv selects a track a stream marks as default, so they were appearing with no way to turn them
  off. Measured on the Free-TV UK playlist — GB News carries a WebVTT English track that mpv had
  already selected, while BBC One and BBC Two carry no subtitle track at all.
  - Three settings, applied when the player is created and live whenever they change:
    `sub-visibility`, `sub-scale` (0.5x–3x) and `sub-pos`. The defaults are 1.0 and 100, which are
    mpv's own, so they are a no-op until someone moves them.
  - **The position slider stops at the bottom of the frame.** mpv's `sub-pos` accepts up to 150,
    which puts the text below the picture where it cannot be seen; there is no reason to offer that.
  - **V toggles, matching mpv's own binding**, and the Preferences checkbox is kept in step without
    echoing the change back round. When a channel has no subtitle track the status bar says so,
    rather than reporting "on" and appearing to do nothing.
  - F2 now lists the subtitle tracks a stream offers, or "none in this stream".
  - **Two honest limits, stated in the UI rather than discovered.** Subtitles burned into the
    picture are video and nothing here affects them; and size and position apply to text subtitles,
    not to bitmap DVB ones.
  - The settings shim gains `get_double`/`set_double` and `get_int`/`set_int` — real
    `Gio.Settings` method names, so it keeps its shape rather than growing a bespoke API.

### Fixed

- **Every explanatory hint on the Preferences page was clipped mid-sentence.** A word-wrapped
  `QLabel` reports a size hint computed for a width it does not get, and a `QVBoxLayout` believes
  it, so the last line or two of each explanation was cut off — the blocklist hint lost "add your
  own rules…", the logo hint lost its off-switch sentence. Pre-existing; adding three more hints
  made it obvious. Fixed in two parts, because the first was not enough: the size policy has to ask
  for `heightForWidth` at all, and the measurement has to use the width the label really has, since
  measuring against the column's maximum under-counts once margins are removed.


---

## [0.1.0] - 2026-09-01

First release. Everything below was built during the port; it is grouped as one
version rather than invented history, because there was no earlier release to
diff against.

### Added

- **A signing step in `build.py package`, and a refusal to distribute without it.** Roadmap §11
  asked for signing "as a step after COLLECT, so an unsigned build is never what gets distributed
  by accident". The line drawn here is the **archive**, not the build: `dist/Winnotix` builds
  unsigned with a note, and `--zip` refuses unless something signed the executable, because the zip
  is what gets handed to someone else. `--allow-unsigned` covers an archive that is not for
  distribution.
  - Configured by `WINNOTIX_SIGN_COMMAND`, a command template with `{path}` for the executable — a
    template rather than a fixed `signtool` call, because the three routes worth considering
    (SignPath's free open-source tier, Azure Trusted Signing, an OV certificate on a hardware
    token) take entirely different command lines, and this project has none of them yet.
  - **A configured command that fails, fails the build.** A build that tried to sign and could not
    is precisely the one that must not quietly become a release.
  - **The path is substituted after splitting, and splitting uses `posix=False`.** `shlex` in its
    default mode treats a backslash as an escape, so it silently turned a Windows path into one
    with the separators eaten — a signer handed that fails for a reason nothing in its output
    explains. Caught by a test, not by inspection.
- **A version, shown in About** (`__version__`, 0.0.1 → 0.1.0).

- **A channel check** (`winnotix/core/health.py`, menu → Check Channels, Ctrl+T). Until now a dead
  channel announced itself only by failing to play; `streamcheck` then explained why. This asks the
  question first, for the list on screen. Measured on the Free-TV UK playlist: **54 channels in
  2.3–4.8 s — 43 playable, 7 dead, 4 geo-blocked**, and it independently caught the ITV 1–4
  micro_httpd case this changelog documents, reporting "the body is another HTTP response".
  - **The same response means opposite things before and after a failure**, which is why the
    verdict is computed here rather than reused. A manifest that loads is bad news on the failure
    path — the address is good, so `describe_response` says the channel is off air — and is the
    *good* outcome when checking ahead. The wording is borrowed; the judgement is not.
  - **A 403 is not death.** It is usually geo-blocking, so it is its own state, counted separately
    and never dimmed: the channel is alive and simply not available from here.
  - **Nothing is hidden or removed, only dimmed**, with the reason in the tooltip. A check is one
    request at one moment: across two runs minutes apart the same list reported 3 unreachable and
    then 0, all of them transient timeouts. Being wrong about a channel someone wanted is worse
    than leaving a dead row in place, so the row stays and stays clickable.
  - **Scoped to the open list, not the provider.** A country is tens or hundreds of requests; the
    iptv-org catalogue is 11,000, which is not something to fire at other people's servers from a
    menu. Eight workers, a 4/6 s timeout, one request per distinct URL however many channels share
    it, and verdicts cached on disk for seven days so a second pass costs nothing.
  - Pressing the menu item again stops a run in progress. Queued checks are cancelled rather than
    merely ignored, so stopping costs one timeout instead of one per remaining channel.

- **A programme guide** (`winnotix/core/epg.py`, `ChannelList.apply_guide`, Preferences →
  Playlists). Upstream Hypnotix has none — it stores a per-provider EPG URL, the sixth field of
  the `:::` format and an entry box on the Add-provider form, and then never reads it. Someone
  could type a guide URL into Hypnotix or into Winnotix and nothing whatsoever would happen. Now
  the channel list shows what is on beside each channel, the playback bar shows it while a channel
  plays, and F2 gains Now and Next rows.
  - **Guides come from the playlist itself.** The M3U standard puts them in the header —
    `#EXTM3U x-tvg-url="…"` — and Free-TV's declares **101 gzipped XMLTV files**, one per country.
    So for the default provider this needs no configuration at all. A provider's own EPG field is
    read too, and takes precedence, because for iptv-org it is the only possible source: iptv-org
    declares no guides and publishes none, its `epg` repository being a grabber you run yourself
    and its `guides.json` mapping channels to scraper *sites* rather than to XMLTV.
  - **Only the country on screen is fetched.** The combined `ALL_SOURCES` guide is **191 MB
    gzipped**; one country is 2.6 MB gz for 486 channels and 41,299 programmes, parsed in 1.6 s.
    So guides load when a country's channel list is opened, and are cached on disk for six hours.
    Programmes outside a −2h/+36h window are dropped while parsing, via `iterparse`, because only
    now and next are ever shown and the file holds days.
  - **Matching is partial, by nature rather than by defect.** Guide and playlist use unrelated id
    schemes — epgshare says `BBC.One.West.HD.uk` where our playlists say `BBCOne.uk` — so an id
    join matches **4 of 55** channels on Free-TV UK (7%) and **4 of 310** on iptv-org's UK group
    (1%). Falling back to the guide's `display-name`, normalised for quality suffixes and playlist
    noise like `(720p)` and `[Not 24/7]`, lifts those to **36/55 (65%)** and **55/310 (17%)**.
    Measured in the running app: 29 of 54 rows on Free-TV UK. The rest genuinely have no listings
    published, so they show nothing — a placeholder on every second row would be noise, not
    information.
  - **One alias decides whether the UK works at all.** Of the 64 two-letter codes across those 101
    guides, exactly one is not ISO: `epg_ripper_UK1`, where ISO says `GB`. A group resolves to GB,
    so without resolving that the country with the best coverage of any would silently get
    nothing. Non-ISO codes are now resolved as names, where `UK → GB` already lived.
  - The channel sidebar's default width goes from 250 to 340 px, since a row now carries a channel
    *and* a programme. It is a splitter, so it can be dragged back.
  - A stale cached guide is preferred to none when a fetch fails: a guide is days of listings, so
    yesterday's copy is still largely right.
  - On by default. The guides are named by the playlist the user already chose, so it is the same
    trust boundary as its streams and its logos, and nothing is fetched until a channel list is
    opened.

- **The Movies and Series tiles fill up for an M3U provider** (`winnotix/core/genres.py`,
  `tools/generate_genres.py`, `resources/channel_genres.json`, Preferences → Playlists).
  For an M3U provider every group is a `TV_GROUP` — `Group.__init__` decides the type by looking
  for the words "VOD" and "SERIES" in the group name (`common.py:88-95`), and a country-grouped
  playlist never has them — so both tiles were permanently empty however much film and drama the
  playlist carried. iptv-org classifies its channels by the same `tvg-id` our playlists already
  parse, which is enough to fill them. Measured on the bundled iptv-org catalogue: **574 channels
  to Movies across 79 countries, 158 to Series across 37**, laid out as country tiles exactly like
  TV Channels.
  - **The roadmap's premise for this was wrong, and §11 is corrected.** It assumed iptv-org's
    `categories` would identify a channel looping a single show. It does not: `categories` is a
    *genre* taxonomy, and no field in the record marks a single-show channel — the shape is `id`,
    `name`, `alt_names`, `network`, `owners`, `country`, `categories`, `is_nsfw`, `launched`,
    `closed`, `replaced_by`, `website`. So the series set mixes Baywatch, Cops and Degrassi with
    AXN Asia, BBC Drama and Fox Life, and the movies set is linear film channels — AMC, Nova
    Cinema, Cinecanal — not a video-on-demand library. What shipped is a genre browse, and the
    Preferences text says so rather than promising single shows.
  - **The join needs the ids normalised, and this is not cosmetic.** iptv-org's published
    playlists append a feed suffix — `BBCOne.uk@SD` — while its API keys on the bare `BBCOne.uk`.
    Joined raw, **1 of 12,358** entries matches; normalised first, **12,336**. It happens in
    `genres.py` rather than `common.py:141` so the parser stays at its five documented deviations
    from upstream.
  - **Routing runs after the blocklist, never before.** 503 of the 689 channels iptv-org
    classifies as series were Pluto TV behind the `jmp2.uk` redirector, so the other order would
    have filled a brand-new page with takedown slates. Fixing that gap is what the entry below is.
  - **Channels tagged both series and movies are skipped** — 138 of 2,572, AXN White next to
    Battlestar Galactica. Routing *moves* a channel out of its country list, so it only happens
    where the classification is unambiguous and the conservative failure is that a channel stays
    where it already was.
  - A routed channel reaches the Series grid as a `Channel`, not a `Serie`, because it has no
    seasons or episodes to open — so it plays on click like any other channel, and it is counted
    from its group rather than pushed into `provider.series`, which would break every consumer
    expecting `.seasons`/`.episodes`, `Blocklist.apply` included.
  - **Off by default**, unlike the other two Winnotix settings, because it moves channels out of
    the country lists the playlist published them in — a visible change to a playlist the user
    chose. Toggling it reloads from the cached copy, so it takes effect without a restart.
  - `route()` is idempotent: the groups it creates are flagged and never re-examined, so a second
    pass cannot cascade.

- **Flags that a Windows checkout had quietly broken** (`winnotix/core/countries.py`,
  `tools/repair_flags.py`). Upstream circle-flags uses **symlinks** for codes that
  share another country's flag — `uk` → `gb`, `sj` → `no`, 17 in all. Git on Windows
  without symlink support writes the *link target's filename* into the file, so
  `bq.svg` was nine bytes reading `bq-bo.svg`, and Qt logged "Start tag expected" on
  every lookup while drawing nothing.
  - Seven pointed at flags already vendored and were repaired in place. Nine of the
    rest point at subdivision or non-ISO flags never vendored (`sh-ac`,
    `european_union`, `other/united_nations`); none appears in any catalogue or
    playlist. Bonaire, the one that did, now has a working flag.
  - `flag_file()` checks that a file really is SVG rather than trusting its name, so
    an unrepaired checkout loses a flag instead of spraying parse errors. This is the
    part that matters: the breakage returns silently on every fresh Windows clone.
  - `tools/repair_flags.py` resolves what it can locally and `--fetch` downloads the
    rest from upstream.
- **A portable build** (`winnotix.spec`, `launcher.py`, `python build.py package`) —
  roadmap Phase 4. One folder in `dist/Winnotix`, no installer, `--zip` for a
  distributable archive.
  - **One-folder rather than one-file**, for a specific reason: python-mpv resolves
    libmpv at *import* time (`core/mpvloader.py`), and one-file unpacks to a fresh
    temp directory each launch that the loader would have to chase.
  - Nothing in the app needed changing to support being frozen. `paths.project_root()`
    already returned `sys._MEIPASS`, and `mpvloader._candidate_dirs()` already yielded
    the executable's directory — both written in anticipation of this, long before it.
    `resources/` and `vendor/libmpv/` land exactly where those two already look.
  - `launcher.py` exists because PyInstaller freezes a script, and
    `winnotix/__main__.py` is not one: its relative imports only resolve when the
    package is imported. Development still uses `python -m winnotix`.
  - 38 unused Qt modules are excluded — WebEngine, Quick/QML, 3D, Charts,
    Multimedia and the rest — worth roughly half the bundle. QtNetwork and QtOpenGL
    are deliberately left in: Qt reaches for those internally even though the app
    never imports them.
  - **18 MB of Qt that nothing reaches is filtered out.** The Python-level `excludes`
    cannot see it: PyInstaller's PySide6 hook collects Qt's own DLLs as *data*, and
    two plugins drag in trees of their own — `platforminputcontexts` pulls the
    virtual keyboard, which pulls Qml and Quick (13 MB), and the PDF image format
    pulls Qt6Pdf (4.6 MB). The spec names what to drop rather than filtering plugins
    wholesale, because the SVG plugins beside them draw every flag and icon.
    Verified after rebuilding: Qml, Quick, VirtualKeyboard and Pdf gone; Core, Gui,
    Widgets, Svg, Network and OpenGL present, along with the Windows platform
    plugin, both SVG plugins, the TLS backends and the styles.
  - `package` refuses to start when the previous `Winnotix.exe` is running. PyInstaller
    deletes `dist/` before rebuilding and Windows will not delete a running
    executable, so this otherwise surfaced as a `PermissionError` from inside
    `shutil` — having already *partially* deleted the previous build, destroying it
    without replacing it.
  - `package` checks after building that `resources/` and `vendor/libmpv/` actually
    made it into the bundle. Their absence is this build's most likely failure and
    would otherwise surface as missing flags and a dead player rather than an error.
  - `*.spec` stays gitignored — that rule is for the specs PyInstaller generates —
    with an exception for this hand-written one.
- **yt-dlp can be downloaded and is actually used** (`winnotix/core/ytdlp.py`,
  Preferences → yt-dlp). This closes the last named Phase 3 item, and the three Linux
  dependencies roadmap section 7 lists against it: the `wget`/`chmod` bootstrap (#2),
  the hardcoded `/usr/bin/yt-dlp` (#4), and the `~/.cache` paths (#5).
  - **A fourth defect was not a portability one.** Upstream downloads its local copy
    to `~/.cache/hypnotix/yt-dlp` and then never tells mpv it exists — it passes
    `ytdl=True` and nothing more (`hypnotix.py:1645`), while mpv's ytdl_hook resolves
    the binary *by name, through PATH*. So upstream's `use-local-ytdlp` downloads a
    binary that never runs. `apply_preference()` is the missing half: it puts the
    chosen copy's directory on PATH, which is also why it avoids mpv's
    `script-opts` escaping rules — a Windows path is exactly the kind of value
    those rules exist for.
  - Two smaller repairs to the same upstream function: it calls `os.chdir` and never
    changes back, so clicking Update in Preferences permanently moves the process
    working directory; and it verifies nothing about what it downloaded. Here the
    transfer is checked against the SHA-256 the release publishes. Both files come
    from the same host over HTTPS, so that is an integrity check rather than a trust
    anchor — what it reliably catches is a truncated download becoming an executable
    that fails confusingly later. A missing checksum list does not block the install,
    but the UI says the copy was not verified.
  - Preferences now shows both versions — the system copy and ours — with a button
    that reads Download or Update depending on which applies, disabled with a
    percentage while a transfer runs. Before this the panel had a version label,
    and an `ytdlp_update_clicked` signal that nothing emitted and nothing received.
  - A failed download never disturbs a working copy: bytes go to a `.part` file and
    are only renamed into place once the checksum matches.
  - Turning the setting on mid-session takes effect without a restart where mpv
    allows it. Rather than guess whether `ytdl` is settable at run time, the option
    is set and then read back, and the status line says which of the two happened.
- **Winnotix has its own icon** (`assets/`, `resources/appicon.ico`,
  `resources/generic_tv_logo.png`, `tools/generate_icons.py`). The placeholder shown
  for a channel with no usable logo was Hypnotix's own mark, byte-identical to
  upstream's — which roadmap section 8 asks us not to ship — and only **22x22**, so
  every 200x200 VOD poster was a 9x upscale of a 22-pixel image.
  - The blue mark is now the window, task bar, Alt-Tab and dialog icon, set on the
    QApplication so every dialog inherits it. The app had no icon at all before.
  - Windows files a task bar button under the process that launched it, so a
    Python-hosted app shows Python's icon beside its own window. `main()` now claims
    an explicit AppUserModelID before the first window exists, which is what makes the
    task bar use ours.
  - The grey mark replaces the channel-logo placeholder at 512x512 — twice the poster
    size, so it still downscales on a HiDPI screen rather than being blown up.
  - `assets/` keeps the masters (2048px PNGs and a full 16..256 .ico ladder, blue and
    grey); `resources/` keeps only what the app loads. `tools/generate_icons.py`
    derives the second from the first, using Qt rather than Pillow so it runs in the
    project venv with no added dependency.
  - The About dialog still credits Hypnotix and Linux Mint. That is a GPLv3
    obligation, and separate from shipping their artwork.
- **Logos load in the United Kingdom again** (`winnotix/core/logoproxy.py`,
  `winnotix/ui/logos.py`). imgur withdrew from the UK in September 2025 and now serves
  nothing to a UK address. That is not a long-tail gap for an IPTV client: imgur hosts
  **1,457 of Free-TV's 2,059 channel logos (71%) and 7,729 of iptv-org's 14,310 (54%)**,
  so a UK user saw a placeholder on most of the app.
  - Picking a different URL does not fix it. iptv-org's own logo database has a
    non-imgur alternative for only **358** of them. Fetching the *same* URL from
    somewhere else does, so a refused logo is retried through DuckDuckGo's image
    proxy, which makes the request from its own servers.
  - **Which proxy is not a free choice.** imgur refuses most of them. Measured
    against the same imgur logo: `images.weserv.nl` returned 404 for all six URL
    forms (imgur refuses its servers outright), Google's gadget proxy is
    discontinued, allorigins and codetabs were both down with 522, corsproxy.io now
    requires an API key, web.archive.org timed out, and Photon simply redirected
    back to imgur without proxying anything. DuckDuckGo returned a real PNG.
    imgur's own thumbnail forms (`_d.webp`, the `s`/`m` size suffixes) serve the
    block image too, so there is no way around this at the origin.
  - **The refusal does not look like one.** imgur answers a UK request with HTTP 200,
    `Content-Type: image/png`, and a real 336x478 PNG reading "Content not viewable in
    your region" — so no status code, header or decode check can tell it from a logo,
    and it was cached like any other. In one real cache **833 of 1,279 files were
    byte-identical copies of it**, and because a cached file is never re-fetched, each
    one had permanently poisoned that channel's logo.
  - `SentinelWatch` recognises it by content hash, checked only against images whose
    length already matches, so a real logo is settled by a `len()` and never hashed.
    Relying on one hardcoded digest would be brittle — the day imgur redraws that
    image every logo silently reverts — so any image a host repeats across four
    *different* URLs is promoted to a sentinel too, and copies stored before the
    promotion are deleted. Real logos differ; a refusal is the same picture every time.
  - Caches from before this change are cleaned once at startup. The scan hashes only
    size-matching files, so it costs little more than a directory walk.
  - **The proxy is a fallback, never a rewrite.** The direct fetch is tried first, so a
    user outside the blocked region never contacts a third party at all, and only the
    logo address is ever sent.
  - **Only refusals are retried** — connection errors, timeouts, 403/429/451, a block
    page served as `200 text/html`, and a known sentinel image. A 404 is not: the image
    is genuinely gone, and retrying it would double the requests for every dead logo in
    a playlist, of which public playlists have plenty.
  - **A host that keeps refusing is learned.** One wasted round trip per logo across
    9,185 imgur URLs would trade one problem for another, so after three refusals with
    no success a host goes straight to the proxy for the rest of the session. The block
    costs three wasted requests in total, not three thousand.
  - Off switch in Preferences → Channel logos, for anyone who would rather Winnotix
    talked to nobody but the playlist's own hosts. Toggling it clears what has been
    learned so the visible rows retry immediately, with no restart and no reload.
  - Cache paths are unchanged — still derived from the original URL by
    `common.py:Channel.__init__` — so a cache of real logos stays valid and turning the
    proxy off orphans nothing.
- **Closing the window no longer hangs after a stream that logs errors**
  (`winnotix/core/mpvlog.py`, `mpvloader.shutdown()`). Reported against BBC HD
  channels, which play while spamming the terminal — and then froze the app on close. One cause
  behind both symptoms.
  - mpv hands every log line to its client **on its own event thread**, and python-mpv calls the
    handler synchronously from that thread's loop. `MPV.terminate()` destroys the handle and then
    joins that thread with **no timeout** (`mpv.py:1171-1173`), and the thread leaves its loop only
    on the SHUTDOWN event — so it must first drain everything queued ahead of it, running our
    handler and a console write for each. A backlog of thousands is not just noise on screen; it is
    what made closing look like a hang.
  - Measured against a BBC DASH channel: **mpv sent 2,120 log messages in 30 seconds**. Worse, a
    player stuck in libmpv's own retry loop never reaches SHUTDOWN at all — `terminate()` had still
    not returned after 30 seconds, even with logging off and playback stopped first.
  - `LogThrottle` keeps one counter per distinct message and prints each at most once every five
    seconds with a note of what it held back. On that same channel: **2,120 messages in, 38 printed
    — 98.2% suppressed**, and every *kind* of error still shown. Digits are masked when forming the
    key, because the worst offender is `stream: Failed to open …/465675009.m4s`, one textually
    unique message per segment; masking took the tracked set from 109 entries to 9.
  - `mpvloader.shutdown()` silences the log at source, detaches the event callback, terminates on a
    throwaway thread and stops waiting after 1.5 s. A healthy stream terminates in 0.06 s, so the
    budget is ample; a stuck one now closes the window in 1.5 s instead of never. Covered by tests
    using a player whose `terminate()` blocks.
  - Also guards `_diagnose_stream` so a repeatedly failing URL cannot accumulate worker threads,
    each holding an 8-second read timeout.
- **A live DASH manifest is no longer reported as a dead channel.** `describe_response` classified
  `application/dash+xml` as "no explanation", so a `.mpd` that mpv could not play produced a banner
  saying nothing useful. It now names the case, because the case is misleading.
  - Found on BBC One Northern Ireland (`vs-cmaf-pushb-uk-live…/pc_hd_abr_v2.mpd`), where mpv logged
    100 consecutive fragment 404s and gave up. **The stream was fine.** The manifest returned 200;
    fetching the live-edge segment computed from its own `availabilityStartTime` and
    `duration/timescale` returned 46 KB of real audio, as did the ten before it; the segment mpv
    asked for was ~62 ahead of the live edge — about four minutes into the future — and 404ed, as
    did every other future segment. The machine clock agreed with the origin's `Date` header to
    0.4 s and with the manifest's own `UTCTiming` source (`time.akamai.com`) to 0.6 s, so this is
    not clock drift: mpv's DASH demuxer overshoots the live edge on this manifest.
  - **Nor is it geo-blocking**, despite iptv-org tagging the channel `[Geo-blocked]`. The channel's
    HLS URL plays from here: master → variant with 1,875 segments listed, last segment 283 KB of
    video.
  - The message says the address is good and points at HLS, where segments are listed rather than
    calculated. Verified that `vs-cmaf-pushb` → `vs-hls-pushb` and `.mpd` → `.m3u8` works for BBC's
    `pc_hd_abr_v2` and `iptv_hd_abr_v1` profiles (5 of 5 sampled) but not `hevc_*`, which is
    DASH-only (0 of 3). No URL is rewritten automatically — that would be guessing on one
    broadcaster's scheme.
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
    picker's source filter. **Suite is now 244 passing, 2 xfailed.**
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

- **The sidebar stylesheet painted over per-row colours.** `QListWidget#Sidebar::item` set
  `color`, and a stylesheet colour beats `QListWidgetItem.setForeground()` — so the channel check
  computed its dimming correctly and then had it overwritten. Found by looking at a screenshot:
  the unit test passed throughout, because it read the item's foreground data rather than what Qt
  actually paints. Normal rows now take their colour from the widget palette, which `ChannelList`
  already sets to the same value, and a test asserts the rule carries no `color` so this cannot
  come back.

- **Wide logos were clipped on both edges in the Movies and Series poster grid**
  (`winnotix/ui/pages.py`, `winnotix/ui/logos.py`). `POSTER_SIZE` was `QSize(200, 200)` in
  `logos.py` while the tile that has to display it is 180 wide with 8px margins in `pages.py` —
  164 usable. A `QLabel` clips a pixmap wider than itself instead of shrinking it, and clips it
  centred, so every wide logo lost 18px off each end: "Anger Management Channel" arrived with both
  ends missing and "Designated Survivor" rendered as "ESIGNAT / URVIVO".
  - **The two constants living in different modules is the actual defect**, so the fix is to derive
    one from the other — `POSTER_IMAGE_SIZE` is now the tile width less the margins, beside the
    tile geometry it belongs to, and `logos.py` keeps only `TV_LOGO_SIZE`. The regression test
    asserts the relationship rather than the numbers, so changing the tile size cannot
    reintroduce this.
  - The image label is also given an explicit width now rather than only a fixed height, so what it
    can show is stated rather than inferred from the layout.
  - Pre-existing, and not specific to genre routing: `VodPage` is Xtream's VOD grid too. Routing is
    what made it reachable for an M3U provider, which is how it was noticed. Verified against the
    live iptv-org Series page: 46 posters, none exceeding its label in either dimension.

- **The Pluto TV blocklist missed every entry in the larger of the two bundled catalogues**
  (`resources/blocklist.json`). The existing rule matches `host_suffix: ".pluto.tv"`, which is
  how Free-TV links the stitcher — but iptv-org links through a redirector, `jmp2.uk`, and a host
  rule sees the URL as written rather than where it lands. So the rule matched none of them.
  - **2,342 of the 14,307 entries** in `index.country.m3u` are this shape — 16% of the playlist,
    listed as ordinary channels and playing a takedown slate. A random sample of 60 resolved 59 to
    `stitcher-ipv4.pluto.tv` and one to an HTTP error, none anywhere else, so the redirector is
    Pluto's alone in this playlist and can be blocked by host.
  - **Blocking the redirector rather than resolving it** is the whole point. Following 2,342
    redirects at load time to discover what the URLs already imply would cost more than the feature
    saves, and would put a network round trip in the parse path.
  - The rule is separate from `pluto-tv-takedown` rather than folded into it, so that if Pluto
    restores third-party access both can be retired together and the reason for each stays legible.
  - Found while measuring iptv-org's channel categories for the Series routing work: 503 of the 689
    channels it classifies as `series` are these, so the blocklist gap would have filled a new
    Series page with takedown slates.

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

- **A blocklist audit across both bundled catalogues found nothing new to block.** 16,351 stream
  URLs resolve to 5,185 distinct hosts. The 39 busiest were probed — one channel each, following
  redirects and one HLS variant down to real segment names, looking for the signatures filler
  streams carry: `takedown`, `slate`, `barker`, `advert`, `placeholder`, `geo-block`, `offline`
  and the like.
  - **Only `service-stitcher.clusters.pluto.tv` matched** — `advert`, `slate`, `takedown` — and it
    is already covered, along with the `jmp2.uk` redirector that fronts it. The probe re-confirmed
    that redirect independently.
  - `jmp2.uk` turns out to carry **5 Free-TV entries as well as 2,342 iptv-org ones**, so that
    rule was doing more than the commit that added it claimed.
  - `www.youtube.com` is the third-busiest host at 133 Free-TV channels. Those are live YouTube
    streams, which need yt-dlp rather than blocking, and Winnotix ships that.
  - **This is the expected outcome, not a failed search.** Filler that names its own segments can
    be found automatically and has been; filler that does not is indistinguishable from a working
    stream by construction, which is why the blocklist is a curated data file rather than a
    detector. The audit is worth repeating when a catalogue changes, so the script's approach is
    recorded here rather than the result being taken as permanent.
  - **What the probe did surface is rot, not filler:** 12 of the 39 busiest hosts failed outright
    on the sampled channel — five 403, two 404, five connection errors. A 403 can be geo-blocking
    rather than death, and one sample does not condemn a host, but it is a useful measure of how
    much of a public playlist is already gone.

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
