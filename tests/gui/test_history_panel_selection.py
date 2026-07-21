"""Selection -> data mapping in the History panel's Rename Sessions table.

_get_selected_session() maps a *visual row index* straight into self._sessions.
That holds only while the table is unsorted. Undoing the wrong session renames
real files on disk, so the failure mode is destructive and silent.

See spitball/2026-07-21-history-export-and-sorting-plan.md, section 3d.
"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView

from src.gui.widgets import history_panel as hp
from src.renamer import RenameRecord, RenameSession

# Mirrors _SESS_* in history_panel: Session ID is the last column, pushed right
# of Description so it stays out of the way for GUI users.
DATE, FILES, DESCRIPTION, SESSION_ID = range(4)


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


class TestColumnLayout:
    """Pins the visible column order (the other tests use index constants, so
    they'd pass even if the order were wrong in both places)."""

    def test_session_id_is_the_last_column(self, panel):
        header = panel._table.horizontalHeader()
        labels = [
            panel._table.horizontalHeaderItem(c).text()
            for c in range(panel._table.columnCount())
        ]
        assert labels == ["Date/Time", "Files", "Description", "Session ID"]
        assert header.count() - 1 == SESSION_ID

    def test_session_id_column_holds_the_id(self, panel):
        """The id must render in the column the header names, not elsewhere."""
        panel._table.selectRow(0)
        assert panel._table.item(0, SESSION_ID).text() == "ccc11111"
        assert panel._table.item(0, DATE).text() == "2026-07-21 10:00:00"

    def test_description_absorbs_width_so_id_sits_off_to_the_right(self, panel):
        """Description resizes to contents, pushing Session ID past the edge.

        Only checks the mechanism (Description is the growing section, ID is
        last); whether the id is literally off-screen depends on window width
        and description length at runtime.
        """
        header = panel._table.horizontalHeader()
        assert header.sectionResizeMode(DESCRIPTION) == QHeaderView.ResizeMode.ResizeToContents
        assert not header.stretchLastSection()


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
    """Regression guard for the fixed row-index bug (plan item 3d).

    Sorting reorders the table's items while self._sessions keeps its original
    order, so resolving a selection by row number returns the wrong session.
    These fail if _get_selected_session() ever goes back to indexing by row.
    """

    def test_selected_row_returns_the_session_it_displays(self, panel):
        panel._table.setSortingEnabled(True)
        panel._table.sortByColumn(SESSION_ID, Qt.SortOrder.AscendingOrder)

        panel._table.selectRow(0)
        displayed = panel._table.item(0, SESSION_ID).text()

        # Row 0 shows "aaa22222" while self._sessions[0] is "ccc11111": a
        # row-index lookup would return a session the user never selected.
        assert displayed == "aaa22222"
        assert panel._get_selected_session().session_id == displayed

    def test_every_row_maps_correctly_under_sorting(self, panel):
        panel._table.setSortingEnabled(True)
        for order in (Qt.SortOrder.AscendingOrder, Qt.SortOrder.DescendingOrder):
            for column in (SESSION_ID, DATE, FILES):
                panel._table.sortByColumn(column, order)
                for row in range(panel._table.rowCount()):
                    panel._table.selectRow(row)
                    displayed = panel._table.item(row, SESSION_ID).text()
                    selected = panel._get_selected_session()
                    assert selected is not None
                    assert selected.session_id == displayed, (
                        f"column {column}, order {order}, row {row}"
                    )

    def test_undo_signal_carries_the_displayed_session(self, qtbot, panel):
        """The destructive path end-to-end: sorted table -> click -> payload."""
        panel._table.setSortingEnabled(True)
        panel._table.sortByColumn(SESSION_ID, Qt.SortOrder.AscendingOrder)
        panel._table.selectRow(0)

        with qtbot.waitSignal(panel.undo_session, timeout=1000) as blocker:
            panel._undo_btn.click()

        assert blocker.args[0].session_id == "aaa22222"

    def test_delete_removes_the_displayed_session(self, panel, monkeypatch):
        """Delete is the other destructive path through the same accessor."""
        deleted = []
        monkeypatch.setattr(
            hp, "delete_session", lambda session_id: deleted.append(session_id)
        )
        panel._table.setSortingEnabled(True)
        panel._table.sortByColumn(SESSION_ID, Qt.SortOrder.AscendingOrder)
        panel._table.selectRow(0)

        panel._delete_btn.click()

        assert deleted == ["aaa22222"]
