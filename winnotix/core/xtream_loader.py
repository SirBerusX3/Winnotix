"""Xtream API providers: connect, load, and fetch a series' episodes.

`xtream.py` is kept byte-identical to upstream (see README), so everything that
has to change to make Xtream work lives here.

Upstream drives pyxtream straight from its GTK reload loop
(`hypnotix.py:1533-1573`): construct `XTream`, check `auth_data != {}`, call
`load_iptv()`, hand the four collections to the Provider. That is the whole
integration, and it inherits six problems that only show up once there is more
than one provider, once credentials are wrong, or once someone opens a series:

1. **`XTream` stores its state on the class, not the instance.** `state`,
   `auth_data`, `authorization`, `groups`, `channels`, `movies`, `series` and
   `catch_all_group` are all class attributes that `__init__` never rebinds. So
   a second Xtream provider finds `state["authenticated"]` already `True`,
   skips authentication entirely, reads the never-reassigned class-level
   `auth_data` — `{}` — and reports an authentication failure it never
   attempted. `XtreamSession` below gives each session its own.

2. **`authenticate()` treats any HTTP 200 carrying a `user_info` object as
   success.** Panels answer wrong credentials, expired subscriptions and bans
   with exactly that shape, so a dead account looks connected and then silently
   loads nothing. `check_account` reads `auth` and `status` instead.

3. **`load_iptv()` resolves a stream's category against one flat group list**
   (`next(x for x in self.groups if x.group_id == int(category_id))`) even
   though Xtream namespaces category ids *per stream type* — live category 3
   and VOD category 3 are unrelated. Whichever sorted first wins, so movies get
   filed under TV categories. `load()` resolves within a stream type.

4. **`get_series_info_by_id()` nests its episode loop inside its season loop**,
   giving every season a copy of every episode in the series; and its `Episode`
   reads `cover` off the *season* dict it is handed as `series_info`, so a panel
   that omits it loses the series to a `KeyError`. `load_series()` replaces
   both.

5. **`Channel` normalises the odd `created_live` / `radio_streams` stream types
   for its type check but then builds the URL from the raw value**, producing
   `…/created_live/user/pass/1.ts`. `load()` normalises the dict first.

6. **`authenticate()` can raise straight out of the constructor.** It calls
   `r.json()` and then indexes `user_info["username"]` with no guard, so an
   HTML error page, or the `{"user_info": {"auth": 0}}` most panels answer a
   bad password with, raises `ValueError`/`KeyError` from `XTream.__init__`
   rather than leaving `auth_data` empty for the caller's check. `connect()`
   catches that and diagnoses it like any other failure.

What is *not* changed: the request methods, the JSON disk cache and its 8-hour
freshness threshold, and the `Channel`/`Group`/`Serie`/`Season`/`Episode` model
classes are all upstream's, used as-is. `load_iptv()` is the only part replaced.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

from .xtream import XTream, Channel, Episode, Group, Season, Serie

# Upstream calls this group "xEverythingElse" — the leading x is there to sort
# it last. We sort explicitly, so it can have a name worth showing a user.
UNCATEGORISED = "Uncategorised"
UNCATEGORISED_ID = "9999"


class XtreamError(RuntimeError):
    """A connection, credential or payload problem, phrased for the status bar."""


class XtreamSession(XTream):
    """An `XTream` whose state is genuinely per-instance.

    Every attribute rebound here is declared at class level upstream and never
    reassigned in `__init__` — see note 1 in the module docstring. They are set
    *before* `super().__init__`, because that constructor calls `authenticate()`,
    which reads `state` and writes `auth_data`.
    """

    def __init__(self, *args, **kwargs) -> None:
        self.state = {"authenticated": False, "loaded": False}
        self.auth_data = {}
        self.authorization = {}
        self.groups = []
        self.channels = []
        self.series = []
        self.movies = []
        self.catch_all_group = Group(
            {"category_id": UNCATEGORISED_ID, "category_name": UNCATEGORISED, "parent_id": 0},
            "",
        )
        super().__init__(*args, **kwargs)


@dataclass
class XtreamLoad:
    """What a load produced, and what it had to throw away."""

    channels: int = 0
    movies: int = 0
    series: int = 0
    groups: int = 0
    skipped_unnamed: int = 0
    skipped_adult: int = 0
    skipped_malformed: int = 0
    account: str = ""

    def summary(self) -> str:
        parts = []
        if self.skipped_unnamed:
            parts.append(f"{self.skipped_unnamed} unnamed")
        if self.skipped_adult:
            parts.append(f"{self.skipped_adult} adult")
        if self.skipped_malformed:
            parts.append(f"{self.skipped_malformed} malformed")
        return f"skipped {', '.join(parts)}" if parts else ""


# ----------------------------------------------------------------------
# Connecting
# ----------------------------------------------------------------------


def connect(provider, *, user_agent: str = "", cache_path: str = "",
            hide_adult_content: bool = False) -> XtreamSession:
    """Authenticate against `provider`, or raise `XtreamError` saying why not.

    Upstream's only failure message is `print("XTREAM Authentication Failed")`,
    which covers a typo'd URL, a refused connection, an expired subscription and
    a panel that is not Xtream at all. Each gets its own message here.
    """
    url = (provider.url or "").strip().rstrip("/")
    if not url:
        raise XtreamError("This provider has no server URL.")
    if not url.startswith(("http://", "https://")):
        raise XtreamError("The server URL must start with http:// or https://.")
    if not (provider.username or "").strip() or not (provider.password or "").strip():
        raise XtreamError("Xtream providers need both a username and a password.")

    if cache_path:
        os.makedirs(cache_path, exist_ok=True)

    username = provider.username.strip()
    password = provider.password.strip()
    auth_url = f"{url}/player_api.php?username={username}&password={password}"

    try:
        session = XtreamSession(
            provider.name,
            username,
            password,
            url,
            hide_adult_content=hide_adult_content,
            user_agent=user_agent,
            cache_path=cache_path,
        )
    except Exception:
        # See note 6: authenticate() indexes user_info["username"] and calls
        # r.json() unguarded, so a rejection payload or an HTML error page
        # raises straight out of the constructor.
        raise XtreamError(_diagnose(auth_url, user_agent)) from None

    if not session.auth_data:
        raise XtreamError(_diagnose(auth_url, user_agent))
    problem = check_account(session.auth_data)
    if problem:
        raise XtreamError(problem)
    return session


def check_account(auth_data: dict) -> str | None:
    """Return why this account cannot be used, or None if it can.

    Upstream never looks past the presence of `user_info` — see note 2.
    """
    info = auth_data.get("user_info") or {}
    if str(info.get("auth", "1")).lower() not in ("1", "true"):
        return "The server rejected that username and password."
    status = str(info.get("status") or "").strip()
    if status and status.lower() != "active":
        return f"That account is not active — the server reports it as “{status}”."
    return None


def account_summary(auth_data: dict) -> str:
    """A short 'expires …, n of m connections' line, as far as the panel reports it."""
    info = auth_data.get("user_info") or {}
    parts = []
    expiry = info.get("exp_date")
    if expiry in (None, "", "null"):
        parts.append("no expiry")
    else:
        try:
            when = datetime.fromtimestamp(int(expiry), tz=timezone.utc)
            parts.append(f"expires {when:%Y-%m-%d}")
        except (TypeError, ValueError, OverflowError, OSError):
            pass
    active, allowed = info.get("active_cons"), info.get("max_connections")
    if active is not None and allowed not in (None, "", "0"):
        parts.append(f"{active} of {allowed} connections in use")
    return ", ".join(parts)


def _diagnose(auth_url: str, user_agent: str) -> str:
    """Ask the server once more, on the failure path only, to say what went wrong.

    `authenticate()` prints its reason and discards it, and can raise before a
    session object exists at all, so the reason has to be obtained again rather
    than read off the session.
    """
    try:
        response = requests.get(
            auth_url,
            timeout=(4, 15),
            headers={"User-Agent": user_agent},
        )
    except requests.exceptions.SSLError:
        return "The server's HTTPS certificate could not be verified."
    except requests.exceptions.Timeout:
        return "The server did not answer in time."
    except requests.exceptions.ConnectionError:
        return "Could not reach the server. Check the address, including its port."
    except requests.exceptions.RequestException as exc:
        return f"Could not reach the server: {exc}"

    if not response.ok:
        return f"The server answered {response.status_code} {response.reason}."
    try:
        data = response.json()
    except ValueError:
        return ("The server answered, but not with Xtream data. The URL should be the "
                "panel root — http://host:8080 — with no /player_api.php or /c on the end.")
    problem = check_account(data)
    return problem or "The server did not accept that username and password."


# ----------------------------------------------------------------------
# Loading
# ----------------------------------------------------------------------


def load(provider, session: XtreamSession, *, refresh: bool = False) -> XtreamLoad:
    """Fill `provider`'s four collections from `session`.

    Replaces `XTream.load_iptv()` — see notes 3 and 5 in the module docstring.
    The disk cache, its 8-hour freshness threshold and the model classes are
    still upstream's; only the grouping is ours.
    """
    result = XtreamLoad(account=account_summary(session.auth_data))
    channels: list = []
    movies: list = []
    series: list = []
    groups: list = []

    for stream_type in (session.live_type, session.vod_type, session.series_type):
        categories = _cached(session, f"all_groups_{stream_type}.json", refresh,
                             lambda t=stream_type: session._load_categories_from_provider(t))
        if categories is None:
            raise XtreamError(f"The server did not return its {stream_type} categories.")
        streams = _cached(session, f"all_stream_{stream_type}.json", refresh,
                          lambda t=stream_type: session._load_streams_from_provider(t))
        if streams is None:
            raise XtreamError(f"The server did not return its {stream_type} listing.")

        # Category ids are namespaced per stream type, so this map is rebuilt
        # for each type rather than shared across all three.
        by_id: dict[int, Group] = {}
        type_groups: list[Group] = []
        for category in categories:
            try:
                group = Group(category, stream_type)
            except (KeyError, TypeError, ValueError):
                result.skipped_malformed += 1
                continue
            by_id.setdefault(group.group_id, group)
            type_groups.append(group)

        catch_all = Group(
            {"category_id": UNCATEGORISED_ID, "category_name": UNCATEGORISED, "parent_id": 0},
            stream_type,
        )
        type_groups.append(catch_all)

        for stream in streams:
            item = _build(session, stream, stream_type, by_id, catch_all, result)
            if item is None:
                continue
            entry, group = item
            if stream_type == session.series_type:
                series.append(entry)
                group.series.append(entry)
            elif stream_type == session.live_type:
                channels.append(entry)
                group.channels.append(entry)
            else:
                movies.append(entry)
                group.channels.append(entry)

        # An Xtream panel typically advertises categories it has no streams for.
        # Upstream lists them as "Name (0)" tiles; the app already drops groups
        # that filtering empties, so empty ones are dropped here for the same reason.
        groups.extend(g for g in type_groups if g.channels or g.series)

    groups.sort(key=lambda g: (g.group_type, g.name.lower()))

    provider.channels = channels
    provider.movies = movies
    provider.series = series
    provider.groups = groups

    result.channels = len(channels)
    result.movies = len(movies)
    result.series = len(series)
    result.groups = len(groups)
    return result


def _build(session, stream, stream_type, by_id, catch_all, result):
    """One raw stream dict -> (model object, the group it belongs to), or None."""
    if not isinstance(stream, dict):
        result.skipped_malformed += 1
        return None
    if not str(stream.get("name") or "").strip():
        result.skipped_unnamed += 1
        return None
    if (session.hide_adult_content and stream_type == session.live_type
            and str(stream.get("is_adult") or "0") == "1"):
        result.skipped_adult += 1
        return None

    category = stream.get("category_id")
    group = catch_all
    if category in (None, "", "0"):
        # `Channel` does `int(stream_info["category_id"])` whenever the key is
        # present, so an empty one is a ValueError. Upstream rewrites it to the
        # catch-all id before constructing; so do we.
        stream = dict(stream, category_id=UNCATEGORISED_ID)
    else:
        try:
            group = by_id.get(int(category), catch_all)
        except (TypeError, ValueError):
            group = catch_all

    try:
        if stream_type == session.series_type:
            entry = Serie(session, stream)
        else:
            # `Channel` normalises these two for its type check but not for the
            # URL it builds -- see note 5.
            if stream.get("stream_type") in ("created_live", "radio_streams"):
                stream = dict(stream, stream_type="live")
            entry = Channel(session, group.name, stream)
            if not entry.url:
                # Channel prints and returns without setting anything when it
                # does not recognise the stream type.
                result.skipped_malformed += 1
                return None
    except (KeyError, TypeError, ValueError):
        result.skipped_malformed += 1
        return None
    return entry, group


def _cached(session: XtreamSession, filename: str, refresh: bool, fetch):
    """Upstream's read-cache-or-download-and-save, with a refresh bypass."""
    if not refresh:
        cached = session._load_from_file(filename)
        if cached is not None:
            return cached
    data = fetch()
    if data is not None:
        session._save_to_file(data, filename)
    return data


# ----------------------------------------------------------------------
# Seasons and episodes
# ----------------------------------------------------------------------


def load_series(session: XtreamSession, serie: Serie) -> int:
    """Populate `serie.seasons` and `serie.episodes`. Returns the episode count.

    Replaces `XTream.get_series_info_by_id()` — see note 4. Two differences
    beyond fixing that: the `episodes` object drives the result rather than
    `seasons` (panels routinely return an empty `seasons` array while carrying a
    full `episodes` map, and upstream would show nothing at all for those), and
    seasons are keyed by number so they sort like the M3U path's do.
    """
    data = session._load_series_info_by_id_from_provider(serie.series_id)
    if not data:
        raise XtreamError("The server did not return this series' episodes.")

    episodes_by_season = data.get("episodes") or {}
    if isinstance(episodes_by_season, list):
        # Some panels return a list positional by season rather than an object.
        episodes_by_season = {str(i + 1): v for i, v in enumerate(episodes_by_season)}

    names = {}
    for season_info in data.get("seasons") or []:
        if isinstance(season_info, dict) and season_info.get("season_number") is not None:
            names[str(season_info["season_number"])] = str(
                season_info.get("name") or ""
            ).strip()

    serie.seasons = {}
    serie.episodes = []
    total = 0
    for key in sorted(episodes_by_season, key=_number_key):
        entries = episodes_by_season[key] or []
        if not isinstance(entries, list):
            continue
        season = Season(names.get(str(key)) or str(key))
        for episode_info in entries:
            episode = _episode(session, serie, episode_info)
            if episode is None:
                continue
            number = str(episode_info.get("episode_num") or "").strip()
            season.episodes[number or episode.title] = episode
            serie.episodes.append(episode)
            total += 1
        if season.episodes:
            serie.seasons[str(key)] = season
    if not total:
        raise XtreamError("The server returned no episodes for this series.")
    return total


def _episode(session, serie, episode_info):
    """Build one Episode, supplying the cover upstream reads off the wrong dict."""
    if not isinstance(episode_info, dict) or not episode_info.get("id"):
        return None
    try:
        # Upstream hands `Episode` the *season* dict as `series_info` and reads
        # `cover` from it. The series' own cover is what it actually wants, and
        # is always present; a season's often is not.
        return Episode(session, {"cover": serie.logo}, serie.name, dict(
            episode_info,
            title=str(episode_info.get("title") or "").strip()
            or f"Episode {episode_info.get('episode_num', '?')}",
            container_extension=episode_info.get("container_extension") or "mp4",
            info=episode_info.get("info") or {},
        ))
    except (KeyError, TypeError, ValueError):
        return None


def _number_key(value):
    """Sort '2' before '10', and anything non-numeric after both."""
    text = str(value).strip()
    return (0, int(text), "") if text.isdigit() else (1, 0, text.lower())
