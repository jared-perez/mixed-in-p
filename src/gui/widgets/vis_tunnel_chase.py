"""Tunnel Chase: the wormhole's sibling, flown to the beat.

Same wireframe tube and the same O(lines) cost, but where the wormhole flies a
frozen closed loop at a speed set by the level, this one is **generated ahead
of the camera in beat-space**: arc length is measured in beats
(``UNITS_PER_BEAT`` world units each), so a turn scheduled for beat 16 is a
bend in the tube at 16 × U units, and the camera reaches it exactly when the
music does. Speed is therefore the tempo, not the volume.

The turn schedule is the brief, in two lines: **a turn on the first beat of
every bar, and a second one on the third beat of every fourth bar.** That
gives a plain four-bar phrase you can feel — three ordinary bars and one that
swings twice.

Why it cannot be a precomputed loop like the wormhole's: the turns have to
fall where the *beats* fall, so the loop's turn spacing would have to be
locked to the beat grid and its length to the tempo, and every tempo change
would need a new loop. Generating ahead is both simpler and exact.

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
* **It owns its image and follows the host's aspect**, like the wormhole —
  a wireframe stretched non-uniformly draws ellipses for rings — and that
  image is never assigned to ``VisRenderer._image``.

The beat itself comes from :class:`~.beat_clock.BeatClock`; no audio and no
tempo estimation happens here. :meth:`TunnelChaseScene.render` takes a phase
in beats, a level and a kick pulse as plain numbers.
"""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QLineF, QPointF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QPainter,
    QPen,
    QPolygonF,
    QRadialGradient,
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
# there, which is the same property the wormhole's frozen waypoints have.
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
_N_PLANETS = 3
_STAR_FLOOR = 0.15  # a star's depth alpha between kicks
_STAR_DECAY_AT_33MS = 0.82  # the wormhole's release, as a time constant
_STAR_POINT_MIN = 1.8  # below this a star is a dot rather than a 4-point star
_PLANET_RADIUS = (0.6, 1.8)  # world units

# Planet variety. The pale cream the whole field used to be is still most of
# it — its brightness was judged right in the running app, so nothing below
# touches it — and these are the exceptions rolled once, at spawn.
#
# They are chances rather than counts because there are only three planets on
# screen at a time, and a "small percentage" is a property of the stream rather
# than of the three. Measured over three minutes at 128 BPM: **about fifty
# planets a minute**, of which nine are dusky, nine wear the wireframe's own
# colour and ten carry rings. (Fifty is more churn than the geometry suggests —
# a planet spawns 22 to 42 units out and travels at 5.3 units a second, so it
# should last four to eight — because a turn swings the ones off to the side
# out of the depth window early. Same for the stars; it is not new here.)
_PLANET_DARK_CHANCE = 0.18
_PLANET_TINT_CHANCE = 0.18
_PLANET_DARK = 0.62  # value multiplier on the cream: a rock, not an ice ball
_PLANET_TINT_WASH = 0.22  # how far the tinted one is washed toward white

# Rings: thin, concentric, and in a plane of their own per planet. The span is
# in planet radii, and the rings are spread across it rather than drawn at
# random radii, so two of them never land on top of each other and read as one
# thick band. 36 segments is enough that a ring seen nearly face-on has no
# visible corners at the sizes a planet ever reaches (its radius is capped by
# `_PLANET_RADIUS` and it is culled below 1.5 px).
_PLANET_RING_CHANCE = 0.22
_PLANET_RING_COUNT = 3  # at most; 1 to this many
_PLANET_RING_SPAN = (1.35, 2.15)  # planet radii
_PLANET_RING_SEGMENTS = 36
_PLANET_RING_PEN = 1.15  # px at the 512-high reference

# A ring is brighter than the planet it circles, and has to be: the disc gets
# its alpha over thousands of pixels and the ring over a one-pixel line, so at
# the alpha the disc is comfortable at — around 0.3 by the time the depth fade
# and the between-kicks glow floor have both been applied — the ring simply is
# not there. Rendered against a real flight, 1.0 was invisible and this reads at
# every distance a planet is drawn at. The ceiling is what stops a close pass —
# where the disc's own alpha is already near 1 — from putting the brightest line
# in the frame around a planet: the tunnel is the subject, and the sky, rings
# included, is depth behind it.
_PLANET_RING_ALPHA = 1.8  # multiplier on the planet's own alpha
_PLANET_RING_MAX_ALPHA = 0.85

_HISTORY = 4.0  # world units of path kept behind the camera

_GREY = (205, 205, 215)


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
    into a bend — the property the wormhole's closed loop had to buy with a
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


class TunnelChaseScene:
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
        self._stars = np.empty((_N_STARS, 3))
        self._star_kind = np.empty(_N_STARS, int)
        self._planets = np.empty((_N_PLANETS, 4))  # x, y, z, radius
        self._planet_kind = np.zeros(_N_PLANETS, int)
        # Two perpendicular directions spanning each planet's ring plane, and
        # the radii (in planet radii) of the rings drawn in it — 0 for a ring
        # slot this planet does not use.
        self._planet_ring_basis = np.zeros((_N_PLANETS, 2, 3))
        self._planet_ring_radii = np.zeros((_N_PLANETS, _PLANET_RING_COUNT))
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
        for i in range(_N_PLANETS):
            # Nearer than a respawn on purpose: the first seconds should have
            # planets in them rather than an empty sky waiting for the first
            # one to arrive.
            self._spawn_planet(i, self._rng.uniform(self._far * 0.5, self._far * 1.5))
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
        wireframe draws ellipses where the rings should be, and a host smaller
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
        # Kept rather than passed straight through: a QPainter cannot be
        # recorded (its draw methods are not virtual), so the near-plane rules
        # are asserted against the numbers the painter is handed.
        self._geometry = geometry = self._project(rel)
        self._fade_rings(geometry, ring_s)

        self._advance_stars(basis, cam)
        self._advance_planets(basis, cam)
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

    def _spawn_planet(self, index: int, depth: float | None = None) -> None:
        """A fresh planet: where, how big, which tint, and whether it wears rings.

        Everything about a planet is decided here and then left alone, so a
        planet does not change colour or grow rings while it is on screen.
        """
        if depth is None:
            depth = self._rng.uniform(self._far * 0.8, self._far * 1.5)
        self._planets[index, :3] = self._spawn(depth, margin=2.5)
        self._planets[index, 3] = self._rng.uniform(*_PLANET_RADIUS)

        roll = self._rng.random()
        if roll < _PLANET_DARK_CHANCE:
            self._planet_kind[index] = 1
        elif roll < _PLANET_DARK_CHANCE + _PLANET_TINT_CHANCE:
            self._planet_kind[index] = 2
        else:
            self._planet_kind[index] = 0

        self._planet_ring_radii[index] = 0.0
        if self._rng.random() >= _PLANET_RING_CHANCE:
            return
        # A plane through the planet at a random attitude: take a normal off
        # the sphere and any two perpendiculars to it. The normal is drawn from
        # a Gaussian rather than from two uniform angles because that is
        # uniform on the sphere — polar angles bunch the normals at the poles,
        # which would give most ringed planets a near-edge-on band.
        normal = self._rng.normal(size=3)
        normal /= np.linalg.norm(normal)
        aside = np.array([0.0, 0.0, 1.0]) if abs(normal[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
        u = np.cross(normal, aside)
        u /= np.linalg.norm(u)
        self._planet_ring_basis[index] = np.stack([u, np.cross(normal, u)])

        count = int(self._rng.integers(1, _PLANET_RING_COUNT + 1))
        inner, outer = _PLANET_RING_SPAN
        for slot in range(count):
            band = (outer - inner) / count
            low = inner + band * slot
            self._planet_ring_radii[index, slot] = self._rng.uniform(low, low + band * 0.65)

    def _rigid(self, basis, cam):
        """Rotation and offset carrying last frame's camera coordinates into this one's.

        ``None`` on the first frame, where there is no previous camera to come
        from. Stars and planets live in camera coordinates — projecting is then
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

    def _advance_planets(self, basis, cam) -> None:
        """As the stars, plus the ring planes.

        A ring's plane is fixed in the world like the planet it belongs to, so
        its two basis vectors take the rotation and **not** the offset: they are
        directions, not points. Skipping that would leave the rings facing the
        camera the same way through every turn, which reads as the plane
        swinging round to follow you.
        """
        move = self._rigid(basis, cam)
        if move is not None:
            rotation, offset = move
            self._planets[:, :3] = self._planets[:, :3] @ rotation.T + offset
            self._planet_ring_basis[:] = self._planet_ring_basis @ rotation.T
        z = self._planets[:, 2]
        for i in np.flatnonzero((z < 0.5) | (z > self._far * 1.6)):
            self._spawn_planet(i)

    def _wash(self, white: float) -> QColor:
        """The wireframe colour mixed *white* of the way toward white."""
        main = self._color
        return QColor(
            int(main.red() * (1 - white) + 255 * white),
            int(main.green() * (1 - white) + 255 * white),
            int(main.blue() * (1 - white) + 255 * white),
        )

    def _palette(self) -> list[QColor]:
        """Grey, and two washes of the wireframe colour toward white.

        Paler than the mesh on purpose (the brief): the tunnel is the subject
        and the sky is depth behind it.
        """
        return [QColor(*_GREY), self._wash(0.65), self._wash(0.4)]

    def _planet_tints(self) -> list[QColor]:
        """Cream, a dusky one, and one wearing the wireframe's own colour.

        The first is the shade every planet used to be, unchanged: its
        brightness was judged right in the running app, and the point of the
        other two is variety at the same brightness budget rather than a
        different one. The dusky planet is that cream taken down in value, so
        it stays the same hue and reads as rock beside an ice ball; the tinted
        one is barely washed at all, which is the only way the colour survives
        being drawn at a fraction of full alpha on black.
        """
        pale = self._wash(0.65)
        dark = QColor(
            int(pale.red() * _PLANET_DARK),
            int(pale.green() * _PLANET_DARK),
            int(pale.blue() * _PLANET_DARK),
        )
        return [pale, dark, self._wash(_PLANET_TINT_WASH)]

    # ── Paint ──────────────────────────────────────────────────────────────

    def _paint(self, geometry: dict, ring_s, level: float, pulse: float) -> None:
        width, height = self._image.width(), self._image.height()
        scale = height / _REF_H  # the pixel sizes below were tuned at 512 high
        self._image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self._image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = self._palette()
        glow = _STAR_FLOOR + (1.0 - _STAR_FLOOR) * self._star_glow

        self._paint_planets(painter, self._planet_tints(), width, height, glow, scale)
        self._paint_stars(painter, palette, width, height, glow, scale)
        self._paint_mesh(painter, geometry, ring_s, level, pulse)
        painter.end()

    def _paint_planets(self, painter, tints, width, height, glow, scale) -> None:
        """Sparse shaded discs, behind everything. Three at a time, far out.

        A ringed planet is drawn in three passes — the half of each ring behind
        the planet, the disc, then the half in front — which is what makes the
        band pass *through* rather than sit on top. The disc's own alpha is
        what dims the far half; nothing else is done about it.
        """
        for index, (x, y, z, radius) in enumerate(self._planets):
            if z <= 0.2:
                continue
            px = width / 2 + self._focal * x / z
            py = height / 2 - self._focal * y / z
            pr = self._focal * radius / z
            if pr < 1.5 * scale or not (-pr <= px <= width + pr and -pr <= py <= height + pr):
                continue
            alpha = float(np.clip(1.15 - z / (self._far * 1.6), 0.15, 1.0))
            near = QColor(tints[int(self._planet_kind[index])])
            near.setAlphaF(alpha * (0.35 + 0.65 * glow))

            behind, in_front = self._ring_arcs(index, width, height)
            self._paint_ring_arcs(painter, behind, near, scale)

            limb = QColor(near)
            limb.setAlphaF(near.alphaF() * 0.25)
            shade = QRadialGradient(px - pr * 0.35, py - pr * 0.35, pr * 1.3)
            shade.setColorAt(0.0, near)
            shade.setColorAt(1.0, limb)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(shade))
            painter.drawEllipse(QPointF(px, py), pr, pr)

            self._paint_ring_arcs(painter, in_front, near, scale)

    def _ring_arcs(self, index: int, width: int, height: int):
        """This planet's rings, projected and split into behind-it and in-front-of-it.

        Returns two lists of :class:`QLineF`. A ring is a circle in the world,
        so it projects to an ellipse and is drawn as segments; splitting them by
        whether each end is nearer than the planet's centre is exactly the
        Saturn silhouette, and costs a comparison per segment.
        """
        radii = self._planet_ring_radii[index]
        if not radii.any():
            return [], []
        cx, cy, cz, radius = self._planets[index]
        u, v = self._planet_ring_basis[index]
        theta = np.linspace(0, 2 * np.pi, _PLANET_RING_SEGMENTS, endpoint=False)
        rim = np.cos(theta)[:, None] * u + np.sin(theta)[:, None] * v
        centre = np.array([cx, cy, cz])
        behind: list[QLineF] = []
        in_front: list[QLineF] = []
        for factor in radii:
            if factor <= 0.0:
                continue
            points = centre + rim * (factor * radius)
            depth = points[:, 2]
            if depth.min() <= 0.2 or self._focal * factor * radius / cz < 2.0:
                continue  # behind the lens, or too small to be anything but a smudge
            sx = width / 2 + self._focal * points[:, 0] / depth
            sy = height / 2 - self._focal * points[:, 1] / depth
            nearer = depth < cz
            for m in range(_PLANET_RING_SEGMENTS):
                n = (m + 1) % _PLANET_RING_SEGMENTS
                line = QLineF(sx[m], sy[m], sx[n], sy[n])
                (in_front if nearer[m] and nearer[n] else behind).append(line)
        return behind, in_front

    def _ring_colour(self, disc: QColor) -> QColor:
        """The disc's colour, brightened for a line and held under the ceiling."""
        lit = QColor(disc)
        lit.setAlphaF(min(_PLANET_RING_MAX_ALPHA, disc.alphaF() * _PLANET_RING_ALPHA))
        return lit

    def _paint_ring_arcs(self, painter, lines, colour: QColor, scale: float) -> None:
        if not lines:
            return
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(self._ring_colour(colour), max(_PLANET_RING_PEN * scale, 0.8)))
        painter.drawLines(lines)

    def _paint_stars(self, painter, palette, width, height, glow, scale) -> None:
        """Dots far out, four-point stars with a white core near.

        The glow scales the whole field, so depth still orders them: a near
        star between kicks stays brighter than a far one, just barely lit.
        """
        z = self._stars[:, 2]
        xs = width / 2 + self._focal * self._stars[:, 0] / z
        ys = height / 2 - self._focal * self._stars[:, 1] / z
        painter.setPen(Qt.PenStyle.NoPen)
        for x, y, depth, kind in zip(xs, ys, z, self._star_kind):
            if depth <= 0.2 or not (0 <= x < width and 0 <= y < height):
                continue
            alpha = float(np.clip(1.1 - depth / self._far, 0.15, 1.0)) * glow
            colour = QColor(palette[kind])
            colour.setAlphaF(alpha)
            size = (1.0 + 2.5 * (1.0 - depth / self._far)) * scale
            painter.setBrush(colour)
            if size < _STAR_POINT_MIN * scale:
                painter.drawEllipse(QPointF(x, y), size * 0.6, size * 0.6)
                continue
            long_arm, waist = size * 1.8, size * 0.45
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

    def _paint_mesh(self, painter, geometry, ring_s, level, pulse) -> None:
        sx, sy = geometry["sx"], geometry["sy"]
        ahead, spoke_ok = geometry["ahead"], geometry["spoke_ok"]
        depth_fade, ring_fade = geometry["spoke_fade"], geometry["ring_fade"]
        bright = 0.55 + 0.45 * min(1.0, level * 1.5 + pulse)
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
