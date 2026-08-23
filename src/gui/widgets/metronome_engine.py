"""The metronome's click train, and the tap-tempo estimator.

Qt-free and device-free on purpose (the ``beat_clock.py`` shape): everything
here is testable offline against a numpy buffer, and the view owns the stream
that calls ``render`` from its audio callback.

**The beat grid is kept in SAMPLES, not in wall time.** ``_next_beat`` is a
float sample position advanced by ``sr * 60 / bpm`` per beat, so there is no
cumulative drift by construction — the error is bounded by rounding each onset
to the nearest sample, ±0.5 sample ≈ 0.011 ms at 44.1 kHz, and it does not
depend on the block size.

That is not a preference; a QTimer measurably cannot do this job. Measured on
an M-series Mac (`spitball/mip-pip/evidence/metronome/RESULTS.md`): a repeating
PreciseTimer holds an *integer* millisecond interval, so 174 BPM (344.83 ms →
345) drifts 0.174 ms every beat, systematically, forever; naive one-shot rearm
drifts ~1 ms/beat; a CoarseTimer is off by 26 ms on a single fire. A
drift-corrected absolute schedule holds under 1 ms net with ±1.5 ms jitter —
good enough for a blinking light, never for the sound. So the sound is the
clock and the visual polls it (``phase_snapshot``).

A related rule the rest of this app has had to learn twice: nothing here is
denominated in frames. Where a visual decay would need re-deriving whenever
the host's frame rate changed, a sample count is already an absolute duration.
Keep it that way.
"""

from __future__ import annotations

import statistics
import threading

import numpy as np

# Beats per bar. Beat 1 gets the higher click so the bar is audible.
BEATS_PER_BAR = 4

# The click itself: a short decaying sine burst. Two pitches, one accented.
_CLICK_MS = 5.0
_CLICK_HZ = 1000.0
_ACCENT_HZ = 1500.0

# What the BPM box will accept. Wide enough for half-time and drum'n'bass.
MIN_BPM = 20.0
MAX_BPM = 300.0


def _make_click(freq: float, sr: int) -> np.ndarray:
    """One burst, rendered once at construction and only ever sliced after.

    Building this in the audio callback would allocate on the audio thread,
    which is the one place in the app that must not.
    """
    count = int(sr * _CLICK_MS / 1000.0)
    t = np.arange(count) / sr
    envelope = np.exp(-t / (_CLICK_MS / 1000.0 / 4.0))
    return (np.sin(2 * np.pi * freq * t) * envelope).astype(np.float32)


def clamp_bpm(bpm: float) -> float:
    return max(MIN_BPM, min(MAX_BPM, float(bpm)))


class MetronomeEngine:
    """Renders a click train by sample count. Safe to reconfigure from any
    thread; the audio callback only ever calls :meth:`render`."""

    def __init__(self, bpm: float = 120.0, sr: int = 44100) -> None:
        self._lock = threading.Lock()
        self.sr = sr
        self._bpm = clamp_bpm(bpm)
        self._bend = 1.0
        self._gain = 1.0
        self._click = _make_click(_CLICK_HZ, sr)
        self._accent = _make_click(_ACCENT_HZ, sr)
        self._pos = 0  # absolute sample position of the next block's start
        self._next_beat = 0.0  # absolute float sample of the next onset
        self._beat_index = 0
        # Clicks still sounding, as (onset, template, samples already mixed).
        self._active: list[tuple[int, np.ndarray, int]] = []

    # ── parameters (any thread) ─────────────────────────────────────

    @property
    def bpm(self) -> float:
        return self._bpm

    def set_bpm(self, bpm: float) -> None:
        """Change the tempo without disturbing the beat already scheduled.

        ``_next_beat`` is deliberately left alone: the beat the user is about
        to hear keeps the position it was promised, and only the period
        *after* it changes. Measured on a 120 → 150 change mid-beat: no click
        lost, none doubled, intervals go 500, 500, 400…
        """
        with self._lock:
            self._bpm = clamp_bpm(bpm)

    def set_bend(self, multiplier: float) -> None:
        """Temporarily multiply the tempo (1.04 = 4% faster) while held."""
        with self._lock:
            self._bend = max(0.5, min(2.0, float(multiplier)))

    def clear_bend(self) -> None:
        self.set_bend(1.0)

    @property
    def bend(self) -> float:
        return self._bend

    def set_gain(self, gain: float) -> None:
        with self._lock:
            self._gain = max(0.0, min(1.0, float(gain)))

    def reset(self) -> None:
        """Start the grid again from beat 1 of the bar."""
        with self._lock:
            self._pos = 0
            self._next_beat = 0.0
            self._beat_index = 0
            self._active = []

    # ── the audio thread ────────────────────────────────────────────

    def render(self, out: np.ndarray) -> None:
        """Mix the clicks landing in this block into mono float32 *out*.

        Allocation-free in the steady state: the two burst templates are
        pre-rendered and only sliced here.
        """
        frames = len(out)
        out[:] = 0.0
        with self._lock:
            bpm = self._bpm
            bend = self._bend
            gain = self._gain
        end = self._pos + frames
        while self._next_beat < end:
            onset = int(round(self._next_beat))
            accented = self._beat_index % BEATS_PER_BAR == 0
            self._active.append((onset, self._accent if accented else self._click, 0))
            self._next_beat += self.sr * 60.0 / (bpm * bend)
            self._beat_index += 1
        still: list[tuple[int, np.ndarray, int]] = []
        for onset, template, consumed in self._active:
            src = consumed
            dst = onset + consumed - self._pos
            if dst < 0:
                src += -dst
                dst = 0
            count = min(frames - dst, len(template) - src)
            if count > 0:
                out[dst : dst + count] += template[src : src + count]
                consumed = src + count
            if consumed < len(template):
                still.append((onset, template, consumed))
        self._active = still
        if gain != 1.0:
            out *= gain
        self._pos = end

    # ── what the eye reads ──────────────────────────────────────────

    def phase_snapshot(self) -> tuple[int, float]:
        """(beat within the bar, 0.0-1.0 phase toward the next beat).

        The sample clock is the truth and this only feeds a repaint, so a
        coarse timer polling it is entirely adequate — no precise-timer
        machinery is needed for the eye.
        """
        with self._lock:
            bpm = self._bpm
            bend = self._bend
        period = self.sr * 60.0 / (bpm * bend)
        # _beat_index counts beats already *scheduled*, so the one currently
        # sounding is the previous one. Before the first render nothing has
        # been scheduled at all, and -1 % 4 would report the last beat of a
        # bar that has not started.
        beat = (self._beat_index - 1) % BEATS_PER_BAR if self._beat_index else 0
        remaining = (self._next_beat - self._pos) / period if period else 0.0
        phase = 1.0 - max(0.0, min(1.0, remaining))
        return beat, phase


class TapTempo:
    """BPM from the last few taps.

    Mean of the intervals, not the median: measured over 5000 trials at 128
    BPM with 15 ms of tap jitter, the mean is about twice as steady at every
    tap count (the median telescopes onto the two endpoints). Mean absolute
    error is 1.55 BPM at 4 taps, 0.92 at 6, 0.67 at 8.

    That is also why a tapped result should be shown rounded: 0.01 BPM at 128
    is 36.6 µs of period, which no human tap can resolve. The two decimals in
    the box exist for typed and dragged input.
    """

    MAX_TAPS = 8
    RESET_GAP_S = 2.0

    def __init__(self) -> None:
        self._taps: list[float] = []

    def tap(self, when: float) -> float | None:
        """Register a tap at *when* (seconds). Returns the estimate, or None
        for the first tap of a run — one tap is not an interval."""
        if self._taps:
            gap = when - self._taps[-1]
            intervals = self._intervals()
            # A long gap means a new count-in, not a very slow tempo. Both
            # tests matter: the absolute one catches a pause at any tempo, the
            # relative one catches a stumble at a fast one.
            if gap > self.RESET_GAP_S or (
                intervals and gap > 2.0 * statistics.mean(intervals)
            ):
                self._taps = []
        self._taps.append(when)
        self._taps = self._taps[-self.MAX_TAPS :]
        return self.bpm()

    def reset(self) -> None:
        self._taps = []

    def _intervals(self) -> list[float]:
        return [b - a for a, b in zip(self._taps, self._taps[1:])]

    def bpm(self) -> float | None:
        intervals = self._intervals()
        if not intervals:
            return None
        return 60.0 / statistics.mean(intervals)
