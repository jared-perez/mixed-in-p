"""Dragging tracks into a playlist: copy semantics, tags, undo, refresh.

Drops are exercised through the handlers with a duck-typed event rather
than a synthesized QDropEvent — the same convention the tree's move tests
use (`_apply_move` directly). What matters here is the contract: the source
list keeps its tracks (CopyAction), the target gains them, and the Player
is told when the list it is showing changed underneath it.
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QMessageBox

from src.gui.main_window import MainWindow
from src.gui.widgets import playlist_tree as tree_mod
from src.gui.widgets.dialogs import duplicate_policy as dup_mod
from src.gui.widgets.player_panel import PlayerPanel
from src.gui.widgets.playlist_tree import NODE_MIME, PlaylistTreePanel
from src.gui.models.undo_stack import UndoStack
from src.library import SCRATCH_NODE_ID, Library
from src.metadata.tags import TrackMetadata, read_metadata


@pytest.fixture(scope="module", autouse=True)
def warm_tag_reader(tmp_path_factory):
    """Pull mutagen's lazy imports in on the main thread, once, up front.

    Dropping a file reads its tags, and the Player fixture's decode threads
    lazy-import librosa at the same time. Two threads entering the import
    lock like that aborts the process — the same race
    tests/gui/test_undo_stack.py imports MainWindow at collection time to
    avoid. Doing the first read here means no test is ever the one that
    triggers it.
    """
    warm = tmp_path_factory.mktemp("warm") / "warm.wav"
    warm.write_bytes(b"not really audio")
    try:
        read_metadata(str(warm))
    except Exception:  # noqa: BLE001 — we want the imports, not the tags
        pass


@pytest.fixture
def lib(tmp_path):
    library = Library(tmp_path / "library.db")
    yield library
    library.close()


@pytest.fixture
def stack():
    return UndoStack()


@pytest.fixture
def tree(qtbot, lib, stack):
    panel = PlaylistTreePanel()
    qtbot.addWidget(panel)
    panel.set_library(lib)
    panel.tree.set_undo_stack(stack)
    panel.ensure_loaded()
    return panel.tree


@pytest.fixture
def player(qtbot, lib):
    panel = PlayerPanel()
    qtbot.addWidget(panel)
    panel.set_library(lib)
    return panel


def make_files(tmp_path, *names):
    paths = []
    for name in names:
        f = tmp_path / name
        f.write_bytes(b"audio-" + name.encode())
        paths.append(str(f))
    return paths


def track_dicts(paths):
    return [{"file_path": p, "display_name": Path(p).name} for p in paths]


def url_mime(paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
    return mime


class FakeDropEvent:
    """The slice of QDropEvent the drop handlers actually use."""

    def __init__(self, mime, pos=QPointF(0, 0)):
        self._mime = mime
        self._pos = pos
        self.action = None
        self.accepted = None

    def mimeData(self):
        return self._mime

    def position(self):
        return self._pos

    def setDropAction(self, action):
        self.action = action

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.accepted = False


def pump(qtbot):
    """Let a deferred (zero-delay-timer) duplicate prompt actually run.

    Deliberately not ``qtbot.wait(0)``: that returns without draining the
    event queue, so a test using it asserts against a prompt that never fired
    and passes for the wrong reason.
    """
    qtbot.wait(10)


def aim_at(tree, node_id, monkeypatch):
    """Make indexAt() report the row for *node_id*, whatever the position."""
    item = tree._find_item(node_id)
    monkeypatch.setattr(tree, "indexAt", lambda _pos: item.index())


class TestTrackDragDetection:
    def test_a_node_drag_is_never_a_track_drag(self, tmp_path):
        # The tree's own drags carry member URLs too (§4c); dragging a
        # playlist onto another playlist must stay a node move, i.e. refused.
        (a,) = make_files(tmp_path, "a.wav")
        mime = url_mime([a])
        mime.setData(NODE_MIME, b"7")
        assert tree_mod.PlaylistTree._is_track_drag(mime) is False

    def test_audio_urls_are_a_track_drag(self, tmp_path):
        (a,) = make_files(tmp_path, "a.wav")
        assert tree_mod.PlaylistTree._is_track_drag(url_mime([a])) is True

    def test_non_audio_urls_are_not(self, tmp_path):
        doc = tmp_path / "notes.txt"
        doc.write_text("nope")
        assert tree_mod.PlaylistTree._is_track_drag(url_mime([str(doc)])) is False


class TestDropTarget:
    def test_playlist_and_scratch_accept_tracks(self, tree, lib, monkeypatch):
        pl = lib.create_playlist("Set")
        tree.refresh()
        aim_at(tree, pl, monkeypatch)
        assert tree._track_drop_target(QPointF(0, 0).toPoint()) == pl
        aim_at(tree, SCRATCH_NODE_ID, monkeypatch)
        assert tree._track_drop_target(QPointF(0, 0).toPoint()) == SCRATCH_NODE_ID

    def test_folders_refuse_tracks(self, tree, lib, monkeypatch):
        folder = lib.create_folder("Gigs")
        tree.refresh()
        aim_at(tree, folder, monkeypatch)
        assert tree._track_drop_target(QPointF(0, 0).toPoint()) is None


class TestDropTracks:
    def test_drop_adds_and_reports_a_copy(self, tree, lib, tmp_path, monkeypatch):
        a, b = make_files(tmp_path, "a.wav", "b.wav")
        pl = lib.create_playlist("Set")
        tree.refresh()
        aim_at(tree, pl, monkeypatch)

        event = FakeDropEvent(url_mime([a, b]))
        tree._drop_tracks(event)

        assert [t.path for t in lib.get_items(pl)] == [a, b]
        assert event.accepted is True
        # The whole point: a move would have made the source list drop them.
        assert event.action == Qt.DropAction.CopyAction

    def test_source_playlist_keeps_its_tracks(self, tree, lib, tmp_path, monkeypatch):
        a, b = make_files(tmp_path, "a.wav", "b.wav")
        source = lib.create_playlist("Source")
        target = lib.create_playlist("Target")
        for path in (a, b):
            lib.add_items(source, [lib.add_track(path)])
        tree.refresh()
        aim_at(tree, target, monkeypatch)

        tree._drop_tracks(FakeDropEvent(url_mime([a, b])))

        assert [t.path for t in lib.get_items(source)] == [a, b]
        assert [t.path for t in lib.get_items(target)] == [a, b]

    def test_dropping_on_a_folder_does_nothing(self, tree, lib, tmp_path, monkeypatch):
        (a,) = make_files(tmp_path, "a.wav")
        folder = lib.create_folder("Gigs")
        tree.refresh()
        aim_at(tree, folder, monkeypatch)

        event = FakeDropEvent(url_mime([a]))
        tree._drop_tracks(event)

        assert event.accepted is False
        assert lib.track_count() == 0

    def test_emits_tracks_added(self, tree, lib, tmp_path, monkeypatch, qtbot):
        (a,) = make_files(tmp_path, "a.wav")
        pl = lib.create_playlist("Set")
        tree.refresh()
        aim_at(tree, pl, monkeypatch)

        with qtbot.waitSignal(tree.tracks_added, timeout=1000) as blocker:
            tree._drop_tracks(FakeDropEvent(url_mime([a])))
        assert blocker.args == [pl]

    def test_drop_is_undoable(self, tree, lib, stack, tmp_path, monkeypatch):
        a, b = make_files(tmp_path, "a.wav", "b.wav")
        pl = lib.create_playlist("Set")
        lib.add_items(pl, [lib.add_track(a)])
        tree.refresh()
        aim_at(tree, pl, monkeypatch)

        tree._drop_tracks(FakeDropEvent(url_mime([b])))
        assert stack.peek_label() == "Add Tracks"

        stack.undo()
        assert [t.path for t in lib.get_items(pl)] == [a]


class TestDuplicatePolicy:
    """§22: adding a track a playlist already holds.

    The prompt is deferred off the drop event, so these pump the event loop
    (``pump(qtbot)``) rather than expecting the add to have happened by the
    time ``_drop_tracks`` returns. The policy and the box are both patched:
    the box because a real one would block a headless run forever, and the
    policy because it is a user setting the suite must not depend on.
    """

    @staticmethod
    def answer(monkeypatch, verdict):
        """Patch the prompt to a fixed answer; returns the recorded calls.

        Overriding ``_prompt`` is also what tells the conftest guard this test
        means to reach the box.
        """
        asked = []

        def stub(parent, collisions, total, playlist_name):
            asked.append((collisions, total, playlist_name))
            return verdict

        monkeypatch.setattr(dup_mod, "_prompt", stub)
        return asked

    @staticmethod
    def policy(monkeypatch, value):
        monkeypatch.setattr(dup_mod, "current_policy", lambda: value)

    def seeded(self, tree, lib, tmp_path, monkeypatch, held, dropping):
        """A playlist already holding *held*, aimed at, ready for *dropping*."""
        pl = lib.create_playlist("Set")
        for path in held:
            lib.add_items(pl, [lib.add_track(path)])
        tree.refresh()
        aim_at(tree, pl, monkeypatch)
        return pl

    def test_a_clean_add_never_asks(self, tree, lib, tmp_path, monkeypatch, qtbot):
        a, b = make_files(tmp_path, "a.wav", "b.wav")
        pl = self.seeded(tree, lib, tmp_path, monkeypatch, [a], [b])
        asked = self.answer(monkeypatch, True)

        tree._drop_tracks(FakeDropEvent(url_mime([b])))
        pump(qtbot)

        assert asked == []
        assert [t.path for t in lib.get_items(pl)] == [a, b]

    def test_add_keeps_the_duplicate(self, tree, lib, tmp_path, monkeypatch, qtbot):
        (a,) = make_files(tmp_path, "a.wav")
        pl = self.seeded(tree, lib, tmp_path, monkeypatch, [a], [a])
        asked = self.answer(monkeypatch, True)

        tree._drop_tracks(FakeDropEvent(url_mime([a])))
        qtbot.waitUntil(lambda: len(lib.get_items(pl)) == 2, timeout=1000)

        assert [t.path for t in lib.get_items(pl)] == [a, a]
        assert asked == [(1, 1, "Set")]

    def test_skip_drops_only_the_duplicates(
        self, tree, lib, tmp_path, monkeypatch, qtbot
    ):
        a, b = make_files(tmp_path, "a.wav", "b.wav")
        pl = self.seeded(tree, lib, tmp_path, monkeypatch, [a], [a, b])
        asked = self.answer(monkeypatch, False)

        tree._drop_tracks(FakeDropEvent(url_mime([a, b])))
        qtbot.waitUntil(lambda: len(lib.get_items(pl)) == 2, timeout=1000)

        assert [t.path for t in lib.get_items(pl)] == [a, b]
        # The message distinguishes "some of these" from "all of these".
        assert asked == [(1, 2, "Set")]

    def test_cancel_adds_nothing_and_leaves_undo_alone(
        self, tree, lib, stack, tmp_path, monkeypatch, qtbot
    ):
        (a,) = make_files(tmp_path, "a.wav")
        pl = self.seeded(tree, lib, tmp_path, monkeypatch, [a], [a])
        self.answer(monkeypatch, None)

        tree._drop_tracks(FakeDropEvent(url_mime([a])))
        pump(qtbot)

        assert [t.path for t in lib.get_items(pl)] == [a]
        # A no-op entry here would swallow the next Cmd+Z.
        assert not stack.peek_label()

    def test_policy_add_never_asks(self, tree, lib, tmp_path, monkeypatch, qtbot):
        (a,) = make_files(tmp_path, "a.wav")
        pl = self.seeded(tree, lib, tmp_path, monkeypatch, [a], [a])
        self.policy(monkeypatch, "add")
        asked = self.answer(monkeypatch, True)

        tree._drop_tracks(FakeDropEvent(url_mime([a])))

        # Synchronous: no prompt means no deferral, so no pumping needed.
        assert [t.path for t in lib.get_items(pl)] == [a, a]
        assert asked == []

    def test_policy_skip_never_asks(self, tree, lib, tmp_path, monkeypatch, qtbot):
        a, b = make_files(tmp_path, "a.wav", "b.wav")
        pl = self.seeded(tree, lib, tmp_path, monkeypatch, [a], [a, b])
        self.policy(monkeypatch, "skip")
        asked = self.answer(monkeypatch, True)

        tree._drop_tracks(FakeDropEvent(url_mime([a, b])))

        assert [t.path for t in lib.get_items(pl)] == [a, b]
        assert asked == []

    def test_skip_collapses_repeats_inside_one_drop(
        self, tree, lib, tmp_path, monkeypatch
    ):
        """A batch holding the same file twice contributes one copy."""
        (a,) = make_files(tmp_path, "a.wav")
        pl = self.seeded(tree, lib, tmp_path, monkeypatch, [], [a, a])
        self.policy(monkeypatch, "skip")

        tree._drop_tracks(FakeDropEvent(url_mime([a, a])))

        assert [t.path for t in lib.get_items(pl)] == [a]

    def test_a_skipped_new_file_leaves_no_library_row(
        self, tree, lib, tmp_path, monkeypatch
    ):
        """Resolution runs before _track_id_for, so nothing is created."""
        a, b = make_files(tmp_path, "a.wav", "b.wav")
        pl = self.seeded(tree, lib, tmp_path, monkeypatch, [a], [a, a])
        self.policy(monkeypatch, "skip")
        before = lib.track_count()

        # b is dropped twice and is new: the second copy must not create a row.
        tree._drop_tracks(FakeDropEvent(url_mime([b, b])))

        assert lib.track_count() == before + 1

    def test_a_skipped_file_is_never_tag_read(
        self, tree, lib, tmp_path, monkeypatch, qtbot
    ):
        (a,) = make_files(tmp_path, "a.wav")
        self.seeded(tree, lib, tmp_path, monkeypatch, [a], [a])
        self.answer(monkeypatch, False)

        def explode(_path):
            raise AssertionError("a skipped file should not be tag-read")

        monkeypatch.setattr(tree_mod, "read_metadata", explode)
        tree._drop_tracks(FakeDropEvent(url_mime([a])))
        pump(qtbot)

    def test_the_filter_re_reads_the_playlist_after_the_answer(
        self, tree, lib, tmp_path, monkeypatch, qtbot
    ):
        """Two quick drops: the second must not diff against a stale list.

        The box for the second drop is answered *after* the first one landed,
        so what it skips has to be judged against the playlist as it is by
        then, not as it was when the drag started.
        """
        a, b = make_files(tmp_path, "a.wav", "b.wav")
        pl = self.seeded(tree, lib, tmp_path, monkeypatch, [a], [a, b])
        self.answer(monkeypatch, False)

        tree._drop_tracks(FakeDropEvent(url_mime([a, b])))  # b is new here
        tree._drop_tracks(FakeDropEvent(url_mime([b])))  # b is new here too...
        pump(qtbot)

        # ...but by the time the second box is answered, b has landed, so Skip
        # drops it rather than adding a second copy.
        assert [t.path for t in lib.get_items(pl)] == [a, b]


class TestRealDropEventRouting:
    """dropEvent's branch order, through an actual QDropEvent."""

    @staticmethod
    def _drop(mime):
        """Build a real QDropEvent.

        The caller MUST hold its own reference to *mime* for as long as the
        event lives: QDropEvent keeps only a raw pointer, so an inlined
        `self._drop(url_mime([...]))` lets Python collect the QMimeData and
        the first `event.mimeData()` segfaults.
        """
        return QDropEvent(
            QPointF(0, 0),
            Qt.DropAction.MoveAction | Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

    def test_a_file_drop_adds_tracks(self, tree, lib, tmp_path, monkeypatch):
        (a,) = make_files(tmp_path, "a.wav")
        pl = lib.create_playlist("Set")
        tree.refresh()
        aim_at(tree, pl, monkeypatch)

        mime = url_mime([a])  # must outlive the event — see _drop
        event = self._drop(mime)
        tree.dropEvent(event)

        assert [t.path for t in lib.get_items(pl)] == [a]
        assert event.dropAction() == Qt.DropAction.CopyAction

    def test_a_playlist_dragged_onto_a_playlist_is_refused(
        self, tree, lib, tmp_path, monkeypatch
    ):
        """It stays a node move — and playlists don't accept nodes."""
        (a,) = make_files(tmp_path, "a.wav")
        source = lib.create_playlist("Source")
        target = lib.create_playlist("Target")
        lib.add_items(source, [lib.add_track(a)])
        tree.refresh()
        aim_at(tree, target, monkeypatch)

        # A tree drag carries BOTH payloads, exactly like startDrag builds it.
        mime = url_mime([a])
        mime.setData(NODE_MIME, str(source).encode("ascii"))
        monkeypatch.setattr(
            tree,
            "dropIndicatorPosition",
            lambda: tree.DropIndicatorPosition.OnItem,
        )
        event = self._drop(mime)
        tree.dropEvent(event)

        # Not merged into the target, and not moved anywhere.
        assert lib.get_items(target) == []
        assert lib.get_node(source).parent_id is None


class TestTagsOnDrop:
    def test_a_new_file_gets_its_tags_read(self, tree, lib, tmp_path, monkeypatch):
        (a,) = make_files(tmp_path, "a.wav")
        pl = lib.create_playlist("Set")
        tree.refresh()
        aim_at(tree, pl, monkeypatch)
        monkeypatch.setattr(
            tree_mod,
            "read_metadata",
            lambda _p: TrackMetadata(artist="Nu Groove", title="Deep Cut", bpm=124.0),
        )

        tree._drop_tracks(FakeDropEvent(url_mime([a])))

        track = lib.get_items(pl)[0]
        assert (track.artist, track.title, track.bpm) == ("Nu Groove", "Deep Cut", 124.0)

    def test_a_known_file_is_not_re_read(self, tree, lib, tmp_path, monkeypatch):
        """Inline edits in the Player must not be rolled back by a drop."""
        (a,) = make_files(tmp_path, "a.wav")
        track_id = lib.add_track(a, artist="Edited By Hand")
        lib.add_items(SCRATCH_NODE_ID, [track_id])
        pl = lib.create_playlist("Set")
        tree.refresh()
        aim_at(tree, pl, monkeypatch)

        def explode(_path):
            raise AssertionError("tags should not be re-read for a known path")

        monkeypatch.setattr(tree_mod, "read_metadata", explode)
        tree._drop_tracks(FakeDropEvent(url_mime([a])))

        assert lib.get_items(pl)[0].artist == "Edited By Hand"

    def test_an_unreadable_file_still_lands(self, tree, lib, tmp_path, monkeypatch):
        (a,) = make_files(tmp_path, "a.wav")
        pl = lib.create_playlist("Set")
        tree.refresh()
        aim_at(tree, pl, monkeypatch)

        def explode(_path):
            raise OSError("corrupt")

        monkeypatch.setattr(tree_mod, "read_metadata", explode)
        tree._drop_tracks(FakeDropEvent(url_mime([a])))

        assert [t.path for t in lib.get_items(pl)] == [a]


class TestPathSpelling:
    """A dropped path is stored the way every other add route stores it.

    Path identity in the library is exact-string, so a drop that spells a file
    differently from the file dialog or a folder scan makes one file into two
    rows and blinds the duplicate check. That is exactly what Windows hit:
    ``QUrl.toLocalFile()`` returns ``C:/music/a.mp3`` there while the other
    routes return ``C:\\music\\a.mp3``.

    Separators can't be reproduced on a Mac, but the property under test isn't
    about separators — it is "two spellings of one file resolve to one row".
    A redundant ``sub/..`` segment gives a second spelling on every platform
    (QUrl passes dot segments through untouched, verified).
    """

    @staticmethod
    def detour(path):
        """The same file, spelled with a pointless round trip through a dir."""
        p = Path(path)
        (p.parent / "sub").mkdir(exist_ok=True)
        return str(p.parent / "sub" / ".." / p.name)

    def test_a_detoured_path_is_stored_canonically(
        self, tree, lib, tmp_path, monkeypatch
    ):
        (a,) = make_files(tmp_path, "a.wav")
        pl = lib.create_playlist("Set")
        tree.refresh()
        aim_at(tree, pl, monkeypatch)

        tree._drop_tracks(FakeDropEvent(url_mime([self.detour(a)])))

        assert [t.path for t in lib.get_items(pl)] == [a]

    def test_a_detoured_path_is_the_same_library_row(
        self, tree, lib, tmp_path, monkeypatch
    ):
        (a,) = make_files(tmp_path, "a.wav")
        known = lib.add_track(a, artist="Edited By Hand")
        pl = lib.create_playlist("Set")
        tree.refresh()
        aim_at(tree, pl, monkeypatch)

        tree._drop_tracks(FakeDropEvent(url_mime([self.detour(a)])))

        # One row, not two — and the row already there, tags intact.
        assert lib.track_count() == 1
        assert [t.id for t in lib.get_items(pl)] == [known]
        assert lib.get_items(pl)[0].artist == "Edited By Hand"

    def test_the_add_files_route_normalizes_too(self, tmp_path):
        """The other half of the bug, and the half no test covered.

        QFileDialog returns forward slashes on every platform, so on Windows
        Add Files hands the Player ``C:/music/a.mp3`` while a folder scan hands
        it ``C:\\music\\a.mp3``. Driven as an unbound method against a stub —
        the same trick TestPlayerRefreshHandoff uses — because the routing is
        all this needs, not a whole MainWindow.
        """
        (a,) = make_files(tmp_path, "a.wav")

        class StubPanel:
            def __init__(self):
                self.tracks = None

            def add_tracks(self, tracks):
                self.tracks = tracks

        class StubWindow:
            def __init__(self):
                self._player_panel = StubPanel()

        window = StubWindow()
        MainWindow._add_files_to_player(window, [self.detour(a)])

        assert [t["file_path"] for t in window._player_panel.tracks] == [a]

    def test_a_detoured_path_counts_as_a_duplicate(
        self, tree, lib, tmp_path, monkeypatch, qtbot
    ):
        """The Windows symptom: 'skip' saw no duplicates and added them all."""
        (a,) = make_files(tmp_path, "a.wav")
        pl = lib.create_playlist("Set")
        lib.add_items(pl, [lib.add_track(a)])
        tree.refresh()
        aim_at(tree, pl, monkeypatch)
        monkeypatch.setattr(dup_mod, "current_policy", lambda: "skip")

        tree._drop_tracks(FakeDropEvent(url_mime([self.detour(a)])))
        pump(qtbot)

        assert [t.path for t in lib.get_items(pl)] == [a]


class TestPlayerRefreshHandoff:
    """MainWindow reloads the Player only when the drop hit its list."""

    class _Stub:
        def __init__(self, loaded, ):
            self.loaded_node_id = loaded
            self.reloaded = []

        def load_node(self, node_id):
            self.reloaded.append(node_id)

    def test_reloads_when_the_drop_hit_the_loaded_list(self):
        stub = self._Stub(loaded=7)
        window = type("W", (), {"_player_panel": stub})()
        MainWindow._on_tracks_added(window, 7)
        assert stub.reloaded == [7]

    def test_leaves_the_player_alone_otherwise(self):
        stub = self._Stub(loaded=7)
        window = type("W", (), {"_player_panel": stub})()
        MainWindow._on_tracks_added(window, 9)
        assert stub.reloaded == []


class TestPlayerDragGuard:
    def test_guard_is_wired_into_the_table(self, player):
        assert player._table._drag_guard_fn == player._guard_drag

    def test_present_files_drag_freely(self, player, tmp_path):
        a, b = make_files(tmp_path, "a.wav", "b.wav")
        player.add_tracks(track_dicts([a, b]))
        player._table.selectAll()
        assert player._guard_drag() is True

    def test_a_moved_file_is_refused_marked_and_announced(
        self, player, tmp_path, monkeypatch, qtbot
    ):
        # The cache case: the row looks fine (and may still be playing)
        # because nothing has re-checked the disk since it was added.
        (a,) = make_files(tmp_path, "a.wav")
        player.add_tracks(track_dicts([a]))
        assert player._table.item(0, 1).text() == "a.wav"
        Path(a).unlink()

        shown = []
        monkeypatch.setattr(QMessageBox, "exec", lambda box: shown.append(box.text()))
        player._table.selectRow(0)
        assert player._guard_drag() is False
        assert player._table.item(0, 1).text() == "! a.wav"

        # The box is deferred off the drag handler with a zero-delay timer.
        qtbot.waitUntil(lambda: bool(shown), timeout=1000)
        assert "a.wav" in shown[0]

    def test_one_missing_file_refuses_the_whole_selection(
        self, player, tmp_path, monkeypatch, qtbot
    ):
        a, b = make_files(tmp_path, "a.wav", "b.wav")
        player.add_tracks(track_dicts([a, b]))
        Path(b).unlink()

        monkeypatch.setattr(QMessageBox, "exec", lambda box: None)
        player._table.selectAll()
        assert player._guard_drag() is False

    def test_multi_select_drag_carries_every_selected_row(self, player, tmp_path):
        a, b, c = make_files(tmp_path, "a.wav", "b.wav", "c.wav")
        player.add_tracks(track_dicts([a, b, c]))
        player._table.selectAll()

        paths, _remove = player._drag_data()
        assert paths == [a, b, c]
