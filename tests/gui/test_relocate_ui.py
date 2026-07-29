"""Missing-file marking in the Player, and the relocate dialog's wiring.

The matching itself is covered by tests/test_relocate.py. What's under test
here is what the user touches: the "!" mark and its tooltip, the context
menu offering Locate only when the file is actually gone, and the two ways
out of the dialog leaving the visible list pointing at real files.
"""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox

from src.gui.styles.theme import Theme
from src.gui.widgets.dialogs.relocate_dialog import RelocateDialog
from src.gui.widgets.player_panel import PlayerPanel
from src.library import SCRATCH_NODE_ID, Library


@pytest.fixture
def lib(tmp_path):
    library = Library(tmp_path / "library.db")
    yield library
    library.close()


@pytest.fixture
def player(qtbot, lib):
    panel = PlayerPanel()
    qtbot.addWidget(panel)
    panel.set_library(lib)
    return panel


def make_files(directory, *names, content=b"audio-"):
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in names:
        f = directory / name
        f.write_bytes(content + name.encode())
        paths.append(str(f))
    return paths


def track_dicts(paths):
    return [{"file_path": p, "display_name": Path(p).name} for p in paths]


def silence_boxes(monkeypatch):
    """Swallow the summary dialogs, capturing their text."""
    seen = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: seen.append(a[2]))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: seen.append(a[2]))
    return seen


class TestMissingMarker:
    def test_missing_row_is_marked_dimmed_and_explained(self, player, tmp_path):
        here, gone = make_files(tmp_path / "audio", "here.wav", "gone.wav")
        player.add_tracks(track_dicts([here, gone]))
        Path(gone).unlink()
        player._refresh_missing_marks()

        assert player._table.item(0, 1).text() == "here.wav"
        assert player._table.item(1, 1).text() == "! gone.wav"
        assert gone in player._table.item(1, 1).toolTip()
        assert player._table.item(1, 1).foreground().color().name() == (
            Theme.TEXT_DISABLED
        )
        # The present file keeps normal text and no tooltip.
        assert player._table.item(0, 1).toolTip() == ""

    def test_mark_clears_when_the_file_comes_back(self, player, tmp_path):
        (gone,) = make_files(tmp_path / "audio", "gone.wav")
        player.add_tracks(track_dicts([gone]))
        Path(gone).unlink()
        player._refresh_missing_marks()
        assert player._table.item(0, 1).text() == "! gone.wav"

        Path(gone).write_bytes(b"back")
        player._refresh_missing_marks()
        assert player._table.item(0, 1).text() == "gone.wav"

    def test_playing_row_keeps_its_highlight_while_missing(self, player, tmp_path):
        (gone,) = make_files(tmp_path / "audio", "gone.wav")
        player.add_tracks(track_dicts([gone]))
        Path(gone).unlink()
        player._current_index = 0
        player._refresh_missing_marks()
        player._highlight_current_row()

        assert player._table.item(0, 1).foreground().color().name() == (
            Theme.NEON_YELLOW
        )

    def test_reorder_survives_the_marker(self, player, tmp_path):
        """Regression: the '!' makes the cell text a bad row identity."""
        a, b = make_files(tmp_path / "audio", "a.wav", "b.wav")
        player.add_tracks(track_dicts([a, b]))
        Path(a).unlink()
        player._refresh_missing_marks()

        # Simulate the drop handler's move: take the rows and swap them.
        table = player._table
        row0 = [table.takeItem(0, c) for c in range(table.columnCount())]
        table.removeRow(0)
        table.insertRow(1)
        for col, item in enumerate(row0):
            table.setItem(1, col, item)
        player._sync_playlist_from_table()

        assert [e.file_path for e in player._playlist] == [b, a]


class TestContextMenu:
    def test_locate_is_offered_only_for_a_missing_file(self, player, tmp_path):
        here, gone = make_files(tmp_path / "audio", "here.wav", "gone.wav")
        player.add_tracks(track_dicts([here, gone]))
        Path(gone).unlink()
        player._missing_cache = {}

        assert player._is_missing(gone) is True
        assert player._is_missing(here) is False


class TestRelocateDialog:
    def test_locate_relinks_the_clicked_track(self, qtbot, lib, tmp_path, monkeypatch):
        (original,) = make_files(tmp_path / "old", "song.wav")
        track_id = lib.add_track(original)
        lib.add_items(SCRATCH_NODE_ID, [track_id])
        (moved,) = make_files(tmp_path / "new", "song.wav")
        Path(original).unlink()

        dialog = RelocateDialog(lib, original)
        qtbot.addWidget(dialog)
        monkeypatch.setattr(
            QFileDialog, "getOpenFileName", lambda *a, **k: (moved, "")
        )
        dialog._on_locate()

        assert dialog.relinked == 1
        assert dialog.new_path == moved
        assert lib.get_track(track_id).path == moved

    def test_cancelled_locate_changes_nothing(self, qtbot, lib, tmp_path, monkeypatch):
        (original,) = make_files(tmp_path / "old", "song.wav")
        track_id = lib.add_track(original)
        lib.add_items(SCRATCH_NODE_ID, [track_id])
        Path(original).unlink()

        dialog = RelocateDialog(lib, original)
        qtbot.addWidget(dialog)
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))
        dialog._on_locate()

        assert dialog.relinked == 0
        assert dialog.new_path is None
        assert lib.get_track(track_id).path == original

    def test_find_in_folder_relinks_every_missing_file(
        self, qtbot, lib, tmp_path, monkeypatch
    ):
        a, b = make_files(tmp_path / "old", "a.wav", "b.wav")
        for path in (a, b):
            lib.add_items(SCRATCH_NODE_ID, [lib.add_track(path)])
        destination = tmp_path / "new"
        destination.mkdir()
        for path in (a, b):
            (destination / Path(path).name).write_bytes(Path(path).read_bytes())
            Path(path).unlink()

        seen = silence_boxes(monkeypatch)
        monkeypatch.setattr(
            QFileDialog, "getExistingDirectory", lambda *a, **k: str(destination)
        )
        dialog = RelocateDialog(lib, a)
        qtbot.addWidget(dialog)
        with qtbot.waitSignal(dialog.accepted, timeout=5000):
            dialog._on_find_in_folder()

        assert dialog.relinked == 2
        assert dialog.new_path == str(destination / "a.wav")
        assert [t.path for t in lib.get_items(SCRATCH_NODE_ID)] == [
            str(destination / "a.wav"),
            str(destination / "b.wav"),
        ]
        assert seen  # the scan reported what it did

    def test_find_in_folder_reports_when_nothing_matched(
        self, qtbot, lib, tmp_path, monkeypatch
    ):
        (gone,) = make_files(tmp_path / "old", "song.wav")
        lib.add_items(SCRATCH_NODE_ID, [lib.add_track(gone)])
        Path(gone).unlink()
        empty = tmp_path / "empty"
        empty.mkdir()

        silence_boxes(monkeypatch)
        monkeypatch.setattr(
            QFileDialog, "getExistingDirectory", lambda *a, **k: str(empty)
        )
        dialog = RelocateDialog(lib, gone)
        qtbot.addWidget(dialog)
        dialog._on_find_in_folder()
        qtbot.waitUntil(lambda: dialog._scan_thread is None, timeout=5000)

        assert dialog.relinked == 0
        assert dialog._status_label.isVisible() or dialog._status_label.text()
        assert dialog.result() != RelocateDialog.DialogCode.Accepted

    def test_counts_the_other_missing_files(self, qtbot, lib, tmp_path):
        a, b, c = make_files(tmp_path / "old", "a.wav", "b.wav", "c.wav")
        for path in (a, b, c):
            lib.add_items(SCRATCH_NODE_ID, [lib.add_track(path)])
        Path(a).unlink()
        Path(b).unlink()

        dialog = RelocateDialog(lib, a)
        qtbot.addWidget(dialog)
        # a is the one being relocated, b is the "other", c is fine.
        assert "1" in dialog._others_label.text()


class TestPlayerIntegration:
    def test_locate_repoints_the_visible_row(
        self, qtbot, player, lib, tmp_path, monkeypatch
    ):
        (original,) = make_files(tmp_path / "old", "song.wav")
        player.add_tracks(track_dicts([original]))
        (moved,) = make_files(tmp_path / "new", "song.wav")
        Path(original).unlink()
        player._refresh_missing_marks()

        monkeypatch.setattr(
            QFileDialog, "getOpenFileName", lambda *a, **k: (moved, "")
        )
        monkeypatch.setattr(RelocateDialog, "exec", lambda self: self._on_locate())
        player._locate_missing(0)

        assert [e.file_path for e in player._playlist] == [moved]
        assert player._table.item(0, 1).text() == "song.wav"
        # And the playlist itself followed, not just the view.
        assert [t.path for t in lib.get_items(SCRATCH_NODE_ID)] == [moved]

    def test_a_dismissed_dialog_leaves_the_list_alone(
        self, qtbot, player, lib, tmp_path, monkeypatch
    ):
        (original,) = make_files(tmp_path / "old", "song.wav")
        player.add_tracks(track_dicts([original]))
        Path(original).unlink()
        player._refresh_missing_marks()

        monkeypatch.setattr(RelocateDialog, "exec", lambda self: None)
        player._locate_missing(0)

        assert [e.file_path for e in player._playlist] == [original]
        assert player._table.item(0, 1).text() == "! song.wav"
