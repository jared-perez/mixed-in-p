"""The Player's two slice views are independent toggles.

"Waveform" opens the full-track waveform (which is then the seek control);
"Loop Slicer" opens the zoomed scrubber and the slice controls. Either alone,
both, or neither — and only the pair together is the view the single combined
header used to give.

Visibility is asserted with ``isHidden()``, not ``isVisible()``: nothing is
shown in an offscreen suite, so ``isVisible()`` is False for every widget here
and an assertion on it would pass against any build.
"""

import pytest

from src.gui.widgets.player_engine import PlayerEngine
from src.gui.widgets.slice_section import SliceSection

DURATION_MS = 240_000


@pytest.fixture
def section(qtbot):
    sec = SliceSection(PlayerEngine())
    qtbot.addWidget(sec)
    return sec


@pytest.fixture
def loaded(section, tmp_path):
    """A section pointed at a track, i.e. with both toggles enabled."""
    track = tmp_path / "track.wav"
    track.write_bytes(b"not-really-audio")
    section.set_track(str(track), DURATION_MS)
    return section


class TestHeaderToggles:
    def test_both_views_start_closed(self, loaded):
        assert loaded._waveform.isHidden()
        assert loaded._body.isHidden()
        assert not loaded.is_waveform_shown()
        assert not loaded.is_expanded()
        assert not loaded.is_open()

    def test_waveform_opens_only_the_full_waveform(self, loaded):
        loaded._waveform_btn.setChecked(True)

        assert not loaded._waveform.isHidden()
        assert loaded._body.isHidden(), "the slice tray is the other button's job"
        assert loaded.is_waveform_shown()
        assert not loaded.is_expanded()

    def test_loop_slicer_opens_only_the_tray(self, loaded):
        loaded._slicer_btn.setChecked(True)

        assert not loaded._body.isHidden()
        assert loaded._waveform.isHidden(), "the full waveform is the other button's job"
        assert loaded.is_expanded()
        assert not loaded.is_waveform_shown()

    def test_both_together_give_the_whole_slicer(self, loaded):
        loaded._waveform_btn.setChecked(True)
        loaded._slicer_btn.setChecked(True)

        assert not loaded._waveform.isHidden()
        assert not loaded._body.isHidden()

    def test_closing_one_leaves_the_other_open(self, loaded):
        loaded._waveform_btn.setChecked(True)
        loaded._slicer_btn.setChecked(True)

        loaded._slicer_btn.setChecked(False)

        assert not loaded._waveform.isHidden()
        assert loaded._body.isHidden()
        assert loaded.is_open()

    def test_the_arrow_follows_each_button_independently(self, loaded):
        loaded._waveform_btn.setChecked(True)

        assert loaded._waveform_btn.text().startswith(SliceSection._ARROW_OPEN)
        assert loaded._slicer_btn.text().startswith(SliceSection._ARROW_CLOSED)

    def test_a_header_is_wide_enough_for_its_own_label(self, loaded):
        # A QPushButton centres rather than elides, so a short width cuts the
        # label at both ends with no ellipsis to admit it.
        for btn in (loaded._waveform_btn, loaded._slicer_btn):
            fitted = btn.fontMetrics().horizontalAdvance(btn.text())
            assert btn.width() >= fitted, btn.text()

    def test_both_headers_are_dead_until_a_track_is_loaded(self, section):
        assert not section._waveform_btn.isEnabled()
        assert not section._slicer_btn.isEnabled()

    def test_unloading_the_track_closes_and_disables_both(self, loaded):
        loaded._waveform_btn.setChecked(True)
        loaded._slicer_btn.setChecked(True)

        loaded.set_track(None, 0)

        assert not loaded.is_open()
        assert loaded._waveform.isHidden() and loaded._body.isHidden()
        assert not loaded._waveform_btn.isEnabled()
        assert not loaded._slicer_btn.isEnabled()


class TestWaveformRequests:
    """One build feeds both canvases, and neither view opens without asking."""

    def test_the_waveform_view_asks_for_a_waveform(self, loaded, qtbot):
        with qtbot.waitSignal(loaded.request_waveform, timeout=500):
            loaded._waveform_btn.setChecked(True)

    def test_the_slicer_asks_for_a_waveform(self, loaded, qtbot):
        with qtbot.waitSignal(loaded.request_waveform, timeout=500):
            loaded._slicer_btn.setChecked(True)

    def test_the_second_view_reuses_the_first_one_s_waveform(self, loaded):
        asked = []
        loaded.request_waveform.connect(lambda: asked.append(1))

        loaded._waveform_btn.setChecked(True)
        loaded.set_waveform([0.0], [0.0], [0.0], [0.0], 100.0)
        loaded._slicer_btn.setChecked(True)

        assert len(asked) == 1


class TestPanelReflow:
    """What the panel does with each view — the seek control and the playlist."""

    @pytest.fixture
    def player(self, qtbot, tmp_path):
        from src.gui.widgets.player_panel import PlayerPanel

        panel = PlayerPanel()
        qtbot.addWidget(panel)
        track = tmp_path / "track.wav"
        track.write_bytes(b"not-really-audio")
        panel._slice.set_track(str(track), DURATION_MS)
        return panel

    def test_the_waveform_takes_over_as_the_seek_control(self, player):
        player._slice._waveform_btn.setChecked(True)

        assert player._seek_row_widget.isHidden()

    def test_the_slicer_alone_keeps_the_plain_seek_bar(self, player):
        # There is no waveform to scrub on, so removing the slider would leave
        # the user nothing to seek with.
        player._slice._slicer_btn.setChecked(True)

        assert not player._seek_row_widget.isHidden()

    def test_closing_the_slicer_does_not_take_the_seek_bar_back(self, player):
        player._slice._waveform_btn.setChecked(True)
        player._slice._slicer_btn.setChecked(True)

        player._slice._slicer_btn.setChecked(False)

        assert player._seek_row_widget.isHidden(), "the waveform is still the seek control"

    def test_either_view_pins_the_playlist_height(self, player):
        stretchy = player._table.maximumHeight()

        player._slice._waveform_btn.setChecked(True)
        pinned = player._table.maximumHeight()
        player._slice._waveform_btn.setChecked(False)

        assert pinned < stretchy
        assert player._table.maximumHeight() == stretchy

    def test_closing_one_view_leaves_the_playlist_pinned(self, player):
        # Pinned, not pinned to the same pixel: closing the waveform brings the
        # seek row back and swaps which canvas is reserved, so the budget — and
        # with it the height — legitimately moves a little.
        player._slice._waveform_btn.setChecked(True)
        player._slice._slicer_btn.setChecked(True)

        player._slice._waveform_btn.setChecked(False)

        assert player._is_table_pinned()

    def test_only_the_slicer_widens_the_window_minimum(self, player):
        # slice_expanded drives WindowSizer.on_slicer_expanded, and it is the
        # tray's time row — not the waveform — that needs the extra width.
        seen = []
        player.slice_expanded.connect(seen.append)

        player._slice._waveform_btn.setChecked(True)
        assert seen == [False]

        player._slice._slicer_btn.setChecked(True)
        assert seen == [False, True]

    def test_the_slice_keys_belong_to_the_tray(self, player):
        player._slice._waveform_btn.setChecked(True)
        assert not player._slice.is_expanded(), "S/Q/E/L drive controls in the tray"

        player._slice._slicer_btn.setChecked(True)
        assert player._slice.is_expanded()


class TestTallRowsStayOnScreen:
    """Opening a view must not push itself below the fold.

    The playlist pin used to be a fixed *row count* (12), tuned when a row was
    the height of its text. Full artwork makes a row ~2.6x taller, so 12 of
    them exceeded the whole viewport and the transport, the waveform and the
    slice controls all opened out of sight — you had to scroll the panel to
    find the thing you had just opened.

    Asserted as a relation between two things Qt reports (does the canvas end
    above the fold), never as a pixel count: the suite runs with no stylesheet,
    so every height here differs from the running app's.
    """

    @pytest.fixture
    def player(self, qtbot, tmp_path):
        from src.gui.widgets.player_panel import PlayerPanel
        from src.library import Library

        lib = Library(tmp_path / "library.db")
        panel = PlayerPanel()
        qtbot.addWidget(panel)
        panel.set_library(lib)
        # A real geometry: the pin is a share of the viewport, so a panel that
        # was never given one has nothing to divide up.
        panel.resize(1024, 795)
        panel.show()
        qtbot.waitExposed(panel)

        entries = []
        for i in range(40):
            f = tmp_path / f"t{i:02d}.wav"
            f.write_bytes(b"not-really-audio")
            entries.append({"file_path": str(f), "display_name": f"Track {i:02d}"})
        panel.add_tracks(entries)
        # Full only changes the row height while the Art column is showing.
        panel._table.setColumnHidden(panel._ARTWORK_COLUMN, False)
        qtbot.wait(10)
        yield panel
        lib.close()

    @staticmethod
    def below_fold(player, widget):
        """Pixels of *widget*'s bottom edge that fall past the viewport.

        Activates the layout first: Qt computes child geometry lazily, so a
        position read straight after a toggle is the *previous* answer. Forcing
        it beats waiting a fixed number of milliseconds, which is only ever
        long enough until the suite is under load.
        """
        content = player._scroll.widget()
        content.layout().activate()
        bottom = widget.mapTo(content, widget.rect().bottomLeft()).y()
        return bottom - player._scroll.viewport().height()

    @staticmethod
    def visible_rows(player):
        """How many playlist rows the pin leaves room for.

        The header and frame are taken off first: they are a fixed cost that
        does not scale with the row, so a ratio that leaves them in makes tall
        rows look like fewer rows even when the count has not moved.
        """
        chrome = (
            player._table.horizontalHeader().height()
            + 2 * player._table.frameWidth()
            + 4
        )
        return (player._table.maximumHeight() - chrome) / player._row_height()

    @pytest.mark.parametrize("view", ["top", "middle", "full"])
    def test_the_waveform_opens_on_screen_in_every_artwork_view(
        self, player, qtbot, view
    ):
        player.set_artwork_view(view)
        player._slice._waveform_btn.setChecked(True)
        qtbot.wait(20)

        assert self.below_fold(player, player._slice._waveform) <= 0

    @pytest.mark.parametrize("view", ["top", "middle", "full"])
    def test_the_transport_opens_on_screen_in_every_artwork_view(
        self, player, qtbot, view
    ):
        player.set_artwork_view(view)
        player._slice._waveform_btn.setChecked(True)
        qtbot.wait(20)

        assert self.below_fold(player, player._clear_btn) <= 0

    def test_the_zoomed_canvas_opens_on_screen_with_tall_rows(self, player, qtbot):
        player.set_artwork_view("full")
        player._slice._slicer_btn.setChecked(True)
        qtbot.wait(20)

        assert self.below_fold(player, player._slice._zoom_waveform) <= 0

    def test_tall_rows_cost_rows_not_the_panel(self, player, qtbot):
        """The playlist gives up rows to make room — it does not overflow."""
        player.set_artwork_view("top")
        player._slice._waveform_btn.setChecked(True)
        qtbot.wait(20)
        text_rows = self.visible_rows(player)

        player.set_artwork_view("full")
        qtbot.wait(20)
        art_rows = self.visible_rows(player)

        assert art_rows < text_rows, "tall rows must yield, not push the panel down"
        assert art_rows >= player._MIN_ROWS_WHEN_SLICING, "the playlist must survive"

    def test_a_text_height_row_still_gets_the_full_row_count(self, player, qtbot):
        # The budget is a cap, so the shipped behaviour at a normal row height
        # is unchanged: still the 12 rows the old fixed pin gave.
        player.set_artwork_view("top")
        player._slice._waveform_btn.setChecked(True)
        qtbot.wait(20)

        assert round(self.visible_rows(player)) == player._ROWS_VISIBLE_WHEN_SLICING

    def test_shrinking_the_window_re_fits_the_playlist(self, player, qtbot):
        # The budget is a share of the viewport, so a resize changes the answer
        # and the pin has to be recomputed — the old fixed row count never was.
        player.set_artwork_view("full")
        player._slice._waveform_btn.setChecked(True)
        qtbot.wait(20)
        tall = player._table.maximumHeight()
        viewport = player._scroll.viewport().height()

        player.resize(1024, 560)
        # Wait for the resize to reach the viewport — the pin is recomputed from
        # it, so asserting before it lands reads the old budget and the test
        # passes or fails on how busy the machine is.
        qtbot.waitUntil(
            lambda: player._scroll.viewport().height() < viewport, timeout=2000
        )

        assert player._table.maximumHeight() < tall

    def test_the_playlist_never_shrinks_below_the_floor(self, player, qtbot):
        """A window too short for both keeps a usable playlist and scrolls.

        Deliberately *not* asserting the waveform stays on screen here: past
        this point there is no height that satisfies both, and the design
        chooses to keep some playlist and let the panel scroll. Asserting
        otherwise demands something no implementation can deliver.
        """
        player.set_artwork_view("full")
        player._slice._waveform_btn.setChecked(True)
        qtbot.wait(20)

        player.resize(1024, 320)
        qtbot.wait(20)

        assert self.visible_rows(player) >= player._MIN_ROWS_WHEN_SLICING
