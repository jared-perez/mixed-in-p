"""Adding tracks brings the new rows into view; opening a playlist does not.

Two things make these assertions mean something. The scroll is read off the
vertical scrollbar, and every test first checks the bar has room to move — a
table whose rows all fit is at "the bottom" and at "the top" at once, so an
assertion on it would pass against the bug. And the bar's *range* is only
recomputed when Qt processes the pending layout, so each test pumps
(``settle``) before reading it: without that the range is whatever last forced
an update, which in a passing build is the very scroll under test.
"""

from pathlib import Path

import pytest

from src.gui.widgets.dialogs import duplicate_policy as dup_mod
from src.gui.widgets.player_panel import PlayerPanel
from src.library import SCRATCH_NODE_ID, Library

#: Enough rows that the table must scroll at the size the fixture gives it.
ROWS = 40


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
    # Shown at a real geometry, so the table's viewport is shorter than the
    # rows the tests put in it.
    panel.resize(900, 400)
    panel.show()
    qtbot.waitExposed(panel)
    return panel


def make_files(tmp_path, count):
    paths = []
    for i in range(count):
        f = tmp_path / f"t{i:02d}.wav"
        f.write_bytes(b"not-really-audio")
        paths.append(str(f))
    return paths


def track_dicts(paths):
    return [{"file_path": p, "display_name": Path(p).name} for p in paths]


def bar(player):
    return player._table.verticalScrollBar()


def pump(qtbot):
    """Drain the event queue.

    Deliberately not ``qtbot.wait(0)``, which returns without draining it — so
    a deferred duplicate prompt would never fire and the test would pass for
    the wrong reason.
    """
    qtbot.wait(10)


def settle_at_top(player, qtbot):
    """Put the viewport at the top, with a scrollbar that can leave it."""
    pump(qtbot)
    player._table.scrollToTop()
    assert bar(player).maximum() > 0, "table isn't scrollable; the test proves nothing"


class TestScrollOnAdd:
    def test_an_append_shows_the_new_rows(self, player, tmp_path, qtbot):
        paths = make_files(tmp_path, ROWS)
        player.add_tracks(track_dicts(paths[:-1]), allow_duplicates=True)
        settle_at_top(player, qtbot)

        player.add_tracks(track_dicts(paths[-1:]), allow_duplicates=True)

        assert bar(player).value() == bar(player).maximum()

    def test_an_add_does_not_move_the_selection(self, player, tmp_path, qtbot):
        paths = make_files(tmp_path, ROWS)
        player.add_tracks(track_dicts(paths[:-1]), allow_duplicates=True)
        settle_at_top(player, qtbot)
        player._table.selectRow(0)

        player.add_tracks(track_dicts(paths[-1:]), allow_duplicates=True)

        assert player._table.currentRow() == 0

    def test_a_caller_can_opt_out(self, player, tmp_path, qtbot):
        paths = make_files(tmp_path, ROWS)
        player.add_tracks(track_dicts(paths[:-1]), allow_duplicates=True)
        settle_at_top(player, qtbot)

        player.add_tracks(
            track_dicts(paths[-1:]), allow_duplicates=True, scroll_to_end=False
        )

        assert bar(player).value() == 0

    def test_a_deferred_add_scrolls_once_the_prompt_is_answered(
        self, player, tmp_path, monkeypatch, qtbot
    ):
        """The ASK path: ``add_tracks`` returns before the rows exist, so a
        scroll done there would fire against the old table."""
        paths = make_files(tmp_path, ROWS)
        player.add_tracks(track_dicts(paths), allow_duplicates=True)
        settle_at_top(player, qtbot)
        monkeypatch.setattr(dup_mod, "_prompt", lambda *a: True)  # Add anyway

        player.add_tracks(track_dicts(paths[:1]))  # a duplicate → asks
        assert bar(player).value() == 0  # nothing has landed yet
        pump(qtbot)

        assert len(player._playlist) == ROWS + 1
        assert bar(player).value() == bar(player).maximum()

    def test_an_add_resolved_away_leaves_the_view_alone(
        self, player, tmp_path, monkeypatch, qtbot
    ):
        """Skip-all adds nothing, so there is nothing to scroll to."""
        paths = make_files(tmp_path, ROWS)
        player.add_tracks(track_dicts(paths), allow_duplicates=True)
        settle_at_top(player, qtbot)
        monkeypatch.setattr(dup_mod, "_prompt", lambda *a: False)  # Skip

        player.add_tracks(track_dicts(paths[:1]))
        pump(qtbot)

        assert len(player._playlist) == ROWS
        assert bar(player).value() == 0


def stocked_playlist(lib, player, tmp_path, name, prefix, rows=ROWS):
    """A saved playlist of *rows* real files, ready to load."""
    paths = []
    for i in range(rows):
        f = tmp_path / f"{prefix}{i:02d}.wav"
        f.write_bytes(b"not-really-audio")
        paths.append(str(f))
    node = lib.create_playlist(name)
    lib.set_items(node, [lib.add_track(p) for p in paths])
    return node, paths


class TestAFirstOpenStartsAtTheTop:
    """A playlist nobody has scrolled has nothing to restore, so it opens at
    its beginning — what every load did before scroll memory existed."""

    def test_opening_a_playlist_starts_at_its_beginning(
        self, player, lib, tmp_path, qtbot
    ):
        node, paths = stocked_playlist(lib, player, tmp_path, "Peak Time", "p")
        # Start from the far end, so landing at the top is a result rather
        # than the state the test happened to begin in.
        player.add_tracks(track_dicts(paths), allow_duplicates=True)
        settle_at_top(player, qtbot)
        player._table.scrollToBottom()

        player.load_node(node)

        assert len(player._playlist) == ROWS
        assert bar(player).value() == 0


class TestComingBackToAPlaylist:
    """Where a list was left is where it reopens — per playlist, for the
    session. The value is a row index (ScrollPerItem), not a pixel."""

    def test_a_playlist_reopens_where_it_was_left(
        self, player, lib, tmp_path, qtbot
    ):
        a, _ = stocked_playlist(lib, player, tmp_path, "A", "a")
        b, _ = stocked_playlist(lib, player, tmp_path, "B", "b")
        player.load_node(a)
        settle_at_top(player, qtbot)
        halfway = bar(player).maximum() // 2
        assert halfway > 0, "nowhere to scroll; the test proves nothing"
        bar(player).setValue(halfway)

        player.load_node(b)
        pump(qtbot)
        assert bar(player).value() == 0, "B has never been opened"
        player.load_node(a)

        assert bar(player).value() == halfway

    def test_coming_back_from_a_shorter_list_still_lands(
        self, player, lib, tmp_path, qtbot
    ):
        """The lists visited in between are not all the same length, and the
        scrollbar's range is the previous list's until Qt runs the pending
        relayout — so a restore made against it is clamped to that list's
        length. Every other test here uses ROWS-row playlists throughout,
        which is exactly the case that cannot see it: the bug showed in the
        app as "only the last playlist or two remember where they were"."""
        long_one, _ = stocked_playlist(lib, player, tmp_path, "Long", "l")
        short_one, _ = stocked_playlist(lib, player, tmp_path, "Short", "s", rows=5)
        player.load_node(long_one)
        settle_at_top(player, qtbot)
        halfway = bar(player).maximum() // 2
        assert halfway > 0, "nowhere to scroll; the test proves nothing"
        bar(player).setValue(halfway)

        player.load_node(short_one)
        pump(qtbot)
        assert bar(player).maximum() == 0, "the short list scrolls; the test proves nothing"
        player.load_node(long_one)

        assert bar(player).value() == halfway
        pump(qtbot)
        assert bar(player).value() == halfway, "clamped once Qt recomputed the range"

    def test_a_longer_list_is_not_cut_to_the_shorter_ones_length(
        self, player, lib, tmp_path, qtbot
    ):
        """The other direction: a position past the end of the list just
        left is clamped to that list's range, not restored to its own."""
        short_one, _ = stocked_playlist(lib, player, tmp_path, "Short", "s")
        long_one, _ = stocked_playlist(lib, player, tmp_path, "Long", "l", rows=ROWS * 2)
        player.load_node(short_one)
        settle_at_top(player, qtbot)
        short_reach = bar(player).maximum()
        player.load_node(long_one)
        settle_at_top(player, qtbot)
        deep = bar(player).maximum() - 1
        assert deep > short_reach, "the short list reaches that far; the test proves nothing"
        bar(player).setValue(deep)

        player.load_node(short_one)
        pump(qtbot)  # as between two clicks: the range is the short list's now
        player.load_node(long_one)

        assert bar(player).value() == deep

    def test_scratch_is_no_different(self, player, lib, tmp_path, qtbot):
        """Scratch is a real node (id 1), not a special case — it keeps its
        place like any other list. This replaces the old assertion that it
        always reloaded at the top."""
        other, _ = stocked_playlist(lib, player, tmp_path, "Elsewhere", "e")
        paths = make_files(tmp_path, ROWS)
        player.add_tracks(track_dicts(paths), allow_duplicates=True)
        settle_at_top(player, qtbot)
        bar(player).setValue(bar(player).maximum())
        parked = bar(player).value()

        player.load_node(other)
        player.load_node(SCRATCH_NODE_ID)

        assert bar(player).value() == parked

    def test_a_reload_of_the_showing_list_holds_its_place(
        self, player, lib, tmp_path, qtbot
    ):
        """Dropping files onto the playlist that is already showing reloads
        the same node (main_window._on_tracks_added), which used to throw the
        view back to the top. Save-then-restore round-trips it for free."""
        node, _ = stocked_playlist(lib, player, tmp_path, "Working Set", "w")
        player.load_node(node)
        settle_at_top(player, qtbot)
        halfway = bar(player).maximum() // 2
        assert halfway > 0, "nowhere to scroll; the test proves nothing"
        bar(player).setValue(halfway)

        player.load_node(node)

        assert bar(player).value() == halfway

    def test_a_search_does_not_take_the_playlists_place(
        self, player, lib, tmp_path, qtbot
    ):
        """While a search is showing, the table holds the hits but
        _loaded_node_id still names the underlying playlist — so saving the
        scroll on the way out of a search would file the search's position
        under the playlist's id.

        The search's position has to differ from the playlist's for this to
        mean anything: parked halfway, "searching" at the bottom. Note the
        guard must be read before load_node dismisses the search, which
        clears the flag — placed after it, this test passes against the bug.
        """
        node, _ = stocked_playlist(lib, player, tmp_path, "Deep", "d")
        other, _ = stocked_playlist(lib, player, tmp_path, "Other", "o")
        player.load_node(node)
        settle_at_top(player, qtbot)
        halfway = bar(player).maximum() // 2
        assert halfway > 0, "nowhere to scroll; the test proves nothing"
        bar(player).setValue(halfway)
        player.load_node(other)
        player.load_node(node)  # node's slot now holds halfway
        pump(qtbot)

        player._search_active = True  # stand in for a running search
        bar(player).setValue(bar(player).maximum())
        player.load_node(other)
        player.load_node(node)

        assert bar(player).value() == halfway
