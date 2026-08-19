"""Playlist tree: model building, CRUD write-through, drag-move semantics."""

import pytest
from PySide6.QtWidgets import QMessageBox

from src.gui.widgets.playlist_tree import (
    KIND_ROLE,
    NODE_ID_ROLE,
    _ROW_ADD_MARGIN,
    PlaylistTreePanel,
)
from src.gui.widgets.droppable_table import SOURCE_PAGE_MIME
from src.library import SCRATCH_NODE_ID


@pytest.fixture
def panel(qtbot, tmp_path):
    p = PlaylistTreePanel(db_path=tmp_path / "library.db")
    qtbot.addWidget(p)
    p.ensure_loaded()
    return p


@pytest.fixture
def tree(panel):
    return panel.tree


def root_ids(tree) -> list[int]:
    root = tree._model.invisibleRootItem()
    return [root.child(r).data(NODE_ID_ROLE) for r in range(root.rowCount())]


class TestModel:
    def test_sorting_is_never_enabled(self, tree):
        # Manual order is authoritative; a view-level sort would scramble
        # nodes.position under auto-save. This must stay False forever.
        assert tree.isSortingEnabled() is False

    def test_scratch_pinned_first_and_locked(self, tree):
        root = tree._model.invisibleRootItem()
        scratch = root.child(0)
        assert scratch.data(NODE_ID_ROLE) == SCRATCH_NODE_ID
        assert scratch.data(KIND_ROLE) == "scratch"
        assert not scratch.isEditable()
        assert not scratch.isDragEnabled()
        assert not scratch.isDropEnabled()

    def test_newest_node_appears_at_top_below_scratch(self, tree):
        lib = tree.library
        a = lib.create_playlist("A")
        b = lib.create_folder("B")
        tree._rebuild()
        assert root_ids(tree) == [SCRATCH_NODE_ID, b, a]

    def test_playlists_reject_node_drops_folders_accept(self, tree):
        lib = tree.library
        lib.create_playlist("P")
        lib.create_folder("F")
        tree._rebuild()
        root = tree._model.invisibleRootItem()
        by_kind = {root.child(r).data(KIND_ROLE): root.child(r) for r in range(root.rowCount())}
        assert by_kind["folder"].isDropEnabled()
        assert not by_kind["playlist"].isDropEnabled()

    def test_rebuild_preserves_expansion(self, tree):
        lib = tree.library
        outer = lib.create_folder("Outer")
        lib.create_playlist("P", parent_id=outer)
        tree._rebuild()
        tree.setExpanded(tree._find_item(outer).index(), True)
        tree._rebuild()
        assert tree.isExpanded(tree._find_item(outer).index())


class TestExpansionPersistence:
    """The tree comes back the shape the user left it in."""

    def test_expanding_writes_through(self, tree):
        lib = tree.library
        outer = lib.create_folder("Outer")
        lib.create_playlist("P", parent_id=outer)
        tree._rebuild()

        tree.setExpanded(tree._find_item(outer).index(), True)
        assert lib.expanded_node_ids() == {outer}

        tree.setExpanded(tree._find_item(outer).index(), False)
        assert lib.expanded_node_ids() == set()

    def test_a_rebuild_does_not_clobber_the_stored_set(self, tree):
        """The replay inside _rebuild is us restoring, not the user acting —
        it must leave the stored state exactly as it found it."""
        lib = tree.library
        outer = lib.create_folder("Outer")
        lib.create_folder("Other")
        lib.create_playlist("P", parent_id=outer)
        tree._rebuild()
        tree.setExpanded(tree._find_item(outer).index(), True)

        for _ in range(3):
            tree._rebuild()

        assert lib.expanded_node_ids() == {outer}

    def test_a_new_tree_on_the_same_database_opens_the_same_folders(
        self, qtbot, tmp_path
    ):
        """The point of the whole feature: quit with a folder open, come back
        to it open."""
        db = tmp_path / "library.db"
        first = PlaylistTreePanel(db_path=db)
        qtbot.addWidget(first)
        first.ensure_loaded()
        outer = first.tree.library.create_folder("Outer")
        closed = first.tree.library.create_folder("Closed")
        first.tree.library.create_playlist("P", parent_id=outer)
        first.tree._rebuild()
        first.tree.setExpanded(first.tree._find_item(outer).index(), True)
        first.tree.library.close()  # the "quit"

        second = PlaylistTreePanel(db_path=db)
        qtbot.addWidget(second)
        second.ensure_loaded()

        assert second.tree.isExpanded(second.tree._find_item(outer).index())
        assert not second.tree.isExpanded(second.tree._find_item(closed).index())
        second.tree.library.close()


class TestCrud:
    def test_create_buttons_write_to_db(self, panel, tree):
        panel._new_playlist_btn.click()
        panel._new_folder_btn.click()
        children = tree.library.get_children()
        assert [n.kind for n in children] == ["folder", "playlist"]
        assert children[0].name == "New Folder"
        assert children[1].name == "New Playlist"

    def test_inline_rename_writes_through(self, tree):
        node_id = tree.library.create_playlist("Old Name")
        tree._rebuild()
        tree._find_item(node_id).setText("Summer Set")
        assert tree.library.get_node(node_id).name == "Summer Set"

    def test_empty_rename_reverts(self, tree):
        node_id = tree.library.create_playlist("Keep Me")
        tree._rebuild()
        item = tree._find_item(node_id)
        item.setText("   ")
        assert tree.library.get_node(node_id).name == "Keep Me"
        assert item.text() == "Keep Me"

    def test_delete_confirms_and_cascades(self, tree, monkeypatch):
        lib = tree.library
        folder = lib.create_folder("F")
        inner = lib.create_playlist("P", parent_id=folder)
        tree._rebuild()

        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No
        )
        tree._delete_node(folder)
        assert lib.get_node(folder) is not None  # No leaves everything alone

        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
        )
        tree._delete_node(folder)
        assert lib.get_node(folder) is None
        assert lib.get_node(inner) is None
        assert tree._find_item(folder) is None


class TestRowAddButton:
    """The floating create button at the tree's right edge."""

    @staticmethod
    def _shown(panel, qtbot):
        panel.resize(240, 320)
        panel.show()
        qtbot.wait(10)

    def test_playlist_button_creates_a_sibling_directly_below(self, tree):
        lib = tree.library
        folder = lib.create_folder("Crates")
        third = lib.create_playlist("Third", parent_id=folder)
        anchor = lib.create_playlist("Anchor", parent_id=folder)
        first = lib.create_playlist("First", parent_id=folder)  # newest on top
        tree._rebuild()
        assert [n.id for n in lib.get_children(folder)] == [first, anchor, third]

        tree._row_add_node_id = anchor
        tree._on_row_add_clicked()

        ids = [n.id for n in lib.get_children(folder)]
        assert ids[0] == first and ids[1] == anchor and ids[3] == third
        new = lib.get_node(ids[2])
        assert new.kind == "playlist"
        assert new.parent_id == folder  # same folder, not the root

    def test_playlist_button_at_the_root_stays_at_the_root(self, tree):
        lib = tree.library
        anchor = lib.create_playlist("Anchor")
        tree._rebuild()
        tree._row_add_node_id = anchor
        tree._on_row_add_clicked()
        ids = [n.id for n in lib.get_children(None)]
        assert ids[0] == anchor
        assert lib.get_node(ids[1]).parent_id is None

    def test_folder_button_creates_a_playlist_at_the_top_inside(self, tree):
        lib = tree.library
        folder = lib.create_folder("Crates")
        existing = lib.create_playlist("Already here", parent_id=folder)
        tree._rebuild()
        tree._row_add_node_id = folder
        tree._on_row_add_clicked()
        # Inside the folder, not beside it.
        assert [n.id for n in lib.get_children(None)] == [folder]
        children = lib.get_children(folder)
        assert len(children) == 2
        # A playlist (folders are the right-click menu's job), at the top.
        assert children[0].kind == "playlist"
        assert children[1].id == existing

    def test_stale_aim_after_a_delete_creates_nothing(self, tree):
        lib = tree.library
        node_id = lib.create_playlist("Gone")
        tree._rebuild()
        lib.delete_node(node_id)
        tree._row_add_node_id = node_id  # the hover the button was left with
        tree._on_row_add_clicked()
        assert lib.get_children(None) == []

    def test_button_rides_the_viewport_edge_not_the_item_rect(self, panel, tree, qtbot):
        lib = tree.library
        # Long enough that the item rect runs well past the viewport: the
        # column is ResizeToContents with ElideNone, so a row's own right edge
        # is nowhere near the tree's.
        node_id = lib.create_playlist("A very long playlist name indeed, honestly")
        tree._rebuild()
        self._shown(panel, qtbot)

        rect = tree.visualRect(tree._find_item(node_id).index())
        tree._aim_row_add_button(rect.center())

        btn = tree._row_add_btn
        assert not btn.isHidden()
        assert tree._row_add_node_id == node_id
        assert btn.geometry().right() == tree.viewport().width() - _ROW_ADD_MARGIN - 1
        assert rect.top() <= btn.geometry().center().y() <= rect.bottom()

    def test_button_survives_the_cursor_travelling_to_it(self, panel, tree, qtbot):
        # The button sits well past the end of a short name, and the single
        # column is only as wide as its content — so the cursor crosses "empty
        # space" on its way there. A cell-wise hit test hides the button
        # mid-reach and it can never be clicked.
        lib = tree.library
        node_id = lib.create_playlist("Hi")
        tree._rebuild()
        self._shown(panel, qtbot)

        rect = tree.visualRect(tree._find_item(node_id).index())
        tree._aim_row_add_button(rect.center())
        btn_centre = tree._row_add_btn.geometry().center()
        assert btn_centre.x() > rect.right()  # genuinely outside the item rect

        tree._aim_row_add_button(btn_centre)
        assert not tree._row_add_btn.isHidden()
        assert tree._row_add_node_id == node_id

    def test_no_button_on_the_scratch_row(self, panel, tree, qtbot):
        lib = tree.library
        node_id = lib.create_playlist("Real")
        tree._rebuild()
        self._shown(panel, qtbot)

        tree._aim_row_add_button(tree.visualRect(tree._find_item(node_id).index()).center())
        assert not tree._row_add_btn.isHidden()  # it was showing…

        scratch = tree.visualRect(tree._find_item(SCRATCH_NODE_ID).index())
        tree._aim_row_add_button(scratch.center())
        assert tree._row_add_btn.isHidden()  # …and Scratch takes it away
        assert tree._row_add_node_id is None


class TestMoves:
    def test_reorder_within_root(self, tree):
        lib = tree.library
        a = lib.create_playlist("A")
        b = lib.create_playlist("B")
        c = lib.create_playlist("C")  # order now: C, B, A
        tree._rebuild()

        # Drag C below A. Qt-style row counted with C still in place -> 3,
        # minus 1 for Scratch at model row 0 handled by the caller; here we
        # exercise _apply_move directly with the library-space row.
        assert tree._apply_move(c, None, 3)
        assert [n.id for n in lib.get_children()] == [b, a, c]
        assert root_ids(tree) == [SCRATCH_NODE_ID, b, a, c]

    def test_reparent_into_folder(self, tree):
        lib = tree.library
        p = lib.create_playlist("P")
        f = lib.create_folder("F")
        tree._rebuild()
        assert tree._apply_move(p, f, 0)
        assert [n.id for n in lib.get_children(f)] == [p]
        # Destination folder is expanded so the moved node stays visible.
        assert tree.isExpanded(tree._find_item(f).index())

    def test_cycle_rejected(self, tree):
        lib = tree.library
        outer = lib.create_folder("Outer")
        inner = lib.create_folder("Inner")
        tree._rebuild()
        assert tree._apply_move(inner, outer, 0)
        assert not tree._apply_move(outer, inner, 0)  # refuse, don't crash
        assert lib.get_node(outer).parent_id is None


class TestDragPayload:
    def test_paths_under_playlist_and_folder(self, tree, tmp_path):
        lib = tree.library
        files = []
        for name in ("a.aiff", "b.aiff", "c.aiff"):
            f = tmp_path / name
            f.write_bytes(b"x")
            files.append(str(f))

        folder = lib.create_folder("Crate")
        p1 = lib.create_playlist("One", parent_id=folder)
        p2 = lib.create_playlist("Two", parent_id=folder)
        t = [lib.add_track(f) for f in files]
        lib.add_items(p1, [t[0], t[1]])
        lib.add_items(p2, [t[1], t[2]])  # t[1] shared across both

        assert tree._paths_under(p1, "playlist") == [files[0], files[1]]
        # Folder: flattened subtree, deduped, first occurrence wins.
        assert tree._paths_under(folder, "folder") == [files[1], files[2], files[0]]

    def test_source_marker_constant(self):
        assert SOURCE_PAGE_MIME  # the drag marker the sidebar routes on
