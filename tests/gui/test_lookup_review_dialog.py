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
from src.online.result import Candidate, ProposedTags, TrackQuery

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


def test_a_single_candidate_leaves_nothing_to_switch_to(qtbot):
    dialog = _dialog(qtbot, current={})
    assert not dialog._candidate_combo.isEnabled()


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
