"""Playlist tree: model building, CRUD write-through, drag-move semantics."""

import pytest
from PySide6.QtWidgets import QMessageBox

from src.gui.widgets.playlist_tree import (
    KIND_ROLE,
    NODE_ID_ROLE,
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
