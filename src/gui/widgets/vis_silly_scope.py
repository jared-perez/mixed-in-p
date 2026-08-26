"""Silly Scope: a sheet of liquid gold, wiggled at its source like a garden hose.

The **backdrop** face of the ``backdrop_scope`` menu row, and the mode that
retired the chunky 152x64 retro trace that used to draw it. Backdrop-only, the
way fire is — the popout's ``oscilloscope`` keeps its green CRT
(:mod:`.vis_analog_scope`) and is a separate mode id.

**The model, in one line**: the stream is a garden hose. The *source*'s vertical
position wiggles with the averaged volume, that displacement travels along the
stream at a fixed flow speed, and what the wave carries is a **flat sheet**
shaded by its orientation — not a tube. The source sits at the right edge (the
newest audio) and the wave rolls left, taking ~:data:`_WINDOW_SECONDS` to cross.

That one decision is what buys the look cheaply. The silhouette is smooth *by
construction*, because it is the history of a smooth signal advected: there is
no per-edge turbulence machinery anywhere in here, and an earlier round that
had some produced spiky stalactites. Amplitude literally *is* volume dynamics —
a zero-mean band-passed loudness, so loud and dynamic music sends big swings
rolling across and quiet music leaves a nearly level sheet.

The pipeline, per frame, over a crop of the rows the sheet actually touches:

1. ``s = (y - centerline) / halfwidth`` — the across-sheet coordinate, -1..1.
2. A fake surface height ``z``: the **rolled-edge cross profile** (flat through
   the middle, rolling off over the outer third), a twist tilt, two drifting
   undulation sines, and the centerline's own pitch.
3. Normals from shifted differences, with the x-gradient scaled up against the
   y one — without that the sheet loses its side glints.
4. Shade from a **multi-band chrome environment ramp** indexed by the normal's
   vertical component: nine stacked features rather than three. It is a
   precomputed 1-D table, so *layers of contrast cost nothing per frame*, and
   that is the whole answer to "hard boundaries do not look like liquid" — a
   flat pool carries several gradations instead of one plateau and one step.
   On top: a marble perturbation of the *index* (which is what keeps a flat
   pool liquid), a sheet-only curvature term (the thin dark contour tracing
   every fold), a side glint, and a rim boost that **leans with the twist**.
   Then one 1-2-1 blur over the shade field, which is what dissolves the harsh
   band edges everywhere at once.
5. A gold ramp, and an alpha that fades out over the last pixel of the edge.

Why this shape and not another: a QPainterPath ribbon with gradient fills is
cheap and reads as *plastic*, because a gradient that does not follow the
surface curvature has no metallic banding; a real 2-D fluid sim is O(pixels x
iterations) and art-directs badly. The reference renders are about *shading*,
not turbulence.

Beat response is stamped at the source: the kick brightens what is leaving
the nozzle, that brightness rides the flow in a second history beside the
displacement's, and between beats the stream rests dimmer — so beats read as
bright surges travelling down a faded ribbon rather than as a strobe. (Two
earlier beat answers are retired: droplet sprites read as clutter next to
the sheet, and a whole-frame flicker blinked the picture without ever making
the stream *carry* the beat.) Under it sits the fractal's silence fade: a
saturating glow envelope — instant attack, exponential release — multiplies
the shade *and* the alpha, so the whole sheet dims to nothing in well under
a second without sound and snaps back the frame the music returns.

Every constant is expressed in **seconds**, never per frame. The backdrop only
ever runs at 33 ms, but ``scripts/vis_sheet.py`` can drive this at any rate and
a decay written per frame is a duration only at one of them.

No audio analysis lives here: :meth:`SillyScopeScene.render` takes the band
heights and the kick pulse :class:`~.vis_canvas.VisRenderer` already computes.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtGui import QColor, QImage

# ── Size and the frame budget ──────────────────────────────────────────────
# Cost is linear in pixels, as it is for the tunnels and the analog scope, and
# the cap is a frame budget. Measured on the M-series Mac against *this*
# pipeline, median of 80 frames:
#
#   760x320   (0.24 Mpx)   2.5 ms
#   912x384   (0.35 Mpx)   3.6 ms
#   1024x420  (0.43 Mpx)   4.3 ms
#   1216x512  (0.62 Mpx)   6.2 ms   <- the cap: a shade under the ~8 ms target
#   1400x590  (0.83 Mpx)   8.2 ms
#   1600x672  (1.08 Mpx)  10.7 ms
#
# Against a real decoded track through the real VisRenderer (which is what
# scripts/vis_sheet.py drives) the capped size measures 6.0 ms median, 6.5 p95.
#
# The backdrop's budget is the *host*: a 33 ms frame with ~11 ms of playlist
# repaint beside it, and the other backdrops spending 1-5 ms — so the target is
# ~8 ms. The proof of concept measured 7.7 ms where this measures 2.7 and put
# the cap at 0.30 Mpx on that basis; three things closed the gap and they are
# the reason the number moved rather than a free lunch. Only the rows the
# stream can touch are rendered (see _paint), and a 2.4:1 backdrop is mostly
# empty above and below it; everything stays float32, where the proof of
# concept's environment lookup silently went float64; and the final lookup uses
# the packed-uint32 trick with the alpha byte written over the word, which is
# the same move that took the analog scope's paint from 5.0 ms to 0.8. Raise it
# again only against another re-measure of this scene.
_BACKDROP_CAP_PX = 620_000
# There is no popout face today (see the module docstring). If one is ever
# offered the budget is *larger* — no row repaint — so the cap is stated rather
# than implied, exactly as the analog scope states the one it never meets.
_POPOUT_CAP_PX = 900_000
_MIN_W, _MIN_H = 96, 48
# For a host that never calls set_target_size at all.
_DEFAULT_SIZE = (912, 384)

# ── The hose ───────────────────────────────────────────────────────────────
# How long the wave takes to cross the window. Shipped at 10.0 and retuned
# four times on request, to ~0.5 s. Everything else in here is expressed in
# time, so each retune is this one number: the history still holds the same
# music per second, each feature just crosses faster (and sits
# proportionally wider on screen).
_WINDOW_SECONDS = 0.5
# Nozzle history resolution. In bins per *second* so the buffer holds the same
# stretch of music however often it is fed. Doubled from 20 when the crossing
# dropped to ~1.7 s, keeping a bin (width / (crossing * rate) pixels, ~18 px
# here) comfortably inside the centerline smoother's kernel — a bin wider
# than the smoother shows its smoothstep knots as facets.
_HISTORY_BINS_PER_S = 40.0
# Loudness followers. The difference of the two is the band-passed wiggle: the
# fast one tracks the phrase, the slow one is what it is measured against, so a
# steady loud passage sits still and a dynamic one swings.
_LEVEL_FAST_TAU = 0.45
_LEVEL_SLOW_TAU = 3.5
# How hard that difference throws the nozzle. It is **squashed**, not
# clipped: a hard clamp is reached constantly on loud music and turns the
# nozzle signal into a square wave, which advects into a stream with vertical
# walls and flat tops — measured, the centerline slope hit 6 px per px and the
# pitch term flipped sign pixel to pixel down every one of those walls, which
# is what the creases were.
_HOSE_GAIN = 8.0
# Overall level gates it, so quiet music barely wiggles the hose.
_PRESENCE_TAU = 1.2
_PRESENCE_KNEE = 0.34  # level at which the gate is fully open
# Vertical swing of the centerline, as a fraction of the image height. Tuned
# as a *pair* with _BASE_HALF_FRAC below, and against decoded audio rather than
# synthetic band heights — see the note there. Doubled from the shipped 0.24
# on request: the ribbon keeps its thickness, the wave just travels further,
# and a full-scale crest now brushes the frame edge — the row crop clips it,
# exactly as the stream running off the sides already does.
_SWING_FRAC = 0.48
# Smoothing over the nozzle history, in bins, and then over the sampled
# centerline, in pixels. Both are about the same thing: the pitch term
# amplifies any kink in the centerline into a vertical crease down the whole
# sheet, so the centerline has to be smooth before anything differentiates it.
_HISTORY_BLURS = 3
# The pixel-space smoother over the sampled centerline — expressed in
# **seconds of signal**, converted through the transport speed at the call
# site (sigma_px = seconds / _WINDOW_SECONDS * width), so it survives both a
# render-size change and a flow retune. It shipped as a width fraction
# (0.018), which is the same family of mistake as a decay written per frame:
# a fraction of the width is a duration only at one flow speed. At 10 s it
# meant 0.18 s of signal; by the 1.7 s crossing it meant 0.03 s, a real
# nozzle turnover spanned ~70 px, and every crest wore a visible corner —
# and doubling the bin rate did not touch it, because the kinks were the
# *signal*, not the knots. 0.06 s is the identity 0.018 * width at the
# 3.33 s window, i.e. exactly the smoothing the look was judged smooth at.
# Its original job is unchanged: the x-gradient (scaled by 0.2 * width for
# the side glints) multiplies the centerline's second difference by ~240 and
# paints any kink as vertical corduroy or a crease down the whole sheet.
_CENTER_SMOOTH_SECONDS = 0.06

# ── The sheet ──────────────────────────────────────────────────────────────
# Half-width at full flare, as a fraction of the image height — and it is a
# ratio against _SWING_FRAC rather than a size on its own. A wave whose swing
# is small next to the ribbon's own thickness reads as a *flat* ribbon with a
# texture on it, however hard the hose is working: measured against a real
# track, an 11% swing inside a 42%-thick ribbon looked motionless while the
# state underneath it was moving exactly as designed.
_BASE_HALF_FRAC = 0.17
# The twist: the sheet turns edge-on and back, which is the reference's
# pinch-and-flare. Waves across the window, plus a slow drift of its own so the
# pattern never repeats exactly against the flow. |cos| pinches TWICE per
# wave, so the on-screen pinch count is 2x this number — at the original
# 1.35 that was ~2.7 evenly spaced pinches, which read fine crossing in 10 s
# and read as beads on a string at 0.5 s. Fewer and shallower: about one
# pinch on screen, and the sheet keeps most of its width through it, so the
# silhouette is a long gently curved protrusion rather than a bulb.
_TWIST_WAVES = 0.45
_TWIST_DRIFT = 0.16  # radians per second
_TWIST_NARROW = 0.75  # half-width multiplier where the sheet is fully edge-on
# How flat silence leaves it: the multiplier on the half-width with no music.
_QUIET_WIDTH = 0.42

# The rolled-edge cross profile. Flat through the middle — which is what
# *preserves the broad pools* — and rolling off only in the outer third, where
# the normal then sweeps the whole environment ramp and several reflection
# bands stack compressed at the silhouette. That is the roundedness, and it
# needs no machinery of its own. A full-width sqrt tube instead paints a bright
# specular horizon along the whole axis, which reads as "one centre stream with
# colour drawn out to the sides" — the rejected round.
_ROLL_START = 0.70
_ROLL_HEIGHT = 0.30

_TILT = 0.44  # how far the twist tips the sheet across its width
# Stretched along the flow with the twist (they were 1.7 and 2.9): pools much
# shorter than the window slide past as repeating blobs at this speed, which
# is the same bead-reading the flare had.
_UND1 = (0.9, 0.42, 0.105)  # (waves across the window, waves across s, weight)
_UND2 = (1.6, -0.70, 0.072)
_UND_DRIFT1 = 0.055  # window-widths per second, on top of the flow
_UND_DRIFT2 = -0.038
_PITCH = 0.22  # how far the centerline's own slope tips the sheet
_PITCH_SENS = 2.2  # inside the squash, so a steep wave saturates rather than spikes

# Normals. The x-gradient stays scaled up against the y one or the sheet loses
# its side glints: z varies over the whole width but only over a fifth of the
# height, so equal weighting flattens everything along the flow.
_GRAD_X = 0.20
_GRAD_Y = 0.55

# ── The chrome environment ─────────────────────────────────────────────────
# A 1-D table indexed by the normal's vertical component: 0 is facing straight
# down, 1 straight up, 0.5 is a sheet lying flat. Nine stacked features, and
# they are free — the table is built once. This layout *is* the chrome-look
# knob; spending more layers here costs nothing per frame.
_ENV_BANDS = (
    # (centre, width, amplitude)
    (0.500, 0.055, 0.50),   # hot horizon core — where a flat sheet sits
    (0.437, 0.015, -0.42),  # the thin dark line hugging it: the chrome tell
    (0.655, 0.058, 0.24),   # secondary bright
    (0.820, 0.036, 0.19),   # sky streak
    (0.930, 0.022, 0.13),   # second sky streak
    (0.340, 0.052, -0.26),  # under-shadow
    (0.208, 0.068, 0.21),   # bounce light off the ground
    (0.078, 0.070, -0.20),  # deep ground dark
    (0.012, 0.030, 0.08),   # floor lift, so the darkest face is not flat black
)
# The base gradient the bands sit on. The floor is the dark-balance knob: the
# proof-of-concept pair differed in this alone, one dramatic with big dark
# faces and one at the reference's mostly-bright-gold balance. This is the
# bright one.
_ENV_FLOOR = 0.30
_ENV_SPAN = 0.44
_ENV_SIZE = 1024

# Marble: a slow drifting perturbation of the environment *index*, not of the
# height. Perturbing the index is what keeps a flat pool liquid — a genuinely
# flat sheet otherwise saturates the ramp over wide areas and renders as
# posterized paper, and flattening the ramp to fix that makes it worse.
# Elongated along the flow on purpose — several waves down the stream against
# less than one across it. Comparable counts on the two axes make a regular
# grid of lozenges that reads as chain-link rather than as reflection, which is
# the artificial-looking failure this pattern has.
_MARBLE = 0.052
_MARBLE_WAVES_X = 3.1
_MARBLE_WAVES_S = 0.85
_MARBLE_DRIFT_X = 0.045
_MARBLE_DRIFT_S = 0.21

# Curvature: the second difference of the vertical normal, darkening concave
# folds and lighting convex ridges — the thin contour that traces every pool
# boundary in the reference. It wants a broad radius: anything bead-sized put
# through it is shredded into speckle, which is why the retired droplets were
# sprites and why no small feature should ever share this shader.
_FOLD_GAIN = 0.55
_GLINT = 0.16  # cubed side glint from the horizontal normal
_RIM_START = 0.88
_RIM_GAIN = 0.34
_RIM_LEAN = 0.55  # the rim brightens on the edge the twist turns toward
# Passes of 1-2-1 over the shade field before the LUT. This is the harsh-line
# dissolver: it softens every band edge at once, wherever it came from.
_SHADE_BLURS = 1

# Gold. Fixed rather than following the waveform-colour setting: this is the
# one visual whose whole subject is the logo's liquid gold, so set_color exists
# and is deliberately ignored, exactly as the analog scope ignores it for green
# phosphor.
# Retinted toward yellow on request (the first cut read as orange): green
# sits closer under red through the body — G/R ~0.78 in the mids against the
# original ~0.70 — which is the yellow-gold axis, while the R >= G >= B
# ordering that keeps the ramp *gold* rather than grey still holds at every
# stop (and therefore everywhere, since the channels interpolate linearly
# between the same abscissae).
_GOLD_STOPS = (
    (0.00, (28, 17, 2)),
    (0.20, (118, 80, 8)),
    (0.42, (202, 156, 24)),
    (0.66, (243, 208, 62)),
    (0.85, (255, 240, 138)),
    (1.00, (255, 254, 238)),
)
_EDGE_AA_PX = 1.6  # how many pixels the silhouette fades out over

# ── The beat, stamped at the source ────────────────────────────────────────
# The kick brightens what is *leaving the nozzle*, and that brightness rides
# the flow exactly as the displacement does — a second history, sampled per
# column by the same math — so a beat is a bright surge travelling down the
# stream. The floor is the between-beats brightness, deliberately well below
# 1 or nothing reads as a surge (beatless music simply shows the dimmer
# resting ribbon); the peak is what a full kick stamps; the release is what
# lets a surge fade back to the floor well before the next kick at DJ
# tempos — at 0.06 s a 128 BPM kick's surge is long gone (e^(-0.47/0.06) is
# nothing), so each beat is one crisp band sweeping the ~0.5 s window.
# Brightness multiplies the shade only — the alpha belongs to the silence
# fade below, so the silhouette never pulses. The release was 0.18 and was
# cut 3x with the window: at half a second of crossing a 0.18 s tail was a
# third of the stream.
_BEAT_FLOOR = 0.50
_BEAT_PEAK = 1.35
_BEAT_RELEASE_TAU = 0.06
# The silence fade, the fractal's other half. Instant attack, exponential
# release: the sheet is at full strength the frame music plays and dims to
# nothing in ~0.7 s without it (started at the fractal's own 0.5 s tau, cut
# 3x on request). The knee saturates the envelope, so any music above a low
# level shows the sheet at full strength and the fade only speaks when the
# sound actually stops. It multiplies the shade AND the alpha: dimming the
# shade alone would leave an opaque near-black ribbon lying over the
# playlist rows.
_GLOW_KNEE = 0.25
_GLOW_RELEASE_TAU = 0.5 / 3.0


def build_env_ramp(size: int = _ENV_SIZE) -> np.ndarray:
    """The chrome environment: normal-up-ness -> shade, as a 1-D table."""
    t = np.linspace(0.0, 1.0, size)
    base = np.clip((t - 0.14) / 0.80, 0.0, 1.0)
    ramp = _ENV_FLOOR + _ENV_SPAN * (base * base * (3.0 - 2.0 * base))
    for centre, width, amp in _ENV_BANDS:
        ramp = ramp + amp * np.exp(-0.5 * ((t - centre) / width) ** 2)
    return np.clip(ramp, 0.0, 1.0).astype(np.float32)


def build_gold_lut() -> np.ndarray:
    """256 BGRA rows: deep amber -> body gold -> bright gold -> white.

    Straight (non-premultiplied) alpha like the fire renderer's, so the
    playlist grey composites correctly under the backdrop's 0.40 opacity. The
    alpha column is a placeholder — every pixel's real alpha comes from the
    sheet coordinate and is written over the packed word (see :meth:`_paint`).
    """
    t = np.linspace(0.0, 1.0, 256)
    stops = np.array([s[0] for s in _GOLD_STOPS])
    cols = np.array([s[1] for s in _GOLD_STOPS], dtype=np.float64)
    rgb = np.empty((256, 3))
    for channel in range(3):
        rgb[:, channel] = np.interp(t, stops, cols[:, channel])
    lut = np.empty((256, 4), dtype=np.uint8)
    lut[:, 0] = rgb[:, 2].astype(np.uint8)  # B
    lut[:, 1] = rgb[:, 1].astype(np.uint8)  # G
    lut[:, 2] = rgb[:, 0].astype(np.uint8)  # R
    lut[:, 3] = 255
    return lut


def _blur121(buf: np.ndarray, passes: int) -> np.ndarray:
    """Separable 1-2-1 blur, *passes* times in each direction.

    Edges keep their own value rather than being pulled toward an implicit
    black border, which would draw a dark line down a sheet that runs off the
    side of the frame — and it always does, at both ends.
    """
    out = buf
    for _ in range(passes):
        blurred = out.copy()
        blurred[:, 1:-1] = 0.25 * out[:, :-2] + 0.5 * out[:, 1:-1] + 0.25 * out[:, 2:]
        out = blurred
        blurred = out.copy()
        blurred[1:-1, :] = 0.25 * out[:-2, :] + 0.5 * out[1:-1, :] + 0.25 * out[2:, :]
        out = blurred
    return out


def _blur1d(values: np.ndarray, passes: int) -> np.ndarray:
    """1-2-1 along a single axis, ends held — for short arrays."""
    out = values
    for _ in range(passes):
        smoothed = out.copy()
        smoothed[1:-1] = 0.25 * out[:-2] + 0.5 * out[1:-1] + 0.25 * out[2:]
        out = smoothed
    return out


def _smooth1d(values: np.ndarray, sigma: float) -> np.ndarray:
    """Near-gaussian smoothing of a 1-D signal, at O(len) whatever the width.

    Three box passes, each a running mean taken from one cumulative sum, so a
    12 px kernel costs the same as a 2 px one — which matters because the
    kernel this wants is a fraction of the image width, and 1-2-1 passes to
    reach it would be a hundred of them. The ends are clamped rather than
    wrapped: the stream runs off both sides of the frame and always does.
    """
    if sigma < 0.5 or values.size < 8:
        return values
    radius = max(1, int(round(sigma * 0.85)))
    out = values.astype(np.float32)
    for _ in range(3):
        padded = np.concatenate((
            np.full(radius, out[0], dtype=np.float32),
            out,
            np.full(radius, out[-1], dtype=np.float32),
        ))
        cumulative = np.concatenate(([np.float32(0.0)], np.cumsum(padded, dtype=np.float32)))
        window = 2 * radius + 1
        out = ((cumulative[window:] - cumulative[:-window]) / window).astype(np.float32)
    return out


class SillyScopeScene:
    """The hose's history, the sheet it carries, and the image they paint."""

    def __init__(self) -> None:
        self._env = build_env_ramp()
        self._lut = build_gold_lut()
        # The same table packed one pixel to a word. Indexing a (256, 4) uint8
        # table with an (H, W) index gathers four separate bytes per pixel; the
        # (256,) uint32 view gathers one word for a byte-identical result, and
        # is what took the analog scope's paint from 5.0 ms to 0.8.
        self._lut32 = self._lut.view(np.uint32).reshape(256)
        self._dt = 33.0 / 1000.0
        self._level_fast = 0.0
        self._level_slow = 0.0
        self._presence = 0.0
        self.set_frame_interval(33.0)
        bins = int(round(_WINDOW_SECONDS * _HISTORY_BINS_PER_S)) + 2
        self._history = np.zeros(bins, dtype=np.float32)
        self._bright_history = np.full(bins, _BEAT_FLOOR, dtype=np.float32)
        self._bin_accum = 0.0
        self._prev_nozzle = 0.0
        self._prev_bright = _BEAT_FLOOR
        self._beat_glow = 0.0
        self._scroll = 0.0
        self._twist_phase = 0.0
        self._und_phase = [0.0, 0.0]
        self._marble_phase = [0.0, 0.0]
        self._pulse = 0.0
        self._glow = 0.0
        width, height = _DEFAULT_SIZE
        self._size = (width, height)
        self._image = QImage(width, height, QImage.Format.Format_ARGB32)
        self._image.fill(0)

    # ── Public API ─────────────────────────────────────────────────────────

    def image(self) -> QImage:
        return self._image

    def set_color(self, color: QColor | str) -> None:
        """Ignored on purpose — see :data:`_GOLD_STOPS`. Present so the
        renderer can forward the setting to every scene without asking which
        ones care.
        """

    def set_frame_interval(self, frame_ms: float) -> None:
        """Re-derive the per-frame follower alphas from the host's tick rate.

        Rate state only: :meth:`reset` must not touch it, because vis_sheet
        sets the interval *before* the mode, and setting the mode is what calls
        reset. Everything else in here is integrated against ``dt`` directly,
        so it needs no conversion at all.
        """
        if frame_ms <= 0:
            return
        self._dt = float(frame_ms) / 1000.0
        self._fast_alpha = float(np.exp(-self._dt / _LEVEL_FAST_TAU))
        self._slow_alpha = float(np.exp(-self._dt / _LEVEL_SLOW_TAU))
        self._presence_alpha = float(np.exp(-self._dt / _PRESENCE_TAU))
        self._glow_release = float(np.exp(-self._dt / _GLOW_RELEASE_TAU))
        self._beat_release = float(np.exp(-self._dt / _BEAT_RELEASE_TAU))

    def reset(self) -> None:
        """Forget the stream: the wave in flight and the phases."""
        self._history[:] = 0.0
        self._bright_history[:] = _BEAT_FLOOR
        self._bin_accum = 0.0
        self._prev_nozzle = 0.0
        self._prev_bright = _BEAT_FLOOR
        self._beat_glow = 0.0
        self._scroll = 0.0
        self._twist_phase = 0.0
        self._und_phase = [0.0, 0.0]
        self._marble_phase = [0.0, 0.0]
        self._level_fast = 0.0
        self._level_slow = 0.0
        self._presence = 0.0
        self._pulse = 0.0
        self._glow = 0.0
        width, height = self._size
        self._image = QImage(width, height, QImage.Format.Format_ARGB32)
        self._image.fill(0)

    def set_target_size(self, width: int, height: int, popout: bool = False) -> None:
        """Match the render size to the host's shape, capped by frame cost.

        *width* and *height* are **device** pixels, read from the widget that
        paints. The aspect is held exactly and the image is never made larger
        than the host asked for: there is nothing to gain from rendering a soft
        field the host then shrinks, and it upscales beautifully.
        """
        if width <= 0 or height <= 0:
            return
        cap = _POPOUT_CAP_PX if popout else _BACKDROP_CAP_PX
        scale = min(1.0, float(np.sqrt(cap / float(width * height))))
        target_w = max(_MIN_W, int(round(width * scale)))
        target_h = max(_MIN_H, int(round(height * scale)))
        if (target_w, target_h) == self._size:
            return
        self._size = (target_w, target_h)
        self._image = QImage(target_w, target_h, QImage.Format.Format_ARGB32)
        self._image.fill(0)

    def render(self, heights: np.ndarray | None, pulse: float = 0.0) -> QImage:
        """Advance the stream one frame and paint it.

        *heights* is the renderer's log-band array (``None`` or empty is
        silence, which is what the backdrop feeds after a pause: the envelope
        releases, the sheet thins toward a resting thread and the host's timer
        stops on a still frame — liquid settling, for free). *pulse* is the
        same kick accent the other modes read.
        """
        if heights is None or len(heights) == 0:
            level = 0.0
        else:
            # The fire/fractal blend: mean alone leaves a lone bass line nearly
            # invisible, max alone never breathes.
            level = float(np.clip(0.5 * heights.mean() + 0.6 * heights.max(), 0.0, 1.0))
        self._pulse = float(np.clip(pulse, 0.0, 1.0))
        self._advance(level)
        self._paint()
        return self._image

    # ── State ──────────────────────────────────────────────────────────────

    def _advance(self, level: float) -> None:
        """One frame of hose, twist and drift."""
        dt = self._dt
        self._level_fast = self._fast_alpha * self._level_fast + (1.0 - self._fast_alpha) * level
        self._level_slow = self._slow_alpha * self._level_slow + (1.0 - self._slow_alpha) * level
        self._presence = self._presence_alpha * self._presence + (1.0 - self._presence_alpha) * level
        gate = float(np.clip(self._presence / _PRESENCE_KNEE, 0.0, 1.0))
        # The silence fade's envelope: attack is the max, release the decay,
        # snapped to zero once it is below what an alpha byte can show.
        self._glow = max(
            float(np.clip(level / _GLOW_KNEE, 0.0, 1.0)),
            self._glow * self._glow_release,
        )
        if self._glow < 1.0 / 512.0:
            self._glow = 0.0
        # The beat envelope: instant attack on the kick, released fast enough
        # to reach the floor again before the next one (see _BEAT_RELEASE_TAU).
        self._beat_glow = max(self._pulse, self._beat_glow * self._beat_release)
        bright = _BEAT_FLOOR + (_BEAT_PEAK - _BEAT_FLOOR) * self._beat_glow
        nozzle = float(np.tanh(_HOSE_GAIN * (self._level_fast - self._level_slow)) * gate)

        # Push the nozzle into the history at a fixed rate in *time*, so the
        # buffer holds the same stretch of music however often it is fed — and
        # push the value it had **at the bin boundary**, interpolated, not the
        # value it happens to have at the end of whichever frame crossed it.
        # Without that the bins are sampled on the frame grid, so a 33 ms host
        # reads the nozzle up to 33 ms late while a 16 ms one reads it up to
        # 16, and on a fast attack the two disagree by more than the wiggle
        # they are recording. The bin rate being a time is not enough on its
        # own; what goes *into* the bin has to be a time as well.
        period = 1.0 / _HISTORY_BINS_PER_S
        self._bin_accum += dt
        while self._bin_accum >= period:
            self._bin_accum -= period
            across = 1.0 - min(self._bin_accum / dt, 1.0) if dt > 0.0 else 1.0
            self._history[:-1] = self._history[1:]
            self._history[-1] = self._prev_nozzle + (nozzle - self._prev_nozzle) * across
            self._bright_history[:-1] = self._bright_history[1:]
            self._bright_history[-1] = (
                self._prev_bright + (bright - self._prev_bright) * across
            )
        self._prev_nozzle = nozzle
        self._prev_bright = bright

        self._scroll += dt / _WINDOW_SECONDS
        self._twist_phase += _TWIST_DRIFT * dt
        self._und_phase[0] += _UND_DRIFT1 * dt
        self._und_phase[1] += _UND_DRIFT2 * dt
        self._marble_phase[0] += _MARBLE_DRIFT_X * dt
        self._marble_phase[1] += _MARBLE_DRIFT_S * dt

    def _sample_history(self, values: np.ndarray, width: int) -> np.ndarray:
        """A history -> one value per column, advected.

        ``v(x) = history(t - (W - x) / v)`` — the source is the right edge,
        where the newest audio is, and what it holds rolls left. The sub-bin
        phase is folded in so a feature slides smoothly rather than stepping
        at :data:`_HISTORY_BINS_PER_S`. Shared by the centerline and the
        beat's brightness, which is what keeps the two in exact phase.
        """
        bins = len(values)
        columns = np.arange(width, dtype=np.float32)
        age = (width - 1 - columns) / max(width - 1, 1) * _WINDOW_SECONDS
        index = (bins - 1) - (age - self._bin_accum) * _HISTORY_BINS_PER_S
        np.clip(index, 0.0, bins - 1.0, out=index)
        # Smoothed in *bins* — i.e. in time — rather than in pixels: a pixel
        # blur wide enough to matter would have to span several bins, and the
        # thing being smoothed is the signal, not the picture.
        history = _blur1d(values, _HISTORY_BLURS)
        # Interpolated with a smoothstep rather than linearly. That is not a
        # refinement: linear interpolation leaves a C1 kink at every bin
        # boundary, the pitch term turns each one into a vertical crease, and
        # at 20 bins a second across a 10 s window that is a crease every few
        # pixels down the whole sheet. Smoothstep is C1 at the knots, so the
        # creases cannot form in the first place.
        base = np.floor(index).astype(np.int32)
        np.clip(base, 0, bins - 2, out=base)
        frac = (index - base).astype(np.float32)
        frac = frac * frac * (3.0 - 2.0 * frac)
        sampled = history[base] * (1.0 - frac) + history[base + 1] * frac
        return _smooth1d(
            sampled.astype(np.float32),
            _CENTER_SMOOTH_SECONDS / _WINDOW_SECONDS * width,
        )

    def _centerline(self, width: int, height: int) -> np.ndarray:
        """Where the sheet's middle sits in each column: the nozzle's history."""
        offsets = self._sample_history(self._history, width)
        return (0.5 * height + offsets * _SWING_FRAC * height).astype(np.float32)

    def _brightline(self, width: int) -> np.ndarray:
        """The brightness each column's material left the nozzle with."""
        return self._sample_history(self._bright_history, width)

    # ── Paint ──────────────────────────────────────────────────────────────

    def _paint(self) -> None:
        width, height = self._size
        centre = self._centerline(width, height)
        columns = np.arange(width, dtype=np.float32)
        u = columns / width + self._scroll  # scroll-space: a feature holds its u

        twist = (2.0 * np.pi * _TWIST_WAVES * u + self._twist_phase).astype(np.float32)
        sin_twist = np.sin(twist)
        flare = _TWIST_NARROW + (1.0 - _TWIST_NARROW) * np.abs(np.cos(twist))
        quiet = _QUIET_WIDTH + (1.0 - _QUIET_WIDTH) * float(
            np.clip(self._presence / _PRESENCE_KNEE, 0.0, 1.0)
        )
        half = (_BASE_HALF_FRAC * height * flare * quiet).astype(np.float32)
        np.maximum(half, 1.5, out=half)

        # Only the rows the sheet can touch are rendered; the rest stays
        # transparent, which is a real saving because a 2.4:1 backdrop is
        # mostly empty above and below the stream.
        low = int(max(0, np.floor(np.min(centre - half)) - 2))
        high = int(min(height, np.ceil(np.max(centre + half)) + 3))
        bgra = np.zeros((height, width, 4), dtype=np.uint8)
        if high > low and self._glow > 0.0:
            rows = np.arange(low, high, dtype=np.float32)
            self._paint_sheet(
                bgra[low:high], rows, centre, half, u, sin_twist,
                self._brightline(width),
            )
        self._image = QImage(
            bgra.tobytes(), width, height, width * 4, QImage.Format.Format_ARGB32
        ).copy()

    def _paint_sheet(
        self,
        out: np.ndarray,
        rows: np.ndarray,
        centre: np.ndarray,
        half: np.ndarray,
        u: np.ndarray,
        sin_twist: np.ndarray,
        bright: np.ndarray,
    ) -> None:
        width = len(centre)
        s = (rows[:, None] - centre[None, :]) / half[None, :]
        absr = np.abs(s)

        # 1. The rolled-edge cross profile: flat through the middle (which is
        #    what keeps the broad pools), rolling off over the outer third.
        roll = np.clip((absr - _ROLL_START) / (1.0 - _ROLL_START), 0.0, 1.0)
        z = _ROLL_HEIGHT * np.sqrt(np.maximum(1.0 - roll * roll, 0.0))
        # 2. The twist tips the sheet across its width.
        z += s * (_TILT * sin_twist)[None, :]
        # 3. Two gentle undulations drifting with the flow — the broad pools.
        for (wx, ws, weight), phase in zip((_UND1, _UND2), self._und_phase):
            z += weight * np.sin(
                2.0 * np.pi * (wx * u[None, :] + ws * s) + 2.0 * np.pi * phase
            )
        # 4. The centerline's own slope, squashed so a steep wave saturates
        #    rather than spiking.
        # No smoothing of its own: the centerline it differentiates has
        # already been through _smooth1d at a width-proportional kernel, and a
        # blur written as a *pass count* on top of that would be one more
        # constant that is only right at one render size — measured, it moved
        # 0.1% of the frame.
        pitch = np.tanh(np.gradient(centre) * _PITCH_SENS).astype(np.float32)
        z += (_PITCH * pitch)[None, :]

        z = z.astype(np.float32)
        nx, ny = self._normals(z, width, out.shape[0])

        # The environment index, marbled: perturbing the *index* is what keeps
        # a flat pool liquid, where perturbing the height only moves the pool.
        index = 0.5 * (ny + 1.0)
        marble = np.sin(
            2.0 * np.pi * (_MARBLE_WAVES_X * u + self._marble_phase[0])
        ).astype(np.float32)[None, :] * np.sin(
            2.0 * np.pi * (_MARBLE_WAVES_S * s + self._marble_phase[1])
        )
        index += _MARBLE * marble
        np.clip(index, 0.0, 1.0, out=index)
        shade = self._env[(index * (_ENV_SIZE - 1)).astype(np.int32)]

        # Curvature: dark concave folds, bright convex ridges — the contour
        # that traces every pool boundary.
        shade = shade + _FOLD_GAIN * self._curvature(ny)
        # A side glint, cubed so it is a glint and not a wash.
        shade += _GLINT * (nx ** 3)
        # The rim, leaning: brighter on the edge the twist turns toward, dimmer
        # on the other. That lean is what makes the to-and-fro read as a plane
        # turning in depth rather than as a flat band changing width.
        rim = np.clip((absr - _RIM_START) / (1.0 - _RIM_START), 0.0, 1.0) ** 2
        shade += _RIM_GAIN * rim * (1.0 + _RIM_LEAN * sin_twist[None, :] * np.sign(s))
        # The beat rides the stream: each column wears the brightness its
        # material left the nozzle with, times the silence fade. Shade only —
        # the alpha keeps the silhouette (see _BEAT_FLOOR).
        shade *= (self._glow * bright)[None, :]
        np.clip(shade, 0.0, 1.0, out=shade)
        shade = _blur121(shade, _SHADE_BLURS)

        packed = self._lut32[(shade * 255.0).astype(np.uint8)]
        view = packed.view(np.uint8).reshape(packed.shape[0], width, 4)
        alpha = np.clip((1.0 - absr) * half[None, :] / _EDGE_AA_PX, 0.0, 1.0)
        if self._glow < 1.0:
            alpha *= self._glow
        view[..., 3] = (alpha * 255.0).astype(np.uint8)
        out[:] = view

    @staticmethod
    def _normals(z: np.ndarray, width: int, rows: int) -> tuple[np.ndarray, np.ndarray]:
        """Unit normal's x and y components from shifted central differences.

        The gradients are scaled by the image's own dimensions, so the look is
        resolution-independent: z varies over the whole width but only over a
        fifth of the height, and equal weighting flattens the sheet along the
        flow until its side glints disappear.
        """
        gx = np.empty_like(z)
        gx[:, 1:-1] = 0.5 * (z[:, 2:] - z[:, :-2])
        gx[:, 0] = z[:, 1] - z[:, 0]
        gx[:, -1] = z[:, -1] - z[:, -2]
        gy = np.empty_like(z)
        if rows >= 3:
            gy[1:-1, :] = 0.5 * (z[2:, :] - z[:-2, :])
            gy[0, :] = z[1, :] - z[0, :]
            gy[-1, :] = z[-1, :] - z[-2, :]
        else:
            gy[:] = 0.0
        nx = -gx * (_GRAD_X * width)
        ny = -gy * (_GRAD_Y * rows)
        inv = 1.0 / np.sqrt(nx * nx + ny * ny + 1.0)
        return nx * inv, ny * inv

    @staticmethod
    def _curvature(ny: np.ndarray) -> np.ndarray:
        """Second difference of the vertical normal, in both directions."""
        curv = np.zeros_like(ny)
        curv[:, 1:-1] += ny[:, :-2] + ny[:, 2:] - 2.0 * ny[:, 1:-1]
        if ny.shape[0] >= 3:
            curv[1:-1, :] += ny[:-2, :] + ny[2:, :] - 2.0 * ny[1:-1, :]
        return curv

