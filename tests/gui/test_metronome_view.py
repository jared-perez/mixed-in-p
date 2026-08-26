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

from src.utils.config import load_config, save_config
from src.gui.widgets.metronome_engine import MAX_BPM, MIN_BPM, SHARP, SOFT
from src.gui.widgets.metronome_view import (
    DEFAULT_CLICK_VOLUME,
    SILENT,
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


def store_global_click(on):
    """Put the setting on disk BEFORE the widget is built.

    MetronomeView imports load_config at module level, so patching it on the
    config module would not be seen — and the suite's isolated_app_data makes
    this a throwaway file per test. Same rule the panel settings follow.
    """
    cfg = load_config()
    cfg.metronome_global_click = on
    save_config(cfg)


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
        """Switching to another view in the switcher, or off the panel.

        With Global Click off, which is not the default — see
        TestGlobalClickSurvivesLeavingTheView for the other half.
        """
        view, streams = opened
        view._global_btn.setChecked(False)
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


class TestTheClickRowPicksWhichClick:
    """Three exclusive toggles where the volume slider was: silent, soft,
    sharp. The level is a constant now — it is which click that varies."""

    def test_it_starts_on_the_soft_click_at_the_old_level(self, view):
        assert view.click_choice == SOFT
        assert view._engine.voice == SOFT
        assert view._engine._gain == pytest.approx(DEFAULT_CLICK_VOLUME / 100.0)

    def test_the_sharp_choice_reaches_the_engine(self, view):
        view.set_click_choice(SHARP)

        assert view._engine.voice == SHARP
        assert view._engine._gain == pytest.approx(DEFAULT_CLICK_VOLUME / 100.0)

    def test_silence_is_a_gain_of_zero(self, view):
        view.set_click_choice(SILENT)

        assert view.volume == 0.0
        assert view._engine._gain == 0.0

    def test_silence_leaves_the_voice_alone_so_coming_back_restores_it(self, view):
        view.set_click_choice(SHARP)
        view.set_click_choice(SILENT)

        assert view._engine.voice == SHARP
        view.set_click_choice(SHARP)
        assert view._engine._gain == pytest.approx(DEFAULT_CLICK_VOLUME / 100.0)

    def test_only_one_is_ever_on(self, view):
        for choice in (SILENT, SOFT, SHARP):
            view.set_click_choice(choice)
            on = [c for c, b in view._click_buttons.items() if b.isChecked()]
            assert on == [choice]

    def test_the_light_keeps_time_while_silent(self, view):
        """Silence is a gain, not a stopped grid — the beat light reads the
        engine, so a silent metronome still has to be a running one."""
        view.set_click_choice(SILENT)
        view._start_btn.setChecked(True)

        assert view.running
        assert view._vis_timer.isActive()

    def test_a_switch_applies_once_though_it_is_announced_twice(self, view):
        """An exclusive group announces both halves. Both would apply the
        same choice — Qt has already checked the incoming button when the
        outgoing one emits — so this is about the redundant call, not about
        correctness, and the handler's docstring says so."""
        view.set_click_choice(SILENT)
        applied = []
        view._apply_click_choice = lambda: applied.append(view.click_choice)

        view.set_click_choice(SHARP)

        assert applied == [SHARP]

class TestGlobalClickSurvivesLeavingTheView:
    """On by default and remembered. Off, hiding the view silences it.

    Hiding is the whole mechanism — collapsing the Player's metronome section
    is what hides this widget — so it is tested here rather than at the
    section. What the *host* does with it is in test_player_metronome.py.
    """

    def test_it_is_on_by_default(self, view):
        assert view.global_click

    def test_hiding_the_view_still_stops_it_when_off(self, opened, qtbot):
        view, streams = opened
        view._global_btn.setChecked(False)
        view.show()
        qtbot.waitExposed(view)
        view._start_btn.setChecked(True)

        view.hide()

        assert not view.running

    def test_hiding_the_view_keeps_it_when_on(self, opened, qtbot):
        view, streams = opened
        view.show()
        qtbot.waitExposed(view)
        view._start_btn.setChecked(True)

        view.hide()

        assert view.running
        assert not streams[0].stopped
        assert view._start_btn.isChecked()
        view.stop()

    def test_the_tooltip_says_what_the_next_click_does(self, view):
        before = view._global_btn.toolTip()
        view._global_btn.setChecked(False)

        assert view._global_btn.toolTip() != before
        assert "leave this view" in view._global_btn.toolTip()

    def test_the_tooltip_starts_on_the_sentence_the_stored_state_earns(self, qtbot):
        """setChecked runs before the tooltip is first synced, so a stored
        'on' must not open wearing the 'off' sentence — the blockSignals law
        one door along: housekeeping a caller can skip has to be re-run."""
        store_global_click(False)
        off = MetronomeView(stream_factory=lambda: None)
        qtbot.addWidget(off)
        store_global_click(True)
        on = MetronomeView(stream_factory=lambda: None)
        qtbot.addWidget(on)

        assert "Keep the click going" in off._global_btn.toolTip()
        assert "Stop the click" in on._global_btn.toolTip()


class TestGlobalClickIsRemembered:
    """It is a mode, not a gesture — a DJ who wants the click everywhere wants
    it there next launch too."""

    def test_a_stored_off_is_restored(self, qtbot):
        store_global_click(False)
        view = MetronomeView(stream_factory=lambda: None)
        qtbot.addWidget(view)

        assert not view.global_click

    def test_a_stored_on_is_restored(self, qtbot):
        store_global_click(False)
        store_global_click(True)
        view = MetronomeView(stream_factory=lambda: None)
        qtbot.addWidget(view)

        assert view.global_click

    def test_clicking_it_writes_through(self, view):
        view._global_btn.setChecked(False)

        assert load_config().metronome_global_click is False
        view._global_btn.setChecked(True)
        assert load_config().metronome_global_click is True

    def test_it_defaults_on_for_a_config_that_never_heard_of_it(self):
        """Every config in the wild predates the field."""
        assert load_config().metronome_global_click is True

    def test_the_window_does_not_revert_it_on_close(self):
        """_persist_config re-reads the fields panels write before saving its
        own startup snapshot. A new one missing from that merge list is
        reverted by the very act of closing the window."""
        source = pathlib.Path("src/gui/main_window.py").read_text()
        start = source.index("def _persist_config")
        merge = source[start : source.index("save_config(self._config)", start)]
        assert "metronome_global_click = disk.metronome_global_click" in merge

    def test_it_sits_beside_tap(self, view):
        row = view._tap_btn.parentWidget().layout().itemAt(0).layout()
        widgets = [row.itemAt(i).widget() for i in range(row.count())]
        assert widgets.index(view._global_btn) == widgets.index(view._tap_btn) + 1


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

    def test_the_click_toggles_obey_the_same_rule(self):
        rule = self.rule_for("metroClickButton")
        assert "padding: 0;" in rule
        assert "min-width: 0" not in rule, "collapses the button to its glyph"
        assert "min-width: 24px;" in rule
        assert "max-width: 24px;" in rule

    def test_a_checked_click_toggle_reads_as_on(self):
        """The one thing #metroStepButton has no use for: these hold a state
        rather than firing an action."""
        text = pathlib.Path("src/gui/styles/app.qss.template").read_text()
        assert "QPushButton#metroClickButton:checked {" in text
        assert "QPushButton#metroGlobalButton:checked" in text
