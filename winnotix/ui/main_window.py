"""Main window: navigation, playback and provider management.

Mirrors upstream's MainWindow. In particular it keeps upstream's navigation
model rather than inventing one: there is no page stack, just a single
`back_page` that each page sets as it is entered (hypnotix.py:navigate_to).
Reproducing that exactly is what makes Back behave the way Hypnotix users
expect -- e.g. Back from a movie returns to the VOD grid, not to wherever you
happened to come from.
"""

from __future__ import annotations

import shutil
import subprocess

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

from ..core import mpvloader
from ..core.filters import Blocklist, FilterResult
from ..core.common import (
    MOVIES_GROUP,
    SERIES_GROUP,
    TV_GROUP,
    Channel,
    Manager,
    Provider,
    async_function,
    idle_function,
)
from ..core.settings import DEFAULTS, SettingsShim
from . import pages as P
from .logos import LogoCache
from .theme import current_palette, stylesheet
from .widgets import HeaderBar, StatusBar

mpv = mpvloader.load_mpv()

APP_NAME = "Winnotix"

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

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1200, 720)
        self.setMinimumSize(880, 560)

        self.palette_ = current_palette()
        self.setStyleSheet(stylesheet(self.palette_))

        self.settings = SettingsShim()
        self.manager = Manager(self.settings)
        self.logo_cache = LogoCache(self.settings, self)
        self.blocklist = Blocklist.load()

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
        self.mpv = None
        self.volume = 100
        self._is_fullscreen = False

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

        self.header.add_menu_action("Keyboard Shortcuts", "keyboard", "Ctrl+K",
                                    self.open_keyboard_shortcuts)
        self.info_action = self.header.add_menu_action("Stream Information", "info",
                                                       "F2", self.open_stream_info)
        self.info_action.setEnabled(False)
        self.header.menu.addSeparator()
        self.header.add_menu_action("About", "info", "F1", self.open_about)
        self.header.add_menu_action("Quit", "exit", "Ctrl+Q", self.close)

        self.provider_loaded.connect(self._on_provider_loaded)

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
            self.header.set_titles(APP_NAME, "Free-TV playlists")
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
                self.provider_loaded.emit(
                    provider, False,
                    "Xtream providers are not supported yet — coming in a later release.",
                    FilterResult(),
                )
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
        except Exception as exc:
            self.provider_loaded.emit(provider, False, str(exc), FilterResult())
            return
        self.provider_loaded.emit(provider, True, "", filtered)

    def _on_provider_loaded(self, provider: Provider, ok: bool, message: str,
                            filtered: FilterResult) -> None:
        if provider is not self.active_provider:
            return  # a different provider was selected while this one loaded
        if not ok:
            self.navigate_to(LANDING)
            self.status.set_status(f"{provider.name}: {message}")
            return
        self.settings.set_string("active-provider", provider.name)
        self.navigate_to(LANDING)
        summary = (
            f"{provider.name}: {len(provider.channels)} channels, "
            f"{len(provider.movies)} movies, {len(provider.series)} series"
        )
        if filtered.removed:
            summary += f" — {filtered.summary()}"
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
            self.providers[index] = new_provider
        else:
            self.providers.append(new_provider)
        self._save_providers()
        self.edit_provider = None
        self.load_provider(new_provider, refresh=True)

    def on_delete_confirmed(self) -> None:
        if self.pending_delete is not None and self.pending_delete in self.providers:
            self.providers.remove(self.pending_delete)
            self._save_providers()
            if self.active_provider is self.pending_delete:
                self.active_provider = None
        self.pending_delete = None
        self.show_providers()

    def on_reset_confirmed(self) -> None:
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
            series = group.series if group else provider.series
            self.vod.show_items(series)
            self.navigate_to(VOD)

    def show_channels(self, channels, favorites: bool = False) -> None:
        self.content_type = TV_GROUP
        self.channels.set_sidebar_visible(True)
        self.channels.channel_list.set_channels(channels)
        self.navigate_to(CHANNELS, favorites=favorites)
        self.status.set_status(f"{self.channels.channel_list.count()} channels")

    def on_vod_item_clicked(self, item) -> None:
        if self.content_type == SERIES_GROUP:
            self.active_serie = item
            self.episodes.show_serie(item)
            self.navigate_to(EPISODES)
        else:
            self.on_channel_activated(item)

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
            ytdl=bool(shutil.which("yt-dlp")),
            log_handler=self._on_mpv_log,
            loglevel="warn",
        )
        self.mpv.volume = self.volume
        self.mpv.observe_property("core-idle", self._on_core_idle)

    @staticmethod
    def _on_mpv_log(level: str, prefix: str, text: str) -> None:
        print(f"[mpv/{level}] {prefix}: {text.strip()}")

    def _on_core_idle(self, _name, _value) -> None:
        pass  # observed so mpv keeps the property live for the info dialog

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
        self.status.set_status(f"Playing {channel.name}")
        try:
            self.mpv.play(channel.url)
        except Exception as exc:
            self.status.set_status(f"Could not play {channel.name}: {exc}")

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
        if key == "hide-unplayable" and self.active_provider is not None:
            # Filtering happens during load, so the change needs a reload to
            # take effect -- and a reload is cheap, the playlist is cached.
            self.status.set_status("Reloading the playlist to apply the change…")
            self.load_provider(self.active_provider)

    def _refresh_ytdlp_version(self) -> None:
        path = shutil.which("yt-dlp")
        if path is None:
            self.preferences.set_ytdlp_version(
                "Not installed. Streams needing extraction (e.g. YouTube) will not play."
            )
            return
        try:
            version = subprocess.run(
                [path, "--version"], capture_output=True, text=True, timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout.strip()
            self.preferences.set_ytdlp_version(f"Version {version} ({path})")
        except Exception as exc:
            self.preferences.set_ytdlp_version(f"Found at {path}, but not runnable: {exc}")

    def open_keyboard_shortcuts(self) -> None:
        rows = [
            ("Ctrl+F", "Search channels"),
            ("F11", "Toggle fullscreen"),
            ("Escape", "Leave fullscreen or close search"),
            ("Backspace", "Go back"),
            ("Space", "Pause / resume"),
            ("F1", "About"),
            ("F2", "Stream information"),
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
            f"<h3>{APP_NAME}</h3>"
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
        if self.mpv is not None:
            try:
                self.mpv.terminate()
            except Exception:
                pass
            self.mpv = None
        super().closeEvent(event)
