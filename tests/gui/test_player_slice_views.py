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
        player._slice._waveform_btn.setChecked(True)
        player._slice._slicer_btn.setChecked(True)
        pinned = player._table.maximumHeight()

        player._slice._waveform_btn.setChecked(False)

        assert player._table.maximumHeight() == pinned

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
