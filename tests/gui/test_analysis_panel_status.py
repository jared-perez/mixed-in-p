"""The Analyze table as a live view of the queue.

Three defects, all seen in one run of three tracks cancelled part-way:

* cancelling reset the un-analysed tracks to QUEUED, which the Analyze table
  filters out — so two of the three rows silently vanished. QUEUED is the
  *Rename* panel's working set (``rename_panel`` lists exactly that state), so
  the cancelled tracks had effectively been moved to another panel;
* ``TrackState.ANALYSING`` was styled, filtered and counted but never assigned,
  so nothing ever showed which file was being worked on;
* the model inherited its incremental updates from ``TrackTableModel``, whose
  ``_get_row_for_id`` indexes the *unfiltered* store while this model's
  ``rowCount``/``data`` come from the filtered list — so every emitted row
  number was wrong and the Status column only moved on a full reset.
"""

from __future__ import annotations

import pytest
from PySide6.QtTest import QSignalSpy

from src.gui.models.state import TrackState
from src.gui.models.track_model import TrackItem, TrackStore
from src.gui.widgets.analysis_panel import AnalysisTableModel

STATUS_COLUMN = 8


@pytest.fixture
def store():
    return TrackStore()


@pytest.fixture
def model(store, qtbot):
    return AnalysisTableModel(store)


def _add(store, name: str, state: TrackState) -> TrackItem:
    # Deliberately a taggable format: a .wav row is additionally flagged as
    # unable to store tags, which is test_analysis_panel_tagless's subject and
    # would mask the state label these tests are about.
    track = store.add_from_path(f"/music/{name}")
    assert track is not None
    store.update(track.id, state=state)
    return track


def _statuses(model) -> list[str]:
    return [
        model.data(model.index(r, STATUS_COLUMN)) for r in range(model.rowCount())
    ]


def test_pending_tracks_are_listed(store, model):
    """A track waiting its turn must be visible, not just the finished ones."""
    _add(store, "a.mp3", TrackState.PENDING)
    assert model.rowCount() == 1
    assert _statuses(model) == ["Pending"]


def test_status_follows_state_without_a_manual_refresh(store, model):
    """The reported symptom: Status went stale until the batch ended.

    The row set does not change here (PENDING and ANALYSING are both in the
    filter), so the view is repainted via dataChanged — and it must actually be
    emitted, and must cover the Status column.
    """
    track = _add(store, "a.mp3", TrackState.PENDING)

    changes = QSignalSpy(model.dataChanged)
    store.update(track.id, state=TrackState.ANALYSING)

    assert _statuses(model) == ["Analyzing"]
    assert changes.count() == 1, "the row was never repainted"
    top_left, bottom_right = changes.at(0)[0], changes.at(0)[1]
    assert top_left.column() <= STATUS_COLUMN <= bottom_right.column()

    store.update(track.id, state=TrackState.ANALYSED)
    assert _statuses(model) == ["Analyzed"]


def test_row_count_tracks_a_state_change_into_the_filter(store, model):
    """QUEUED is filtered out; moving to PENDING must add the row.

    Asserted on the *signal*, not on rowCount(): rowCount recomputes the filter
    on every call, so it reads correctly even when the view was never told the
    row set changed — which was the actual defect. Only a reset makes the view
    re-ask.
    """
    track = _add(store, "a.mp3", TrackState.QUEUED)
    assert model.rowCount() == 0

    resets = QSignalSpy(model.modelReset)
    store.update(track.id, state=TrackState.PENDING)

    assert model.rowCount() == 1
    assert resets.count() == 1, "view was never told the row set grew"


def test_queued_tracks_stay_out_of_the_analyze_table(store, model):
    """QUEUED belongs to the Rename panel — it must not leak in here."""
    _add(store, "rename-me.mp3", TrackState.QUEUED)
    assert model.rowCount() == 0


def test_error_state_is_shown(store, model):
    _add(store, "bad.mp3", TrackState.ERROR)
    assert _statuses(model) == ["Error"]


def test_status_labels_are_translatable(store, model):
    """They were the raw enum value, so no language could translate them.

    Also pins the spelling to the panel's own "analyzed", not the enum's
    British "analysed".
    """
    track = _add(store, "a.mp3", TrackState.ANALYSED)
    assert model.data(model.index(0, STATUS_COLUMN)) == "Analyzed"
    store.update(track.id, state=TrackState.ANALYSING)
    assert model.data(model.index(0, STATUS_COLUMN)) == "Analyzing"


def test_removal_updates_the_row_count(store, model):
    a = _add(store, "a.mp3", TrackState.PENDING)
    _add(store, "b.mp3", TrackState.PENDING)
    assert model.rowCount() == 2

    store.remove(a.id)
    assert model.rowCount() == 1


def test_batch_add_is_visible_once_the_batch_ends(store, model):
    """Adds inside a batch are signal-suppressed; the end-of-batch reset shows
    them. Without it a drop of several files listed nothing at all."""
    store.begin_batch_update()
    for name in ("a.mp3", "b.mp3", "c.mp3"):
        track = store.add_from_path(f"/music/{name}")
        store.update(track.id, state=TrackState.PENDING)
    store.end_batch_update()

    assert model.rowCount() == 3
    assert _statuses(model) == ["Pending"] * 3
