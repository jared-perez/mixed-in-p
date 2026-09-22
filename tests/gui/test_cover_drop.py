"""Dropping an image on the playing track's cover makes it the new cover.

Two covers take the drop — the Player's 56px header art and the big box at
the foot of the sidebar — and both write to the *loaded* track only, never a
playlist row, so a drop can't land a row off. Both follow the Edit Lock the
way inline tag editing does, and neither is offered for a format that keeps
no tags.

With no cover, the header shows an empty square rather than nothing, so
there is somewhere to drop one.

Playback isn't needed: the covers read the loaded path's tags, so the tests
set the path and run the same refresh a track change does, without opening
an audio stream (see test_sidebar_art_box.TestTheWholeGesture).
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QImage

from src.gui.main_window import MainWindow
from src.gui.widgets.player_panel import PlayerPanel
from src.metadata.tags import read_metadata

RED = "#c02020"


@pytest.fixture
def sf():
    return pytest.importorskip("soundfile")


def make_track(sf, tmp_path, name, fmt="FLAC"):
    path = tmp_path / name
    sf.write(str(path), np.zeros(4410, dtype=np.float32), 44100, format=fmt)
    return str(path)


def make_image(tmp_path, name="cover.png"):
    image = QImage(64, 64, QImage.Format.Format_RGB32)
    image.fill(QColor(RED))
    path = tmp_path / name
    image.save(str(path))
    return path


def url_mime(path) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    return mime


def drop_event(mime: QMimeData) -> QDropEvent:
    """The caller holds *mime* for the event's life: QDropEvent keeps only a
    raw pointer to it (CLAUDE.md)."""
    return QDropEvent(
        QPointF(5, 5),
        Qt.DropAction.CopyAction | Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def enter_event(mime: QMimeData) -> QDragEnterEvent:
    return QDragEnterEvent(
        QPoint(5, 5),
        Qt.DropAction.CopyAction | Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def load(panel: PlayerPanel, path: str | None) -> None:
    """Make *path* the loaded track, as a track change would."""
    panel._playing_path = path
    if path is None:
        panel._hide_artwork()
    else:
        panel._show_current_artwork()


def set_locked(panel: PlayerPanel, locked: bool) -> None:
    panel._edit_lock_cb.setChecked(locked)


@pytest.fixture
def panel(qtbot):
    p = PlayerPanel()
    qtbot.addWidget(p)
    set_locked(p, False)
    yield p
    p.shutdown_workers()


# ------------------------------------------------------------- header square


class TestTheEmptySquare:
    def test_a_loaded_track_with_no_cover_shows_the_square(self, panel, sf, tmp_path):
        load(panel, make_track(sf, tmp_path, "bare.flac"))

        art = panel._art_label
        assert not art.isHidden(), "nowhere to drop a cover"
        assert not art.has_cover()

    def test_nothing_loaded_shows_nothing(self, panel):
        load(panel, None)
        assert panel._art_label.isHidden()

    def test_the_square_invites_a_drop_only_when_it_would_take_one(
        self, panel, sf, tmp_path
    ):
        """The "Drop…" line is the difference between the two paints."""
        load(panel, make_track(sf, tmp_path, "bare.flac"))
        art = panel._art_label
        art.show()
        inviting = art.grab().toImage()

        set_locked(panel, True)

        assert art.grab().toImage() != inviting


# ---------------------------------------------------------------- who may drop


class TestWhenADropIsTaken:
    def test_unlocked_with_a_track_loaded(self, panel, sf, tmp_path):
        load(panel, make_track(sf, tmp_path, "bare.flac"))
        assert panel.artwork_editable()
        assert panel._art_label.is_droppable()
        assert panel._art_label.acceptDrops()

    def test_not_under_the_edit_lock(self, panel, sf, tmp_path):
        load(panel, make_track(sf, tmp_path, "bare.flac"))
        set_locked(panel, True)
        assert not panel.artwork_editable()
        assert not panel._art_label.acceptDrops()

        set_locked(panel, False)
        assert panel.artwork_editable()

    def test_not_with_nothing_loaded(self, panel):
        load(panel, None)
        assert not panel.artwork_editable()

    def test_not_for_a_wav(self, panel, sf, tmp_path):
        load(panel, make_track(sf, tmp_path, "bare.wav", fmt="WAV"))
        assert not panel.artwork_editable()

    def test_the_answer_is_announced_as_it_changes(self, panel, qtbot, sf, tmp_path):
        track = make_track(sf, tmp_path, "bare.flac")
        with qtbot.waitSignal(panel.art_editable_changed) as blocker:
            load(panel, track)
        assert blocker.args == [True]
        with qtbot.waitSignal(panel.art_editable_changed) as blocker:
            set_locked(panel, True)
        assert blocker.args == [False]


# ------------------------------------------------------------------ the write


class TestDroppingOnTheHeader:
    def test_the_image_becomes_the_loaded_tracks_cover(
        self, panel, qtbot, sf, tmp_path
    ):
        track = make_track(sf, tmp_path, "bare.flac")
        other = make_track(sf, tmp_path, "other.flac")
        image = make_image(tmp_path)
        load(panel, track)

        mime = url_mime(image)
        event = drop_event(mime)
        with qtbot.waitSignal(panel.playing_artwork_changed):
            panel._art_label.dropEvent(event)

        assert event.isAccepted()
        assert event.dropAction() == Qt.DropAction.CopyAction
        assert read_metadata(track).artwork == image.read_bytes()
        assert read_metadata(other).artwork is None
        assert panel._art_label.has_cover()

    def test_a_drag_is_refused_under_the_lock(self, panel, sf, tmp_path):
        track = make_track(sf, tmp_path, "bare.flac")
        load(panel, track)
        set_locked(panel, True)

        mime = url_mime(make_image(tmp_path))
        event = enter_event(mime)
        panel._art_label.dragEnterEvent(event)
        assert not event.isAccepted()

        # Even a drop that got here anyway writes nothing.
        drop = drop_event(mime)
        panel._art_label.dropEvent(drop)
        assert read_metadata(track).artwork is None

    def test_a_file_that_only_claims_to_be_an_image_is_refused(
        self, panel, sf, tmp_path
    ):
        track = make_track(sf, tmp_path, "bare.flac")
        load(panel, track)
        fake = tmp_path / "fake.png"
        fake.write_bytes(b"not an image")

        mime = url_mime(fake)
        event = drop_event(mime)
        panel._art_label.dropEvent(event)

        assert not event.isAccepted()
        assert read_metadata(track).artwork is None

    def test_the_art_column_forgets_what_it_knew(self, panel, sf, tmp_path):
        track = make_track(sf, tmp_path, "bare.flac")
        load(panel, track)
        panel._art_missing.add(panel._art_key(track))

        assert panel.set_playing_artwork(make_image(tmp_path).read_bytes(), "image/png")

        assert not any(key[0] == track for key in panel._art_missing)


# ------------------------------------------------------------ the sidebar box


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    set_locked(win._player_panel, False)
    yield win
    win._player_panel.shutdown_workers()


class TestDroppingOnTheSidebarBox:
    def test_it_follows_the_players_answer(self, window, sf, tmp_path):
        box = window._sidebar._art_box
        assert not box.is_droppable(), "nothing is loaded"

        load(window._player_panel, make_track(sf, tmp_path, "bare.flac"))
        assert box.is_droppable()

        set_locked(window._player_panel, True)
        assert not box.is_droppable()

    def test_a_drop_writes_the_playing_track_and_shows_it(
        self, window, qtbot, sf, tmp_path
    ):
        player = window._player_panel
        track = make_track(sf, tmp_path, "bare.flac")
        load(player, track)
        player.art_clicked.emit()  # open the box
        box = window._sidebar._art_box
        assert not box.has_artwork()

        image = make_image(tmp_path)
        mime = url_mime(image)
        event = drop_event(mime)
        box.dropEvent(event)

        assert event.isAccepted()
        assert read_metadata(track).artwork == image.read_bytes()
        assert box.has_artwork(), "the open box still shows the placeholder"
        assert player._art_label.has_cover()
