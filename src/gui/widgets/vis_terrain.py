"""Terrain flight: soaring over a wireframe mountain range, mirrored overhead.

**The menu calls this "Mountain flight"**; ``terrain`` is the id, named for the
mechanism (a scrolling heightfield) like the tunnels' ids, so the label can be
re-judged without a config migration.

A heightfield scrolls toward the camera. Rows sit at fixed *world* depths and
slide past as the camera advances (the loop tunnel's rings, laid flat); each
time the camera passes one, the buffer rolls and a new row is **born at the
far edge** — on the horizon, mid-screen — from the music at that moment. Its
height is the level through a fast-attack/slow-release follower, times a
lateral ridge profile (two value-noise layers drifting sideways row by row,
multiplied, so ridges run diagonally rather than as parallel walls), plus a
peak the kick plants at a random spot that decays over the next few rows. A
loud passage therefore builds a range on the horizon and a quiet one a plain,
and what was built takes a few seconds to arrive. The newest rows also rise
out of the horizon over their first few rows of life, so the range visibly
*grows* in the distance instead of popping in fully formed.

The ground is mirrored overhead: one height buffer, drawn as a floor at
``-ALT`` and a ceiling at ``+ALT``, with the camera flying the corridor between
them. The centre columns are hollowed into a valley so no peak ever reaches the
flight line.

The camera soars rather than rails: yaw wanders on two incommensurate sines,
the bank follows the yaw *rate* (a bird leans into its turn, and levels out
through it), pitch and altitude bob on their own slow sines. Every one of
those, and the travel and the follower, is written in **seconds** and rescaled
in :meth:`TerrainScene.set_frame_interval`, so the 16 ms and 33 ms hosts fly
the same flight (see CLAUDE.md on per-frame decays).

Same rendering choice as the loop tunnel: antialiased lines into an image that
shares the host's aspect (a stretched wireframe draws the wrong perspective),
sized from device pixels under a per-host cap. The cost is O(lines) — but there
are several times more lines than in the tunnel, so the popout cap is lower
(measured in the constants below).

No audio code lives here: :meth:`TerrainScene.render` takes a level and a
kick pulse as plain numbers and :class:`~.vis_canvas.VisRenderer` supplies
them.
"""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QLineF, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF

from ..styles.theme import Theme

# Image size, in device pixels: the host's own size over _DOWNSCALE, under a
# per-host cap (see vis_loop_tunnel for why the caps exist and why the image
# follows the host's aspect). The pen is **one image pixel**, and the
# downscale is what gives the line its weight on screen: about two device
# pixels, softened by the host's smooth upscale, whatever the host.
#
# That is a cost decision, measured. Qt's raster engine strokes an
# antialiased pen wider than one pixel through the general path stroker, and
# the ~1200 lines of a frame cost 14 ms that way at 1575x900 against 5 ms for
# a pen of one pixel — a cliff at exactly 1.0, not a slope. Rendering the
# thick pen without antialiasing is 3 ms but staircases (measured on a crop at
# 1:1 after the host's upscale). A one-pixel antialiased line at half the
# host's resolution, blown up smoothly, is 3.5 ms and the cleanest of the
# four. The loop tunnel's "pen scaled with the image" rule is therefore not
# followed here; this mode's line weight is a property of the image size.
POPOUT_CAP = (1400, 700)
BACKDROP_CAP = (1000, 400)
_DOWNSCALE = 2.0  # device pixels per image pixel, before the cap
_MIN_H = 64
_DEFAULT_FRAME_MS = 33.0

# Vertical field of view; a wider host shows more to the sides. Narrower
# than the tunnels' 95°, on purpose: a wide lens shrinks the far range into a
# ripple on the horizon, and the range is the picture. At 50° a peak on the
# horizon stands about 80% taller on screen than it did at 80°.
_FOV_DEG = 50.0
ALT = 1.0  # camera height above the valley floor, and below the ceiling
# The tallest peak as a fraction of ALT. This ratio *is* the picture: at 0.85
# one near ridge hid everything behind it and the flight read as skimming
# between two hills; at 0.55 a dozen silhouettes stack up the lower half.
MAX_H = 0.55
_NEAR = 0.3  # depth of the nearest row; a flat row leaves the frame below ~2.1
ROWS = 22
SPACING = 0.35  # world units between rows: the far plane is ~8 units out
# Columns are world-fixed (so the mesh lines *are* the terrain, and a peak
# stays on its lines as it approaches) but not uniform: spacing grows
# geometrically from the centre. A uniform grid wide enough for the far view
# on a 3:1 popout leaves two lines on screen at the near rows; this keeps a
# handful there while still reaching ±47 units — past the edge of a 3:1 popout
# at the far plane, yawed.
_COLS_PER_SIDE = 24
_COL_SPACING = 0.4  # world units between the two centre columns
_COL_GROWTH = 1.12  # each column outward is this much further than the last
_BASE_SPEED = 4.2  # world units per second with no audio
_SPEED_LEVEL = 1.5  # extra travel at full level, as a multiple of base
# Depth fade for the line alpha. Rows pile toward the horizon (uniform world
# spacing, 1/z on screen) and the far dozen read as a solid band unless they
# go dim; the newest rows are still seen being built because they rise out
# of the horizon (_RISE_ROWS) as they brighten.
_FADE_EXP = 2.0
_RISE_ROWS = 4  # a newborn row rises from flat to full height over this many rows
# Spokes (the lines running away from the camera) are drawn only in the near
# field, fading out toward _SPOKE_FAR. Beyond it the rows are ridgelines
# alone: that is what a range on the horizon looks like, and it is also what
# stops every spoke converging into a bright knot at the vanishing point —
# which was both the ugliest and the most expensive part of the first cut.
_SPOKE_NEAR = 3.0  # full alpha inside this depth
_SPOKE_FAR = 6.5  # none beyond this
_SPOKE_ALPHA = 0.35  # of the ridgeline's: silhouettes carry the picture
_PEN_WIDTH = 1.0  # image px — never more, see the note on _DOWNSCALE

# The camera's soaring, in degrees and seconds. Two incommensurate sines for
# the yaw so the wander never repeats visibly; the bank is the yaw *rate*
# times a lag (bank into the turn, level out through it) plus a small sway of
# its own so a straight glide still rocks.
_YAW_DEG = 7.0
_YAW_PERIODS = (19.0, 7.7)
_YAW_WEIGHTS = (1.0, 0.45)
_BANK_S = 2.6  # degrees of roll per degree/s of yaw rate (~13° on the sharpest turn)
_ROLL_DEG = 3.0
_ROLL_PERIOD = 11.3
_PITCH_DEG = 3.5
_PITCH_PERIOD = 13.1
_BOB = 0.06  # world units of altitude bob
_BOB_PERIOD = 8.9

# What a new row is made of.
_AMP_RELEASE_S = 1.0  # e-fold time of the level follower's release
_AMP_FULL_LEVEL = 0.55  # the level at which the range is built at full height
_FLOOR = 0.15  # fraction of full height the range keeps in silence
_NOISE_CELLS = (1.8, 4.5)  # world units per noise cell, the two ridge layers
_NOISE_DRIFT = (0.5, -0.3)  # lateral drift per row of each layer: diagonal ridges
_ROCK_CELL = 0.8  # a third, finer layer added on top: rock, not rolling hills
_ROCK_AMP = 0.3
_NOISE_TABLE = 128  # random values per layer (the noise period, in cells)
_RIDGE_NORM = 0.25  # noise product at which a ridge is full height
_RIDGE_POWER = 2.5  # >1 sharpens ridges into peaks
_VALLEY_WIDTH = 2.0  # world units: the flight corridor's half-width (gaussian)
_VALLEY_DEPTH = 0.1  # fraction of height removed at the very centre
_ROW_MEMORY = 0.3  # weight of the previous row in a new one: ridge continuity
_PEAK_MIN_PULSE = 0.35  # a kick weaker than this plants nothing
_PEAK_HEIGHT = 0.7  # x pulse, as a fraction of MAX_H
_PEAK_WIDTH = 1.5  # world units (gaussian sigma)
_PEAK_DECAY = 0.86  # per row: the peak's footprint along the flight
_PEAK_SPREAD = 7.0  # a peak lands within ± this of the centre line: in view at the far plane
_DEPTH_EPS = 0.05  # camera-space depth below which a point is not drawn


def _value_noise(x: np.ndarray, cell: float, table: np.ndarray) -> np.ndarray:
    """1-D value noise in 0..1 at arbitrary positions, cosine-interpolated.

    *table* holds the control values, one per *cell* world units, and wraps
    (so the layer is periodic at ``len(table) * cell`` units — wider than the
    strip even for the finest layer, so no ridge repeats across the view).
    """
    u = x / cell
    i0 = np.floor(u).astype(int)
    f = u - i0
    f = 0.5 - 0.5 * np.cos(np.pi * f)
    n = len(table)
    return table[i0 % n] * (1.0 - f) + table[(i0 + 1) % n] * f


def column_positions(per_side: int = _COLS_PER_SIDE, spacing: float = _COL_SPACING,
                     growth: float = _COL_GROWTH) -> np.ndarray:
    """World x of every mesh column, symmetric about 0, geometric spacing."""
    steps = spacing * growth ** np.arange(per_side)
    right = np.cumsum(steps) - steps[0] / 2.0  # first column half a step out
    return np.concatenate([-right[::-1], right])


class TerrainScene:
    """The terrain flight's own state and image; driven by level and kick pulse."""

    def __init__(self) -> None:
        self._color = QColor(Theme.WAVEFORM_DEFAULT)
        self._image = QImage(
            BACKDROP_CAP[0], BACKDROP_CAP[1], QImage.Format.Format_ARGB32_Premultiplied
        )
        self._image.fill(Qt.GlobalColor.transparent)
        self._focal = (self._image.height() / 2) / math.tan(math.radians(_FOV_DEG) / 2)
        self._x = column_positions()
        # Heights as a fraction of MAX_H: index 0 is the row just ahead of the
        # camera, index ROWS the newest, on the horizon.
        self._rows = np.zeros((ROWS + 1, len(self._x)))
        self._far = _NEAR + (ROWS + 1) * SPACING
        self._sway = 1.0
        self._dt = _DEFAULT_FRAME_MS / 1000.0
        self._amp_release = math.exp(-self._dt / _AMP_RELEASE_S)
        self._rng = np.random.default_rng(7)
        self._tables: tuple[np.ndarray, ...] = ()
        self._s = 0.0
        self._born = 0
        self._time = 0.0
        self._amp = 0.0
        self._pending_kick = 0.0
        self._peak: list[float] | None = None
        self.reset()

    # ── Public API ─────────────────────────────────────────────────────────

    def image(self) -> QImage:
        return self._image

    def set_color(self, color: QColor | str) -> None:
        self._color = QColor(color)

    def set_sway(self, amount: float) -> None:
        """Scale the camera's soaring: 1.0 is the tuned flight, 0.0 a rail."""
        self._sway = float(amount)

    def set_frame_interval(self, frame_ms: float) -> None:
        """Tell the scene how often it is advanced; every rate here is per second."""
        if frame_ms <= 0:
            return
        self._dt = frame_ms / 1000.0
        self._amp_release = math.exp(-self._dt / _AMP_RELEASE_S)

    def reset(self) -> None:
        """Back to the start: a flat plain, level flight, the same ridges again."""
        self._s = 0.0
        self._born = 0
        self._time = 0.0
        self._amp = 0.0
        self._pending_kick = 0.0
        self._peak = None
        self._rows[:] = 0.0
        # Re-seeded so a reset replays the same range for the same music,
        # which is what makes a test's flight repeatable.
        self._rng = np.random.default_rng(7)
        self._tables = tuple(
            self._rng.uniform(0.0, 1.0, _NOISE_TABLE) for _ in (*_NOISE_CELLS, _ROCK_CELL)
        )
        self._image.fill(Qt.GlobalColor.transparent)

    def set_target_size(self, width: int, height: int, popout: bool = False) -> None:
        """Match the image to the host's shape and size, capped by frame cost.

        Device pixels in, aspect preserved, never upscaled, reallocated only
        on a real change, and a host that is not on screen yet (zero or
        negative) keeps the previous size — the loop tunnel's rules, for the
        loop tunnel's reasons.
        """
        if width <= 0 or height <= 0:
            return
        cap_w, cap_h = POPOUT_CAP if popout else BACKDROP_CAP
        scale = min(cap_w / width, cap_h / height, 1.0 / _DOWNSCALE)
        target_w = max(2 * _MIN_H, int(round(width * scale)))
        target_h = max(_MIN_H, int(round(height * scale)))
        if (target_w, target_h) == (self._image.width(), self._image.height()):
            return
        self._image = QImage(
            target_w, target_h, QImage.Format.Format_ARGB32_Premultiplied
        )
        self._image.fill(Qt.GlobalColor.transparent)
        self._focal = (target_h / 2) / math.tan(math.radians(_FOV_DEG) / 2)

    def camera_angles(self, t: float | None = None) -> tuple[float, float, float]:
        """``(yaw, pitch, roll)`` in degrees at flight time *t* (default: now)."""
        yaw, pitch, roll, _bob = self._sway_at(self._time if t is None else t)
        return yaw, pitch, roll

    def heights(self) -> np.ndarray:
        """A copy of the height buffer, ``(ROWS + 1, columns)``, nearest row
        first, as fractions of ``MAX_H``."""
        return self._rows.copy()

    def row_depths(self) -> np.ndarray:
        """Camera-relative depth of every buffered row, nearest first."""
        return (self._born + np.arange(ROWS + 1)) * SPACING - self._s + _NEAR

    def render(self, level: float, pulse: float) -> QImage:
        """Advance one frame and paint it. *level* and *pulse* are 0..1."""
        self._time += self._dt
        self._amp = max(min(level / _AMP_FULL_LEVEL, 1.0), self._amp * self._amp_release)
        self._pending_kick = max(self._pending_kick, pulse)
        self._s += _BASE_SPEED * (1.0 + _SPEED_LEVEL * level) * self._dt
        # Every row the camera has passed since last frame is retired and a
        # new one born on the horizon. Normally one at most; a while, because
        # a rate is a rate.
        while self._s >= self._born * SPACING:
            self._bear_row()

        width, height = self._image.width(), self._image.height()
        yaw, pitch, roll, bob = self._sway_at(self._time)
        basis = self._basis(yaw, pitch, roll)
        z = self.row_depths()
        # Newborn rows rise out of the horizon over their first few rows.
        grow = np.clip((self._far - z) / (_RISE_ROWS * SPACING), 0.0, 1.0)
        heights = self._rows * (MAX_H * ALT) * grow[:, None]  # (rows, cols)
        x = np.broadcast_to(self._x[None, :], heights.shape)
        zz = np.broadcast_to(z[:, None], heights.shape)
        ground = np.stack([x, -ALT + heights - bob, zz], axis=-1)
        ceiling = np.stack([x, ALT - heights - bob, zz], axis=-1)
        projected = [self._project(mesh @ basis, width, height) for mesh in (ground, ceiling)]

        fade = np.clip(1.0 - z / self._far, 0.0, 1.0) ** _FADE_EXP
        bright = 0.55 + 0.45 * min(1.0, level * 1.5 + pulse)
        spokes = np.clip((_SPOKE_FAR - z) / (_SPOKE_FAR - _SPOKE_NEAR), 0.0, 1.0)
        # Where "down the mountainside" points on screen: world -y under the
        # roll (pitch and yaw barely move it, and it only has to reach off
        # the frame). The ceiling's is the opposite.
        down = (math.sin(math.radians(roll)), math.cos(math.radians(roll)))
        self._paint(projected, fade * bright, spokes, width, height, down)
        return self._image

    # ── Internals ──────────────────────────────────────────────────────────

    def _bear_row(self) -> None:
        """Retire the nearest row and build a new one on the horizon."""
        x = self._x
        n = self._born
        ridge = np.ones_like(x)
        for table, cell, drift in zip(self._tables, _NOISE_CELLS, _NOISE_DRIFT):
            ridge = ridge * _value_noise(x + drift * n, cell, table)
        ridge = np.clip(ridge / _RIDGE_NORM, 0.0, 1.0) ** _RIDGE_POWER
        rock = _value_noise(x + 0.4 * n, _ROCK_CELL, self._tables[-1])
        ridge = np.clip(ridge + _ROCK_AMP * (rock - 0.5), 0.0, 1.0)
        valley = 1.0 - _VALLEY_DEPTH * np.exp(-((x / _VALLEY_WIDTH) ** 2))
        fresh = (_FLOOR + (1.0 - _FLOOR) * self._amp) * ridge * valley
        # The kick's peak: planted where the strongest kick since the last row
        # asks, and carried (decaying) into the rows that follow so it is a
        # mountain with a footprint, not a wall one row thick.
        if self._pending_kick >= _PEAK_MIN_PULSE and self._peak is None:
            self._peak = [
                float(self._rng.uniform(-_PEAK_SPREAD, _PEAK_SPREAD)),
                _PEAK_HEIGHT * self._pending_kick,
            ]
        self._pending_kick = 0.0
        if self._peak is not None:
            px, ph = self._peak
            fresh = fresh + ph * np.exp(-(((x - px) / _PEAK_WIDTH) ** 2))
            self._peak[1] *= _PEAK_DECAY
            if self._peak[1] < 0.02:
                self._peak = None
        row = _ROW_MEMORY * self._rows[-1] + (1.0 - _ROW_MEMORY) * fresh
        self._rows = np.roll(self._rows, -1, axis=0)
        self._rows[-1] = np.minimum(row, 1.0)
        self._born += 1

    def _sway_at(self, t: float) -> tuple[float, float, float, float]:
        """``(yaw, pitch, roll, bob)`` — degrees, degrees, degrees, world units."""
        two_pi = 2.0 * math.pi
        yaw = 0.0
        yaw_rate = 0.0
        for period, weight in zip(_YAW_PERIODS, _YAW_WEIGHTS):
            w = two_pi / period
            yaw += weight * math.sin(w * t)
            yaw_rate += weight * w * math.cos(w * t)
        yaw *= _YAW_DEG
        yaw_rate *= _YAW_DEG
        roll = _BANK_S * yaw_rate + _ROLL_DEG * math.sin(two_pi * t / _ROLL_PERIOD)
        pitch = _PITCH_DEG * math.sin(two_pi * t / _PITCH_PERIOD)
        bob = _BOB * math.sin(two_pi * t / _BOB_PERIOD)
        s = self._sway
        return yaw * s, pitch * s, roll * s, bob * s

    @staticmethod
    def _basis(yaw: float, pitch: float, roll: float) -> np.ndarray:
        """Camera axes as columns (right, up, forward) in world coordinates.

        Yaw positive turns right, pitch positive noses up, roll positive
        drops the right wing — so banking into a right turn lifts the right
        end of the horizon on screen, the way it does from a cockpit.
        Composed yaw ∘ pitch ∘ roll; camera coordinates are ``p @ basis``.
        """
        cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
        cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
        cr, sr = math.cos(math.radians(roll)), math.sin(math.radians(roll))
        ry = np.array([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]])
        rx = np.array([[1.0, 0.0, 0.0], [0.0, cp, sp], [0.0, -sp, cp]])
        rz = np.array([[cr, sr, 0.0], [-sr, cr, 0.0], [0.0, 0.0, 1.0]])
        return ry @ rx @ rz

    def _project(self, cam: np.ndarray, width: int, height: int):
        """Camera-space points (rows, cols, 3) → ``(sx, sy, depth)`` arrays."""
        depth = cam[..., 2]
        safe = np.where(depth > _DEPTH_EPS, depth, _DEPTH_EPS)
        sx = width / 2 + self._focal * cam[..., 0] / safe
        sy = height / 2 - self._focal * cam[..., 1] / safe
        return sx, sy, depth

    def _paint(self, meshes, alpha: np.ndarray, spokes: np.ndarray,
               width: int, height: int, down: tuple[float, float]) -> None:
        # Hidden-line removal, or the range reads as a rippling transparent
        # sheet: every ridgeline shows through the ones in front of it, and
        # the far rows pile into a bright band on the horizon. So this is a
        # painter's algorithm over the surface *patches* — the strip between
        # a row and the next nearer one — drawn far to near. Each patch is
        # *erased* (painted transparent, CompositionMode_Source, so the
        # backdrop composites the playlist through the mountain's body rather
        # than a black slab) before its far ridgeline and the spokes crossing
        # it are stroked; the next, nearer patch then erases whatever of them
        # it stands in front of. Filling each patch once, instead of the whole
        # region under each ridgeline, keeps the erased area to about the
        # frame's own size per mesh.
        #
        # Segments with an end behind the camera are dropped (with the camera
        # yawed, the far ends of a near row are), and so are segments wholly
        # off one side of the frame — the near rows are mostly that.
        big = 2.0 * (width + height)
        self._image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self._image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(self._color, _PEN_WIDTH)
        source = QPainter.CompositionMode.CompositionMode_Source
        over = QPainter.CompositionMode.CompositionMode_SourceOver

        def stroke(lines: list[QLineF], a: float) -> None:
            a = int(255 * a)
            if a <= 2 or not lines:
                return
            col = QColor(self._color)
            col.setAlpha(a)
            pen.setColor(col)
            painter.setPen(pen)
            painter.drawLines(lines)

        def erase(points: list[QPointF]) -> None:
            # Aliased on purpose: the fill's edge is under a stroked line
            # three pixels wide, and the antialiased fill cost as much as
            # all the lines together.
            if len(points) < 3:
                return
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            painter.setCompositionMode(source)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(Qt.GlobalColor.transparent)
            painter.drawPolygon(QPolygonF(points))
            painter.setCompositionMode(over)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        for sign, (sx, sy, depth) in zip((1.0, -1.0), meshes):
            dx, dy = sign * down[0] * big, sign * down[1] * big
            # Each row's visible run, once, as points.
            rows: list[list[QPointF]] = []
            # Coordinates clamped to a frame around the image: a point a
            # million pixels out is off the frame either way, and the
            # rasteriser is not made to iterate a bounding box that size.
            lo_x, hi_x, lo_y, hi_y = -width, 2 * width, -height, 2 * height
            for k in range(ROWS + 1):
                ok = depth[k] > _DEPTH_EPS
                xs = np.clip(sx[k][ok], lo_x, hi_x).tolist()
                ys = np.clip(sy[k][ok], lo_y, hi_y).tolist()
                rows.append([QPointF(x, y) for x, y in zip(xs, ys)])
            for k in range(ROWS, -1, -1):
                far = rows[k]
                if k >= 1:
                    near = rows[k - 1]
                elif far:
                    # Under the camera: row 0 pulled down the mountainside
                    # and off the frame.
                    near = [
                        QPointF(far[0].x() + dx, far[0].y() + dy),
                        QPointF(far[-1].x() + dx, far[-1].y() + dy),
                    ]
                else:
                    near = []
                erase(far + near[::-1])
                if k >= 1 and spokes[k - 1] > 0.0:
                    stroke(self._segments(
                        sx[k - 1], sy[k - 1], depth[k - 1],
                        sx[k], sy[k], depth[k], width, height,
                    ), alpha[k - 1] * spokes[k - 1] * _SPOKE_ALPHA)
                stroke(self._segments(
                    sx[k, :-1], sy[k, :-1], depth[k, :-1],
                    sx[k, 1:], sy[k, 1:], depth[k, 1:], width, height,
                ), alpha[k])
        painter.end()

    @staticmethod
    def _segments(x1, y1, d1, x2, y2, d2, width: int, height: int) -> list[QLineF]:
        ok = (d1 > _DEPTH_EPS) & (d2 > _DEPTH_EPS)
        ok &= ~((x1 < 0) & (x2 < 0)) & ~((x1 > width) & (x2 > width))
        ok &= ~((y1 < 0) & (y2 < 0)) & ~((y1 > height) & (y2 > height))
        if not ok.any():
            return []
        return list(map(
            QLineF, x1[ok].tolist(), y1[ok].tolist(), x2[ok].tolist(), y2[ok].tolist()
        ))
