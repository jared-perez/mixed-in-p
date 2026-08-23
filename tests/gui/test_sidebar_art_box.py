"""The big album art at the foot of the sidebar.

Clicking the Player's 56px header cover opens the same picture at the rail's
full inner width (164px), above Settings. Three things this file guards:

- Where it sits. It goes into the sidebar's *outer* layout, between the mode
  stack and Settings — "above Settings" is the brief, and the two bottom
  buttons must not get pulled up into the nav list by it.
- What it costs when nobody opens it. The sidebar's min_content_height sums
  its layout's size hints and the window sizer turns that into the window's
  minimum height, so a box that is closed must contribute nothing.
- That it follows the playing track, and shows a placeholder rather than
  disappearing when there is nothing to show.

Visibility is asserted as ``isHidden()`` throughout: offscreen, nothing is
ever ``isVisible()`` (CLAUDE.md), and the box additionally has an open state
that is not the same question as being on screen.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QPushButton

from src.gui.main_window import MainWindow
from src.gui.widgets.player_panel import PlayerPanel
from src.gui.widgets.sidebar import Sidebar
from src.gui.widgets.sidebar_art_box import SidebarArtBox
from src.metadata.tags import TrackMetadata, write_metadata

RED = "#c02020"
BLUE = "#2040c0"


def cover(tmp_path, colour, size=240):
    image = QImage(size, size, QImage.Format.Format_RGB32)
    image.fill(QColor(colour))
    path = tmp_path / f"cover-{colour.strip('#')}.png"
    image.save(str(path))
    return path.read_bytes()


def make_track(sf, tmp_path, name, art=None):
    path = tmp_path / name
    sf.write(str(path), np.zeros(4410, dtype=np.float32), 44100, format="FLAC")
    if art is not None:
        write_metadata(
            str(path),
            TrackMetadata(title=name, artwork=art, artwork_mime="image/png"),
        )
    return str(path)


@pytest.fixture
def sf():
    return pytest.importorskip("soundfile")


@pytest.fixture
def sidebar(qtbot):
    """A rail at a real geometry.

    Size matters here in a way it does not for most widgets: the cover's side
    is budgeted from the rail's height, so an unsized (0-tall) sidebar has no
    room for it and every test would measure a hidden box.
    """
    bar = Sidebar()
    qtbot.addWidget(bar)
    bar.resize(176, 900)
    bar.show()
    qtbot.waitExposed(bar)
    return bar


class TestWhereItSits:
    def test_it_is_closed_and_invisible_to_the_layout_by_default(self, sidebar):
        assert not sidebar.art_box_open()
        assert sidebar._art_box.isHidden()

    def test_it_sits_between_the_mode_stack_and_settings(self, sidebar):
        """Read off the laid-out rail rather than from attributes, so this
        measures the arrangement rather than the order things were built in."""
        layout = sidebar.layout()
        order = []
        for i in range(layout.count()):
            widget = layout.itemAt(i).widget()
            if widget is sidebar._mode_stack:
                order.append("stack")
            elif widget is sidebar._art_box:
                order.append("art")
            elif widget is sidebar._settings_btn:
                order.append("settings")
            elif widget is sidebar._history_btn:
                order.append("history")
        assert order == ["stack", "art", "settings", "history"]

    def test_it_fills_the_rails_inner_width_when_there_is_room(
        self, sidebar, qtbot
    ):
        """164px, the rail minus its own margins. A literal 4x of the 56px
        header art would be 224 and does not fit a 176px rail at all."""
        sidebar.show_art_box(None)
        margins = sidebar.layout().contentsMargins()
        inner = 176 - margins.left() - margins.right()

        assert sidebar._art_box.width() == inner
        assert sidebar._art_box.height() == inner

    def test_a_closed_box_costs_the_rail_nothing(self, sidebar):
        """min_content_height feeds the window's minimum height, so a cover
        nobody opened must not be part of it."""
        closed = sidebar.min_content_height()
        sidebar.show_art_box(None)
        assert sidebar.min_content_height() == closed


class TestItTakesOnlyTheRoomThatIsSpare:
    """The rail cannot scroll, so a box pinned at 164px pushes Settings and
    History off the bottom of a short window — measured at the 480px height
    floor, Settings landed 59px below the rail. The side is a budget: what is
    left once everything else has its minimum, capped at the rail's inner
    width.
    """

    def open_at(self, sidebar, qtbot, height):
        """Resize the rail and open the box on the new geometry.

        Waits for the height to actually land rather than for a fixed few
        milliseconds: a resize goes through the platform window, and under a
        full-suite load a 10ms wait loses that race — the box then gets sized
        from the *old* height and the test reads a number for a rail that no
        longer exists.
        """
        sidebar.resize(176, height)
        qtbot.waitUntil(lambda: sidebar.height() == height)
        sidebar.show_art_box(None)
        return sidebar._art_box

    def test_the_bottom_buttons_stay_on_the_rail_at_any_height(
        self, sidebar, qtbot
    ):
        # Starts at the reserve because that *is* the rail's own minimum
        # height — Qt refuses to shrink it further, so there is no shorter
        # case to check.
        reserve = sidebar._art_reserve()
        for height in (reserve, reserve + 90, reserve + 400):
            box = self.open_at(sidebar, qtbot, height)
            bottom = sidebar._history_btn.y() + sidebar._history_btn.height()
            assert bottom <= height, f"History off the rail at {height}px"
            assert box.height() <= 164

    def test_a_middling_height_gets_a_smaller_square(self, sidebar, qtbot):
        """The height is derived from the rail's own reserve rather than
        written down: the reserve is a sum of font-dependent button hints, so
        a literal number here would be a number for one machine's fonts."""
        box = self.open_at(sidebar, qtbot, sidebar._art_reserve() + 90)

        assert box.height() == 90
        assert box.width() == box.height(), "still square"

    def test_too_little_room_shows_nothing_but_stays_open(
        self, sidebar, qtbot
    ):
        """A two-pixel sliver reads as damage. The box stays *open* though, so
        making the window taller brings it back without another click."""
        reserve = sidebar._art_reserve()
        box = self.open_at(sidebar, qtbot, reserve + 10)
        assert box.isHidden()
        assert sidebar.art_box_open()

        tall = reserve + 400
        sidebar.resize(176, tall)
        qtbot.waitUntil(lambda: sidebar.height() == tall)
        assert not box.isHidden()
        assert box.height() == 164


class TestOpeningAndClosing:
    def test_show_opens_it(self, sidebar, tmp_path):
        sidebar.show_art_box(cover(tmp_path, RED))
        assert sidebar.art_box_open()
        assert not sidebar._art_box.isHidden()
        assert sidebar._art_box.has_artwork()

    def test_the_close_button_closes_it(self, sidebar, tmp_path):
        sidebar.show_art_box(cover(tmp_path, RED))
        sidebar._art_box._close_btn.click()
        assert not sidebar.art_box_open()
        assert sidebar._art_box.isHidden()

    def test_no_artwork_shows_a_placeholder_rather_than_closing(self, sidebar):
        """A box that vanishes on Stop reads as a crash, not as an empty
        state."""
        sidebar.show_art_box(None)
        assert sidebar.art_box_open()
        assert not sidebar._art_box.isHidden()
        assert not sidebar._art_box.has_artwork()

    def test_junk_bytes_fall_back_to_the_placeholder(self, sidebar):
        sidebar.show_art_box(b"not an image")
        assert not sidebar._art_box.has_artwork()
        assert not sidebar._art_box.isHidden()

    def test_set_art_leaves_a_closed_box_closed(self, sidebar, tmp_path):
        """Track changes arrive whether or not anyone is looking."""
        sidebar.set_art(cover(tmp_path, RED))
        assert not sidebar.art_box_open()
        assert sidebar._art_box.isHidden()


class TestCollapsingTheRail:
    """44px of cover is noise, so the box hides while the rail is collapsed —
    without forgetting that the user asked for it."""

    def test_collapsing_hides_it_and_expanding_brings_it_back(
        self, sidebar, tmp_path
    ):
        sidebar.show_art_box(cover(tmp_path, RED))

        sidebar.set_collapsed(True)
        assert sidebar._art_box.isHidden()
        assert sidebar.art_box_open(), "collapsing is not closing"

        sidebar.set_collapsed(False)
        assert not sidebar._art_box.isHidden()

    def test_expanding_does_not_open_a_box_nobody_opened(self, sidebar):
        sidebar.set_collapsed(True)
        sidebar.set_collapsed(False)
        assert sidebar._art_box.isHidden()

    def test_opening_while_collapsed_waits_for_the_expand(
        self, sidebar, tmp_path
    ):
        sidebar.set_collapsed(True)
        sidebar.show_art_box(cover(tmp_path, RED))
        assert sidebar._art_box.isHidden()

        sidebar.set_collapsed(False)
        assert not sidebar._art_box.isHidden()


class TestTheBoxItself:
    def test_the_side_is_an_input_not_a_hint(self, qtbot, tmp_path):
        """A QLabel holding a pixmap reports that pixmap as its size hint, so
        a box that sized itself from its own contents would converge on its
        first picture and never grow again. Applying a size twice is what
        catches that — one pass is stable in the broken build too."""
        box = SidebarArtBox()
        qtbot.addWidget(box)
        box.set_artwork(cover(tmp_path, RED))

        box.set_side(120)
        assert box.size().toTuple() == (120, 120)
        box.set_side(200)
        assert box.size().toTuple() == (200, 200)
        box.set_side(200)
        assert box.size().toTuple() == (200, 200)

    def test_the_close_button_keeps_a_label_to_draw(self, qtbot):
        """The global QPushButton padding is 8px/16px; this button is 18px
        square, so its rule must zero that or there is no contents rect and
        the glyph is simply not drawn. The suite has no stylesheet, so it can
        only check the button is small and carries text — the drawing was
        ground-truthed by rendering it."""
        box = SidebarArtBox()
        qtbot.addWidget(box)
        assert box._close_btn.text()
        assert box._close_btn.width() <= 24
        assert box._close_btn.objectName() == "sidebarArtClose"


class TestTheHeaderArtIsTheDoor:
    def test_clicking_the_header_art_asks_the_panel_to_announce_it(
        self, qtbot
    ):
        panel = PlayerPanel()
        qtbot.addWidget(panel)
        with qtbot.waitSignal(panel.art_clicked):
            panel._art_label.clicked.emit()

    def test_the_header_art_says_what_a_click_does(self, qtbot):
        panel = PlayerPanel()
        qtbot.addWidget(panel)
        assert panel._art_label.toolTip()


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    win._player_panel.shutdown_workers()


class TestTheWholeGesture:
    """Driven through a real MainWindow, because the wiring between a panel
    that owns no sidebar and a sidebar that owns no player is the feature.

    Playback is *not* part of it: the box reads the playing path's tags, and
    the path is all it needs. Setting it and calling _update_now_playing runs
    the real signal chain (now_playing_changed -> _sync_sidebar_art) without
    opening an audio stream — which matters, because these are real tagged
    FLACs rather than the fake bytes the other MainWindow tests use, and they
    really would decode and play.
    """

    def set_playing(self, window, qtbot, path):
        player = window._player_panel
        player._playing_path = path
        player._update_now_playing()
        qtbot.wait(10)

    def test_a_click_opens_the_cover_of_the_playing_track(
        self, window, qtbot, sf, tmp_path
    ):
        track = make_track(sf, tmp_path, "red.flac", cover(tmp_path, RED))
        self.set_playing(window, qtbot, track)

        window._player_panel.art_clicked.emit()

        assert window._sidebar.art_box_open()
        assert window._sidebar._art_box.has_artwork()

    def test_the_next_track_swaps_the_picture(
        self, window, qtbot, sf, tmp_path
    ):
        """Sampled off the rendered box, not off a data role: the question is
        which pixels reached the screen. Indexed in *device* pixels — a grab
        on a Retina screen is twice the logical size, and reading it with
        logical coordinates samples the top-left corner of everything."""
        red = make_track(sf, tmp_path, "red.flac", cover(tmp_path, RED))
        blue = make_track(sf, tmp_path, "blue.flac", cover(tmp_path, BLUE))
        self.set_playing(window, qtbot, red)
        window._player_panel.art_clicked.emit()
        box = window._sidebar._art_box
        box.show()
        qtbot.wait(10)

        def middle():
            image = box.grab().toImage()
            ratio = image.devicePixelRatio()
            return image.pixelColor(
                int(box.width() / 2 * ratio), int(box.height() / 2 * ratio)
            )

        was = middle()
        assert was == QColor(RED), "the cover is not what reached the screen"

        self.set_playing(window, qtbot, blue)

        assert middle() == QColor(BLUE)

    def test_stopping_leaves_the_box_open_on_the_placeholder(
        self, window, qtbot, sf, tmp_path
    ):
        track = make_track(sf, tmp_path, "red.flac", cover(tmp_path, RED))
        self.set_playing(window, qtbot, track)
        window._player_panel.art_clicked.emit()
        assert window._sidebar._art_box.has_artwork()

        self.set_playing(window, qtbot, None)

        assert window._sidebar.art_box_open(), "a box that vanishes reads as a crash"
        assert not window._sidebar._art_box.has_artwork()

    def test_a_track_with_no_cover_shows_the_placeholder(
        self, window, qtbot, sf, tmp_path
    ):
        bare = make_track(sf, tmp_path, "bare.flac")
        self.set_playing(window, qtbot, bare)

        window._player_panel.art_clicked.emit()

        assert window._sidebar.art_box_open()
        assert not window._sidebar._art_box.has_artwork()


def test_settings_and_history_are_still_the_last_two_buttons(sidebar):
    """The pinning this feature inserts above — restated here because the box
    goes into the same outer layout those two are pinned to."""
    layout = sidebar.layout()
    buttons = [
        layout.itemAt(i).widget()
        for i in range(layout.count())
        if isinstance(layout.itemAt(i).widget(), QPushButton)
    ]
    assert buttons[-2:] == [sidebar._settings_btn, sidebar._history_btn]

