"""CSV export row-building in the History panel.

The rows must follow the table's *current sort order* while carrying the
*underlying* values — not the formatted cell text. Re-parsing "91%" back into
0.91 is exactly the lossy round-trip export exists to avoid.
"""

import pytest
from PySide6.QtCore import Qt

from src.gui.widgets import history_panel as hp
from src.renamer import RenameRecord, RenameSession

ENTRIES = [
    {
        "file_path": "/music/zebra.aiff",
        "bpm": 91.5, "bpm_confidence": 0.09,
        "key": "Am", "key_confidence": 0.85,
        "keycode": "10A", "energy": 7,
        "timestamp": "2026-07-01T10:00:00",
        "key_alternatives": [{"key": "Fm", "keycode": "4A", "confidence": 0.27}],
    },
    {
        "file_path": "/music/Alpha.aiff",
        "bpm": 128.0, "bpm_confidence": 0.91,
        "key": "Cm", "key_confidence": 0.62,
        "keycode": "1A", "energy": 10,
        "timestamp": "2026-07-21T10:00:00",
        "key_alternatives": [],
    },
    {
        "file_path": "/music/blank.aiff",
        "bpm": None, "bpm_confidence": None,
        "key": "", "key_confidence": None,
        "keycode": "", "energy": None,
        "timestamp": "2026-06-01T10:00:00",
        "key_alternatives": [],
    },
]

SESSIONS = [
    RenameSession(
        session_id="aaa11111",
        timestamp="2026-07-21T10:00:00",
        description="Renamed 2 files",
        records=[
            RenameRecord("/music/a.aiff", "/music/a-renamed.aiff", "2026-07-21T10:00:00"),
            RenameRecord("/music/b.aiff", "/music/b-renamed.aiff", "2026-07-21T10:00:00"),
        ],
    ),
    RenameSession(
        session_id="bbb22222",
        timestamp="2026-07-01T10:00:00",
        description="Renamed 1 files",
        records=[
            RenameRecord("/music/c.aiff", "/music/c-renamed.aiff", "2026-07-01T10:00:00"),
        ],
    ),
]

NAME, PATH, BPM, BPM_CONF, KEY, KEY_CONF, KEYCODE, ALTS, ENERGY, ANALYZED = range(10)


@pytest.fixture
def panel(qtbot, monkeypatch):
    monkeypatch.setattr(hp, "load_analysis_entries", lambda: list(ENTRIES))
    monkeypatch.setattr(hp, "list_sessions", lambda limit=50: list(SESSIONS))
    widget = hp.HistoryPanel()
    qtbot.addWidget(widget)
    widget.refresh()
    return widget


class TestKeysExport:
    def test_headers_are_english_and_stable(self, panel):
        """Headers are data for spreadsheets/scripts, never localized."""
        headers, _ = panel._keys_export_rows()
        assert headers == [
            "File Name", "File Path", "BPM", "BPM Confidence", "Key",
            "Key Confidence", "Key Code", "Alternative Keys", "Energy",
            "Analyzed At",
        ]

    def test_exports_raw_values_not_display_text(self, panel):
        """Confidence exports as 0.91, not "91%"; BPM as a float, not a string."""
        _, rows = panel._keys_export_rows()
        alpha = next(r for r in rows if r[NAME] == "Alpha.aiff")
        assert alpha[BPM] == 128.0
        assert alpha[BPM_CONF] == 0.91
        assert alpha[KEY_CONF] == 0.62
        assert alpha[ENERGY] == 10
        assert alpha[PATH] == "/music/Alpha.aiff"
        assert alpha[ANALYZED] == "2026-07-21T10:00:00"

    def test_follows_current_sort_order(self, panel):
        """What you see is what you get — export mirrors the visible order."""
        panel._keys_table.sortByColumn(2, Qt.SortOrder.AscendingOrder)  # BPM
        _, rows = panel._keys_export_rows()
        assert [r[NAME] for r in rows] == ["blank.aiff", "zebra.aiff", "Alpha.aiff"]

        panel._keys_table.sortByColumn(2, Qt.SortOrder.DescendingOrder)
        _, rows = panel._keys_export_rows()
        assert [r[NAME] for r in rows] == ["Alpha.aiff", "zebra.aiff", "blank.aiff"]

    def test_missing_values_export_as_none(self, panel):
        """None reaches write_csv, which renders it as an empty cell."""
        _, rows = panel._keys_export_rows()
        blank = next(r for r in rows if r[NAME] == "blank.aiff")
        assert blank[BPM] is None
        assert blank[BPM_CONF] is None
        assert blank[ENERGY] is None

    def test_alternatives_flatten_to_text(self, panel):
        _, rows = panel._keys_export_rows()
        zebra = next(r for r in rows if r[NAME] == "zebra.aiff")
        assert zebra[ALTS] == "Fm (4A) 27%"

    def test_row_count_matches_table(self, panel):
        _, rows = panel._keys_export_rows()
        assert len(rows) == panel._keys_table.rowCount() == len(ENTRIES)


class TestSessionsExport:
    def test_one_row_per_renamed_file(self, panel):
        """Sessions nest records; CSV can't, so metadata repeats per file."""
        headers, rows = panel._sessions_export_rows()
        assert headers == [
            "Session ID", "Session Timestamp", "Original Path", "New Path",
            "Renamed At",
        ]
        assert len(rows) == 3  # 2 records + 1 record
        assert [r[0] for r in rows] == ["aaa11111", "aaa11111", "bbb22222"]
        assert [r[2] for r in rows] == [
            "/music/a.aiff", "/music/b.aiff", "/music/c.aiff",
        ]

    def test_session_metadata_repeats_across_its_rows(self, panel):
        _, rows = panel._sessions_export_rows()
        first, second = rows[0], rows[1]
        assert first[0] == second[0] == "aaa11111"
        assert first[1] == second[1] == "2026-07-21T10:00:00"
        assert first[3] == "/music/a-renamed.aiff"


class TestExportDispatch:
    def test_picks_the_visible_view(self, panel):
        panel._set_view("sessions")
        assert not panel._showing_keys()
        panel._set_view("keys")
        assert panel._showing_keys()

    def test_end_to_end_writes_a_readable_file(self, panel, tmp_path, monkeypatch):
        """Click-path: dialog returns a path, file lands, contents parse back."""
        import csv

        out = tmp_path / "keys.csv"
        panel._set_view("keys")
        monkeypatch.setattr(
            hp.QFileDialog, "getSaveFileName",
            staticmethod(lambda *a, **k: (str(out), "CSV files (*.csv)")),
        )
        shown = []
        monkeypatch.setattr(
            hp.QMessageBox, "information",
            staticmethod(lambda *a, **k: shown.append(a)),
        )

        panel._on_export_clicked()

        with open(out, newline="", encoding="utf-8-sig") as f:
            parsed = list(csv.reader(f))
        assert parsed[0][0] == "File Name"
        assert len(parsed) == len(ENTRIES) + 1
        assert shown, "expected a completion message"

    def test_cancelled_dialog_writes_nothing(self, panel, tmp_path, monkeypatch):
        monkeypatch.setattr(
            hp.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", ""))
        )
        panel._on_export_clicked()
        assert not list(tmp_path.iterdir())
