"""The Player's three slice views are independent toggles.

"Waveform" opens the full-track waveform (which is then the seek control);
"Zoomed Wave" opens the ±0.5 s scrubber; "Loop Slicer" opens the slice controls.
Any one alone, any pair, or all three — and only all three together is the view
the single combined header used to give.

The zoomed canvas and the controls share one tray, so a test that asks whether
the Loop Slicer is open must look at ``_controls``, not at ``_body``: the tray
is showing for either of its halves.

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
    def test_every_view_starts_closed(self, loaded):
        assert loaded._waveform.isHidden()
        assert loaded._zoom_waveform.isHidden()
        assert loaded._controls.isHidden()
        assert loaded._body.isHidden(), "an empty tray is not a view"
        assert not loaded.is_waveform_shown()
        assert not loaded.is_zoom_shown()
        assert not loaded.is_expanded()
        assert not loaded.is_open()

    def test_all_three_headers_share_one_row(self, loaded):
        # The user's ask: one row, in reading order. Same y, strictly ascending
        # x. Activated first — Qt lays out lazily, and unlaid-out buttons all
        # sit at (0, 0), where "same y, ascending x" is true of any arrangement.
        loaded.layout().activate()
        boxes = [btn.geometry() for btn in loaded._header_buttons()]
        xs = [b.x() for b in boxes]

        assert len({b.y() for b in boxes}) == 1, "one row"
        assert xs == sorted(xs) and len(set(xs)) == 3, "left to right"

    def test_waveform_opens_only_the_full_waveform(self, loaded):
        loaded._waveform_btn.setChecked(True)

        assert not loaded._waveform.isHidden()
        assert loaded._body.isHidden(), "the slice tray is the other buttons' job"
        assert loaded.is_waveform_shown()
        assert not loaded.is_zoom_shown()
        assert not loaded.is_expanded()

    def test_zoomed_wave_opens_only_the_zoomed_canvas(self, loaded):
        loaded._zoom_btn.setChecked(True)

        assert not loaded._zoom_waveform.isHidden()
        assert not loaded._body.isHidden(), "the tray carries the zoomed canvas"
        assert loaded._controls.isHidden(), "the slice controls are not its job"
        assert loaded._waveform.isHidden()
        assert loaded.is_zoom_shown()
        assert not loaded.is_expanded()

    def test_loop_slicer_opens_only_the_controls(self, loaded):
        loaded._slicer_btn.setChecked(True)

        assert not loaded._controls.isHidden()
        assert not loaded._body.isHidden(), "the tray carries the controls"
        assert loaded._zoom_waveform.isHidden(), "the zoomed wave has its own button"
        assert loaded._waveform.isHidden()
        assert loaded.is_expanded()
        assert not loaded.is_zoom_shown()
        assert not loaded.is_waveform_shown()

    def test_all_three_together_give_the_whole_slicer(self, loaded):
        for btn in loaded._header_buttons():
            btn.setChecked(True)

        assert not loaded._waveform.isHidden()
        assert not loaded._zoom_waveform.isHidden()
        assert not loaded._controls.isHidden()

    def test_closing_one_leaves_the_others_open(self, loaded):
        for btn in loaded._header_buttons():
            btn.setChecked(True)

        loaded._slicer_btn.setChecked(False)

        assert not loaded._waveform.isHidden()
        assert not loaded._zoom_waveform.isHidden()
        assert loaded._controls.isHidden()
        assert loaded.is_open()

    def test_the_tray_outlives_the_first_of_its_two_halves(self, loaded):
        loaded._zoom_btn.setChecked(True)
        loaded._slicer_btn.setChecked(True)

        loaded._zoom_btn.setChecked(False)

        assert not loaded._body.isHidden(), "the controls still need the tray"
        assert loaded._zoom_waveform.isHidden()

    def test_the_tray_closes_with_the_last_of_them(self, loaded):
        loaded._zoom_btn.setChecked(True)
        loaded._slicer_btn.setChecked(True)

        loaded._zoom_btn.setChecked(False)
        loaded._slicer_btn.setChecked(False)

        assert loaded._body.isHidden()

    def test_the_arrow_follows_each_button_independently(self, loaded):
        loaded._zoom_btn.setChecked(True)

        assert loaded._zoom_btn.text().startswith(SliceSection._ARROW_OPEN)
        assert loaded._waveform_btn.text().startswith(SliceSection._ARROW_CLOSED)
        assert loaded._slicer_btn.text().startswith(SliceSection._ARROW_CLOSED)

    def test_a_header_is_wide_enough_for_its_own_label(self, loaded):
        # A QPushButton centres rather than elides, so a short width cuts the
        # label at both ends with no ellipsis to admit it.
        for btn in loaded._header_buttons():
            fitted = btn.fontMetrics().horizontalAdvance(btn.text())
            assert btn.width() >= fitted, btn.text()

    def test_every_header_is_dead_until_a_track_is_loaded(self, section):
        for btn in section._header_buttons():
            assert not btn.isEnabled()

    def test_unloading_the_track_closes_and_disables_them_all(self, loaded):
        for btn in loaded._header_buttons():
            btn.setChecked(True)

        loaded.set_track(None, 0)

        assert not loaded.is_open()
        assert loaded._waveform.isHidden() and loaded._body.isHidden()
        for btn in loaded._header_buttons():
            assert not btn.isEnabled()


class TestWaveformRequests:
    """One build feeds both canvases, and no canvas opens without asking."""

    def test_the_waveform_view_asks_for_a_waveform(self, loaded, qtbot):
        with qtbot.waitSignal(loaded.request_waveform, timeout=500):
            loaded._waveform_btn.setChecked(True)

    def test_the_zoomed_wave_asks_for_a_waveform(self, loaded, qtbot):
        with qtbot.waitSignal(loaded.request_waveform, timeout=500):
            loaded._zoom_btn.setChecked(True)

    def test_the_controls_alone_do_not_pay_for_a_decode(self, loaded):
        # They set markers by Mark/nudge/typing and draw no samples, so a
        # request here would be a decode for a view nobody can see.
        asked = []
        loaded.request_waveform.connect(lambda: asked.append(1))

        loaded._slicer_btn.setChecked(True)

        assert asked == []
        assert not loaded.needs_waveform()

    def test_the_second_view_reuses_the_first_one_s_waveform(self, loaded):
        asked = []
        loaded.request_waveform.connect(lambda: asked.append(1))

        loaded._waveform_btn.setChecked(True)
        loaded.set_waveform([0.0], [0.0], [0.0], [0.0], 100.0)
        loaded._zoom_btn.setChecked(True)

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

    def test_the_zoomed_wave_alone_keeps_the_plain_seek_bar(self, player):
        # It scrubs ±0.5 s around the playhead, so it is no substitute for a
        # whole-track seek control.
        player._slice._zoom_btn.setChecked(True)

        assert not player._seek_row_widget.isHidden()

    def test_closing_the_slicer_does_not_take_the_seek_bar_back(self, player):
        player._slice._waveform_btn.setChecked(True)
        player._slice._slicer_btn.setChecked(True)

        player._slice._slicer_btn.setChecked(False)

        assert player._seek_row_widget.isHidden(), "the waveform is still the seek control"

    def test_the_waveform_alone_leaves_the_playlist_stretchy(self, player):
        # The canvas lives in the pinned footer, which takes its room out of
        # the viewport before the playlist is measured — nothing in the scroll
        # content grows, so there is nothing to pin against and the playlist
        # fills whatever the footer leaves. That IS the feature: more visible
        # playlist, not a 12-row cap.
        stretchy = player._table.maximumHeight()

        player._slice._waveform_btn.setChecked(True)

        assert player._table.maximumHeight() == stretchy

    def test_a_scroll_content_view_pins_the_playlist_height(self, player):
        stretchy = player._table.maximumHeight()

        player._slice._slicer_btn.setChecked(True)
        pinned = player._table.maximumHeight()
        player._slice._slicer_btn.setChecked(False)

        assert pinned < stretchy
        assert player._table.maximumHeight() == stretchy

    def test_closing_one_view_leaves_the_playlist_pinned(self, player):
        # The waveform never held the pin (it lives in the footer), so closing
        # it must not release the pin the still-open slice controls hold.
        player._slice._waveform_btn.setChecked(True)
        player._slice._slicer_btn.setChecked(True)

        player._slice._waveform_btn.setChecked(False)

        assert player._is_table_pinned()

    def test_only_the_slicer_widens_the_window_minimum(self, player):
        # slice_expanded drives WindowSizer.on_slicer_expanded, and it is the
        # controls' time row — not either canvas — that needs the extra width.
        seen = []
        player.slice_expanded.connect(seen.append)

        player._slice._waveform_btn.setChecked(True)
        player._slice._zoom_btn.setChecked(True)
        assert seen == [False, False]

        player._slice._slicer_btn.setChecked(True)
        assert seen == [False, False, True]

    def test_the_slice_keys_belong_to_the_controls(self, player):
        player._slice._waveform_btn.setChecked(True)
        player._slice._zoom_btn.setChecked(True)
        assert not player._slice.is_expanded(), "S/Q/E/L drive the slice controls"

        player._slice._slicer_btn.setChecked(True)
        assert player._slice.is_expanded()

    def test_the_window_minimum_holds_the_whole_header_row(self, player):
        """Three translated labels are what a 600px constant stopped fitting.

        The row is on screen whether or not anything is expanded, so this is
        floored unconditionally — the wiring, without a whole MainWindow.
        """
        from types import SimpleNamespace

        from PySide6.QtCore import QSize

        from src.gui.window_sizer import WindowSizer

        window = SimpleNamespace(
            _sidebar=SimpleNamespace(width=lambda: 220),
            _player_panel=player,
            _header=SimpleNamespace(minimumSizeHint=lambda: QSize(0, 0)),
        )
        sizer = WindowSizer(window)

        assert (
            sizer._min_width_for("player")
            >= 220 + player.slice_header_row_min_width()
        )

    def test_the_header_row_minimum_counts_every_toggle(self, player):
        # A width taken from two of the three is the bug this measurement
        # exists to prevent, and it is invisible in English.
        section = player._slice
        widths = [b.width() for b in section._header_buttons()]

        assert section.header_row_min_width() >= sum(widths)

    def test_the_zoomed_wave_alone_still_pins_the_playlist(self, player):
        # The point of the split: with the controls closed, the zoomed view and
        # the metronome below it must still get room reserved for them.
        stretchy = player._table.maximumHeight()

        player._slice._zoom_btn.setChecked(True)

        assert player._table.maximumHeight() < stretchy


class TestTallRowsStayOnScreen:
    """Opening a view must not push itself below the fold.

    The playlist pin used to be a fixed *row count* (12), tuned when a row was
    the height of its text. Full artwork makes a row ~2.6x taller, so 12 of
    them exceeded the whole viewport and everything below opened out of sight.
    The transport and the full waveform are out of the game entirely now —
    they live in a pinned footer below the scroll area — so the pin only has
    to land the scroll-content views (zoomed wave, slice controls, metronome)
    on screen, and the 12-row cap itself is gone: surplus height the playlist
    refused was redistributed by the layout into the growable chrome rows,
    which inflated the title and now-playing lines into ~140px black bands.

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

    def test_the_waveform_and_transport_live_in_the_pinned_footer(self, player):
        # They cannot open below the fold or scroll off: they are not scroll
        # content at all. Asserted structurally — the suite wears no
        # stylesheet, so a pixel claim would measure a different app.
        wf = player._slice.waveform_widget()
        for w in (wf, player._seek_row_widget, player._clear_btn,
                  player._play_btn, player._now_playing_row):
            assert player._footer.isAncestorOf(w), w
            assert not player._scroll.isAncestorOf(w), w
        assert not player._scroll.isAncestorOf(player._footer)

    def test_scrolling_to_the_bottom_cannot_move_the_transport(self, player, qtbot):
        # The user's report: scrolled down to the slicer, the transport was
        # gone. The footer sits outside the scroll area, justified to the
        # panel's bottom edge, so the outer scrollbar cannot touch it.
        player.set_artwork_view("full")
        player._slice._slicer_btn.setChecked(True)
        player._metronome_section.set_expanded(True)
        qtbot.wait(20)
        before = player._footer.geometry()
        assert before.bottom() == player.rect().bottom()

        bar = player._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        qtbot.wait(20)

        assert player._footer.geometry() == before

    def test_the_zoomed_canvas_opens_on_screen_with_tall_rows(self, player, qtbot):
        player.set_artwork_view("full")
        player._slice._zoom_btn.setChecked(True)
        qtbot.wait(20)

        assert self.below_fold(player, player._slice._zoom_waveform) <= 0

    def test_the_controls_open_on_screen_with_tall_rows(self, player, qtbot):
        # Its own reservation: with no canvas open, the time row is the first
        # thing the tray shows and it must not land under the fold.
        player.set_artwork_view("full")
        player._slice._slicer_btn.setChecked(True)
        qtbot.wait(20)

        assert self.below_fold(player, player._slice._time_row_widget) <= 0

    def test_tall_rows_cost_rows_not_the_panel(self, player, qtbot):
        """The playlist gives up rows to make room — it does not overflow."""
        player.set_artwork_view("top")
        player._slice._zoom_btn.setChecked(True)
        qtbot.wait(20)
        text_rows = self.visible_rows(player)

        player.set_artwork_view("full")
        qtbot.wait(20)
        art_rows = self.visible_rows(player)

        assert art_rows < text_rows, "tall rows must yield, not push the panel down"
        assert art_rows >= player._MIN_ROWS_WHEN_SLICING, "the playlist must survive"

    def test_the_playlist_absorbs_the_whole_budget(self, player, qtbot):
        """No surplus is left for the layout to redistribute.

        The old 12-row cap left hundreds of pixels that QVBoxLayout handed to
        every growable chrome row — the title and now-playing lines measured
        143px against size hints of 29/16 on a tall window, which the user
        reported as giant black bands. The playlist takes the whole budget
        now, so those rows sit at their own heights however tall the window.
        """
        player.resize(1024, 1500)
        player.set_artwork_view("top")
        player._slice._zoom_btn.setChecked(True)
        qtbot.wait(20)
        content = player._scroll.widget()
        content.layout().activate()
        qtbot.wait(20)

        for row in (player._title_row_widget, player._metronome_section):
            assert row.height() <= row.sizeHint().height() + 1, (
                f"{row.objectName() or row} inflated past its own height"
            )
        budget = (
            player._scroll.viewport().height()
            - player._height_outside_playlist()
        )
        assert player._table.maximumHeight() == budget

    def test_shrinking_the_window_re_fits_the_playlist(self, player, qtbot):
        # The budget is a share of the viewport, so a resize changes the answer
        # and the pin has to be recomputed — the old fixed row count never was.
        player.set_artwork_view("full")
        player._slice._zoom_btn.setChecked(True)
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
        player._slice._zoom_btn.setChecked(True)
        qtbot.wait(20)

        player.resize(1024, 320)
        qtbot.wait(20)

        assert self.visible_rows(player) >= player._MIN_ROWS_WHEN_SLICING
