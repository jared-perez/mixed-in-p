"""Cmd/Ctrl+L jumps to the playlist the current track is playing from.

The keyboard sibling of the "In Playlist" link, whose own routing is covered in
`test_playing_playlist_link_routing.py`. What is only true of the hotkey is
tested here, and it is all about *where you were when you pressed it*: the link
only exists on the Player page, so it never had to switch pages, never had to
leave the sidebar alone, and never had to find the playing row in a list the
user had scrolled away from.

The key itself is read off PLAYING_PLAYLIST_SHORTCUT rather than spelled out,
so a re-binding moves the test with it and only the *choice* of key — which is
argued in that constant's comment — is stated in one place.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from src.gui.main_window import MainWindow
from src.gui.widgets.player_panel import PLAYING_PLAYLIST_SHORTCUT
from src.gui.widgets.playlist_tree import NODE_ID_ROLE
from src.library import SCRATCH_NODE_ID


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    yield win
    win._player_panel.shutdown_workers()


# The key that has to come back up for each modifier a shortcut holds down.
_MODIFIER_KEYS = (
    (Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Control),
    (Qt.KeyboardModifier.ShiftModifier, Qt.Key.Key_Shift),
    (Qt.KeyboardModifier.AltModifier, Qt.Key.Key_Alt),
    (Qt.KeyboardModifier.MetaModifier, Qt.Key.Key_Meta),
)


def press_hotkey(target) -> None:
    """Send whatever PLAYING_PLAYLIST_SHORTCUT is currently bound to.

    Qt maps ControlModifier onto Command on macOS at the event level, which is
    the same abstraction that lets the constant be one string for both
    platforms — so this is Cmd+L here and Ctrl+L on Windows without branching.

    The release matters. QTest.keyClick sends the modifier down but never lets
    it back up, and QGuiApplication.keyboardModifiers() is *application*
    state: it outlives the widget, the test and the fixture. The damage is
    silent and lands somewhere else entirely, because
    QAbstractItemView.selectRow asks selectionCommand() what to do and
    selectionCommand() reads those modifiers — so a later test's programmatic
    selectRow(1) becomes a Ctrl-click that *adds* row 1 to the selection
    instead of replacing it. That is a real bug this file caused (a search
    highlight test three files away began asserting the union of two rows) and
    the conftest guard now catches it, but a key that goes down should come
    back up here anyway.
    """
    combo = PLAYING_PLAYLIST_SHORTCUT[0]
    mods = combo.keyboardModifiers()
    QTest.keyClick(target, combo.key(), mods)
    for modifier, key in _MODIFIER_KEYS:
        if mods & modifier:
            QTest.keyRelease(target, key)


def centring_error(table, row) -> float:
    """Pixels between the middle of *row* and the middle of the viewport.

    Measured off the row geometry alone (rowViewportPosition/rowHeight) rather
    than a visualRect: column 0 is '#', which the panel hides during a search
    and which an optional-column layout can leave off, and a hidden column's
    rect is empty.

    Judged against a row height rather than to the pixel: PositionAtCenter
    lands the row on the centre within its own height, so which row owns the
    exact middle pixel is integer arithmetic and not the thing under test.
    """
    middle = table.rowViewportPosition(row) + table.rowHeight(row) / 2
    return abs(middle - table.viewport().height() / 2)


def centring_slack(table) -> float:
    """How far off the exact middle a *correct* PositionAtCenter may land.

    A row height was the obvious bound and is the wrong one, because the view
    scrolls per item: a row's middle can only sit on the row grid, at
    ``k * row_h + row_h / 2``, while the viewport's middle is wherever
    ``height / 2`` falls. The two are in phase only when the viewport is a
    whole number of rows tall, which is a fact about the platform's header and
    scrollbar metrics rather than about this panel. Measured here: a 583px
    viewport against a 30px row is 19.4 rows, so the nearest grid position to
    the middle is already 6.5px out, and Qt's own rounding inside scrollToItem
    lands a step further at 36.5px — a correct centring that a one-row
    tolerance calls a failure. macOS's viewport happens to put both inside one
    row, which is the only reason the flat bound ever passed.

    The middle third of the viewport instead: that is what "centred rather
    than merely on screen" means to someone looking at it, and it is the same
    statement in any font. It stays well clear of both ends — the callers
    assert the error starts above four row heights (120px against this bound's
    97px), so an implementation that does not scroll at all still fails.
    """
    return table.viewport().height() / 6


def make_files(tmp_path, count):
    paths = []
    for i in range(count):
        f = tmp_path / f"{i:03d}.wav"
        f.write_bytes(b"not-really-audio-%d" % i)
        paths.append(str(f))
    return paths


def stock(window, tmp_path, count=1, name="Warm Up"):
    """A saved playlist of *count* files, with the tree loaded."""
    lib = window._library
    paths = make_files(tmp_path, count)
    node = lib.create_playlist(name)
    lib.set_items(node, [lib.add_track(p) for p in paths])
    window._playlists_panel.ensure_loaded()
    return node, paths


def test_it_switches_to_the_player_and_loads_the_playing_list(
    window, qtbot, tmp_path
):
    player = window._player_panel
    node, paths = stock(window, tmp_path, count=3)

    player.load_node(node)
    player._play_track(0)
    player.load_node(SCRATCH_NODE_ID)  # wander off within the Player…
    window._sidebar.set_current_page("convert")  # …and off the page entirely
    window._on_page_changed("convert")
    assert window._current_page == "convert"

    press_hotkey(window)

    assert window._current_page == "player"
    assert window._pages.currentWidget() is player
    assert player.loaded_node_id == node
    assert [e.file_path for e in player._playlist] == paths
    # The tree agrees, so it is on the right row whenever it is next shown.
    assert window._playlists_panel.tree.currentIndex().data(NODE_ID_ROLE) == node


def test_it_leaves_the_sidebar_mode_alone(window, qtbot, tmp_path):
    """Showing the tree is Shift+Tab's job. One key, one job — pressing this
    one with the nav rail up must not also flip the rail away, and pressing it
    with the tree already up must not close it."""
    player = window._player_panel
    node, _ = stock(window, tmp_path)
    player.load_node(node)
    player._play_track(0)
    player.load_node(SCRATCH_NODE_ID)

    assert not window._sidebar.playlists_mode
    press_hotkey(window)
    assert not window._sidebar.playlists_mode

    window._sidebar.toggle_playlists_mode()
    assert window._sidebar.playlists_mode
    player.load_node(SCRATCH_NODE_ID)
    press_hotkey(window)
    assert window._sidebar.playlists_mode


def test_it_centres_the_playing_row(window, qtbot, tmp_path):
    """The point of the key mid-session: "where am I". A row merely made
    visible would sit at whichever edge it was scrolled past, so this asserts
    the row at the middle of the viewport, not just that it is on screen."""
    player = window._player_panel
    node, _ = stock(window, tmp_path, count=60)

    player.load_node(node)
    player._play_track(30)
    table = player._table
    table.scrollToTop()
    qtbot.wait(10)  # scroll ranges are lazy — see tests/gui/README.md
    row_h = table.rowHeight(30)
    assert centring_error(table, 30) > 4 * row_h  # nowhere near, to start

    press_hotkey(window)
    qtbot.wait(10)

    assert centring_error(table, 30) <= centring_slack(table)


def test_it_scrolls_even_when_the_list_is_already_showing(window, qtbot, tmp_path):
    """The commonest press of all: still on the playlist, scrolled away from
    the track. There is no load to do, so the scroll is the whole action — and
    a handler that only did its work inside the `not is_showing_node` branch
    would be a dead key in exactly this case."""
    player = window._player_panel
    node, _ = stock(window, tmp_path, count=60)

    player.load_node(node)
    player._play_track(30)
    table = player._table
    table.scrollToBottom()
    qtbot.wait(10)
    row_h = table.rowHeight(30)
    assert centring_error(table, 30) > 4 * row_h

    press_hotkey(window)
    qtbot.wait(10)

    assert player.loaded_node_id == node
    assert centring_error(table, 30) <= centring_slack(table)


def test_it_does_not_yank_a_scrolled_across_list_back_to_the_left(
    window, qtbot, tmp_path
):
    """scrollToItem moves BOTH axes, and this panel's rows are deliberately
    allowed to be wider than the viewport (_sync_title_row_width) — so a
    vertical request arrives with a horizontal jump stapled to it unless the
    across position is put back. Measured on the raw Qt call: 1704 -> 0.
    """
    player = window._player_panel
    node, _ = stock(window, tmp_path, count=60)
    player.load_node(node)
    player._play_track(30)

    table = player._table
    # Force a horizontal range this list would not otherwise have.
    table.setColumnWidth(1, table.viewport().width() + 800)
    qtbot.wait(20)
    bar = table.horizontalScrollBar()
    assert bar.maximum() > 0, "no horizontal range to preserve — test is vacuous"
    bar.setValue(bar.maximum())
    table.scrollToTop()
    bar.setValue(bar.maximum())
    qtbot.wait(10)
    across = bar.value()

    press_hotkey(window)
    qtbot.wait(10)

    assert centring_error(table, 30) <= centring_slack(table)  # it did scroll…
    assert bar.value() == across  # …and only downwards


def test_it_does_nothing_with_nothing_playing(window, qtbot, tmp_path):
    """Silently — there is no list to jump to, and inventing one (the loaded
    playlist, say, which is not where playback is) would be worse than the key
    appearing not to work."""
    player = window._player_panel
    stock(window, tmp_path)
    window._sidebar.set_current_page("convert")
    window._on_page_changed("convert")

    assert player.playing_node_id is None
    press_hotkey(window)

    assert window._current_page == "convert"  # not even the page switch


def test_it_does_nothing_for_a_track_played_out_of_a_search(
    window, qtbot, tmp_path, monkeypatch
):
    """A search result set is not a playlist, so there is nothing to return to
    — which the panel already records by leaving playing_node_id None."""
    player = window._player_panel
    node, paths = stock(window, tmp_path, count=3)
    player.load_node(node)

    player._search_active = True
    player._play_track(0)
    assert player.playing_node_id is None

    loads = []
    monkeypatch.setattr(player, "load_node", lambda n: loads.append(n))
    press_hotkey(window)
    assert loads == []


def test_the_link_tooltip_advertises_the_key(window, tmp_path):
    """One source for the key and the label it is announced by, the same
    arrangement the Playlists button has — so they cannot drift apart."""
    from PySide6.QtGui import QKeySequence

    native = PLAYING_PLAYLIST_SHORTCUT.toString(
        QKeySequence.SequenceFormat.NativeText
    )
    tip = window._player_panel._playing_playlist_link.toolTip()
    assert native in tip
    # The translated sentence is still its own string, un-edited: the key was
    # appended outside it so no .ts entry was orphaned.
    assert tip.startswith("Open the playlist the current track is playing from")
