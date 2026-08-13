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


class TestLoadNodeShowsTheTop:
    def test_opening_a_playlist_starts_at_its_beginning(
        self, player, lib, tmp_path, qtbot
    ):
        paths = make_files(tmp_path, ROWS)
        pl = lib.create_playlist("Peak Time")
        lib.set_items(pl, [lib.add_track(p) for p in paths])
        # Start from the far end, so landing at the top is a result rather
        # than the state the test happened to begin in.
        player.add_tracks(track_dicts(paths), allow_duplicates=True)
        settle_at_top(player, qtbot)
        player._table.scrollToBottom()

        player.load_node(pl)

        assert len(player._playlist) == ROWS
        assert bar(player).value() == 0

    def test_scratch_reloads_at_the_top_too(self, player, lib, tmp_path, qtbot):
        paths = make_files(tmp_path, ROWS)
        player.add_tracks(track_dicts(paths), allow_duplicates=True)
        settle_at_top(player, qtbot)
        player._table.scrollToBottom()

        player.load_node(SCRATCH_NODE_ID)

        assert bar(player).value() == 0
