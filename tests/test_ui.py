"""Tests for UI logic that can be checked without a display.

Runs under Qt's offscreen platform, so there is no window and no network. These
cover the pieces where a silent regression would be easy to miss: the provider
form's conditional fields, the group-name cleanup, and the flow layout's
wrapping arithmetic.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, QSize  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from winnotix.ui.flow_layout import FlowLayout  # noqa: E402
from winnotix.ui.pages import (  # noqa: E402
    PROVIDER_TYPE_LOCAL,
    PROVIDER_TYPE_URL,
    PROVIDER_TYPE_XTREAM,
    ProviderEditPage,
    _remove_word,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def edit_page(qapp):
    page = ProviderEditPage()
    yield page
    page.deleteLater()


# --------------------------------------------------------------------------
# Group name cleanup
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "word,text,expected",
    [
        ("VOD", "VOD Movies", "Movies"),
        ("SERIES", "EN SERIES", "EN"),
        ("VOD", "Movies", "Movies"),          # word absent: unchanged
        ("VOD", "VOD", "VOD"),                # would empty the label: keep original
        ("VOD", "VOD Action VOD", "Action"),  # every occurrence removed
    ],
)
def test_remove_word(word, text, expected):
    assert _remove_word(word, text) == expected


# --------------------------------------------------------------------------
# Provider form: conditional fields
# --------------------------------------------------------------------------

def _set_type(page, type_id):
    page.type_combo.setCurrentIndex(page.type_combo.findData(type_id))


def test_m3u_url_shows_url_and_epg_only(edit_page):
    _set_type(edit_page, PROVIDER_TYPE_URL)
    assert edit_page.url_entry.isVisibleTo(edit_page)
    assert edit_page.epg_entry.isVisibleTo(edit_page)
    assert not edit_page.username_entry.isVisibleTo(edit_page)
    assert not edit_page.password_entry.isVisibleTo(edit_page)


def test_local_file_shows_path_not_url(edit_page):
    _set_type(edit_page, PROVIDER_TYPE_LOCAL)
    assert edit_page.path_entry.isVisibleTo(edit_page)
    assert not edit_page.url_entry.isVisibleTo(edit_page)


def test_xtream_shows_credentials_not_epg(edit_page):
    _set_type(edit_page, PROVIDER_TYPE_XTREAM)
    assert edit_page.username_entry.isVisibleTo(edit_page)
    assert edit_page.password_entry.isVisibleTo(edit_page)
    assert not edit_page.epg_entry.isVisibleTo(edit_page)


def test_password_field_is_masked(edit_page):
    from PySide6.QtWidgets import QLineEdit
    assert edit_page.password_entry.echoMode() == QLineEdit.EchoMode.Password


# --------------------------------------------------------------------------
# Provider form: round-tripping
# --------------------------------------------------------------------------

def test_load_then_accept_round_trips_a_url_provider(edit_page, providers_dir):
    from winnotix.core.common import Provider

    # Built with join rather than hand-written separators: the format is six
    # fields, and miscounting the colons is easy and silent.
    info = ":::".join(["Name", "url", "http://host/p.m3u", "", "", "http://epg"])
    edit_page.load(Provider(None, info))

    captured = {}
    edit_page.accepted.connect(captured.update)
    edit_page._accept()

    assert captured["name"] == "Name"
    assert captured["type_id"] == PROVIDER_TYPE_URL
    assert captured["url"] == "http://host/p.m3u"
    assert captured["epg"] == "http://epg"


def test_local_provider_emits_path_as_url(edit_page, providers_dir):
    """A local provider stores its file path in the same `url` field."""
    from winnotix.core.common import Provider

    info = ":::".join(["Local", "local", r"C:\playlists\mine.m3u", "", "", ""])
    edit_page.load(Provider(None, info))
    assert edit_page.path_entry.text() == r"C:\playlists\mine.m3u"

    captured = {}
    edit_page.accepted.connect(captured.update)
    edit_page._accept()
    assert captured["url"] == r"C:\playlists\mine.m3u"


def test_load_none_clears_every_field(edit_page, providers_dir):
    from winnotix.core.common import Provider

    edit_page.load(Provider(
        None, ":::".join(["N", "xtream", "http://h", "u", "p", "e"])))
    edit_page.load(None)

    assert edit_page.name_entry.text() == ""
    assert edit_page.url_entry.text() == ""
    assert edit_page.username_entry.text() == ""
    assert edit_page.password_entry.text() == ""
    assert edit_page.epg_entry.text() == ""
    assert edit_page.type_combo.currentData() == PROVIDER_TYPE_URL


def test_accepted_payload_is_stripped(edit_page):
    edit_page.name_entry.setText("  Padded  ")
    edit_page.url_entry.setText("  http://host/p.m3u  ")

    captured = {}
    edit_page.accepted.connect(captured.update)
    edit_page._accept()
    assert captured["name"] == "Padded"
    assert captured["url"] == "http://host/p.m3u"


# --------------------------------------------------------------------------
# Flow layout
# --------------------------------------------------------------------------

def test_flow_layout_wraps_and_reports_height(qapp):
    host = QWidget()
    layout = FlowLayout(host, margin=0, spacing=10)
    for _ in range(6):
        child = QWidget()
        child.setFixedSize(QSize(100, 40))
        layout.addWidget(child)

    # 340px fits three 100px items plus two 10px gaps (320), not four (430).
    three_wide = layout.heightForWidth(340)
    assert three_wide == 40 * 2 + 10, three_wide

    # One per row: six rows.
    one_wide = layout.heightForWidth(100)
    assert one_wide == 40 * 6 + 10 * 5, one_wide


def test_flow_layout_places_items_left_to_right(qapp):
    host = QWidget()
    layout = FlowLayout(host, margin=0, spacing=10)
    children = []
    for _ in range(3):
        child = QWidget()
        child.setFixedSize(QSize(100, 40))
        layout.addWidget(child)
        children.append(child)

    layout.setGeometry(QRect(0, 0, 230, 200))
    assert children[0].geometry().topLeft().toTuple() == (0, 0)
    assert children[1].geometry().topLeft().toTuple() == (110, 0)
    # Third does not fit on the first row (330 > 230), so it wraps.
    assert children[2].geometry().topLeft().toTuple() == (0, 50)


def test_flow_layout_count_and_takeat(qapp):
    host = QWidget()
    layout = FlowLayout(host)
    for _ in range(3):
        layout.addWidget(QWidget())
    assert layout.count() == 3
    layout.takeAt(0)
    assert layout.count() == 2
    assert layout.itemAt(99) is None
    assert layout.takeAt(99) is None
