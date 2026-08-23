"""The metronome's controls, and how it sits in the Keyboard panel.

The engine's timing lives in tests/test_metronome_engine.py, offline and
Qt-free. What is left here is the interface: the scrub box, the buttons, the
switcher, and — the one that matters — that leaving the view kills the click.

**No test here opens an audio device.** ``MetronomeView`` takes a stream
factory precisely so this file can hand it one that returns a recorder, and
the assertions are about the *view's* state, never the device's.
"""

from __future__ import annotations

import pathlib

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from src.gui.widgets.keyboard_panel import KeyboardPanel
from src.gui.widgets.metronome_engine import MAX_BPM, MIN_BPM
from src.gui.widgets.metronome_view import (
    DEFAULT_CLICK_VOLUME,
    BpmScrubBox,
    MetronomeView,
)


class FakeStream:
    """Stands in for sd.OutputStream. Records that it was asked to stop."""

    def __init__(self):
        self.stopped = False
        self.closed = False

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


@pytest.fixture
def opened(qtbot):
    """A view whose 'device' is a recorder, plus the list of streams made."""
    streams = []

    def factory():
        stream = FakeStream()
        streams.append(stream)
        return stream

    view = MetronomeView(stream_factory=factory)
    qtbot.addWidget(view)
    return view, streams


@pytest.fixture
def view(opened):
    return opened[0]


@pytest.fixture
def box(qtbot):
    widget = BpmScrubBox(120.0)
    qtbot.addWidget(widget)
    widget.resize(96, 30)
    return widget


def drag(widget, dy, modifier=Qt.KeyboardModifier.NoModifier):
    """Press in the middle, move by dy (negative = up), release."""
    start = QPointF(widget.width() / 2, widget.height() / 2)
    end = QPointF(start.x(), start.y() + dy)
    for kind, at, buttons in (
        (QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseMove, end, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseButtonRelease, end, Qt.MouseButton.NoButton),
    ):
        widget.event(
            QMouseEvent(
                kind,
                at,
                Qt.MouseButton.LeftButton,
                buttons,
                modifier,
            )
        )


class TestTheScrubBox:
    def test_it_shows_two_decimals(self, box):
        assert box.text() == "120.00"

    def test_dragging_up_raises_the_tempo(self, box):
        drag(box, -40)  # 40px up at 4px per BPM
        assert box.value() == pytest.approx(130.0)
        assert box.text() == "130.00"

    def test_dragging_down_lowers_it(self, box):
        drag(box, 40)
        assert box.value() == pytest.approx(110.0)

    def test_shift_makes_the_same_gesture_two_decimals_fine(self, box):
        drag(box, -40, Qt.KeyboardModifier.ShiftModifier)
        assert box.value() == pytest.approx(120.10)

    def test_a_tiny_movement_is_a_click_not_a_drag(self, box):
        """The two gestures share a press, so the drag only starts past a
        threshold — otherwise clicking to type would nudge the tempo."""
        drag(box, -2)
        assert box.value() == 120.0

    def test_a_drag_is_clamped_at_both_ends(self, box):
        drag(box, -4000)
        assert box.value() == MAX_BPM
        drag(box, 8000)
        assert box.value() == MIN_BPM

    def test_it_announces_a_change_once(self, box, qtbot):
        with qtbot.waitSignal(box.value_changed) as caught:
            drag(box, -40)
        assert caught.args == [pytest.approx(130.0)]


class TestTypingATempo:
    def test_a_typed_value_is_taken_and_reformatted(self, box):
        box.setText("174.5")
        box.editingFinished.emit()
        assert box.value() == 174.5
        assert box.text() == "174.50"

    def test_a_comma_decimal_works_too(self, box):
        """Half the languages this ships in write 174,5."""
        box.setText("174,5")
        box.editingFinished.emit()
        assert box.value() == 174.5

    def test_junk_restores_the_last_good_value(self, box):
        box.setText("banana")
        box.editingFinished.emit()
        assert box.value() == 120.0
        assert box.text() == "120.00"

    def test_a_typed_value_out_of_range_is_clamped(self, box):
        box.setText("9000")
        box.editingFinished.emit()
        assert box.value() == MAX_BPM


class TestTheStepButtons:
    def test_they_move_by_a_whole_bpm_and_keep_the_decimals(self, view):
        view._bpm_box.set_value(120.37)

        view._plus_btn.click()
        assert view._bpm_box.value() == pytest.approx(121.37)

        view._minus_btn.click()
        view._minus_btn.click()
        assert view._bpm_box.value() == pytest.approx(119.37)

    def test_they_repeat_while_held(self, view):
        """A tempo is often 10 or 20 BPM away; clicking twenty times is not
        the gesture. Same precedent as the slicer's nudge buttons."""
        assert view._plus_btn.autoRepeat()
        assert view._minus_btn.autoRepeat()

    def test_the_bend_buttons_do_not_repeat(self, view):
        """They are a hold, not a click — pressed and released are the whole
        gesture, and auto-repeat would fire pressed over and over."""
        assert not view._slower_btn.autoRepeat()
        assert not view._faster_btn.autoRepeat()


class TestBending:
    def test_holding_leans_the_tempo_and_releasing_snaps_back(self, view):
        view._faster_btn.pressed.emit()
        assert view._engine.bend == pytest.approx(1.04)
        view._faster_btn.released.emit()
        assert view._engine.bend == 1.0

        view._slower_btn.pressed.emit()
        assert view._engine.bend == pytest.approx(0.96)
        view._slower_btn.released.emit()
        assert view._engine.bend == 1.0

    def test_the_tempo_itself_is_untouched(self, view):
        """A bend is a lean, not an edit — the box must not move under it."""
        view._faster_btn.pressed.emit()
        assert view._bpm_box.value() == 120.0
        assert view._engine.bpm == 120.0


class TestTheTransport:
    def test_starting_opens_a_stream_and_runs_the_light(self, opened):
        view, streams = opened

        view._start_btn.setChecked(True)

        assert len(streams) == 1
        assert view._vis_timer.isActive()
        assert view.running

    def test_stopping_closes_it(self, opened):
        view, streams = opened
        view._start_btn.setChecked(True)

        view._start_btn.setChecked(False)

        assert streams[0].stopped and streams[0].closed
        assert not view._vis_timer.isActive()
        assert not view.running

    def test_the_button_says_what_the_next_click_does(self, view):
        assert view._start_btn.text() == "Start"
        view._start_btn.setChecked(True)
        assert view._start_btn.text() == "Stop"

    def test_hiding_the_view_stops_it(self, opened, qtbot):
        """Switching to another view in the switcher, or off the panel: the
        click is not background music."""
        view, streams = opened
        view.show()
        qtbot.waitExposed(view)
        view._start_btn.setChecked(True)

        view.hide()

        assert streams[0].stopped
        assert not view.running
        assert not view._start_btn.isChecked()

    def test_a_machine_with_no_output_still_keeps_time(self, qtbot):
        """The factory returning None is the no-device case. The light has to
        keep running or the whole view looks broken."""
        view = MetronomeView(stream_factory=lambda: None)
        qtbot.addWidget(view)

        view._start_btn.setChecked(True)

        assert view._vis_timer.isActive()
        assert view.running

    def test_starting_restarts_the_bar(self, view):
        """Beat 1 is the accented click, so a start that picked up mid-bar
        would put the accent in the wrong place.

        Phase reads 1.0 rather than 0.0 here on purpose: phase measures
        progress *toward* the next beat, and immediately after a reset the
        first beat is due right now.
        """
        import numpy as np

        view._engine.render(np.zeros(44100, dtype=np.float32))  # a whole second
        assert view._engine.phase_snapshot()[0] == 1, "mid-bar"

        view.start()

        assert view._engine.phase_snapshot() == (0, 1.0)


class TestTap:
    def test_four_taps_set_the_tempo(self, view, monkeypatch):
        clock = {"t": 0.0}
        monkeypatch.setattr(
            "src.gui.widgets.metronome_view.time.perf_counter",
            lambda: clock["t"],
        )
        for _ in range(4):
            view._tap_btn.click()
            clock["t"] += 60.0 / 140.0

        assert view._bpm_box.value() == pytest.approx(140.0, abs=0.1)

    def test_one_tap_changes_nothing(self, view):
        view._tap_btn.click()
        assert view._bpm_box.value() == 120.0


class TestTheClickHasItsOwnVolume:
    """It first followed the Keyboard panel's slider, which sits beside the
    piano and says nothing about the click — the user's report was that the
    metronome had no volume control at all. One slider on the view, and it is
    the only thing that reaches the engine's gain."""

    def test_the_slider_reaches_the_click(self, view):
        view._volume_slider.setValue(40)

        assert view._engine._gain == pytest.approx(0.4)
        assert view.volume == pytest.approx(0.4)

    def test_it_starts_at_the_level_the_click_used_to_have(self, view):
        assert view._volume_slider.value() == DEFAULT_CLICK_VOLUME
        assert view._engine._gain == pytest.approx(DEFAULT_CLICK_VOLUME / 100.0)

    def test_the_panels_slider_no_longer_moves_it(self, qtbot):
        panel = KeyboardPanel()
        qtbot.addWidget(panel)
        before = panel._metronome._engine._gain

        panel._on_volume_change(10)

        assert panel._engine.volume == pytest.approx(0.1)
        assert panel._metronome._engine._gain == pytest.approx(before)
        panel.stop_audio()


class TestItIsTheThirdViewInTheSwitcher:
    def test_the_switcher_offers_three_views(self, qtbot):
        panel = KeyboardPanel()
        qtbot.addWidget(panel)
        try:
            assert panel._view_combo.count() == 3
            assert panel._view_combo.itemText(2) == "Metronome"
        finally:
            panel.stop_audio()

    def test_exactly_one_view_shows_at_a_time(self, qtbot):
        panel = KeyboardPanel()
        qtbot.addWidget(panel)
        try:
            views = [panel._hex, panel._circle, panel._metronome]
            for index in range(3):
                panel._view_combo.setCurrentIndex(index)
                visible = [i for i, w in enumerate(views) if not w.isHidden()]
                assert visible == [index]
        finally:
            panel.stop_audio()

    def test_leaving_the_panel_stops_the_click(self, qtbot):
        """MainWindow calls stop_audio on a page change and on close. The
        Keyboard panel going off screen does NOT hide the metronome widget —
        a child of a hidden parent gets no hideEvent — so stop_audio has to
        reach the click itself.
        """
        panel = KeyboardPanel()
        qtbot.addWidget(panel)
        streams = []
        panel._metronome._stream_factory = lambda: streams.append(FakeStream()) or streams[-1]
        panel._view_combo.setCurrentIndex(2)
        panel._metronome._start_btn.setChecked(True)
        assert panel._metronome.running

        panel.stop_audio()

        assert not panel._metronome.running
        assert streams[0].stopped

    def test_the_holder_is_wide_enough_for_all_three(self, qtbot):
        """The holder's width is fixed to the widest view so the column does
        not slide sideways when the switcher changes it."""
        panel = KeyboardPanel()
        qtbot.addWidget(panel)
        try:
            holder = panel._metronome.parentWidget()
            assert holder.width() >= panel._metronome.sizeHint().width()
            assert holder.width() >= panel._hex.width()
        finally:
            panel.stop_audio()


class TestTheSmallButtonsSurviveTheStylesheet:
    """A 24px button is the app's standing trap, and the suite cannot see it.

    The GUI suite runs with no application stylesheet, so here the buttons
    wear their setFixedSize and look fine whatever the QSS says — both the
    original failure (the global 8px/16px padding leaves no contents rect, so
    no glyph is drawn) and the one the first fix caused (a stylesheet
    `min-width: 0` REPLACES the minimum setFixedSize set, the hint collapses
    to the glyph, and the layout hands the button 9px) are invisible.

    So this asserts the rule, on the line anyone would edit to reintroduce
    either. The rendering itself was ground-truthed by hand.
    """

    def rule_for(self, name):
        text = (
            pathlib.Path("src/gui/styles/app.qss.template").read_text()
        )
        start = text.index(f"QPushButton#{name} {{")
        return text[start : text.index("}", start)]

    def test_the_step_button_rule_kills_the_global_padding(self):
        assert "padding: 0;" in self.rule_for("metroStepButton")

    def test_it_states_a_width_rather_than_zeroing_the_minimum(self):
        rule = self.rule_for("metroStepButton")
        assert "min-width: 0" not in rule, "collapses the button to its glyph"
        assert "min-width: 24px;" in rule
        assert "max-width: 24px;" in rule
