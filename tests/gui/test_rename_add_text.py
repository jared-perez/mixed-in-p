"""Prepend and Append as two independent on/off steps.

They were one mode switch with one box, so a batch could gain a prefix *or* a
suffix. Now each is its own toggle over its own box and a run can do both, which
puts three things at risk that the old mutually-exclusive pair could not get
wrong: that both operations reach _build_operations from one pass, that
switching a toggle off keeps the typed text (that is the point of a toggle
rather than a Clear), and that typing arms the toggle — before the toggles
existed, text in the box simply applied, so a box whose text did nothing until a
separate click would read as broken.

Structure and behaviour, never pixels: the suite runs with no application
stylesheet, so a width measured here is not the width the app draws.
"""

from __future__ import annotations

import pytest

from src.gui.models import TrackState, TrackStore
from src.gui.widgets.rename_panel import RenamePanel
from src.renamer import AddPrefix, AddSuffix


@pytest.fixture
def panel(qtbot, tmp_path):
    store = TrackStore()
    p = RenamePanel(store)
    qtbot.addWidget(p)
    # One queued file — QUEUED *is* the Rename panel's working set.
    f = tmp_path / "track.wav"
    f.write_bytes(b"")
    track = store.add_from_path(str(f))
    store.update(track.id, state=TrackState.QUEUED)
    p.refresh()
    return p


def _new_name(panel) -> str:
    assert panel._previews, "the fixture's queued file should preview"
    return panel._previews[0].new_name


def test_both_apply_in_one_pass(panel):
    panel._prepend_edit.setText("128 - ")
    panel._append_edit.setText(" [8A]")

    kinds = [type(op) for op in panel._operations]
    assert AddPrefix in kinds and AddSuffix in kinds
    assert _new_name(panel) == "128 - track [8A].wav"


def test_typing_arms_the_toggle(panel):
    assert not panel._prepend_btn.isChecked()
    panel._prepend_edit.setText("128 - ")
    assert panel._prepend_btn.isChecked()
    # ...and only its own.
    assert not panel._append_btn.isChecked()


def test_switching_off_keeps_the_text(panel, qtbot):
    panel._prepend_edit.setText("128 - ")
    panel._append_edit.setText(" [8A]")

    panel._prepend_btn.setChecked(False)
    panel._on_prepend_toggled()

    assert panel._prepend_edit.text() == "128 - ", "the text is kept, not cleared"
    assert [type(op) for op in panel._operations] == [AddSuffix]
    assert _new_name(panel) == "track [8A].wav"

    # Back on, from the text that was still sitting there.
    panel._prepend_btn.setChecked(True)
    panel._on_prepend_toggled()
    assert _new_name(panel) == "128 - track [8A].wav"


def test_an_off_toggle_with_text_adds_nothing(panel):
    panel._append_edit.setText(" [8A]")
    panel._append_btn.setChecked(False)
    panel._on_append_toggled()
    assert panel._operations == []
    assert _new_name(panel) == "track.wav"


def test_clear_resets_both_boxes_and_both_toggles(panel):
    panel._prepend_edit.setText("128 - ")
    panel._append_edit.setText(" [8A]")

    panel._clear_operations()

    assert panel._prepend_edit.text() == ""
    assert panel._append_edit.text() == ""
    assert not panel._prepend_btn.isChecked()
    assert not panel._append_btn.isChecked()
    assert not panel._prepend_on and not panel._append_on


def test_the_row_min_grows_with_a_longer_label(panel):
    before = panel.ops_row_min_width()
    panel._append_btn.setText("Een veel langer label voor deze knop")
    panel._append_btn.setMinimumWidth(panel._append_btn.sizeHint().width())
    assert panel.ops_row_min_width() > before


def test_the_window_minimum_is_measured_from_the_rows(panel):
    """The wiring, without standing up a whole MainWindow."""
    from types import SimpleNamespace

    from PySide6.QtCore import QSize

    from src.gui.window_sizer import WindowSizer

    window = SimpleNamespace(
        _sidebar=SimpleNamespace(width=lambda: 220),
        _rename_panel=panel,
        _header=SimpleNamespace(minimumSizeHint=lambda: QSize(0, 0)),
    )
    sizer = WindowSizer(window)

    panel._append_btn.setText("Een veel langer label voor deze knop")
    panel._append_btn.setMinimumWidth(panel._append_btn.sizeHint().width())

    assert sizer._min_width_for("rename") >= 220 + panel.ops_row_min_width()


def test_each_button_is_sized_to_its_own_label(panel):
    # Not a pixel count — the suite has no stylesheet, so the numbers here are
    # not the app's. What must hold is that the floor comes from the button's
    # own hint (i.e. its translated label) rather than from a shared constant,
    # which is what let the English pair sit wider than either word needed.
    for btn in (panel._prepend_btn, panel._append_btn):
        assert btn.minimumWidth() == btn.sizeHint().width()
