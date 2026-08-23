"""The beat clock: does it find the beat, hold it, and count bars.

Synthetic streams only — a kick train is an impulse every period, and that is
enough to say whether the lock forms, whether it sticks, and whether the
period adapts. The measured behaviour against real tracks lives in the
handoff's table and is reproduced by ``scripts/vis_sheet.py``, not here: a unit
test cannot tell you that off-beat bass exists.

No Qt in this file, on purpose — the clock is plain numpy and runs in
milliseconds, so these are fast.
"""

import numpy as np
import pytest

from src.gui.widgets.beat_clock import DEFAULT_BPM, BeatClock

FPS = 60.0
BPM = 128.0


def kick_train(beats, fps=FPS, bpm=BPM, offset=0.3, amplitude=1.0, noise=0.0,
               every=1, seed=0):
    """A feature stream of *beats* beats, one impulse each at *offset* into it.

    Measured in **beats**, not seconds, so two streams fed one after another to
    the same clock stay on the same grid — a clock ten seconds into a 128 BPM
    track is 21.33 beats in, and a follow-on stream starting at its own beat 0
    would arrive a third of a beat out and read as a rival train. That artefact
    cost an afternoon of believing the stickiness was broken.

    ``every`` accents one beat in N (``amplitude`` applies to the accented
    ones, 1.0 to the rest) — that is what gives the bar slot something to find.
    """
    rng = np.random.default_rng(seed)
    frames_per_beat = 60.0 / bpm * fps
    n = int(round(beats * frames_per_beat))
    out = np.zeros(n)
    if noise:
        out += rng.uniform(0.0, noise, n)
    beat = 0
    while True:
        # One frame early: the clock advances its phase and *then* takes the
        # frame's feature, so the block that lands on the beat is the one
        # before it. Without the -1 every impulse reads a frame late and the
        # lock looks 0.035 beats off when it is exactly right.
        frame = int(round((beat + offset) * frames_per_beat)) - 1
        if frame >= n:
            break
        if frame < 0:
            beat += 1
            continue
        out[frame] += amplitude if beat % every == 0 else 1.0
        beat += 1
    return out


def run(clock, feed):
    for value in feed:
        clock.tick(float(value))
    return clock


def beat_error(clock, offset=0.3):
    """How far the clock's beat sits from where the impulses land, in beats.

    An impulse at raw phase ``offset`` should be a whole beat of ``phase``, so
    the clock's offset is what has to match.
    """
    return abs((clock._offset - offset + 0.5) % 1.0 - 0.5)


# ── Lock ───────────────────────────────────────────────────────────────────


def test_it_locks_to_a_kick_train_and_stays_there():
    clock = BeatClock(1.0 / FPS)
    clock.set_tempo(BPM)
    run(clock, kick_train(16, noise=0.02))  # ~7.5 s
    assert clock.locked
    assert beat_error(clock) < 0.05
    run(clock, kick_train(64, noise=0.02))  # ~30 s more
    assert beat_error(clock) < 0.05


def test_a_weak_rival_train_never_takes_the_lock():
    """The stickiness is load-bearing: 22 visible jumps in two minutes without it."""
    clock = BeatClock(1.0 / FPS)
    clock.set_tempo(BPM)
    run(clock, kick_train(24))
    settled = clock._offset
    # Half a beat away, 60% of the mass — an off-beat bass line.
    rival = kick_train(128, offset=0.8, amplitude=0.6)
    run(clock, kick_train(128) + rival)
    assert beat_error(clock) < 0.05
    assert abs(clock._offset - settled) < 0.05


def test_a_strong_sustained_rival_does_take_the_lock():
    """...but a phase that really is where the music went must win eventually."""
    clock = BeatClock(1.0 / FPS)
    clock.set_tempo(BPM)
    run(clock, kick_train(24))
    # The old train stops and a new one starts half a beat away, twice as loud.
    run(clock, kick_train(24, offset=0.8, amplitude=2.0))
    assert beat_error(clock, offset=0.8) < 0.1


# ── Period ─────────────────────────────────────────────────────────────────


def test_adapt_rescues_a_tag_that_is_off_by_half_a_bpm():
    """A wrong tag walks the offset steadily; that walk is the correction signal."""
    clock = BeatClock(1.0 / FPS)
    clock.set_tempo(BPM - 0.7)  # what the file claims
    run(clock, kick_train(96, bpm=BPM))  # what it actually is, ~45 s of it
    assert abs(clock.tempo_bpm - BPM) < 0.15


def test_adapt_never_leaves_one_percent_of_the_tag():
    """A swung bar must not be allowed to run away with the tempo."""
    clock = BeatClock(1.0 / FPS)
    clock.set_tempo(BPM)
    run(clock, kick_train(128, bpm=BPM * 1.1))  # wildly wrong evidence
    assert (BPM * 0.99) - 1e-9 <= clock.tempo_bpm <= (BPM * 1.01) + 1e-9


def test_silence_free_runs_at_exactly_the_tempo():
    """No feature is no evidence: the tunnel keeps flying on its own grid."""
    clock = BeatClock(1.0 / FPS)
    clock.set_tempo(BPM)
    run(clock, np.zeros(int(20 * FPS)))
    assert clock.phase == pytest.approx(20.0 * BPM / 60.0, abs=1e-9)
    assert not clock.locked


def test_a_quiet_passage_does_not_cost_the_lock():
    clock = BeatClock(1.0 / FPS)
    clock.set_tempo(BPM)
    run(clock, kick_train(24))
    settled = clock._offset
    run(clock, np.zeros(int(10 * FPS)))
    assert clock.locked
    # The histogram decays uniformly, so the target it points at does not
    # move: the glide finishes converging onto it and stops. A thousandth of a
    # beat over ten seconds is that tail, not wandering.
    assert clock._offset == pytest.approx(settled, abs=0.01)
    assert beat_error(clock) < 0.05


# ── Bars ───────────────────────────────────────────────────────────────────


def test_the_bar_slot_settles_and_holds():
    clock = BeatClock(1.0 / FPS)
    clock.set_tempo(BPM)
    run(clock, kick_train(48, amplitude=2.0, every=4))
    # The train's accents are its own beats 0, 4, 8 ... and the clock started
    # with it, so the slot the evidence picks is the one it started on.
    assert clock._bar_slot == 0
    for _ in range(3):
        run(clock, kick_train(48, amplitude=2.0, every=4))
        assert clock._bar_slot == 0


def test_a_brief_louder_rival_slot_does_not_flip_the_bar():
    clock = BeatClock(1.0 / FPS)
    clock.set_tempo(BPM)
    run(clock, kick_train(48, amplitude=2.0, every=4))
    slot = clock._bar_slot
    # A few seconds of a louder accent landing two beats into the bar: the
    # same pattern with its first two beats cut off.
    two_beats = int(round(2 * 60.0 / BPM * FPS))
    run(clock, kick_train(10, amplitude=3.0, every=4)[two_beats:])
    assert clock._bar_slot == slot


# ── No tag ─────────────────────────────────────────────────────────────────


def test_without_a_tag_it_flies_at_the_default_then_finds_the_tempo():
    clock = BeatClock(1.0 / FPS)
    clock.set_tempo(None)
    assert clock.tempo_bpm == pytest.approx(DEFAULT_BPM)
    run(clock, kick_train(24, noise=0.02))  # ~11 s: past the bank's window
    assert abs(clock.tempo_bpm - BPM) <= 1.0
    run(clock, kick_train(128, noise=0.02))  # a minute more
    assert abs(clock.tempo_bpm - BPM) <= 1.0


# ── Frame interval ─────────────────────────────────────────────────────────


def test_the_lock_is_the_same_at_16_ms_and_33_ms():
    """Every coefficient is a time constant, not a per-frame number.

    The popout runs at 16 ms and the backdrop at 33; a clock tuned for one
    would be a different visual in the other, in ways that look like tuning.
    """
    fast = BeatClock(1.0 / 60.0)
    fast.set_tempo(BPM)
    run(fast, kick_train(64, fps=60.0, noise=0.02))
    slow = BeatClock(1.0 / 30.0)
    slow.set_tempo(BPM)
    run(slow, kick_train(64, fps=30.0, noise=0.02))
    assert abs(fast._offset - slow._offset) < 0.05
    assert abs(fast.tempo_bpm - slow.tempo_bpm) < 0.2
    assert fast.phase == pytest.approx(slow.phase, rel=1e-3)


# ── Reset ──────────────────────────────────────────────────────────────────


def test_reset_forgets_the_evidence_and_keeps_the_phase():
    """A seek: the histogram belongs to where we were, the flight does not."""
    clock = BeatClock(1.0 / FPS)
    clock.set_tempo(BPM)
    run(clock, kick_train(24))
    phase = clock.phase
    clock.reset()
    assert clock.phase == phase
    assert not clock.locked
    assert clock._hist.sum() == 0.0
