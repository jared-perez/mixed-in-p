"""Right-click 'Open File Location' in the Key History table."""

import pytest

from src.gui.widgets import history_panel as hp


def entry(name, path):
    return {
        "file_path": path,
        "bpm": 128.0, "bpm_confidence": 0.9,
        "key": "Am", "key_confidence": 0.9,
        "keycode": "8A", "energy": 5,
        "timestamp": "2026-07-21T10:00:00",
        "key_alternatives": [],
    }


ENTRIES = [
    entry("present", "/music/present.aiff"),
    entry("gone", "/music/gone.aiff"),
]


@pytest.fixture
def panel(qtbot, monkeypatch):
    monkeypatch.setattr(hp, "load_analysis_entries", lambda: list(ENTRIES))
    monkeypatch.setattr(hp, "list_sessions", lambda limit=50: [])
    widget = hp.HistoryPanel()
    qtbot.addWidget(widget)
    widget._loaded = True
    widget.refresh()
    return widget


def row_of(panel, name):
    for r in range(panel._keys_table.rowCount()):
        if panel._keys_table.item(r, 0).text() == f"{name}.aiff":
            return r
    raise AssertionError(name)


class TestPathLookup:
    def test_row_maps_to_its_file_path(self, panel):
        assert panel._entry_path_at_row(row_of(panel, "present")) == "/music/present.aiff"
        assert panel._entry_path_at_row(row_of(panel, "gone")) == "/music/gone.aiff"


class TestRevealSucceeds:
    def test_existing_file_is_revealed_no_dialog(self, panel, monkeypatch):
        revealed = []
        monkeypatch.setattr(
            hp, "reveal_in_file_manager",
            lambda p: (revealed.append(p) or True),
        )
        shown = []
        monkeypatch.setattr(hp.QMessageBox, "information",
                            staticmethod(lambda *a, **k: shown.append(a)))

        panel._open_file_location("/music/present.aiff")

        assert revealed == ["/music/present.aiff"]
        assert shown == []  # no "moved" message when the reveal works


class TestRevealFailsGracefully:
    def test_missing_file_shows_message(self, panel, monkeypatch):
        """A moved/deleted file surfaces a friendly info dialog, not a crash."""
        monkeypatch.setattr(hp, "reveal_in_file_manager", lambda p: False)
        shown = []
        monkeypatch.setattr(hp.QMessageBox, "information",
                            staticmethod(lambda *a, **k: shown.append(a)))

        panel._open_file_location("/music/gone.aiff")

        assert len(shown) == 1
        # The message text is the 3rd positional arg (self, title, text).
        assert "moved" in shown[0][2].lower()
