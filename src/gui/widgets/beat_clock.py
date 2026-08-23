"""A beat counter for the visuals: a tempo, a phase, and a bar slot.

Tunnel Chase turns on beat 1 of every bar and again on beat 3 of every fourth
bar, which means something has to *count beats* — the first visual that does.
The kick detector the other modes use cannot: measured over six real tracks it
fires 1.2–3.5 times per beat, because an off-beat bass line and an eighth-note
bass are as loud in the 50–120 Hz band as the kick. A phase-locked loop that
corrects on every one of those onsets is dragged off the beat on four of the
six.

So the two halves of "where is the beat" come from different places:

* **The period is the tag.** The file's own BPM — the app analysed it — is
  accurate, and a clock free-running at it drifts by nothing over a track.
* **The phase comes from accumulated evidence**, never from a single onset: a
  decaying histogram of a kick-flux feature against the clock's own beat, and
  the clock glides toward wherever that mass sits. With the tag as the period,
  every kick-led track locks to within a few hundredths of a beat and never
  jumps.

The lock is **sticky** on purpose. Without it a track whose bass sits between
the kicks flips the clock back and forth — 22 visible jumps in two minutes on
one measured track, 0 with stickiness. A rival phase has to out-mass the
locked one by half again *and hold it for two seconds* before the clock will
move to it; a neighbouring bin (the same train drifting) it follows freely.

Untagged files fall back to :class:`TempoBank`, a bank of candidate periods
each keeping its own phase histogram — 3 µs a frame, right on every track with
a regular kick and wrong by a rational ratio (3:2, 4:3) on the two without.
Running librosa during playback would be the accurate answer and is ruled out:
heavy DSP fights the audio callback for the GIL, which is why the pulse is a
few numpy ops in the first place.

No Qt here, and no audio: :class:`~.vis_canvas.VisRenderer` owns the spectrum
and hands ``tick`` a single number per frame.

Every coefficient below is expressed in **seconds** and turned into a
per-frame one from the host's interval, because the popout runs at 16 ms and
the backdrop at 33 ms and a constant tuned for one is a different visual in
the other.
"""

from __future__ import annotations

import numpy as np

BINS = 16  # phase histogram resolution: 1/16 beat
DEFAULT_BPM = 125.0  # what an untagged track flies at until the bank answers

_HIST_SECS = 6.0  # 5% of a deposit is left after this long
_GAIN_60 = 0.03  # offset glide per frame at 60 fps
_STICK_RATIO = 1.5  # how much a rival phase must out-mass the locked one by
_STICK_SECS = 2.0  # ...and for how long
_PROMINENCE = 2.0  # first lock needs a peak this many times the mean bin
# Correction applied to 1/period per unit of measured drift. The prototype
# used 0.3, which measured a standing ±0.27 BPM limit cycle against a tag 0.7
# out — the drift is read over a five-second window, so the loop is always
# correcting for what the offset was doing a moment ago. Halving it settles
# instead of ringing, and still rescues the wrong tag inside twenty seconds.
_ADAPT_GAIN = 0.15
_ADAPT_SECS = 5.0  # window the drift is measured over
# How long the lock must have held before its drift means anything. Without
# this the adapt reads the *convergence* — the offset walking from zero to
# wherever the beat is, in the first second or two — as a period error, and
# drives the tempo a full 1% off before it can recover. Measured: a correct
# 128 BPM tag settled at 126.8 within ten seconds and the lock ended a tenth
# of a beat from the kick.
_ADAPT_SETTLE = 6.0
_ADAPT_CLAMP = 0.01  # never more than ±1% away from the tag
_BAR_SECS = 16.0  # decay of the four bar-slot accumulators
_BAR_STICK_RATIO = 1.3
_BAR_STICK_SECS = 4.0
_ON_BEAT = 0.125  # ±1/8 beat counts as "on the beat"
_SILENCE = 1e-9  # below this the frame carries no evidence at all


def _decay_per_frame(frame_s: float, secs: float, left: float = 0.05) -> float:
    """Per-frame multiplier leaving *left* of a deposit after *secs*."""
    return float(np.exp(np.log(left) * frame_s / max(secs, 1e-6)))


class TempoBank:
    """Candidate periods racing on how peaked their own phase histogram is.

    91 candidates a beat-per-minute apart, each advancing its own phase and
    depositing the feature into its own 16 bins. A candidate at the true tempo
    collects every kick into one bin; one at a wrong tempo smears them. The
    peakiest wins.

    Wrong by a *ratio* is the failure mode it cannot fix on its own — a track
    with bass on every eighth reads as 180 against a tag of 120 — which is why
    it only ever runs when there is no tag to believe.
    """

    def __init__(self, frame_s: float, lo: float = 90.0, hi: float = 180.0,
                 step: float = 1.0, win: float = 8.0) -> None:
        self.bpms = np.arange(lo, hi + 1e-9, step)
        self.win = win
        self._idx = np.arange(len(self.bpms))
        self.hist = np.zeros((len(self.bpms), BINS))
        self.phase = np.zeros(len(self.bpms))
        self.elapsed = 0.0
        self.set_frame_interval(frame_s)

    def set_frame_interval(self, frame_s: float) -> None:
        self.frame_s = frame_s
        self.steps = self.bpms / 60.0 * frame_s  # beats per frame per candidate
        self.decay = _decay_per_frame(frame_s, self.win)

    def reset(self) -> None:
        self.hist[:] = 0.0
        self.phase[:] = 0.0
        self.elapsed = 0.0

    def tick(self, feat: float) -> None:
        self.phase = (self.phase + self.steps) % 1.0
        self.elapsed += self.frame_s
        self.hist *= self.decay
        if feat <= _SILENCE:
            return
        bins = (self.phase * BINS).astype(int)
        self.hist[self._idx, bins] += feat

    def scores(self) -> np.ndarray:
        """Peakiness per candidate: the best bin plus its neighbours, over the total."""
        total = self.hist.sum(axis=1) + 1e-9
        top = np.max(
            self.hist
            + np.roll(self.hist, 1, axis=1)
            + np.roll(self.hist, -1, axis=1),
            axis=1,
        )
        return top / total

    def ready(self) -> bool:
        return self.elapsed >= self.win


class BeatClock:
    """Beats elapsed, which beat of the bar it is, and how sure we are.

    ``phase`` is fractional beats and monotonic in the ordinary case; it is the
    only thing the scene needs, since the tunnel's arc length is measured in
    beats. ``beat_in_bar`` is 0 on the downbeat.

    The bar slot is *consistency, not downbeat detection*. It picks whichever
    of the four beat positions carries the most on-beat energy and holds it;
    on one measured track that is beat 4 and on another it is a coin-flip
    between 1 and 3. That is fine and deliberate — the turns need a stable
    four-beat grid, not a musicologically correct downbeat — so please don't
    "fix" it into a real downbeat detector.
    """

    def __init__(self, frame_s: float = 1.0 / 60.0) -> None:
        self._frame_s = frame_s
        self._nominal = 60.0 / DEFAULT_BPM
        self._bpm_known = False
        self.period = self._nominal
        self._bank = TempoBank(frame_s)
        self._raw = 0.0
        self._offset = 0.0
        self._locked_bin: int | None = None
        self._hist = np.zeros(BINS)
        self._rival_secs = 0.0
        self._locked_secs = 0.0
        self._bar = np.zeros(4)
        self._bar_slot = 0
        self._bar_rival_secs = 0.0
        self._elapsed = 0.0
        self._adapt_log: list[tuple[float, float]] = []  # (t, offset) once a second
        self._next_sample = 1.0
        self._bank_lead_secs = 0.0
        self._bank_adopted = False
        self.set_frame_interval(frame_s)

    # ── Public API ─────────────────────────────────────────────────────────

    @property
    def phase(self) -> float:
        """Beats elapsed since the clock started, fractional."""
        return self._raw - self._offset

    @property
    def beat_index(self) -> int:
        return int(np.floor(self.phase))

    @property
    def beat_in_bar(self) -> int:
        """0 on the bar's first beat, given the slot the evidence settled on."""
        return (self.beat_index - self._bar_slot) % 4

    @property
    def bar_slot(self) -> int:
        """Which value of ``beat_index % 4`` the evidence calls the downbeat."""
        return self._bar_slot

    @property
    def tempo_bpm(self) -> float:
        return 60.0 / self.period

    @property
    def locked(self) -> bool:
        return self._locked_bin is not None

    def set_frame_interval(self, frame_s: float) -> None:
        """Re-derive every coefficient from the host's frame interval."""
        if frame_s <= 0:
            return
        self._frame_s = frame_s
        self._hist_decay = _decay_per_frame(frame_s, _HIST_SECS)
        self._bar_decay = _decay_per_frame(frame_s, _BAR_SECS)
        # The 0.03 glide is per 1/60 s; hold the same time constant elsewhere.
        self._gain = 1.0 - (1.0 - _GAIN_60) ** (frame_s * 60.0)
        self._bank.set_frame_interval(frame_s)

    def set_tempo(self, bpm: float | None) -> None:
        """Take the track's tag as the period, or fall back to the bank."""
        self._bpm_known = bpm is not None and bpm > 0
        self._nominal = 60.0 / float(bpm) if self._bpm_known else 60.0 / DEFAULT_BPM
        self.period = self._nominal
        self.reset()

    def reset(self) -> None:
        """Forget the evidence, keep the phase.

        Called on a seek and on a new track: the histogram belongs to where we
        *were*, and left alone it argues with the new position for six seconds.
        The phase carries on, so nothing lurches — the lock re-forms in a few
        seconds.
        """
        self._hist[:] = 0.0
        self._locked_bin = None
        self._rival_secs = 0.0
        self._locked_secs = 0.0
        self._bar[:] = 0.0
        self._bar_rival_secs = 0.0
        self._adapt_log.clear()
        self._elapsed = 0.0
        self._next_sample = 1.0
        self._bank.reset()
        self._bank_lead_secs = 0.0
        self._bank_adopted = False

    def tick(self, feat: float) -> None:
        """Advance one frame. *feat* is this frame's kick-flux, 0..1."""
        self._raw += self._frame_s / self.period
        self._elapsed += self._frame_s
        if not self._bpm_known:
            self._bank.tick(feat)
            self._update_bank()
        # Every frame, not just the ones carrying an onset. A kick train is
        # two or three frames in every twenty-eight, so gliding only on those
        # divides the loop gain by an order of magnitude and the lock takes
        # half a minute to form instead of a few seconds. Silence takes care
        # of itself: with nothing in the histogram there is no target, and
        # _update_lock leaves the offset exactly where it was.
        self._deposit(feat)
        self._update_bar(feat)
        self._update_lock()
        self._maybe_adapt()

    # ── Internals ──────────────────────────────────────────────────────────

    def _deposit(self, feat: float) -> None:
        """Mass goes in at the *raw* phase, never the corrected one.

        The offset is a separate number for exactly this reason: nudge the
        phase and leave the histogram in its old coordinates and the clock
        slides forever, chasing a peak that moves with it. Rolling the
        histogram by the nudge instead rounds to zero every frame. Both were
        built and measured before this shape was.
        """
        self._hist *= self._hist_decay
        self._hist[int((self._raw % 1.0) * BINS) % BINS] += feat

    def _update_bar(self, feat: float) -> None:
        """Which of the four beat positions carries the on-beat energy."""
        frac = self.phase % 1.0
        if not (frac < _ON_BEAT or frac > 1.0 - _ON_BEAT):
            return
        self._bar *= self._bar_decay
        self._bar[int(np.floor(self.phase + _ON_BEAT)) % 4] += feat
        best = int(np.argmax(self._bar))
        if best != self._bar_slot and self._bar[best] > _BAR_STICK_RATIO * self._bar[self._bar_slot]:
            # Counted in on-beat frames, so four seconds here is around
            # sixteen seconds of music — only a quarter of frames land in the
            # window. That is the shape the measured slot stability (at most
            # one flip in two minutes) was taken with; loosening it is a
            # change to the thing, not to the test.
            self._bar_rival_secs += self._frame_s
            if self._bar_rival_secs >= _BAR_STICK_SECS:
                self._bar_slot = best
                self._bar_rival_secs = 0.0
        else:
            self._bar_rival_secs = 0.0

    def _update_lock(self) -> None:
        total = self._hist.sum()
        if total < 1e-6:
            return
        peak = int(np.argmax(self._hist))
        if self._locked_bin is None:
            if self._hist[peak] > _PROMINENCE * total / BINS:
                self._locked_bin = peak
                self._locked_secs = 0.0
            return
        self._locked_secs += self._frame_s
        current = self._locked_bin
        # Fine correction: glide toward the sub-bin centre of the locked bin,
        # as a circular mean over it and its two neighbours.
        neighbours = np.array([current - 1, current, current + 1])
        weights = self._hist[neighbours % BINS]
        angles = 2 * np.pi * (neighbours + 0.5) / BINS
        target = (
            np.arctan2((weights * np.sin(angles)).sum(), (weights * np.cos(angles)).sum())
            / (2 * np.pi)
        ) % 1.0
        error = (target - self._offset + 0.5) % 1.0 - 0.5
        # Deliberately NOT wrapped to [0, 1): a wrap is a whole beat of phase
        # discontinuity, which the tunnel would fly straight through.
        self._offset += self._gain * error
        # Coarse: has a non-adjacent bin out-massed us, and kept it up?
        distance = min((peak - current) % BINS, (current - peak) % BINS)
        if distance > 1 and self._hist[peak] > _STICK_RATIO * max(self._hist[current], 1e-9):
            self._rival_secs += self._frame_s
            if self._rival_secs >= _STICK_SECS:
                self._locked_bin = peak
                self._rival_secs = 0.0
                # A coarse move is a step, not a drift; the period must not be
                # corrected for the glide that follows it.
                self._locked_secs = 0.0
        else:
            self._rival_secs = 0.0
            if distance == 1:
                self._locked_bin = peak  # the same train drifting; follow it

    def _maybe_adapt(self) -> None:
        """Nudge the period to kill a standing drift in the offset.

        Rescues a tag that is off by half a BPM — the offset then walks
        steadily in one direction, which is exactly the signal. Clamped to ±1%
        of the tag so a swung bar can never run away with the tempo, and off
        entirely when there is no tag, because then the bank owns the period
        and two controllers on one number is how an oscillation starts.
        """
        if not self._bpm_known or self._locked_bin is None:
            return
        if self._locked_secs < _ADAPT_SETTLE:
            self._adapt_log.clear()
            self._next_sample = self._elapsed + 1.0
            return
        if self._elapsed < self._next_sample:
            return
        self._next_sample = self._elapsed + 1.0
        self._adapt_log.append((self._elapsed, self._offset))
        window = int(_ADAPT_SECS) + 1
        if len(self._adapt_log) < window:
            return
        (t0, p0), (t1, p1) = self._adapt_log[-window], self._adapt_log[-1]
        drift = (p1 - p0) / (t1 - t0)  # beats of offset per second
        new = 1.0 / (1.0 / self.period - _ADAPT_GAIN * drift)
        lo, hi = self._nominal * (1 - _ADAPT_CLAMP), self._nominal * (1 + _ADAPT_CLAMP)
        self.period = float(np.clip(new, lo, hi))

    def _update_bank(self) -> None:
        """Adopt the bank's tempo once it has something, then stick to it.

        The first answer is taken as soon as the bank has its window of data —
        until then the tunnel flies at the default, and there is nothing to be
        loyal to. Every *later* change has to earn it, or a track whose kick
        pattern shifts for a bar re-times the whole visual.
        """
        if not self._bank.ready():
            return
        scores = self._bank.scores()
        best = int(np.argmax(scores))
        if not self._bank_adopted:
            self._bank_adopted = True
            self.period = 60.0 / float(self._bank.bpms[best])
            self._nominal = self.period
            return
        current = int(np.argmin(np.abs(self._bank.bpms - self.tempo_bpm)))
        if best == current:
            self._bank_lead_secs = 0.0
            return
        if scores[best] > 1.2 * max(scores[current], 1e-9):
            self._bank_lead_secs += self._frame_s
            if self._bank_lead_secs >= 4.0:
                self.period = 60.0 / float(self._bank.bpms[best])
                self._nominal = self.period
                self._bank_lead_secs = 0.0
        else:
            self._bank_lead_secs = 0.0
