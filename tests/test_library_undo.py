"""Library snapshot/restore primitives behind the session undo stack (§11).

The hard parts these cover: a restore has to survive the track garbage
collector (removing a track's last membership deletes its row), it has to
put a cascaded subtree back with its structure, order, and contents intact,
and it must not roll back tag edits that happened after the snapshot —
undo reverses playlist structure, never file contents.
"""

import pytest

from src.library import Library


@pytest.fixture
def lib(tmp_path):
    library = Library(tmp_path / "library.db")
    yield library
    library.close()


@pytest.fixture
def files(tmp_path):
    paths = []
    for name in ("a.wav", "b.wav", "c.wav"):
        f = tmp_path / name
        f.write_bytes(b"audio-" + name.encode())
        paths.append(str(f))
    return paths


class TestItemSnapshots:
    def test_restore_after_gc_recreates_the_track_rows(self, lib, files):
        pl = lib.create_playlist("Set")
        lib.set_items(pl, [lib.add_track(p, artist="DJ", bpm=128.0) for p in files])
        snap = lib.snapshot_items(pl)

        lib.set_items(pl, [])  # every track loses its last membership
        assert lib.track_count() == 0

        lib.restore_items(pl, snap)
        restored = lib.get_items(pl)
        assert [t.path for t in restored] == files
        assert [t.artist for t in restored] == ["DJ"] * 3
        assert [t.bpm for t in restored] == [128.0] * 3

    def test_restore_preserves_order_and_duplicates(self, lib, files):
        a, b, _ = files
        pl = lib.create_playlist("Set")
        ids = [lib.add_track(a), lib.add_track(b)]
        lib.set_items(pl, [ids[0], ids[1], ids[0]])
        snap = lib.snapshot_items(pl)

        lib.set_items(pl, [ids[1]])
        lib.restore_items(pl, snap)
        assert [t.path for t in lib.get_items(pl)] == [a, b, a]

    def test_restore_keeps_tags_edited_since_the_snapshot(self, lib, files):
        # The track survives in another playlist, gets retagged there, then
        # the first playlist's removal is undone. Undo owns playlist
        # structure; it must not drag the old tags back with it.
        a = files[0]
        keep = lib.create_playlist("Keep")
        edit = lib.create_playlist("Edited")
        tid = lib.add_track(a, artist="Old", bpm=120.0)
        lib.set_items(keep, [tid])
        lib.set_items(edit, [tid])
        snap = lib.snapshot_items(keep)

        lib.set_items(keep, [])
        lib.update_track_tags(tid, artist="New", bpm=128.0)
        lib.restore_items(keep, snap)

        (restored,) = lib.get_items(keep)
        assert restored.artist == "New"
        assert restored.bpm == 128.0
        assert restored.id == tid  # same row, not a duplicate


class TestSubtreeSnapshots:
    def test_folder_delete_round_trips(self, lib, files):
        folder = lib.create_folder("Crates")
        peak = lib.create_playlist("Peak", folder)
        warm = lib.create_playlist("Warm", folder)
        other = lib.create_playlist("Top")  # root sibling, must not move
        lib.set_items(peak, [lib.add_track(p) for p in files])
        lib.set_items(warm, [lib.add_track(files[0])])

        before_root = [(n.id, n.name, n.position) for n in lib.get_children(None)]
        before_kids = [(n.id, n.name, n.position) for n in lib.get_children(folder)]

        snap = lib.snapshot_subtree(folder)
        lib.delete_node(folder)
        assert [n.id for n in lib.get_children(None)] == [other]
        assert lib.track_count() == 0  # contents cascaded and were collected

        assert lib.restore_subtree(snap) == folder
        assert [(n.id, n.name, n.position) for n in lib.get_children(None)] == before_root
        assert [(n.id, n.name, n.position) for n in lib.get_children(folder)] == before_kids
        assert [t.path for t in lib.get_items(peak)] == files
        assert [t.path for t in lib.get_items(warm)] == [files[0]]

    def test_restore_brings_back_the_expansion_state(self, lib):
        """Undoing a delete should give back the tree the user had, open
        folders included — not a subtree collapsed flat."""
        outer = lib.create_folder("Outer")
        inner = lib.create_folder("Inner", outer)
        lib.set_node_expanded(outer, True)

        snap = lib.snapshot_subtree(outer)
        lib.delete_node(outer)
        lib.restore_subtree(snap)

        assert lib.expanded_node_ids() == {outer}
        assert lib.get_node(inner).expanded is False

    def test_restore_lands_between_the_right_siblings(self, lib):
        # Newest-first creation means these sit [c, b, a]; deleting the
        # middle one and undoing must put it back in the middle.
        a = lib.create_playlist("A")
        b = lib.create_playlist("B")
        c = lib.create_playlist("C")
        assert [n.id for n in lib.get_children(None)] == [c, b, a]

        snap = lib.snapshot_subtree(b)
        lib.delete_node(b)
        assert [n.id for n in lib.get_children(None)] == [c, a]
        lib.restore_subtree(snap)
        assert [n.id for n in lib.get_children(None)] == [c, b, a]

    def test_reused_id_forces_a_remap(self, lib, files):
        # SQLite hands out max(id)+1, so creating a node after the delete can
        # claim the deleted id. The restore must not collide with it.
        folder = lib.create_folder("Crates")
        inner = lib.create_playlist("Inner", folder)
        lib.set_items(inner, [lib.add_track(files[0])])
        snap = lib.snapshot_subtree(folder)
        lib.delete_node(folder)

        squatters = [lib.create_playlist(f"New {i}") for i in range(3)]
        assert folder in squatters or inner in squatters  # ids really were reused

        new_root = lib.restore_subtree(snap)
        node = lib.get_node(new_root)
        assert node is not None and node.name == "Crates"
        (child,) = lib.get_children(new_root)
        assert child.name == "Inner"
        assert [t.path for t in lib.get_items(child.id)] == [files[0]]
        # Nothing was overwritten: the squatters are all still there.
        assert {n.id for n in lib.get_children(None)} >= set(squatters)

    def test_orphaned_parent_restores_at_the_root(self, lib):
        outer = lib.create_folder("Outer")
        inner = lib.create_playlist("Inner", outer)
        snap = lib.snapshot_subtree(inner)
        lib.delete_node(inner)
        lib.delete_node(outer)  # the parent it remembers is gone too

        restored = lib.restore_subtree(snap)
        node = lib.get_node(restored)
        assert node is not None
        assert node.parent_id is None
        assert node.name == "Inner"

    def test_scratch_cannot_be_snapshotted(self, lib):
        from src.library import SCRATCH_NODE_ID

        with pytest.raises(ValueError):
            lib.snapshot_subtree(SCRATCH_NODE_ID)
