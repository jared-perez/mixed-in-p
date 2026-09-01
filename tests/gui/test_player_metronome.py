"""The metronome's new home: a collapsible section in the Player panel.

It was the Keyboard panel's third view until 2026-08-26. The metronome
*itself* is unchanged and is tested in test_metronome_view.py; what is here is
the move — the disclosure, the room the panel makes for it, and the two audio
lifecycles the host owes it (leave on navigation, stop on close).

Visibility is asserted with ``isHidden()``, not ``isVisible()``: nothing is
shown in an offscreen suite, so ``isVisible()`` is False for every widget here
and an assertion on it would pass against any build.
"""

from __future__ import annotations

import pathlib

import pytest

from src.gui.widgets import player_panel as player_panel_mod
from src.gui.widgets import section_header
from src.gui.widgets.keyboard_panel import KeyboardPanel
from src.gui.styles.theme import Theme
from src.gui.widgets.metronome_section import MetronomeSection
from src.gui.widgets.player_panel import PlayerPanel


class FakeStream:
    def __init__(self):
        self.stopped = False
        self.closed = False

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


@pytest.fixture
def section(qtbot):
    """A section whose 'device' is a recorder — nothing here opens one."""
    streams = []

    def factory():
        streams.append(FakeStream())
        return streams[-1]

    sec = MetronomeSection(stream_factory=factory)
    qtbot.addWidget(sec)
    sec._streams = streams
    return sec


@pytest.fixture
def player(qtbot):
    panel = PlayerPanel()
    qtbot.addWidget(panel)
    panel._metronome_section.view._stream_factory = lambda: None
    yield panel
    panel.shutdown_metronome()


class TestTheDisclosure:
    def test_it_starts_closed(self, section):
        assert not section.is_expanded()
        assert section._body.isHidden()

    def test_expanding_shows_the_metronome(self, section):
        section.set_expanded(True)

        assert section.is_expanded()
        assert not section._body.isHidden()

    def test_the_arrow_follows_the_state(self, section):
        assert section._header_btn.text().startswith(section_header.ARROW_CLOSED)
        section.set_expanded(True)
        assert section._header_btn.text().startswith(section_header.ARROW_OPEN)

    def test_the_tooltip_says_what_the_next_click_does(self, section):
        closed = section._header_btn.toolTip()
        section.set_expanded(True)

        assert section._header_btn.toolTip() != closed
        assert "Hide" in section._header_btn.toolTip()

    def test_it_wears_the_same_header_as_the_slice_views(self, section):
        """One family of disclosure toggles, one implementation — the look is
        fiddly enough (a QPushButton centres rather than elides) to be worth
        not writing twice."""
        from src.gui.widgets.slice_section import SliceSection

        assert SliceSection._ARROW_OPEN == section_header.ARROW_OPEN
        assert SliceSection._header_button is section_header.header_button

    def test_no_control_in_it_can_take_focus(self, section):
        """Space stays play/pause and the panel's S/Q/E routing is not
        swallowed — the rule the slice section already follows."""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QAbstractButton

        for btn in section.findChildren(QAbstractButton):
            assert btn.focusPolicy() == Qt.FocusPolicy.NoFocus

    def test_the_tempo_box_still_takes_focus(self, section):
        """It is a QLineEdit and typing a tempo into it is the point — the
        no-focus sweep must not have caught it."""
        from PySide6.QtCore import Qt

        assert section.view._bpm_box.focusPolicy() != Qt.FocusPolicy.NoFocus


class TestStartSitsOnTheHeaderRow:
    """The one control the section lays out that it does not own. The view
    builds and drives it; being up here is what makes it the biggest target
    in the metronome."""

    def test_the_section_adopted_it(self, section):
        button = section.view.start_button()

        assert button.parent() is section
        assert section._start_btn is button

    def test_it_shares_the_header_row_with_the_word(self, section):
        row = section.layout().itemAt(0).layout()
        widgets = [
            row.itemAt(i).widget() for i in range(row.count())
        ]

        assert section._header_btn in widgets
        assert section._start_btn in widgets

    def test_it_is_the_taller_of_the_two(self, section):
        """Drawn that way on purpose — it is not a second word of the label."""
        assert section._start_size().height() > section._header_btn.height()

    def test_the_tempo_controls_share_that_row_too(self, section):
        """The condensing: BPM/Tap/Global Click ride beside Start instead of
        owning a row of their own, which is half of two-rows-not-four."""
        row = section.layout().itemAt(0).layout()
        widgets = [row.itemAt(i).widget() for i in range(row.count())]

        assert section.view.tempo_row() in widgets
        assert section.view.tempo_row().parent() is section
        # Right of Start, not left of it.
        assert widgets.index(section.view.tempo_row()) > widgets.index(
            section._start_btn
        )

    def test_a_collapsed_section_shows_only_its_word(self, section, qtbot):
        """The same shape as the two sections beside it. It also closes the
        second door into a running click: Start reachable over a hidden body
        would open the stream against a view the Global Click rule has
        already had its say about."""
        section.show()
        qtbot.waitExposed(section)

        assert section._start_btn.isHidden()
        assert section.view.tempo_row().isHidden()

        section.set_expanded(True)
        assert not section._start_btn.isHidden()
        assert not section.view.tempo_row().isHidden()

        section.set_expanded(False)
        assert section._start_btn.isHidden()
        assert section.view.tempo_row().isHidden()

    def test_the_window_minimum_covers_the_header_row(self, section):
        """row_min_width measures both rows now — the header one can be the
        wider of the two once a translated Start joins it."""
        header_row = (
            section._header_btn.width()
            + Theme.SPACING
            + 12
            + section._start_size().width()
            + 12
            + section.view.tempo_row().sizeHint().width()
        )

        assert section.row_min_width() >= header_row


class TestCollapsingSilencesIt:
    """Through MetronomeView.hideEvent, not through anything in the section:
    hiding the body IS the stop signal, so Global Click is honoured by one
    code path rather than two that have to be kept in step."""

    def test_collapsing_stops_a_running_click(self, section, qtbot):
        section.view._global_btn.setChecked(False)
        section.set_expanded(True)
        section.show()
        qtbot.waitExposed(section)
        section.view._start_btn.setChecked(True)

        section.set_expanded(False)

        assert not section.view.running
        assert section._streams[0].stopped

    def test_global_click_keeps_it_through_a_collapse(self, section, qtbot):
        section.set_expanded(True)
        section.show()
        qtbot.waitExposed(section)
        section.view._start_btn.setChecked(True)

        section.set_expanded(False)

        assert section.view.running
        assert not section._streams[0].stopped
        section.stop()


class TestThePanelMakesRoomForIt:
    def test_it_is_closed_when_the_panel_opens(self, player):
        assert not player._metronome_section.is_expanded()

    def test_opening_it_pins_the_playlist(self, player):
        """The pin is about the panel growing past the viewport so the outer
        scrollbar reveals what is below — which the metronome needs exactly as
        much as the slicer does. Keyed off the slice section alone, an opened
        metronome was squeezed by a stretchy playlist."""
        assert not player._is_table_pinned()

        player._metronome_section.set_expanded(True)

        assert player._is_table_pinned()

    def test_closing_it_releases_the_pin(self, player):
        player._metronome_section.set_expanded(True)
        player._metronome_section.set_expanded(False)

        assert not player._is_table_pinned()

    def test_it_does_not_release_a_pin_the_slicer_still_wants(self, player):
        # The zoomed wave, not the waveform: the full waveform lives in the
        # pinned footer now and never holds the pin itself.
        player._slice._zoom_btn.setChecked(True)
        player._metronome_section.set_expanded(True)

        player._metronome_section.set_expanded(False)

        assert player._is_table_pinned(), "the zoomed wave is still open"

    def test_an_open_section_is_reserved_out_of_the_playlists_budget(self, player):
        before = player._height_outside_playlist()

        player._metronome_section.set_expanded(True)

        assert player._height_outside_playlist() > before

    def test_it_announces_the_change(self, player, qtbot):
        with qtbot.waitSignal(player.metronome_expanded) as sig:
            player._metronome_section.set_expanded(True)
        assert sig.args == [True]

    def test_the_window_minimum_is_measured_not_written_down(self, player):
        """Every label in the metronome is translated, and a constant is an
        English width — the lesson the Convert format row already carries."""
        assert player.metronome_row_min_width() >= (
            player._metronome_section.view.sizeHint().width()
        )


class TestTheFooterMovingDoesNotStrandDeadSpace:
    """The playlist's pin is a share of the scroll viewport, and the footer
    can change that viewport without the panel being resized at all.

    Opening Waveform swaps the seek slider for the waveform down in the
    pinned footer. The height the panel reads one line later is the pre-swap
    one, so the budget came out short by the slider's row and the difference
    showed as a band of dead space under the metronome — which opening and
    closing Zoomed Wave then repaired, because that recompute ran against a
    settled viewport.
    """

    def settle(self, player, qtbot):
        player.show()
        qtbot.waitExposed(player)
        qtbot.wait(20)

    def test_the_pin_matches_the_settled_viewport(self, player, qtbot):
        player.resize(1075, 900)
        self.settle(player, qtbot)
        player._metronome_section.set_expanded(True)
        qtbot.wait(20)

        player._slice._waveform_btn.setChecked(True)
        qtbot.wait(20)

        # The budget asked for now, against a viewport that has stopped
        # moving — the pin must already be it.
        assert player._table.maximumHeight() == player._pinned_table_height()

    def test_opening_the_zoom_and_closing_it_changes_nothing(
        self, player, qtbot
    ):
        """The round trip was the user's workaround: it recomputed against a
        settled viewport. It must now be a no-op instead of a repair."""
        player.resize(1075, 900)
        self.settle(player, qtbot)
        player._metronome_section.set_expanded(True)
        player._slice._waveform_btn.setChecked(True)
        qtbot.wait(20)
        before = player._table.maximumHeight()

        player._slice._zoom_btn.setChecked(True)
        qtbot.wait(20)
        player._slice._zoom_btn.setChecked(False)
        qtbot.wait(20)

        assert player._table.maximumHeight() == before


BPM_COLUMN = 4


def stock(player, tmp_path, bpms=("128", "")):
    """Two tracks, with whatever BPM tags the test wants."""
    tracks = []
    for i, bpm in enumerate(bpms):
        f = tmp_path / f"{i}.wav"
        f.write_bytes(b"not-really-audio")
        tracks.append(
            {"file_path": str(f), "display_name": f.name, "artist": "A",
             "title": f.name, "bpm": bpm}
        )
    player.add_tracks(tracks, allow_duplicates=True)
    return [t["file_path"] for t in tracks]


class TestTheTrackButtonReadsTheLoadedTrack:
    """One record of the tempo and it lives here — the button asks
    loaded_track_bpm() rather than being handed a copy to keep in step."""

    def test_it_answers_for_the_loaded_track_not_the_selected_row(
        self, player, tmp_path
    ):
        paths = stock(player, tmp_path, ("128", "90"))
        player._playing_path = paths[1]
        player._table.selectRow(0)

        assert player.loaded_track_bpm() == pytest.approx(90.0)

    def test_nothing_loaded_is_no_tempo(self, player, tmp_path):
        stock(player, tmp_path)

        assert player.loaded_track_bpm() is None

    def test_a_blank_tag_is_no_tempo(self, player, tmp_path):
        paths = stock(player, tmp_path, ("128", ""))
        player._playing_path = paths[1]

        assert player.loaded_track_bpm() is None

    def test_a_track_playing_out_of_the_visible_list_is_no_tempo(
        self, player, tmp_path
    ):
        """_current_index is -1 whenever the visible list is a different
        playlist from the one playing, which is why this is derived from the
        path — an index lookup would answer for whichever row happened to be
        there."""
        stock(player, tmp_path)
        player._playing_path = str(tmp_path / "elsewhere.wav")

        assert player.loaded_track_bpm() is None

    def test_it_is_derived_on_every_call(self, player, tmp_path):
        paths = stock(player, tmp_path, ("128", "90"))
        player._playing_path = paths[0]
        assert player.loaded_track_bpm() == pytest.approx(128.0)

        player._playlist[0].bpm = "174"

        assert player.loaded_track_bpm() == pytest.approx(174.0)

    def test_the_button_follows_the_loaded_track(self, player, tmp_path):
        """now_playing_changed is the panel's own "the loaded track moved" —
        played, removed from under the player, or cleared."""
        button = player._metronome_section.view._track_btn
        paths = stock(player, tmp_path, ("128", ""))
        assert not button.isEnabled()

        player._playing_path = paths[0]
        player.now_playing_changed.emit()

        assert button.isEnabled()
        button.click()
        assert player._metronome_section.view._bpm_box.value() == pytest.approx(128.0)

    def test_a_bpm_typed_into_the_loaded_row_reaches_it(
        self, player, tmp_path, monkeypatch
    ):
        """The edit rewrites the entry with no reload, so the enabled state
        has to be told the answer may have moved — the value itself is read
        fresh either way."""
        monkeypatch.setattr(
            player_panel_mod, "write_metadata", lambda *a, **k: None
        )
        paths = stock(player, tmp_path, ("", ""))
        player._playing_path = paths[0]
        player.now_playing_changed.emit()
        button = player._metronome_section.view._track_btn
        assert not button.isEnabled()

        player._table.item(0, BPM_COLUMN).setText("140")

        assert button.isEnabled()
        button.click()
        assert player._metronome_section.view._bpm_box.value() == pytest.approx(140.0)


class TestTheHostOwnsTheAudioLifecycle:
    def test_leaving_the_player_honours_global_click(self, player, qtbot):
        streams = []
        player._metronome_section.view._stream_factory = (
            lambda: streams.append(FakeStream()) or streams[-1]
        )
        player._metronome_section.set_expanded(True)
        player._metronome_section.view._start_btn.setChecked(True)

        player.leave_metronome()

        assert player._metronome_section.view.running
        assert not streams[0].stopped

    def test_leaving_stops_it_with_global_click_off(self, player, qtbot):
        streams = []
        view = player._metronome_section.view
        view._stream_factory = lambda: streams.append(FakeStream()) or streams[-1]
        view._global_btn.setChecked(False)
        player._metronome_section.set_expanded(True)
        view._start_btn.setChecked(True)

        player.leave_metronome()

        assert not view.running
        assert streams[0].stopped

    def test_closing_overrides_global_click(self, player):
        streams = []
        view = player._metronome_section.view
        view._stream_factory = lambda: streams.append(FakeStream()) or streams[-1]
        player._metronome_section.set_expanded(True)
        view._start_btn.setChecked(True)

        player.shutdown_metronome()

        assert not view.running
        assert streams[0].stopped

    def test_the_window_asks_on_navigation_and_on_close(self):
        """Two different calls on purpose — a navigation that used the close
        path would ignore Global Click, and a close that used the navigation
        path would hold an open stream through teardown."""
        source = pathlib.Path("src/gui/main_window.py").read_text()
        nav = source[source.index("def _on_page_changed") : source.index("def _persist_config")]
        close = source[source.index("def closeEvent") :]
        assert "leave_metronome()" in nav
        assert "shutdown_metronome()" in close
        assert "shutdown_metronome()" not in nav
        assert "leave_metronome()" not in close


class TestTheKeyboardPanelNoLongerHostsIt:
    def test_the_switcher_is_back_to_two_views(self, qtbot):
        panel = KeyboardPanel()
        qtbot.addWidget(panel)
        try:
            assert panel._view_combo.count() == 2
            assert [
                panel._view_combo.itemText(i) for i in range(2)
            ] == ["Hex Grid", "Circle of Fifths"]
        finally:
            panel.stop_audio()

    def test_the_panel_holds_no_metronome_at_all(self, qtbot):
        """Asserted on the attribute, which is the line anyone would write to
        put it back — not on a behaviour, which would keep passing while a
        second, hidden metronome sat there holding a stream."""
        panel = KeyboardPanel()
        qtbot.addWidget(panel)
        try:
            assert not hasattr(panel, "_metronome")
        finally:
            panel.stop_audio()
