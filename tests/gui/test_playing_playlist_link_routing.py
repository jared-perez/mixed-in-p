"""The "In Playlist" link's other half: what MainWindow does with the click.

The panel only emits — the routing lives in MainWindow so the tree's selection
follows, exactly as it would had the playlist been clicked in the tree instead.
Covered here rather than in `test_playing_playlist_link.py` because it needs
the real wiring: a panel on its own has no tree to move.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.gui.main_window import MainWindow
from src.library import SCRATCH_NODE_ID


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    win._player_panel.shutdown_workers()


def make_files(tmp_path, *names):
    paths = []
    for name in names:
        f = tmp_path / name
        f.write_bytes(b"not-really-audio-" + name.encode())
        paths.append(str(f))
    return paths


def track_dicts(paths):
    return [{"file_path": p, "display_name": Path(p).name} for p in paths]


def test_the_link_loads_the_playlist_and_moves_the_tree(window, qtbot, tmp_path):
    lib = window._library
    player = window._player_panel
    (a,) = make_files(tmp_path, "a.wav")

    folder = lib.create_folder("Crates")
    source = lib.create_playlist("Warm Up", parent_id=folder)
    lib.set_items(source, [lib.add_track(a)])
    window._playlists_panel.ensure_loaded()

    player.load_node(source)
    player._play_track(0)
    player.load_node(SCRATCH_NODE_ID)  # wander off
    assert player.loaded_node_id == SCRATCH_NODE_ID

    player._playing_playlist_link.clicked.emit()

    assert player.loaded_node_id == source
    assert [e.file_path for e in player._playlist] == [a]
    # The tree agrees, with the folder that was hiding it opened.
    tree = window._playlists_panel.tree
    from src.gui.widgets.playlist_tree import NODE_ID_ROLE

    assert tree.currentIndex().data(NODE_ID_ROLE) == source
    assert tree.isExpanded(tree._find_item(folder).index())


def test_renaming_in_the_tree_reaches_the_link(window, qtbot, tmp_path):
    """A rename edits the tree item in place — no rebuild — so the tree has to
    say so explicitly or the Player goes on naming a playlist that is gone."""
    lib = window._library
    player = window._player_panel
    (a,) = make_files(tmp_path, "a.wav")
    source = lib.create_playlist("Old Name")
    lib.set_items(source, [lib.add_track(a)])
    window._playlists_panel.ensure_loaded()

    player.load_node(source)
    player._play_track(0)
    assert player._playing_playlist_link.text() == "In Playlist: Old Name"

    # The inline rename, driven the way the editor commits it.
    tree = window._playlists_panel.tree
    tree._find_item(source).setText("New Name")
    assert player._playing_playlist_link.text() == "In Playlist: New Name"

    # And a delete takes the link away rather than leaving a dead one.
    tree._library.delete_node(source)
    tree.refresh()
    assert player._playing_playlist_link.isHidden()


def test_clicking_the_list_already_showing_does_not_reload_it(
    window, qtbot, tmp_path, monkeypatch
):
    """It is not a no-op button — it still moves the tree — but reloading a
    500-track playlist to arrive where you already are would throw away the
    user's scroll position and selection for nothing."""
    lib = window._library
    player = window._player_panel
    (a,) = make_files(tmp_path, "a.wav")
    source = lib.create_playlist("Warm Up")
    lib.set_items(source, [lib.add_track(a)])
    window._playlists_panel.ensure_loaded()

    player.load_node(source)
    player._play_track(0)

    loads = []
    monkeypatch.setattr(player, "load_node", lambda node_id: loads.append(node_id))
    player._playing_playlist_link.clicked.emit()

    assert loads == []
    from src.gui.widgets.playlist_tree import NODE_ID_ROLE

    assert window._playlists_panel.tree.currentIndex().data(NODE_ID_ROLE) == source
