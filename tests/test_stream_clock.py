"""Mark on beat's two clocks: what a stream is heard playing, and when the
metronome's next click lands. Both Qt-free and device-free."""

from types import SimpleNamespace

import numpy as np
import pytest

from src.gui.widgets import stream_clock
from src.gui.widgets.metronome_engine import MetronomeEngine
from src.gui.widgets.stream_clock import StreamClock

SR = 44100


def at(monkeypatch, t):
    monkeypatch.setattr(stream_clock.time, "perf_counter", lambda: t)


class TestStreamClock:
    def test_nothing_is_heard_before_the_first_block(self):
        assert StreamClock(SR).sample_at(1.0) is None

    def test_the_dac_time_is_when_the_block_is_heard(self, monkeypatch):
        clock = StreamClock(SR)
        at(monkeypatch, 10.0)
        # PortAudio says the block reaches the DAC 50 ms after the callback.
        clock.mark(SR, SimpleNamespace(currentTime=100.0, outputBufferDacTime=100.05))

        assert clock.sample_at(10.05) == pytest.approx(SR)
        assert clock.sample_at(10.0) == pytest.approx(SR - 0.05 * SR)
        assert clock.sample_at(10.55) == pytest.approx(SR * 1.5)

    def test_no_dac_time_falls_back_to_the_stated_latency(self, monkeypatch):
        clock = StreamClock(SR)
        clock.set_latency(0.02)
        at(monkeypatch, 5.0)
        clock.mark(0, SimpleNamespace(currentTime=0.0, outputBufferDacTime=0.0))

        assert clock.sample_at(5.02) == pytest.approx(0.0)

    def test_a_test_double_latency_counts_as_zero(self):
        clock = StreamClock(SR)
        clock.set_latency(object())
        assert clock._latency == 0.0

    def test_reset_forgets_the_anchor(self, monkeypatch):
        clock = StreamClock(SR)
        at(monkeypatch, 1.0)
        clock.mark(0, SimpleNamespace(currentTime=0.0, outputBufferDacTime=0.0))
        clock.reset()
        assert clock.sample_at(1.0) is None


class TestNextClick:
    def rendered(self, bpm, blocks):
        engine = MetronomeEngine(bpm, sr=SR)
        buf = np.zeros(2048, dtype=np.float32)
        for _ in range(blocks):
            engine.render(buf)
        return engine

    def test_the_first_click_is_sample_zero(self):
        assert MetronomeEngine(120.0, sr=SR).next_click_sample(0.0) == 0.0

    @pytest.mark.parametrize("after", [1.0, 10_000.0, 22_049.0, 22_050.0])
    def test_it_is_the_next_onset_on_the_grid(self, after):
        # 120 BPM at 44.1 kHz: a click every 22050 samples.
        engine = self.rendered(120.0, 20)
        assert engine.next_click_sample(after) == pytest.approx(22_050.0)

    def test_a_click_rendered_but_not_yet_heard_still_counts(self):
        """The render frontier runs a block or more ahead of the ear, so the
        click the ear is waiting for is often one already scheduled."""
        engine = self.rendered(120.0, 30)  # frontier at 61440, past 2 onsets
        assert engine.sample_position == 61_440
        assert engine.next_click_sample(40_000.0) == pytest.approx(44_100.0)

    def test_it_follows_a_tempo_change(self):
        engine = self.rendered(120.0, 1)
        engine.set_bpm(60.0)
        # The next scheduled onset keeps its place; the period after it is new.
        nxt = engine._next_beat
        assert engine.next_click_sample(nxt + 1) == pytest.approx(nxt + SR)
