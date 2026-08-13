"""The v5 columns travel the whole way, add to database to reload.

Schema v5 gives year, track number, label and bitrate a home, but a column
nothing fills is worse than no column: the Player's Year column was blank for
every library row for exactly this reason — the field existed on the entry and
had nowhere to be stored. So this covers the round trip rather than the
storage: entry -> library row -> entry again.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.gui.widgets.player_panel import PlayerPanel, _parse_int
from tests.gui.helpers import unlink_when_released
from src.library import SCRATCH_NODE_ID, Library
from src.metadata.tags import TrackMetadata, write_metadata


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


@pytest.fixture
def tagged_file(tmp_path):
    """A real FLAC carrying every v5 field, so nothing here is simulated."""
    sf = pytest.importorskip("soundfile")
    path = tmp_path / "tagged.flac"
    sf.write(str(path), np.zeros(44100, dtype=np.float32), 44100, format="FLAC")
    write_metadata(
        str(path),
        TrackMetadata(
            artist="Photek", title="Ni Ten Ichi Ryu", year=1997,
            track_number=3, label="Science",
        ),
    )
    return str(path)


def add(player, path, qtbot):
    player.add_tracks(
        [{"file_path": path, "display_name": Path(path).name}],
        allow_duplicates=True,
    )
    qtbot.wait(10)


def test_the_parser_matches_its_neighbours(player):
    assert _parse_int("320") == 320
    assert _parse_int("") is None
    assert _parse_int(None) is None


def test_an_added_track_carries_the_new_fields_into_the_entry(
    player, tagged_file, qtbot
):
    add(player, tagged_file, qtbot)

    entry = player._playlist[0]
    assert entry.year == "1997"
    assert entry.track_number == "3"
    assert entry.label == "Science"
    assert entry.bitrate  # measured off the real stream, so not pinned exactly


def test_they_reach_the_library_row(player, lib, tagged_file, qtbot):
    """The gap this closes: before v5 there was no column, so every one of
    these was read from the file and then dropped on the floor."""
    add(player, tagged_file, qtbot)

    track = lib.get_track_by_path(tagged_file)
    assert track.year == "1997"
    assert track.track_number == "3"
    assert track.label == "Science"
    assert track.bitrate is not None


def test_reopening_the_playlist_shows_them_again(player, lib, tagged_file, qtbot):
    add(player, tagged_file, qtbot)
    player.load_node(SCRATCH_NODE_ID)
    qtbot.wait(10)

    entry = player._playlist[0]
    assert entry.year == "1997"
    assert entry.label == "Science"


def test_a_search_result_carries_them_without_opening_the_file(
    player, lib, tagged_file, qtbot
):
    """_entry_from_track builds rows for library tracks that aren't in the
    loaded list. It must read them off the row: a search can return two
    thousand of these, and opening two thousand files is not an option."""
    add(player, tagged_file, qtbot)
    track = lib.get_track_by_path(tagged_file)

    # The file is gone; the row is all there is. Via the helper because the
    # add just warmed this very file on a decode thread, and Windows will not
    # unlink a file that still has a handle open on it.
    unlink_when_released(player, tagged_file)
    entry = player._entry_from_track(track)

    assert entry.year == "1997"
    assert entry.track_number == "3"
    assert entry.label == "Science"


def test_the_keycode_follows_the_key_into_the_library(player, lib, tmp_path, qtbot):
    """Written nowhere by the Player, derived everywhere by the library —
    which is the point of deriving it inside add_track."""
    sf = pytest.importorskip("soundfile")
    path = tmp_path / "keyed.flac"
    sf.write(str(path), np.zeros(4410, dtype=np.float32), 44100, format="FLAC")
    write_metadata(str(path), TrackMetadata(key="Am"))

    add(player, str(path), qtbot)

    assert lib.get_track_by_path(str(path)).keycode == "8A"
