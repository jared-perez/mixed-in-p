"""What's playing, shown in the app header for every panel that isn't the Player.

Playback outlives the Player being on screen, so from Analyze or Convert there
was no way to tell what was running short of switching back — which is exactly
what this saves. Clicking it goes to the playlist the track came from.

The invariants:
- Shown off the Player, hidden on it; follows both the page and the track.
- It elides; it never pushes the Add button off the bar.
- The click lands on the playlist, and falls back to the Player when the track
  came from a search result set and has no playlist to go to.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.gui.main_window import MainWindow
from src.gui.widgets.header_bar import HeaderBar
from src.gui.widgets.playlist_tree import NODE_ID_ROLE
from src.library import SCRATCH_NODE_ID

LONG = (
    "Some Very Long Artist Name Feat. Another One - An Absurdly Long Track "
    "Title You Would Not Believe (Extended Peak Time Club Mix).aiff"
)


def make_files(tmp_path, *names):
    paths = []
    for name in names:
        f = tmp_path / name
        f.write_bytes(b"not-really-audio-" + name.encode())
        paths.append(str(f))
    return paths


def track_dicts(paths):
    return [{"file_path": p, "display_name": Path(p).name} for p in paths]


@pytest.fixture
def header(qtbot):
    bar = HeaderBar()
    qtbot.addWidget(bar)
    bar.resize(1200, bar.height())
    bar.show()
    qtbot.wait(10)
    return bar


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    win._player_panel.shutdown_workers()


class TestTheHeaderWidget:
    def test_it_words_the_bare_filename_itself(self, header):
        header.set_now_playing("Neon Avenue.aiff")
        assert not header._now_playing.isHidden()
        assert header._now_playing.text() == "Playing: Neon Avenue.aiff"

    def test_empty_hides_it(self, header):
        header.set_now_playing("Neon Avenue.aiff")
        header.set_now_playing("")
        assert header._now_playing.isHidden()

    def test_a_click_emits(self, header, qtbot):
        header.set_now_playing("Neon Avenue.aiff")
        with qtbot.waitSignal(header.now_playing_clicked):
            header._now_playing.clicked.emit()

    def test_it_never_pushes_the_add_button_off_the_bar(self, header, qtbot):
        """A filename is text whose length we do not control, and this bar's
        right-hand end is the app's only Add button."""
        header.set_now_playing(LONG)
        qtbot.wait(10)
        label = header._now_playing
        assert label.sizeHint().width() > label.width()  # it really is cut short
        add = header._add_btn
        assert add.x() + add.width() <= header.width()
        assert add.width() >= add.sizeHint().width()

    def test_a_narrow_bar_drops_the_tagline_not_the_track(self, header, qtbot):
        """The tagline is the same on every launch; the track is not.

        Reached with setFixedWidth rather than resize because a plain resize
        cannot get there: the subtitle's own width is part of the minimum that
        stops the bar shrinking to where the rule would hide it (460 against a
        438 threshold — true of this rule before the now-playing line existed
        too). The rule is still worth having, and still worth checking, for
        whatever does force the width down.
        """
        header.set_now_playing("Neon Avenue.aiff")
        qtbot.wait(10)
        assert header._subtitle.isVisible()

        header.setFixedWidth(500)
        qtbot.wait(10)
        assert not header._subtitle.isVisible()
        assert not header._now_playing.isHidden()

    def test_a_track_arriving_re_runs_the_rule(self, header, qtbot):
        """The line joins the row the subtitle is competing for, so the
        threshold moves the moment a track starts — and no resize follows a
        track change to apply it."""
        # Derived, not a constant: the bar has gained widgets before now (the
        # pipeline cluster last), and each time a hardcoded width here turned
        # into a test about a header the app no longer has.
        header.setFixedWidth(header._subtitle_fits() + 20)
        qtbot.wait(10)
        assert header._subtitle.isVisible()  # room enough with no track

        header.set_now_playing("Neon Avenue.aiff")
        qtbot.wait(10)
        assert not header._subtitle.isVisible()

    def test_the_threshold_grows_by_the_floor_not_the_filename(self, header, qtbot):
        """A long filename must not be what takes the tagline away — it elides.
        Only a bar with no room for even a stub of the line should."""
        bare = header._subtitle_fits()
        header.set_now_playing("Neon Avenue.aiff")
        qtbot.wait(10)
        short = header._subtitle_fits()
        assert short > bare  # it did join the row the subtitle competes for

        header.set_now_playing(LONG)
        qtbot.wait(10)
        assert header._subtitle_fits() == short

    def test_a_long_filename_does_not_widen_the_bar(self, header, qtbot):
        """The other half of the same rule, from the window's side: the app's
        minimum width must not follow whatever the user named their files."""
        header.set_now_playing("Neon Avenue.aiff")
        qtbot.wait(10)
        short = header.minimumSizeHint().width()

        header.set_now_playing(LONG)
        qtbot.wait(10)
        assert header.minimumSizeHint().width() == short


class TestWhenItShows:
    def test_off_the_player_it_shows_and_on_it_it_does_not(
        self, window, qtbot, tmp_path
    ):
        (a,) = make_files(tmp_path, "a.wav")
        player = window._player_panel
        player.add_tracks(track_dicts([a]))
        player._play_track(0)

        window._on_page_changed("analysis")
        assert window._header._now_playing.text() == "Playing: a.wav"
        assert not window._header._now_playing.isHidden()

        # The Player says it better one line above the slicer.
        window._on_page_changed("player")
        assert window._header._now_playing.isHidden()

    def test_it_follows_the_track_without_a_page_change(
        self, window, qtbot, tmp_path
    ):
        a, b = make_files(tmp_path, "a.wav", "b.wav")
        player = window._player_panel
        player.add_tracks(track_dicts([a, b]))
        player._play_track(0)
        window._on_page_changed("analysis")
        assert window._header._now_playing.text() == "Playing: a.wav"

        player._play_track(1)
        assert window._header._now_playing.text() == "Playing: b.wav"

        player._on_clear_playlist()
        assert window._header._now_playing.isHidden()

    def test_nothing_playing_shows_nothing(self, window):
        window._on_page_changed("analysis")
        assert window._header._now_playing.isHidden()


class TestWhereTheClickGoes:
    def test_it_opens_the_playlist_and_the_player(self, window, qtbot, tmp_path):
        lib = window._library
        player = window._player_panel
        (a,) = make_files(tmp_path, "a.wav")
        folder = lib.create_folder("Crates")
        source = lib.create_playlist("Warm Up", parent_id=folder)
        lib.set_items(source, [lib.add_track(a)])
        window._playlists_panel.ensure_loaded()

        player.load_node(source)
        player._play_track(0)
        player.load_node(SCRATCH_NODE_ID)  # wander off…
        window._on_page_changed("convert")  # …and off the Player entirely

        window._header._now_playing.clicked.emit()

        assert window._current_page == "player"
        assert player.loaded_node_id == source
        tree = window._playlists_panel.tree
        assert tree.currentIndex().data(NODE_ID_ROLE) == source
        assert tree.isExpanded(tree._find_item(folder).index())

    def test_a_search_result_track_still_opens_the_player(
        self, window, qtbot, tmp_path
    ):
        """No playlist to go to is not a reason for the click to do nothing —
        "take me to what's playing" is still answerable."""
        lib = window._library
        player = window._player_panel
        (a,) = make_files(tmp_path, "cadence.wav")
        pl = lib.create_playlist("Set")
        lib.set_items(pl, [lib.add_track(a, title="Cadence")])
        player.load_node(pl)
        player._search_field.setText("cadence")
        player._search_timer.stop()
        player._run_search()
        assert player._playlist
        player._play_track(0)
        assert player.playing_node_id is None
        window._on_page_changed("analysis")

        window._header._now_playing.clicked.emit()
        assert window._current_page == "player"

    def test_clicking_the_list_already_loaded_does_not_reload_it(
        self, window, qtbot, tmp_path, monkeypatch
    ):
        lib = window._library
        player = window._player_panel
        (a,) = make_files(tmp_path, "a.wav")
        source = lib.create_playlist("Warm Up")
        lib.set_items(source, [lib.add_track(a)])
        window._playlists_panel.ensure_loaded()
        player.load_node(source)
        player._play_track(0)
        window._on_page_changed("metadata")

        loads = []
        monkeypatch.setattr(player, "load_node", lambda node_id: loads.append(node_id))
        window._header._now_playing.clicked.emit()

        assert loads == []
        assert window._current_page == "player"
