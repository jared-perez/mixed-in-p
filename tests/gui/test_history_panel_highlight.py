"""Low-confidence highlighting in the Key History table.

Flagging is driven by key_confidence alone. The detector already folds the
runner-up margin into that score (weighted most heavily of its three terms), so
a separate margin rule here would double-count — see LOW_KEY_CONFIDENCE.
"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from src.gui.styles.theme import Theme
from src.gui.widgets import history_panel as hp
from src.gui.widgets.history_panel import LOW_KEY_CONFIDENCE

KEY, KEY_CONF, KEYCODE = 3, 4, 5
NAME, BPM, BPM_CONF, ALTS, ENERGY, DATE = 0, 1, 2, 6, 7, 8


def entry(name, key_conf, alternatives=None):
    return {
        "file_path": f"/music/{name}.aiff",
        "bpm": 128.0, "bpm_confidence": 0.9,
        "key": "Am", "key_confidence": key_conf,
        "keycode": "8A", "energy": 7,
        "timestamp": "2026-07-21T10:00:00",
        "key_alternatives": alternatives or [],
    }


ENTRIES = [
    entry("confident", 0.85),
    entry("borderline_above", LOW_KEY_CONFIDENCE + 0.01),
    entry("borderline_at", LOW_KEY_CONFIDENCE),
    entry("shaky", 0.12),
    # No detection at all — nothing to second-guess, so not flagged.
    {
        "file_path": "/music/nokey.aiff",
        "bpm": None, "bpm_confidence": None,
        "key": "", "key_confidence": None,
        "keycode": "", "energy": None,
        "timestamp": "2026-06-01T10:00:00",
        "key_alternatives": [],
    },
]


@pytest.fixture
def panel(qtbot, monkeypatch):
    monkeypatch.setattr(hp, "load_analysis_entries", lambda: list(ENTRIES))
    widget = hp.HistoryPanel()
    qtbot.addWidget(widget)
    widget.refresh()
    return widget


def row_of(panel, name):
    table = panel._keys_table
    for r in range(table.rowCount()):
        if table.item(r, NAME).text() == f"{name}.aiff":
            return r
    raise AssertionError(f"no row for {name}")


def is_flagged(panel, name):
    cell = panel._keys_table.item(row_of(panel, name), KEY_CONF)
    return cell.foreground().color() == QColor(Theme.WARNING)


class TestWhichRowsAreFlagged:
    def test_confident_row_is_not_flagged(self, panel):
        assert not is_flagged(panel, "confident")

    def test_shaky_row_is_flagged(self, panel):
        assert is_flagged(panel, "shaky")

    def test_threshold_is_inclusive(self, panel):
        """<= the threshold flags; just above it does not."""
        assert is_flagged(panel, "borderline_at")
        assert not is_flagged(panel, "borderline_above")

    def test_missing_confidence_is_not_flagged(self, panel):
        """No detection means nothing to doubt — an empty row isn't a warning."""
        assert not is_flagged(panel, "nokey")


class TestWhichCellsAreTinted:
    def test_only_key_related_cells_are_tinted(self, panel):
        """BPM and energy aren't in doubt when the *key* is uncertain."""
        row = row_of(panel, "shaky")
        table = panel._keys_table
        warning = QColor(Theme.WARNING)
        for col in (KEY, KEY_CONF, KEYCODE):
            assert table.item(row, col).foreground().color() == warning, col
        for col in (NAME, BPM, BPM_CONF, ALTS, ENERGY, DATE):
            assert table.item(row, col).foreground().color() != warning, col

    def test_flagged_cells_explain_themselves(self, panel):
        """The colour needs a text explanation to be meaningful."""
        row = row_of(panel, "shaky")
        for col in (KEY, KEY_CONF, KEYCODE):
            assert "double-check" in panel._keys_table.item(row, col).toolTip()

    def test_unflagged_cells_have_no_hint(self, panel):
        row = row_of(panel, "confident")
        assert panel._keys_table.item(row, KEY_CONF).toolTip() == ""


class TestSurvivesInteraction:
    def test_highlight_follows_rows_through_sorting(self, panel):
        """Tinting rides on the item, so it must move with it."""
        panel._keys_table.sortByColumn(KEY_CONF, Qt.SortOrder.AscendingOrder)
        assert is_flagged(panel, "shaky")
        assert not is_flagged(panel, "confident")
        panel._keys_table.sortByColumn(NAME, Qt.SortOrder.DescendingOrder)
        assert is_flagged(panel, "shaky")
        assert not is_flagged(panel, "confident")

    def test_highlight_survives_refresh(self, panel):
        panel.refresh()
        assert is_flagged(panel, "shaky")
        assert not is_flagged(panel, "confident")
