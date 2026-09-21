"""The Player reads a row's tags off the GUI thread, not in front of the user.

A playlist row is filled from the library where it can be and from the file's
own tags where it cannot, and that second path is a full mutagen parse per
file. Doing it inline meant a long playlist froze the window for as long as the
whole list took to open — measured at ~1.6 s for 99 tracks on a USB stick,
which reads as a hang rather than as work.

So the rows go up immediately carrying what the library knows, an unread blank
shows a placeholder so it cannot be mistaken for an empty tag, and a reader
thread fills the rest in. What is worth testing is not the speed, which this
suite cannot see, but the four things that can go wrong once the read is no
longer synchronous:

* an auto-save landing mid-read must not write the unread blanks into the
  library (``Library.add_track`` skips ``None``, not ``""``);
* an answer must reach the row it was read for even after a sort or a second
  copy of the same file has moved things around;
* a value the user typed while the read was in flight must win;
* switching playlists must not let the old list's answers land in the new one.
"""

from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from src.gui.widgets.player_panel import _PENDING_TEXT, PlayerPanel
from src.library import Library
from src.metadata.tags import write_metadata, TrackMetadata


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


def make_track(tmp_path, name, **tags):
    """A real audio file, optionally tagged, that the reader can open.

    FLAC rather than WAV: a WAV holds no artist, BPM or key (see
    `stores_tags`), so a fixture written as one would test the reader against
    a file that cannot answer. FLAC is also in `_SIZED_EXTENSIONS`, which is
    what makes a fully-tagged row still worth opening for its bit depth.
    """
    path = tmp_path / name
    sf.write(path, np.zeros(4410, dtype=np.float32), 44100, subtype="PCM_16")
    if tags:
        write_metadata(str(path), TrackMetadata(**tags), fields=list(tags))
    return str(path)


def bare(path):
    """The dict a caller with nothing but a path hands to add_tracks."""
    from pathlib import Path

    return {"file_path": path, "display_name": Path(path).name}


def settle(qtbot, player):
    """Wait for the queued read to start and finish."""
    qtbot.waitUntil(lambda: not any(e.pending for e in player._playlist), timeout=5000)
    qtbot.wait(10)


def cell(player, row, col):
    item = player._table.item(row, col)
    return item.text() if item is not None else None


ARTIST, TITLE, BPM = 2, 3, 4


class TestTheRowsAppearBeforeTheFilesAreRead:
    def test_an_unread_row_is_on_screen_immediately(self, qtbot, player, tmp_path):
        path = make_track(tmp_path, "a.flac", artist="Someone")
        player.add_tracks([bare(path)])
        # No pumping: this is the state the user sees the instant the add
        # returns, which is the whole point of the change.
        assert player._table.rowCount() == 1
        assert player._playlist[0].pending

    def test_an_unread_blank_shows_the_placeholder(self, qtbot, player, tmp_path):
        path = make_track(tmp_path, "a.flac", artist="Someone")
        player.add_tracks([bare(path)])
        assert cell(player, 0, ARTIST) == _PENDING_TEXT

    def test_the_placeholder_is_replaced_by_what_was_on_disk(
        self, qtbot, player, tmp_path
    ):
        path = make_track(tmp_path, "a.flac", artist="Someone")
        player.add_tracks([bare(path)])
        settle(qtbot, player)
        assert cell(player, 0, ARTIST) == "Someone"

    def test_a_tag_the_file_really_lacks_ends_up_blank_not_placeholder(
        self, qtbot, player, tmp_path
    ):
        # The distinction the placeholder exists for: once we have looked, an
        # empty cell is the answer rather than a promise.
        path = make_track(tmp_path, "a.flac", artist="Someone")
        player.add_tracks([bare(path)])
        settle(qtbot, player)
        assert cell(player, 0, BPM) == ""

    def test_a_row_the_caller_fully_described_is_never_pending(
        self, qtbot, player, tmp_path
    ):
        # Nothing to look up, so no read is queued at all — this is the path
        # every caller that has already read the tags takes (a Finder drop).
        path = make_track(tmp_path, "a.flac")
        player.add_tracks([
            {
                **bare(path),
                "artist": "A", "title": "T", "bpm": "128", "key": "8A",
                "comment": "c", "year": "2026", "duration": 1.0, "bit_depth": "16",
            }
        ])
        assert not player._playlist[0].pending
        assert cell(player, 0, ARTIST) == "A"


class TestThePlaceholderAlwaysGoesAway:
    """It promises an answer, so every path has to deliver one or clear it."""

    def test_a_file_that_cannot_be_read_stops_being_pending(
        self, qtbot, player, tmp_path
    ):
        # Not audio at all. The reader reports the failure rather than
        # dropping it; otherwise the row wears "…" in every column for the
        # rest of the session and no amount of waiting changes it.
        path = tmp_path / "broken.flac"
        path.write_bytes(b"\0" * 64)
        player.add_tracks([bare(str(path))])
        settle(qtbot, player)
        assert cell(player, 0, ARTIST) == ""

    def test_a_search_over_a_pending_row_does_not_strand_it(
        self, qtbot, player, tmp_path
    ):
        # A search result list is not the loaded node, so answers arriving
        # while one is up are dropped rather than written into it. Leaving the
        # search has to ask again, or the row keeps its placeholder for good.
        path = make_track(tmp_path, "a.flac", artist="Someone")
        player.add_tracks([bare(path)])
        player._search_field.setText("nothing matches this")
        player._search_timer.stop()
        player._run_search()
        qtbot.wait(20)
        player._exit_search()

        settle(qtbot, player)
        assert cell(player, 0, ARTIST) == "Someone"

    def test_a_lossy_file_never_shows_one_for_bit_depth(
        self, qtbot, player, tmp_path
    ):
        # An MP3 has no bit depth and never will, and the extension says so
        # without opening anything — so there is nothing to wait for and the
        # cell should be empty from the first paint, pending row or not.
        path = tmp_path / "a.mp3"
        path.write_bytes(b"\0" * 64)
        player.add_tracks([bare(str(path))])
        assert player._playlist[0].pending
        assert cell(player, 0, PlayerPanel._BIT_DEPTH_COLUMN) == ""


class TestAnAutoSaveMidReadDoesNotBlankTheLibrary:
    """The sharpest edge of moving the read off the main thread.

    ``Library.add_track`` treats ``None`` as "don't touch" but ``""`` as a
    value, and ``_write_playlist`` hands it every entry field on every list
    edit. With the read synchronous the entries were always complete by then;
    with it in flight they are full of blanks, so a drag, a delete or a Clear
    would have wiped the tags off every row the reader had not reached.
    """

    def test_a_persist_while_pending_leaves_the_library_row_alone(
        self, qtbot, player, lib, tmp_path
    ):
        path = make_track(tmp_path, "a.flac")
        track_id = lib.add_track(path, artist="Known", title="Kept", key="8A")
        lib.set_items(lib.create_playlist("P"), [track_id])

        # A pending entry, persisted before its read can land.
        player.add_tracks([bare(path)])
        assert player._playlist[0].pending
        player._persist_playlist()

        row = lib.get_track_by_path(path)
        assert (row.artist, row.title, row.key) == ("Known", "Kept", "8A")

    def test_an_unreadable_file_still_stores_what_the_caller_supplied(
        self, qtbot, player, lib, tmp_path
    ):
        # The row was pending, so the auto-save at the end of the add wrote
        # nothing — and the read then failed, so there was nothing to fill.
        # The comment the caller handed in has still never been stored, and
        # the write-through after the read is its only remaining chance.
        path = tmp_path / "broken.flac"
        path.write_bytes(b"\0" * 64)
        player.add_tracks([{**bare(str(path)), "comment": "dubby stepper"}])
        settle(qtbot, player)
        assert lib.get_track_by_path(str(path)).comment == "dubby stepper"

    def test_the_same_persist_after_the_read_writes_what_was_found(
        self, qtbot, player, lib, tmp_path
    ):
        # The other half: once the entry is no longer pending its blanks are
        # real answers again, and auto-save goes back to writing them through.
        path = make_track(tmp_path, "a.flac", artist="OnDisk")
        player.add_tracks([bare(path)])
        settle(qtbot, player)
        player._persist_playlist()
        assert lib.get_track_by_path(path).artist == "OnDisk"


class TestTheAnswerReachesTheRightRow:
    def test_two_copies_of_one_file_both_fill(self, qtbot, player, tmp_path):
        # PlaylistEntry is a dataclass, so these two compare equal. Anything
        # that found the row with `index` or `in` would fill the first twice.
        path = make_track(tmp_path, "a.flac", artist="Twice")
        player.add_tracks([bare(path), bare(path)], allow_duplicates=True)
        settle(qtbot, player)
        assert cell(player, 0, ARTIST) == "Twice"
        assert cell(player, 1, ARTIST) == "Twice"

    def test_a_row_that_moved_under_a_sort_still_gets_its_tags(
        self, qtbot, player, tmp_path
    ):
        first = make_track(tmp_path, "z-first.flac", artist="Zulu")
        second = make_track(tmp_path, "a-second.flac", artist="Alpha")
        player.add_tracks([bare(first), bare(second)])
        # Sort by filename while the read is still queued: the rows swap.
        player._sort_column, player._sort_desc = 1, False
        player._apply_sort()
        settle(qtbot, player)
        by_name = {e.display_name: e.artist for e in player._playlist}
        assert by_name == {"z-first.flac": "Zulu", "a-second.flac": "Alpha"}


class TestWhatTheUserTypedWins:
    def test_an_edit_made_while_pending_is_not_overwritten(
        self, qtbot, player, tmp_path
    ):
        path = make_track(tmp_path, "a.flac", artist="OnDisk")
        player.add_tracks([bare(path)])
        entry = player._playlist[0]
        assert entry.pending
        # Stand in for the inline editor having committed before the answer
        # came back: the fill is `or`, so a filled field is left alone.
        entry.artist = "Typed"
        settle(qtbot, player)
        assert entry.artist == "Typed"


class TestSwitchingPlaylistsMidRead:
    def test_answers_for_the_old_list_do_not_land_in_the_new_one(
        self, qtbot, player, lib, tmp_path
    ):
        old_file = make_track(tmp_path, "old.flac", artist="Old")
        new_file = make_track(tmp_path, "new.flac", artist="New")
        old_node = lib.create_playlist("old")
        new_node = lib.create_playlist("new")
        lib.set_items(old_node, [lib.add_track(old_file)])
        lib.set_items(new_node, [lib.add_track(new_file)])

        player.load_node(old_node)
        player.load_node(new_node)  # before the first read can come back
        settle(qtbot, player)

        assert [e.display_name for e in player._playlist] == ["new.flac"]
        assert player._playlist[0].artist == "New"

    def test_the_reader_is_stopped_when_the_panel_closes(
        self, qtbot, player, tmp_path
    ):
        # A running QThread destroyed with the panel is undefined behaviour;
        # the reader's run() is a plain loop, so quit() alone would not do it.
        paths = [make_track(tmp_path, f"t{i}.flac", artist="A") for i in range(4)]
        player.add_tracks([bare(p) for p in paths])
        player.close()
        assert player.wait_for_readers()
        assert player._tag_queue == []
