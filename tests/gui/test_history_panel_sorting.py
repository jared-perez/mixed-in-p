"""Sorting behaviour of the History panel's Key History table.

These assert on the *rendered* cell text, not just row order. A sort value
written to the wrong item role silently replaces the cell's display text while
leaving ordering plausible — that regression shipped once and was invisible to
the pure-function unit tests in tests/test_history_panel_sort.py.
"""

import pytest
from PySide6.QtCore import Qt

from src.gui.widgets import history_panel as hp

# Deliberately adversarial fixtures:
#   - BPM 91.5 vs 100.0   -> text sort puts "100.0" first
#   - conf 9% vs 85%/91%  -> text sort puts "9%" last
#   - energy 2 vs 10      -> text sort puts "10" first
#   - keycode 1A vs 10A   -> text sort puts "10A" first
#   - names Alpha/zebra   -> case-sensitive sort puts "zebra" before "empty"
#   - one all-missing row -> blanks must group, not interleave
ENTRIES = [
    {
        "file_path": "/music/zebra.aiff",
        "bpm": 91.5, "bpm_confidence": 0.09,
        "key": "Am", "key_confidence": 0.85,
        "keycode": "10A", "energy": 7,
        "timestamp": "2026-07-01T10:00:00",
        "key_alternatives": [],
    },
    {
        "file_path": "/music/Alpha.aiff",
        "bpm": 128.0, "bpm_confidence": 0.91,
        "key": "Cm", "key_confidence": 0.09,
        "keycode": "1A", "energy": 10,
        "timestamp": "2026-07-21T10:00:00",
        "key_alternatives": [],
    },
    {
        "file_path": "/music/mid.aiff",
        "bpm": 100.0, "bpm_confidence": 0.85,
        "key": "Fm", "key_confidence": 0.62,
        "keycode": "2B", "energy": 2,
        "timestamp": "2026-07-10T10:00:00",
        "key_alternatives": [],
    },
    {
        "file_path": "/music/empty.aiff",
        "bpm": None, "bpm_confidence": None,
        "key": "", "key_confidence": None,
        "keycode": "", "energy": None,
        "timestamp": "2026-06-01T10:00:00",
        "key_alternatives": [],
    },
]

# Column indices, mirroring _setup_ui's header order.
NAME, BPM, BPM_CONF, KEY, KEY_CONF, KEYCODE, ALTS, ENERGY, DATE = range(9)


@pytest.fixture
def panel(qtbot, monkeypatch):
    """A HistoryPanel populated from ENTRIES instead of real app data."""
    monkeypatch.setattr(hp, "load_analysis_entries", lambda: list(ENTRIES))
    widget = hp.HistoryPanel()
    qtbot.addWidget(widget)
    widget.refresh()
    return widget


def column_text(table, col):
    """Rendered text of every cell in a column, in current visual order."""
    return [table.item(row, col).text() for row in range(table.rowCount())]


def sorted_text(panel, col, order=Qt.SortOrder.AscendingOrder):
    panel._keys_table.sortByColumn(col, order)
    return column_text(panel._keys_table, col)


class TestDefaultOrder:
    def test_defaults_to_newest_first(self, panel):
        """Enabling sorting must not disturb load_entries()' newest-first order."""
        assert column_text(panel._keys_table, DATE) == [
            "2026-07-21 10:00:00",
            "2026-07-10 10:00:00",
            "2026-07-01 10:00:00",
            "2026-06-01 10:00:00",
        ]


class TestNumericColumns:
    def test_bpm_sorts_numerically(self, panel):
        """91.5 < 100.0 < 128.0 — as text, "100.0" would sort first."""
        assert sorted_text(panel, BPM) == ["", "91.5", "100.0", "128.0"]

    def test_bpm_confidence_sorts_numerically(self, panel):
        """9% < 85% < 91% — as text, "9%" would sort last."""
        assert sorted_text(panel, BPM_CONF) == ["", "9%", "85%", "91%"]

    def test_key_confidence_sorts_numerically(self, panel):
        assert sorted_text(panel, KEY_CONF) == ["", "9%", "62%", "85%"]

    def test_energy_sorts_numerically(self, panel):
        """2 < 7 < 10 — as text, "10" would sort first."""
        assert sorted_text(panel, ENERGY) == ["", "2", "7", "10"]

    def test_descending_reverses(self, panel):
        assert sorted_text(panel, BPM, Qt.SortOrder.DescendingOrder) == [
            "128.0", "100.0", "91.5", "",
        ]


class TestKeyCodeColumn:
    def test_sorts_by_number_not_text(self, panel):
        """1A < 2B < 10A — as text, "10A" would sort before "1A"."""
        assert sorted_text(panel, KEYCODE) == ["", "1A", "2B", "10A"]


class TestNameColumn:
    def test_sorts_case_insensitively(self, panel):
        """Case-sensitive sort would place "zebra" before "empty"."""
        assert sorted_text(panel, NAME) == [
            "Alpha.aiff", "empty.aiff", "mid.aiff", "zebra.aiff",
        ]


class TestMissingValues:
    def test_blanks_group_together(self, panel):
        """Missing values share a sentinel so they cluster at one end."""
        for col in (BPM, BPM_CONF, KEY_CONF, ENERGY):
            assert sorted_text(panel, col)[0] == "", f"column {col}"

    def test_missing_values_render_blank_not_sentinel(self, panel):
        """The -1 sort sentinel must never reach the screen.

        Direct guard on the shipped EditRole bug: the sentinel was displayed
        as "-1" because EditRole and DisplayRole share storage.
        """
        for col in (BPM, BPM_CONF, KEY_CONF, ENERGY):
            assert "-1" not in sorted_text(panel, col), f"column {col}"


class TestDisplayTextIntegrity:
    def test_sort_values_never_replace_display_text(self, panel):
        """Formatted text survives sorting — the EditRole regression guard.

        Percentages keep their "%", BPM keeps one decimal, and key codes are
        not shown zero-padded ("01A"), which is how the sort value renders if
        it lands in the wrong role.
        """
        panel._keys_table.sortByColumn(BPM, Qt.SortOrder.AscendingOrder)
        table = panel._keys_table

        assert column_text(table, BPM_CONF) == ["", "9%", "85%", "91%"]
        assert column_text(table, BPM) == ["", "91.5", "100.0", "128.0"]
        assert column_text(table, KEYCODE) == ["", "10A", "2B", "1A"]
        assert column_text(table, NAME) == [
            "empty.aiff", "zebra.aiff", "mid.aiff", "Alpha.aiff",
        ]

    def test_key_column_is_untouched_by_sorting(self, panel):
        """The Key column carries no sort value; it must still render keys."""
        panel._keys_table.sortByColumn(BPM, Qt.SortOrder.AscendingOrder)
        assert column_text(panel._keys_table, KEY) == ["", "Am", "Fm", "Cm"]


class TestRefresh:
    def test_refresh_preserves_user_sort(self, panel):
        """Repopulating must re-apply the chosen sort, not reset to default."""
        before = sorted_text(panel, BPM, Qt.SortOrder.DescendingOrder)
        panel.refresh()
        assert column_text(panel._keys_table, BPM) == before

    def test_refresh_does_not_scramble_rows(self, panel):
        """Rows must stay internally consistent across a repopulate.

        With sorting left enabled during the fill loop, Qt re-sorts after each
        setItem() and cells land in the wrong rows.
        """
        panel._keys_table.sortByColumn(BPM, Qt.SortOrder.AscendingOrder)
        panel.refresh()
        table = panel._keys_table
        rows = {
            table.item(r, NAME).text(): (
                table.item(r, BPM).text(),
                table.item(r, KEYCODE).text(),
            )
            for r in range(table.rowCount())
        }
        assert rows["Alpha.aiff"] == ("128.0", "1A")
        assert rows["zebra.aiff"] == ("91.5", "10A")
        assert rows["mid.aiff"] == ("100.0", "2B")
        assert rows["empty.aiff"] == ("", "")
