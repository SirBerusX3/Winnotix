"""Main window: navigation, playback and provider management.

Mirrors upstream's MainWindow. In particular it keeps upstream's navigation
model rather than inventing one: there is no page stack, just a single
`back_page` that each page sets as it is entered (hypnotix.py:navigate_to).
Reproducing that exactly is what makes Back behave the way Hypnotix users
expect -- e.g. Back from a movie returns to the VOD grid, not to wherever you
happened to come from.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
    QStackedWidget,
)

from .. import __version__
from ..core import epg, genres, health, mpvloader, ytdlp
from ..core.filters import Blocklist, FilterResult
from ..core.genres import GenreIndex
from ..core.common import (
    MOVIES_GROUP,
    SERIES_GROUP,
    TV_GROUP,
    Channel,
    Manager,
    Provider,
    Serie,
    async_function,
    idle_function,
)
from ..core.settings import DEFAULTS, SettingsShim
from ..core import mpvlog, paths, streamcheck, xtream_loader
from . import pages as P
from .logos import LogoCache
from .theme import current_palette, stylesheet
from .widgets import HeaderBar, StatusBar

mpv = mpvloader.load_mpv()

APP_NAME = "Winnotix"

# MpvEventEndFile.ERROR -- mpv gave up opening or decoding the file.
END_FILE_ERROR = 4

# How long to wait for mpv to stop before closing the window regardless.
MPV_SHUTDOWN_TIMEOUT = mpvloader.SHUTDOWN_TIMEOUT

LANDING = "landing_page"
CATEGORIES = "categories_page"
CHANNELS = "channels_page"
VOD = "vod_page"
EPISODES = "episodes_page"
PREFERENCES = "preferences_page"
PROVIDERS = "providers_page"
ADD = "add_page"
DELETE = "delete_page"
RESET = "reset_page"
NEW_CHANNEL = "new_channel_page"
CATALOGUE = "catalogue_page"
SPINNER = "spinner_page"


class MainWindow(QMainWindow):
    provider_loaded = Signal(object, bool, str, object)
    series_loaded = Signal(object, bool, str)
    playback_failed = Signal(object, str)
    stream_diagnosed = Signal(object, str)
    guides_loaded = Signal(str, object)   # country code, list[Guide]
    check_progress = Signal(int, int)
    check_finished = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1200, 720)
        self.setMinimumSize(880, 560)

        self.palette_ = current_palette()
        self.setStyleSheet(stylesheet(self.palette_))

        self.settings = SettingsShim()
        self.manager = Manager(self.settings)
        # Before anything constructs mpv: this decides which yt-dlp is on PATH,
        # and mpv's ytdl_hook resolves the binary by name from there.
        ytdlp.apply_preference(self.settings.get_boolean("use-local-ytdlp"))

        self.logo_cache = LogoCache(self.settings, self)
        # Versions before the region-block fix cached "not available in your
        # region" images as though they were logos, and a cached file is never
        # re-fetched. Clear them once, in the background.
        self.logo_cache.purge_cached_refusals()
        self.blocklist = Blocklist.load()
        self.genres = GenreIndex.load()
        self.epg_store = epg.EpgStore(
            user_agent=self.settings.get_string("user-agent") or "winnotix")
        self.epg_urls: list[str] = []       # guides this provider declares
        self.epg_guides: list = []          # parsed guides for the open country
        self.epg_country: str | None = None
        self.health = health.HealthCache().load()
        self.checking = False

        # State, mirroring upstream's MainWindow attributes.
        self.providers: list[Provider] = []
        self.active_provider: Provider | None = None
        self.active_group = None
        self.active_channel = None
        self.active_serie = None
        self.content_type = TV_GROUP
        self.back_page = LANDING
        self.favorite_data: list[str] = []
        self.edit_provider: Provider | None = None
        self.pending_delete: Provider | None = None
        self.page_is_loading = False
        # One authenticated Xtream session per provider name, kept because a
        # series' episodes are fetched lazily, long after the provider loaded.
        self.xtream_sessions: dict[str, xtream_loader.XtreamSession] = {}
        self.pending_serie = None
        self.mpv = None
        self.volume = 100
        self._is_fullscreen = False
        self._mpv_log = mpvlog.LogThrottle()
        self._diagnosing: set[str] = set()

        self._build_ui()
        self._build_shortcuts()
        self._load_favorites()
        self._load_providers_from_settings()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.header = HeaderBar(self.palette_)
        self.header.back_clicked.connect(self.on_go_back)
        self.header.search_toggled.connect(self._on_search_toggled)
        self.header.search_changed.connect(self._on_search_changed)
        self.header.fullscreen_clicked.connect(self.toggle_fullscreen)

        self.status = StatusBar(self.palette_)
        self.status.show_clicked.connect(lambda: self.navigate_to(CHANNELS))
        self.status.pause_clicked.connect(self.toggle_pause)
        self.status.stop_clicked.connect(self.stop_playback)

        self.stack = QStackedWidget()
        self.pages: dict[str, QWidget] = {}

        self.landing = P.LandingPage(self.palette_)
        self.landing.tv_clicked.connect(lambda: self.show_groups(TV_GROUP))
        self.landing.movies_clicked.connect(lambda: self.show_groups(MOVIES_GROUP))
        self.landing.series_clicked.connect(lambda: self.show_groups(SERIES_GROUP))
        self.landing.favorites_clicked.connect(self.show_favorites)
        self.landing.preferences_clicked.connect(lambda: self.navigate_to(PREFERENCES))
        self.landing.providers_clicked.connect(self.show_providers)
        self.landing.new_channel_clicked.connect(self._start_new_channel)
        self._add_page(LANDING, self.landing)

        self.categories = P.CategoriesPage()
        self.categories.category_clicked.connect(self.on_category_clicked)
        self._add_page(CATEGORIES, self.categories)

        self.channels = P.ChannelsPage(self.palette_, self.logo_cache)
        self.channels.channel_activated.connect(self.on_channel_activated)
        self.channels.favorite_toggled.connect(self.on_favorite_toggled)
        self.channels.video.wid_ready.connect(self._on_wid_ready)
        self._add_page(CHANNELS, self.channels)

        self.vod = P.VodPage(self.logo_cache)
        self.vod.item_clicked.connect(self.on_vod_item_clicked)
        self._add_page(VOD, self.vod)

        self.episodes = P.EpisodesPage()
        self.episodes.episode_clicked.connect(self.on_channel_activated)
        self._add_page(EPISODES, self.episodes)

        self.preferences = P.PreferencesPage(self.settings)
        self.preferences.setting_changed.connect(self._on_setting_changed)
        self.preferences.bool_setting_changed.connect(self._on_bool_setting_changed)
        self.preferences.ytdlp_update_clicked.connect(self.download_ytdlp)
        self._add_page(PREFERENCES, self.preferences)

        self.providers_page = P.ProvidersPage(self.palette_)
        self.providers_page.provider_activated.connect(self.on_provider_activated)
        self.providers_page.provider_edit.connect(self._start_edit_provider)
        self.providers_page.provider_delete.connect(self._start_delete_provider)
        self.providers_page.add_clicked.connect(self._start_add_provider)
        self.providers_page.browse_clicked.connect(self._start_browse_catalogue)
        self.providers_page.reset_clicked.connect(lambda: self.navigate_to(RESET))
        self._add_page(PROVIDERS, self.providers_page)

        self.provider_edit_page = P.ProviderEditPage()
        self.provider_edit_page.accepted.connect(self.on_provider_saved)
        self.provider_edit_page.cancelled.connect(lambda: self.navigate_to(PROVIDERS))
        self._add_page(ADD, self.provider_edit_page)

        self.delete_page = P.ConfirmPage()
        self.delete_page.confirmed.connect(self.on_delete_confirmed)
        self.delete_page.cancelled.connect(lambda: self.navigate_to(PROVIDERS))
        self._add_page(DELETE, self.delete_page)

        self.reset_page = P.ConfirmPage()
        self.reset_page.ask("Are you sure you want to reset to the default providers?")
        self.reset_page.confirmed.connect(self.on_reset_confirmed)
        self.reset_page.cancelled.connect(lambda: self.navigate_to(PROVIDERS))
        self._add_page(RESET, self.reset_page)

        self.new_channel_page = P.NewChannelPage()
        self.new_channel_page.accepted.connect(self.on_new_channel_saved)
        self.new_channel_page.cancelled.connect(lambda: self.navigate_to(LANDING))
        self._add_page(NEW_CHANNEL, self.new_channel_page)

        self.catalogue_page = P.CataloguePage()
        self.catalogue_page.entry_chosen.connect(self.on_catalogue_entry_chosen)
        self.catalogue_page.cancelled.connect(self.show_providers)
        self._add_page(CATALOGUE, self.catalogue_page)

        self.spinner = P.SpinnerPage()
        self._add_page(SPINNER, self.spinner)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.status)
        self.setCentralWidget(central)

        self.reload_action = self.header.add_menu_action(
            "Reload Provider", "refresh", "Ctrl+R", self.reload_provider)
        self.header.add_menu_action("Keyboard Shortcuts", "keyboard", "Ctrl+K",
                                    self.open_keyboard_shortcuts)
        self.info_action = self.header.add_menu_action("Stream Information", "info",
                                                       "F2", self.open_stream_info)
        self.info_action.setEnabled(False)
        self.check_action = self.header.add_menu_action(
            "Check Channels", "refresh", "Ctrl+T", self.check_channels)
        self.header.menu.addSeparator()
        self.header.add_menu_action("About", "info", "F1", self.open_about)
        self.header.add_menu_action("Quit", "exit", "Ctrl+Q", self.close)

        self.provider_loaded.connect(self._on_provider_loaded)
        self.guides_loaded.connect(self._on_guides_loaded)
        self.check_progress.connect(self._on_check_progress)
        self.check_finished.connect(self._on_check_finished)
        self.series_loaded.connect(self._on_series_loaded)
        self.playback_failed.connect(self._on_playback_failed)
        self.stream_diagnosed.connect(self._on_stream_diagnosed)

    def _add_page(self, name: str, widget: QWidget) -> None:
        self.pages[name] = widget
        self.stack.addWidget(widget)

    def _build_shortcuts(self) -> None:
        for keys, handler in (
            ("Ctrl+F", lambda: self.header.search_button.toggle()),
            ("F11", self.toggle_fullscreen),
            ("Escape", self._on_escape),
            ("Ctrl+W", self.close),
            ("Space", self.toggle_pause),
            ("Backspace", self.on_go_back),
        ):
            QShortcut(QKeySequence(keys), self, activated=handler)

    # ------------------------------------------------------------------
    # Navigation — upstream's back_page model
    # ------------------------------------------------------------------

    def navigate_to(self, page: str, name: str = "", favorites: bool = False) -> None:
        self.stack.setCurrentWidget(self.pages[page])
        provider = self.active_provider
        self.back_page = LANDING
        self.header.back_button.show()
        self.header.search_button.setVisible(page == CHANNELS)
        self.header.fullscreen_button.hide()

        if page == LANDING:
            self.header.set_titles(APP_NAME, "Watch TV")
            self.landing.update_provider(provider)
            self.header.back_button.hide()
        elif page == CATEGORIES:
            self.header.set_titles(provider.name if provider else APP_NAME,
                                   self._content_label())
        elif page == CHANNELS:
            self.header.fullscreen_button.show()
            self.status.set_playing(None)
            if favorites:
                self.header.set_titles(APP_NAME, "Favourites")
            elif provider is not None:
                self.header.set_titles(provider.name, self._channels_subtitle())
                if self.content_type == TV_GROUP and self.active_group is not None:
                    self.back_page = CATEGORIES
                elif self.content_type == MOVIES_GROUP:
                    self.back_page = VOD
                elif self.content_type == SERIES_GROUP:
                    self.back_page = EPISODES
        elif page == VOD:
            self.header.set_titles(provider.name if provider else APP_NAME,
                                   self._vod_subtitle())
            if self.active_group is not None:
                self.back_page = CATEGORIES
        elif page == EPISODES:
            self.back_page = VOD
            self.header.set_titles(provider.name if provider else APP_NAME,
                                   self.active_serie.name if self.active_serie else "")
        elif page == NEW_CHANNEL:
            self.header.set_titles(APP_NAME, "New Channel")
        elif page == PREFERENCES:
            self.header.set_titles(APP_NAME, "Preferences")
            self._refresh_ytdlp_version()
        elif page == PROVIDERS:
            self.header.set_titles(APP_NAME, "Providers")
        elif page == ADD:
            self.back_page = PROVIDERS
            subtitle = f"Edit {name}" if name else "Add a new provider"
            self.header.set_titles(APP_NAME, subtitle)
        elif page in (DELETE, RESET):
            self.back_page = PROVIDERS
            self.header.set_titles(APP_NAME, "Providers")
        elif page == CATALOGUE:
            self.back_page = PROVIDERS
            self.header.set_titles(APP_NAME, "Country playlists")
        elif page == SPINNER:
            self.header.set_titles(APP_NAME, "Loading")
            self.header.back_button.hide()

    def _content_label(self) -> str:
        return {TV_GROUP: "TV Channels",
                MOVIES_GROUP: "Movies",
                SERIES_GROUP: "Series"}[self.content_type]

    def _channels_subtitle(self) -> str:
        if self.content_type == TV_GROUP:
            if self.active_group is None:
                return "TV Channels"
            return f"TV Channels > {self.active_group.name}"
        return self.active_channel.name if self.active_channel else ""

    def _vod_subtitle(self) -> str:
        label = self._content_label()
        if self.active_group is None:
            return label
        return f"{label} > {self.active_group.name}"

    def on_go_back(self) -> None:
        if self._is_fullscreen:
            self.toggle_fullscreen()
            return
        target = self.back_page
        self.navigate_to(target)
        if self.active_channel is not None and target != CHANNELS:
            self.status.set_playing(self.active_channel.name)
        if target == CATEGORIES and self.active_provider is not None:
            self.categories.show_groups(self.active_provider, self.content_type)

    def _on_escape(self) -> None:
        if self._is_fullscreen:
            self.toggle_fullscreen()
        elif self.header.search_button.isChecked():
            self.header.search_button.setChecked(False)

    # ------------------------------------------------------------------
    # Providers
    # ------------------------------------------------------------------

    def _load_providers_from_settings(self) -> None:
        self.providers = []
        for info in self.settings.get_strv("providers"):
            try:
                self.providers.append(Provider(name=None, provider_info=info))
            except ValueError:
                print(f"[winnotix] skipping malformed provider entry: {info!r}")

        active_name = self.settings.get_string("active-provider")
        chosen = next((p for p in self.providers if p.name == active_name), None)
        if chosen is None and self.providers:
            chosen = self.providers[0]

        if chosen is None:
            self.navigate_to(LANDING)
            self.status.set_status("No providers configured. Add one to get started.")
            return
        self.load_provider(chosen)

    def reload_provider(self) -> None:
        """Re-fetch the active provider, bypassing its cache.

        Upstream has no manual reload -- it re-downloads on a timer instead,
        every 5 minutes for M3U and every 2 hours for Xtream (hypnotix.py:150,
        1564). Reloading a large playlist unprompted is exactly the stall that
        the lazy logo loading was introduced to avoid, so this is on demand.
        """
        if self.active_provider is None:
            self.status.set_status("No provider to reload.")
            return
        self.load_provider(self.active_provider, refresh=True)

    def load_provider(self, provider: Provider, refresh: bool = False) -> None:
        self.active_provider = provider
        self.active_group = None
        self.navigate_to(SPINNER)
        self.spinner.set_message(f"Loading {provider.name}…",
                                 "Downloading and parsing the playlist.")
        self.status.set_status(f"Loading {provider.name}…")
        self._fetch_provider(provider, refresh)

    @async_function
    def _fetch_provider(self, provider: Provider, refresh: bool) -> None:
        """Worker thread: download and parse. Must not touch widgets."""
        try:
            if provider.type_id == P.PROVIDER_TYPE_XTREAM:
                self._fetch_xtream(provider, refresh)
                return
            if not self.manager.get_playlist(provider, refresh=refresh):
                self.provider_loaded.emit(provider, False,
                                          "Could not download the playlist.",
                                          FilterResult())
                return
            if not self.manager.check_playlist(provider):
                self.provider_loaded.emit(provider, False,
                                          "That URL did not return a valid M3U playlist.",
                                          FilterResult())
                return
            provider.groups.clear()
            provider.channels.clear()
            provider.movies.clear()
            provider.series.clear()
            self.manager.load_channels(provider)
            filtered = FilterResult()
            if self.settings.get_boolean("hide-unplayable"):
                filtered = self.blocklist.apply(provider)
            # After the blocklist, never before: most of what iptv-org
            # classifies as series is Pluto TV, which the blocklist removes.
            if self.settings.get_boolean("route-by-genre"):
                self.genres.route(provider)
        except Exception as exc:
            self.provider_loaded.emit(provider, False, str(exc), FilterResult())
            return
        self.provider_loaded.emit(provider, True, "", filtered)

    def _fetch_xtream(self, provider: Provider, refresh: bool) -> None:
        """Worker thread: authenticate and load an Xtream provider.

        Upstream does this inline in its reload loop with a wait cursor
        (hypnotix.py:1533-1573), which blocks the GUI for the whole load; the
        awkward parts of that integration live in core/xtream_loader.py.
        """
        try:
            session = xtream_loader.connect(
                provider,
                user_agent=self.settings.get_string("user-agent"),
                cache_path=str(paths.PROVIDERS_PATH),
                hide_adult_content=self.settings.get_boolean("hide-adult-content"),
            )
            result = xtream_loader.load(provider, session, refresh=refresh)
        except xtream_loader.XtreamError as exc:
            self.provider_loaded.emit(provider, False, str(exc), FilterResult())
            return

        self.xtream_sessions[provider.name] = session
        filtered = FilterResult()
        if self.settings.get_boolean("hide-unplayable"):
            filtered = self.blocklist.apply(provider)

        note = " — ".join(part for part in (result.account, result.summary()) if part)
        self.provider_loaded.emit(provider, True, note, filtered)

    def _on_provider_loaded(self, provider: Provider, ok: bool, message: str,
                            filtered: FilterResult) -> None:
        if provider is not self.active_provider:
            return  # a different provider was selected while this one loaded
        if not ok:
            self.navigate_to(LANDING)
            self.status.set_status(f"{provider.name}: {message}")
            return
        self.settings.set_string("active-provider", provider.name)
        self.epg_urls = epg.guide_urls(provider.path, provider)
        self.epg_guides = []
        self.epg_country = None
        self.navigate_to(LANDING)
        summary = (
            f"{provider.name}: {len(provider.channels)} channels, "
            f"{len(provider.movies)} movies, {genres.series_total(provider)} series"
        )
        if filtered.removed:
            summary += f" — {filtered.summary()}"
        if message:
            summary += f" — {message}"
        self.status.set_status(summary)

    def show_providers(self) -> None:
        self.providers_page.show_providers(
            self.providers, self.active_provider.name if self.active_provider else ""
        )
        self.navigate_to(PROVIDERS)

    def on_provider_activated(self, provider: Provider) -> None:
        self.load_provider(provider)

    def _start_browse_catalogue(self) -> None:
        self.catalogue_page.reset()
        self.navigate_to(CATALOGUE)

    def on_catalogue_entry_chosen(self, entry) -> None:
        """Adding a catalogue playlist just creates an ordinary provider."""
        existing = next(
            (p for p in self.providers if p.url == entry.url), None
        )
        if existing is not None:
            self.status.set_status(f"{existing.name} is already in your providers.")
            self.load_provider(existing)
            return

        info = ":::".join([entry.provider_name, P.PROVIDER_TYPE_URL, entry.url,
                           "", "", ""])
        provider = Provider(name=None, provider_info=info)
        self.providers.append(provider)
        self._save_providers()
        self.load_provider(provider, refresh=True)

    def _start_add_provider(self) -> None:
        self.edit_provider = None
        self.provider_edit_page.load(None)
        self.navigate_to(ADD)

    def _start_edit_provider(self, provider: Provider) -> None:
        self.edit_provider = provider
        self.provider_edit_page.load(provider)
        self.navigate_to(ADD, name=provider.name)

    def _start_delete_provider(self, provider: Provider) -> None:
        self.pending_delete = provider
        self.delete_page.ask(
            f"Are you sure you want to delete the provider “{provider.name}”?"
        )
        self.navigate_to(DELETE)

    def on_provider_saved(self, data: dict) -> None:
        if not data["name"] or not data["url"]:
            self.status.set_status("A provider needs both a name and a URL or path.")
            return
        info = ":::".join([data["name"], data["type_id"], data["url"],
                           data["username"], data["password"], data["epg"]])
        new_provider = Provider(name=None, provider_info=info)

        if self.edit_provider is not None:
            index = self.providers.index(self.edit_provider)
            # Credentials or the server may have changed, so the authenticated
            # session cached under the old name is no longer trustworthy.
            self.xtream_sessions.pop(self.edit_provider.name, None)
            self.providers[index] = new_provider
        else:
            self.providers.append(new_provider)
        self._save_providers()
        self.edit_provider = None
        self.load_provider(new_provider, refresh=True)

    def on_delete_confirmed(self) -> None:
        if self.pending_delete is not None and self.pending_delete in self.providers:
            self.providers.remove(self.pending_delete)
            self.xtream_sessions.pop(self.pending_delete.name, None)
            self._save_providers()
            if self.active_provider is self.pending_delete:
                self.active_provider = None
        self.pending_delete = None
        self.show_providers()

    def on_reset_confirmed(self) -> None:
        self.xtream_sessions.clear()
        self.settings.reset("providers")
        self._load_providers_from_settings()
        self.show_providers()

    def _save_providers(self) -> None:
        self.settings.set_strv("providers", [p.get_info() for p in self.providers])

    # ------------------------------------------------------------------
    # Browsing
    # ------------------------------------------------------------------

    def show_groups(self, content_type: int) -> None:
        if self.active_provider is None:
            return
        self.content_type = content_type
        self.active_group = None
        self.navigate_to(CATEGORIES)
        if not self.categories.show_groups(self.active_provider, content_type):
            # No groups of this type: go straight to the full list, as upstream does.
            self.on_category_clicked(None)

    def on_category_clicked(self, group) -> None:
        self.active_group = group
        provider = self.active_provider
        if self.content_type == TV_GROUP:
            channels = group.channels if group else provider.channels
            self.show_channels(channels)
        elif self.content_type == MOVIES_GROUP:
            movies = group.channels if group else provider.movies
            self.vod.show_items(movies)
            self.navigate_to(VOD)
        else:
            if group is not None:
                # A routed group holds Channels; a real one holds Serie objects.
                series = group.series or group.channels
            else:
                series = provider.series or genres.series_channels(provider)
            self.vod.show_items(series)
            self.navigate_to(VOD)

    def show_channels(self, channels, favorites: bool = False) -> None:
        self.content_type = TV_GROUP
        self.channels.set_sidebar_visible(True)
        self.channels.channel_list.set_channels(channels)
        self.navigate_to(CHANNELS, favorites=favorites)
        self.status.set_status(f"{self.channels.channel_list.count()} channels")
        self._maybe_load_guides()

    # -- channel health ------------------------------------------------

    def check_channels(self) -> None:
        """Ask every channel in the open list whether it still answers.

        Scoped to what is on screen rather than the whole provider: a country
        is tens or hundreds of requests, a full catalogue is 11,000, and the
        second is not a thing to fire at other people's servers from a menu.
        """
        if self.checking:
            self.checking = False       # a second press stops the run
            self.status.set_status("Stopping the check…")
            return
        channels = self.channels.channel_list.channels()
        if not channels:
            self.status.set_status("Open a channel list first.")
            return
        self.checking = True
        self.check_action.setText("Stop Checking")
        self.status.set_status(f"Checking {len(channels)} channels…")
        self._run_check(channels)

    @async_function
    def _run_check(self, channels) -> None:
        """Worker thread: many small requests. Must not touch widgets."""
        try:
            result = health.sweep(
                channels, self.health,
                user_agent=self.settings.get_string("user-agent"),
                referer=self.settings.get_string("http-referer"),
                progress=lambda done, total: self.check_progress.emit(done, total),
                should_stop=lambda: not self.checking,
            )
        except Exception as exc:        # one bad host must not kill the thread
            print(f"[winnotix] channel check failed: {exc}")
            result = health.Sweep()
        self.check_finished.emit(result)

    def _on_check_progress(self, done: int, total: int) -> None:
        self.status.set_status(f"Checking channels… {done} of {total}")

    def _on_check_finished(self, result) -> None:
        self.checking = False
        self.check_action.setText("Check Channels")
        marked = self.channels.channel_list.apply_health(
            lambda channel: self.health.get(channel.url))
        summary = result.summary() or "nothing to check"
        note = f" — {marked} dimmed" if marked else ""
        self.status.set_status(f"Checked: {summary}{note}")

    # -- programme guide -----------------------------------------------

    def _maybe_load_guides(self) -> None:
        """Fetch the guide for the country now on screen, if there is one.

        Per country, and only on demand: the combined guide is 191 MB gzipped
        while one country is 2.6 MB, so fetching everything up front would cost
        far more than it could ever show.
        """
        if not self.settings.get_boolean("show-epg") or not self.epg_urls:
            return
        code = epg.country_for_group(self.active_group)
        if code is None or code == self.epg_country:
            self._apply_guides()
            return
        if not epg.urls_for_country(self.epg_urls, code):
            self.epg_country, self.epg_guides = code, []
            return
        self.epg_country = code
        self.epg_guides = []
        self._fetch_guides(code, list(self.epg_urls))

    @async_function
    def _fetch_guides(self, code: str, urls) -> None:
        """Worker thread: download and parse. Must not touch widgets."""
        try:
            guides = self.epg_store.load_for(urls, code)
        except Exception as exc:   # a bad guide must not kill the thread
            print(f"[winnotix] guide load failed for {code}: {exc}")
            guides = []
        self.guides_loaded.emit(code, guides)

    def _on_guides_loaded(self, code: str, guides) -> None:
        if code != self.epg_country:
            return          # the user moved to another country while it loaded
        self.epg_guides = guides
        self._apply_guides()

    def _apply_guides(self) -> None:
        """Put now/next on the visible rows, and on whatever is playing."""
        if not self.epg_guides:
            return
        matched = self.channels.channel_list.apply_guide(
            lambda channel: self.epg_store.now_next(self.epg_guides, channel))
        if matched:
            self.status.set_status(
                f"{self.channels.channel_list.count()} channels — "
                f"listings for {matched}")
        if self.active_channel is not None:
            self._show_playing_with_guide(self.active_channel)

    def _now_next(self, channel):
        if not self.epg_guides or not self.settings.get_boolean("show-epg"):
            return None, None
        return self.epg_store.now_next(self.epg_guides, channel)

    def _show_playing_with_guide(self, channel) -> None:
        current, _following = self._now_next(channel)
        if current is None:
            self.status.set_playing(channel.name)
            return
        self.status.set_playing(f"{channel.name} — {current.when()}  {current.title}")

    def on_vod_item_clicked(self, item) -> None:
        if self.content_type != SERIES_GROUP or not isinstance(item, Serie):
            # A genre-routed channel reaches the Series grid as a Channel: it
            # loops one show or carries a drama schedule, and has no episode
            # list to open, so it plays like any other channel.
            self.on_channel_activated(item)
            return
        self.active_serie = item
        session = self._active_xtream_session()
        if session is not None and not item.seasons:
            # Xtream does not ship seasons and episodes with the series list;
            # they are a separate request per series, so fetch on first open.
            # Upstream does it synchronously behind a wait cursor
            # (hypnotix.py:588) -- off the GUI thread here.
            self.pending_serie = item
            self.spinner.set_message(f"Loading {item.name}…", "Fetching seasons and episodes.")
            self.navigate_to(SPINNER)
            self._fetch_series(session, item)
            return
        self.episodes.show_serie(item)
        self.navigate_to(EPISODES)

    def _active_xtream_session(self):
        provider = self.active_provider
        if provider is None or provider.type_id != P.PROVIDER_TYPE_XTREAM:
            return None
        return self.xtream_sessions.get(provider.name)

    @async_function
    def _fetch_series(self, session, serie) -> None:
        """Worker thread: one get_series_info request. Must not touch widgets."""
        try:
            xtream_loader.load_series(session, serie)
        except xtream_loader.XtreamError as exc:
            self.series_loaded.emit(serie, False, str(exc))
            return
        except Exception as exc:  # a malformed payload should not kill the thread
            self.series_loaded.emit(serie, False, f"Could not read this series: {exc}")
            return
        self.series_loaded.emit(serie, True, "")

    def _on_series_loaded(self, serie, ok: bool, message: str) -> None:
        if serie is not self.pending_serie:
            return  # the user moved on while it loaded
        self.pending_serie = None
        if not ok:
            self.navigate_to(VOD)
            self.status.set_status(f"{serie.name}: {message}")
            return
        self.episodes.show_serie(serie)
        self.navigate_to(EPISODES)
        self.status.set_status(
            f"{serie.name}: {len(serie.episodes)} episodes in {len(serie.seasons)} seasons"
        )

    def show_favorites(self) -> None:
        self.content_type = TV_GROUP
        channels = []
        for line in self.favorite_data:
            try:
                info, url = line.rsplit(":::", 1)
            except ValueError:
                continue
            channel = Channel(None, info)
            channel.url = url
            channels.append(channel)
        if not channels:
            self.status.set_status("No favourites yet — star a channel while watching.")
            return
        self.show_channels(channels, favorites=True)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _on_search_toggled(self, checked: bool) -> None:
        if not checked:
            self.channels.channel_list.filter("")

    def _on_search_changed(self, text: str) -> None:
        matches = self.channels.channel_list.filter(text)
        if text:
            self.status.set_status(f"{matches} channels match “{text}”")
        else:
            self.status.set_status(f"{self.channels.channel_list.count()} channels")

    # ------------------------------------------------------------------
    # Favourites
    # ------------------------------------------------------------------

    def _load_favorites(self) -> None:
        try:
            self.favorite_data = self.manager.load_favorites()
        except FileNotFoundError:
            self.favorite_data = []
        except Exception as exc:
            print(f"[winnotix] could not read favourites: {exc}")
            self.favorite_data = []

    def _favorite_key(self, channel) -> str:
        return f"{channel.info}:::{channel.url}"

    def on_favorite_toggled(self, checked: bool) -> None:
        if self.page_is_loading or self.active_channel is None:
            return
        key = self._favorite_key(self.active_channel)
        if checked and key not in self.favorite_data:
            self.favorite_data.append(key)
        elif not checked and key in self.favorite_data:
            self.favorite_data.remove(key)
        try:
            self.manager.save_favorites(self.favorite_data)
        except Exception as exc:
            self.status.set_status(f"Could not save favourites: {exc}")

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    def _on_wid_ready(self, wid: int) -> None:
        options = {}
        try:
            mpv_options = self.settings.get_string("mpv-options")
            if "=" in mpv_options:
                for pair in mpv_options.split():
                    key, value = pair.split("=", 1)
                    options[key] = value
        except Exception as exc:
            print(f"[winnotix] could not parse mpv-options: {exc}")

        options["user_agent"] = self.settings.get_string("user-agent")
        options["referrer"] = self.settings.get_string("http-referer")
        osc = options.pop("osc", "yes") != "no"

        self.mpv = mpv.MPV(
            **options,
            wid=str(wid),
            osc=osc,
            input_default_bindings=True,
            input_vo_keyboard=True,
            ytdl=self._ytdlp_available(),
            log_handler=self._on_mpv_log,
            loglevel="warn",
        )
        self.mpv.volume = self.volume
        self.mpv.observe_property("core-idle", self._on_core_idle)
        self.mpv.register_event_callback(self._on_mpv_event)

    def _on_mpv_log(self, level: str, prefix: str, text: str) -> None:
        """mpv's event thread. Must stay cheap -- see core/mpvlog.py."""
        line = self._mpv_log.line(level, prefix, text)
        if line is not None:
            print(line)

    def _on_core_idle(self, _name, _value) -> None:
        pass  # observed so mpv keeps the property live for the info dialog

    def _on_mpv_event(self, event) -> None:
        """mpv's event thread. Emits a signal; must not touch widgets.

        Upstream never notices a failed open at all -- mpv logs "Failed to open"
        and the GUI keeps showing the channel as though it were playing. Public
        playlists are full of dead entries, so the failure has to be visible.
        """
        try:
            data = event.data
            if data is None or getattr(data, "reason", None) != END_FILE_ERROR:
                return
            reason = mpv.ErrorCode.human_readable(data.error)
        except Exception:
            return
        self.playback_failed.emit(self.active_channel, reason)

    def _on_playback_failed(self, channel, reason: str) -> None:
        if channel is None or channel is not self.active_channel:
            return  # a stale failure from a channel we have already left
        self.status.set_status(f"Could not play {channel.name}: {reason}")
        self.channels.show_message(f"{channel.name} would not play — {reason}. Checking why…")
        # One probe per URL at a time: a stream that fails repeatedly should not
        # accumulate worker threads, each holding an 8-second read timeout.
        if channel.url not in self._diagnosing:
            self._diagnosing.add(channel.url)
            self._diagnose_stream(channel)

    @async_function
    def _diagnose_stream(self, channel) -> None:
        """Worker thread: ask the URL itself what went wrong. One request."""
        detail = streamcheck.diagnose(
            channel.url,
            user_agent=self.settings.get_string("user-agent"),
            referer=self.settings.get_string("http-referer"),
        )
        self.stream_diagnosed.emit(channel, detail)

    def _on_stream_diagnosed(self, channel, detail: str) -> None:
        self._diagnosing.discard(channel.url)
        if channel is not self.active_channel or not detail:
            return
        self.status.set_status(f"{channel.name}: {detail}")
        self.channels.show_message(f"{channel.name} would not play. {detail}")

    def on_channel_activated(self, channel) -> None:
        if channel is None or not channel.url or self.mpv is None:
            return
        self.page_is_loading = True
        self.active_channel = channel
        self.channels.set_channel(channel)
        self.channels.set_favorite(self._favorite_key(channel) in self.favorite_data)
        self.page_is_loading = False

        if self.content_type != TV_GROUP:
            self.channels.set_sidebar_visible(False)
            self.navigate_to(CHANNELS)

        self.info_action.setEnabled(True)
        self.channels.clear_message()
        self.status.set_status(f"Playing {channel.name}")
        self._show_playing_with_guide(channel)
        try:
            self.mpv.play(channel.url)
        except Exception as exc:
            self.status.set_status(f"Could not play {channel.name}: {exc}")
            self.channels.show_message(f"{channel.name} would not play — {exc}")

    def toggle_pause(self) -> None:
        if self.mpv is None or self.active_channel is None:
            return
        try:
            self.mpv.pause = not self.mpv.pause
            self.status.set_paused(self.mpv.pause)
        except Exception:
            pass

    def stop_playback(self) -> None:
        if self.mpv is not None:
            try:
                self.mpv.stop()
            except Exception:
                pass
        self.active_channel = None
        self.info_action.setEnabled(False)
        self.status.set_playing(None)
        self.status.set_status("Stopped")

    def toggle_fullscreen(self) -> None:
        self._is_fullscreen = not self._is_fullscreen
        if self._is_fullscreen:
            self.navigate_to(CHANNELS)
            self.header.hide()
            self.status.hide()
            self.channels.set_sidebar_visible(False)
            self.channels.info_bar.hide()
            self.showFullScreen()
        else:
            self.header.show()
            self.status.show()
            self.channels.info_bar.show()
            self.channels.set_sidebar_visible(self.content_type == TV_GROUP)
            self.showNormal()

    # ------------------------------------------------------------------
    # Menu actions
    # ------------------------------------------------------------------

    def _start_new_channel(self) -> None:
        self.new_channel_page.clear()
        self.navigate_to(NEW_CHANNEL)

    def on_new_channel_saved(self, data: dict) -> None:
        if not data["name"] or not data["url"]:
            self.status.set_status("A channel needs both a name and a URL.")
            return
        info = f'#EXTINF:-1 tvg-name="{data["name"]}" tvg-logo="{data["logo"]}",{data["name"]}'
        self.favorite_data.append(f'{info}:::{data["url"]}')
        try:
            self.manager.save_favorites(self.favorite_data)
            self.status.set_status(f'Added “{data["name"]}” to favourites.')
        except Exception as exc:
            self.status.set_status(f"Could not save favourites: {exc}")
        self.navigate_to(LANDING)

    def _on_setting_changed(self, key: str, value: str) -> None:
        self.settings.set_string(key, value)
        if key == "mpv-options":
            self.status.set_status("MPV options will apply the next time Winnotix starts.")

    def _on_bool_setting_changed(self, key: str, value: bool) -> None:
        self.settings.set_boolean(key, value)
        if key == "hide-adult-content" and self.active_provider is not None:
            # Only Xtream marks adult streams, and the marking is applied while
            # loading, so this is a no-op for anything else.
            if self.active_provider.type_id == P.PROVIDER_TYPE_XTREAM:
                self.status.set_status("Reloading the provider to apply the change…")
                self.load_provider(self.active_provider)
            return
        if key == "use-local-ytdlp":
            in_effect = ytdlp.apply_preference(value)
            if value and not ytdlp.local_path().is_file():
                self.status.set_status(
                    "No downloaded copy yet — use Download in Preferences."
                )
            elif in_effect is None:
                self.status.set_status("No yt-dlp found. Streams needing "
                                       "extraction will not play.")
            else:
                self.status.set_status(f"Using {in_effect}.")
            self._refresh_ytdlp_version()
            return
        if key == "proxy-blocked-logos":
            # Whether a host is reachable has just changed answer, so drop what
            # was learned under the old setting and let the visible rows ask
            # again. No reload: logos are fetched independently of the playlist.
            self.logo_cache.reset_failures()
            self.status.set_status(
                "Logos will be fetched through the proxy when a host refuses them."
                if value else
                "Logos will only be fetched from the address in the playlist."
            )
            return
        if key == "show-epg":
            self.epg_country = None
            self.epg_guides = []
            if value:
                self._maybe_load_guides()
            elif self.active_channel is not None:
                self.status.set_playing(self.active_channel.name)
            return
        if key in ("hide-unplayable", "route-by-genre") and self.active_provider is not None:
            # Filtering happens during load, so the change needs a reload to
            # take effect -- and a reload is cheap, the playlist is cached.
            self.status.set_status("Reloading the playlist to apply the change…")
            self.load_provider(self.active_provider)

    def _ytdlp_available(self) -> bool:
        return ytdlp.apply_preference(
            self.settings.get_boolean("use-local-ytdlp")) is not None

    @async_function
    def _refresh_ytdlp_version(self) -> None:
        """Both copies, off the GUI thread -- each answer is a process launch."""
        system = ytdlp.version(ytdlp.system_path())
        local = ytdlp.version(ytdlp.local_path())             if ytdlp.local_path().is_file() else None
        self._show_ytdlp_versions(system, local)

    @idle_function
    def _show_ytdlp_versions(self, system, local) -> None:
        self.preferences.set_ytdlp_versions(system, local)

    @async_function
    def download_ytdlp(self) -> None:
        """Fetch yt-dlp into the app's own cache directory.

        Upstream shells out to wget and chmod, and calls os.chdir without
        changing back -- see core/ytdlp.py. This is the Windows replacement.
        """
        self._ytdlp_busy("Downloading…")
        try:
            result = ytdlp.download(on_progress=self._ytdlp_progress)
        except ytdlp.ChecksumMismatch as exc:
            self._ytdlp_finished(None, f"Download did not verify: {exc}")
            return
        except Exception as exc:
            self._ytdlp_finished(None, f"Could not download yt-dlp: {exc}")
            return
        note = "" if result.verified else " (checksum list unavailable, not verified)"
        self._ytdlp_finished(result.path, f"yt-dlp downloaded{note}.")

    def _ytdlp_progress(self, done: int, total: int) -> None:
        """Called from the download thread, once per chunk."""
        if total:
            self._ytdlp_busy(f"Downloading… {done * 100 // total}%")
        else:
            self._ytdlp_busy(f"Downloading… {done / 1e6:.1f} MB")

    @idle_function
    def _ytdlp_busy(self, message) -> None:
        self.preferences.set_ytdlp_busy(message)

    @idle_function
    def _ytdlp_finished(self, path, message) -> None:
        self.preferences.set_ytdlp_busy(None)
        if path is not None and self.settings.get_boolean("use-local-ytdlp"):
            ytdlp.apply_preference(True)
            message += " " + self._enable_ytdl_now()
        self.status.set_status(message)
        self._refresh_ytdlp_version()

    def _enable_ytdl_now(self) -> str:
        """Turn the hook on in the running player, if mpv will take it live.

        mpv was constructed with `ytdl` off if no yt-dlp existed then. Rather
        than guess whether the option is settable at run time, set it and read
        it back.
        """
        if self.mpv is None:
            return ""
        try:
            self.mpv.ytdl = True
            if bool(self.mpv.ytdl):
                return "It is in use now."
        except Exception:
            pass
        return "It will be used the next time Winnotix starts."

    def open_keyboard_shortcuts(self) -> None:
        rows = [
            ("Ctrl+F", "Search channels"),
            ("F11", "Toggle fullscreen"),
            ("Escape", "Leave fullscreen or close search"),
            ("Backspace", "Go back"),
            ("Space", "Pause / resume"),
            ("F1", "About"),
            ("F2", "Stream information"),
            ("Ctrl+R", "Reload the current provider"),
            ("Ctrl+K", "This dialog"),
            ("Ctrl+Q", "Quit"),
        ]
        body = "\n".join(f"{keys:<12}{label}" for keys, label in rows)
        self._info_dialog("Keyboard Shortcuts", body, monospace=True)

    def open_stream_info(self) -> None:
        if self.mpv is None or self.active_channel is None:
            return
        fields = [
            ("Channel", self.active_channel.name),
            ("URL", self.active_channel.url),
        ]
        current, following = self._now_next(self.active_channel)
        if current is not None:
            fields.append(("Now", f"{current.when()}  {current.title}"))
        if following is not None:
            fields.append(("Next", f"{following.when()}  {following.title}"))
        for label, prop in (
            ("Resolution", "video-params/w"),
            ("Video codec", "video-format"),
            ("Video bitrate", "video-bitrate"),
            ("FPS", "estimated-vf-fps"),
            ("Audio codec", "audio-codec-name"),
            ("Audio bitrate", "audio-bitrate"),
            ("Hardware decoding", "hwdec-current"),
            ("Video output", "current-vo"),
        ):
            try:
                value = self.mpv._get_property(prop)
            except Exception:
                value = None
            fields.append((label, "—" if value is None else str(value)))

        try:
            width = self.mpv.width
            height = self.mpv.height
            if width and height:
                fields[2] = ("Resolution", f"{width}×{height}")
        except Exception:
            pass

        body = "\n".join(f"{label:<20}{value}" for label, value in fields)
        self._info_dialog("Stream Information", body, monospace=True)

    def open_about(self) -> None:
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<h3>{APP_NAME} {__version__}</h3>"
            "<p>An IPTV player for Windows.</p>"
            "<p>A port of <b>Hypnotix</b> by Linux Mint, licensed GPLv3. "
            "Playback by libmpv.</p>"
            "<p>Not affiliated with or endorsed by Linux Mint.</p>",
        )

    def _info_dialog(self, title: str, body: str, monospace: bool = False) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        label = QLabel(body)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if monospace:
            font = label.font()
            font.setFamily("Consolas")
            label.setFont(font)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 18, 20, 14)
        layout.addWidget(label)
        layout.addWidget(buttons)
        dialog.exec()

    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        self.logo_cache.shutdown()
        player, self.mpv = self.mpv, None
        if player is not None:
            self._shutdown_mpv(player)
        super().closeEvent(event)

    def _shutdown_mpv(self, player) -> None:
        if not mpvloader.shutdown(player, event_callback=self._on_mpv_event,
                                  timeout=MPV_SHUTDOWN_TIMEOUT):
            print("[winnotix] mpv did not shut down in time; closing anyway.")
