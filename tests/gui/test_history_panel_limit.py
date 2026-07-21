"""History panel display-limit behaviour.

The limit is a *display* cap: entries and sessions beyond it stay loaded/on
disk, so raising it reveals rows rather than re-creating them, and lowering it
never destroys anything.
"""

import pytest
from PySide6.QtCore import Qt

from src.gui.widgets import history_panel as hp
from src.renamer import RenameRecord, RenameSession
from src.utils.config import DEFAULT_HISTORY_DISPLAY_LIMIT

NAME = 0


def entry(i):
    return {
        "file_path": f"/music/track {i:04d}.aiff",
        "bpm": 120.0, "bpm_confidence": 0.9,
        "key": "Am", "key_confidence": 0.9,
        "keycode": "8A", "energy": 5,
        # Descending timestamps so newest-first order is track 0000 first.
        "timestamp": f"2026-07-21T{23 - (i % 24):02d}:00:00",
        "key_alternatives": [],
    }


ENTRIES = [entry(i) for i in range(300)]
SESSIONS = [
    RenameSession(
        session_id=f"sess{i:04d}",
        timestamp=f"2026-07-21T{23 - (i % 24):02d}:00:00",
        description="Renamed 1 files",
        records=[RenameRecord(f"/m/{i}.aiff", f"/m/{i}-x.aiff", "2026-07-21T10:00:00")],
    )
    for i in range(300)
]


@pytest.fixture
def panel(qtbot, monkeypatch):
    monkeypatch.setattr(hp, "load_analysis_entries", lambda: list(ENTRIES))
    # Mirror list_sessions honouring its limit kwarg, as the real one does.
    monkeypatch.setattr(
        hp, "list_sessions", lambda limit=50: list(SESSIONS[:limit])
    )
    widget = hp.HistoryPanel()
    qtbot.addWidget(widget)
    widget.set_history_limit(50)
    widget._loaded = True
    widget.refresh()
    return widget


class TestKeysDisplayCap:
    def test_set_limit_caps_visible_rows(self, panel):
        """Fixture set the cap to 50 against 300 loaded entries."""
        assert panel._keys_table.rowCount() == 50

    def test_full_history_stays_loaded(self, panel):
        """The cap is display-only — all 300 remain in memory for export."""
        assert len(panel._entries) == 300

    def test_raising_limit_reveals_more_rows(self, panel):
        panel.set_history_limit(250)
        assert panel._keys_table.rowCount() == 250

    def test_lowering_limit_hides_without_dropping_data(self, panel):
        panel.set_history_limit(250)
        panel.set_history_limit(50)
        assert panel._keys_table.rowCount() == 50
        assert len(panel._entries) == 300  # nothing lost

    def test_count_label_reflects_shown_not_stored(self, panel):
        assert panel._keys_btn.text() == panel.tr("{0} Song Keys").format(50)


class TestDefaultLimit:
    def test_untouched_panel_uses_default(self, qtbot, monkeypatch):
        """A panel with no set_history_limit() call shows the default cap."""
        monkeypatch.setattr(hp, "load_analysis_entries", lambda: list(ENTRIES))
        monkeypatch.setattr(hp, "list_sessions", lambda limit=50: list(SESSIONS[:limit]))
        widget = hp.HistoryPanel()
        qtbot.addWidget(widget)
        widget._loaded = True
        widget.refresh()
        assert widget._display_limit == DEFAULT_HISTORY_DISPLAY_LIMIT == 100
        assert widget._keys_table.rowCount() == 100


class TestSessionsDisplayCap:
    def test_limit_is_passed_to_list_sessions(self, panel):
        panel._set_view("sessions")
        assert panel._table.rowCount() == 50
        panel.set_history_limit(100)
        assert panel._table.rowCount() == 100


class TestSignalAndPersistenceContract:
    def test_user_change_emits_limit(self, qtbot, panel):
        with qtbot.waitSignal(panel.history_limit_changed, timeout=1000) as sig:
            panel._limit_actions[500].trigger()
        assert sig.args == [500]

    def test_menu_reflects_current_selection(self, panel):
        """The chosen count is checked; the button shows it."""
        panel._limit_actions[250].trigger()
        assert panel._limit_btn.text() == "250"
        assert panel._limit_actions[250].isChecked()
        assert not panel._limit_actions[100].isChecked()

    def test_reselecting_current_limit_is_a_noop(self, qtbot, panel):
        """Picking the already-active count emits nothing and stays put."""
        panel.set_history_limit(100)
        with qtbot.assertNotEmitted(panel.history_limit_changed):
            panel._limit_actions[100].trigger()

    def test_set_history_limit_does_not_emit(self, qtbot, panel):
        """Loading persisted state must not look like a user edit."""
        with qtbot.assertNotEmitted(panel.history_limit_changed):
            panel.set_history_limit(250)
        assert panel._limit_btn.text() == "250"

    def test_unknown_limit_falls_back_to_default(self, panel):
        panel.set_history_limit(999)
        assert panel._display_limit == DEFAULT_HISTORY_DISPLAY_LIMIT


class TestExportRespectsLimit:
    def test_export_rows_capped_to_visible(self, panel):
        """Export follows the table, so it emits only the shown rows."""
        panel.set_history_limit(100)
        _, rows = panel._keys_export_rows()
        assert len(rows) == 100


class TestEntryIndexMappingUnderCap:
    def test_export_values_match_visible_rows_after_sort(self, panel):
        """The entry-index role must still resolve when rows are a prefix."""
        panel._keys_table.sortByColumn(NAME, Qt.SortOrder.AscendingOrder)
        _, rows = panel._keys_export_rows()
        names = [r[0] for r in rows]
        assert names == sorted(names)
        assert len(names) == 50
