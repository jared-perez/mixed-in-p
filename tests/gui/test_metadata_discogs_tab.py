"""The Metadata panel's Discogs tab, and the release memory behind it.

Two rules carry this feature, and both are easy to break silently:

* **A file dropped here need not be in the library, and the panel must not
  put it there.** Calling `add_track` from a tag editor would quietly turn it
  into a library importer.
* **What is stored is an identity, not content.** The release id, and nothing
  the provider fetched — which is what leaves the freshness rule intact and
  is why the tab has a Refresh button rather than a cache.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.gui.widgets.metadata_panel import MetadataPanel
from src.gui.workers.lookup_worker import LookupJob, LookupResult, _preferred
from src.library import Library
from src.online.result import Candidate, ProposedTags


@pytest.fixture
def flac(tmp_path):
    sf = pytest.importorskip("soundfile")
    path = tmp_path / "Underworld - Born Slippy.flac"
    sf.write(str(path), np.zeros(4410, dtype=np.float32), 44100, format="FLAC")
    return str(path)


@pytest.fixture
def library(tmp_path):
    lib = Library(tmp_path / "library.db")
    yield lib
    lib.close()


@pytest.fixture
def panel(qtbot, flac):
    widget = MetadataPanel()
    qtbot.addWidget(widget)
    widget.set_online_lookup(True, token="tok")
    widget._load_file(flac)
    return widget


def _candidate(release_id: int = 249504) -> Candidate:
    return Candidate(
        provider="discogs",
        release_id=release_id,
        artist="Underworld",
        album="Born Slippy",
        label="Junior Boy's Own",
        country="UK",
        year=1995,
        formats=("Vinyl", '12"', "Single"),
        styles=("Techno", "Progressive House"),
        page_url=f"https://www.discogs.com/release/{release_id}",
        score=0.9,
    )


def _result(path, candidate=None) -> LookupResult:
    chosen = candidate or _candidate()
    return LookupResult(
        path=path,
        candidates=[chosen],
        chosen=chosen,
        proposed=ProposedTags(
            title="Born Slippy (Nuxx)",
            provider="discogs",
            source_url=chosen.page_url,
        ),
    )


def _apply(panel, path, candidate=None):
    """Hand the panel a result and apply it, without showing a modal."""
    class _Stub:
        def set_result(self, result):
            pass

    panel._review_dialog = _Stub()
    try:
        panel._on_lookup_result(_result(path, candidate))
    finally:
        panel._review_dialog = None
    panel._apply_lookup_values({"title": "Born Slippy (Nuxx)"})


# --- the memory -------------------------------------------------------------


def test_a_file_in_the_library_remembers_its_release(panel, flac, library):
    library.add_track(flac)
    panel.set_library(library)
    _apply(panel, flac)
    assert library.get_track_by_path(flac).discogs_release_id == 249504


def test_a_file_that_is_not_in_the_library_is_not_added_to_it(panel, flac, library):
    # The trap: a tag editor is not an importer. The apply must still work.
    panel.set_library(library)
    _apply(panel, flac)
    assert library.get_track_by_path(flac) is None
    assert library.track_count() == 0


def test_the_panel_works_with_no_library_at_all(panel, flac):
    # MainWindow hands one over, but the panel is constructed bare and every
    # test above builds it that way.
    _apply(panel, flac)
    assert panel._release_id == 249504


def test_the_memory_comes_back_when_the_file_is_loaded_again(
    qtbot, flac, library
):
    library.add_track(flac)
    library.set_release_id(library.get_track_by_path(flac).id, 249504)
    widget = MetadataPanel()
    qtbot.addWidget(widget)
    widget.set_online_lookup(True, token="tok")
    widget.set_library(library)
    widget._load_file(flac)
    assert widget._release_id == 249504


def test_another_file_does_not_inherit_the_memory(qtbot, flac, tmp_path, library):
    sf = pytest.importorskip("soundfile")
    other = tmp_path / "other.flac"
    sf.write(str(other), np.zeros(4410, dtype=np.float32), 44100, format="FLAC")
    library.add_track(flac)
    widget = MetadataPanel()
    qtbot.addWidget(widget)
    widget.set_online_lookup(True, token="tok")
    widget.set_library(library)
    widget._load_file(flac)
    _apply(widget, flac)
    widget._load_file(str(other))
    assert widget._release_id is None


# --- the tab ----------------------------------------------------------------


def test_the_tab_shows_the_release_after_a_lookup(panel, flac):
    _apply(panel, flac)
    labels = [
        panel._discogs_details.itemAt(i).widget().text()
        for i in range(panel._discogs_details.count())
    ]
    assert "Junior Boy's Own" in labels
    assert '12", Single' in labels
    assert "Techno; Progressive House" in labels


def test_a_remembered_release_gives_the_tab_something_to_say_on_load(
    qtbot, flac, library
):
    # The honest middle state: an identity is stored, no content is.
    library.add_track(flac)
    library.set_release_id(library.get_track_by_path(flac).id, 249504)
    widget = MetadataPanel()
    qtbot.addWidget(widget)
    widget.set_online_lookup(True, token="tok")
    widget.set_library(library)
    widget._load_file(flac)
    assert "249504" in widget._discogs_summary.text()
    assert not widget._discogs_refresh_btn.isHidden()
    assert widget._discogs_page_url().endswith("/249504")


def test_a_file_with_no_release_says_so_rather_than_going_blank(panel):
    assert panel._discogs_summary.text()
    assert panel._discogs_refresh_btn.isHidden()


def test_the_tab_says_when_the_feature_is_off(qtbot, flac):
    widget = MetadataPanel()
    qtbot.addWidget(widget)
    widget._load_file(flac)
    assert "Settings" in widget._discogs_summary.text()


def test_a_refresh_fills_the_tab_and_opens_no_dialog(panel, flac, monkeypatch):
    opened: list = []
    monkeypatch.setattr(
        MetadataPanel, "_show_review_dialog", lambda self, r: opened.append(r)
    )
    panel._release_id = 249504
    panel._tab_refresh = True
    panel._on_lookup_result(_result(flac))
    assert opened == []
    assert panel._discogs_summary.text() == "Born Slippy"
    # And the flag is spent, or the next real lookup is swallowed too.
    assert panel._tab_refresh is False


def test_a_failed_refresh_does_not_leave_the_flag_set(panel, flac, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    panel._tab_refresh = True
    panel._on_lookup_result(
        LookupResult(path=flac, proposed=None, error="network")
    )
    assert panel._tab_refresh is False


# --- pre-selecting the approved release -------------------------------------


def test_the_remembered_release_is_preferred_over_the_top_ranked_one():
    ranked = [_candidate(1), _candidate(249504), _candidate(3)]
    assert _preferred(ranked, 249504).release_id == 249504
    assert _preferred(ranked, None).release_id == 1
    # Not found in this search: the ranking still decides, no empty answer.
    assert _preferred(ranked, 999).release_id == 1


def test_a_lookup_asks_for_the_remembered_release(panel, flac, monkeypatch):
    jobs: list[LookupJob] = []
    monkeypatch.setattr(
        MetadataPanel, "_start_lookup", lambda self, job: jobs.append(job)
    )
    panel._release_id = 249504
    panel._on_lookup_clicked()
    assert jobs and jobs[0].prefer_release_id == 249504


# --- the already-tagged file ------------------------------------------------
#
# Reported from the running app: a file tagged from Discogs in an earlier
# session opened the review dialog on the right release, and the tab still
# said "No release known for this file yet". Two separate faults, both of
# which this file's shape makes unavoidable — every field matches, so the
# diff has nothing to offer and there is nothing to tick.


def test_the_tab_fills_in_as_soon_as_a_result_arrives(panel, flac, monkeypatch):
    # Not only when a value is written: the tab reports what Discogs knows,
    # and a review the user then cancels has still answered that.
    monkeypatch.setattr(MetadataPanel, "_show_review_dialog", lambda self, r: None)
    panel._on_lookup_result(_result(flac))
    assert panel._discogs_summary.text() == "Born Slippy"
    assert panel._discogs_page_url().endswith("/249504")


def test_approving_nothing_still_remembers_the_release(panel, flac, library):
    # The reported case exactly: nothing left to tick, Apply pressed anyway.
    library.add_track(flac)
    panel.set_library(library)
    panel._last_result = _result(flac)
    panel._apply_lookup_values({})
    assert library.get_track_by_path(flac).discogs_release_id == 249504
    assert panel._release_id == 249504


def test_approving_nothing_claims_no_write(panel, flac):
    # ...but it must not say "Applied from Discogs" over an unchanged file.
    panel._last_result = _result(flac)
    panel._apply_lookup_values({})
    assert panel._release_link.isHidden()
    assert not panel._lookup_status.text()


def test_a_cancelled_review_records_nothing(panel, flac, library, monkeypatch):
    # A review is cancelled when the match was *wrong*; remembering it would
    # seed the next lookup with the release the user just rejected. Driven
    # through the real _show_review_dialog, with only exec() replaced — a
    # test that just asserts the column is still NULL passes without a fix.
    from src.gui.widgets.dialogs.lookup_review import LookupReviewDialog

    library.add_track(flac)
    panel.set_library(library)
    monkeypatch.setattr(LookupReviewDialog, "exec", lambda self: 0)  # rejected
    panel._on_lookup_result(_result(flac))
    assert library.get_track_by_path(flac).discogs_release_id is None
    # The tab still shows what the search found — session state, not stored.
    assert panel._discogs_summary.text() == "Born Slippy"


def test_an_accepted_review_records_it_even_with_nothing_ticked(
    panel, flac, library, monkeypatch
):
    """The reported case, end to end through the real dialog.

    The file's tags already match the release, so the diff offers nothing and
    _select_none is what the user effectively pressed. Accepting still means
    "this is the right release".
    """
    from src.gui.widgets.dialogs.lookup_review import LookupReviewDialog

    library.add_track(flac)
    panel.set_library(library)

    def accept_with_nothing(self):
        self._select_none()
        return 1  # QDialog.Accepted

    monkeypatch.setattr(LookupReviewDialog, "exec", accept_with_nothing)
    panel._on_lookup_result(_result(flac))
    assert library.get_track_by_path(flac).discogs_release_id == 249504


def test_a_refresh_from_a_stored_id_alone_describes_the_release(panel, flac):
    """The reported case: stored id → Refresh → "Unknown release".

    Refresh builds a candidate from the release id and nothing else, so the
    tab is only as good as what `fetch` writes back onto it. Driven here with
    the provider stubbed the way the real one now behaves.
    """
    panel._release_id = 249504
    described = _candidate()          # what fetch fills a bare candidate with
    panel._tab_refresh = True
    panel._on_lookup_result(_result(flac, described))
    assert panel._discogs_summary.text() == "Born Slippy"
    labels = [
        panel._discogs_details.itemAt(i).widget().text()
        for i in range(panel._discogs_details.count())
    ]
    assert "Junior Boy's Own" in labels and "UK" in labels
