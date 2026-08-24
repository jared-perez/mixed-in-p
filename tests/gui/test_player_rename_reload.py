"""The Player follows a rename of a file it is showing.

library.update_paths re-points the library rows the moment a rename lands, so
the playlist is correct on disk. The Player's visible entries are not: they
still hold the old path, and its next _persist_playlist writes the *visible*
list back — add_track() on a file that no longer exists, then set_items()
pointing the playlist at that new row. Two rows, one of them dead.

The hazard predates the pipeline (anyone analysing a file the Player has open
hits it); the pipeline makes it the common case, because watching a run fill a
playlist is the natural thing to do while it runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QObject

from src.gui.main_window import MainWindow
from src.gui.widgets.player_panel import PlayerPanel
from src.library import Library
from src.metadata import read_metadata
from src.renamer.history import RenameRecord, RenameSession


@pytest.fixture(scope="session", autouse=True)
def warm_tag_reader(tmp_path_factory):
    """Pull mutagen's lazy imports in on the main thread before any decode
    thread can race them — two threads in the import lock abort the process."""
    warm = tmp_path_factory.mktemp("warm") / "warm.wav"
    warm.write_bytes(b"not really audio")
    try:
        read_metadata(str(warm))
    except Exception:  # noqa: BLE001 — we want the imports, not the tags
        pass


@pytest.fixture
def lib():
    library = Library()
    yield library
    library.close()


@pytest.fixture
def player(qtbot, lib):
    panel = PlayerPanel()
    qtbot.addWidget(panel)
    panel.set_library(lib)
    return panel


class WindowStub(QObject):
    """The reload hook, over a self that owns only a Player."""

    _reload_player_for_renamed = MainWindow._reload_player_for_renamed

    def __init__(self, player):
        super().__init__()
        self._player_panel = player


def _session(pairs):
    return RenameSession(
        session_id="s1",
        records=[
            RenameRecord(original_path=old, new_path=new, timestamp="")
            for old, new in pairs
        ],
        timestamp="",
    )


def _file(tmp_path, name) -> str:
    path = tmp_path / name
    path.write_bytes(b"audio-" + name.encode())
    return str(path)


def _load(player, lib, node_id, paths):
    lib.add_items(node_id, [lib.add_track(p) for p in paths])
    player.load_node(node_id)


def test_the_visible_list_follows_the_rename(player, lib, tmp_path, qtbot):
    node_id = lib.create_playlist("Pipeline test")
    old = _file(tmp_path, "a.wav")
    _load(player, lib, node_id, [old])
    assert player.shows_any_path([old])

    new = str(tmp_path / "128 - 8A - a.wav")
    Path(old).rename(new)
    lib.update_paths([(old, new)])
    WindowStub(player)._reload_player_for_renamed([old])

    assert not player.shows_any_path([old])
    assert player.shows_any_path([new])


def test_a_persist_after_the_reload_leaves_exactly_one_row(player, lib, tmp_path):
    """The point of the reload: without it the write-back resurrects the old
    path as a second library row and points the playlist at it."""
    node_id = lib.create_playlist("Pipeline test")
    old = _file(tmp_path, "a.wav")
    _load(player, lib, node_id, [old])

    new = str(tmp_path / "128 - 8A - a.wav")
    Path(old).rename(new)
    lib.update_paths([(old, new)])
    WindowStub(player)._reload_player_for_renamed([old])

    player._persist_playlist()
    items = lib.get_items(node_id)
    assert [i.path for i in items] == [new]
    assert lib.get_track_by_path(old) is None


def test_a_player_showing_another_playlist_is_not_reloaded(player, lib, tmp_path):
    other = lib.create_playlist("Other")
    renamed_in = lib.create_playlist("Renamed in here")
    shown = _file(tmp_path, "shown.wav")
    elsewhere = _file(tmp_path, "elsewhere.wav")
    lib.add_items(renamed_in, [lib.add_track(elsewhere)])
    _load(player, lib, other, [shown])

    new = str(tmp_path / "renamed.wav")
    Path(elsewhere).rename(new)
    lib.update_paths([(elsewhere, new)])
    WindowStub(player)._reload_player_for_renamed([elsewhere])

    assert player.shows_any_path([shown])  # untouched


def test_nothing_renamed_is_a_no_op(player, lib, tmp_path):
    node_id = lib.create_playlist("Pipeline test")
    path = _file(tmp_path, "a.wav")
    _load(player, lib, node_id, [path])
    WindowStub(player)._reload_player_for_renamed([])
    assert player.shows_any_path([path])


def test_a_search_is_not_thrown_away(player, lib, tmp_path, monkeypatch):
    """load_node dismisses a search rather than declining, and _persist_playlist
    already refuses to write while one is showing — so there is nothing to fix
    and everything to lose."""
    node_id = lib.create_playlist("Pipeline test")
    old = _file(tmp_path, "a.wav")
    _load(player, lib, node_id, [old])
    player._search_active = True
    loads = []
    monkeypatch.setattr(player, "load_node", lambda n: loads.append(n))

    new = str(tmp_path / "renamed.wav")
    Path(old).rename(new)
    lib.update_paths([(old, new)])
    WindowStub(player)._reload_player_for_renamed([old])
    assert loads == []


def test_a_sorted_list_still_follows_the_rename(player, lib, tmp_path):
    """A sorted list writes the *canonical* order back, so that is the list a
    stale path would be written from — the question has to be asked of it."""
    node_id = lib.create_playlist("Pipeline test")
    a, b = _file(tmp_path, "b.wav"), _file(tmp_path, "a.wav")
    _load(player, lib, node_id, [a, b])
    player._on_header_clicked(1)  # sort by filename
    assert player._sorted
    assert player.shows_any_path([a])

    new = str(tmp_path / "renamed.wav")
    Path(a).rename(new)
    lib.update_paths([(a, new)])
    WindowStub(player)._reload_player_for_renamed([a])
    assert player.shows_any_path([new])
    assert not player.shows_any_path([a])
