"""Selection -> data mapping in the History panel's Rename Sessions table.

_get_selected_session() maps a *visual row index* straight into self._sessions.
That holds only while the table is unsorted. Undoing the wrong session renames
real files on disk, so the failure mode is destructive and silent.

See spitball/2026-07-21-history-export-and-sorting-plan.md, section 3d.
"""

import pytest
from PySide6.QtCore import Qt

from src.gui.widgets import history_panel as hp
from src.renamer import RenameRecord, RenameSession

SESSION_ID, DATE, FILES, DESCRIPTION = range(4)


def make_session(session_id, timestamp, filename):
    return RenameSession(
        session_id=session_id,
        timestamp=timestamp,
        description="Renamed 1 files",
        records=[
            RenameRecord(
                original_path=f"/music/{filename}",
                new_path=f"/music/renamed-{filename}",
                timestamp=timestamp,
            )
        ],
    )


# list_sessions() returns newest first, so IDs are deliberately NOT in
# alphabetical order — sorting by Session ID must move rows away from their
# list positions.
SESSIONS = [
    make_session("ccc11111", "2026-07-21T10:00:00", "newest.aiff"),
    make_session("aaa22222", "2026-07-10T10:00:00", "middle.aiff"),
    make_session("bbb33333", "2026-07-01T10:00:00", "oldest.aiff"),
]


@pytest.fixture
def panel(qtbot, monkeypatch):
    monkeypatch.setattr(hp, "list_sessions", lambda limit=50: list(SESSIONS))
    monkeypatch.setattr(hp, "load_analysis_entries", lambda: [])
    widget = hp.HistoryPanel()
    qtbot.addWidget(widget)
    widget.refresh()
    return widget


class TestSelectionMappingUnsorted:
    """Current shipping behaviour: correct, because sorting is disabled."""

    def test_each_row_returns_its_own_session(self, panel):
        for row in range(panel._table.rowCount()):
            panel._table.selectRow(row)
            displayed = panel._table.item(row, SESSION_ID).text()
            assert panel._get_selected_session().session_id == displayed

    def test_no_selection_returns_none(self, panel):
        panel._table.clearSelection()
        assert panel._get_selected_session() is None


class TestUndoSignal:
    """The Undo button must emit the session the user actually selected."""

    def test_emits_selected_session(self, qtbot, panel):
        panel._table.selectRow(1)
        with qtbot.waitSignal(panel.undo_session, timeout=1000) as blocker:
            panel._undo_btn.click()
        assert blocker.args[0].session_id == "aaa22222"

    def test_button_disabled_without_selection(self, panel):
        panel._table.clearSelection()
        assert not panel._undo_btn.isEnabled()
        assert not panel._delete_btn.isEnabled()

    def test_button_enabled_with_selection(self, panel):
        panel._table.selectRow(0)
        assert panel._undo_btn.isEnabled()
        assert panel._delete_btn.isEnabled()


class TestSelectionMappingSorted:
    """Latent bug: the mapping breaks the moment the table is sorted."""

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Known bug (plan item 3d): _get_selected_session() indexes "
            "self._sessions by visual row. Fix by storing session_id on the "
            "item and looking it up by ID. Remove this marker once fixed."
        ),
    )
    def test_selected_row_returns_the_session_it_displays(self, panel):
        panel._table.setSortingEnabled(True)
        panel._table.sortByColumn(SESSION_ID, Qt.SortOrder.AscendingOrder)

        panel._table.selectRow(0)
        displayed = panel._table.item(0, SESSION_ID).text()

        # Row 0 now shows "aaa22222", but self._sessions[0] is "ccc11111",
        # so Undo would revert a session the user never selected.
        assert panel._get_selected_session().session_id == displayed
