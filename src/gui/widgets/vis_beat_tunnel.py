"""Beat Tunnel: a tunnel generated ahead of the camera and flown to the beat.

**The menu calls this one "Wormhole"**, and calls its sibling
:mod:`.vis_loop_tunnel` "Tunnel chase". The module, the class and the config
value name the *mechanism* instead, deliberately. The two labels used to sit
the other way round, and they were right until this one's wall became nebula
cloud — at which point the beat tunnel was plainly the wormhole-looking one
and the names had to be swapped. **A name for the look goes stale when the
look changes; a name for the mechanism does not.** The retired ``wormhole``
and ``tunnel_chase`` config values are migrated in
:func:`~src.utils.config._renamed_vis_mode`.

Same tube geometry as the loop tunnel's, but where that one flies a frozen
closed loop at a speed set by the level, this one is **generated ahead of the
camera in beat-space**: arc length is measured in beats
(``UNITS_PER_BEAT`` world units each), so a turn scheduled for beat 16 is a
bend in the tube at 16 × U units, and the camera reaches it exactly when the
music does. Speed is therefore the tempo, not the volume.

The turn schedule is the brief, in two lines: **a turn on the first beat of
every bar, and a second one on the third beat of every fourth bar.** That
gives a plain four-bar phrase you can feel — three ordinary bars and one that
swings twice.

Why it cannot be a precomputed loop like the loop tunnel's: the turns have to
fall where the *beats* fall, so the loop's turn spacing would have to be
locked to the beat grid and its length to the tempo, and every tempo change
would need a new loop. Generating ahead is both simpler and exact.

**The wall is a nebula, not a wireframe.** The ring mesh is still what the
picture is built on — the bends, the drift, the pulse ripple and the depth
fades all live in it — but what gets *drawn* at its vertices is a wall of
additive cloud puffs, translucent enough that the stars carry straight
through it. See "The nebula wall" below for the whole of it. The
wireframe itself survives as a knob (``_NEBULA_MESH_ALPHA``, off) because the
beat-locked turns are this mode's soul and cloud may soften the turn read on a
real track — a judgement only the running app can settle.

Three things the prototype taught about the picture, all of which the code
below is shaped by:

* **The near plane needs two different treatments.** A ring passing beside the
  camera on a bend projects a correct but startling bright chord across the
  lens. Clipping it away also drops the nearest ring's spokes — and those
  spokes, reaching in from off-frame, are what put the viewer *inside* a tube
  rather than in front of a cone. So: spokes are **clipped at** the near plane
  by interpolation (never dropped while their far end is ahead), and ring
  polygons are **faded out near** it.
* **Judge frames at 1:1.** A half-scale still of this showed a "pale white
  line" that an instrumented render proved to be an ordinary spoke lying on
  the horizontal through the vanishing point. Hence the half-segment angle
  offset below, and hence ``scripts/vis_sheet.py``.
* **It owns its image and follows the host's aspect**, like the loop tunnel —
  a tube stretched non-uniformly draws ellipses for rings — and that image is
  never assigned to ``VisRenderer._image``.

The beat itself comes from :class:`~.beat_clock.BeatClock`; no audio and no
tempo estimation happens here. :meth:`BeatTunnelScene.render` takes a phase
in beats, a level and a kick pulse as plain numbers.
"""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QPainter,
    QPen,
    QPolygonF,
    QRadialGradient,
    QTransform,
)

from ..styles.theme import Theme

TUNNEL_R = 1.0
UNITS_PER_BEAT = 2.5  # world units of tunnel per beat — this is the speed
DS = 0.125  # arc-length step the path is integrated at

# Render size. The image follows the host's aspect exactly (never stretched)
# and is capped by area, because the cost is lines and the antialiaser pays
# per pixel they cover. The popout gets the bigger budget: it runs at 60 fps
# but the host does one drawImage, while the backdrop's playlist repaint is
# ~11 ms on its own.
POPOUT_CAP = (1600, 720)
BACKDROP_CAP = (1216, 512)
_MIN_H = 64
_REF_H = 512  # the height the pixel sizes below were tuned at

_RINGS = 28
_SEGMENTS = 20
_SPACING = 1.0
_FOV_DEG = 95.0
_LOOK_AHEAD = 2.5
_FADE_EXP = 2.0  # depth fade; gentler stacks the far end into a bright knot
_SPOKE_CULL = 0.12  # drop spokes fainter than this: cost, and far-end clutter
_PEN_WIDTH = 1.3
_PULSE_RIPPLE = 0.12
_NEAR = 0.3  # camera-space depth a mesh point is clipped at
_NEAR_FADE = 0.9  # depth span a ring fades in over as it reaches the camera
_DEPTH_FLOOR = 0.05  # keeps a projected point from flying a million pixels out

# Turn shape. The bump is a raised cosine in arc length whose integral is the
# heading change, centred a tenth of a beat after the kick so the swing peaks
# just behind it. Because the integral is fixed, widening the bump lowers its
# peak curvature in proportion: the turn still happens, it just takes longer.
#
# 0.9 beats was the prototype's, and it made the flight read as a series of
# elbows — measured, 53% of it was dead straight (radius over 50 R) and the
# turns spiked to 2.27 R. 1.6 opens the sharpest turn to 3.6 R while still
# fitting a distinct swing between one bar's beat and the next, which is what
# keeps the turn legible *as* a turn on the beat. Past about 2.2 consecutive
# bumps overlap and the turns blur into one continuous sweep.
_TURN_LAG = 0.1  # beats
_TURN_WIDTH = 1.6  # beats, half-width of the bump
_BAR_TURN_RAD = (0.55, 1.0)  # heading change on the first beat of a bar
_PHRASE_TURN_RAD = (0.4, 0.7)  # ...and on the phrase bar's third beat
_COMPASS = 8  # directions a turn can take in the normal/binormal plane

# A slow wander laid under everything, so a "straightaway" is a long lazy
# curve rather than a corridor. Two sinusoids in arc length, one per frame
# axis, at wavelengths that are neither equal nor a whole number of bars — so
# the wander never lines up with the turn schedule and never reads as part of
# it. The amplitude is a radius of curvature around 18 R: far too gentle to
# see as a turn, and enough that the tunnel is rarely pointing straight down
# its own axis (which is also what was piling the far end into a bright knot).
#
# Deliberately a pure function of arc length rather than a random walk: the
# path can then be re-derived from any *s* without knowing how the camera got
# there, which is the same property the loop tunnel's frozen waypoints have.
#
# 0.026 is tuned by eye, converging from both sides: 53% of the flight was
# straighter than 1/50 R before any of this, 0.05 took it to 3.3% (too much
# wander, it never settled), 0.023 to 8.9% (too straight), and this leaves
# **6.8%**. Two warnings about that percentage, because it is the number this
# knob gets discussed in and it is a slippery one.
#
# It is hypersensitive right here and the picture is not: 1/50 R *is* roughly
# this amplitude, so what the figure counts is how often the two sinusoids
# cross zero together, while the wander's own median radius moves only 15 to
# 17 R across the whole useful range. And it drifts with how much path you
# measure — the same 0.023 reads 8.9% over 40 bars and 10.1% over 60 — because
# the two wavelengths do not come back into phase inside a short sample.
#
# So quote it with the length attached, and judge the setting by rendering.
# The number is a way to hold a judgement still between sessions, not a way to
# make one.
_DRIFT_K = 0.026  # curvature amplitude, both axes
_DRIFT_WAVELENGTHS = (33.0, 48.0)  # world units — about 13 and 19 beats
_DRIFT_PHASE = 1.7  # so the two axes do not cross zero together

_N_STARS = 160
_STAR_FLOOR = 0.15  # a star's depth alpha between kicks
_STAR_DECAY_AT_33MS = 0.82  # the loop tunnel's release, as a time constant
_STAR_POINT_MIN = 1.8  # below this a star is a dot rather than a 4-point star
# How a star looks is one roll per star, skewed toward the small end: most of
# the field is small compact dots and tight sparkles, and the occasional big
# star wears the long arms. Spike is how far the cross pokes out, in star
# sizes; size is a multiplier on the depth-driven base (whose old effective
# value was a fixed 1.0 — the field reads smaller now on purpose). The two
# ride the *same* roll deliberately: "less spiky" and "more compact" are the
# same star, so a short-armed one never comes out as a fat plus.
_STAR_SPIKE = (1.25, 2.6)
_STAR_SIZE = (0.4, 1.25)
_STAR_SIZE_BIAS = 2.0  # exponent on the roll: higher skews further toward small

_SKY_PARKED = -1000.0  # where a resting body waits, far behind the lens

# Galaxies: one slot, resting most of the time — the brief is *sparse*. Drawn
# as translucent haze (a tilted gradient disc plus a round bulge), so it reads
# as background rather than as an approaching object.
#
# A slot that empties does not refill at once: it rests for a stretch of
# *path* first. World units rather than seconds or frames, so the rate scales
# with the tempo exactly as the churn it thins does, and the 16 ms and 33 ms
# hosts agree. The stream's rate is **lifetime plus rest**, which is the whole
# of how the knob works and why it is not linear: the lifetime (spawn depth
# over travel, minus the ones a turn swings out of the window early) sits in
# the denominator and does not move when the rest gap does. This slot used to
# share the mechanism with a stream of planets, which is where the numbers
# below were measured; the planets are gone and the galaxies kept their rate.
_N_GALAXIES = 1
_GALAXY_RADIUS = (2.2, 4.0)  # world units
_GALAXY_REST = (12.0, 26.0)  # world units the slot lies empty
_GALAXY_NEAR = 2.0  # dies here: this big, any nearer would fill the frame
_GALAXY_MIN_PX = 5.0  # smaller than this is a smudge, not a galaxy
# The spiral: two arms wound this many radians from bulge to rim, drawn in
# the disc's own plane so the tilt foreshortens them with everything else.
# An arm is a run of overlapping soft blobs, not a stroke — the stroked
# version read as a curled wire in the running app, and cloud is clumps.
# Handedness and the exact wind are rolled at spawn; each blob's jitter,
# size and brightness are hashed from the wind, so a galaxy keeps its own
# clumps for life and no two galaxies share them.
_GALAXY_ARM_WIND = (3.6, 5.2)
_GALAXY_ARM_BLOBS = 16  # per arm
_GALAXY_ARM_START = 0.18  # where an arm leaves the bulge, in disc radii

_HISTORY = 4.0  # world units of path kept behind the camera

_GREY = (205, 205, 215)

# ── The nebula wall ────────────────────────────────────────────────────────
#
# The tube's wall is not a wireframe but a cloud: additive pre-rendered puffs
# anchored to the ring mesh's own vertices, drawn in the mesh's slot of the
# paint order (galaxies → stars → wall). Everything the geometry already knows
# — the beat-locked bends, the drift, the pulse ripple on the radius, the
# depth fades — is inherited by the cloud for free, because a puff is drawn
# *at* a mesh vertex rather than in screen space.
#
# It is a pure function of world arc length, like the path itself: every
# property of a puff is hashed from ``ring_s`` and the segment index, never
# from the ring *slot* k, which re-seats every ``_SPACING`` and would make the
# texture swim. There is no per-frame state, so nothing here belongs in
# :meth:`BeatTunnelScene.set_frame_interval` and the 16 ms and 33 ms hosts
# render identical worlds.
#
# Measured (PoC, 1600×720, the popout cap): the cost is per pixel *covered*,
# so the culls below are coverage caps rather than taste. Smooth filtering off
# is 1.65 ms against 2.19 ms on for the same puffs, which is why three sprite
# sizes are baked — a soft blob tolerates nearest-neighbour sampling as long as
# it is not being scaled by a factor of four.
_NEBULA_PALETTE = [  # blue → violet → magenta → teal → green
    (45, 95, 255),
    (115, 65, 255),
    (185, 70, 235),
    (45, 200, 185),
    (70, 220, 130),
]
# Deliberately the nebula's own colours and not the theme accent: the wireframe
# colour stays on the sky's tinted stars, so `_palette()` is untouched and
# `set_color` does not rebuild a sprite.
_NEBULA_WALL_R = 1.45  # puffs sit this far out from the tube axis, in wall radii
_PUFF_WORLD_R = 0.5  # world-unit radius of one puff
_PUFF_ALPHA = 0.5  # base opacity, before every fade
_PUFF_FADE_EXP = 2.2  # *extra* far fade over the mesh's own; see below
_PUFF_VARIANTS = 4  # distinct cloud shapes baked
# Pixel sizes at the 512-high reference, scaled like every other one. The PoC
# proved 3.5 / 7.0 / 300 at 720 high, which is what these are at that height.
_PUFF_MIN_PX = 2.5  # smaller than this is a blit nobody sees
_PUFF_THIN_PX = 5.0  # below this only every other segment is drawn
_PUFF_MAX_PX = 210.0  # a puff passing the lens may not fill the frame twice over
_PUFF_ALPHA_CULL = 0.02
# The hue field: two nested sinusoids over (arc length, angle), so one colour
# holds for a stretch of tube and a stretch of wall rather than banding by ring
# or by segment, plus a ±1-stop hash jitter that scatters the boundary.
_HUE_FIELD_S = 0.16  # how fast the colour walks along the tube
_HUE_FIELD_SWIRL = 1.4  # how far the angular term bends the walk
_HUE_FIELD_THETA = 2.0  # lobes around the wall
_HUE_FIELD_TWIST = 0.045  # ...and how fast those lobes rotate along it
_HUE_JITTER = 1.2  # stops of per-puff scatter across a boundary
# Sprite pixel sizes, and the drawn diameters they hand over at (the geometric
# means, so each sprite is used within √2 of its own resolution). All three are
# the *same* cloud downsampled, never separately generated noise: a puff
# crossing a threshold as it approaches would otherwise change texture.
_PUFF_SPRITE_SIZES = (32, 64, 128)
_PUFF_SIZE_SWITCH = (45.3, 90.5)
# A whisper of the old wireframe under the cloud, off by default. It is kept
# because the beat-locked turns are this mode's soul and cloud may soften the
# turn read on a real track — that is a judgement from the running app, and at
# 0.18 it costs a measured 3.5 ms.
_NEBULA_MESH_ALPHA = 0.0

_SPRITE_CACHE: dict[int, list] = {}


def _value_noise(size: int, cells: int, rng: np.random.Generator) -> np.ndarray:
    """One octave of bilinear-interpolated value noise, ``size`` square, 0..1."""
    grid = rng.random((cells + 1, cells + 1))
    idx = np.linspace(0, cells - 1e-6, size)
    i0 = idx.astype(int)
    frac = idx - i0
    a = grid[i0][:, i0]
    b = grid[i0 + 1][:, i0]
    c = grid[i0][:, i0 + 1]
    d = grid[i0 + 1][:, i0 + 1]
    fy, fx = frac[:, None], frac[None, :]
    return a * (1 - fy) * (1 - fx) + b * fy * (1 - fx) + c * (1 - fy) * fx + d * fy * fx


def _puff_alpha_master(size: int, rng: np.random.Generator) -> np.ndarray:
    """One cloud's coverage, 0..1: three octaves of noise inside a soft disc."""
    yy, xx = np.mgrid[0:size, 0:size]
    cx = (xx - size / 2) / (size / 2)
    cy = (yy - size / 2) / (size / 2)
    falloff = np.clip(1.0 - (cx * cx + cy * cy), 0.0, 1.0) ** 2
    noise = (
        _value_noise(size, 4, rng)
        + 0.5 * _value_noise(size, 9, rng)
        + 0.25 * _value_noise(size, 18, rng)
    )
    noise = (noise - noise.min()) / (noise.max() - noise.min() + 1e-9)
    return falloff * (0.25 + 0.75 * noise ** 1.4)


def _bake_nebula_sprites(seed: int) -> list[list[list[QImage]]]:
    """``[size][hue][variant]`` premultiplied cloud sprites, baked once.

    Noise is evaluated *here* and never per frame or per pixel: the per-frame
    work is a handful of hashes and a run of blits. About 1.7 MB in total for
    all sixty images, and cached per seed because every scene built from the
    same seed wants the same clouds — including the forty in the test suite.
    """
    cached = _SPRITE_CACHE.get(seed)
    if cached is not None:
        return cached
    rng = np.random.default_rng(seed + 500)
    biggest = max(_PUFF_SPRITE_SIZES)
    masters = [_puff_alpha_master(biggest, rng) for _ in range(_PUFF_VARIANTS)]
    sprites: list[list[list[QImage]]] = []
    for size in _PUFF_SPRITE_SIZES:
        step = biggest // size
        # Area-average down from the one master, so the three sizes are the
        # same cloud at three resolutions rather than three different clouds.
        scaled = [
            m.reshape(size, step, size, step).mean(axis=(1, 3)) if step > 1 else m
            for m in masters
        ]
        by_hue: list[list[QImage]] = []
        for red, green, blue in _NEBULA_PALETTE:
            row: list[QImage] = []
            for cover in scaled:
                # Format_ARGB32_Premultiplied is BGRA in memory on a
                # little-endian host, and premultiplied means every channel is
                # already scaled by the coverage.
                buf = np.empty((size, size, 4), np.uint8)
                buf[..., 0] = blue * cover
                buf[..., 1] = green * cover
                buf[..., 2] = red * cover
                buf[..., 3] = cover * 255
                image = QImage(
                    buf.tobytes(), size, size,
                    QImage.Format.Format_ARGB32_Premultiplied,
                )
                row.append(image.copy())  # own the pixels; buf is about to go
            by_hue.append(row)
        sprites.append(by_hue)
    _SPRITE_CACHE[seed] = sprites
    return sprites


def _hash01(value: np.ndarray, scale: float) -> np.ndarray:
    """The usual sine hash, as a fraction: deterministic, cheap, world-anchored."""
    raw = np.sin(value) * scale
    return raw - np.floor(raw)


def schedule_turns(beat_from: int, beat_to: int, rng: np.random.Generator,
                   bar_offset: int = 0):
    """``(beat, direction, heading change)`` for every turn in the half-open range.

    The brief: the first beat of every bar, plus the third beat of every fourth
    bar. Directions are eight compass points in the tube's normal/binormal
    plane, and a turn never repeats the previous direction or takes its exact
    reverse — a zig-zag reads as a wobble rather than as a course change.

    *bar_offset* is which beat the clock currently believes is the downbeat.
    It is applied here, to beats not yet scheduled, rather than by shifting the
    camera's phase: the clock's bar slot can flip (at most once in a couple of
    minutes, but it can), and shifting the phase would jump the camera a whole
    beat or three down the tunnel. Moving the *schedule* instead means the
    turns quietly arrive on the new grid a few bars later, with nothing to see.
    """
    out: list[tuple[int, float, float]] = []
    previous: float | None = None
    for beat in range(beat_from, beat_to):
        bar, position = divmod(beat - bar_offset, 4)
        on_bar = position == 0
        on_phrase = position == 2 and bar % 4 == 0
        if not (on_bar or on_phrase):
            continue
        while True:
            direction = float(rng.integers(0, _COMPASS)) * (2 * np.pi / _COMPASS)
            if previous is None:
                break
            delta = (direction - previous) % (2 * np.pi)
            if min(delta, 2 * np.pi - delta) > 0.1 and abs(delta - np.pi) > 0.1:
                break
        previous = direction
        lo, hi = _BAR_TURN_RAD if on_bar else _PHRASE_TURN_RAD
        out.append((beat, direction, float(rng.uniform(lo, hi))))
    return out


class PathAhead:
    """The tube's centre line, integrated forwards and forgotten behind.

    A **Bishop frame** is stepped along arc length: ``dT = (kN·N + kB·B) ds``,
    ``dN = -kN·T ds``, ``dB = -kB·T ds``. It is rotation-minimising by
    construction, so the mesh never rolls on a straight and never corkscrews
    into a bend — the property the loop tunnel's closed loop had to buy with a
    post-pass that spread the leftover twist around the seam. Nothing closes
    here, so there is no seam and no twist to spread.

    World coordinates grow without bound (about 150 000 units in eight hours);
    float64 carries that with room to spare, so there is no rebasing.
    """

    def __init__(self, seed: int = 1) -> None:
        self._rng = np.random.default_rng(seed)
        self.bar_offset = 0
        self.reset()

    def reset(self) -> None:
        self.s0 = 0.0  # arc-length of sample 0
        self.pos = [np.zeros(3)]
        self.tan = [np.array([0.0, 0.0, 1.0])]
        self.normal = [np.array([0.0, 1.0, 0.0])]
        self.binormal = [np.array([1.0, 0.0, 0.0])]
        self.kappa = [0.0]
        self.turns: list[tuple[int, float, float]] = []
        self._scheduled_to = 0

    # ── Building ───────────────────────────────────────────────────────────

    def curvature_at(self, s: float) -> tuple[float, float]:
        """The (N, B) curvature at arc-length *s*: the turns, plus the wander.

        The only place the tunnel's shape is decided. Everything downstream —
        the frame integration, where the rings sit, the projection, the near
        plane — reads the result and has no opinion about where it came from,
        which is why the shape is two constants away at any time.
        """
        kn = kb = 0.0
        half = _TURN_WIDTH * UNITS_PER_BEAT
        for beat, direction, heading in self.turns:
            centre = (beat + _TURN_LAG) * UNITS_PER_BEAT
            u = (s - centre) / half
            if -1.0 < u < 1.0:
                # Raised cosine, area = half, so the bump's integral is the
                # heading change however wide it is made.
                magnitude = heading / half * 0.5 * (1.0 + math.cos(math.pi * u))
                kn += magnitude * math.cos(direction)
                kb += magnitude * math.sin(direction)
        first, second = _DRIFT_WAVELENGTHS
        kn += _DRIFT_K * math.sin(s * 2 * math.pi / first)
        kb += _DRIFT_K * math.sin(s * 2 * math.pi / second + _DRIFT_PHASE)
        return kn, kb

    def extend_to(self, s_needed: float) -> None:
        while self.s0 + (len(self.pos) - 1) * DS < s_needed:
            s = self.s0 + (len(self.pos) - 1) * DS
            # A turn centred up to _TURN_WIDTH beats ahead already bends the
            # path *here*, so the schedule has to reach that far or the first
            # half of every bump is silently missing and the turn comes out
            # smaller than it was asked for. Today the `+ 16` below is what
            # actually guarantees it — this trigger only decides *when* the
            # next chunk is cut — but it was written as a bare `+ 2`, true
            # only while the width was 0.9, and the two numbers have no
            # business being independent. Derived, and a test asserts the
            # frontier stays covered.
            needed_beat = int(s / UNITS_PER_BEAT) + int(math.ceil(_TURN_WIDTH)) + 1
            if needed_beat >= self._scheduled_to:
                self.turns += schedule_turns(
                    self._scheduled_to, needed_beat + 16, self._rng, self.bar_offset
                )
                self._scheduled_to = needed_beat + 16
            kn, kb = self.curvature_at(s)
            tan, normal, binormal = self.tan[-1], self.normal[-1], self.binormal[-1]
            tan2 = tan + (kn * normal + kb * binormal) * DS
            normal2 = normal - kn * tan * DS
            tan2 /= np.linalg.norm(tan2)
            normal2 -= np.dot(normal2, tan2) * tan2
            normal2 /= np.linalg.norm(normal2)
            self.pos.append(self.pos[-1] + tan2 * DS)
            self.tan.append(tan2)
            self.normal.append(normal2)
            self.binormal.append(np.cross(tan2, normal2))
            self.kappa.append(math.hypot(kn, kb))

    def trim(self, cam_s: float) -> None:
        """Forget the path behind the camera, and the turns that shaped it."""
        drop = int((cam_s - _HISTORY - self.s0) / DS)
        if drop <= 64:
            return
        del self.pos[:drop]
        del self.tan[:drop]
        del self.normal[:drop]
        del self.binormal[:drop]
        del self.kappa[:drop]
        self.s0 += drop * DS
        reach = math.ceil(_TURN_WIDTH) + 1
        self.turns = [
            t for t in self.turns
            if (t[0] + reach) * UNITS_PER_BEAT > cam_s - 2 * _HISTORY
        ]

    def at(self, s: float):
        """``(position, normal, binormal)`` at arc-length *s*, clamped to what exists."""
        i = int((s - self.s0) / DS)
        i = max(0, min(i, len(self.pos) - 1))
        return self.pos[i], self.normal[i], self.binormal[i]

    def min_radius(self) -> float:
        """Smallest radius of curvature so far, in tunnel radii.

        Analytic — it comes from the bump sum, not from finite differences over
        the integrated polyline, which over-counts on a piecewise-linear path.
        Below about 2 the inside wall of a turn would fold through itself.
        """
        peak = max(self.kappa)
        return 1.0 / max(peak, 1e-9)

    def max_radius(self) -> float:
        """Largest radius of curvature so far — how straight the flattest bit is.

        The counterpart of the above, and the number that says whether the
        tunnel ever becomes a corridor. The drift is what keeps it finite.
        """
        return 1.0 / max(min(self.kappa[1:], default=0.0), 1e-9)


class BeatTunnelScene:
    """The scene's own state and image, driven by a beat phase and the audio."""

    def __init__(self, seed: int = 1) -> None:
        self._color = QColor(Theme.WAVEFORM_DEFAULT)
        self._path = PathAhead(seed)
        self._seed = seed
        self._rng = np.random.default_rng(seed + 100)
        self._image = QImage(
            BACKDROP_CAP[0], BACKDROP_CAP[1], QImage.Format.Format_ARGB32_Premultiplied
        )
        self._image.fill(Qt.GlobalColor.transparent)
        self._far = _RINGS * _SPACING
        # Vertical field of view is fixed, so a wider host simply shows more to
        # the sides rather than distorting.
        self._focal = (self._image.height() / 2) / math.tan(math.radians(_FOV_DEG) / 2)
        # Half a segment of offset, so no spoke is exactly axis-aligned on a
        # dead straight: an axis-aligned 1.3 px antialiased line lands on one
        # pixel row at full coverage and reads as a brighter line than its
        # neighbours.
        theta = np.linspace(0, 2 * np.pi, _SEGMENTS, endpoint=False) + np.pi / _SEGMENTS
        self._cos, self._sin = np.cos(theta), np.sin(theta)
        self._sprites = _bake_nebula_sprites(seed)
        # Rows, not columns: every per-puff array below is (ring, segment), so
        # these broadcast against ``ring_s[:, None]`` without a reshape a frame.
        self._seg = np.arange(_SEGMENTS)[None, :]
        self._seg_theta = theta[None, :]
        self._seg_odd = (self._seg % 2 == 1)
        self._stars = np.empty((_N_STARS, 3))
        self._star_kind = np.empty(_N_STARS, int)
        self._star_spike = np.full(_N_STARS, _STAR_SPIKE[0])
        self._star_size = np.full(_N_STARS, _STAR_SIZE[0])
        self._galaxies = np.empty((_N_GALAXIES, 4))  # x, y, z, radius
        self._galaxy_basis = np.zeros((_N_GALAXIES, 2, 3))  # the disc's plane
        # The camera arc-length before which an empty slot stays empty — the
        # rest gap that thins the stream (see _GALAXY_REST).
        self._galaxy_wake = np.zeros(_N_GALAXIES)
        self._galaxy_twist = np.zeros(_N_GALAXIES)  # signed arm wind, per spawn
        self._prev_basis: np.ndarray | None = None
        self._prev_cam: np.ndarray | None = None
        self._star_glow = 0.0
        self._cam_s = 0.0
        self._ring_s = np.zeros(_RINGS)
        self.set_frame_interval(1000.0 / 60.0)
        self.reset()

    # ── Public API ─────────────────────────────────────────────────────────

    def image(self) -> QImage:
        return self._image

    def set_color(self, color: QColor | str) -> None:
        self._color = QColor(color)

    def set_frame_interval(self, frame_ms: float) -> None:
        """Re-derive the per-frame decays from the host's interval.

        The star glow's 0.82 was solved by eye against a 33 ms frame; at 16 ms
        the same number is a release twice as fast, which is a different visual
        wearing the same constant.
        """
        if frame_ms <= 0:
            return
        self._star_decay = _STAR_DECAY_AT_33MS ** (frame_ms / 33.0)

    def reset(self) -> None:
        """Back to the start of a fresh path, with a fresh sky."""
        self._path = PathAhead(self._seed)
        self._rng = np.random.default_rng(self._seed + 100)
        self._prev_basis = None
        self._prev_cam = None
        self._star_glow = 0.0
        self._cam_s = 0.0
        for i in range(_N_STARS):
            self._stars[i] = self._spawn(self._rng.uniform(1.0, self._far))
            self._star_kind[i] = self._rng.integers(0, 3)
            self._roll_star_look(i)
        # Galaxies start resting, not on screen: sparse is the brief, and a
        # full rest before the first one keeps short deterministic test
        # flights (and the first bars of every track) galaxy-free.
        self._galaxies[:] = 0.0
        self._galaxies[:, 2] = _SKY_PARKED
        self._galaxy_basis[:] = 0.0
        self._galaxy_twist[:] = 0.0
        for i in range(_N_GALAXIES):
            self._galaxy_wake[i] = self._rng.uniform(*_GALAXY_REST)
        self._image.fill(Qt.GlobalColor.transparent)

    def set_target_size(self, width: int, height: int, popout: bool = False) -> None:
        """Match the image to the host's shape, capped by what a frame may cost.

        *width* and *height* are **device** pixels — the host's logical size
        times its own ``devicePixelRatioF``, read from the widget that paints
        and not from the primary screen, since a popout can be dragged to
        another display. A Retina popout at 1400×800 logical therefore asks for
        2800×1600 and gets 1260×720, smoothly upscaled by the host; rendering
        it natively would cost around 10 ms a frame for no visible gain.

        The aspect is preserved exactly and never upscaled: a stretched
        tube draws ellipses where the rings should be, and a host smaller
        than the cap is better served at its own size.
        """
        if width <= 0 or height <= 0:
            return
        cap_w, cap_h = POPOUT_CAP if popout else BACKDROP_CAP
        scale = min(cap_w / width, cap_h / height, 1.0)
        target_w = max(2 * _MIN_H, int(round(width * scale)))
        target_h = max(_MIN_H, int(round(height * scale)))
        if (target_w, target_h) == (self._image.width(), self._image.height()):
            return
        self._image = QImage(
            target_w, target_h, QImage.Format.Format_ARGB32_Premultiplied
        )
        self._image.fill(Qt.GlobalColor.transparent)
        self._focal = (target_h / 2) / math.tan(math.radians(_FOV_DEG) / 2)

    def render(self, beat_phase: float, level: float, pulse: float,
               bar_offset: int = 0) -> QImage:
        """Fly to *beat_phase* and paint. *level* and *pulse* are 0..1.

        *bar_offset* is the clock's current idea of the downbeat; see
        :func:`schedule_turns` for why it moves the schedule rather than the
        camera.
        """
        self._path.bar_offset = bar_offset
        self._cam_s = beat_phase * UNITS_PER_BEAT
        self._path.extend_to(self._cam_s + self._far + _LOOK_AHEAD + 2.0)
        self._path.trim(self._cam_s)
        self._star_glow = max(pulse, self._star_glow * self._star_decay)

        cam, up_hint, _ = self._path.at(self._cam_s)
        look, _, _ = self._path.at(self._cam_s + _LOOK_AHEAD)
        forward = look - cam
        forward /= np.linalg.norm(forward)
        right = np.cross(up_hint, forward)
        right /= np.linalg.norm(right)
        up = np.cross(forward, right)
        basis = np.stack([right, up, forward], axis=1)  # columns

        # Rings sit at fixed *world* arc-lengths, so they slide toward the
        # camera as it advances rather than riding along with it.
        first = math.ceil(self._cam_s / _SPACING) * _SPACING
        ring_s = first + np.arange(_RINGS) * _SPACING
        self._ring_s = ring_s
        centres, ring_n, ring_b = (
            np.array(a) for a in zip(*(self._path.at(s) for s in ring_s))
        )
        radius = TUNNEL_R * (
            1.0 + _PULSE_RIPPLE * pulse * np.exp(-(ring_s - self._cam_s) / 4.0)
        )[:, None, None]
        points = centres[:, None, :] + radius * (
            self._cos[None, :, None] * ring_n[:, None, :]
            + self._sin[None, :, None] * ring_b[:, None, :]
        )
        rel = (points - cam) @ basis
        # The cloud is anchored *outside* the wall, not on it. Pushed in world
        # space rather than screen space on purpose: the obvious screen-space
        # version scales each vertex away from the ring's projected centroid,
        # and the centroid of a ring that is partly behind the camera is
        # garbage — which the near rings always are on a bend, i.e. exactly
        # where it shows. Anchored at the wall radius itself the puffs smear
        # across the flight path and the bore fills in.
        puff_rel = (
            centres[:, None, :] + (points - centres[:, None, :]) * _NEBULA_WALL_R - cam
        ) @ basis
        # Kept rather than passed straight through: a QPainter cannot be
        # recorded (its draw methods are not virtual), so the near-plane rules
        # are asserted against the numbers the painter is handed.
        self._geometry = geometry = self._project(rel)
        geometry.update(self._project_puffs(puff_rel))
        self._fade_rings(geometry, ring_s)

        self._advance_stars(basis, cam)
        self._advance_galaxies(basis, cam)
        self._prev_basis, self._prev_cam = basis, cam
        self._paint(geometry, ring_s, level, pulse)
        return self._image

    # ── Projection ─────────────────────────────────────────────────────────

    def _project(self, rel: np.ndarray) -> dict:
        """Screen coordinates for the ring mesh, plus what survives the near plane."""
        width, height = self._image.width(), self._image.height()
        ahead = rel[..., 2] > _NEAR
        nearest = rel[..., 2].min(axis=1)
        depth = np.maximum(rel[..., 2], _DEPTH_FLOOR)
        sx = width / 2 + self._focal * rel[..., 0] / depth
        sy = height / 2 - self._focal * rel[..., 1] / depth

        # A spoke runs from ring k to ring k+1. Where its near end is beside or
        # behind the camera it is moved *up* to the near plane rather than
        # dropped: those lines, arriving from off-frame, are what put the
        # viewer inside the tube instead of in front of a cone.
        near_end, far_end = rel[:-1], rel[1:]
        za, zb = near_end[..., 2], far_end[..., 2]
        span = np.where(np.abs(zb - za) < 1e-9, 1e-9, zb - za)
        t = np.clip((_NEAR - za) / span, 0.0, 1.0)
        clipped = np.where((za < _NEAR)[..., None], near_end + (far_end - near_end) * t[..., None], near_end)
        spoke_ok = (zb >= _NEAR) & (clipped[..., 2] >= _NEAR - 1e-6)
        cd = np.maximum(clipped[..., 2], _DEPTH_FLOOR)
        return {
            "sx": sx,
            "sy": sy,
            "ahead": ahead,
            "nearest": nearest,
            "spoke_ok": spoke_ok,
            "spoke_x": width / 2 + self._focal * clipped[..., 0] / cd,
            "spoke_y": height / 2 - self._focal * clipped[..., 1] / cd,
        }

    def _project_puffs(self, rel: np.ndarray) -> dict:
        """Screen position and camera depth for each puff anchor.

        The near-plane *spoke* machinery above is deliberately not applied. A
        spoke is a line with a far end to interpolate toward; a puff is a local
        blob with nothing to clip along, so one whose anchor has reached the
        plane is simply dropped — and the alpha it would have been drawn at is
        already zero by then, for the same reason a ring's is.
        """
        width, height = self._image.width(), self._image.height()
        depth = np.maximum(rel[..., 2], _DEPTH_FLOOR)
        return {
            "puff_x": width / 2 + self._focal * rel[..., 0] / depth,
            "puff_y": height / 2 - self._focal * rel[..., 1] / depth,
            "puff_z": rel[..., 2],
        }

    # ── Sky ────────────────────────────────────────────────────────────────

    def _spawn(self, depth: float | None = None, margin: float = 1.6) -> np.ndarray:
        """A point in camera coordinates, outside the tunnel wall."""
        if depth is None:
            depth = self._rng.uniform(self._far * 0.6, self._far)
        aspect = self._image.width() / max(self._image.height(), 1)
        lim_x = depth * 0.9 * aspect
        lim_y = depth * 0.9
        while True:
            x = self._rng.uniform(-lim_x, lim_x)
            y = self._rng.uniform(-lim_y, lim_y)
            if x * x + y * y > (TUNNEL_R * margin) ** 2:
                return np.array([x, y, depth])

    def _roll_star_look(self, index: int) -> None:
        """One prominence roll per star, driving spike and size together.

        Squaring the roll (``_STAR_SIZE_BIAS``) skews the field toward small:
        most stars land near the compact short-armed end, and the long-armed
        ones stay the exceptions that make the sky read as varied.
        """
        t = self._rng.random() ** _STAR_SIZE_BIAS
        self._star_spike[index] = _STAR_SPIKE[0] + (_STAR_SPIKE[1] - _STAR_SPIKE[0]) * t
        self._star_size[index] = _STAR_SIZE[0] + (_STAR_SIZE[1] - _STAR_SIZE[0]) * t

    def _random_plane_basis(self) -> np.ndarray:
        """Two perpendicular unit vectors spanning a plane at a random attitude.

        Take a normal off the sphere and any two perpendiculars to it. The
        normal is drawn from a Gaussian rather than from two uniform angles
        because that is uniform on the sphere — polar angles bunch the normals
        at the poles, which would give most galaxies a near-edge-on disc.
        """
        normal = self._rng.normal(size=3)
        normal /= np.linalg.norm(normal)
        aside = np.array([0.0, 0.0, 1.0]) if abs(normal[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
        u = np.cross(normal, aside)
        u /= np.linalg.norm(u)
        return np.stack([u, np.cross(normal, u)])

    def _spawn_galaxy(self, index: int) -> None:
        """A fresh galaxy: where, how big, its disc's attitude, its spiral."""
        depth = self._rng.uniform(self._far * 0.9, self._far * 1.5)
        self._galaxies[index, :3] = self._spawn(depth, margin=3.0)
        self._galaxies[index, 3] = self._rng.uniform(*_GALAXY_RADIUS)
        self._galaxy_basis[index] = self._random_plane_basis()
        handed = -1.0 if self._rng.random() < 0.5 else 1.0
        self._galaxy_twist[index] = handed * self._rng.uniform(*_GALAXY_ARM_WIND)

    def _rigid(self, basis, cam):
        """Rotation and offset carrying last frame's camera coordinates into this one's.

        ``None`` on the first frame, where there is no previous camera to come
        from. The sky lives in camera coordinates — projecting is then
        a divide — so every frame applies this exact rigid transform instead of
        re-deriving world positions.
        """
        if self._prev_basis is None:
            return None
        return basis.T @ self._prev_basis, basis.T @ (self._prev_cam - cam)

    def _advance_stars(self, basis, cam) -> None:
        """Keep the stars still in the world, and refill the ones that fall off."""
        move = self._rigid(basis, cam)
        if move is not None:
            rotation, offset = move
            self._stars[:] = self._stars @ rotation.T + offset
        z = self._stars[:, 2]
        for i in np.flatnonzero((z < _NEAR) | (z > self._far * 1.2)):
            self._stars[i] = self._spawn()
            self._roll_star_look(i)

    def _refill_slot(self, positions, wake, index, rest, spawn) -> None:
        """One empty sky slot: park it, rest it, then let *spawn* refill it.

        The first frame after a body leaves the window rolls the rest gap and
        parks it far behind the lens; every later frame re-parks it (the rigid
        transform moves parked points like any other) until the camera has
        flown *rest* units, and only then does the slot refill. This is the
        whole of thinning the sky: the stream's rate is lifetime plus rest, so
        `_GALAXY_REST` is the only knob that sets how often one comes round.
        """
        if positions[index, 2] > _SKY_PARKED * 0.5:
            wake[index] = self._cam_s + self._rng.uniform(*rest)
            positions[index, 2] = _SKY_PARKED
        elif self._cam_s >= wake[index]:
            spawn(index)
        else:
            positions[index, 2] = _SKY_PARKED

    def _advance_galaxies(self, basis, cam) -> None:
        """As the stars: fixed in the world, but resting between visits.

        A galaxy's disc plane is fixed in the world too, so its two basis
        vectors take the rotation and **not** the offset: they are directions,
        not points. The near bound is high because a galaxy is huge — letting
        one reach the lens would fill the frame with haze — and its alpha has
        already faded to nothing by then.
        """
        move = self._rigid(basis, cam)
        if move is not None:
            rotation, offset = move
            self._galaxies[:, :3] = self._galaxies[:, :3] @ rotation.T + offset
            self._galaxy_basis[:] = self._galaxy_basis @ rotation.T
        z = self._galaxies[:, 2]
        for i in np.flatnonzero((z < _GALAXY_NEAR) | (z > self._far * 1.8)):
            self._refill_slot(
                self._galaxies, self._galaxy_wake, i, _GALAXY_REST, self._spawn_galaxy
            )

    def _wash(self, white: float) -> QColor:
        """The accent colour mixed *white* of the way toward white."""
        main = self._color
        return QColor(
            int(main.red() * (1 - white) + 255 * white),
            int(main.green() * (1 - white) + 255 * white),
            int(main.blue() * (1 - white) + 255 * white),
        )

    def _palette(self) -> list[QColor]:
        """Grey, and two washes of the accent colour toward white.

        Paler than the mesh on purpose (the brief): the tunnel is the subject
        and the sky is depth behind it.
        """
        return [QColor(*_GREY), self._wash(0.65), self._wash(0.4)]

    # ── Paint ──────────────────────────────────────────────────────────────

    def _paint(self, geometry: dict, ring_s, level: float, pulse: float) -> None:
        width, height = self._image.width(), self._image.height()
        scale = height / _REF_H  # the pixel sizes below were tuned at 512 high
        self._image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self._image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = self._palette()
        glow = _STAR_FLOOR + (1.0 - _STAR_FLOOR) * self._star_glow

        self._paint_galaxies(painter, width, height, glow, scale)
        self._paint_stars(painter, palette, width, height, glow, scale)
        if _NEBULA_MESH_ALPHA > 0:
            self._paint_mesh(
                painter, geometry, ring_s, level, pulse, _NEBULA_MESH_ALPHA
            )
        self._paint_nebula(painter, geometry, ring_s, level, pulse, scale)
        painter.end()

    def _paint_galaxies(self, painter, width, height, glow, scale) -> None:
        """Rare translucent discs, the farthest thing in the frame.

        A galaxy is a circle in its own plane, so it projects to an ellipse —
        drawn by mapping the unit circle through the projected images of its
        two plane axes, which is what makes an edge-on one a sliver and a
        face-on one a wheel with no per-case code. Two passes: the tilted
        gradient disc, then a round bulge in *screen* space, because a bulge
        is a ball and does not foreshorten with the disc it sits in.
        """
        for index, (x, y, z, radius) in enumerate(self._galaxies):
            if z <= _GALAXY_NEAR:
                continue
            px = width / 2 + self._focal * x / z
            py = height / 2 - self._focal * y / z
            centre = np.array([x, y, z])
            axes = []
            for direction in self._galaxy_basis[index]:
                tip = centre + direction * radius
                if tip[2] <= 0.2:
                    break
                axes.append((
                    width / 2 + self._focal * tip[0] / tip[2] - px,
                    height / 2 - self._focal * tip[1] / tip[2] - py,
                ))
            if len(axes) < 2:
                continue
            (ux, uy), (vx, vy) = axes
            major = max(math.hypot(ux, uy), math.hypot(vx, vy))
            if major < _GALAXY_MIN_PX * scale or abs(ux * vy - uy * vx) < 1e-6:
                continue
            if not (-major <= px <= width + major and -major <= py <= height + major):
                continue
            # The near fade is the ring lesson again: by the time the death
            # bound removes it, it is already drawing at nothing.
            near = float(np.clip((z - _GALAXY_NEAR) / 6.0, 0.0, 1.0))
            alpha = float(np.clip(1.05 - z / (self._far * 1.5), 0.12, 0.45))
            alpha *= near * (0.35 + 0.65 * glow)

            core = self._wash(0.85)
            core.setAlphaF(min(1.0, alpha * 1.6))
            mid = self._wash(0.5)
            mid.setAlphaF(alpha * 0.65)  # haze under the arms, not the shape
            edge = QColor(mid)
            edge.setAlphaF(0.0)
            disc = QRadialGradient(QPointF(0.0, 0.0), 1.0)
            disc.setColorAt(0.0, core)
            disc.setColorAt(0.35, mid)
            disc.setColorAt(1.0, edge)
            painter.save()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setTransform(QTransform(ux, uy, vx, vy, px, py), True)
            painter.setBrush(QBrush(disc))
            painter.drawEllipse(QRectF(-1.0, -1.0, 2.0, 2.0))
            self._paint_spiral_arms(painter, self._galaxy_twist[index], alpha)
            painter.restore()

            core_r = major * 0.16
            bright = self._wash(0.9)
            bright.setAlphaF(min(1.0, alpha * 1.9))
            dim = QColor(bright)
            dim.setAlphaF(0.0)
            bulge = QRadialGradient(QPointF(px, py), core_r)
            bulge.setColorAt(0.0, bright)
            bulge.setColorAt(1.0, dim)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(bulge))
            painter.drawEllipse(QPointF(px, py), core_r, core_r)

    def _paint_spiral_arms(self, painter, twist: float, alpha: float) -> None:
        """Two arms of cloud clumps in the disc's unit circle.

        Drawn while the galaxy's plane transform is on the painter, so the
        arms foreshorten and tilt with the disc for free — an edge-on spiral
        collapses into its sliver like everything else. Each arm is a run of
        overlapping radial-gradient blobs, jittered off the spiral's spine
        and varied in size and brightness by a hash of the galaxy's own wind:
        clumps, not a stroke, which is the difference between cloud and the
        curled wire the first cut read as. The taper power is what dissolves
        the tip — a linear fade left it hanging past the haze as a hook.
        """
        ts = np.linspace(_GALAXY_ARM_START, 1.0, _GALAXY_ARM_BLOBS)
        angles = twist * ts
        radii = ts ** 0.9
        arm_colour = self._wash(0.7)
        painter.setPen(Qt.PenStyle.NoPen)
        steps = np.arange(_GALAXY_ARM_BLOBS)
        for arm, phase in enumerate((0.0, math.pi)):
            seed = twist * 57.3 + arm * 19.1
            h1 = _hash01(seed + steps * 12.9898, 43758.5453)
            h2 = _hash01(seed + steps * 78.233, 27183.1)
            xs = radii * np.cos(angles + phase) + (h1 - 0.5) * 0.12
            ys = radii * np.sin(angles + phase) + (h2 - 0.5) * 0.12
            for m in range(_GALAXY_ARM_BLOBS):
                taper = 1.0 - float(ts[m])
                bright = min(1.0, alpha * 1.15) * taper ** 1.1 * (0.6 + 0.4 * float(h2[m]))
                if bright < 0.01:
                    continue
                blob_r = 0.10 + 0.10 * taper + 0.06 * float(h1[m])
                centre = QColor(arm_colour)
                centre.setAlphaF(bright)
                edge = QColor(arm_colour)
                edge.setAlphaF(0.0)
                blob = QRadialGradient(QPointF(xs[m], ys[m]), blob_r)
                blob.setColorAt(0.0, centre)
                blob.setColorAt(1.0, edge)
                painter.setBrush(QBrush(blob))
                painter.drawEllipse(QPointF(xs[m], ys[m]), blob_r, blob_r)

    def _paint_stars(self, painter, palette, width, height, glow, scale) -> None:
        """Dots far out, four-point stars with a white core near.

        The glow scales the whole field, so depth still orders them: a near
        star between kicks stays brighter than a far one, just barely lit.
        """
        z = self._stars[:, 2]
        xs = width / 2 + self._focal * self._stars[:, 0] / z
        ys = height / 2 - self._focal * self._stars[:, 1] / z
        painter.setPen(Qt.PenStyle.NoPen)
        for x, y, depth, kind, spike, prominence in zip(
            xs, ys, z, self._star_kind, self._star_spike, self._star_size
        ):
            if depth <= 0.2 or not (0 <= x < width and 0 <= y < height):
                continue
            alpha = float(np.clip(1.1 - depth / self._far, 0.15, 1.0)) * glow
            colour = QColor(palette[kind])
            colour.setAlphaF(alpha)
            size = (1.0 + 2.5 * (1.0 - depth / self._far)) * prominence * scale
            painter.setBrush(colour)
            if size < _STAR_POINT_MIN * scale:
                painter.drawEllipse(QPointF(x, y), size * 0.6, size * 0.6)
                continue
            long_arm, waist = size * spike, size * 0.45
            painter.drawPolygon(QPolygonF([
                QPointF(x, y - long_arm), QPointF(x + waist, y - waist),
                QPointF(x + long_arm, y), QPointF(x + waist, y + waist),
                QPointF(x, y + long_arm), QPointF(x - waist, y + waist),
                QPointF(x - long_arm, y), QPointF(x - waist, y - waist),
            ]))
            painter.setBrush(QColor(255, 255, 255, int(200 * alpha)))
            painter.drawEllipse(QPointF(x, y), size * 0.35, size * 0.35)

    def _fade_rings(self, geometry: dict, ring_s) -> None:
        """How bright each ring and each ring's spokes are drawn.

        Two different curves on purpose. Both fade with distance, but a ring
        *also* dissolves as it reaches the camera: one passing beside the lens
        on a bend would otherwise draw a bright chord across the whole frame,
        and raising the near plane to hide that makes rings pop instead. The
        spokes get the depth fade alone, because they have to reach the lens —
        they are what puts the viewer inside the tube.
        """
        depth_fade = np.clip(1.0 - (ring_s - self._cam_s) / self._far, 0.0, 1.0) ** _FADE_EXP
        geometry["spoke_fade"] = depth_fade
        geometry["ring_fade"] = depth_fade * np.clip(
            (geometry["nearest"] - _NEAR) / _NEAR_FADE, 0.0, 1.0
        )

    def _paint_mesh(self, painter, geometry, ring_s, level, pulse,
                    alpha_scale: float = 1.0) -> None:
        """The old wireframe tube, now a whisper under the cloud.

        *alpha_scale* dims it through the pen colours rather than through
        ``self._color``, which the sky's palette is derived from: scaling the
        attribute instead would fade the sky along with it.
        """
        sx, sy = geometry["sx"], geometry["sy"]
        ahead, spoke_ok = geometry["ahead"], geometry["spoke_ok"]
        depth_fade, ring_fade = geometry["spoke_fade"], geometry["ring_fade"]
        bright = (0.55 + 0.45 * min(1.0, level * 1.5 + pulse)) * alpha_scale
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for k in range(_RINGS):
            ring_alpha = int(255 * ring_fade[k] * bright)
            spoke_alpha = int(255 * depth_fade[k] * bright)
            if ring_alpha <= 2 and spoke_alpha <= 2:
                continue
            if ring_alpha > 2:
                colour = QColor(self._color)
                colour.setAlpha(ring_alpha)
                painter.setPen(QPen(colour, _PEN_WIDTH))
                if ahead[k].all():
                    painter.drawPolygon(QPolygonF(
                        [QPointF(sx[k, m], sy[k, m]) for m in range(_SEGMENTS)]
                    ))
                else:
                    # Only the edges with both ends ahead of the near plane.
                    painter.drawLines([
                        QLineF(sx[k, m], sy[k, m],
                               sx[k, (m + 1) % _SEGMENTS], sy[k, (m + 1) % _SEGMENTS])
                        for m in range(_SEGMENTS)
                        if ahead[k, m] and ahead[k, (m + 1) % _SEGMENTS]
                    ])
            if k + 1 < _RINGS and depth_fade[k] > _SPOKE_CULL:
                colour = QColor(self._color)
                colour.setAlpha(max(spoke_alpha, 0))
                painter.setPen(QPen(colour, _PEN_WIDTH))
                painter.drawLines([
                    QLineF(geometry["spoke_x"][k, m], geometry["spoke_y"][k, m],
                           sx[k + 1, m], sy[k + 1, m])
                    for m in range(_SEGMENTS) if spoke_ok[k, m]
                ])

    def _puff_field(self, geometry, ring_s, level, pulse, scale) -> dict:
        """Every puff's colour, size, opacity and fate, as ``(ring, segment)`` grids.

        Deciding is separated from drawing for the reason the row menus are: a
        test can then ask what the wall *is* without a painter, and the loop
        that blits has nothing left to work out inside it.

        Everything here is a pure function of world arc length and the segment
        index — there is no per-frame state, so the 16 ms and 33 ms hosts
        render identical worlds and ``set_frame_interval`` has nothing to add.
        """
        sx, sy, z = geometry["puff_x"], geometry["puff_y"], geometry["puff_z"]
        width, height = self._image.width(), self._image.height()
        bright = 0.55 + 0.45 * min(1.0, level * 1.5 + pulse)
        arc = ring_s[:, None]
        seg = self._seg

        # Two independent hashes of the world position. Anchored to ``ring_s``
        # and never to the ring slot: slots re-seat every ``_SPACING`` unit, so
        # a property hashed from k makes the whole texture swim forward with
        # the camera instead of streaming past it.
        h1 = _hash01(arc * 12.9898 + seg * 78.233, 43758.5453)
        h2 = _hash01(arc * 39.3468 + seg * 11.135, 27183.1)

        # Additive puffs stack where the tube converges — the wireframe's
        # "bright knot" problem squared — so the cloud gets an extra far fade
        # over the mesh's own, and the far rings get half their puffs below.
        fade = geometry["spoke_fade"][:, None] ** _PUFF_FADE_EXP
        near = np.clip((z - _NEAR) / _NEAR_FADE, 0.0, 1.0)
        alpha = _PUFF_ALPHA * fade * near * bright * (0.6 + 0.4 * h2)

        radius = self._focal * _PUFF_WORLD_R * (0.7 + 0.6 * h1) / np.maximum(
            z, _DEPTH_FLOOR
        )
        np.minimum(radius, _PUFF_MAX_PX * scale, out=radius)

        keep = (z >= _NEAR) & (alpha >= _PUFF_ALPHA_CULL)
        keep &= radius >= _PUFF_MIN_PX * scale
        keep &= ~((radius < _PUFF_THIN_PX * scale) & self._seg_odd)
        # Off-screen with the puff's own radius as the margin, so one whose
        # centre has left the frame still paints the part that has not.
        keep &= (sx > -radius) & (sx < width + radius)
        keep &= (sy > -radius) & (sy < height + radius)

        hues = len(_NEBULA_PALETTE)
        # A smooth hue field over (arc length, angle) so one colour holds for a
        # stretch of tube and a stretch of wall, plus a hash jitter that
        # scatters its boundary rather than drawing it as a seam.
        field = 0.5 + 0.5 * np.sin(
            arc * _HUE_FIELD_S
            + _HUE_FIELD_SWIRL
            * np.sin(self._seg_theta * _HUE_FIELD_THETA + arc * _HUE_FIELD_TWIST)
        )
        hue = np.clip(
            field * hues + (h1 - 0.5) * _HUE_JITTER, 0.0, hues - 1e-6
        ).astype(int)
        variant = (h2 * _PUFF_VARIANTS).astype(int)
        # Nearest baked resolution to the diameter actually being drawn, which
        # is what lets smooth filtering stay off: measured 1.65 ms against 2.19
        # for the same puffs, and a soft blob within √2 of its own resolution
        # does not read as blocky.
        sprite = np.digitize(2.0 * radius, _PUFF_SIZE_SWITCH)

        return {
            "x": sx, "y": sy, "radius": radius, "alpha": alpha,
            "hue": hue, "variant": variant, "sprite": sprite, "keep": keep,
        }

    def _paint_nebula(self, painter, geometry, ring_s, level, pulse, scale) -> None:
        """The wall: additive cloud puffs at the mesh's own vertices.

        QPainter has no batched image-draw, so the blits stay a Python loop —
        but a short one, over the survivors of :meth:`_puff_field`'s culls
        alone, with every number already decided.

        Draw order does not matter: ``CompositionMode_Plus`` is addition, and
        addition commutes, so there is no back-to-front sort to pay for.
        """
        field = self._puff_field(geometry, ring_s, level, pulse, scale)
        keep = field["keep"].ravel()
        if not keep.any():
            return
        xs = field["x"].ravel()[keep].tolist()
        ys = field["y"].ravel()[keep].tolist()
        rs = field["radius"].ravel()[keep].tolist()
        alphas = field["alpha"].ravel()[keep].tolist()
        hue = field["hue"].ravel()[keep].tolist()
        variant = field["variant"].ravel()[keep].tolist()
        sprite = field["sprite"].ravel()[keep].tolist()

        was_smooth = painter.testRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform
        )
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        sprites = self._sprites
        for x, y, r, a, hu, var, size in zip(
            xs, ys, rs, alphas, hue, variant, sprite
        ):
            painter.setOpacity(a)
            painter.drawImage(
                QRectF(x - r, y - r, 2 * r, 2 * r), sprites[size][hu][var]
            )
        # Put the painter back: nothing follows the wall today, but whatever is
        # added after it would inherit Plus, an opacity and a render hint.
        painter.setOpacity(1.0)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, was_smooth)
