"""Clicking a playlist column header sorts the view — and only the view.

The three-state cycle is ascending, descending, back to the stored order.
What makes this feature safe is the second half of that sentence: the panel's
whole design assumes ``row == index into self._playlist`` (about thirty call
sites), so the sort reorders ``_playlist`` itself and keeps a canonical
snapshot beside it. Everything that writes to the database writes the
snapshot. Nothing about the saved playlist changes because someone looked at
it in a different order.

Assertions are on rendered cell text where the question is "what does the user
see" (tests/gui/README.md) and on entry paths where the question is "which
track is where".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.gui.widgets.player_panel import PlayerPanel, SeparatorHeaderView
from src.library import SCRATCH_NODE_ID, Library

# Column indexes under test, by name, so the tests read as the feature does.
NUM, FILENAME, ARTIST, TITLE, BPM, KEY = 0, 1, 2, 3, 4, 5
COMMENT, DURATION, YEAR = 6, 7, 8
TRACK_NO, BITRATE, ENERGY, ART = 11, 13, 14, 15


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


def make(tmp_path, name):
    f = tmp_path / name
    f.write_bytes(b"not-really-audio-" + name.encode())
    return str(f)


def stock(player, tmp_path, rows):
    """Add *rows* — dicts of PlaylistEntry fields keyed by a filename."""
    tracks = []
    for name, fields in rows:
        path = make(tmp_path, name)
        tracks.append({"file_path": path, "display_name": name, **fields})
    player.add_tracks(tracks, allow_duplicates=True)
    return tracks


def shown(player, column):
    """The column's rendered text, top to bottom."""
    return [
        player._table.item(row, column).text()
        for row in range(player._table.rowCount())
    ]


def names(player):
    return [e.display_name for e in player._playlist]


def stored(lib, node=SCRATCH_NODE_ID):
    """The order the database holds, by filename."""
    return [Path(t.path).name for t in lib.get_items(node)]


class TestTheCycle:
    def test_three_clicks_go_up_down_and_back(self, player, tmp_path):
        stock(
            player,
            tmp_path,
            [
                ("c.wav", {"artist": "Carol"}),
                ("a.wav", {"artist": "Alice"}),
                ("b.wav", {"artist": "Bob"}),
            ],
        )
        assert names(player) == ["c.wav", "a.wav", "b.wav"]

        player._on_header_clicked(ARTIST)
        assert shown(player, ARTIST) == ["Alice", "Bob", "Carol"]

        player._on_header_clicked(ARTIST)
        assert shown(player, ARTIST) == ["Carol", "Bob", "Alice"]

        player._on_header_clicked(ARTIST)
        assert shown(player, ARTIST) == ["Carol", "Alice", "Bob"]
        assert names(player) == ["c.wav", "a.wav", "b.wav"]

    def test_a_different_column_starts_over_ascending(self, player, tmp_path):
        stock(
            player,
            tmp_path,
            [
                ("a.wav", {"artist": "Alice", "title": "Zulu"}),
                ("b.wav", {"artist": "Bob", "title": "Alpha"}),
            ],
        )
        player._on_header_clicked(ARTIST)
        player._on_header_clicked(ARTIST)  # now descending

        player._on_header_clicked(TITLE)

        assert player._sort_column == TITLE
        assert player._sort_desc is False
        assert shown(player, TITLE) == ["Alpha", "Zulu"]

    def test_the_artwork_column_is_not_sortable(self, player, tmp_path):
        stock(player, tmp_path, [("a.wav", {}), ("b.wav", {})])

        player._on_header_clicked(ART)

        assert player._sort_column is None

    def test_a_search_ignores_header_clicks(self, player, tmp_path):
        """Results are ranked by the search, and column 0 is a membership
        count there rather than a position."""
        stock(player, tmp_path, [("b.wav", {"artist": "Bob"})])
        player._search_active = True

        player._on_header_clicked(ARTIST)

        assert player._sort_column is None


class TestKeysThatAreNotText:
    def test_bpm_sorts_as_a_number(self, player, tmp_path):
        stock(
            player,
            tmp_path,
            [
                ("a.wav", {"bpm": "98"}),
                ("b.wav", {"bpm": "102"}),
                ("c.wav", {"bpm": "9"}),
            ],
        )
        player._on_header_clicked(BPM)
        assert shown(player, BPM) == ["9", "98", "102"]

    def test_duration_sorts_past_ten_minutes(self, player, tmp_path):
        """As text "10:00" sorts before "9:59", because "1" < "9"."""
        stock(
            player,
            tmp_path,
            [("a.wav", {"duration": 600.0}), ("b.wav", {"duration": 599.0})],
        )
        player._on_header_clicked(DURATION)
        assert shown(player, DURATION) == ["9:59", "10:00"]

    def test_a_track_number_with_a_total_sorts_by_its_number(
        self, player, tmp_path
    ):
        stock(
            player,
            tmp_path,
            [
                ("a.wav", {"track_number": "10/12"}),
                ("b.wav", {"track_number": "3/12"}),
            ],
        )
        player._on_header_clicked(TRACK_NO)
        assert shown(player, TRACK_NO) == ["3/12", "10/12"]

    def test_the_key_column_orders_by_code_whatever_the_tag_says(
        self, player, tmp_path
    ):
        """The Player shows the tag verbatim, so one file says "Am" and the
        next says "8A" for the same key. Ordering the text would put them in
        different places; both go through key_to_keycode first.

        8A and Am are the same key, so their relative order is whatever the
        sort was already showing — a tie, not a ranking.
        """
        stock(
            player,
            tmp_path,
            [
                ("a.wav", {"key": "10A"}),
                ("b.wav", {"key": "Am"}),
                ("c.wav", {"key": "2A"}),
                ("d.wav", {"key": "8A"}),
            ],
        )
        player._on_header_clicked(KEY)

        order = shown(player, KEY)
        assert order[0] == "2A"
        assert set(order[1:3]) == {"Am", "8A"}, "8A and Am tie"
        assert order[3] == "10A"


class TestBlanks:
    """A track with nothing in the column sorts last in BOTH directions. A
    sentinel key would flip them to the top on the descending click, which is
    the opposite of what "show me the highest BPM" means."""

    def test_blanks_stay_last_ascending_and_descending(self, player, tmp_path):
        stock(
            player,
            tmp_path,
            [
                ("blank.wav", {}),
                ("high.wav", {"bpm": "174"}),
                ("low.wav", {"bpm": "120"}),
            ],
        )

        player._on_header_clicked(BPM)
        assert names(player) == ["low.wav", "high.wav", "blank.wav"]

        player._on_header_clicked(BPM)
        assert names(player) == ["high.wav", "low.wav", "blank.wav"]


class TestTheNumberColumn:
    def test_it_keeps_showing_the_stored_position_while_sorted(
        self, player, tmp_path
    ):
        """So "back to how it was" is visibly what the third click does."""
        stock(
            player,
            tmp_path,
            [
                ("c.wav", {"artist": "Carol"}),
                ("a.wav", {"artist": "Alice"}),
                ("b.wav", {"artist": "Bob"}),
            ],
        )

        player._on_header_clicked(ARTIST)

        assert shown(player, ARTIST) == ["Alice", "Bob", "Carol"]
        assert shown(player, NUM) == ["2", "3", "1"]

    def test_clicking_it_is_the_stored_order(self, player, tmp_path):
        stock(
            player,
            tmp_path,
            [("c.wav", {}), ("a.wav", {}), ("b.wav", {})],
        )
        player._on_header_clicked(FILENAME)  # scramble it first

        player._on_header_clicked(NUM)

        assert names(player) == ["c.wav", "a.wav", "b.wav"]
        assert shown(player, NUM) == ["1", "2", "3"]

    def test_clicking_it_twice_reverses(self, player, tmp_path):
        stock(player, tmp_path, [("c.wav", {}), ("a.wav", {}), ("b.wav", {})])

        player._on_header_clicked(NUM)
        player._on_header_clicked(NUM)

        assert names(player) == ["b.wav", "a.wav", "c.wav"]
        assert shown(player, NUM) == ["3", "2", "1"]


class TestTheDatabaseNeverSeesTheVisibleOrder:
    """The whole law of the feature."""

    def test_sorting_alone_changes_nothing_stored(self, player, lib, tmp_path):
        """Checked at every point in the cycle, and with data whose sorted
        order differs from its stored order in *both* directions — the first
        attempt used two tracks whose descending sort happened to equal the
        order they were added in, so it passed against a build that wrote the
        visible order straight to the database.
        """
        stock(
            player,
            tmp_path,
            [
                ("c.wav", {"title": "Bravo"}),
                ("a.wav", {"title": "Alpha"}),
                ("b.wav", {"title": "Charlie"}),
            ],
        )
        before = stored(lib)
        assert before == ["c.wav", "a.wav", "b.wav"]

        seen = []
        for _ in range(3):
            player._on_header_clicked(TITLE)
            seen.append(names(player))
            player._persist_playlist()
            assert stored(lib) == before

        assert seen[0] == ["a.wav", "c.wav", "b.wav"], "ascending by title"
        assert seen[1] == ["b.wav", "c.wav", "a.wav"], "descending"
        assert seen[2] == before, "and back"

    def test_removing_a_row_while_sorted_drops_only_that_track(
        self, player, lib, tmp_path
    ):
        stock(
            player,
            tmp_path,
            [
                ("c.wav", {"artist": "Carol"}),
                ("a.wav", {"artist": "Alice"}),
                ("b.wav", {"artist": "Bob"}),
            ],
        )
        player._on_header_clicked(ARTIST)  # Alice, Bob, Carol
        player._table.selectRow(0)  # a.wav

        player._on_remove_selected()

        assert names(player) == ["b.wav", "c.wav"]
        assert stored(lib) == ["c.wav", "b.wav"], "stored order otherwise intact"

    def test_adding_while_sorted_arrives_at_the_stored_end(
        self, player, lib, tmp_path
    ):
        """Visually it lands where the sort says; in the database it lands
        where it actually arrived."""
        stock(
            player,
            tmp_path,
            [("c.wav", {"artist": "Carol"}), ("a.wav", {"artist": "Alice"})],
        )
        player._on_header_clicked(ARTIST)

        stock(player, tmp_path, [("b.wav", {"artist": "Bob"})])

        assert names(player) == ["a.wav", "b.wav", "c.wav"], "visually in place"
        assert stored(lib) == ["c.wav", "a.wav", "b.wav"], "stored by arrival"

    def test_the_stored_order_survives_a_reload(self, player, lib, tmp_path):
        node = lib.create_playlist("Set")
        stock(
            player,
            tmp_path,
            [("c.wav", {"artist": "Carol"}), ("a.wav", {"artist": "Alice"})],
        )
        player._persist_playlist()
        lib.set_items(node, [t.id for t in lib.get_items(SCRATCH_NODE_ID)])
        player.load_node(node)
        before = names(player)

        player._on_header_clicked(ARTIST)
        player.load_node(node)

        assert names(player) == before


class TestReorderIsOffWhileSorted:
    def test_the_table_refuses_a_hand_drag(self, player, tmp_path):
        stock(player, tmp_path, [("b.wav", {"artist": "B"}), ("a.wav", {"artist": "A"})])
        assert player._table._reorder_enabled

        player._on_header_clicked(ARTIST)
        assert not player._table._reorder_enabled

        player._on_header_clicked(ARTIST)
        player._on_header_clicked(ARTIST)  # back to off
        assert player._table._reorder_enabled


class TestWhatClearsIt:
    def test_loading_another_playlist_clears_the_sort(
        self, player, lib, tmp_path
    ):
        """A different list is a different question."""
        node = lib.create_playlist("Other")
        stock(player, tmp_path, [("b.wav", {"artist": "B"}), ("a.wav", {"artist": "A"})])
        player._on_header_clicked(ARTIST)

        player.load_node(node)

        assert player._sort_column is None
        assert player._unsorted_playlist is None

    def test_clearing_the_playlist_drops_the_snapshot(self, player, tmp_path):
        stock(player, tmp_path, [("b.wav", {"artist": "B"}), ("a.wav", {"artist": "A"})])
        player._on_header_clicked(ARTIST)

        player._on_clear_playlist()

        assert player._sort_column is None
        assert player._unsorted_playlist is None

    def test_starting_a_search_clears_the_sort(self, player, tmp_path):
        stock(player, tmp_path, [("b.wav", {"artist": "B"}), ("a.wav", {"artist": "A"})])
        player._on_header_clicked(ARTIST)

        # Signals blocked so only the explicit call runs: setText also arms
        # the 250ms debounce, which would otherwise fire at teardown and
        # search a library the fixture has already closed.
        player._search_field.blockSignals(True)
        player._search_field.setText("b")
        player._search_field.blockSignals(False)
        player._run_search()

        assert player._sort_column is None


class TestTheHeaderStateStaysClean:
    def test_sorting_does_not_touch_the_saved_column_layout(
        self, player, tmp_path
    ):
        """QHeaderView.saveState() serialises the style's sort indicator, so
        using setSortIndicator would carry a stale arrow across launches for a
        sort that is session-only by design. The glyph is painted by hand
        instead, and this asserts the saved blob is byte-identical."""
        stock(player, tmp_path, [("b.wav", {"artist": "B"}), ("a.wav", {"artist": "A"})])
        header = player._table.horizontalHeader()
        before = bytes(header.saveState())

        player._on_header_clicked(ARTIST)
        player._on_header_clicked(ARTIST)

        assert bytes(header.saveState()) == before

    def test_the_header_knows_which_way_to_draw(self, player, tmp_path):
        stock(player, tmp_path, [("b.wav", {"artist": "B"}), ("a.wav", {"artist": "A"})])
        header = player._table.horizontalHeader()
        assert isinstance(header, SeparatorHeaderView)

        player._on_header_clicked(ARTIST)
        assert (header._sort_section, header._sort_desc) == (ARTIST, False)

        player._on_header_clicked(ARTIST)
        assert (header._sort_section, header._sort_desc) == (ARTIST, True)

        player._on_header_clicked(ARTIST)
        assert header._sort_section is None


class TestTheRestOfThePanelKeepsUp:
    def test_the_playing_track_keeps_its_highlight_through_a_sort(
        self, player, tmp_path
    ):
        """_current_index is a position in _playlist, which the sort moves."""
        tracks = stock(
            player,
            tmp_path,
            [
                ("c.wav", {"artist": "Carol"}),
                ("a.wav", {"artist": "Alice"}),
                ("b.wav", {"artist": "Bob"}),
            ],
        )
        player._playing_path = tracks[0]["file_path"]  # c.wav, row 0
        player._relink_playing_row()
        assert player._current_index == 0

        player._on_header_clicked(ARTIST)  # Alice, Bob, Carol

        assert player._current_index == 2
        assert names(player)[player._current_index] == "c.wav"

    def test_the_row_count_matches_the_list_at_every_step(
        self, player, tmp_path
    ):
        stock(
            player,
            tmp_path,
            [("c.wav", {"artist": "C"}), ("a.wav", {"artist": "A"})],
        )
        for _ in range(4):
            player._on_header_clicked(ARTIST)
            assert player._table.rowCount() == len(player._playlist)
