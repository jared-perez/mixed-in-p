"""The playing context: which row, in which playlist, is playing.

The user's report: a track playing from one playlist stopped when it was
removed from a *different* playlist that also held it. The Player tracked the
file that was playing, never the row it was playing from, and walked the
*visible* list for Next — so the fix separates the two, and these tests pin
the agreed behaviour table (spitball/pip/2026-09-18-HANDOFF-playing-context.md
§2). Duplicates are everywhere here, because two copies of one file are where
identity and path disagree.

The PCM cache is seeded so a play loads synchronously and nothing decodes the
not-really-audio fixtures; the engine's play() is stubbed so no output device
is opened. unload() is recorded: nothing in this file may call it.
"""

from pathlib import Path

import numpy as np
import pytest

from src.gui.widgets import player_panel as player_panel_mod
from src.gui.widgets.player_panel import PlayerPanel
from src.library import Library

BPM = 4


@pytest.fixture
def lib(tmp_path):
    library = Library(tmp_path / "library.db")
    yield library
    library.close()


@pytest.fixture
def player(qtbot, lib, monkeypatch):
    panel = PlayerPanel()
    qtbot.addWidget(panel)
    panel.set_library(lib)
    engine = panel._engine
    monkeypatch.setattr(engine, "play", lambda: setattr(engine, "_state", "playing"))
    panel.unloads = []
    monkeypatch.setattr(engine, "unload", lambda: panel.unloads.append(True))
    return panel


def make_files(tmp_path, *names):
    paths = []
    for name in names:
        f = tmp_path / name
        if not f.exists():
            f.write_bytes(b"not-really-audio-" + name.encode())
        paths.append(str(f))
    return paths


def fill(player, node, paths, bpms=None):
    """Load *node* and add *paths* to it through the Player, tags on the dicts."""
    player.load_node(node)
    dicts = [{"file_path": p, "display_name": Path(p).name} for p in paths]
    for d, bpm in zip(dicts, bpms or []):
        d["bpm"] = bpm
    player.add_tracks(dicts, allow_duplicates=True, scroll_to_end=False)
    # The rows go up before their files are read, and the BPM above only
    # reaches the library on the write-through that follows that read.
    assert player.wait_for_tags()
    for p in paths:
        player._cache_put(p, np.zeros((64, 2), dtype=np.float32), 44100)


def remove_row(player, row):
    player._table.clearSelection()
    player._table.selectRow(row)
    player._on_remove_selected()


def stored(lib, node):
    return [Path(t.path).name for t in lib.get_items(node)]


def playing_name(player):
    return Path(player._playing_path).name if player._playing_path else None


def still_playing(player, name):
    assert playing_name(player) == name
    assert player._engine.has_buffer()
    assert player._engine.is_playing()
    assert player.unloads == []


@pytest.fixture
def ab(player, lib, tmp_path):
    """Playlists A and B (empty), and a way to make files by name."""
    a = lib.create_playlist("A")
    b = lib.create_playlist("B")
    return a, b, lambda *names: make_files(tmp_path, *names)


class TestRemove:
    def test_removing_it_from_another_playlist_leaves_playback_alone(
        self, player, lib, ab
    ):
        """The report."""
        a, b, files = ab
        x, y, z = files("x.wav", "y.wav", "z.wav")
        fill(player, a, [x, y])
        fill(player, b, [z, y])
        player.load_node(a)
        player._play_track(1)  # y, from A

        player.load_node(b)
        remove_row(player, 1)  # y, from B

        still_playing(player, "y.wav")
        assert player._ctx.node_id == a and not player._ctx.orphaned
        assert stored(lib, a) == ["x.wav", "y.wav"]
        assert stored(lib, b) == ["z.wav"]

    def test_removing_the_playing_row_orphans_it_and_next_plays_what_followed(
        self, player, lib, ab
    ):
        a, _, files = ab
        x, y, z = files("x.wav", "y.wav", "z.wav")
        fill(player, a, [x, y, z])
        player._play_track(1)

        remove_row(player, 1)

        still_playing(player, "y.wav")
        assert player._ctx.orphaned
        assert player._current_index == -1
        assert player._next_btn.isEnabled()
        player._on_next()
        assert playing_name(player) == "z.wav"
        assert player._current_index == 1

    def test_previous_from_an_orphan_plays_the_row_before_the_gap(
        self, player, lib, ab
    ):
        a, _, files = ab
        x, y, z = files("x.wav", "y.wav", "z.wav")
        fill(player, a, [x, y, z])
        player._play_track(1)
        remove_row(player, 1)

        player._on_previous()

        assert playing_name(player) == "x.wav"
        assert player._current_index == 0


class TestDuplicates:
    def test_removing_the_first_copy_keeps_the_second_playing(self, player, ab):
        a, _, files = ab
        d, e = files("dup.wav", "e.wav")
        fill(player, a, [d, e, d])
        player._play_track(2)
        playing = player._playlist[2]

        remove_row(player, 0)

        still_playing(player, "dup.wav")
        assert not player._ctx.orphaned
        assert player._current_index == 1
        assert player._playlist[1] is playing

    def test_removing_the_second_copy_keeps_the_first_playing(self, player, ab):
        a, _, files = ab
        d, e = files("dup.wav", "e.wav")
        fill(player, a, [d, e, d])
        player._play_track(0)
        playing = player._playlist[0]

        remove_row(player, 2)

        still_playing(player, "dup.wav")
        assert not player._ctx.orphaned
        assert player._current_index == 0
        assert player._playlist[0] is playing

    def test_a_drag_reorder_follows_the_playing_copy(self, player, ab):
        a, _, files = ab
        d, e = files("dup.wav", "e.wav")
        fill(player, a, [d, e, d])
        player._play_track(2)
        playing = player._playlist[2]

        # The drop handler's move: take row 1 (e) and put it on top.
        table = player._table
        moved = [table.takeItem(1, c) for c in range(table.columnCount())]
        table.removeRow(1)
        table.insertRow(0)
        for col, item in enumerate(moved):
            table.setItem(0, col, item)
        player._sync_playlist_from_table()

        assert [en.display_name for en in player._playlist] == [
            "e.wav", "dup.wav", "dup.wav"
        ]
        assert player._current_index == 2
        assert player._playlist[2] is playing
        assert player._ctx.position == 2


class TestClear:
    def test_clearing_the_playing_list_plays_the_track_out(self, player, lib, ab):
        a, _, files = ab
        x, y = files("x.wav", "y.wav")
        fill(player, a, [x, y])
        player._play_track(0)

        player._on_clear_playlist()

        still_playing(player, "x.wav")
        assert player._ctx.orphaned
        assert not player._next_btn.isEnabled()
        assert player._play_btn.isEnabled()  # still pausable
        assert stored(lib, a) == []

    def test_clearing_a_sorted_list_clears_it(self, player, lib, ab):
        # Found on the way past: the sort's own clear put every row back.
        a, _, files = ab
        x, y = files("x.wav", "y.wav")
        fill(player, a, [x, y], bpms=["130", "120"])
        player._on_header_clicked(BPM)

        player._on_clear_playlist()

        assert player._playlist == []
        assert stored(lib, a) == []

    def test_clearing_another_list_does_not_touch_the_engine(self, player, lib, ab):
        a, b, files = ab
        x, y = files("x.wav", "y.wav")
        fill(player, a, [x, y])
        fill(player, b, [y])
        player.load_node(a)
        player._play_track(0)

        player.load_node(b)
        player._on_clear_playlist()

        still_playing(player, "x.wav")
        assert not player._ctx.orphaned
        assert stored(lib, a) == ["x.wav", "y.wav"]


class TestAdvanceWhileAway:
    def test_auto_advance_walks_the_playing_list_not_the_visible_one(
        self, player, ab
    ):
        a, b, files = ab
        x, y, z, p, q = files("x.wav", "y.wav", "z.wav", "p.wav", "q.wav")
        fill(player, a, [x, y, z])
        fill(player, b, [p, q])
        player.load_node(a)
        player._play_track(1)

        player.load_node(b)
        player._on_track_finished()

        assert playing_name(player) == "z.wav"
        assert player._ctx.node_id == a
        assert player._current_index == -1  # B has no row for it

        # Coming back re-binds to A's freshly loaded row.
        player.load_node(a)
        assert player._current_index == 2
        assert player._playlist[2] is player._ctx.entry

    def test_a_track_appended_behind_the_players_back_is_reached(
        self, player, lib, ab
    ):
        a, b, files = ab
        x, y, w, p = files("x.wav", "y.wav", "w.wav", "p.wav")
        fill(player, a, [x, y])
        fill(player, b, [p])
        player.load_node(a)
        player._play_track(1)  # the last row
        player.load_node(b)
        player._update_transport_state()
        assert not player._next_btn.isEnabled()

        lib.add_items(a, [lib.add_track(w)])  # the tree's path: straight to the DB
        player._update_transport_state()
        assert player._next_btn.isEnabled()
        player._on_track_finished()

        assert playing_name(player) == "w.wav"

    def test_deleting_the_playing_list_ends_the_run_without_interrupting(
        self, player, lib, ab
    ):
        a, b, files = ab
        x, y, p = files("x.wav", "y.wav", "p.wav")
        fill(player, a, [x, y])
        fill(player, b, [p])
        player.load_node(a)
        player._play_track(0)
        player.load_node(b)

        lib.delete_node(a)
        player.refresh_playing_playlist()  # what the tree's change signal does
        player._on_next()
        still_playing(player, "x.wav")
        assert not player._next_btn.isEnabled()

        player._on_track_finished()
        assert playing_name(player) == "x.wav"
        assert not player._engine.is_playing()  # stopped at the end, as ever


class TestSearchContext:
    def test_next_walks_the_hits_after_the_search_is_dismissed(
        self, player, lib, ab
    ):
        a, _, files = ab
        names = ("hit1.wav", "other.wav", "hit2.wav", "hit3.wav")
        fill(player, a, list(files(*names)))
        player._apply_search_scope(False)  # this playlist
        player._search_field.setText("hit")
        player._search_timer.stop()
        player._run_search()
        assert [e.display_name for e in player._playlist] == [
            "hit1.wav", "hit2.wav", "hit3.wav"
        ]
        player._play_track(1)
        assert player._ctx.node_id is None and player._ctx.snapshot is not None

        player._exit_search()
        player._on_next()

        assert playing_name(player) == "hit3.wav"


class TestSorted:
    def test_next_follows_the_visible_order_then_the_stored_one(
        self, player, ab
    ):
        a, b, files = ab
        x, y, z = files("x.wav", "y.wav", "z.wav")
        fill(player, a, [x, y, z], bpms=["120", "130", "125"])
        player._on_header_clicked(BPM)  # visible: x 120, z 125, y 130
        assert [e.display_name for e in player._playlist] == [
            "x.wav", "z.wav", "y.wav"
        ]
        player._play_track(0)
        player._on_next()
        assert playing_name(player) == "z.wav"

        # Leaving clears the sort, so coming back Next follows stored order.
        player.load_node(b)
        player.load_node(a)
        assert player._sort_column is None
        player._play_track(0)
        player._on_next()
        assert playing_name(player) == "y.wav"


class TestReaders:
    def test_loaded_track_bpm_answers_while_another_list_is_on_screen(
        self, player, ab
    ):
        a, b, files = ab
        x, p = files("x.wav", "p.wav")
        fill(player, a, [x], bpms=["128"])
        fill(player, b, [p], bpms=["90"])
        player.load_node(a)
        player._play_track(0)

        player.load_node(b)

        assert player.loaded_track_bpm() == pytest.approx(128.0)

    def test_an_inline_bpm_edit_reaches_the_context_entry(
        self, player, ab, monkeypatch
    ):
        monkeypatch.setattr(player_panel_mod, "write_metadata", lambda *a, **k: None)
        a, _, files = ab
        (x,) = files("x.wav")
        fill(player, a, [x], bpms=["128"])
        player._play_track(0)

        player._table.item(0, BPM).setText("140")

        assert player._ctx.entry is player._playlist[0]
        assert player.loaded_track_bpm() == pytest.approx(140.0)

    def test_scroll_to_playing_row_is_a_no_op_for_an_orphan(self, player, ab):
        a, _, files = ab
        x, y = files("x.wav", "y.wav")
        fill(player, a, [x, y])
        player._play_track(0)
        remove_row(player, 0)

        player.load_node(a)  # what Cmd+L does
        assert player.playing_node_id == a
        assert player._current_index == -1  # never re-bound to another row
