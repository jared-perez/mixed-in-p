"""Remove All is live whenever the Rename panel holds files.

Its enablement used to hang off itemSelectionChanged alone, so the button —
born disabled — stayed dead until a row happened to be clicked. That read as
"select something before you can clear", but no such rule was ever written:
_on_remove_all ignores the selection and drops the whole QUEUED set. These
tests pin the arrival path (rows appear without the user touching the table)
and the clear itself with nothing selected.

Structure and behaviour, never pixels: the suite runs with no application
stylesheet, so a width measured here is not the width the app draws.
"""

from __future__ import annotations

import pytest

from src.gui.models import TrackState, TrackStore
from src.gui.widgets.rename_panel import RenamePanel


@pytest.fixture
def store():
    return TrackStore()


@pytest.fixture
def panel(qtbot, store):
    p = RenamePanel(store)
    qtbot.addWidget(p)
    return p


def _queue(store, tmp_path, *names: str) -> None:
    """Put files in the panel's working set the way the app does — no clicks."""
    for name in names:
        f = tmp_path / name
        f.write_bytes(b"")
        track = store.add_from_path(str(f))
        # The state change is the panel move, and its signal is what the
        # panel refreshes on.
        store.update(track.id, state=TrackState.QUEUED)


def test_disabled_while_empty(panel):
    assert not panel._remove_btn.isEnabled()


def test_enabled_when_files_arrive_untouched(panel, store, tmp_path):
    _queue(store, tmp_path, "a.wav", "b.wav")

    assert panel._preview_table.rowCount() == 2
    assert not panel._preview_table.selectedItems(), "nothing was clicked"
    assert panel._remove_btn.isEnabled()


def test_clears_everything_with_nothing_selected(panel, store, tmp_path):
    _queue(store, tmp_path, "a.wav", "b.wav")

    panel._remove_btn.click()

    assert store.get_by_state(TrackState.QUEUED) == []
    assert panel._preview_table.rowCount() == 0


def test_disabled_again_once_cleared(panel, store, tmp_path):
    _queue(store, tmp_path, "a.wav")
    panel._remove_btn.click()

    assert not panel._remove_btn.isEnabled()
