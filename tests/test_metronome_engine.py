"""The metronome's click engine, offline.

No Qt and no audio device: the engine renders into a numpy buffer, so every
claim about its timing can be checked by looking at where the clicks landed.
That is the whole reason it is a separate module from the view.

The numbers here are the ones the spike measured
(`spitball/mip-pip/evidence/metronome/RESULTS.md`), re-asserted as bounds.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.gui.widgets.metronome_engine import (
    BEATS_PER_BAR,
    MAX_BPM,
    MIN_BPM,
    SHARP,
    SOFT,
    VOICES,
    MetronomeEngine,
    TapTempo,
    clamp_bpm,
)

SR = 44100


def render(engine, seconds, block=256):
    total = int(engine.sr * seconds)
    buf = np.zeros(total, dtype=np.float32)
    scratch = np.zeros(block, dtype=np.float32)
    i = 0
    while i < total:
        n = min(block, total - i)
        view = scratch[:n]
        engine.render(view)
        buf[i : i + n] = view
        i += n
    return buf


def onsets(buf, threshold=0.05, min_gap=400):
    """Rising edges of the click train, in samples.

    *min_gap* is a run of SILENCE, measured from the last hot sample — not
    from the last onset. Measuring it from the onset works only while every
    burst is shorter than the gap, which was true of the 5 ms tick and is not
    true of the 40 ms beep: one beep then reads as five onsets 400 samples
    apart, and every assertion downstream lines up against the wrong beat.
    The sub-threshold notches a sine puts at its own zero crossings are under
    a sample wide, and the beep's fade-out tail is ~75, so both stay well
    inside the gap.
    """
    hot = np.flatnonzero(np.abs(buf) > threshold)
    if len(hot) == 0:
        return np.array([], dtype=int)
    starts = [hot[0]]
    last = hot[0]
    for i in hot[1:]:
        if i - last > min_gap:
            starts.append(i)
        last = i
    return np.array(starts)


class TestTheGridDoesNotDrift:
    def test_thirty_seconds_stay_on_the_ideal_grid(self):
        """The claim the whole design exists for. A QTimer at this tempo
        drifts systematically because it can only hold whole milliseconds;
        a sample-counted grid cannot, by construction."""
        bpm = 127.53
        engine = MetronomeEngine(bpm, sr=SR)
        buf = render(engine, 30.0)
        period = SR * 60.0 / bpm

        found = onsets(buf)
        assert len(found) >= 60, "not enough clicks to say anything"
        ideal = np.arange(len(found)) * period
        error = np.abs(found - ideal)

        # A click's own rise takes a few samples to cross the threshold, so
        # the bound is the *drift*, not the absolute offset: the last beat is
        # no further off than the first.
        assert error.max() - error.min() <= 2, f"drifted {error.max() - error.min()}"

    def test_the_block_size_makes_no_difference(self):
        """The onset is a position on an absolute grid, not an offset within
        whatever buffer the device happens to hand us."""
        small = onsets(render(MetronomeEngine(127.53, sr=SR), 10.0, block=64))
        large = onsets(render(MetronomeEngine(127.53, sr=SR), 10.0, block=2048))

        assert len(small) == len(large)
        assert np.abs(small - large).max() <= 1


class TestChangingTempoMidStream:
    def test_no_click_is_lost_or_doubled(self):
        """The beat already scheduled keeps the position it was promised;
        only the period after it changes. Intervals go 500, 500, 400…"""
        engine = MetronomeEngine(120.0, sr=SR)
        block = 256
        total = int(10.0 * SR)
        buf = np.zeros(total, dtype=np.float32)
        scratch = np.zeros(block, dtype=np.float32)
        i = 0
        changed = False
        while i < total:
            if not changed and i >= int(5.25 * SR):  # mid-beat
                engine.set_bpm(150.0)
                changed = True
            n = min(block, total - i)
            view = scratch[:n]
            engine.render(view)
            buf[i : i + n] = view
            i += n

        intervals = np.diff(onsets(buf)) / SR * 1e3
        at_120 = np.sum(np.abs(intervals - 500.0) < 5)
        at_150 = np.sum(np.abs(intervals - 400.0) < 5)
        assert at_120 + at_150 == len(intervals), "an interval belonged to neither"
        assert at_120 >= 9 and at_150 >= 10

    def test_the_pending_beat_keeps_its_position(self):
        engine = MetronomeEngine(120.0, sr=SR)
        block = 256
        total = int(7.0 * SR)
        buf = np.zeros(total, dtype=np.float32)
        scratch = np.zeros(block, dtype=np.float32)
        i = 0
        changed = False
        while i < total:
            if not changed and i >= int(5.25 * SR):
                engine.set_bpm(150.0)
                changed = True
            n = min(block, total - i)
            view = scratch[:n]
            engine.render(view)
            buf[i : i + n] = view
            i += n

        found = onsets(buf)
        assert np.any(np.abs(found - 5.5 * SR) < 60), "the 5.5s beat moved"


class TestBending:
    def test_a_held_bend_shortens_the_period_and_releasing_restores_it(self):
        engine = MetronomeEngine(120.0, sr=SR)
        block = 256
        total = int(9.0 * SR)
        buf = np.zeros(total, dtype=np.float32)
        scratch = np.zeros(block, dtype=np.float32)
        i = 0
        while i < total:
            if i <= int(3.1 * SR) < i + block:
                engine.set_bend(1.04)
            if i <= int(5.1 * SR) < i + block:
                engine.clear_bend()
            n = min(block, total - i)
            view = scratch[:n]
            engine.render(view)
            buf[i : i + n] = view
            i += n

        intervals = np.diff(onsets(buf)) / SR * 1e3
        assert np.sum(np.abs(intervals - 500.0) < 2) >= 8, "unbent beats"
        assert np.sum(np.abs(intervals - 500.0 / 1.04) < 2) >= 3, "bent beats"

    def test_the_bend_is_clamped(self):
        engine = MetronomeEngine(120.0)
        engine.set_bend(99.0)
        assert engine.bend == 2.0
        engine.set_bend(0.0)
        assert engine.bend == 0.5


class TestTheBar:
    def test_beat_one_of_each_bar_is_the_accented_pitch(self):
        """Rendered at a tempo whose bar is a round number of samples, so the
        two pitches can be told apart by counting zero crossings in the burst
        rather than by trusting a label."""
        engine = MetronomeEngine(120.0, sr=SR)
        buf = render(engine, 4.1)
        found = onsets(buf)
        assert len(found) >= 8

        def crossings(start):
            burst = buf[start : start + int(SR * 0.004)]
            return int(np.sum(np.diff(np.signbit(burst)) != 0))

        accented = [crossings(found[i]) for i in range(0, 8, BEATS_PER_BAR)]
        plain = [crossings(found[i]) for i in range(1, 8) if i % BEATS_PER_BAR]
        assert min(accented) > max(plain), "the accent is not the higher pitch"


class TestTheTwoVoices:
    """Which pair of bursts the grid sounds with. Counted in zero crossings
    rather than trusted from a label, the same way the accent is above."""

    def test_the_sharp_voice_is_a_beep_not_a_tick(self):
        """The whole point of it: long enough for the ear to integrate and to
        hear a pitch, which is what carries over a track."""
        engine = MetronomeEngine(120.0, sr=SR)
        engine.set_voice(SHARP)
        soft_burst, _ = engine._voices[SOFT]
        sharp_burst, _ = engine._voices[SHARP]

        assert len(sharp_burst) > 4 * len(soft_burst)
        # A sustained body, not a decay: the tick is long past its peak by
        # its own midpoint and the beep is still at full height.
        assert abs(sharp_burst).max() > 0.99
        mid = len(sharp_burst) // 2
        assert abs(sharp_burst[mid : mid + 40]).max() > 0.95
        assert abs(soft_burst[len(soft_burst) // 2 :]).max() < 0.3

    def test_both_ends_are_ramped_so_the_beep_does_not_pop(self):
        """A tone starting or stopping on a hard edge is a broadband
        transient — audibly a click at each end of the thing meant to
        replace clicking."""
        for burst in engine_bursts(SHARP):
            assert abs(burst[0]) < 0.01
            assert abs(burst[-1]) < 0.01

    @staticmethod
    def _beat_crossings(engine):
        buf = render(engine, 2.1)
        found = onsets(buf)
        assert len(found) >= 4
        # Beat 2, i.e. an unaccented one, so this measures the voice and not
        # the 3:2 partner every voice shares.
        burst = buf[found[1] : found[1] + int(SR * 0.004)]
        return int(np.sum(np.diff(np.signbit(burst)) != 0))

    def test_it_starts_soft(self):
        assert MetronomeEngine(120.0, sr=SR).voice == SOFT

    def test_sharp_is_the_higher_of_the_two(self):
        soft = MetronomeEngine(120.0, sr=SR)
        sharp = MetronomeEngine(120.0, sr=SR)
        sharp.set_voice(SHARP)

        assert self._beat_crossings(sharp) > self._beat_crossings(soft)

    def test_each_voice_keeps_its_own_accent_on_beat_one(self):
        for voice in VOICES:
            engine = MetronomeEngine(120.0, sr=SR)
            engine.set_voice(voice)
            buf = render(engine, 4.1)
            found = onsets(buf)

            def crossings(start):
                burst = buf[start : start + int(SR * 0.004)]
                return int(np.sum(np.diff(np.signbit(burst)) != 0))

            accented = [crossings(found[i]) for i in range(0, 8, BEATS_PER_BAR)]
            plain = [crossings(found[i]) for i in range(1, 8) if i % BEATS_PER_BAR]
            assert min(accented) > max(plain), f"{voice} lost its accent"

    def test_switching_does_not_disturb_the_grid(self):
        """A voice change is not a tempo change: no click is lost or doubled
        across it, and each stretch sits on the grid.

        Measured per stretch rather than over the join, because a beep is
        detected a few samples later inside its own burst than a tick is — it
        ramps in and a tick does not — so the one gap that spans the switch
        is about the envelope, not about the schedule.
        """
        engine = MetronomeEngine(120.0, sr=SR)
        soft = onsets(render(engine, 1.1))
        sharp = onsets(_switched(engine, SHARP, 1.0))

        # 2.1 s at 120 BPM is five beats: 0, .5, 1.0 | 1.5, 2.0.
        assert (len(soft), len(sharp)) == (3, 2)
        assert np.allclose(np.diff(soft), SR // 2, atol=1)
        # The beep's tolerance is one attack ramp, and it has to be: a
        # threshold is crossed a little later at 2 kHz than at 3 kHz, so a
        # plain beat and the accent that follows it are detected 2 samples
        # apart even when both land on the grid exactly. Nothing the schedule
        # could get wrong is that small — a lost or doubled click moves an
        # onset by a whole beat, and the count above is what catches it.
        ramp = int(SR * 2.0 / 1000.0)
        assert np.allclose(np.diff(sharp), SR // 2, atol=ramp)

    def test_an_unknown_voice_is_refused(self):
        with pytest.raises(ValueError):
            MetronomeEngine(120.0, sr=SR).set_voice("cowbell")

    def test_it_allocates_nothing_per_change(self):
        """Both templates are rendered at construction, so a switch is a dict
        lookup — never a burst built on the audio thread."""
        engine = MetronomeEngine(120.0, sr=SR)
        before = {k: (id(a), id(b)) for k, (a, b) in engine._voices.items()}
        engine.set_voice(SHARP)
        engine.set_voice(SOFT)

        assert {k: (id(a), id(b)) for k, (a, b) in engine._voices.items()} == before


def engine_bursts(voice):
    engine = MetronomeEngine(120.0, sr=SR)
    return engine._voices[voice]


def _switched(engine, voice, seconds):
    engine.set_voice(voice)
    return render(engine, seconds)


class TestClamping:
    @pytest.mark.parametrize(
        "given,expected", [(0.0, MIN_BPM), (1000.0, MAX_BPM), (128.5, 128.5)]
    )
    def test_bpm_is_clamped_to_the_usable_range(self, given, expected):
        assert clamp_bpm(given) == expected

    def test_the_engine_clamps_too(self):
        engine = MetronomeEngine(9999.0)
        assert engine.bpm == MAX_BPM


class TestThePhaseTheEyeReads:
    def test_it_advances_through_the_beat_then_moves_to_the_next(self):
        engine = MetronomeEngine(120.0, sr=SR)  # a beat every 0.5s
        scratch = np.zeros(SR // 10, dtype=np.float32)  # 0.1s per render

        seen = []
        for _ in range(6):
            engine.render(scratch)
            seen.append(engine.phase_snapshot())

        within = [phase for _, phase in seen[:5]]
        assert within == sorted(within), "phase went backwards inside a beat"
        assert [beat for beat, _ in seen[:5]] == [0] * 5, "still the first beat"
        assert seen[5] == (1, pytest.approx(0.2)), "and over to the second"

    def test_a_fresh_engine_reports_the_start_of_the_bar(self):
        """Not -1 % 4, which would light the last beat of a bar that has not
        begun — the indicator would flash the accent before the first click."""
        assert MetronomeEngine(120.0).phase_snapshot()[0] == 0


class TestTapTempo:
    def test_one_tap_is_not_an_interval(self):
        assert TapTempo().tap(0.0) is None

    def test_perfect_taps_give_the_exact_tempo(self):
        tap = TapTempo()
        period = 60.0 / 128.0
        for k in range(8):
            result = tap.tap(k * period)
        assert result == pytest.approx(128.0)

    def test_jittered_taps_land_within_the_measured_error(self):
        """Eight taps at 128 BPM with 15 ms of Gaussian jitter measured a mean
        absolute error of 0.67 BPM. Asserted as a bound over many trials, not
        as the figure — this is a statistic, not a constant."""
        rng = np.random.default_rng(42)
        period = 60.0 / 128.0
        errors = []
        for _ in range(400):
            tap = TapTempo()
            estimate = None
            for k in range(8):
                estimate = tap.tap(k * period + rng.normal(0, 0.015))
            errors.append(abs(estimate - 128.0))
        assert np.mean(errors) < 1.0

    def test_more_taps_are_steadier_than_fewer(self):
        rng = np.random.default_rng(7)
        period = 60.0 / 128.0

        def error_at(count):
            out = []
            for _ in range(400):
                tap = TapTempo()
                estimate = None
                for k in range(count):
                    estimate = tap.tap(k * period + rng.normal(0, 0.015))
                out.append(abs(estimate - 128.0))
            return float(np.mean(out))

        assert error_at(8) < error_at(4)

    def test_a_long_pause_starts_a_new_count_in(self):
        tap = TapTempo()
        period = 60.0 / 128.0
        for k in range(4):
            tap.tap(k * period)

        assert tap.tap(4 * period + 3.0) is None, "the pause should have reset it"

    def test_a_stumble_at_a_fast_tempo_resets_too(self):
        """A gap of more than twice the running mean is a new count-in even
        when it is well under the two-second absolute threshold."""
        tap = TapTempo()
        period = 60.0 / 174.0  # 0.345s — 3x that is still only ~1s
        for k in range(4):
            tap.tap(k * period)

        assert tap.tap(4 * period + 3 * period) is None

    def test_only_the_last_eight_taps_count(self):
        tap = TapTempo()
        slow = 60.0 / 100.0
        fast = 60.0 / 160.0
        when = 0.0
        for _ in range(8):
            tap.tap(when)
            when += slow
        for _ in range(8):
            tap.tap(when)
            when += fast

        assert tap.bpm() == pytest.approx(160.0, abs=0.5)
