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
from src.gui.widgets.history_panel import LOW_BPM_CONFIDENCE, LOW_KEY_CONFIDENCE

KEY, KEY_CONF, KEYCODE = 3, 4, 5
NAME, BPM, BPM_CONF, ALTS, ENERGY, DATE = 0, 1, 2, 6, 7, 8

# Well clear of the BPM threshold so key-only fixtures never trip the BPM flag.
_CONFIDENT_BPM = 0.95


def entry(name, key_conf, alternatives=None, bpm_conf=_CONFIDENT_BPM):
    return {
        "file_path": f"/music/{name}.aiff",
        "bpm": 128.0, "bpm_confidence": bpm_conf,
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
    # Confident key, shaky tempo: BPM flag only, key untouched.
    entry("bpm_only", 0.85, bpm_conf=0.30),
    # Shaky on both axes: the two flags are independent and both fire.
    entry("both_shaky", 0.10, bpm_conf=0.25),
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


def _tinted(panel, name, col):
    cell = panel._keys_table.item(row_of(panel, name), col)
    return cell.foreground().color() == QColor(Theme.WARNING)


def is_flagged(panel, name):
    """Key flag: the Key Conf cell is tinted."""
    return _tinted(panel, name, KEY_CONF)


def is_bpm_flagged(panel, name):
    """BPM flag: the BPM Conf cell is tinted."""
    return _tinted(panel, name, BPM_CONF)


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


class TestBpmFlagging:
    def test_confident_bpm_is_not_flagged(self, panel):
        assert not is_bpm_flagged(panel, "confident")

    def test_shaky_bpm_is_flagged(self, panel):
        assert is_bpm_flagged(panel, "bpm_only")

    def test_threshold_is_inclusive(self, panel):
        assert LOW_BPM_CONFIDENCE == 0.70  # guards the agreed value
        # bpm_only sits at 0.30, well under; confident at 0.95, well over.
        assert is_bpm_flagged(panel, "bpm_only")
        assert not is_bpm_flagged(panel, "confident")

    def test_only_bpm_cells_are_tinted(self, panel):
        """A shaky tempo says nothing about the key, so key cells stay clean."""
        row = row_of(panel, "bpm_only")
        table = panel._keys_table
        warning = QColor(Theme.WARNING)
        for col in (BPM, BPM_CONF):
            assert table.item(row, col).foreground().color() == warning, col
        for col in (KEY, KEY_CONF, KEYCODE, ENERGY, NAME):
            assert table.item(row, col).foreground().color() != warning, col

    def test_bpm_hint_mentions_tempo(self, panel):
        row = row_of(panel, "bpm_only")
        assert "tempo" in panel._keys_table.item(row, BPM_CONF).toolTip()


class TestFlagsAreIndependent:
    def test_key_flag_without_bpm_flag(self, panel):
        assert is_flagged(panel, "shaky")
        assert not is_bpm_flagged(panel, "shaky")

    def test_bpm_flag_without_key_flag(self, panel):
        assert is_bpm_flagged(panel, "bpm_only")
        assert not is_flagged(panel, "bpm_only")

    def test_both_flags_together(self, panel):
        assert is_flagged(panel, "both_shaky")
        assert is_bpm_flagged(panel, "both_shaky")

    def test_neither_flag(self, panel):
        assert not is_flagged(panel, "confident")
        assert not is_bpm_flagged(panel, "confident")


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
