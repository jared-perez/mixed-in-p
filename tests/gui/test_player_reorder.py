"""Dragging rows into a new order must move tracks, never edit them.

The reorder handler moves QTableWidgetItems by hand (takeItem / removeRow /
insertRow / setItem), and setItem emits itemChanged — the same signal an
inline metadata edit commits through. Mid-reorder ``self._playlist`` still
holds the pre-drag order, so an unguarded reorder reads the dragged track's
text as a *user edit of the entry that used to live at the destination row*:
the hovered track's artist/title are overwritten in the playlist AND written
into that other file's tags on disk. Edit Lock does not gate the commit
handler (only the edit triggers), so the corruption is lock-independent.

These tests drive ``_handle_internal_reorder`` with a real QDropEvent and
assert both halves: rows land in the new order with every entry keeping its
own fields, and the tag writer is never called by a drag.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QDropEvent

from src.gui.widgets import player_panel as player_panel_mod
from src.gui.widgets.player_panel import PlayerPanel
from src.library import Library

ARTIST, TITLE = 2, 3


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
def tag_writes(monkeypatch):
    """Record (path, metadata, fields) for every write_metadata call.

    Patched on the player_panel module because that is the binding
    _on_item_changed calls through (module-level import).
    """
    calls: list[tuple] = []
    monkeypatch.setattr(
        player_panel_mod,
        "write_metadata",
        lambda path, meta, fields=None: calls.append((path, meta, fields)),
    )
    return calls


def stock(player, tmp_path):
    """Three tracks with distinct artists/titles, in a known order."""
    tracks = []
    for name, artist, title in [
        ("a.wav", "Alice", "Alpha"),
        ("b.wav", "Bob", "Bravo"),
        ("c.wav", "Carol", "Charlie"),
    ]:
        f = tmp_path / name
        f.write_bytes(b"not-really-audio-" + name.encode())
        tracks.append(
            {
                "file_path": str(f),
                "display_name": name,
                "artist": artist,
                "title": title,
            }
        )
    player.add_tracks(tracks, allow_duplicates=True)
    return tracks


def drag_row_onto(player, qtbot, src_row, target_row):
    """Reorder via the real drop handler: drag src_row, release over the
    upper half of target_row (the drop that lands *on* a track, which is
    the gesture that corrupted it)."""
    table = player._table
    # Lazy layout: visualRect answers stale geometry until the view is shown
    # and the event loop has run (tests/gui/README.md).
    player.show()
    qtbot.wait(10)
    table.selectRow(src_row)
    rect = table.visualRect(table.model().index(target_row, 0))
    pos = QPointF(float(rect.center().x()), float(rect.top() + 1))
    mime = QMimeData()  # must outlive the event — QDropEvent keeps a raw pointer
    event = QDropEvent(
        pos,
        Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    table._handle_internal_reorder(event)
    return event, mime


class TestReorderDoesNotEdit:
    def test_rows_move_and_every_entry_keeps_its_own_fields(
        self, player, qtbot, tmp_path, tag_writes
    ):
        stock(player, tmp_path)
        drag_row_onto(player, qtbot, src_row=0, target_row=2)

        assert [e.display_name for e in player._playlist] == [
            "b.wav",
            "a.wav",
            "c.wav",
        ]
        assert [(e.artist, e.title) for e in player._playlist] == [
            ("Bob", "Bravo"),
            ("Alice", "Alpha"),
            ("Carol", "Charlie"),
        ]

    def test_the_rendered_cells_agree(self, player, qtbot, tmp_path, tag_writes):
        stock(player, tmp_path)
        drag_row_onto(player, qtbot, src_row=2, target_row=0)

        table = player._table
        assert [table.item(r, ARTIST).text() for r in range(3)] == [
            "Carol",
            "Alice",
            "Bob",
        ]
        assert [table.item(r, TITLE).text() for r in range(3)] == [
            "Charlie",
            "Alpha",
            "Bravo",
        ]

    def test_a_drag_never_writes_tags(self, player, qtbot, tmp_path, tag_writes):
        """The corruption's on-disk half: mid-reorder itemChanged committed
        the dragged track's text into the hovered track's file."""
        stock(player, tmp_path)
        drag_row_onto(player, qtbot, src_row=0, target_row=2)

        assert tag_writes == []
