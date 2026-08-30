"""Phase 0 shell: channel list on the left, mpv surface on the right.

Deliberately minimal. The point of this window is to prove that libmpv embeds
into a Qt widget on Windows and that the ported backend feeds it real data --
not to resemble the finished application. Anything here is expected to be
replaced in Phase 2.

It does exercise both halves of upstream's threading model on purpose:
@async_function for the download/parse, @idle_function for every widget touch.
If the main-thread marshal in core/mainthread.py were wrong, this window would
crash rather than quietly misbehave later.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..core import mpvloader
from ..core.common import Manager, Provider, async_function, idle_function
from ..core.settings import SettingsShim
from .video_widget import VideoWidget

mpv = mpvloader.load_mpv()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Winnotix — Phase 0 spike")
        self.resize(1180, 680)

        self.settings = SettingsShim()
        self.manager = Manager(self.settings)
        self.mpv: "mpv.MPV | None" = None
        self.provider: Provider | None = None

        self.channel_list = QListWidget()
        self.channel_list.setMinimumWidth(260)
        self.channel_list.itemActivated.connect(self._on_channel_activated)
        self.channel_list.currentItemChanged.connect(
            lambda current, _previous: self._on_channel_activated(current)
        )

        self.video = VideoWidget()
        self.video.wid_ready.connect(self._on_wid_ready)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.list_header = QLabel("Loading…")
        self.list_header.setContentsMargins(8, 6, 8, 6)
        left_layout.addWidget(self.list_header)
        left_layout.addWidget(self.channel_list)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self.video)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 880])

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)
        self.setCentralWidget(container)

        self.statusBar().showMessage("Starting…")

    # -- mpv lifecycle --------------------------------------------------

    def _on_wid_ready(self, wid: int) -> None:
        """Called once the video widget has a real HWND."""
        options = {}
        try:
            mpv_options = self.settings.get_string("mpv-options")
            if "=" in mpv_options:
                for pair in mpv_options.split():
                    key, value = pair.split("=", 1)
                    options[key] = value
        except Exception as exc:  # upstream is equally forgiving here
            print(f"[winnotix] could not parse mpv-options: {exc}")

        options["user_agent"] = self.settings.get_string("user-agent")
        options["referrer"] = self.settings.get_string("http-referer")

        osc = True
        if "osc" in options:
            osc = options.pop("osc") != "no"

        self.mpv = mpv.MPV(
            **options,
            wid=str(wid),
            osc=osc,
            input_default_bindings=True,
            input_vo_keyboard=True,
            log_handler=self._on_mpv_log,
            loglevel="warn",
        )
        self.statusBar().showMessage(f"mpv {self.mpv.mpv_version} ready — HWND {wid}")
        self._load_default_provider()

    @staticmethod
    def _on_mpv_log(level: str, prefix: str, text: str) -> None:
        print(f"[mpv/{level}] {prefix}: {text.strip()}")

    # -- data loading ---------------------------------------------------

    def _load_default_provider(self) -> None:
        providers = self.settings.get_strv("providers")
        if not providers:
            self._set_status("No providers configured")
            return
        self.provider = Provider(name=None, provider_info=providers[0])
        self._set_status(f"Fetching playlist for {self.provider.name}…")
        self._fetch_provider(self.provider)

    @async_function
    def _fetch_provider(self, provider: Provider) -> None:
        """Runs on a worker thread — must not touch widgets directly."""
        try:
            if not self.manager.get_playlist(provider, refresh=False):
                self._set_status(f"Could not download the playlist for {provider.name}")
                return
            if not self.manager.check_playlist(provider):
                self._set_status(f"{provider.name} did not return a valid M3U playlist")
                return
            self.manager.load_channels(provider)
        except Exception as exc:
            self._set_status(f"Error loading {provider.name}: {exc}")
            return
        self._populate(provider)

    @idle_function
    def _populate(self, provider: Provider) -> None:
        self.channel_list.clear()
        for channel in provider.channels:
            if not channel.url:
                continue
            item = QListWidgetItem(channel.name or "Unnamed channel")
            item.setData(Qt.ItemDataRole.UserRole, channel)
            item.setToolTip(channel.url)
            self.channel_list.addItem(item)

        self.list_header.setText(
            f"{provider.name} — {self.channel_list.count()} channels, {len(provider.groups)} groups"
        )
        self.statusBar().showMessage(
            f"Loaded {self.channel_list.count()} channels "
            f"({len(provider.movies)} movies, {len(provider.series)} series). "
            "Select a channel to play."
        )

    @idle_function
    def _set_status(self, message: str) -> None:
        self.statusBar().showMessage(message)

    # -- playback -------------------------------------------------------

    def _on_channel_activated(self, item: QListWidgetItem | None) -> None:
        if item is None or self.mpv is None:
            return
        channel = item.data(Qt.ItemDataRole.UserRole)
        if channel is None or not channel.url:
            return
        self.statusBar().showMessage(f"Playing {channel.name}…")
        self.mpv.play(channel.url)

    def closeEvent(self, event) -> None:
        if self.mpv is not None:
            self.mpv.terminate()
            self.mpv = None
        super().closeEvent(event)
