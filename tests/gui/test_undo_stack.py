"""Session undo stack (§11): the safety net that auto-save requires.

The rule under test: Cmd+Z reverses anything that destroys or scrambles
structure the user built — remove, Clear, reorder, delete, reparent — and
never touches file contents. Tag edits and search results stay off the stack.
"""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QLineEdit, QMessageBox

from src.gui.models.undo_stack import MAX_DEPTH, UndoStack
# Imported at collection time on purpose: importing this module *during* a
# test races the player's decode threads, which lazy-import librosa on their
# own, and two threads entering the import lock like that aborts the process.
from src.gui.main_window import MainWindow
from src.gui.widgets.player_panel import PlayerPanel
from src.gui.widgets.playlist_tree import PlaylistTreePanel
from src.library import SCRATCH_NODE_ID, Library


@pytest.fixture
def lib(tmp_path):
    library = Library(tmp_path / "library.db")
    yield library
    library.close()


@pytest.fixture
def stack():
    return UndoStack()


@pytest.fixture
def player(qtbot, lib, stack):
    panel = PlayerPanel()
    qtbot.addWidget(panel)
    panel.set_library(lib)
    panel.set_undo_stack(stack)
    return panel


@pytest.fixture
def tree(qtbot, lib, stack):
    panel = PlaylistTreePanel()
    qtbot.addWidget(panel)
    panel.set_library(lib)
    panel.set_undo_stack(stack)
    panel.ensure_loaded()
    return panel.tree


def make_files(tmp_path, *names):
    paths = []
    for name in names:
        f = tmp_path / name
        f.write_bytes(b"audio-" + name.encode())
        paths.append(str(f))
    return paths


def track_dicts(paths):
    return [{"file_path": p, "display_name": Path(p).name} for p in paths]


def confirm_deletes(monkeypatch, answer=QMessageBox.StandardButton.Yes):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: answer)


class TestStackMechanics:
    def test_undo_runs_newest_first_and_reports_its_label(self, stack):
        done = []
        stack.push("First", lambda: done.append(1))
        stack.push("Second", lambda: done.append(2))

        assert stack.peek_label() == "Second"
        assert stack.undo() == "Second"
        assert stack.undo() == "First"
        assert done == [2, 1]
        assert not stack.can_undo()
        assert stack.undo() == ""  # empty stack is a silent no-op

    def test_an_entry_cannot_push_while_it_runs(self, stack):
        # Restores write through the same chokepoints that record entries;
        # without the guard, Cmd+Z would flip between two states forever.
        stack.push("Op", lambda: stack.push("Inverse", lambda: None))
        stack.undo()
        assert not stack.can_undo()

    def test_a_failing_entry_is_discarded_not_retried(self, stack):
        # It described a world that no longer exists; leaving it on would
        # jam every older undo behind it.
        def boom():
            raise RuntimeError("its playlist is gone")

        stack.push("Broken", boom)
        stack.push("Fine", lambda: None)
        stack.undo()
        stack.undo()
        assert not stack.can_undo()

    def test_depth_is_capped_dropping_the_oldest(self, stack):
        for i in range(MAX_DEPTH + 10):
            stack.push(f"Op {i}", lambda: None)
        assert len(stack) == MAX_DEPTH
        assert stack.peek_label() == f"Op {MAX_DEPTH + 9}"

    def test_changed_fires_on_push_undo_and_clear(self, stack, qtbot):
        with qtbot.waitSignal(stack.changed):
            stack.push("Op", lambda: None)
        with qtbot.waitSignal(stack.changed):
            stack.undo()
        with qtbot.waitSignal(stack.changed):
            stack.clear()


class TestPlayerEdits:
    def test_remove_is_undoable(self, player, lib, stack, tmp_path):
        a, b, c = make_files(tmp_path, "a.wav", "b.wav", "c.wav")
        player.add_tracks(track_dicts([a, b, c]))
        player._table.selectRow(1)
        player._on_remove_selected()
        assert [t.path for t in lib.get_items(SCRATCH_NODE_ID)] == [a, c]

        assert stack.peek_label() == "Remove Tracks"
        stack.undo()
        assert [t.path for t in lib.get_items(SCRATCH_NODE_ID)] == [a, b, c]

    def test_clear_playlist_is_undoable(self, player, lib, stack, tmp_path):
        # The sharp edge that made undo the priority: Clear on a loaded
        # saved playlist empties the saved playlist, with auto-save.
        a, b = make_files(tmp_path, "a.wav", "b.wav")
        pl = lib.create_playlist("Set")
        lib.set_items(pl, [lib.add_track(p) for p in (a, b)])
        player.load_node(pl)

        player._on_clear_playlist()
        assert lib.get_items(pl) == []
        assert stack.peek_label() == "Clear Playlist"

        stack.undo()
        assert [t.path for t in lib.get_items(pl)] == [a, b]
        player.load_node(pl)  # what MainWindow._on_undone does
        assert [e.file_path for e in player._playlist] == [a, b]

    def test_reorder_is_undoable(self, player, lib, stack, tmp_path):
        a, b, c = make_files(tmp_path, "a.wav", "b.wav", "c.wav")
        player.add_tracks(track_dicts([a, b, c]))
        entries = player._playlist
        player._playlist = [entries[2], entries[0], entries[1]]
        player._rebuild_table()
        player._persist_playlist()
        assert [t.path for t in lib.get_items(SCRATCH_NODE_ID)] == [c, a, b]

        assert stack.peek_label() == "Reorder Playlist"
        stack.undo()
        assert [t.path for t in lib.get_items(SCRATCH_NODE_ID)] == [a, b, c]

    def test_add_is_undoable(self, player, lib, stack, tmp_path):
        a, b = make_files(tmp_path, "a.wav", "b.wav")
        player.add_tracks(track_dicts([a]))
        player.add_tracks(track_dicts([b]))
        assert stack.peek_label() == "Add Tracks"
        stack.undo()
        assert [t.path for t in lib.get_items(SCRATCH_NODE_ID)] == [a]

    def test_a_tag_edit_records_nothing(self, player, lib, stack, tmp_path):
        # Tag writes go to the audio file and route through the same
        # persist path; undo must never reach file contents (§11).
        (a,) = make_files(tmp_path, "a.wav")
        player.add_tracks(track_dicts([a]))
        stack.clear()

        player._playlist[0].artist = "Edited"
        player._persist_playlist()
        assert not stack.can_undo()

    def test_a_no_op_persist_records_nothing(self, player, stack, tmp_path):
        (a,) = make_files(tmp_path, "a.wav")
        player.add_tracks(track_dicts([a]))
        stack.clear()
        player._persist_playlist()
        assert not stack.can_undo()

    def test_search_results_record_nothing(self, player, lib, stack, tmp_path):
        a, b = make_files(tmp_path, "a.wav", "b.wav")
        player.add_tracks(track_dicts([a, b]))
        stack.clear()

        player._search_active = True
        player._persist_playlist()  # hard-guarded, but assert it stays quiet
        assert not stack.can_undo()


class TestTreeEdits:
    def test_delete_playlist_is_undoable(self, tree, lib, stack, monkeypatch, tmp_path):
        (a,) = make_files(tmp_path, "a.wav")
        pl = lib.create_playlist("Doomed")
        lib.set_items(pl, [lib.add_track(a, artist="DJ")])
        tree.refresh()

        confirm_deletes(monkeypatch)
        tree._delete_node(pl)
        assert lib.get_node(pl) is None
        assert stack.peek_label() == "Delete Playlist"

        stack.undo()
        node = lib.get_node(pl)
        assert node is not None and node.name == "Doomed"
        assert [t.path for t in lib.get_items(pl)] == [a]
        assert lib.get_items(pl)[0].artist == "DJ"

    def test_delete_folder_restores_the_whole_subtree(
        self, tree, lib, stack, monkeypatch, tmp_path
    ):
        a, b = make_files(tmp_path, "a.wav", "b.wav")
        folder = lib.create_folder("Crates")
        peak = lib.create_playlist("Peak", folder)
        lib.set_items(peak, [lib.add_track(a), lib.add_track(b)])
        tree.refresh()

        confirm_deletes(monkeypatch)
        tree._delete_node(folder)
        assert stack.peek_label() == "Delete Folder"

        stack.undo()
        assert lib.get_node(folder) is not None
        assert [n.name for n in lib.get_children(folder)] == ["Peak"]
        assert [t.path for t in lib.get_items(peak)] == [a, b]

    def test_a_declined_delete_records_nothing(self, tree, lib, stack, monkeypatch):
        pl = lib.create_playlist("Safe")
        tree.refresh()
        confirm_deletes(monkeypatch, QMessageBox.StandardButton.No)
        tree._delete_node(pl)
        assert lib.get_node(pl) is not None
        assert not stack.can_undo()

    def test_reparent_is_undoable(self, tree, lib, stack):
        folder = lib.create_folder("Crates")
        pl = lib.create_playlist("Set")  # at the root
        tree.refresh()

        assert tree._apply_move(pl, folder, 0)
        assert lib.get_node(pl).parent_id == folder
        assert stack.peek_label() == "Move Playlist"

        stack.undo()
        node = lib.get_node(pl)
        assert node.parent_id is None
        assert node.position == 0

    def test_reorder_among_siblings_is_undoable(self, tree, lib, stack):
        a = lib.create_playlist("A")
        b = lib.create_playlist("B")
        c = lib.create_playlist("C")
        assert [n.id for n in lib.get_children(None)] == [c, b, a]
        tree.refresh()

        assert tree._apply_move(c, None, 3)  # drag C to the bottom
        assert [n.id for n in lib.get_children(None)] == [b, a, c]

        stack.undo()
        assert [n.id for n in lib.get_children(None)] == [c, b, a]

    def test_a_refused_move_records_nothing(self, tree, lib, stack):
        outer = lib.create_folder("Outer")
        inner = lib.create_folder("Inner", outer)
        tree.refresh()
        assert not tree._apply_move(outer, inner, 0)  # cycle
        assert not stack.can_undo()


class TestShortcutGuard:
    """Cmd+Z must keep undoing *typing* when a text editor has focus.

    A window-level shortcut is consumed before the key reaches the focus
    widget, so the handler has to hand off explicitly or the tree's rename
    editor and the search field silently lose their own undo.
    """

    def _handler(self, stack):
        class Stub:
            _undo_stack = stack

        return lambda: MainWindow._on_undo_shortcut(Stub())

    def test_focused_line_edit_keeps_its_own_undo(self, qtbot, stack):
        edit = QLineEdit()
        qtbot.addWidget(edit)
        edit.show()
        edit.setFocus()
        qtbot.waitUntil(edit.hasFocus)
        qtbot.keyClicks(edit, "typed")  # real keystrokes: setText() wipes its undo

        popped = []
        stack.push("Delete Playlist", lambda: popped.append(True))
        self._handler(stack)()

        assert edit.text() == ""  # the line edit undid its own typing
        assert not popped
        assert stack.can_undo()  # the playlist entry is untouched

    def test_stack_runs_when_no_editor_has_focus(self, qtbot, stack):
        popped = []
        stack.push("Delete Playlist", lambda: popped.append(True))
        self._handler(stack)()
        assert popped == [True]
