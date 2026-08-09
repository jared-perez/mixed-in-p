"""Flagging files that cannot hold the tags analysis produces.

A WAV has no slot for BPM or key, and the write layer does not say so: it
returns True and discards the value. So an analysed WAV looked exactly like an
analysed MP3 while none of the detected data had been kept. The panel now says
which rows those are, up front and again once analysed — and analysis is still
allowed, because the BPM/key readout and the rename are useful on their own.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from src.gui.models.state import TrackState
from src.gui.models.track_model import TrackStore
from src.gui.widgets.analysis_panel import AnalysisTableModel
from src.metadata import stores_tags

STATUS_COLUMN = 8
NAME_COLUMN = 0


@pytest.fixture
def store():
    return TrackStore()


@pytest.fixture
def model(store, qtbot):
    return AnalysisTableModel(store)


def _add(store, name: str, state: TrackState):
    track = store.add_from_path(f"/music/{name}")
    store.update(track.id, state=state)
    return track


def test_only_wav_is_treated_as_tagless():
    """Verified by round-trip: WAV drops BPM/key, the others keep them."""
    assert not stores_tags("/music/a.wav")
    assert not stores_tags("/music/UPPER.WAV")
    for keeps in ("a.mp3", "a.flac", "a.aiff", "a.aif", "a.m4a", "a.ogg"):
        assert stores_tags(f"/music/{keeps}"), keeps


def test_wav_is_announced_before_it_runs(store, model):
    """Named at the point the user can still decide it isn't worth analysing."""
    _add(store, "loop.wav", TrackState.PENDING)
    assert model.data(model.index(0, STATUS_COLUMN)) == "WAV file"


def test_wav_is_flagged_again_once_analysed(store, model):
    """The moment the limitation bites: the tags silently went nowhere."""
    _add(store, "loop.wav", TrackState.ANALYSED)
    assert model.data(model.index(0, STATUS_COLUMN)) == "Analyzed, no tags"


def test_live_state_still_wins_mid_run(store, model):
    """While it is actually running, the state matters more than the caveat —
    the row tint carries that."""
    _add(store, "loop.wav", TrackState.ANALYSING)
    assert model.data(model.index(0, STATUS_COLUMN)) == "Analyzing"


def test_taggable_formats_are_unchanged(store, model):
    _add(store, "track.mp3", TrackState.PENDING)
    assert model.data(model.index(0, STATUS_COLUMN)) == "Pending"
    store.update(store.get_all()[0].id, state=TrackState.ANALYSED)
    assert model.data(model.index(0, STATUS_COLUMN)) == "Analyzed"


def test_the_row_is_tinted(store, model):
    _add(store, "loop.wav", TrackState.PENDING)
    _add(store, "track.mp3", TrackState.PENDING)

    wav_bg = model.data(model.index(0, NAME_COLUMN), Qt.ItemDataRole.BackgroundRole)
    mp3_bg = model.data(model.index(1, NAME_COLUMN), Qt.ItemDataRole.BackgroundRole)

    assert wav_bg is not None, "WAV row is not highlighted"
    assert mp3_bg is None, "a taggable row should not be tinted"
    assert wav_bg.alpha() < 255, "tint must be translucent so selection still reads"


def test_tint_covers_every_column(store, model):
    """It is a row highlight, not a cell one."""
    _add(store, "loop.wav", TrackState.PENDING)
    for column in range(len(model.COLUMN_KEYS)):
        bg = model.data(model.index(0, column), Qt.ItemDataRole.BackgroundRole)
        assert bg is not None, f"column {column} not tinted"


def test_tooltip_explains_and_reaches_the_whole_row(store, model):
    _add(store, "loop.wav", TrackState.PENDING)
    for column in range(len(model.COLUMN_KEYS)):
        tip = model.data(model.index(0, column), Qt.ItemDataRole.ToolTipRole)
        assert tip, f"column {column} has no tooltip"
        assert "WAV" in tip and "filename" in tip


def test_taggable_rows_have_no_such_tooltip(store, model):
    _add(store, "track.mp3", TrackState.PENDING)
    tip = model.data(model.index(0, NAME_COLUMN), Qt.ItemDataRole.ToolTipRole)
    assert not tip


def test_the_tint_is_actually_painted(qtbot):
    """Returning a brush from data() is not enough, and looks like it is.

    app.qss.template has a QTableView::item rule, and once a stylesheet targets
    items Qt paints their background itself and ignores the model's
    BackgroundRole — so the highlight was drawing nothing at all while every
    data()-level assertion passed. _NoFocusDelegate paints it. Sampled from a
    render, because that is the only place the difference exists.
    """
    from PySide6.QtWidgets import QApplication
    from src.gui.app import load_stylesheet
    from src.gui.widgets.analysis_panel import AnalysisPanel

    QApplication.instance().setStyleSheet(load_stylesheet())
    store = TrackStore()
    for name in ("loop.wav", "track.mp3"):
        t = store.add_from_path(f"/music/{name}")
        store.update(t.id, state=TrackState.PENDING)

    panel = AnalysisPanel(store)
    qtbot.addWidget(panel)
    panel.resize(1100, 300)
    panel.show()
    qtbot.waitExposed(panel)

    table = panel._table
    shot = table.viewport().grab().toImage()

    def sample(row):
        y = table.rowViewportPosition(row) + table.rowHeight(row) // 2
        # Well inside the first column, clear of any text glyphs.
        return shot.pixelColor(table.columnViewportPosition(0) + 6, y)

    wav, mp3 = sample(0), sample(1)
    assert wav != mp3, "the WAV row is painted identically to a taggable row"
    # The tint is yellow: it must lift red and green above the plain row.
    assert wav.red() > mp3.red() and wav.green() > mp3.green()


def test_alt_keys_tooltip_still_wins_on_its_own_column(store, model):
    """The WAV tooltip must not shadow the runner-up keys explanation."""
    track = _add(store, "loop.wav", TrackState.ANALYSED)
    store.update(track.id, key_alternatives=[
        {"key": "Am", "keycode": "8A", "confidence": 0.62},
    ])
    tip = model.data(model.index(0, 6), Qt.ItemDataRole.ToolTipRole)
    assert "8A" in tip
