"""Dragging the now-playing line out as a file.

The line above the slicer is the only handle on the playing track that is
always present — the list below it may be showing a search or a different
playlist. These cover the handle itself (gesture, threshold, veto) rather
than the drop side, which the playlist-tree tests already own.
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from src.gui.widgets import player_panel as pp_mod
from src.gui.widgets.player_panel import NowPlayingLabel, PlayerPanel


@pytest.fixture
def player(qtbot):
    panel = PlayerPanel()
    qtbot.addWidget(panel)
    return panel


@pytest.fixture
def label(qtbot):
    lbl = NowPlayingLabel()
    qtbot.addWidget(lbl)
    return lbl


def audio_file(tmp_path, name="track.wav"):
    f = tmp_path / name
    f.write_bytes(b"audio")
    return str(f)


def press(widget, x=0):
    widget.mousePressEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(x, 0),
            QPointF(x, 0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )


def move(widget, x):
    widget.mouseMoveEvent(
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(x, 0),
            QPointF(x, 0),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )


def release(widget, x=0):
    widget.mouseReleaseEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(x, 0),
            QPointF(x, 0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )


@pytest.fixture
def drags(monkeypatch):
    """Record start_file_drag calls instead of entering Qt's blocking exec."""
    calls = []

    def fake(widget, page_id, paths):
        calls.append((page_id, paths))
        return Qt.DropAction.CopyAction

    monkeypatch.setattr(pp_mod, "start_file_drag", fake)
    return calls


class TestGesture:
    def test_drag_past_the_threshold_starts_a_file_drag(self, label, drags, tmp_path):
        path = audio_file(tmp_path)
        label.set_drag_source(lambda: path)

        press(label)
        move(label, QApplication.startDragDistance() + 5)

        # Page id "player" is what the sidebar's routing allow-list keys off.
        assert drags == [("player", [path])]

    def test_a_twitch_below_the_threshold_does_not(self, label, drags, tmp_path):
        label.set_drag_source(lambda: audio_file(tmp_path))
        press(label)
        move(label, 1)
        assert drags == []

    def test_a_move_without_a_press_does_not(self, label, drags, tmp_path):
        label.set_drag_source(lambda: audio_file(tmp_path))
        move(label, 100)
        assert drags == []

    def test_release_disarms_the_press(self, label, drags, tmp_path):
        label.set_drag_source(lambda: audio_file(tmp_path))
        press(label)
        release(label)
        move(label, 100)
        assert drags == []

    def test_a_vetoed_drag_does_not_re_fire(self, label, drags):
        """A source returning None must not leave the press armed — otherwise
        the next mouse twitch runs the veto (and its dialog) all over again."""
        asked = []
        label.set_drag_source(lambda: asked.append(1))  # returns None

        press(label)
        move(label, QApplication.startDragDistance() + 5)
        move(label, QApplication.startDragDistance() + 50)

        assert len(asked) == 1
        assert drags == []


class TestDragSource:
    def test_nothing_playing_has_nothing_to_drag(self, player):
        assert player._playing_path is None
        assert player._now_playing_drag_path() is None

    def test_the_playing_file_is_the_dragged_path(self, player, tmp_path):
        path = audio_file(tmp_path)
        player._playing_path = path
        assert player._now_playing_drag_path() == path

    def test_a_moved_file_is_vetoed_and_warned_about(self, player, tmp_path, qtbot):
        """A track plays on from the PCM cache after its file moves, so this
        line can name a file that isn't there — dragging it must not make a
        broken playlist entry."""
        path = audio_file(tmp_path)
        player._playing_path = path
        Path(path).unlink()

        warned = []
        player._warn_files_moved = warned.append

        assert player._now_playing_drag_path() is None
        qtbot.waitUntil(lambda: warned == [[path]], timeout=1000)

    def test_the_label_is_wired_to_the_panel(self, player, tmp_path):
        path = audio_file(tmp_path)
        player._playing_path = path
        assert player._now_playing_label._drag_fn() == path
