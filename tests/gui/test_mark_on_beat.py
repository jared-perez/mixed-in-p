"""Mark on beat: the slicer's Mark buttons land on the metronome's next click.

The marker is placed at the press, at the track position that will be heard
when the click is — so these drive `_mark_position` with a stand-in engine and
beat source rather than waiting on real audio.
"""

from __future__ import annotations

import pytest

from src.gui.widgets.player_engine import PlayerEngine
from src.gui.widgets.player_panel import PlayerPanel
from src.gui.widgets.slice_section import SliceSection

DURATION_MS = 240_000


class FakeEngine(PlayerEngine):
    """A PlayerEngine whose clocks answer whatever the test sets."""

    def __init__(self):
        super().__init__()
        self.rendered_ms = 10_000
        self.heard_ms = 9_950.0
        self.bounds = (0, 0)
        self.lead_ms = 40.0
        self.looping = False
        self.jumps = []
        self.seeks = []

    def current_ms(self):
        return self.rendered_ms

    def heard_ms_at(self, when):
        return self.heard_ms

    def render_lead_ms(self, when):
        return self.lead_ms

    @property
    def loop_enabled(self):
        return self.looping

    def loop_bounds_ms(self):
        return self.bounds

    def set_loop_bounds(self, start_ms, end_ms):
        self.bounds = (start_ms, end_ms)

    def set_loop_enabled(self, enabled):
        self.looping = enabled

    def schedule_jump_ms(self, at_ms, to_ms, enable_loop=False):
        self.jumps.append((at_ms, to_ms, enable_loop))

    def cancel_jump(self, loop_start_only=False):
        self.jumps.append("cancel-loop" if loop_start_only else "cancel")

    def seek_ms(self, ms):
        self.seeks.append(ms)


@pytest.fixture
def section(qtbot, tmp_path):
    engine = FakeEngine()
    sec = SliceSection(engine)
    qtbot.addWidget(sec)
    track = tmp_path / "track.wav"
    track.write_bytes(b"not-really-audio")
    sec.set_track(str(track), DURATION_MS)
    sec.fake = engine
    return sec


class TestMarkPosition:
    def test_off_marks_at_the_playhead(self, section):
        section.set_beat_source(lambda when, not_before=0.0: 300.0)
        section.on_mark_start()
        assert section._range_slider.startValue() == 10_000

    def test_on_marks_where_the_next_click_is_heard(self, section):
        section.set_beat_source(lambda when, not_before=0.0: 300.0)
        section._mark_on_beat_switch.setChecked(True)

        section.on_mark_start()
        section.fake.heard_ms = 11_000.0
        section.on_mark_end()

        # Heard position plus the wait — not the rendered playhead.
        assert section._range_slider.startValue() == 10_250
        assert section._range_slider.endValue() == 11_300

    def test_no_running_click_marks_at_the_playhead(self, section):
        section.set_beat_source(lambda when, not_before=0.0: None)
        section._mark_on_beat_switch.setChecked(True)
        section.on_mark_start()
        assert section._range_slider.startValue() == 10_000

    def test_paused_playback_marks_at_the_playhead(self, section):
        section.set_beat_source(lambda when, not_before=0.0: 300.0)
        section.fake.heard_ms = None
        section._mark_on_beat_switch.setChecked(True)
        section.on_mark_start()
        assert section._range_slider.startValue() == 10_000

    def test_a_click_past_the_loop_end_lands_back_inside_it(self, section):
        section._range_slider.setStartValue(8_000)
        section._range_slider.setEndValue(10_000)
        section._loop_checkbox.setChecked(True)  # Mark on beat off: loops now
        assert section.fake.looping
        section.fake.heard_ms = 9_900.0
        section.set_beat_source(lambda when, not_before=0.0: 300.0)
        section._mark_on_beat_switch.setChecked(True)

        section.on_mark_start()  # 10_200 is past the end marker: wraps
        assert section._range_slider.startValue() == 8_200

    def test_it_never_marks_past_the_end_of_the_track(self, section):
        section.fake.heard_ms = DURATION_MS - 10.0
        section.set_beat_source(lambda when, not_before=0.0: 300.0)
        section._mark_on_beat_switch.setChecked(True)
        section.on_mark_start()
        assert section._range_slider.startValue() <= DURATION_MS


class Clicks:
    """A beat source that records what it was asked: clicks every 500 ms,
    the first one *first* ms away."""

    def __init__(self, first):
        self.first = first
        self.asked = []

    def __call__(self, when, not_before=0.0):
        self.asked.append(not_before)
        wait = self.first
        while wait < not_before:
            wait += 500.0
        return wait


class TestStartOnBeat:
    def test_off_it_seeks_at_once(self, section, qtbot):
        section._range_slider.setStartValue(8_000)
        section.set_beat_source(Clicks(300.0))
        with qtbot.waitSignal(section.seek_requested) as sig:
            section.on_goto_start()
        assert sig.args == [8_000]
        assert section.fake.jumps == []

    def test_on_it_jumps_to_the_start_on_the_next_click(self, section):
        section._range_slider.setStartValue(8_000)
        section.set_beat_source(Clicks(300.0))
        section._mark_on_beat_switch.setChecked(True)

        section.on_goto_start()

        assert section.fake.jumps == [(10_250.0, 8_000, False)]

    def test_a_click_already_rendered_is_passed_over(self, section):
        """The player has 40 ms of audio in the device already, so a click
        heard 20 ms from now is too late to jump on: it takes the next."""
        clicks = Clicks(20.0)
        section.set_beat_source(clicks)
        section._mark_on_beat_switch.setChecked(True)

        section.on_goto_start()

        assert clicks.asked == [pytest.approx(45.0)]  # lead + margin
        assert section.fake.jumps[0][0] == pytest.approx(9_950.0 + 520.0)

    def test_no_running_click_seeks_at_once(self, section, qtbot):
        section.set_beat_source(lambda when, not_before=0.0: None)
        section._mark_on_beat_switch.setChecked(True)
        with qtbot.waitSignal(section.seek_requested):
            section.on_goto_start()
        assert section.fake.jumps == []


class TestLoopOnBeat:
    def test_on_the_loop_starts_on_the_next_click(self, section):
        section._range_slider.setStartValue(8_000)
        section._range_slider.setEndValue(12_000)
        section.set_beat_source(Clicks(300.0))
        section._mark_on_beat_switch.setChecked(True)

        section._loop_checkbox.setChecked(True)

        assert section.fake.jumps == [(10_250.0, 8_000, True)]
        assert not section.fake.looping, "the engine starts looping at the click"
        assert section.fake.bounds == (8_000, 12_000)

    def test_switching_it_off_before_the_click_calls_it_off(self, section):
        section.set_beat_source(Clicks(300.0))
        section._mark_on_beat_switch.setChecked(True)
        section._loop_checkbox.setChecked(True)

        section._loop_checkbox.setChecked(False)

        assert section.fake.jumps[-1] == "cancel-loop"
        assert not section.fake.looping

    def test_off_it_loops_at_once(self, section):
        section.set_beat_source(Clicks(300.0))
        section._loop_checkbox.setChecked(True)
        assert section.fake.looping
        assert section.fake.jumps == []


class TestTheSwitch:
    def test_it_shares_a_row_with_start_and_sits_left_of_it(self, section):
        section._slicer_btn.setChecked(True)
        section.resize(700, 600)
        section.show()
        section.layout().activate()
        switch = section._mark_on_beat_switch
        start = section._goto_start_btn
        s = switch.mapTo(section, switch.rect().center())
        g = start.mapTo(section, start.rect().center())
        assert abs(s.y() - g.y()) <= 2
        assert s.x() < g.x()

    def test_the_tooltip_says_what_the_next_click_does(self, section):
        off = section._mark_on_beat_switch.toolTip()
        section._mark_on_beat_switch.setChecked(True)
        assert section._mark_on_beat_switch.toolTip() != off

    def test_it_announces_the_change(self, section, qtbot):
        with qtbot.waitSignal(section.mark_on_beat_changed) as sig:
            section._mark_on_beat_switch.setChecked(True)
        assert sig.args == [True]


@pytest.fixture
def player(qtbot):
    panel = PlayerPanel()
    qtbot.addWidget(panel)
    panel._metronome_section.view._stream_factory = lambda: None
    yield panel
    panel.shutdown_metronome()


class TestInThePlayer:
    def test_switching_on_opens_the_metronome_at_the_track_tempo(
        self, player, tmp_path
    ):
        f = tmp_path / "a.wav"
        f.write_bytes(b"not-really-audio")
        player.add_tracks(
            [{"file_path": str(f), "display_name": "a", "artist": "A",
              "title": "a", "bpm": "126"}],
            allow_duplicates=True,
        )
        player._playing_path = str(f)
        assert not player._metronome_section.is_expanded()

        player._slice._mark_on_beat_switch.setChecked(True)

        assert player._metronome_section.is_expanded()
        assert player._metronome_section.view._bpm_box.value() == pytest.approx(126.0)
        assert not player._metronome_section.view.running, "starting it is the user's"

    def test_switching_off_leaves_the_metronome_alone(self, player):
        player._slice._mark_on_beat_switch.setChecked(True)
        player._slice._mark_on_beat_switch.setChecked(False)
        assert player._metronome_section.is_expanded()

    def test_a_stopped_metronome_has_no_next_click(self, player):
        assert player._metronome_section.view.ms_to_next_click(0.0) is None
