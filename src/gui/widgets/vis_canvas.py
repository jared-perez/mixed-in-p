"""Classic-style audio visualizer rendering, popout canvas, and popout window.

Retro visuals rendered into an internal QImage and upscaled by the host with
fast (non-smooth) transformation for a chunky pixel look:

- ``oscilloscope`` — a green phosphor CRT: host-resolution, glow and
  persistence, 60 fps in the popout (see :mod:`.vis_analog_scope`). It used to
  be the one mode with **two faces**, wearing a chunky 152x64 retro trace in
  the playlist backdrop and the CRT in the popout, chosen by the ``popout``
  flag ``set_target_size`` carries. The retro face is gone and the CRT is now
  offered in *both* halves of the menu — ``backdrop_oscilloscope`` behind the
  playlist rows, ``oscilloscope`` in the popout — which is one picture drawn
  to whichever host asks, not two faces returning. The ``popout`` flag still
  travels, but it now only picks an area cap and a frame rate.
- ``stream`` — a sheet of liquid gold wiggled at its source like a garden
  hose (see :mod:`.vis_stream`). Backdrop only, which is fire's shape from
  the other end, and the reason it is a *separate mode id* rather than a third
  face: two faces of one id was the arrangement that just ended, and the menu
  row that selects it (``backdrop_scope``) keeps its own id and needs no
  migration either way.
- ``spectrum`` — log-banded FFT bars with instant attack, linear falloff and
  peak-hold caps that drop with accelerating speed.
- ``fire`` — the classic heat-propagation fire effect (blur, cool, rise),
  stoked from the bottom row by the same log-band energies *through a bed of
  embers*: a few persistent hot spots that wander along the width, each
  feeding one tongue that narrows to a point as it rises. Stoking every
  column by the smooth band curve alone gave horizontal bands, not flames
  (see ``_render_fire``).
- ``fractal`` — **labelled "J Fractal"**: a spinning escape-time Julia set
  (the Mandelbrot family). The Julia constant orbits the classic radius so the
  branches continuously morph between dendrites and spirals; overall level
  drives morph/spin speed and brightness, and the kick pulse punches the zoom.
- ``fractal_power`` — **labelled "Tri Fractal"**: the same orbit, camera and
  fade, iterating a blend of ``z²`` and ``z³`` instead of ``z²`` alone. The
  blend weight rides the orbit phase, so the figure morphs between two-fold
  and three-fold symmetry — chunky lobed bodies with a bright fringe — for
  two multiplies and a lerp, no fractional powers.
- ``fractal_trap`` — **labelled "Blade Fractal"**: the Julia orbit coloured by
  an *orbit trap* — how close each pixel's orbit ever comes to the real and
  imaginary axes — instead of by escape time. Glowing blades and filaments
  rather than dendrites, from the math already tuned for ``fractal``. Its
  *fullness* follows the music: a kick shows the shape thick and full, and
  between kicks it thins to a skeleton of the same shape.
- ``loop_tunnel`` — **labelled "Tunnel chase"**: a wireframe tunnel flown
  along a closed 3-D loop, with pixelated stars streaming past. The odd one
  out: it draws antialiased lines into its own larger, host-shaped image (see
  :mod:`.vis_loop_tunnel`) rather than the shared low-res grid, because its
  cost is O(lines) not O(pixels).
- ``beat_tunnel`` — **labelled "Wormhole"**, its sibling flown to the beat: the tunnel is
  generated ahead of the camera, turns on the first beat of every bar, and
  wears a wall of translucent nebula cloud rather than a wireframe (see
  :mod:`.vis_beat_tunnel`). It is the only mode that *counts beats*, so it is
  also the only one with a tempo (:mod:`.beat_clock`), a per-mode frame rate
  (60 fps in the popout) and a smooth upscale rather than chunky pixels.

The rendering lives in :class:`VisRenderer` (no widget), shared by two hosts:
the popout :class:`VisCanvas`, and the Player playlist's backdrop (which blits
the frames dimmed behind the rows). Frames use a transparent background so the
backdrop composites over the playlist grey; the popout fills black first, which
looks identical to drawing opaque.

All constants are original reimplementations informed by publicly documented
behaviour of classic visualizers (see docs/visualizations-plan.md); nothing is
derived from proprietary sources. DSP is plain numpy on ~2048-sample blocks —
well under a millisecond per frame.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..styles.theme import Theme
from .beat_clock import BeatClock
from .vis_analog_scope import AnalogScopeScene
from .vis_beat_tunnel import BeatTunnelScene
from .vis_loop_tunnel import LoopTunnelScene
from .vis_stream import StreamScene

# Internal render resolution; hosts scale it up without smoothing.
_W, _H = 152, 64
FRAME_MS = 33  # ~30 fps
# Two modes run at 60 in the popout, for unrelated reasons — which is why this
# is named for the rate and not for either of them. The beat tunnel needs it to
# be *right*: at 33 ms the kick flux is too coarse for the beat clock to lock
# as tightly (measured). The analog scope needs it to be *smooth*: it is a
# moving line filling a window, and the phosphor decay is what a frame's worth
# of judder shows up in. The backdrop stays at FRAME_MS whatever the mode — see
# PlayerPanel's tick timer.
FAST_FRAME_MS = 16
FFT_SIZE = 2048
_N_BARS = 19
_BAR_W = _W // _N_BARS  # px per bar incl. 1px gap
_DB_FLOOR = -65.0
# Bar ballistics per frame (normalized 0..1 units): instant attack, linear
# release; peak caps hold then fall with multiplicative acceleration.
_BAR_FALL = 0.22
_PEAK_START = 0.05
_PEAK_ACCEL = 1.1
_FIRE_STOKE_GAIN = 1.25
# Fire. What the propagation makes is decided by the *source*: every column
# of the bottom row stoked by the same smooth band curve gave horizontal bands
# of heat rising in step (one per frame of band energy), which read as ripples
# on water however they were bent. Flames are tongues, and a tongue needs a
# hot spot that stays put for a while: the bottom row is the band curve times
# an ember bed — two 1-D value-noise layers drifting in opposite directions,
# multiplied, so a handful of spots wander slowly along the width. Each
# spot's heat then narrows as it rises, because the blur spreads it and the
# cooling clips the thin edges first: the flame dissipates into its hottest
# point. The band curve itself is released slowly so a loud frame does not
# stamp a bright row across every tongue.
_FIRE_EMBER_CELLS = (9, 14)  # px per noise cell, the two layers
_FIRE_EMBER_DRIFT = (3.6, -2.4)  # px/s each layer drifts
_FIRE_EMBER_FLOOR = 0.2  # fraction of the band heat every column gets (the bed)
_FIRE_EMBER_NORM = 0.5  # noise product at which a spot is fully hot
_FIRE_EMBER_POWER = 1.4  # >1 sharpens the spots
_FIRE_STOKE_RELEASE = 0.9  # per FRAME_MS: the band curve's fall between hits
# A surge that lifts every column in the same frame rises as a shelf — a
# horizontal edge at one height across every tongue, because the field moves
# up in lock-step. So the band curve *attacks* per column: the hottest embers
# take a rise almost at once, the bed takes it over ~15 frames, a static
# per-patch jitter spreads the rest, and the edge lands at a different row in
# every tongue. The kick accent goes through a follower for the same reason:
# a one-frame gain stamped a thin bright line; released over ~half a second it
# lifts a tongue and lets it settle. Attack and release are per FRAME_MS,
# rescaled in set_frame_interval.
_FIRE_ATTACK_SLOW = 0.07
_FIRE_ATTACK_FAST = 0.6
_FIRE_ATTACK_POWER = 1.5  # how sharply the fast attack belongs to the hottest spots
_FIRE_ATTACK_JITTER = 0.45  # ± fraction, per patch of ~5 px
_FIRE_KICK_RELEASE = 0.93
# Height. Cooling per row grows with height (quadratic in rows above the
# base, scaled to _FIRE_REACH), so the body burns slowly and the last stretch
# cools fast; the old flat 0.028/row died 36 rows up and never cleared half
# the playlist. Alpha wears a vertical envelope, full below _FIRE_FADE_LO and
# gone by _FIRE_FADE_HI, so the fade-out is the same gradual curve whatever
# the track is doing, and the rows above it stay clean. Measured over a real
# track composited on playlist rows at the backdrop's 0.40: visible reach p50
# 41 rows, max 47 of 64, every row still readable.
_FIRE_COOL_BASE = 0.012
_FIRE_COOL_TOP = 0.018
_FIRE_REACH = 48.0  # rows: the 3/4 mark the cooling curve is scaled to
_FIRE_VERTICAL_BLEND = 0.25  # weight of the cell two rows below in the blur
_FIRE_FADE_LO = 0.6  # of _H, from the bottom
_FIRE_FADE_HI = 0.9
_FIRE_ALPHA_GAIN = 2.2
# Sway: a wind. The blur's side weights are biased by a value that swings
# with time and twists up the height, so heat drifts left then right as it
# rises and a tongue leans and bends. Zero at the base (anchored), full from
# a third of the way up. Per *column*, not per row: one wind for the whole
# width leaned every tongue the same way at once, which looked like a stage
# effect, so each patch of the width has its own phase (static, random) and
# its own rate — slower on the hottest embers, since a big flame moves
# slower than a small one — and neighbouring tongues cross. Rates are
# radians per *second*. A display-time warp of the field was tried first and
# shipped for a day: it bent the bands into travelling waves, which looked
# like rippled water.
_FIRE_WIND_AMP = 1.0  # side-weight bias at full swing (1.0 = one side gets 2/3)
_FIRE_WIND_RATE_BED = 2.6  # rad/s on the bed, ~2.4 s per full sway
_FIRE_WIND_RATE_HOT = 1.2  # rad/s on the hottest ember, ~5 s
_FIRE_WIND_TWIST = 0.7  # turns of phase from base to top: a bend, not a tilt
# Fractal (Julia set) tuning. The constant moves on the classic morphing-Julia
# circle |c| = 0.7885, but swings back and forth through the arc around angle π
# (measured sweep: the sets there are rich branches/spirals) instead of
# circling through the near-empty dust zone around angle 0. The view plane
# spins and the kick pulse punches a momentary zoom.
_JULIA_ITERATIONS = 26
_JULIA_ORBIT_RADIUS = 0.7885
_JULIA_ORBIT_SWING = 2.2  # max angular deviation from π on the c-circle
_JULIA_VIEW_SPAN = 3.1  # complex-plane width of the (pre-zoom) viewport
_JULIA_SPIN_BASE = 0.006  # radians/frame with no audio
_JULIA_SPIN_LEVEL = 0.045  # extra spin at full level
_JULIA_MORPH_BASE = 0.002  # c-orbit advance per frame (silence)
_JULIA_MORPH_LEVEL = 0.022  # extra orbit speed at full level
_JULIA_KICK_ZOOM = 0.14  # fraction of zoom-in on a full-strength kick
# Tri Fractal: the z² ↔ z³ blend weight swings with the orbit phase at its own
# rate, so the symmetry order and the Julia constant never repeat in step.
_POWER_BLEND_RATE = 1.7
# Blade Fractal. The trap is the two axes; intensity is exp(-distance *
# falloff), and *falloff* is the one scalar the music moves: 3.5 is the shape
# at its fullest (a wide soft glow around every blade), 18 the same shape as a
# thin skeleton. Below ~18 the lines go sub-pixel at 152x64 and shimmer as the
# view turns (measured on the contact sheet — the fix would be resolution, not
# tuning). Fullness is mostly the kick, not the level: level barely dips
# between the kicks of real music, so a level-led mix held the shape two-thirds
# full and left the beat nothing to swell into.
_TRAP_FALLOFF_FULL = 3.5
_TRAP_FALLOFF_THIN = 18.0
_TRAP_FULL_BASE = 0.05
_TRAP_FULL_LEVEL = 0.45
_TRAP_FULL_KICK = 0.55
# The kick detector collapses a frame or two after the transient, so the raw
# pulse strobes; this follower's release is the "in and out" of the swell.
_TRAP_KICK_RELEASE = 0.75  # per 33 ms: halfway down ~100 ms after the kick
# Brightness is a gate on level, not a multiple of it: thin lines are already
# dim (low on the ramp, and the alpha follows intensity), so a brightness that
# fell as fast as the shape thinned meant the skeleton was never seen. The
# gate holds brightness while the shape thins after the music stops, then drops
# it out — skeleton at ~0.7 s, gone by ~1.4 s.
_TRAP_GATE_LO = 0.03
_TRAP_GATE_HI = 0.25
# Kick flux (the beat tunnel's feature): the half-wave-rectified rise in
# 50-120 Hz energy, *gated* by the broadband log-spectral flux — a kick has a
# click and a bass note does not, which is what separates the two on a track
# whose bass line sits between the kicks. Each term is normalised by its own
# slow peak follower, since the app cannot take the 99th percentile of a clip
# it has not heard yet.
_FLUX_PEAK_DECAY_AT_60FPS = 0.995  # ~3 s memory of "how big does this get"
_PULSE_ATTACK = 0.97  # per 33 ms: a ~1.1 s time constant on the bass average

RENDER_MODES = (
    "oscilloscope", "spectrum", "fire", "fractal", "fractal_power", "fractal_trap",
    "loop_tunnel", "beat_tunnel", "stream",
)
# The three modes that share the Julia driver (orbit, camera, fade, palette)
# and differ only in what each pixel computes on the grid.
FRACTAL_MODES = ("fractal", "fractal_power", "fractal_trap")
# What the popout window offers, which is no longer everything the renderer can
# draw: fire was retired from the menu's popout half and kept as a backdrop,
# where it reads as lit rows rather than as the whole window, and the stream
# was only ever a backdrop. So a mode may render and not be offered —
# never the other way round, which is derived here rather than written out so a
# new render mode cannot be silently unreachable.
_BACKDROP_ONLY = {"fire", "stream"}
POPOUT_MODES = tuple(m for m in RENDER_MODES if m not in _BACKDROP_ONLY)


def _fire_palette(color: QColor) -> np.ndarray:
    """256 RGB rows: a heat ramp of *color* — black → color → white.

    The classic red/orange fire is exactly this ramp for pure red; deriving it
    from the waveform color instead ties the flames to the same setting as the
    other visuals. Rebuilt only on color change; per-frame cost (a LUT lookup)
    is unaffected by the palette's contents.
    """
    t = np.linspace(0.0, 1.0, 256)[:, None]
    base = np.array([color.red(), color.green(), color.blue()], dtype=np.float64)
    up = np.clip(t / 0.6, 0.0, 1.0)  # black → color over the cooler range
    hot = np.clip((t - 0.6) / 0.4, 0.0, 1.0)  # color → white at the hottest
    rgb = base * up
    rgb = rgb + (255.0 - rgb) * hot
    return rgb.astype(np.uint8)


def _value_noise_1d(length: int, cell: int, seed: int) -> np.ndarray:
    """1-D value noise in 0..1 that tiles at *length*, cosine-interpolated.

    The fire's ember bed. Random control points every *cell* pixels, so the
    spots are that wide; built once per layer, and a drifting window over it
    is what makes them wander.
    """
    rng = np.random.default_rng(seed)
    points = max(2, length // cell)
    grid = rng.uniform(0.0, 1.0, points)
    xs = np.arange(length) / cell
    i0 = np.floor(xs).astype(int) % points
    i1 = (i0 + 1) % points
    f = 0.5 - 0.5 * np.cos(np.pi * (xs - np.floor(xs)))
    return (grid[i0] * (1.0 - f) + grid[i1] * f).astype(np.float32)


class VisRenderer:
    """Renders one visualization mode from mono sample blocks into a QImage."""

    def __init__(self) -> None:
        self._mode: str = "spectrum"
        self._color = QColor(Theme.WAVEFORM_DEFAULT)
        self._image = QImage(_W, _H, QImage.Format.Format_ARGB32)
        self._image.fill(Qt.GlobalColor.transparent)
        self._window = np.hanning(FFT_SIZE).astype(np.float32)
        self._band_slices: list[slice] | None = None
        self._band_sr: int = 0
        # Ballistics state (normalized 0..1 per bar).
        self._bars = np.zeros(_N_BARS, dtype=np.float64)
        self._peaks = np.zeros(_N_BARS, dtype=np.float64)
        self._peak_vel = np.full(_N_BARS, _PEAK_START, dtype=np.float64)
        self._heat = np.zeros((_H, _W), dtype=np.float32)
        self._fire_lut = _fire_palette(self._color)
        # Per-row fire profiles, built once, for rows 0..H-2 (the row above
        # the stoked one is the last computed): cooling, the wind's amplitude
        # and phase twist; the alpha envelope for all H rows; the ember noise
        # layers (three widths long, so a drifting window never wraps
        # visibly); and the fire's clock, in seconds.
        above = (np.arange(_H - 1)[::-1] + 1).astype(np.float32)[:, None]
        self._fire_cool = _FIRE_COOL_BASE + _FIRE_COOL_TOP * (above / _FIRE_REACH) ** 2
        self._fire_wind_amp = _FIRE_WIND_AMP * np.clip(above / _H * 2.5, 0.0, 1.0)
        twist = 2.0 * np.pi * _FIRE_WIND_TWIST * above / _H
        self._fire_twist_sin = np.sin(twist)
        self._fire_twist_cos = np.cos(twist)
        # Each patch's own sway phase: value noise with cells the width of a
        # tongue, over a full turn, so a tongue sways as one and its
        # neighbour is anywhere in the cycle.
        self._fire_wind_phase = 2.0 * np.pi * _value_noise_1d(_W, 16, 32)
        height = (_H - np.arange(_H)).astype(np.float32)[:, None] / _H  # of each row, 1/H..1
        fade = np.clip((height - _FIRE_FADE_LO) / (_FIRE_FADE_HI - _FIRE_FADE_LO), 0.0, 1.0)
        self._fire_fade = 1.0 - fade * fade * (3.0 - 2.0 * fade)
        self._fire_embers = tuple(
            _value_noise_1d(_W * 3, cell, seed) for cell, seed in zip(_FIRE_EMBER_CELLS, (21, 22))
        )
        self._fire_stoke = np.zeros(_W, dtype=np.float32)
        self._fire_release = _FIRE_STOKE_RELEASE
        self._fire_kick_release = _FIRE_KICK_RELEASE
        self._fire_frame_ratio = 1.0
        self._fire_kick: float = 0.0
        # The attack jitter: random per column, smoothed twice over ±2 px so
        # it is per patch, normalised to ±1, then scaled by the constant.
        jitter = np.random.default_rng(31).uniform(-1.0, 1.0, _W).astype(np.float32)
        for _ in range(2):
            jitter = sum(np.roll(jitter, k) for k in range(-2, 3)) / 5.0
        self._fire_jitter = 1.0 + _FIRE_ATTACK_JITTER * jitter / max(float(np.abs(jitter).max()), 1e-6)
        self._fire_time: float = 0.0
        # Beat pulse (Milkdrop-style): instantaneous bass energy against its
        # own smoothed average. Chosen over a precomputed librosa onset
        # envelope because heavy DSP during playback fights the audio callback
        # for the GIL (the same reason the player suppresses prefetch-decode
        # while playing); this is a few numpy ops per frame.
        self._bass_att: float = 0.0
        self._pulse: float = 0.0
        # Fractal state: view rotation, c-orbit phase, and a fast-attack /
        # slow-release level follower so the image fades out over silence.
        self._fract_angle: float = 0.0
        self._fract_phase: float = 0.0
        self._fract_level: float = 0.0
        # Blade Fractal's kick follower, and its release rescaled to the frame
        # interval (see set_frame_interval).
        self._trap_kick: float = 0.0
        self._trap_release = _TRAP_KICK_RELEASE
        # Pixel → complex-plane grid, built once (square pixels, centered).
        xs = np.linspace(-0.5, 0.5, _W) * _JULIA_VIEW_SPAN
        ys = np.linspace(-0.5, 0.5, _H) * (_JULIA_VIEW_SPAN * _H / _W)
        self._fract_grid = (xs[None, :] + 1j * ys[:, None]).astype(np.complex64)
        # Loop tunnel state, including its own image. Cheap to construct — the
        # loop path is built on its first render, not here.
        self._loop_tunnel = LoopTunnelScene()
        # Beat tunnel: its own image again, plus a beat clock. Both cheap to
        # build; the path is generated on the first render.
        self._beat_tunnel = BeatTunnelScene()
        self._clock = BeatClock(FRAME_MS / 1000.0)
        self._frame_ms: float = FRAME_MS
        self._bass_alpha = _PULSE_ATTACK
        # Kick-flux state and the three peak followers that normalise it.
        self._kick_flux: float = 0.0
        self._bass: float = 0.0
        self._prev_bass: float = 0.0
        self._prev_log: np.ndarray | None = None
        self._flux_peaks = np.zeros(3)
        self._flux_decay = _FLUX_PEAK_DECAY_AT_60FPS
        # The popout's face of the oscilloscope, and the flag that selects it.
        # Trustworthy by construction: VisCanvas.feed passes popout=True before
        # every render, and the backdrop's own VisRenderer instance never does.
        self._analog_scope = AnalogScopeScene()
        self._popout = False
        # The backdrop's scope slot. Its own image again, and cheap to build:
        # the LUTs and the bead sprites, nothing per-frame.
        self._stream = StreamScene()

    # ── Public API ─────────────────────────────────────────────────────────

    def image(self) -> QImage:
        if self._mode == "oscilloscope":
            return self._analog_scope.image()
        if self._mode == "stream":
            return self._stream.image()
        if self._mode == "loop_tunnel":
            return self._loop_tunnel.image()
        if self._mode == "beat_tunnel":
            return self._beat_tunnel.image()
        return self._image

    def frame_ms(self) -> int:
        """How often this mode wants to be advanced, in milliseconds.

        Only the popout acts on it. The playlist backdrop stays at FRAME_MS
        whatever the mode, because its cost is the *host*: repainting the
        visible rows behind the frame measures ~11 ms on its own, and at 60 fps
        that alone would be two-thirds of a core. That is also why this asks
        only the mode and not the host: the answer the backdrop would get is
        one it never reads.
        """
        return FAST_FRAME_MS if self._mode in ("beat_tunnel", "oscilloscope") else FRAME_MS

    def smooth_upscale(self) -> bool:
        """Whether the host should interpolate when scaling this mode up.

        The retro modes are meant to look like big pixels. Both tunnel modes
        are drawn near the host's own size, antialiased, so a
        nearest-neighbour blow-up would undo the thing they render large for —
        it is what made the loop tunnel read as a staircase. Measured at 0.4 ms for
        a full-frame upscale, i.e. free.

        The oscilloscope's glow field would staircase once the area cap bites,
        and the stream is a soft liquid field rendered near the host's own
        size — nearest-neighbour on either would undo the thing they render
        large for. This used to answer for the oscilloscope's *host* rather
        than for the mode, because the backdrop's face was the chunky grid;
        that face is gone, so the question is a per-mode one again.
        """
        return self._mode in ("beat_tunnel", "loop_tunnel", "oscilloscope", "stream")

    def set_frame_interval(self, frame_ms: float) -> None:
        """Tell the renderer how often it is being advanced.

        Every decay in here is a *time* constant wearing a per-frame number:
        the bass average's 0.97, the star glow's 0.82, the beat clock's gain
        and histogram decays. Left alone, the popout at 16 ms would behave
        differently from the backdrop at 33 in ways that look like tuning.
        """
        if frame_ms <= 0:
            return
        self._frame_ms = float(frame_ms)
        self._bass_alpha = _PULSE_ATTACK ** (frame_ms / FRAME_MS)
        self._flux_decay = _FLUX_PEAK_DECAY_AT_60FPS ** (frame_ms / (1000.0 / 60.0))
        self._trap_release = _TRAP_KICK_RELEASE ** (frame_ms / FRAME_MS)
        self._fire_frame_ratio = frame_ms / FRAME_MS
        self._fire_release = _FIRE_STOKE_RELEASE ** self._fire_frame_ratio
        self._fire_kick_release = _FIRE_KICK_RELEASE ** self._fire_frame_ratio
        self._clock.set_frame_interval(frame_ms / 1000.0)
        self._beat_tunnel.set_frame_interval(frame_ms)
        self._analog_scope.set_frame_interval(frame_ms)
        self._stream.set_frame_interval(frame_ms)

    def set_track_tempo(self, bpm: float | None) -> None:
        """The playing track's tag BPM — the beat clock's period.

        ``None`` means "no tag": the clock falls back to its own estimator.
        """
        self._clock.set_tempo(bpm)

    def reset_beat_clock(self) -> None:
        """A seek happened: the accumulated evidence belongs to where we were."""
        self._clock.reset()

    def beat_state(self) -> dict | None:
        """What the clock currently believes, or None for a mode without one.

        Read by ``scripts/vis_sheet.py`` so a contact sheet can be indexed by
        beat and labelled with the lock.
        """
        if self._mode != "beat_tunnel":
            return None
        return {
            "phase": self._clock.phase,
            "beat_in_bar": self._clock.beat_in_bar,
            "tempo_bpm": self._clock.tempo_bpm,
            "locked": self._clock.locked,
        }

    def set_mode(self, mode: str) -> None:
        if mode not in RENDER_MODES:
            return
        self._mode = mode
        self._bars[:] = 0.0
        self._peaks[:] = 0.0
        self._peak_vel[:] = _PEAK_START
        self._heat[:] = 0.0
        self._fire_stoke[:] = 0.0
        self._fire_kick = 0.0
        self._fire_time = 0.0
        self._bass_att = 0.0
        self._pulse = 0.0
        self._fract_angle = 0.0
        self._fract_phase = 0.0
        self._fract_level = 0.0
        self._trap_kick = 0.0
        self._kick_flux = 0.0
        self._prev_bass = 0.0
        self._prev_log = None
        self._flux_peaks[:] = 0.0
        if mode == "oscilloscope":
            self._analog_scope.reset()
        elif mode == "stream":
            self._stream.reset()
            self._clock.reset()
        elif mode == "loop_tunnel":
            self._loop_tunnel.reset()
        elif mode == "beat_tunnel":
            self._beat_tunnel.reset()
            self._clock.reset()

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self._fire_lut = _fire_palette(self._color)
        self._loop_tunnel.set_color(self._color)
        self._beat_tunnel.set_color(self._color)
        self._analog_scope.set_color(self._color)
        self._stream.set_color(self._color)

    def set_target_size(self, width: int, height: int, popout: bool = False) -> None:
        """Tell the renderer the host's pixel size; a no-op for most modes.

        The two tunnel modes and the popout's analog scope care: the tunnels
        draw true circles, so their image has to share the host's aspect or the
        rings come out as ellipses, and all three render near the host's own
        resolution rather than being blown up. The remaining modes are a fixed
        low-res grid the host stretches.

        They therefore want **device** pixels and need to know which host is
        asking, because the hosts have different budgets — see
        :meth:`BeatTunnelScene.set_target_size`.

        *popout* is also remembered, because it is what picks the oscilloscope's
        face; the backdrop's own renderer never passes True.
        """
        self._popout = popout
        self._loop_tunnel.set_target_size(width, height, popout)
        self._beat_tunnel.set_target_size(width, height, popout)
        self._analog_scope.set_target_size(width, height, popout)
        self._stream.set_target_size(width, height, popout)

    def render(self, samples: np.ndarray | None, sr: int) -> QImage:
        """Advance one frame from a mono block (zeros/None = silence)."""
        if samples is None or len(samples) < FFT_SIZE:
            samples = np.zeros(FFT_SIZE, dtype=np.float32)
        else:
            samples = samples[-FFT_SIZE:]
        if self._mode == "oscilloscope":
            # Returned, never assigned to self._image — same trap as the
            # tunnels below.
            return self._analog_scope.render(samples, sr)
        else:
            heights = self._band_heights(samples, sr)
            if self._mode == "stream":
                # Down here rather than beside the oscilloscope on purpose: the
                # scene wants band heights and the kick pulse, not raw samples,
                # so it goes through _band_heights like fire and the fractal.
                # Returned, never assigned, like the tunnels. The clock tick is
                # what makes the source's dance beat-locked — same tempo
                # plumbing as the beat tunnel (tag BPM via set_track_tempo,
                # evidence dropped on seek), the scene just reads the phase.
                self._clock.tick(self._kick_flux)
                return self._stream.render(heights, self._pulse, self._clock.phase)
            if self._mode == "loop_tunnel":
                # Returned directly, never assigned to self._image: the
                # scope/spectrum renderers paint into that at _W x _H, and
                # leaving a big image there would draw their next frame into
                # the corner of it.
                return self._render_loop_tunnel(heights)
            if self._mode == "beat_tunnel":
                return self._render_beat_tunnel(heights)
            if self._mode == "spectrum":
                self._render_spectrum(heights)
            elif self._mode in FRACTAL_MODES:
                self._render_fractal(heights)
            else:
                self._render_fire(heights)
        return self._image

    # ── DSP ────────────────────────────────────────────────────────────────

    def _ensure_bands(self, sr: int) -> None:
        """Log-spaced band → FFT-bin slices, rebuilt when the rate changes."""
        if self._band_slices is not None and self._band_sr == sr:
            return
        freqs = np.fft.rfftfreq(FFT_SIZE, 1.0 / max(sr, 1))
        f_lo, f_hi = 50.0, min(16000.0, sr / 2.0 if sr > 0 else 16000.0)
        edges = f_lo * (f_hi / f_lo) ** (np.arange(_N_BARS + 1) / _N_BARS)
        idx = np.searchsorted(freqs, edges).astype(int)
        # Every band gets at least one bin (low bands can span <1 bin).
        for k in range(1, len(idx)):
            idx[k] = max(idx[k], idx[k - 1] + 1)
        idx = np.clip(idx, 1, len(freqs) - 1)
        self._band_slices = [slice(idx[k], max(idx[k + 1], idx[k] + 1)) for k in range(_N_BARS)]
        self._band_sr = sr

    def _band_heights(self, samples: np.ndarray, sr: int) -> np.ndarray:
        """Normalized 0..1 dB heights per log band."""
        self._ensure_bands(sr if sr > 0 else 44100)
        spectrum = np.abs(np.fft.rfft(samples * self._window))
        # Hann coherent gain is 0.5 → a full-scale sine peaks its bin at N/4.
        spectrum /= FFT_SIZE / 4.0
        self._update_pulse(spectrum)
        if self._mode in ("beat_tunnel", "stream"):
            # Only the modes with a beat clock: a log1p over 1025 bins is
            # 30 µs, which is nothing, but it is 30 µs of tax on modes that
            # have no use for it. The stream joined when its source
            # started dancing on the beat grid.
            self._update_kick_flux(spectrum)
        db = 20.0 * np.log10(spectrum + 1e-9)
        heights = np.array([db[s].max() for s in self._band_slices])
        return np.clip((heights - _DB_FLOOR) / -_DB_FLOOR, 0.0, 1.0)

    def _update_pulse(self, spectrum: np.ndarray) -> None:
        """Kick-locked pulse: linear bass energy vs its smoothed average."""
        # The first two log bands cover ~50-120 Hz — the kick-drum range.
        bass = float(
            (spectrum[self._band_slices[0]] ** 2).mean()
            + (spectrum[self._band_slices[1]] ** 2).mean()
        )
        self._bass = bass
        self._bass_att = self._bass_alpha * self._bass_att + (1.0 - self._bass_alpha) * bass
        if self._bass_att < 1e-7:
            self._pulse = 0.0
            return
        ratio = bass / self._bass_att
        # >1.2 counts as a beat; saturate by ~1.8 for a 0..1 accent value.
        self._pulse = float(np.clip((ratio - 1.2) / 0.6, 0.0, 1.0))

    def _update_kick_flux(self, spectrum: np.ndarray) -> None:
        """The beat clock's feature: a bass transient with a click on it.

        The kick pulse above cannot count beats — measured over six tracks it
        fires 1.2 to 3.5 times a beat, because an off-beat bass note lifts the
        same band just as far. Gating the bass *rise* by the broadband rise
        keeps the kicks and drops the bass notes, and that product is what the
        clock's histogram is built from.

        Each term is scaled by its own decaying peak, standing in for the
        prototype's 99th percentile of a whole clip — which is not available to
        something hearing the track for the first time.
        """
        rise = max(0.0, self._bass - self._prev_bass)
        self._prev_bass = self._bass
        log_spectrum = np.log1p(1000.0 * spectrum)
        if self._prev_log is None:
            self._prev_log = log_spectrum
            self._kick_flux = 0.0
            return
        broadband = float(np.maximum(log_spectrum - self._prev_log, 0.0).mean())
        self._prev_log = log_spectrum
        product = self._normalise(0, rise) * self._normalise(1, broadband)
        self._kick_flux = self._normalise(2, product)

    def _normalise(self, index: int, value: float) -> float:
        """Value against its own slow peak, clipped to 0..1."""
        peak = max(value, self._flux_peaks[index] * self._flux_decay)
        self._flux_peaks[index] = peak
        return float(np.clip(value / peak, 0.0, 1.0)) if peak > 1e-12 else 0.0

    def _apply_ballistics(self, heights: np.ndarray) -> None:
        """Instant attack, linear release; accelerating peak-cap fall."""
        self._bars = np.maximum(heights, self._bars - _BAR_FALL)
        rising = self._bars >= self._peaks
        self._peaks = np.where(rising, self._bars, self._peaks - self._peak_vel)
        self._peak_vel = np.where(rising, _PEAK_START, self._peak_vel * _PEAK_ACCEL)
        self._peaks = np.clip(self._peaks, 0.0, 1.0)

    # ── Renderers (into the internal low-res image) ────────────────────────

    def _spectrum_gradient(self) -> QLinearGradient:
        gradient = QLinearGradient(0, _H, 0, 0)
        gradient.setColorAt(0.0, self._color.darker(300))
        gradient.setColorAt(0.6, self._color)
        gradient.setColorAt(1.0, self._color.lighter(160))
        return gradient

    def _render_spectrum(self, heights: np.ndarray) -> None:
        self._apply_ballistics(heights)
        self._image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self._image)
        if self._pulse > 0.0:
            # Kick accent: the whole background glows faintly with the beat.
            flash = QColor(self._color)
            flash.setAlpha(int(28 * self._pulse))
            painter.fillRect(0, 0, _W, _H, flash)
        gradient = self._spectrum_gradient()
        cap_color = QColor(Theme.CHROME)
        for i in range(_N_BARS):
            x = i * _BAR_W
            bar_h = int(self._bars[i] * (_H - 2))
            if bar_h > 0:
                painter.fillRect(x, _H - bar_h, _BAR_W - 1, bar_h, gradient)
            peak_y = _H - 1 - int(self._peaks[i] * (_H - 2))
            painter.fillRect(x, peak_y, _BAR_W - 1, 1, cap_color)
        painter.end()

    def _render_fire(self, heights: np.ndarray) -> None:
        heat = self._heat
        self._fire_time += self._frame_ms / 1000.0
        # Stoke the bottom row: band energies spread across the width, through
        # the ember bed, with a per-column attack (hot spots first) and a slow
        # release. Kick accent: flames leap on the beat, and settle.
        curve = np.interp(
            np.arange(_W), np.linspace(0, _W - 1, _N_BARS), heights
        ).astype(np.float32)
        self._fire_kick = max(self._pulse, self._fire_kick * self._fire_kick_release)
        target = curve * _FIRE_STOKE_GAIN * (1.0 + 0.8 * self._fire_kick)
        embers = self._fire_embers_now()
        stoke = self._fire_stoke
        rising = target > stoke
        self._fire_stoke = np.where(
            rising,
            stoke + (target - stoke) * self._fire_attack(embers),
            np.maximum(target, stoke * self._fire_release),
        ).astype(np.float32)
        heat[_H - 1] = np.minimum(self._fire_stoke * embers, 1.0)
        # Classic propagation: each cell becomes a cooled blend of the cells
        # below it — straight, both diagonals (weighted by the wind), and the
        # one two rows down, which smooths the frame-to-frame steps in the
        # stoke so a tongue is one shape rather than a stack of rows. The
        # cooling is a per-row profile (see the constants).
        below = heat[1:]
        wind = self._fire_wind(embers)
        left = np.roll(below, 1, axis=1)  # a cell taking from its left neighbour
        right = np.roll(below, -1, axis=1)
        two_below = np.vstack([heat[2:], heat[-1:]])
        blend = (
            below + left * (1.0 + wind) + right * (1.0 - wind) + _FIRE_VERTICAL_BLEND * two_below
        ) / (3.0 + _FIRE_VERTICAL_BLEND)
        heat[:-1] = np.maximum(blend - self._fire_cool, 0.0)
        np.clip(heat, 0.0, 1.0, out=heat)

        rgb = self._fire_lut[(heat * 255).astype(np.uint8)]
        # QImage wants 32-bit rows; build BGRA from the palette lookup. Alpha
        # follows heat, under the vertical fade envelope, so cold pixels are
        # transparent (the backdrop host composites over grey; the popout
        # fills black first — same look).
        bgra = np.empty((_H, _W, 4), dtype=np.uint8)
        bgra[..., 0] = rgb[..., 2]
        bgra[..., 1] = rgb[..., 1]
        bgra[..., 2] = rgb[..., 0]
        alpha = np.clip(heat * _FIRE_ALPHA_GAIN, 0.0, 1.0) * self._fire_fade
        bgra[..., 3] = (alpha * 255).astype(np.uint8)
        self._image = QImage(
            bgra.tobytes(), _W, _H, _W * 4, QImage.Format.Format_ARGB32
        ).copy()

    def _fire_embers_now(self) -> np.ndarray:
        """The ember bed at the current fire time: per column, floor..1."""
        cols = np.arange(_W)
        span = _W * 3
        product = np.ones(_W, dtype=np.float32)
        for layer, drift in zip(self._fire_embers, _FIRE_EMBER_DRIFT):
            product *= layer[(cols + int(drift * self._fire_time)) % span]
        spots = np.clip(product / _FIRE_EMBER_NORM, 0.0, 1.0) ** _FIRE_EMBER_POWER
        return _FIRE_EMBER_FLOOR + (1.0 - _FIRE_EMBER_FLOOR) * spots

    def _fire_attack(self, embers: np.ndarray) -> np.ndarray:
        """Per-column attack fraction for a rising stoke, from the ember bed."""
        spots = np.clip((embers - _FIRE_EMBER_FLOOR) / (1.0 - _FIRE_EMBER_FLOOR), 0.0, 1.0)
        per_frame = _FIRE_ATTACK_SLOW + (_FIRE_ATTACK_FAST - _FIRE_ATTACK_SLOW) * spots**_FIRE_ATTACK_POWER
        per_frame = np.clip(per_frame * self._fire_jitter, 0.05, 1.0)
        # A lerp fraction is a per-frame number: the same rise over the same
        # time at another interval is 1 - (1 - a) ** ratio.
        return 1.0 - (1.0 - per_frame) ** self._fire_frame_ratio

    def _fire_wind_rate(self, embers: np.ndarray) -> np.ndarray:
        """Each column's sway rate in rad/s: slower the hotter its ember."""
        spots = np.clip((embers - _FIRE_EMBER_FLOOR) / (1.0 - _FIRE_EMBER_FLOOR), 0.0, 1.0)
        return _FIRE_WIND_RATE_BED + (_FIRE_WIND_RATE_HOT - _FIRE_WIND_RATE_BED) * spots

    def _fire_wind(self, embers: np.ndarray) -> np.ndarray:
        """The blur's side bias per cell (H-1 x W) at the current fire time.

        sin(column phase + row twist) expanded, so it is a sin and a cos per
        column and two outer products rather than a sin per cell.
        """
        column = self._fire_wind_rate(embers) * self._fire_time + self._fire_wind_phase
        sin_c, cos_c = np.sin(column)[None, :], np.cos(column)[None, :]
        swing = sin_c * self._fire_twist_cos + cos_c * self._fire_twist_sin
        return self._fire_wind_amp * swing

    def _render_fractal(self, heights: np.ndarray) -> None:
        # Blend mean and max band height: mean alone leaves sparse spectra
        # (e.g. a lone bass line) nearly invisible, max alone never breathes.
        level = float(np.clip(0.5 * heights.mean() + 0.6 * heights.max(), 0.0, 1.0))
        # Fast attack, slow release: the fractal lights up with the music and
        # fades out over ~2s of silence (0.94^60 ≈ 0.02) instead of freezing.
        self._fract_level = max(level, self._fract_level * 0.94)
        self._fract_angle += _JULIA_SPIN_BASE + _JULIA_SPIN_LEVEL * level
        self._fract_phase += _JULIA_MORPH_BASE + _JULIA_MORPH_LEVEL * level

        # The Blade Fractal's swell is the kick through a follower; the raw
        # detector would strobe. Advanced for every fractal so a mode switch
        # never starts from a stale value, and it is a few flops.
        self._trap_kick = max(self._pulse, self._trap_kick * self._trap_release)
        kick = self._trap_kick if self._mode == "fractal_trap" else self._pulse

        theta = np.pi + _JULIA_ORBIT_SWING * np.sin(self._fract_phase)
        c = _JULIA_ORBIT_RADIUS * np.exp(1j * theta)
        zoom = 1.0 - _JULIA_KICK_ZOOM * kick
        z = (self._fract_grid * (np.exp(-1j * self._fract_angle) * zoom)).ravel()

        # Three kernels on one grid. Each returns a 0..1 intensity per pixel;
        # what the music does to the picture happens above (orbit, camera) and
        # below (brightness), never in here — the math stays audio-blind.
        if self._mode == "fractal_trap":
            fullness = (
                _TRAP_FULL_BASE
                + _TRAP_FULL_LEVEL * self._fract_level
                + _TRAP_FULL_KICK * kick
            )
            intensity = self._orbit_trap(z, c, fullness)
            # Smoothstep gate on level, then the kick flash on top.
            g = (self._fract_level - _TRAP_GATE_LO) / (_TRAP_GATE_HI - _TRAP_GATE_LO)
            g = float(np.clip(g, 0.0, 1.0))
            g = g * g * (3.0 - 2.0 * g)
            brightness = g * (0.62 + 0.55 * kick)
        else:
            blend = None
            if self._mode == "fractal_power":
                blend = 0.5 + 0.5 * np.sin(_POWER_BLEND_RATE * self._fract_phase)
            intensity = self._escape_time(z, c, blend)
            brightness = self._fract_level * (0.8 + 0.5 * kick)
        intensity = (intensity * np.clip(brightness, 0.0, 1.0)).reshape(_H, _W)

        rgb = self._fire_lut[(intensity * 255).astype(np.uint8)]
        bgra = np.empty((_H, _W, 4), dtype=np.uint8)
        bgra[..., 0] = rgb[..., 2]
        bgra[..., 1] = rgb[..., 1]
        bgra[..., 2] = rgb[..., 0]
        bgra[..., 3] = (np.clip(intensity * 2.2, 0.0, 1.0) * 255).astype(np.uint8)
        self._image = QImage(
            bgra.tobytes(), _W, _H, _W * 4, QImage.Format.Format_ARGB32
        ).copy()

    @staticmethod
    def _escape_time(z: np.ndarray, c: complex, blend: float | None) -> np.ndarray:
        """Escape-time intensity for z ← z² + c, or the z²/z³ blend.

        *blend* None is the Julia; 0..1 lerps the iterate between z² and z³
        (not a fractional power — two multiplies and a lerp, and visually the
        wanted thing: a continuous morph between two-fold and three-fold
        symmetry).
        """
        # Points that never escape (the set's interior) keep count 0 and are
        # recolored to mid brightness below.
        count = np.zeros(z.shape, dtype=np.float32)
        alive = np.ones(z.shape, dtype=bool)
        for i in range(1, _JULIA_ITERATIONS + 1):
            za = z[alive]
            z2 = za * za
            if blend is None:
                za = z2 + c
            else:
                za = (1.0 - blend) * z2 + blend * (z2 * za) + c
            z[alive] = za
            escaped = np.abs(za) > 2.0
            idx = np.flatnonzero(alive)[escaped]
            count[idx] = i
            alive[idx] = False
            if not alive.any():
                break

        # Late escape = close to the set = bright branch edge. The interior
        # sits at mid brightness (body in the theme color) so the near-white
        # top of the ramp is reserved for the dendrite fringe — full-bright
        # interiors render as flat washed-out blobs. The exponent darkens the
        # far field for contrast.
        intensity = (count / _JULIA_ITERATIONS) ** 1.6
        intensity[alive] = 0.5
        return intensity

    @staticmethod
    def _orbit_trap(z: np.ndarray, c: complex, fullness: float) -> np.ndarray:
        """Orbit-trap intensity: how near each orbit comes to the two axes.

        Same iteration as the Julia, but instead of counting steps it keeps the
        running minimum of ``min(|re|, |im|)`` — the distance to the trap —
        for every point until it escapes. Intensity is ``exp(-d * falloff)``:
        a wide soft glow at low falloff, a thin skeleton at high. *fullness*
        0..1 picks the falloff on a geometric scale so equal steps look equal.
        """
        dmin = np.full(z.shape, np.inf, dtype=np.float32)
        alive = np.ones(z.shape, dtype=bool)
        for _ in range(_JULIA_ITERATIONS):
            za = z[alive]
            za = za * za + c
            z[alive] = za
            dmin[alive] = np.minimum(
                dmin[alive], np.minimum(np.abs(za.real), np.abs(za.imag))
            )
            escaped = np.abs(za) > 2.0
            alive[np.flatnonzero(alive)[escaped]] = False
            if not alive.any():
                break
        ratio = _TRAP_FALLOFF_THIN / _TRAP_FALLOFF_FULL
        falloff = _TRAP_FALLOFF_FULL * ratio ** (1.0 - float(np.clip(fullness, 0.0, 1.0)))
        return np.exp(-dmin * falloff)

    def _render_loop_tunnel(self, heights: np.ndarray) -> QImage:
        # Same mean/max blend as the fractal: mean alone leaves a sparse
        # spectrum nearly still, max alone never breathes. Level drives travel
        # speed and brightness; the kick pulse ripples the near rings.
        level = float(np.clip(0.5 * heights.mean() + 0.6 * heights.max(), 0.0, 1.0))
        return self._loop_tunnel.render(level, self._pulse)

    def _render_beat_tunnel(self, heights: np.ndarray) -> QImage:
        # Level no longer drives travel — the tempo does — so it only decides
        # brightness here, alongside the kick.
        level = float(np.clip(0.5 * heights.mean() + 0.6 * heights.max(), 0.0, 1.0))
        self._clock.tick(self._kick_flux)
        return self._beat_tunnel.render(
            self._clock.phase, level, self._pulse, self._clock.bar_slot
        )


class VisCanvas(QWidget):
    """Popout widget that renders one visualization mode from fed samples."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(_W * 2, _H * 2)
        self._renderer = VisRenderer()

    def set_mode(self, mode: str) -> None:
        self._renderer.set_mode(mode)

    def set_color(self, color: str) -> None:
        self._renderer.set_color(color)

    def frame_ms(self) -> int:
        return self._renderer.frame_ms()

    def set_frame_interval(self, frame_ms: float) -> None:
        self._renderer.set_frame_interval(frame_ms)

    def set_track_tempo(self, bpm: float | None) -> None:
        self._renderer.set_track_tempo(bpm)

    def reset_beat_clock(self) -> None:
        self._renderer.reset_beat_clock()

    def feed(self, samples: np.ndarray | None, sr: int) -> None:
        # Device pixels, read from this widget rather than the primary screen:
        # the popout can be dragged onto a display with a different ratio.
        ratio = self.devicePixelRatioF()
        self._renderer.set_target_size(
            round(self.width() * ratio), round(self.height() * ratio), popout=True
        )
        self._renderer.render(samples, sr)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform, self._renderer.smooth_upscale()
        )
        painter.fillRect(self.rect(), QColor("#0a0a0a"))
        painter.drawImage(self.rect(), self._renderer.image())
        painter.end()


class VisualizerWindow(QWidget):
    """Popout window hosting a VisCanvas, fed from the player engine."""

    closed = Signal()

    def __init__(self, engine, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle(self.tr("Visualizer"))
        self.setStyleSheet("background-color: #0a0a0a;")
        self.resize(_W * 4, _H * 4)
        self._engine = engine
        self._canvas = VisCanvas(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._canvas)
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._on_tick)

    def set_mode(self, mode: str) -> None:
        self._canvas.set_mode(mode)
        # Per-mode frame rate: the beat tunnel asks for 60 fps, everything else
        # for 30. Applied here rather than at construction because the window
        # outlives the mode the user first chose.
        self._timer.setInterval(self._canvas.frame_ms())
        self._canvas.set_frame_interval(self._canvas.frame_ms())

    def set_color(self, color: str) -> None:
        self._canvas.set_color(color)

    def set_track_tempo(self, bpm: float | None) -> None:
        self._canvas.set_track_tempo(bpm)

    def reset_beat_clock(self) -> None:
        self._canvas.reset_beat_clock()

    def _on_tick(self) -> None:
        # While paused/stopped keep ticking with silence so bars fall and the
        # fire burns down instead of freezing mid-frame.
        samples = self._engine.recent_mono(FFT_SIZE) if self._engine.is_playing() else None
        self._canvas.feed(samples, self._engine.sample_rate())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._timer.stop()

    def closeEvent(self, event) -> None:
        self._timer.stop()
        super().closeEvent(event)
        self.closed.emit()
