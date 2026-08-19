"""The "In Playlist: …" link beside the Player's now-playing line.

Playback is deliberately independent of the visible list, so a track can be
playing from a playlist the user has navigated away from. This line names that
playlist and, clicked, opens it — the way back from wherever they wandered to.

The invariants:
- It names the node the track was *started* from, not whatever is showing now.
- A search result set is no playlist: no link.
- A renamed playlist re-reads; a deleted one takes the link away.
- Clicking routes out as a signal, so the tree's selection can follow.
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent

from src.gui.widgets.player_panel import PlayerPanel
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
    return [{"file_path": p, "display_name": Path(p).name, **extra} for p in paths]


def search(player, query):
    """Type a query and run it immediately (bypassing the debounce timer)."""
    player._search_field.setText(query)
    player._search_timer.stop()
    player._run_search()


class TestWhatItNames:
    def test_it_names_scratch_when_playing_from_scratch(self, player, tmp_path):
        (a,) = make_files(tmp_path, "a.wav")
        player.add_tracks(track_dicts([a]))
        player._play_track(0)

        assert not player._playing_playlist_link.isHidden()
        assert player._playing_playlist_link.text() == "In Playlist: Scratch"
        assert player._playing_node_id == SCRATCH_NODE_ID

    def test_it_keeps_naming_the_list_the_track_came_from(self, player, lib, tmp_path):
        """The whole point: the visible list moves on, the link does not."""
        a, b = make_files(tmp_path, "a.wav", "b.wav")
        source = lib.create_playlist("Warm Up")
        lib.set_items(source, [lib.add_track(a)])
        other = lib.create_playlist("Peak Time")
        lib.set_items(other, [lib.add_track(b)])

        player.load_node(source)
        player._play_track(0)
        player.load_node(other)  # wander off
        player.refresh_playing_playlist()  # …and a refresh lands meanwhile

        assert player.loaded_node_id == other
        assert player._playing_playlist_link.text() == "In Playlist: Warm Up"

    def test_a_search_result_gets_no_link(self, player, lib, tmp_path):
        """A result set is not a playlist — there is nothing to go back to."""
        a, b = make_files(tmp_path, "alpha.wav", "beat.wav")
        player.add_tracks(track_dicts([a], title="Alpha"))
        pl = lib.create_playlist("Set")
        lib.set_items(pl, [lib.add_track(b, title="Cadence")])
        player.load_node(pl)

        search(player, "cadence")
        assert player._playlist  # the search really found something
        player._play_track(0)

        assert player._playing_node_id is None
        assert player._playing_playlist_link.isHidden()
        # …while the track itself is still named.
        assert not player._now_playing_label.isHidden()

    def test_nothing_playing_hides_the_whole_line(self, player, tmp_path):
        (a,) = make_files(tmp_path, "a.wav")
        player.add_tracks(track_dicts([a]))
        player._play_track(0)
        assert not player._now_playing_row.isHidden()

        player._on_clear_playlist()
        assert player._now_playing_row.isHidden()
        assert player._playing_playlist_link.isHidden()
        assert player._playing_node_id is None


class TestTheLineShares:
    """Two facts on one line, and filenames are long.

    Widths here are structural, never pixel counts: the suite runs with no
    application stylesheet, so the numbers it measures are not the app's.
    """

    LONG = (
        "Some Very Long Artist Name Feat. Another One - An Absurdly Long Track "
        "Title You Would Not Believe (Extended Peak Time Club Mix).wav"
    )

    def test_a_long_filename_does_not_crowd_out_the_link(
        self, player, qtbot, tmp_path
    ):
        """Measured against the real window: with no cap the link got exactly
        zero pixels — present, correct and invisible."""
        (a,) = make_files(tmp_path, self.LONG)
        player.resize(700, 500)
        player.show()
        qtbot.wait(10)
        player.add_tracks(track_dicts([a]))
        player._play_track(0)
        qtbot.wait(10)

        label = player._now_playing_label
        link = player._playing_playlist_link
        # The name really is over the cap — otherwise this proves nothing.
        assert label.sizeHint().width() > label.maximumWidth()
        assert link.width() > 0
        assert not link.isHidden()

    def test_a_short_filename_still_hugs_its_text(self, player, qtbot, tmp_path):
        """The cap is a ceiling, not a column: a short name must not leave a
        gap before the link."""
        (a,) = make_files(tmp_path, "a.wav")
        player.resize(700, 500)
        player.show()
        qtbot.wait(10)
        player.add_tracks(track_dicts([a]))
        player._play_track(0)
        qtbot.wait(10)

        label = player._now_playing_label
        assert label.width() == label.sizeHint().width()

    def test_the_drag_instruction_survives_elision(self, player, qtbot, tmp_path):
        """ElidedLabel's own rule *replaces* the tooltip on resize, which here
        would throw away the one thing the user cannot guess by looking."""
        (a,) = make_files(tmp_path, self.LONG)
        player.resize(700, 500)
        player.show()
        qtbot.wait(10)
        player.add_tracks(track_dicts([a]))
        player._play_track(0)
        qtbot.wait(10)

        tip = player._now_playing_label.toolTip()
        assert "Drag this onto a playlist" in tip
        assert Path(a).name in tip  # …and the cut-off name is recoverable

    def test_the_link_is_no_wider_than_its_text(self, player, qtbot, tmp_path):
        """A stretchy label would put several hundred pixels of clickable
        nothing at the end of the line — measured at 684px against 157px of
        text before the trailing stretch took the slack instead."""
        (a,) = make_files(tmp_path, "a.wav")
        player.resize(900, 500)
        player.show()
        qtbot.wait(10)
        player.add_tracks(track_dicts([a]))
        player._play_track(0)
        qtbot.wait(10)

        link = player._playing_playlist_link
        assert link.width() == link.sizeHint().width()

    def test_the_link_keeps_its_own_tooltip(self, player, lib, qtbot, tmp_path):
        """ElidedLabel clears the tooltip on any resize where the text fits,
        which would silently delete the one line saying the name is clickable."""
        (a,) = make_files(tmp_path, "a.wav")
        pl = lib.create_playlist("Set")
        lib.set_items(pl, [lib.add_track(a)])
        player.resize(900, 500)
        player.show()
        qtbot.wait(10)
        player.load_node(pl)
        player._play_track(0)
        player.resize(700, 500)
        qtbot.wait(10)

        assert "Open the playlist" in player._playing_playlist_link.toolTip()

    def test_a_long_name_is_recoverable_from_the_tooltip(
        self, player, lib, qtbot, tmp_path
    ):
        (a,) = make_files(tmp_path, "a.wav")
        name = "Friday Warm Up — Deep & Melodic, 120-124bpm, for the long room"
        pl = lib.create_playlist(name)
        lib.set_items(pl, [lib.add_track(a)])
        player.resize(500, 500)
        player.show()
        qtbot.wait(10)
        player.load_node(pl)
        player._play_track(0)
        qtbot.wait(10)

        link = player._playing_playlist_link
        assert link.width() < link.sizeHint().width()  # it really is cut short
        tip = link.toolTip()
        assert "Open the playlist" in tip
        assert name in tip

    def test_the_filename_can_shrink_at_all(self, player):
        """QLabel answers its full text width as the minimum, which with a
        Maximum policy makes it unshrinkable — the floor is what lets the cap
        bite."""
        label = player._now_playing_label
        label.setText("Playing: " + self.LONG)
        assert label.minimumSizeHint().width() < label.sizeHint().width()


class TestItFollowsTheDatabase:
    def test_a_rename_is_picked_up(self, player, lib, tmp_path):
        (a,) = make_files(tmp_path, "a.wav")
        pl = lib.create_playlist("Old Name")
        lib.set_items(pl, [lib.add_track(a)])
        player.load_node(pl)
        player._play_track(0)

        lib.rename_node(pl, "New Name")
        player.refresh_playing_playlist()
        assert player._playing_playlist_link.text() == "In Playlist: New Name"

    def test_a_deleted_playlist_takes_the_link_away(self, player, lib, tmp_path):
        (a,) = make_files(tmp_path, "a.wav")
        pl = lib.create_playlist("Doomed")
        lib.set_items(pl, [lib.add_track(a)])
        player.load_node(pl)
        player._play_track(0)

        lib.delete_node(pl)
        player.refresh_playing_playlist()
        assert player._playing_playlist_link.isHidden()
        assert player._playing_node_id is None
        # The track plays on regardless — only the way back is gone.
        assert not player._now_playing_label.isHidden()


class TestClicking:
    def test_a_click_emits_the_node(self, player, lib, tmp_path, qtbot):
        a, b = make_files(tmp_path, "a.wav", "b.wav")
        source = lib.create_playlist("Warm Up")
        lib.set_items(source, [lib.add_track(a)])
        player.load_node(source)
        player._play_track(0)
        player.load_node(SCRATCH_NODE_ID)

        with qtbot.waitSignal(player.playing_playlist_clicked) as caught:
            player._playing_playlist_link.clicked.emit()
        assert caught.args == [source]

    def test_a_press_dragged_off_the_label_is_not_a_click(self, player, tmp_path):
        """Qt delivers the release to whoever took the press, so the label has
        to check where the mouse actually ended up."""
        (a,) = make_files(tmp_path, "a.wav")
        player.add_tracks(track_dicts([a]))
        player._play_track(0)
        link = player._playing_playlist_link
        link.resize(120, 20)

        seen = []
        link.clicked.connect(lambda: seen.append(True))

        outside = QPointF(link.width() + 40, 10)
        link.mouseReleaseEvent(
            QMouseEvent(
                QMouseEvent.Type.MouseButtonRelease,
                outside,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        assert seen == []

        link.mouseReleaseEvent(
            QMouseEvent(
                QMouseEvent.Type.MouseButtonRelease,
                QPointF(10, 10),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        assert seen == [True]

    def test_is_showing_node_gates_a_pointless_reload(self, player, lib, tmp_path):
        """What MainWindow keys the reload off: True means the click has
        nowhere to take the user and the list should be left alone."""
        (a,) = make_files(tmp_path, "a.wav")
        pl = lib.create_playlist("Set")
        lib.set_items(pl, [lib.add_track(a, title="Cadence")])
        player.load_node(pl)
        assert player.is_showing_node(pl)
        assert not player.is_showing_node(SCRATCH_NODE_ID)

        # A search over the same loaded node is showing results, not the list.
        search(player, "cadence")
        assert not player.is_showing_node(pl)
