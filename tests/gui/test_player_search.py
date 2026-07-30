"""Search-as-scope in the Player: results are just another (playable) list.

The invariants under test, from the playlist feature research §9-§10:
- All-playlists search shows each matching track ONCE (deduped), with a
  membership count in place of the row number and the names as its tooltip.
- Search results are display-only for the library: they must never be
  written through to the loaded node.
- Clearing the search (or loading a node) restores the loaded playlist;
  there is no state to get stuck in.
- Destructive edits (remove, reorder, drag-out move) are inert on results;
  inline tag edits refresh the library track so every playlist sees them.
"""

from pathlib import Path

import pytest

from src.gui.widgets.player_panel import _SEARCH_LIMIT, PlayerPanel
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


def make_files(tmp_path, *names):
    paths = []
    for name in names:
        f = tmp_path / name
        f.write_bytes(b"not-really-audio-" + name.encode())
        paths.append(str(f))
    return paths


def track_dicts(paths, **extra):
    return [
        {"file_path": p, "display_name": Path(p).name, **extra} for p in paths
    ]


def search(player, query):
    """Type a query and run it immediately (bypassing the debounce timer)."""
    player._search_field.setText(query)
    player._search_timer.stop()
    player._run_search()


@pytest.fixture
def seeded(player, lib, tmp_path):
    """Scratch holds [a]; 'One' holds [b]; 'Two' holds [b, c].

    b's title matches the query 'cadence'; a and c don't.
    """
    a, b, c = make_files(tmp_path, "alpha.wav", "beat.wav", "closer.wav")
    player.add_tracks(track_dicts([a], artist="X", title="Alpha"))
    one = lib.create_playlist("One")
    two = lib.create_playlist("Two")
    tb = lib.add_track(b, artist="Anz", title="Cadence Song")
    tc = lib.add_track(c, artist="Y", title="Other")
    lib.set_items(one, [tb])
    lib.set_items(two, [tb, tc])
    return {"paths": (a, b, c), "nodes": (one, two), "ids": (tb, tc)}


class TestAllPlaylistsScope:
    def test_finds_deduped_with_membership_counts(self, player, seeded):
        a, b, c = seeded["paths"]
        search(player, "cadence")

        # b is in two playlists but appears once; count + names answer "where".
        assert [e.file_path for e in player._playlist] == [b]
        assert player._table.horizontalHeaderItem(0).text() == "Playlists"
        assert player._table.item(0, 0).text() == "2"
        tooltip = player._table.item(0, 0).toolTip()
        assert "One" in tooltip and "Two" in tooltip
        assert player._context_label.text() == "› Search: cadence"
        assert player._stats_label.text() == "1 result"

    def test_matches_scratch_only_tracks_with_zero_count(self, player, seeded):
        a, b, c = seeded["paths"]
        search(player, "alpha")
        assert [e.file_path for e in player._playlist] == [a]
        assert player._table.item(0, 0).text() == "0"  # scratch isn't a playlist

    def test_search_never_persists_to_loaded_node(self, player, lib, seeded):
        a, b, c = seeded["paths"]
        search(player, "cadence")
        assert [t.path for t in lib.get_items(SCRATCH_NODE_ID)] == [a]

    def test_capped_results_are_labelled_honestly(self, player, lib):
        for i in range(_SEARCH_LIMIT + 5):
            lib.add_track(f"/nowhere/track{i:04}.wav", title=f"cad {i:04}")
        search(player, "cad")
        assert len(player._playlist) == _SEARCH_LIMIT
        assert player._stats_label.text() == f"{_SEARCH_LIMIT}+ results"


class TestCommentSearch:
    """DJ notes live in the comment tag, so search has to reach them."""

    def test_all_playlists_scope_finds_a_comment(self, player, lib, seeded):
        a, b, c = seeded["paths"]
        lib.update_track_tags(seeded["ids"][1], comment="peak time roller")

        search(player, "roller")

        assert [e.file_path for e in player._playlist] == [c]
        # The result row shows the comment it matched on, not a blank cell.
        assert player._table.item(0, 6).text() == "peak time roller"

    def test_added_tracks_carry_their_comment_into_the_library(
        self, player, lib, tmp_path
    ):
        """Auto-save writes the comment through, so a track added in the
        Player is comment-searchable without any further step."""
        (path,) = make_files(tmp_path, "one.wav")
        player.add_tracks(track_dicts([path], artist="Anz", comment="dubby stepper"))

        assert lib.get_track_by_path(path).comment == "dubby stepper"
        search(player, "stepper")
        assert [e.file_path for e in player._playlist] == [path]

    def test_a_comment_edit_on_a_result_reaches_the_library(
        self, player, lib, seeded, monkeypatch
    ):
        a, b, c = seeded["paths"]
        monkeypatch.setattr(
            "src.gui.widgets.player_panel.write_comment", lambda *args, **kw: None
        )
        search(player, "cadence")
        player._table.item(0, 6).setText("late set only")  # Comment column

        assert lib.get_track_by_path(b).comment == "late set only"
        assert lib.search("late set") == [lib.get_track_by_path(b).id]

    def test_a_load_backfills_a_comment_the_library_never_had(
        self, player, lib, seeded, monkeypatch
    ):
        """How rows that predate the comment column catch up: opening their
        playlist reads whatever tags the database lacks, and auto-save writes
        the result back — so a comment becomes searchable after one visit."""
        from src.metadata.tags import TrackMetadata

        one = seeded["nodes"][0]
        b = seeded["paths"][1]
        assert lib.get_items(one)[0].comment == ""  # never read from the file
        monkeypatch.setattr(
            "src.metadata.tags.read_metadata",
            lambda path: TrackMetadata(comment="from the file" if path == b else None),
        )

        player.load_node(one)

        assert lib.get_items(one)[0].comment == "from the file"
        assert lib.search("from the file") == [lib.get_track_by_path(b).id]

    def test_a_load_does_not_wipe_a_stored_comment(self, player, lib, seeded):
        """Loading a playlist re-persists it. The comment has to make the
        round trip, or opening a list would blank what search indexed."""
        one = seeded["nodes"][0]
        lib.update_track_tags(seeded["ids"][0], comment="peak time roller")

        player.load_node(one)

        assert lib.get_items(one)[0].comment == "peak time roller"
        assert player._playlist[0].comment == "peak time roller"


class TestThisPlaylistScope:
    def test_filters_visible_list_and_keeps_duplicates(self, player, lib, tmp_path):
        a, b = make_files(tmp_path, "cadence.wav", "other.wav")
        pl = lib.create_playlist("Doubles")
        ta, tb = lib.add_track(a), lib.add_track(b)
        lib.set_items(pl, [ta, tb, ta])  # cadence.wav deliberately twice
        player.load_node(pl)

        player._select_search_scope(False)  # This playlist
        search(player, "cadence")

        assert [e.file_path for e in player._playlist] == [a, a]
        # No count column in this scope — '#' numbering stays.
        assert player._table.horizontalHeaderItem(0).text() == "#"
        assert player._table.item(0, 0).text() == "1"

    def test_scope_switch_reruns_live_query(self, player, seeded):
        a, b, c = seeded["paths"]
        search(player, "alpha")
        assert [e.file_path for e in player._playlist] == [a]
        player._select_search_scope(False)  # rerun over scratch ([a])
        assert [e.file_path for e in player._playlist] == [a]
        assert player._table.horizontalHeaderItem(0).text() == "#"


class TestLeavingSearch:
    def test_clearing_field_restores_loaded_list(self, player, seeded):
        a, b, c = seeded["paths"]
        search(player, "cadence")
        player._search_field.setText("")  # textChanged -> _exit_search

        assert not player._search_active
        assert [e.file_path for e in player._playlist] == [a]
        assert player._table.horizontalHeaderItem(0).text() == "#"
        assert player._save_btn.isEnabled() and player._clear_btn.isEnabled()
        assert player._table.acceptDrops()
        assert player._context_label.text() == "› Scratch"

    def test_exit_search_without_search_is_a_noop(self, player, seeded):
        a, b, c = seeded["paths"]
        player._exit_search()
        assert [e.file_path for e in player._playlist] == [a]

    def test_load_node_clears_search(self, player, lib, seeded):
        a, b, c = seeded["paths"]
        one, two = seeded["nodes"]
        search(player, "cadence")
        player.load_node(two)

        assert not player._search_active
        assert player._search_field.text() == ""
        assert player.loaded_node_id == two
        assert [e.file_path for e in player._playlist] == [b, c]

    def test_add_tracks_during_search_exits_and_appends(
        self, player, lib, seeded, tmp_path
    ):
        a, b, c = seeded["paths"]
        (d,) = make_files(tmp_path, "dropped.wav")
        search(player, "cadence")
        player.add_tracks(track_dicts([d]))

        assert not player._search_active
        assert [e.file_path for e in player._playlist] == [a, d]
        assert [t.path for t in lib.get_items(SCRATCH_NODE_ID)] == [a, d]


class TestResultsAreNotEditableStructure:
    def test_remove_is_gated(self, player, lib, seeded):
        a, b, c = seeded["paths"]
        search(player, "cadence")
        player._table.selectRow(0)
        player._on_remove_selected()
        assert [e.file_path for e in player._playlist] == [b]  # untouched
        assert lib.get_track_by_path(b) is not None

    def test_drops_disabled_and_drag_out_is_copy_only(self, player, seeded):
        a, b, c = seeded["paths"]
        search(player, "cadence")
        assert not player._table.acceptDrops()
        player._table.selectRow(0)
        paths, remove_cb = player._drag_data()
        assert paths == [b]
        assert remove_cb is None

    def test_save_and_clear_buttons_disabled(self, player, seeded):
        search(player, "cadence")
        assert not player._save_btn.isEnabled()
        assert not player._clear_btn.isEnabled()


class TestPlaybackAcrossSearch:
    def test_playing_row_unlinks_and_relinks(self, player, seeded):
        a, b, c = seeded["paths"]
        player._play_track(0)  # play a from scratch
        search(player, "cadence")  # results: [b] — a isn't there

        assert player._playing_path == a
        assert player._current_index == -1  # no row highlight in results

        player._search_field.setText("")
        assert player._current_index == 0  # re-linked in the restored list

    def test_playing_a_result_links_its_row(self, player, seeded):
        a, b, c = seeded["paths"]
        search(player, "cadence")
        player._play_track(0)
        assert player._playing_path == b
        assert player._current_index == 0


class TestHighlightTrail:
    @pytest.fixture
    def crates(self, player, lib, tmp_path):
        """F > G > P1;  F > P2.  Track a is in P1+P2; track b in P2 only."""
        a, b = make_files(tmp_path, "cadence_one.wav", "cadence_two.wav")
        f = lib.create_folder("F")
        g = lib.create_folder("G", f)
        p1 = lib.create_playlist("P1", g)
        p2 = lib.create_playlist("P2", f)
        ta, tb = lib.add_track(a), lib.add_track(b)
        lib.set_items(p1, [ta])
        lib.set_items(p2, [ta, tb])
        seen = []
        player.tree_highlight_changed.connect(
            lambda p, fc: seen.append((set(p), dict(fc)))
        )
        return {"paths": (a, b), "nodes": (f, g, p1, p2), "seen": seen}

    def test_selection_lights_playlists_and_ancestors(self, player, crates):
        f, g, p1, p2 = crates["nodes"]
        search(player, "cadence")
        player._table.selectRow(0)  # track a — in P1 (under G under F) and P2
        assert crates["seen"][-1] == ({p1, p2}, {g: 1, f: 2})

        player._table.selectRow(1)  # track b — in P2 only
        assert crates["seen"][-1] == ({p2}, {f: 1})

    def test_multi_select_highlights_the_union(self, player, crates):
        f, g, p1, p2 = crates["nodes"]
        search(player, "cadence")
        player._table.selectAll()
        assert crates["seen"][-1] == ({p1, p2}, {g: 1, f: 2})

    def test_exiting_search_clears_the_trail(self, player, crates):
        search(player, "cadence")
        player._table.selectRow(0)
        player._search_field.setText("")
        assert crates["seen"][-1] == (set(), {})

    def test_this_playlist_scope_never_lights(self, player, crates):
        player._select_search_scope(False)
        search(player, "cadence")  # scratch is empty — no matter; scope check
        player._table.selectAll()
        assert crates["seen"][-1] == (set(), {})


class TestInlineEditsInSearch:
    def test_edit_updates_library_track_not_loaded_node(
        self, player, lib, seeded, monkeypatch
    ):
        a, b, c = seeded["paths"]
        monkeypatch.setattr(
            "src.gui.widgets.player_panel.write_metadata", lambda *args, **kw: None
        )
        search(player, "cadence")
        player._table.item(0, 3).setText("Renamed Song")  # Title column

        assert lib.get_track_by_path(b).title == "Renamed Song"
        # Loaded node untouched: scratch still holds exactly [a].
        assert [t.path for t in lib.get_items(SCRATCH_NODE_ID)] == [a]

    def test_edit_flows_into_loaded_list_when_track_is_in_it(
        self, player, lib, seeded, monkeypatch
    ):
        a, b, c = seeded["paths"]
        monkeypatch.setattr(
            "src.gui.widgets.player_panel.write_metadata", lambda *args, **kw: None
        )
        search(player, "alpha")  # a — which IS the loaded (scratch) list's row
        player._table.item(0, 3).setText("Alpha II")
        player._search_field.setText("")  # back to scratch

        assert player._playlist[0].title == "Alpha II"
        assert lib.get_track_by_path(a).title == "Alpha II"
