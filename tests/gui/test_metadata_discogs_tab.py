"""The Metadata panel's Discogs tab, and the release memory behind it.

Two rules carry this feature, and both are easy to break silently:

* **A file dropped here need not be in the library, and the panel must not
  put it there.** Calling `add_track` from a tag editor would quietly turn it
  into a library importer.
* **The identity and the description are stored separately.** `tracks`
  (or `discogs_path_releases`) holds which release the file was tagged from;
  `discogs_releases` holds what the provider said about it, stamped with when
  it was read, which is the one place fetched content outlives its request.
  Refresh replaces that row wholesale.
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


def _sections(panel) -> dict[str, dict[str, str]]:
    """The tab's headed blocks, as {heading: {label: value}}.

    Walks the scrolling body rather than one form, because the tab is a column
    of sections now — a heading label followed by the QFormLayout it heads.
    """
    from PySide6.QtWidgets import QFormLayout, QLabel

    body = panel._discogs_body
    out: dict[str, dict[str, str]] = {}
    heading = ""
    for i in range(body.count()):
        item = body.itemAt(i)
        widget = item.widget()
        if isinstance(widget, QLabel):
            heading = widget.text()
            out.setdefault(heading, {})
            continue
        form = item.layout()
        if isinstance(form, QFormLayout):
            rows = out.setdefault(heading, {})
            for row in range(form.rowCount()):
                key = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
                value = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
                if key is not None and value is not None:
                    rows[key.widget().text()] = _value_text(value.widget())
    return out


def _value_text(holder) -> str:
    """The text out of a value cell, which wraps its label with an arrow button."""
    from PySide6.QtWidgets import QLabel

    if isinstance(holder, QLabel):
        return holder.text()
    label = holder.findChild(QLabel)
    return label.text() if label is not None else ""


def _apply_buttons(panel) -> dict[str, object]:
    """Every row's arrow button, keyed by the row label that carries it."""
    from PySide6.QtWidgets import QFormLayout, QPushButton

    body = panel._discogs_body
    out: dict[str, object] = {}
    for i in range(body.count()):
        form = body.itemAt(i).layout()
        if not isinstance(form, QFormLayout):
            continue
        for row in range(form.rowCount()):
            key = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
            value = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
            if key is None or value is None:
                continue
            button = value.widget().findChild(QPushButton)
            if button is not None:
                out[key.widget().text()] = button
    return out


def _all_values(panel) -> list[str]:
    return [v for rows in _sections(panel).values() for v in rows.values()]


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
    sections = _sections(panel)

    assert sections["Release"]["Label"] == "Junior Boy's Own"
    assert sections["Pressing"]["Format"] == '12", Single'
    assert sections["Release"]["Styles"] == "Techno; Progressive House"


def test_the_title_and_artist_are_the_heading_not_a_row(panel, flac):
    """They were the tab's one visible duplication: printed once above the
    table and again as its first row."""
    _apply(panel, flac)

    assert panel._discogs_summary.text() == "Born Slippy"
    assert panel._discogs_subtitle.text() == "Underworld"
    assert "Born Slippy" not in _all_values(panel)


def test_year_and_released_are_kept_apart(panel, flac):
    """They are different facts that can legitimately disagree — the year
    prefers the master's — so under one heading they read as a contradiction."""
    described = _candidate()
    described.released = "1996-05-13"
    _apply(panel, flac, described)
    sections = _sections(panel)

    assert "Year" in sections["Release"]
    assert sections["Pressing"]["Released"] == "1996-05-13"


def test_an_empty_section_is_left_out_entirely(panel, flac):
    """Worse than a missing one: it says Discogs holds this kind of
    information about the record and then shows none of it."""
    _apply(panel, flac)  # the plain fixture has no notes and no identifiers

    assert "Notes" not in _sections(panel)
    assert "Identifiers" not in _sections(panel)


def test_every_value_can_be_selected_and_copied(panel, flac):
    """The reason to look at a catalogue number or a runout is to paste it."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QFormLayout

    from PySide6.QtWidgets import QLabel

    _apply(panel, flac)
    body = panel._discogs_body
    checked = 0
    for i in range(body.count()):
        form = body.itemAt(i).layout()
        if not isinstance(form, QFormLayout):
            continue
        for row in range(form.rowCount()):
            holder = form.itemAt(row, QFormLayout.ItemRole.FieldRole).widget()
            value = holder if isinstance(holder, QLabel) else holder.findChild(QLabel)
            assert (
                value.textInteractionFlags()
                & Qt.TextInteractionFlag.TextSelectableByMouse
            )
            checked += 1
    assert checked


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
        MetadataPanel, "_show_review_dialog", lambda self, r, **kw: opened.append(r)
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
    monkeypatch.setattr(MetadataPanel, "_show_review_dialog", lambda self, r, **kw: None)
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
    values = _all_values(panel)
    assert "Junior Boy's Own" in values and "UK" in values


# --- v7: the description, not just the identity -----------------------------
#
# The complaint this answers: a file that had been looked up came back to a tab
# saying "No release known for this file yet. Look it up online." The identity
# was stored and the description was not, so the most the tab could ever offer
# a known release was its number.


def test_the_tab_describes_the_release_on_load_with_no_lookup(
    qtbot, flac, library
):
    """The headline: open a file, see the release, spend no request."""
    first = MetadataPanel()
    qtbot.addWidget(first)
    first.set_online_lookup(True, token="tok")
    first.set_library(library)
    first._load_file(flac)
    _apply(first, flac)

    # A different panel, a fresh session: nothing in memory, only the database.
    second = MetadataPanel()
    qtbot.addWidget(second)
    second.set_online_lookup(True, token="tok")
    second.set_library(library)
    second._load_file(flac)

    assert second._discogs_summary.text() == "Born Slippy"
    sections = _sections(second)
    assert "Label" in sections["Release"]
    assert "Year" in sections["Release"]
    assert "Country" in sections["Pressing"]


def test_a_dropped_file_remembers_its_release_without_joining_the_library(
    panel, flac, library
):
    """Bug 2. The panel must still not import it — both halves matter."""
    panel.set_library(library)
    _apply(panel, flac)

    assert library.track_count() == 0
    assert library.release_for_path(flac) == 249504


def test_a_release_known_but_never_described_still_says_so(panel, flac, library):
    """A release remembered by a build older than the cache. Not an error —
    show the identity, which is all there is."""
    library.remember_release_for_path(flac, 999)
    panel.set_library(library)
    panel._load_file(flac)

    assert "999" in panel._discogs_summary.text()
    assert _sections(panel) == {}


def test_ejecting_and_reloading_keeps_the_description(panel, flac, library):
    """`_clear` drops the session result on purpose — a new file must not wear
    the last one's release. Reloading the *same* file has to get it back from
    the database, not from what the panel happened to still be holding."""
    panel.set_library(library)
    _apply(panel, flac)
    panel._clear()
    assert panel._discogs_summary.text() != "Born Slippy"  # genuinely dropped

    panel._load_file(flac)

    assert panel._discogs_summary.text() == "Born Slippy"
    assert panel._discogs_page_url() == "https://www.discogs.com/release/249504"


def test_ejecting_takes_the_release_with_the_file(panel, flac, library):
    """`_clear` never reset the release id, so an empty panel went on
    reporting the ejected file's release."""
    panel.set_library(library)
    _apply(panel, flac)
    panel._clear()

    assert panel._release_id is None
    assert "Born Slippy" not in panel._discogs_summary.text()


def test_notes_are_a_paragraph_not_a_field(panel, flac):
    """A one-row form with a blank label indents the text to the label column
    and leaves a rectangle of nothing beside it."""
    from PySide6.QtWidgets import QFormLayout, QLabel

    described = _candidate()
    described.notes = "Comes in a printed inner sleeve."
    _apply(panel, flac, described)

    body = panel._discogs_body
    texts = [
        body.itemAt(i).widget().text()
        for i in range(body.count())
        if isinstance(body.itemAt(i).widget(), QLabel)
    ]
    # Straight onto the column, as its own widget — not inside any form.
    assert "Comes in a printed inner sleeve." in texts
    in_forms = [
        body.itemAt(i).layout()
        for i in range(body.count())
        if isinstance(body.itemAt(i).layout(), QFormLayout)
    ]
    assert all(
        _value_text(form.itemAt(r, QFormLayout.ItemRole.FieldRole).widget())
        != "Comes in a printed inner sleeve."
        for form in in_forms
        for r in range(form.rowCount())
    )


def test_credits_are_grouped_by_role(panel, flac):
    """Three people credited Written-By is one row, not the word three times."""
    from src.online.result import Credit

    described = _candidate()
    described.credits = (
        Credit("Karl Hyde", "Written-By"),
        Credit("Rick Smith", "Written-By"),
        Credit("Rick Smith", "Producer"),
    )
    _apply(panel, flac, described)

    assert _sections(panel)["Credits"]["Written-By"] == "Karl Hyde, Rick Smith"


def test_the_label_column_is_measured_not_a_constant(panel, flac):
    """These strings are translated: a number that fits "Catalogue Number"
    says nothing about "Katalognummer"."""
    from PySide6.QtGui import QFontMetrics

    _apply(panel, flac)
    widths = {key.minimumWidth() for key, _ in panel._discogs_keys}
    assert len(widths) == 1  # one shared column across every aligned section

    widest = max(
        QFontMetrics(key.font()).horizontalAdvance(text)
        for key, text in panel._discogs_keys
    )
    assert widths == {widest}


def test_the_tracklist_keeps_out_of_that_column(panel, flac):
    """A position is data, not a field name — stretching "A1" to the width of
    "Catalogue Number" puts 150px of nothing between a track and its number."""
    _apply(panel, flac)
    assert "A1" not in [text for _key, text in panel._discogs_keys]


# --- putting what it shows into the file ------------------------------------


def test_the_arrow_writes_the_value_to_its_tag(panel, flac):
    from src.metadata.tags import read_metadata

    _apply(panel, flac)
    _apply_buttons(panel)["Label"].click()

    assert read_metadata(flac).label == "Junior Boy's Own"


def test_the_form_shows_it_without_a_reload(panel, flac):
    """The panel reloads from disk rather than trusting what it wrote."""
    _apply(panel, flac)
    _apply_buttons(panel)["Label"].click()

    assert panel._field_edits["label"].text() == "Junior Boy's Own"


def test_a_value_the_file_already_has_offers_a_disabled_button(panel, flac):
    """Which rows are *available* to apply is worth seeing at a glance, and a
    button that comes and goes as tags change is harder to read than one that
    greys out."""
    _apply(panel, flac)
    assert _apply_buttons(panel)["Label"].isEnabled()

    _apply_buttons(panel)["Label"].click()

    button = _apply_buttons(panel)["Label"]
    assert not button.isEnabled()
    assert "Already" in button.toolTip()


def test_the_genre_arrow_writes_styles_not_the_coarse_genre(panel, flac):
    """"Electronic" is not a genre a DJ sorts by; "Techno" is. The arrow sits
    on Styles for that reason, and writes what the lookup would."""
    from src.metadata.tags import read_metadata

    _apply(panel, flac)
    _apply_buttons(panel)["Styles"].click()

    assert read_metadata(flac).genre == "Techno; Progressive House"


def test_genres_is_reference_only(panel, flac):
    assert "Genres" not in _apply_buttons(_applied(panel, flac))


def _applied(panel, flac):
    _apply(panel, flac)
    return panel


def test_a_row_with_no_tag_of_its_own_has_no_arrow(panel, flac):
    """Country and Catalogue Number have nowhere to go in an ID3 frame."""
    _apply(panel, flac)
    buttons = _apply_buttons(panel)

    assert "Country" not in buttons
    assert "Catalogue Number" not in buttons


def test_a_tracklist_row_writes_the_title_and_the_number_together(panel, flac):
    """A title written without its number leaves the file claiming to be track
    1 of a twelve-track compilation."""
    from src.metadata.tags import read_metadata
    from src.online.result import TrackEntry

    described = _candidate()
    described.tracklist = (
        TrackEntry(position="A1", title="Born Slippy (Nuxx) (Extended Mix)",
                   ordinal=1, number=1),
        TrackEntry(position="B1", title="Born Slippy (Nuxx) (Radio Edit)",
                   ordinal=2, number=2),
    )
    _apply(panel, flac, described)
    _apply_buttons(panel)["B1"].click()

    meta = read_metadata(flac)
    assert meta.title == "Born Slippy (Nuxx) (Radio Edit)"
    assert meta.track_number == 2


def test_the_heading_keeps_its_buttons(panel, flac):
    """Moving the album and artist out of the table to stop the duplication
    must not cost them the two arrows most worth having."""
    from src.metadata.tags import read_metadata

    _apply(panel, flac)
    assert panel._album_apply_btn.isVisible() or not panel.isVisible()

    panel._album_apply_btn.click()
    panel._artist_apply_btn.click()

    meta = read_metadata(flac)
    assert meta.album == "Born Slippy"
    assert meta.artist == "Underworld"


def test_the_heading_button_is_rewired_not_re_connected(
    panel, flac, tmp_path, monkeypatch
):
    """It is built once and survives every redraw, so an accumulated
    connection fires once per past redraw.

    Counted, not asserted on the result: with the leak the last connection
    still wins, so the file ends up correct and only the *extra* write —
    of the release we were looking at two files ago — gives it away.
    """
    import numpy as np

    from src.gui import lookup_flow

    sf = pytest.importorskip("soundfile")
    other = tmp_path / "Another - Track.flac"
    sf.write(str(other), np.zeros(4410, dtype=np.float32), 44100, format="FLAC")

    _apply(panel, flac)
    second = _candidate(release_id=888)
    second.album = "A Different Record"
    panel._load_file(str(other))
    _apply(panel, str(other), second)

    calls: list[dict] = []
    real = lookup_flow.apply_values
    monkeypatch.setattr(
        lookup_flow,
        "apply_values",
        lambda path, values: calls.append(dict(values)) or real(path, values),
    )
    panel._album_apply_btn.click()

    assert calls == [{"album": "A Different Record"}]


def test_nothing_is_offered_on_a_release_we_only_know_the_id_of(panel, flac, library):
    library.remember_release_for_path(flac, 999)
    panel.set_library(library)
    panel._load_file(flac)

    assert _apply_buttons(panel) == {}
    assert panel._album_apply_btn.isHidden()
