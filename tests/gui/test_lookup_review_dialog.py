"""The review dialog: what it offers, what it ticks, and what it refuses to.

The load-bearing behaviour here is the *default check state*. A dialog that
pre-ticks an overwrite of a field the user filled in is one bad match away from
destroying tags, and the whole feature's credibility with it.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QDialog

from src.gui.widgets.dialogs.lookup_review import ARTWORK_FIELD, LookupReviewDialog
from src.gui.workers.lookup_worker import LookupResult
from src.online import matching
from src.online.result import Candidate, ProposedTags, TrackEntry, TrackQuery

PROPOSED = ProposedTags(
    title="Born Slippy (Nuxx)",
    artist="Underworld",
    album="Born Slippy",
    label="Junior Boy's Own",
    genre="Techno",
    year=1995,
    track_number=1,
    provider="discogs",
)


def _result(**kwargs) -> LookupResult:
    chosen = kwargs.pop("chosen", None) or Candidate(
        release_id=1, artist="Underworld", album="Born Slippy", score=0.9
    )
    base = dict(
        path="/music/track.mp3",
        query=TrackQuery(artist="Underworld", title="Born Slippy"),
        candidates=[chosen],
        chosen=chosen,
        proposed=PROPOSED,
    )
    base.update(kwargs)
    return LookupResult(**base)


def _dialog(qtbot, current=None, result=None, **kwargs) -> LookupReviewDialog:
    dialog = LookupReviewDialog(
        file_path=current.pop("__path__", "/music/track.mp3") if current else "/music/track.mp3",
        current=current or {},
        result=result or _result(),
        **kwargs,
    )
    qtbot.addWidget(dialog)
    return dialog


def test_an_empty_field_is_ticked_and_a_filled_one_is_not(qtbot):
    dialog = _dialog(qtbot, current={"artist": "", "title": "old title"})
    assert dialog._checks["artist"].isChecked()
    assert not dialog._checks["title"].isChecked()


def test_only_ticked_fields_come_back(qtbot):
    dialog = _dialog(qtbot, current={"title": "old title", "artist": ""})
    values = dialog.selected_values()
    # The filled Title is left alone; the blank Artist (and every field the
    # file simply hasn't got) is offered.
    assert "title" not in values
    assert values["artist"] == "Underworld"


def test_a_field_that_already_matches_is_not_offered_as_a_change(qtbot):
    dialog = _dialog(qtbot, current={"album": "Born Slippy"})
    assert "album" not in dialog._checks


def test_a_numeric_field_compares_as_the_text_it_shows(qtbot):
    # The file's year reads back as an int (or a float, for BPM-adjacent
    # fields); "1995" and 1995 are the same value and not a change.
    dialog = _dialog(qtbot, current={"year": 1995})
    assert "year" not in dialog._checks


def test_select_all_is_the_one_click_for_a_deliberate_retag(qtbot):
    filled = {key: "old" for key in ("title", "artist", "album", "label", "genre")}
    filled.update({"year": 1900, "track_number": 9})
    dialog = _dialog(qtbot, current=filled)
    assert not any(c.isChecked() for c in dialog._checks.values())
    dialog._select_all()
    assert set(dialog.selected_values()) >= {"title", "artist", "genre"}
    dialog._select_none()
    assert dialog.selected_values() == {}


def test_a_weak_match_says_so_instead_of_filling_the_form_confidently(qtbot):
    weak = Candidate(release_id=9, album="Something Else", score=matching.MATCH_FLOOR - 0.2)
    dialog = _dialog(qtbot, current={}, result=_result(chosen=weak, candidates=[weak]))
    assert dialog._warning.isVisible() or not dialog._warning.isHidden()
    assert "confident" in dialog._warning.text().lower()


def test_a_strong_match_shows_no_warning(qtbot):
    dialog = _dialog(qtbot, current={})
    assert dialog._warning.isHidden()


def test_switching_release_asks_the_caller_to_fetch_it(qtbot):
    # The dialog never makes a request itself — that would be a network call on
    # the UI thread, inside a modal.
    first = Candidate(release_id=1, album="First", score=0.9)
    second = Candidate(release_id=2, album="Second", score=0.8)
    dialog = _dialog(
        qtbot, current={}, result=_result(chosen=first, candidates=[first, second])
    )
    asked: list[Candidate] = []
    dialog.candidate_requested.connect(asked.append)
    dialog._candidate_combo.setCurrentIndex(1)
    assert asked == [second]


def test_showing_a_new_result_does_not_read_as_the_user_switching(qtbot):
    # set_result repopulates the combo; unguarded, that fires the change
    # handler and asks for the release we have just been handed.
    first = Candidate(release_id=1, album="First", score=0.9)
    second = Candidate(release_id=2, album="Second", score=0.8)
    dialog = _dialog(
        qtbot, current={}, result=_result(chosen=first, candidates=[first, second])
    )
    asked: list[Candidate] = []
    dialog.candidate_requested.connect(asked.append)
    dialog.set_result(_result(chosen=second, candidates=[first, second]))
    assert asked == []
    assert dialog._candidate_combo.currentIndex() == 1


def test_the_switcher_survives_being_used(qtbot):
    """A switch is answered with a fetch of *one* release, not a new search.

    So the result that comes back carries a single-entry ``candidates`` — what
    ``LookupThread._run_job`` really returns for a job with a candidate on it —
    and rebuilding the combo from it left one row, disabled: the escape hatch
    for a wrong match worked exactly once, on both panels. The fixture above
    hands ``set_result`` the full list, which is the well-populated shape no
    caller actually produces.
    """
    first = Candidate(release_id=1, album="First", score=0.9)
    second = Candidate(release_id=2, album="Second", score=0.8)
    third = Candidate(release_id=3, album="Third", score=0.7)
    dialog = _dialog(
        qtbot, current={},
        result=_result(chosen=first, candidates=[first, second, third]),
    )
    dialog.set_result(_result(chosen=second, candidates=[second]))
    assert dialog._candidate_combo.count() == 3
    assert dialog._candidate_combo.isEnabled()
    assert dialog._candidate_combo.currentIndex() == 1
    # And it is still a way back to the first, and on to the third.
    asked: list[Candidate] = []
    dialog.candidate_requested.connect(asked.append)
    dialog._candidate_combo.setCurrentIndex(2)
    assert asked == [third]


def test_a_switch_that_failed_puts_the_combo_back_without_losing_the_others(qtbot):
    # A guard rather than a regression — this one passes against the old
    # build too, because restore_candidate() reads the *previous* result.
    # It is here so a narrower fix cannot re-collapse the combo on the way
    # back from a failed switch.
    first = Candidate(release_id=1, album="First", score=0.9)
    second = Candidate(release_id=2, album="Second", score=0.8)
    dialog = _dialog(
        qtbot, current={}, result=_result(chosen=first, candidates=[first, second])
    )
    dialog._candidate_combo.setCurrentIndex(1)
    dialog.restore_candidate()
    assert dialog._candidate_combo.count() == 2
    assert dialog._candidate_combo.currentIndex() == 0


def test_a_single_candidate_leaves_nothing_to_switch_to(qtbot):
    dialog = _dialog(qtbot, current={})
    assert not dialog._candidate_combo.isEnabled()


def test_the_switcher_says_what_it_is_for(qtbot):
    # It is the escape hatch for every wrong match in the feature, and it read
    # as a readout: no tooltip anywhere on the row, and a noun for a label.
    dialog = _dialog(qtbot, current={})
    assert dialog._candidate_combo.toolTip()
    # Structure, not pixels — the suite runs with no stylesheet. compactCombo
    # is the Convert format row's compaction, and shrinks this combo's arrow
    # to buy width a dialog row does not need.
    assert dialog._candidate_combo.objectName() != "compactCombo"


# --- the track picker (Q2) --------------------------------------------------
#
# The release switcher answers "which record is this"; this answers "which
# row of it". Nothing offered that until now: pick_track chose among twenty
# rows of a compilation with no way to say it chose wrong.


def _tracks() -> list[TrackEntry]:
    return [
        TrackEntry(position="A", title="Born Slippy", ordinal=1, number=1,
                   duration=245.0),
        TrackEntry(position="B1", title="Born Slippy (Nuxx)", ordinal=2, number=2,
                   duration=584.0),
        TrackEntry(position="B2", title="Born Slippy (Cake Mix)", ordinal=3,
                   number=3, duration=402.0),
    ]


def _with_tracks(picked: int = 1, **kwargs):
    entries = _tracks()
    chosen = Candidate(
        release_id=1,
        artist="Underworld",
        album="Born Slippy",
        score=0.9,
        track=entries[picked],
        tracklist=tuple(entries),
        **kwargs,
    )
    return _result(chosen=chosen, candidates=[chosen])


def test_a_release_with_several_rows_offers_the_one_the_matcher_picked(qtbot):
    dialog = _dialog(qtbot, current={}, result=_with_tracks(picked=1))
    assert not dialog._track_row.isHidden()
    assert dialog._track_combo.count() == 3
    # Pre-selected on pick_track's answer: this is an override, not a
    # replacement for the automatic choice.
    assert dialog._track_combo.currentIndex() == 1
    assert "Born Slippy (Nuxx)" in dialog._track_combo.currentText()


def test_a_single_row_release_does_not_grow_a_pointless_dropdown(qtbot):
    only = TrackEntry(position="A", title="Acid Tracks", ordinal=1, number=1)
    chosen = Candidate(release_id=1, track=only, tracklist=(only,), score=0.9)
    dialog = _dialog(qtbot, current={}, result=_result(chosen=chosen,
                                                       candidates=[chosen]))
    assert dialog._track_row.isHidden()


def test_choosing_another_row_re_derives_the_track_fields(qtbot):
    dialog = _dialog(qtbot, current={}, result=_with_tracks(picked=1))
    dialog._track_combo.setCurrentIndex(2)
    # The diff moved, not just the label: every tick is per-field and three of
    # those rows have new values on both sides.
    assert dialog._proposed_labels["title"].text() == "Born Slippy (Cake Mix)"
    assert dialog.selected_values()["title"] == "Born Slippy (Cake Mix)"
    assert dialog.selected_values()["track_number"] == 3


def test_the_release_fields_do_not_move_with_the_track(qtbot):
    dialog = _dialog(qtbot, current={}, result=_with_tracks(picked=1))
    dialog._track_combo.setCurrentIndex(2)
    values = dialog.selected_values()
    # Album, label, genre and year belong to the release, whichever row the
    # file turns out to be.
    assert values["album"] == "Born Slippy"
    assert values["label"] == "Junior Boy's Own"
    assert values["year"] == 1995


def test_choosing_another_row_asks_for_nothing_over_the_network(qtbot):
    # The tracklist is already downloaded; a track override is not a candidate
    # switch and must not be mistaken for one.
    dialog = _dialog(qtbot, current={}, result=_with_tracks(picked=1))
    asked: list[Candidate] = []
    dialog.candidate_requested.connect(asked.append)
    dialog._track_combo.setCurrentIndex(0)
    assert asked == []


def test_a_compilation_row_credits_the_track_artist(qtbot):
    entries = [
        TrackEntry(position="1-1", title="Sunrise", artist="M People", ordinal=1,
                   number=1),
        TrackEntry(position="1-2", title="Papua New Guinea",
                   artist="The Future Sound Of London", ordinal=2, number=2),
    ]
    chosen = Candidate(release_id=1, artist="Various", album="Renaissance",
                       score=0.9, track=entries[0], tracklist=tuple(entries))
    dialog = _dialog(qtbot, current={}, result=_result(chosen=chosen,
                                                       candidates=[chosen]))
    dialog._track_combo.setCurrentIndex(1)
    # Never "Various": the row's own credit is the artist on a compilation.
    assert dialog.selected_values()["artist"] == "The Future Sound Of London"


def test_showing_a_new_result_repopulates_the_rows(qtbot):
    # A candidate switch brings a different release, so its tracklist replaces
    # this one's rather than being appended to it.
    dialog = _dialog(qtbot, current={}, result=_with_tracks(picked=1))
    only = TrackEntry(position="A", title="Acid Tracks", ordinal=1, number=1)
    other = Candidate(release_id=2, track=only, tracklist=(only,), score=0.8)
    dialog.set_result(_result(chosen=other, candidates=[other]))
    assert dialog._track_combo.count() == 1
    assert dialog._track_row.isHidden()


def test_a_wav_says_its_tags_will_not_stick(qtbot):
    # Lookup is still allowed — reading the values is useful — the same posture
    # the Analyze panel takes.
    dialog = LookupReviewDialog(
        file_path="/music/track.wav", current={}, result=_result()
    )
    qtbot.addWidget(dialog)
    assert not dialog._tagless_label.isHidden()


def test_a_taggable_file_gets_no_such_warning(qtbot):
    dialog = _dialog(qtbot, current={})
    assert dialog._tagless_label.isHidden()


def test_artwork_is_previewed_and_starts_unticked_over_existing_art(qtbot):
    png = _png_bytes()
    dialog = _dialog(
        qtbot,
        current={ARTWORK_FIELD: png},
        result=_result(artwork=png),
    )
    assert not dialog._art_row.isHidden()
    assert not dialog._art_check.isChecked()
    assert ARTWORK_FIELD not in dialog.selected_values()


def test_artwork_starts_ticked_when_the_file_has_none(qtbot):
    png = _png_bytes()
    dialog = _dialog(qtbot, current={}, result=_result(artwork=png))
    assert dialog._art_check.isChecked()
    assert dialog.selected_values()[ARTWORK_FIELD] == png


def test_artwork_is_absent_when_the_setting_that_fetches_it_is_off(qtbot):
    dialog = _dialog(
        qtbot, current={}, result=_result(artwork=_png_bytes()), allow_artwork=False
    )
    assert dialog._art_row.isHidden()


def test_a_result_with_nothing_new_still_opens_and_offers_nothing(qtbot):
    current = {
        "title": PROPOSED.title,
        "artist": PROPOSED.artist,
        "album": PROPOSED.album,
        "label": PROPOSED.label,
        "genre": PROPOSED.genre,
        "year": PROPOSED.year,
        "track_number": PROPOSED.track_number,
    }
    dialog = _dialog(qtbot, current=current)
    assert dialog._checks == {}
    assert dialog.selected_values() == {}
    assert not dialog._apply_btn.isEnabled()


def _png_bytes() -> bytes:
    """A 1x1 PNG — enough for QPixmap.loadFromData to succeed."""
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
        "IQAAAABJRU5ErkJggg=="
    )


def test_the_dialog_is_wide_enough_for_its_own_buttons(qtbot):
    """A width written as a constant is an English width.

    "Select None" is eleven characters; "Снять выделение" is fifteen, and batch
    mode adds a fifth button — which is where this first bit, with the row
    overlapping the attribution. Asserted against the buttons' own minimums
    rather than a pixel count, because the suite runs with no stylesheet and so
    measures a different app than the one that ships.
    """
    dialog = _dialog(
        qtbot, current={}, result=_result(chosen=_batch_candidate()), position=(3, 12)
    )
    row = [
        dialog._all_btn,
        dialog._none_btn,
        dialog._stop_btn,
        dialog._cancel_btn,
        dialog._apply_btn,
    ]
    assert all(b is not None for b in row)  # batch mode has all five
    needed = sum(b.minimumWidth() for b in row)
    assert dialog.minimumWidth() >= needed


def test_a_single_file_review_has_no_skip_or_stop(qtbot):
    dialog = _dialog(qtbot, current={})
    assert dialog._stop_btn is None
    assert "Cancel" in dialog._cancel_btn.text()


def _batch_candidate() -> Candidate:
    return Candidate(release_id=1, artist="Underworld", album="Born Slippy", score=0.9)


def test_both_surfaces_credit_discogs_with_the_same_words(qtbot):
    """The attribution is one constant, shown in the review dialog and About.

    Not translated, and not spelled out twice: the API terms ask for the credit
    wherever the data appears, and two copies of a required string are two
    strings that can drift.
    """
    from src.gui.widgets.dialogs.about_dialog import AboutDialog
    from src.online import discogs

    dialog = _dialog(qtbot, current={})
    assert any(
        w.text() == discogs.ATTRIBUTION
        for w in dialog.findChildren(type(dialog._warning))
    )

    # In About it rides inside the "The Rest of the Kit" slide's rich text,
    # directly under the Discogs blurb, so it is a substring rather than the
    # whole label — but still the same constant, which is the point here.
    about = AboutDialog()
    qtbot.addWidget(about)
    assert any(
        discogs.ATTRIBUTION in w.text()
        for w in about.findChildren(type(dialog._warning))
    )


# --- artwork-only mode (D5, "Find Cover Online") -----------------------------
#
# The same dialog with the field rows suppressed. A mode rather than a default
# check-state, because the ticks default to *empty* fields: "art only" is
# genuinely unreachable by ticking, so a default would leave the user one
# stray tick away from a retag they never asked for.


def _art_bytes() -> bytes:
    from PySide6.QtCore import QBuffer
    from PySide6.QtGui import QColor, QPixmap

    pixmap = QPixmap(8, 8)
    pixmap.fill(QColor("red"))
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")
    return bytes(buffer.data())


def test_artwork_only_offers_the_cover_and_no_fields(qtbot):
    dialog = _dialog(
        qtbot, current={}, result=_result(artwork=_art_bytes()), artwork_only=True
    )
    # Not one tickable field, on a file with nothing filled in — which in the
    # ordinary mode would tick every one of them.
    assert dialog._checks == {}
    assert dialog._diff_scroll.isHidden()
    assert not dialog._art_row.isHidden()
    assert set(dialog.selected_values()) == {ARTWORK_FIELD}


def test_artwork_only_replaces_a_cover_the_file_already_has(qtbot):
    # The standing rule is "never replace art silently". Pressing a button
    # named Find Cover Online over a file that has one is a request to change
    # it, and both covers are on screen side by side — so the tick starts on,
    # or Apply would answer by doing nothing at all.
    dialog = _dialog(
        qtbot,
        current={ARTWORK_FIELD: _art_bytes()},
        result=_result(artwork=_art_bytes()),
        artwork_only=True,
    )
    assert dialog._art_check.isChecked()
    assert dialog._apply_btn.isEnabled()


def test_the_ordinary_mode_still_never_replaces_a_cover_silently(qtbot):
    dialog = _dialog(
        qtbot, current={ARTWORK_FIELD: _art_bytes()}, result=_result(artwork=_art_bytes())
    )
    assert not dialog._art_check.isChecked()


def test_a_release_with_no_cover_says_so_and_offers_nothing_to_apply(qtbot):
    # The ordinary way this search comes back empty. Without the sentence the
    # dialog is a blank frame over a dead Apply, which reads as broken rather
    # than as an answer — and the answer has a next step: another pressing.
    dialog = _dialog(qtbot, current={}, result=_result(), artwork_only=True)
    assert dialog._art_row.isHidden()
    assert not dialog._warning.isHidden()
    assert "cover" in dialog._warning.text().lower()
    assert not dialog._apply_btn.isEnabled()


def test_artwork_only_keeps_the_release_switcher(qtbot):
    # It is the whole interaction: a cover is per release, so picking another
    # pressing is the only way to get a different one.
    first = Candidate(release_id=1, album="First", score=0.9)
    second = Candidate(release_id=2, album="Second", score=0.8)
    dialog = _dialog(
        qtbot,
        current={},
        result=_result(chosen=first, candidates=[first, second],
                       artwork=_art_bytes()),
        artwork_only=True,
    )
    assert dialog._candidate_combo.isEnabled()
    asked: list[Candidate] = []
    dialog.candidate_requested.connect(asked.append)
    dialog._candidate_combo.setCurrentIndex(1)
    assert asked == [second]


def test_artwork_only_drops_the_track_picker(qtbot):
    # Artwork belongs to the release, so choosing a row would move nothing on
    # screen — a control that cannot change the answer it is asked about.
    result = _with_tracks(picked=1)
    result.artwork = _art_bytes()
    dialog = _dialog(qtbot, current={}, result=result, artwork_only=True)
    assert dialog._track_row.isHidden()


def test_artwork_only_drops_select_all_and_select_none(qtbot):
    dialog = _dialog(
        qtbot, current={}, result=_result(artwork=_art_bytes()), artwork_only=True
    )
    assert dialog._all_btn is None and dialog._none_btn is None
    # And the ordinary mode still has them.
    other = _dialog(qtbot, current={}, result=_result())
    assert other._all_btn is not None


def test_artwork_only_says_what_it_is_for_in_its_own_words(qtbot):
    dialog = _dialog(
        qtbot, current={}, result=_result(artwork=_art_bytes()), artwork_only=True
    )
    assert dialog.artwork_only
    assert "cover" in dialog.windowTitle().lower()


def test_a_cover_with_no_field_changes_can_still_be_applied(qtbot):
    """Not artwork-only — the shipped ordinary mode had this wrong.

    ``_fill_rows`` syncs Apply *before* ``_fill_artwork`` has drawn the cover
    row, so on the first pass it read the hidden row ``_setup_ui`` built. A
    result offering a sleeve and no field changes — every tag already matching
    the release, i.e. any file tagged from Discogs in an earlier session —
    left Apply disabled over a cover the user could plainly see.
    """
    matching_tags = {
        "title": PROPOSED.title,
        "artist": PROPOSED.artist,
        "album": PROPOSED.album,
        "label": PROPOSED.label,
        "genre": PROPOSED.genre,
        "year": PROPOSED.year,
        "track_number": PROPOSED.track_number,
    }
    dialog = _dialog(qtbot, current=matching_tags, result=_result(artwork=_art_bytes()))
    assert dialog._checks == {}
    assert not dialog._art_row.isHidden()
    assert dialog._apply_btn.isEnabled()
