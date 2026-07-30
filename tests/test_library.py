"""Tests for the playlist library data layer."""

import sqlite3
from pathlib import Path

import pytest

from src.library import (
    SCRATCH_NODE_ID,
    Library,
    compute_content_id,
    update_paths,
)


@pytest.fixture(params=["fts", "like"])
def lib(request, tmp_path):
    """A fresh library, run once with FTS5 and once on the LIKE fallback."""
    library = Library(tmp_path / "library.db", enable_fts=request.param == "fts")
    yield library
    library.close()


def make_files(tmp_path, *names, content=b"audio-bytes"):
    paths = []
    for name in names:
        p = tmp_path / name
        p.write_bytes(content + name.encode())
        paths.append(str(p))
    return paths


class TestSchema:
    def test_scratch_exists_and_reopen_is_idempotent(self, tmp_path):
        db = tmp_path / "library.db"
        with Library(db) as lib:
            scratch = lib.get_node(SCRATCH_NODE_ID)
            assert scratch is not None
            assert scratch.kind == "scratch"
        with Library(db) as lib:
            assert lib.get_node(SCRATCH_NODE_ID).kind == "scratch"
            assert len([n for n in lib.get_children() if n.kind == "scratch"]) == 0

    def test_scratch_is_protected(self, lib):
        with pytest.raises(ValueError):
            lib.rename_node(SCRATCH_NODE_ID, "Nope")
        with pytest.raises(ValueError):
            lib.delete_node(SCRATCH_NODE_ID)
        with pytest.raises(ValueError):
            lib.move_node(SCRATCH_NODE_ID, None, 0)

    def test_v1_database_gains_the_expanded_column(self, tmp_path):
        """A library written before v2 must open, not crash.

        CREATE TABLE IF NOT EXISTS leaves an existing nodes table exactly as
        it was, so the ALTER in _migrate is the only thing standing between
        an upgrading user and an unreadable library.
        """
        db = tmp_path / "library.db"
        con = sqlite3.connect(db)
        con.executescript(
            """
            CREATE TABLE nodes (
                id INTEGER PRIMARY KEY,
                parent_id INTEGER REFERENCES nodes(id) ON DELETE CASCADE,
                kind TEXT NOT NULL CHECK (kind IN ('folder', 'playlist', 'scratch')),
                name TEXT NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            INSERT INTO nodes (id, parent_id, kind, name, position, created_at)
            VALUES (1, NULL, 'scratch', 'Scratch', -1, 'then'),
                   (2, NULL, 'folder', 'Gigs', 0, 'then');
            PRAGMA user_version=1;
            """
        )
        con.commit()
        con.close()

        with Library(db) as lib:
            folder = lib.get_node(2)
            assert folder.name == "Gigs"
            assert folder.expanded is False  # pre-v2 rows default to collapsed
            lib.set_node_expanded(2, True)
            assert lib.expanded_node_ids() == {2}

    def test_pre_v3_database_gains_a_searchable_comment(self, tmp_path):
        """An FTS5 table's columns are fixed at creation, so the upgrade has
        to drop and rebuild the index — otherwise the new field is stored but
        never searchable for anyone who already had a library."""
        db = tmp_path / "library.db"
        with Library(db) as lib:
            if not lib.has_fts:
                pytest.skip("FTS5 unavailable in this Python build")
        # Roll the tracks table and its index back to their pre-v3 shape.
        con = sqlite3.connect(db)
        con.executescript(
            """
            ALTER TABLE tracks DROP COLUMN comment;
            DROP TABLE tracks_fts;
            CREATE VIRTUAL TABLE tracks_fts USING fts5(artist, title, album, filename);
            PRAGMA user_version=2;
            """
        )
        con.commit()
        con.close()

        (path,) = make_files(tmp_path, "one.aiff")
        with Library(db) as lib:
            playlist = lib.create_playlist("Set")
            tid = lib.add_track(path, artist="Anz", comment="peak time roller")
            lib.add_items(playlist, [tid])
            assert lib.get_track(tid).comment == "peak time roller"
            assert lib.search("roller") == [tid]

    def test_migration_is_idempotent(self, tmp_path):
        db = tmp_path / "library.db"
        for _ in range(3):
            with Library(db) as lib:
                assert lib.get_node(SCRATCH_NODE_ID) is not None

    def test_invalid_kind_rejected_by_schema(self, lib):
        with pytest.raises(sqlite3.IntegrityError):
            lib._con.execute(
                "INSERT INTO nodes (parent_id, kind, name, position, created_at)"
                " VALUES (NULL, 'bogus', 'x', 0, 'now')"
            )


class TestTracks:
    def test_add_track_upserts_by_path(self, lib, tmp_path):
        (path,) = make_files(tmp_path, "one.aiff")
        tid = lib.add_track(path, artist="Anz", title="Cadence")
        assert lib.add_track(path) == tid  # same path -> same id, tags untouched
        track = lib.get_track(tid)
        assert (track.artist, track.title) == ("Anz", "Cadence")

        lib.add_track(path, title="Cadence (VIP)")  # partial update
        track = lib.get_track(tid)
        assert (track.artist, track.title) == ("Anz", "Cadence (VIP)")

    def test_add_track_records_file_stats(self, lib, tmp_path):
        (path,) = make_files(tmp_path, "one.aiff")
        track = lib.get_track(lib.add_track(path))
        assert track.size > 0
        assert track.mtime is not None
        assert track.content_id == compute_content_id(path)
        assert track.filename == "one.aiff"

    def test_content_id_distinguishes_content(self, tmp_path):
        a, b = make_files(tmp_path, "a.wav", "b.wav")
        assert compute_content_id(a) != compute_content_id(b)
        assert compute_content_id(tmp_path / "missing.wav") is None

    def test_update_track_tags_rejects_unknown_columns(self, lib, tmp_path):
        (path,) = make_files(tmp_path, "one.aiff")
        tid = lib.add_track(path)
        with pytest.raises(ValueError):
            lib.update_track_tags(tid, path="/etc/passwd")


class TestTree:
    def test_new_nodes_go_to_top_and_order_persists(self, tmp_path):
        db = tmp_path / "library.db"
        with Library(db) as lib:
            a = lib.create_playlist("A")
            b = lib.create_folder("B")
            c = lib.create_playlist("C")
            assert [n.id for n in lib.get_children()] == [c, b, a]
            lib.set_child_order(None, [b, a, c])
        with Library(db) as lib:  # user-set order survives restart
            assert [n.id for n in lib.get_children()] == [b, a, c]

    def test_set_child_order_requires_permutation(self, lib):
        a = lib.create_playlist("A")
        lib.create_playlist("B")
        with pytest.raises(ValueError):
            lib.set_child_order(None, [a])

    def test_move_node_reparents_and_renumbers(self, lib):
        folder = lib.create_folder("Folder")
        a = lib.create_playlist("A")
        b = lib.create_playlist("B")
        lib.move_node(a, folder, 0)
        assert [n.id for n in lib.get_children(folder)] == [a]
        assert [n.id for n in lib.get_children()] == [b, folder]
        assert lib.ancestor_ids(a) == [folder]

    def test_move_node_rejects_cycles_and_playlist_parents(self, lib):
        outer = lib.create_folder("Outer")
        inner = lib.create_folder("Inner")
        playlist = lib.create_playlist("P")
        lib.move_node(inner, outer, 0)
        with pytest.raises(ValueError):
            lib.move_node(outer, inner, 0)
        with pytest.raises(ValueError):
            lib.move_node(inner, playlist, 0)
        with pytest.raises(ValueError):
            lib.create_playlist("Q", parent_id=playlist)

    def test_expansion_survives_a_restart(self, tmp_path):
        db = tmp_path / "library.db"
        with Library(db) as lib:
            outer = lib.create_folder("Outer")
            inner = lib.create_folder("Inner", parent_id=outer)
            lib.set_node_expanded(outer, True)
            lib.set_node_expanded(inner, True)
            lib.set_node_expanded(inner, False)
        with Library(db) as lib:
            assert lib.expanded_node_ids() == {outer}
            assert lib.get_node(outer).expanded is True
            assert lib.get_node(inner).expanded is False

    def test_expanding_a_deleted_folder_is_a_no_op(self, lib):
        """The write races a delete on the drop/undo paths; it must not raise."""
        folder = lib.create_folder("Gone")
        lib.delete_node(folder)
        lib.set_node_expanded(folder, True)
        assert lib.expanded_node_ids() == set()

    def test_delete_folder_cascades(self, lib, tmp_path):
        (path,) = make_files(tmp_path, "one.aiff")
        folder = lib.create_folder("Folder")
        playlist = lib.create_playlist("P", parent_id=folder)
        tid = lib.add_track(path)
        lib.add_items(playlist, [tid])
        lib.delete_node(folder)
        assert lib.get_node(folder) is None
        assert lib.get_node(playlist) is None
        assert lib.get_track(tid) is None  # orphan GC'd with its last playlist


class TestItems:
    def test_duplicates_allowed_and_order_kept(self, lib, tmp_path):
        one, two = make_files(tmp_path, "one.aiff", "two.aiff")
        playlist = lib.create_playlist("Set")
        t1, t2 = lib.add_track(one), lib.add_track(two)
        lib.add_items(playlist, [t1, t2, t1])  # same track twice, on purpose
        assert lib.get_item_track_ids(playlist) == [t1, t2, t1]
        assert lib.item_count(playlist) == 3

    def test_splice_remove_and_move(self, lib, tmp_path):
        paths = make_files(tmp_path, "a.wav", "b.wav", "c.wav")
        playlist = lib.create_playlist("Set")
        a, b, c = (lib.add_track(p) for p in paths)
        lib.add_items(playlist, [a, c])
        lib.add_items(playlist, [b], position=1)
        assert lib.get_item_track_ids(playlist) == [a, b, c]
        lib.move_item(playlist, 0, 2)
        assert lib.get_item_track_ids(playlist) == [b, c, a]
        lib.remove_items(playlist, [1])
        assert lib.get_item_track_ids(playlist) == [b, a]

    def test_items_only_on_playlists(self, lib, tmp_path):
        (path,) = make_files(tmp_path, "one.aiff")
        folder = lib.create_folder("F")
        tid_holder = lib.create_playlist("holder")
        tid = lib.add_track(path)
        lib.add_items(tid_holder, [tid])
        with pytest.raises(ValueError):
            lib.add_items(folder, [tid])

    def test_scratch_holds_items(self, lib, tmp_path):
        (path,) = make_files(tmp_path, "one.aiff")
        tid = lib.add_track(path)
        lib.add_items(SCRATCH_NODE_ID, [tid])
        assert lib.get_item_track_ids(SCRATCH_NODE_ID) == [tid]

    def test_orphan_gc_waits_for_last_membership(self, lib, tmp_path):
        (path,) = make_files(tmp_path, "one.aiff")
        p1, p2 = lib.create_playlist("P1"), lib.create_playlist("P2")
        tid = lib.add_track(path)
        lib.add_items(p1, [tid])
        lib.add_items(p2, [tid])
        lib.remove_items(p1, [0])
        assert lib.get_track(tid) is not None  # still in P2
        lib.remove_items(p2, [0])
        assert lib.get_track(tid) is None  # last membership gone


class TestMembership:
    def test_counts_and_reverse_lookup_exclude_scratch(self, lib, tmp_path):
        one, two = make_files(tmp_path, "one.aiff", "two.aiff")
        warm = lib.create_playlist("Warmup")
        peak = lib.create_playlist("Peak")
        t1, t2 = lib.add_track(one), lib.add_track(two)
        lib.add_items(warm, [t1, t2])
        lib.add_items(peak, [t1, t1])  # duplicate: still one playlist
        lib.add_items(SCRATCH_NODE_ID, [t1])

        assert lib.membership_counts([t1, t2]) == {t1: 2, t2: 1}
        assert [n.name for n in lib.playlists_containing(t1)] == ["Peak", "Warmup"]
        assert [n.name for n in lib.playlists_containing(t2)] == ["Warmup"]


class TestSearch:
    def _seed(self, lib, tmp_path):
        paths = make_files(tmp_path, "cadence.aiff", "sway.wav", "feelin.mp3")
        playlist = lib.create_playlist("Set")
        ids = [
            lib.add_track(paths[0], artist="Anz", title="Cadence"),
            lib.add_track(paths[1], artist="Nu Yorica", title="Sway"),
            lib.add_track(paths[2], artist="DJ Rashad", title="Feelin'"),
        ]
        lib.add_items(playlist, ids)
        return ids

    def test_search_matches_artist_title_and_filename(self, lib, tmp_path):
        anz, sway, rashad = self._seed(lib, tmp_path)
        assert lib.search("cadence") == [anz]
        assert lib.search("nu yorica") == [sway]
        assert lib.search("feelin") == [rashad]  # filename + title
        assert lib.search("cad") == [anz]  # prefix
        assert lib.search("zzz") == []
        assert lib.search("") == []
        assert lib.search("   ") == []

    def test_search_is_safe_against_query_syntax(self, lib, tmp_path):
        self._seed(lib, tmp_path)
        for hostile in ['"', 'a" OR "b', "NEAR(", "%", "_", "\\"]:
            lib.search(hostile)  # must not raise

    def test_tag_edit_updates_search(self, lib, tmp_path):
        anz, _, _ = self._seed(lib, tmp_path)
        lib.update_track_tags(anz, title="Loos in Twos")
        assert lib.search("loos") == [anz]
        assert anz not in lib.search("cadence.aiff") or lib.get_track(anz).filename == "cadence.aiff"

    def test_search_matches_the_comment(self, lib, tmp_path):
        """DJs keep their working notes in the comment tag — energy, cue
        points, who they got it from — so it has to be searchable."""
        anz, sway, _ = self._seed(lib, tmp_path)
        lib.update_track_tags(anz, comment="peak time roller - 8A")
        lib.update_track_tags(sway, comment="opener, deep")

        assert lib.search("roller") == [anz]
        assert lib.search("peak time") == [anz]
        assert lib.search("opener") == [sway]
        # Still ANDs across fields: one word from the comment, one from a tag.
        assert lib.search("anz roller") == [anz]
        assert lib.search("sway roller") == []

    def test_comment_is_searchable_from_the_moment_a_track_is_added(
        self, lib, tmp_path
    ):
        (path,) = make_files(tmp_path, "one.aiff")
        playlist = lib.create_playlist("Set")
        tid = lib.add_track(path, artist="Anz", comment="dubby stepper")
        lib.add_items(playlist, [tid])
        assert lib.search("stepper") == [tid]

    def test_clearing_the_comment_removes_it_from_the_index(self, lib, tmp_path):
        anz, _, _ = self._seed(lib, tmp_path)
        lib.update_track_tags(anz, comment="banger")
        assert lib.search("banger") == [anz]
        lib.update_track_tags(anz, comment="")
        assert lib.search("banger") == []

    def test_a_rename_keeps_the_comment_searchable(self, lib, tmp_path):
        """update_paths rebuilds search_blob from the stored columns, so it
        has to carry the comment across or the rename would silently drop it
        out of the LIKE index."""
        (old,) = make_files(tmp_path, "one.aiff")
        playlist = lib.create_playlist("Set")
        tid = lib.add_track(old, artist="Anz", comment="dubby stepper")
        lib.add_items(playlist, [tid])

        new = str(tmp_path / "renamed.aiff")
        Path(old).rename(new)
        assert lib.update_paths([(old, new)]) == 1
        assert lib.search("stepper") == [tid]

    def test_search_matches_the_key(self, lib, tmp_path):
        """Key search used to work only by accident — via a filename that
        happened to carry the code, or a comment the app wrote it into."""
        anz, sway, _ = self._seed(lib, tmp_path)
        lib.update_track_tags(anz, key="8A")
        lib.update_track_tags(sway, key="12B")

        assert lib.search("8A") == [anz]
        assert lib.search("8a") == [anz]  # case-insensitive
        assert lib.search("12b") == [sway]
        assert lib.search("anz 8a") == [anz]  # ANDs with the other fields
        assert lib.search("sway 8a") == []

    def test_changing_the_key_updates_the_index(self, lib, tmp_path):
        anz, _, _ = self._seed(lib, tmp_path)
        lib.update_track_tags(anz, key="8A")
        assert lib.search("8A") == [anz]
        lib.update_track_tags(anz, key="9A")
        assert lib.search("8A") == []
        assert lib.search("9A") == [anz]

    def test_key_search_works_on_the_like_fallback(self, tmp_path):
        """The two search paths must agree: FTS indexes the column, and the
        blob has to carry it too or a no-FTS build silently loses the field."""
        (path,) = make_files(tmp_path, "one.aiff")
        with Library(tmp_path / "library.db", enable_fts=False) as lib:
            playlist = lib.create_playlist("Set")
            tid = lib.add_track(path, artist="Anz", key="8A")
            lib.add_items(playlist, [tid])
            assert lib.search("8a") == [tid]

    def test_upgrade_makes_an_existing_key_searchable(self, tmp_path):
        """A pre-v4 row has a stored key its blob predates, so the upgrade has
        to recompute the blobs — otherwise the LIKE path misses it forever."""
        db = tmp_path / "library.db"
        (path,) = make_files(tmp_path, "one.aiff")
        with Library(db) as lib:
            playlist = lib.create_playlist("Set")
            tid = lib.add_track(path, artist="Anz", key="8A")
            lib.add_items(playlist, [tid])
        # Roll this row back to how a pre-v4 build would have left it: key
        # stored, blob and FTS index without it.
        con = sqlite3.connect(db)
        con.execute(
            "UPDATE tracks SET search_blob=? WHERE id=?", ("anz one.aiff", tid)
        )
        con.execute("DROP TABLE IF EXISTS tracks_fts")
        con.execute("PRAGMA user_version=3")
        con.commit()
        con.close()

        with Library(db, enable_fts=False) as lib:  # LIKE path: needs the blob
            assert lib.search("8a") == [tid]
        with Library(db) as lib:  # FTS path: needs the rebuilt index
            if lib.has_fts:
                assert lib.search("8a") == [tid]

    def test_fts_index_resyncs_after_fallback_session(self, tmp_path):
        db = tmp_path / "library.db"
        with Library(db, enable_fts=True) as lib:
            if not lib.has_fts:
                pytest.skip("FTS5 unavailable in this Python build")
            (path,) = make_files(tmp_path, "cadence.aiff")
            playlist = lib.create_playlist("Set")
            lib.add_items(playlist, [lib.add_track(path, artist="Anz")])
        with Library(db, enable_fts=False) as lib:  # simulates a no-FTS build
            (path2,) = make_files(tmp_path, "sway.wav")
            lib.add_items(
                lib.get_children()[0].id, [lib.add_track(path2, artist="Nu Yorica")]
            )
            assert len(lib.search("nu")) == 1  # LIKE fallback still finds it
        with Library(db, enable_fts=True) as lib:  # FTS build resyncs the index
            assert len(lib.search("nu")) == 1
            assert len(lib.search("anz")) == 1


class TestUpdatePaths:
    def test_rename_hook_updates_row_and_keeps_playlists(self, lib, tmp_path):
        (old,) = make_files(tmp_path, "01 - Cadence.aiff")
        playlist = lib.create_playlist("Set")
        tid = lib.add_track(old, artist="Anz", title="Cadence")
        lib.add_items(playlist, [tid])

        new = str(tmp_path / "Cadence - 8A - 138.aiff")
        (tmp_path / "01 - Cadence.aiff").rename(new)
        assert lib.update_paths([(old, new)]) == 1

        track = lib.get_track(tid)
        assert track.path == new
        assert track.filename == "Cadence - 8A - 138.aiff"
        assert lib.get_track_by_path(new).id == tid
        assert lib.get_item_track_ids(playlist) == [tid]  # membership untouched
        assert lib.search("8a") == [tid]  # search sees the new filename

    def test_unknown_and_clashing_paths_are_skipped(self, lib, tmp_path):
        one, two = make_files(tmp_path, "one.aiff", "two.aiff")
        playlist = lib.create_playlist("Set")
        t1, t2 = lib.add_track(one), lib.add_track(two)
        lib.add_items(playlist, [t1, t2])

        assert lib.update_paths([("/nowhere/x.wav", "/nowhere/y.wav")]) == 0
        assert lib.update_paths([(one, two)]) == 0  # would collide with t2's row
        assert lib.get_track(t1).path == one

    def test_module_hook_is_noop_without_database(self, tmp_path):
        missing = tmp_path / "never-created.db"
        assert update_paths([("/a.wav", "/b.wav")], db_path=missing) == 0
        assert not missing.exists()
