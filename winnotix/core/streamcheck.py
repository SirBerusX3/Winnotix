"""Explain, in a sentence, why a stream would not play.

Public IPTV playlists rot constantly, and mpv's report of a failed open is a
single log line -- invisible in a GUI, and for one common class of broken host,
actively misleading.

The case that prompted this: a Free-TV entry pointed at
``http://<host>/itv1/index.m3u8``. That host answers **HTTP 200** with
``Content-Type: application/octet-stream`` whose *body* is an entire second HTTP
response -- a micro_httpd 404 page, status line and headers included. mpv treats
any ``.m3u8`` URL as a playlist even without a ``#EXTM3U`` header, so it parsed
that error page as one, took its last non-comment line as a relative entry, and
tried to open::

    http://<host>/itv1/<ADDRESS><A HREF="http://www.acme.com/...">micro_httpd</A></ADDRESS>

Which reads exactly as though the playlist author had glued HTML onto the URL.
Nothing is wrong with the URL: the host is simply not serving a stream.

A second case, from BBC One Northern Ireland: mpv logged 100 consecutive
fragment 404s and gave up. The manifest was a live DASH `.mpd`, and it was
fine -- fetching the live-edge segment directly returned 46 KB of real audio,
the machine clock agreed with both the origin and the manifest's own
`UTCTiming` source to within a second, and the channel's HLS URL played. mpv's
DASH demuxer had simply computed a live edge minutes ahead of the real one and
was requesting segments that did not exist yet. Left unclassified, that reads
as a dead channel; it is not.

So this module fetches the URL once, on the failure path only, and says what
came back instead. `describe_response` is separated from the request so the
classification can be tested without a network.
"""

from __future__ import annotations

import requests

# Enough to identify a manifest, an HTML page or an embedded HTTP response
# without pulling a video segment.
SNIFF_BYTES = 2048

HTML_MARKERS = (b"<html", b"<!doctype html", b"<head", b"<body", b"<address")

DASH_TYPES = ("application/dash+xml", "video/vnd.mpeg.dash.mpd")


def describe_response(status: int, reason: str, content_type: str, body: bytes) -> str:
    """Say what a response is, if it is not a stream. Empty string if it looks fine."""
    head = (body or b"")[:SNIFF_BYTES]
    stripped = head.lstrip()
    lowered = stripped.lower()
    content_type = (content_type or "").split(";")[0].strip().lower()

    if status == 403:
        return ("The server refused the request (403 Forbidden) — this channel is "
                "usually geo-blocked.")
    if status == 404:
        return "The server has nothing at that address (404 Not Found)."
    if status >= 400:
        return f"The server answered {status} {reason}."

    if stripped.startswith(b"#EXTM3U"):
        # The manifest is fine, so whatever failed is further in: an expired
        # token, a dead segment host, or a codec mpv could not open.
        return ("The playlist itself loaded, so the channel is off air or its video "
                "segments are unavailable.")

    if content_type in DASH_TYPES or b"<mpd" in lowered:
        # Worth calling out separately from HLS. mpv's DASH demuxer computes the
        # live edge from the manifest's clock arithmetic, and on some live
        # manifests it overshoots and asks for segments that do not exist yet --
        # 404 per fragment until it gives up at 100 consecutive failures. The
        # address is good and the stream is usually playing; the same channel's
        # HLS URL, where segments are listed rather than calculated, avoids it.
        return ("The DASH manifest loaded, so the address is good. mpv could not "
                "fetch its segments — live DASH often fails this way even when the "
                "stream is fine, and an HLS (.m3u8) URL for the same channel "
                "usually plays.")

    if stripped.startswith(b"HTTP/"):
        # A whole HTTP response inside a 200 body. Misconfigured embedded servers
        # do this, and it is the case that produces HTML glued onto the URL.
        inner = stripped.split(b"\n", 1)[0].decode("latin-1", "replace").strip()
        return (f"The server answered {status} {reason}, but the body is another HTTP "
                f"response — “{inner}”. There is no stream at that address.")

    if content_type.startswith("text/html") or any(m in lowered for m in HTML_MARKERS):
        return ("The server returned a web page, not a stream — usually a login page "
                "or a captive portal.")

    if content_type.startswith("text/"):
        return f"The server returned {content_type}, not a stream."

    return ""


def diagnose(url: str, *, user_agent: str = "", referer: str = "",
             timeout: tuple[float, float] = (4, 8)) -> str:
    """Fetch `url` once and describe what came back. Never raises."""
    if not url:
        return ""
    headers = {}
    if user_agent:
        headers["User-Agent"] = user_agent
    if referer:
        headers["Referer"] = referer

    try:
        with requests.get(url, headers=headers, timeout=timeout, stream=True) as response:
            body = next(response.iter_content(SNIFF_BYTES), b"")
            return describe_response(
                response.status_code,
                response.reason or "",
                response.headers.get("Content-Type", ""),
                body,
            )
    except requests.exceptions.SSLError:
        return "The server's HTTPS certificate could not be verified."
    except requests.exceptions.Timeout:
        return "The server did not answer in time."
    except requests.exceptions.ConnectionError:
        return "Could not reach the server — the host is down or the address is wrong."
    except requests.exceptions.RequestException as exc:
        return f"Could not reach the server: {exc}"
