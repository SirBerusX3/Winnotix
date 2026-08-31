"""Classifying why a stream would not play. No network.

The first test carries the real response that prompted this module -- see the
header of winnotix/core/streamcheck.py.
"""

from __future__ import annotations

import pytest
import requests

from winnotix.core import streamcheck

# Verbatim from http://45.14.84.37/itv1/index.m3u8, a Free-TV entry for ITV 1:
# HTTP 200, application/octet-stream, and a whole second HTTP response as the body.
MICRO_HTTPD_BODY = (
    b"HTTP/1.1 404 Not Found\r\n"
    b"Server: micro_httpd\r\n"
    b"Cache-Control: no-cache\r\n"
    b"Content-Type: text/html\r\n"
    b"Connection: close\r\n"
    b"\r\n"
    b"<html><head>\n<TITLE>404 Not Found</TITLE></HEAD>\n"
    b'<BODY BGCOLOR="#cc9999"><H4>404 Not Found</H4>\nFile not found.\n<HR>\n'
    b'<ADDRESS><A HREF="http://www.acme.com/software/micro_httpd/">micro_httpd</A>'
    b"</ADDRESS>\n</BODY></HTML>"
)


def test_an_http_response_inside_the_body_is_named():
    """This is what makes mpv build a URL with HTML on the end: it treats any
    .m3u8 as a playlist, so the error page's last line becomes a relative entry."""
    message = streamcheck.describe_response(
        200, "Ok", "application/octet-stream", MICRO_HTTPD_BODY
    )
    assert "404 Not Found" in message
    assert "no stream at that address" in message
    # The explanation must not itself be a wall of HTML.
    assert "<ADDRESS>" not in message


def test_a_login_page_is_named():
    body = (b'<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN">\n'
            b"<html><head><title>Redirect To Login Page</title></head><body></body></html>")
    message = streamcheck.describe_response(200, "Ok", "text/html", body)
    assert "web page, not a stream" in message


def test_a_valid_manifest_points_the_blame_further_in():
    body = b"#EXTM3U\n#EXT-X-VERSION:3\n#EXTINF:6,\nsegment0.ts\n"
    message = streamcheck.describe_response(200, "OK", "application/vnd.apple.mpegurl", body)
    assert "playlist itself loaded" in message


def test_binary_media_gets_no_explanation():
    """A real stream that mpv could not decode is not this module's business."""
    assert streamcheck.describe_response(200, "OK", "video/mp2t", b"\x47\x40\x00\x10" * 8) == ""


@pytest.mark.parametrize(
    "status, reason, expected",
    [
        (403, "Forbidden", "geo-blocked"),
        (404, "Not Found", "404 Not Found"),
        (500, "Internal Server Error", "500 Internal Server Error"),
    ],
)
def test_error_statuses_are_reported(status, reason, expected):
    assert expected in streamcheck.describe_response(status, reason, "text/html", b"")


def test_html_without_a_content_type_is_still_recognised():
    message = streamcheck.describe_response(200, "OK", "", b"\n\n  <HTML><BODY>nope</BODY></HTML>")
    assert "web page" in message


def test_plain_text_is_reported():
    message = streamcheck.describe_response(200, "OK", "text/plain", b"stream offline")
    assert "text/plain" in message


# ----------------------------------------------------------------------
# diagnose()
# ----------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status_code=200, reason="OK", content_type="", body=b""):
        self.status_code = status_code
        self.reason = reason
        self.headers = {"Content-Type": content_type}
        self._body = body

    def iter_content(self, size):
        yield self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_diagnose_reads_the_response(monkeypatch):
    seen = {}

    def fake_get(url, headers=None, timeout=None, stream=None):
        seen.update(url=url, headers=headers, stream=stream)
        return FakeResponse(200, "Ok", "application/octet-stream", MICRO_HTTPD_BODY)

    monkeypatch.setattr(streamcheck.requests, "get", fake_get)
    message = streamcheck.diagnose("http://host/itv1/index.m3u8",
                                   user_agent="Mozilla/5.0", referer="http://ref/")
    assert "404 Not Found" in message
    assert seen["headers"] == {"User-Agent": "Mozilla/5.0", "Referer": "http://ref/"}
    assert seen["stream"] is True  # never pull a whole segment


@pytest.mark.parametrize(
    "exception, expected",
    [
        (requests.exceptions.ConnectionError("refused"), "Could not reach"),
        (requests.exceptions.ReadTimeout("slow"), "did not answer in time"),
        (requests.exceptions.SSLError("bad cert"), "certificate"),
    ],
)
def test_diagnose_survives_network_failures(monkeypatch, exception, expected):
    def failing(*args, **kwargs):
        raise exception

    monkeypatch.setattr(streamcheck.requests, "get", failing)
    assert expected in streamcheck.diagnose("http://host/stream.m3u8")


def test_diagnose_ignores_an_empty_url():
    assert streamcheck.diagnose("") == ""


# The opening of https://vs-cmaf-pushb-uk-live.akamaized.net/.../pc_hd_abr_v2.mpd
# (BBC One Northern Ireland), which mpv reports only as 100 fragment 404s.
DASH_MANIFEST = (
    b'<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="dynamic" '
    b'availabilityStartTime="1970-01-01T00:00:12Z" minBufferTime="PT10S" '
    b'timeShiftBufferDepth="PT2H" maxSegmentDuration="PT4S">\n'
    b'  <Period id="1" start="PT0S">\n'
    b'    <AdaptationSet id="1" contentType="audio" mimeType="audio/mp4">\n'
)


def test_a_dash_manifest_is_not_reported_as_a_dead_link():
    """The manifest is fine; mpv's DASH demuxer overshoots the live edge."""
    message = streamcheck.describe_response(
        200, "OK", "application/dash+xml", DASH_MANIFEST
    )
    assert "DASH manifest loaded" in message
    assert "address is good" in message
    assert ".m3u8" in message  # the workaround worth knowing


def test_dash_is_recognised_without_a_content_type():
    message = streamcheck.describe_response(200, "OK", "", DASH_MANIFEST)
    assert "DASH" in message


def test_dash_is_not_mistaken_for_a_web_page():
    """Both are angle brackets; only one means "there is nothing here"."""
    dash = streamcheck.describe_response(200, "OK", "application/dash+xml", DASH_MANIFEST)
    assert "web page" not in dash
