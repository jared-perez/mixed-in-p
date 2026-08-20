"""The Metadata panel's half of the online lookup: the button, and the write.

No test here reaches the network — the panel's provider is never constructed,
because every test either stops before the request or hands the panel a result
directly.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtWidgets import QMessageBox

import src.gui.widgets.metadata_panel as panel_module
from src.gui.widgets.dialogs.lookup_review import ARTWORK_FIELD
from src.gui.widgets.metadata_panel import MetadataPanel
from src.gui.workers.lookup_worker import LookupResult
from src.metadata.tags import read_metadata, write_metadata, TrackMetadata
from src.online.result import (
    ERROR_AUTH,
    ERROR_NETWORK,
    ERROR_NOT_FOUND,
    ERROR_NO_TOKEN,
    ERROR_RATE_LIMIT,
    Candidate,
    ProposedTags,
)


@pytest.fixture
def flac(tmp_path):
    sf = pytest.importorskip("soundfile")
    path = tmp_path / "Underworld - Born Slippy.flac"
    sf.write(str(path), np.zeros(4410, dtype=np.float32), 44100, format="FLAC")
    return str(path)


@pytest.fixture
def panel(qtbot, flac):
    widget = MetadataPanel()
    qtbot.addWidget(widget)
    widget._load_file(flac)
    return widget


def _result(path, **kwargs) -> LookupResult:
    chosen = Candidate(release_id=1, artist="Underworld", album="Born Slippy", score=0.9)
    base = dict(
        path=path,
        candidates=[chosen],
        chosen=chosen,
        proposed=ProposedTags(
            title="Born Slippy (Nuxx)", artist="Underworld", provider="discogs"
        ),
    )
    base.update(kwargs)
    return LookupResult(**base)


# --- the button -------------------------------------------------------------


def test_the_button_is_hidden_until_the_setting_is_on(panel):
    # Hidden, not greyed: until the user opts in the app should look as
    # offline as it is.
    assert panel._lookup_btn.isHidden()
    panel.set_online_lookup(True, token="tok")
    assert not panel._lookup_btn.isHidden()


def test_the_button_goes_away_with_the_file(panel):
    panel.set_online_lookup(True, token="tok")
    panel._clear()
    assert panel._lookup_btn.isHidden()


def test_turning_the_setting_off_hides_the_button_again(panel):
    panel.set_online_lookup(True, token="tok")
    panel.set_online_lookup(False)
    assert panel._lookup_btn.isHidden()


def test_a_file_with_nothing_to_search_on_says_so_and_starts_no_thread(
    qtbot, tmp_path, monkeypatch
):
    sf = pytest.importorskip("soundfile")
    path = tmp_path / "track01.flac"  # no tags, and a name that parses to nothing
    sf.write(str(path), np.zeros(4410, dtype=np.float32), 44100, format="FLAC")
    widget = MetadataPanel()
    qtbot.addWidget(widget)
    widget._load_file(str(path))
    widget.set_online_lookup(True, token="tok")

    said: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda *args, **kw: said.append(args[2])
    )
    widget._on_lookup_clicked()
    assert said and "Title" in said[0]
    assert widget._lookup_thread is None


def test_the_query_falls_back_to_the_filename_when_the_tags_are_empty(panel, flac):
    # The file is named "Underworld - Born Slippy.flac" and has no tags.
    query = panel._current_query()
    assert query.artist == "Underworld"
    assert query.title == "Born Slippy"


def test_each_failure_kind_gets_its_own_sentence(panel):
    kinds = [ERROR_NO_TOKEN, ERROR_AUTH, ERROR_RATE_LIMIT, ERROR_NOT_FOUND, ERROR_NETWORK]
    sentences = [panel._lookup_error_text(kind) for kind in kinds]
    assert len(set(sentences)) == len(kinds)
    assert all(s and not s.startswith("ERROR") for s in sentences)


def test_a_failed_lookup_reports_it_and_opens_no_dialog(panel, monkeypatch):
    said: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda *args, **kw: said.append(args[2])
    )
    panel._on_lookup_result(_result(panel._file_path, proposed=None, error=ERROR_NETWORK))
    assert said and "connection" in said[0].lower()


def test_a_result_for_a_file_that_has_since_been_ejected_is_dropped(panel, monkeypatch):
    # The lookup runs off-thread; the user is free to eject or drop another
    # file while it does.
    opened: list[str] = []
    monkeypatch.setattr(
        MetadataPanel, "_show_review_dialog", lambda self, r: opened.append(r.path)
    )
    result = _result("/some/other/file.flac")
    panel._on_lookup_result(result)
    assert opened == []


# --- the write --------------------------------------------------------------


def test_approved_values_are_written_through_the_ordinary_tag_path(panel, flac):
    panel._apply_lookup_values({"artist": "Underworld", "title": "Born Slippy (Nuxx)"})
    meta = read_metadata(flac)
    assert meta.artist == "Underworld"
    assert meta.title == "Born Slippy (Nuxx)"


def test_the_form_is_rebuilt_from_disk_after_a_write(panel, flac):
    panel._apply_lookup_values({"artist": "Underworld"})
    # Read back from the form, not from what we believe we wrote.
    assert panel._field_edits["artist"].text() == "Underworld"


def test_nothing_approved_writes_nothing(panel, flac):
    write_metadata(flac, TrackMetadata(artist="Original"), ["artist"])
    panel._apply_lookup_values({})
    assert read_metadata(flac).artist == "Original"


def test_a_field_the_user_left_unticked_is_not_written(panel, flac):
    write_metadata(flac, TrackMetadata(artist="Original"), ["artist"])
    panel._apply_lookup_values({"title": "Born Slippy (Nuxx)"})
    meta = read_metadata(flac)
    assert meta.artist == "Original"
    assert meta.title == "Born Slippy (Nuxx)"


def test_approved_artwork_is_written_with_the_type_its_bytes_say(panel, flac):
    png = _png_bytes()
    panel._apply_lookup_values({ARTWORK_FIELD: png})
    meta = read_metadata(flac)
    assert meta.artwork
    # Written as PNG because the bytes are a PNG — there is no filename to go
    # on, and claiming JPEG produces art some players refuse to draw.
    assert meta.artwork_mime == "image/png"


def test_a_year_arrives_as_a_number_not_a_string(panel, flac):
    panel._apply_lookup_values({"year": 1995, "track_number": 2})
    meta = read_metadata(flac)
    assert meta.year == 1995
    assert meta.track_number == 2


# --- end to end -------------------------------------------------------------


def test_button_to_written_tag_with_a_stub_provider(qtbot, panel, flac, monkeypatch):
    """Click → search → fetch → review → write, with nothing but the network faked.

    The one test that exercises the wiring rather than a piece of it: the real
    thread, the real dialog and the real tag writer, with a stub standing in
    for Discogs.
    """
    import src.gui.widgets.metadata_panel as panel_module
    from src.gui.widgets.dialogs.lookup_review import LookupReviewDialog

    class StubProvider:
        on_wait = None

        def __init__(self, token=""):
            self.token = token

        def search(self, query, limit=25):
            assert query.title == "Born Slippy"  # the filename fallback ran
            return [Candidate(release_id=1, artist="Underworld", album="Born Slippy")]

        def fetch(self, candidate, query):
            candidate.score = 0.95
            return ProposedTags(
                title="Born Slippy (Nuxx)",
                artist="Underworld",
                label="Junior Boy's Own",
                provider="discogs",
            )

        def fetch_artwork(self, url):
            return b""

    monkeypatch.setattr(panel_module, "DiscogsProvider", StubProvider)

    # Approve everything the dialog offers, then accept it.
    def approve(self):
        self._select_all()
        return 1  # QDialog.Accepted

    monkeypatch.setattr(LookupReviewDialog, "exec", approve)

    panel.set_online_lookup(True, token="tok")
    panel._on_lookup_clicked()
    qtbot.waitUntil(lambda: panel._lookup_thread is None, timeout=5000)
    qtbot.wait(10)

    meta = read_metadata(flac)
    assert meta.title == "Born Slippy (Nuxx)"
    assert meta.artist == "Underworld"
    assert meta.label == "Junior Boy's Own"


# --- the empty state --------------------------------------------------------


@pytest.fixture
def untagged(tmp_path):
    sf = pytest.importorskip("soundfile")
    path = tmp_path / "Underworld - Born Slippy.flac"
    sf.write(str(path), np.zeros(4410, dtype=np.float32), 44100, format="FLAC")
    return str(path)


def test_a_file_with_no_tags_is_offered_the_lookup(qtbot, untagged):
    # query_for's filename fallback was written for exactly this file, and the
    # empty form never mentioned it.
    panel = MetadataPanel()
    qtbot.addWidget(panel)
    panel.set_online_lookup(True, token="tok")
    panel._load_file(untagged)
    assert not panel._empty_hint.isHidden()
    assert "Discogs" in panel._empty_hint.text()


def test_the_offer_is_not_made_when_the_feature_is_off(qtbot, untagged):
    # A sentence naming Discogs on a panel with no Discogs on it advertises
    # something the user cannot reach.
    panel = MetadataPanel()
    qtbot.addWidget(panel)
    panel._load_file(untagged)
    assert panel._empty_hint.isHidden()


def test_a_tagged_file_is_not_offered_the_lookup(qtbot, flac):
    write_metadata(flac, TrackMetadata(title="Born Slippy (Nuxx)"), ["title"])
    panel = MetadataPanel()
    qtbot.addWidget(panel)
    panel.set_online_lookup(True, token="tok")
    panel._load_file(flac)
    assert panel._empty_hint.isHidden()


def test_typing_a_title_takes_the_offer_away(qtbot, untagged):
    panel = MetadataPanel()
    qtbot.addWidget(panel)
    panel.set_online_lookup(True, token="tok")
    panel._load_file(untagged)
    # "Add field" is how a blank file gets a Title row at all.
    panel._add_field_row("title", "Title")
    panel._field_edits["title"].setText("Born Slippy (Nuxx)")
    panel._on_editing_finished()
    assert panel._empty_hint.isHidden()


def test_the_offer_goes_away_with_the_file(qtbot, untagged):
    panel = MetadataPanel()
    qtbot.addWidget(panel)
    panel.set_online_lookup(True, token="tok")
    panel._load_file(untagged)
    panel._clear()
    assert panel._empty_hint.isHidden()


# --- provenance -------------------------------------------------------------
#
# Never open a browser: the click handler is driven directly and the URL is
# asserted on the widget, which is the only part of it that is ours.


class _StubDialog:
    """Stands in for an open review dialog, so no modal is ever shown.

    It also puts the result through the branch the ordering trap is about: a
    candidate switch comes back to _on_lookup_result with the dialog already
    open, and returns before the code that shows one.
    """

    def __init__(self) -> None:
        self.results: list = []

    def set_result(self, result) -> None:
        self.results.append(result)


def _applied(panel, path, url="https://www.discogs.com/release/1002", **values):
    """Hand the panel a result, then apply values as the dialog would."""
    panel._review_dialog = _StubDialog()
    try:
        panel._on_lookup_result(
            _result(path, proposed=ProposedTags(provider="discogs", source_url=url))
        )
    finally:
        panel._review_dialog = None
    panel._apply_lookup_values(values or {"artist": "Underworld"})


def test_an_apply_says_where_the_values_came_from(panel, flac):
    _applied(panel, flac, artist="Underworld", title="Born Slippy (Nuxx)")
    assert "Discogs" in panel._lookup_status.text()
    assert not panel._release_link.isHidden()
    assert panel._release_url == "https://www.discogs.com/release/1002"


def test_the_link_follows_the_release_the_user_ended_up_on(panel, flac):
    # A candidate switch comes back through _on_lookup_result while the dialog
    # is open. Crediting the release the user rejected is the failure here.
    _applied(panel, flac, url="https://www.discogs.com/release/1")
    _applied(panel, flac, url="https://www.discogs.com/release/999")
    assert panel._release_url == "https://www.discogs.com/release/999"


def test_the_provenance_goes_away_when_the_file_does(panel, flac):
    _applied(panel, flac)
    panel._clear()
    assert panel._lookup_status.isHidden()
    assert panel._release_link.isHidden()
    assert panel._release_url == ""


def test_a_second_file_does_not_wear_the_first_one_s_provenance(panel, flac, tmp_path):
    sf = pytest.importorskip("soundfile")
    other = tmp_path / "another.flac"
    sf.write(str(other), np.zeros(4410, dtype=np.float32), 44100, format="FLAC")
    _applied(panel, flac)
    panel._load_file(str(other))
    assert panel._lookup_status.isHidden()
    assert panel._release_link.isHidden()
    assert panel._release_url == ""


def test_switching_the_feature_off_takes_the_link_with_it(panel, flac):
    panel.set_online_lookup(True, token="tok")
    _applied(panel, flac)
    panel.set_online_lookup(False)
    assert panel._release_link.isHidden()


def test_a_result_with_no_release_page_offers_no_link(panel, flac):
    _applied(panel, flac, url="")
    assert "Discogs" in panel._lookup_status.text()
    assert panel._release_link.isHidden()


def test_the_link_opens_the_release_page(panel, flac, monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr(
        panel_module.QDesktopServices, "openUrl", lambda url: opened.append(url.toString())
    )
    _applied(panel, flac)
    panel._on_release_link_clicked()
    assert opened == ["https://www.discogs.com/release/1002"]


def _png_bytes() -> bytes:
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
        "IQAAAABJRU5ErkJggg=="
    )
