"""Loop Tunnel: a camera flying a frozen closed 3-D loop, drawn as wireframe rings.

**The menu calls this one "Tunnel chase"**, and calls its sibling
:mod:`.vis_beat_tunnel` "Wormhole" — see that module's header for why the
labels read the other way round from the module names.

The tunnel is a periodic cubic spline through 25 frozen waypoints, resampled
uniformly by arc length, with rotation-minimising (parallel-transported)
frames so the mesh never rolls on a straightaway or jumps at the seam. Each
frame projects a fixed number of rings sitting at *world* arc-lengths ahead of
the camera, so the tunnel slides past as the camera advances, and paints them
as antialiased polylines — the cost is O(lines), not O(pixels), which is why
this renders near the host's own pixel size for a few milliseconds while the
per-pixel modes stay at 152x64. Pixelated stars (crosses built from cells
snapped to a coarse grid) stream past to place it in space; they are lit by the
kick, barely visible between beats.

Path properties are asserted by ``tests/gui/test_vis_loop_tunnel.py`` through
:func:`path_stats`: 15 turns, three straightaways of 22/37/46 units, minimum
radius of curvature 2.45 tunnel radii (the walls never fold into themselves).
Curvature comes from the spline's analytic derivatives — finite differences
over the resampled polyline over-count turns, because the resample is
piecewise-linear.

No audio code lives here: :meth:`LoopTunnelScene.render` takes a level and a
kick pulse as plain numbers and :class:`~.vis_canvas.VisRenderer` supplies
them.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QLineF, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF

from ..styles.theme import Theme

TUNNEL_R = 1.0

# The loop tunnel owns its own image rather than the shared 152x64 grid: a
# wireframe stretched non-uniformly by the host would draw ellipses for rings,
# and the two hosts have different aspects. Both the shape and the size follow
# the host — see set_target_size — capped by what a frame may cost.
#
# It used to be 256 high whatever was asking, blown up to the host with nearest
# -neighbour: on a Retina popout at 1400x800 logical that is 448x256 stretched
# to 2800x1600, one image pixel per 6.25 device pixels, and the wireframe read
# as a staircase. It now renders from **device** pixels and asks the host to
# interpolate whatever is left over.
#
# The popout's cap is higher than the beat tunnel's identical-looking one, and the
# reason is the frame rate, not the picture: the tunnel runs at 60 fps, so its
# 4 ms is a quarter of a 16 ms frame, while this runs at 30 and has 33 ms to
# spend. Measured on the M-series Mac, one frame of the loop tunnel:
#
#   448x256    1.6 ms   (what it used to render, whatever the host)
#   896x512    3.1 ms   (the backdrop, capped)
#   1260x720   4.4 ms   (the beat tunnel's cap, for comparison)
#   2100x1200  8.0 ms   (this cap on a 2800x1600 host — a quarter of the frame)
#   2800x1600 10.7 ms   (native; sharper at 1:1, but a third of the frame and
#                        unbounded on a larger display, which is what a cap is
#                        for — 5K would be 20 ms and drop frames)
#
# Rendered side by side at 1:1 device pixels
# (`evidence/wormhole/resolution_sheet.py`), 2100x1200 upscaled 1.33x is very
# close to native and plainly better than 1260x720 upscaled 2.2x.
#
# The backdrop keeps the smaller cap it shares with the tunnel: its cost is the
# host, not the frame — repainting the playlist rows behind it is ~11 ms on its
# own — and it is drawn at 40% opacity behind text, where the resolution buys
# much less than it does in a popout.
POPOUT_CAP = (2400, 1200)
BACKDROP_CAP = (1216, 512)
_MIN_H = 64
_REF_H = 256  # the height the pixel sizes below were tuned at

_RINGS = 24
_SEGMENTS = 16
_SPACING = 1.0  # world units between rings
_FOV_DEG = 95.0
_BASE_SPEED = 0.18  # world units per frame with no audio (~5.4 u/s at 30 fps)
_SPEED_LEVEL = 1.2  # extra travel speed at full level
_LOOK_AHEAD = 2.5  # how far up the path the camera aims
# Depth fade curve for the ring alpha. Steeper than it looks like it needs
# to be: rings pile geometrically into the vanishing point, so a gentler
# curve (1.3 was the prototype's) stacks the far end into a solid bright
# knot instead of a throat receding into the dark.
_FADE_EXP = 2.0
_PEN_WIDTH = 1.2  # px at the reference height; scaled with the image
_PULSE_RIPPLE = 0.12  # near-ring radius bump on a full-strength kick
_N_STARS = 110
# Stars are drawn as a cross — a horizontal and a vertical bar of _STAR_CELL
# -sized cells — rather than a solid block, so they read as points of light
# instead of confetti. Near ones get longer arms, which reads as a closer star
# twinkling harder. The two bars overlap at the centre, and the doubled alpha
# there is wanted: it gives each star a brighter core, which is most of what
# makes it read as a star rather than a plus sign.
#
# How chunky a star looks is the *ratio* of bar thickness to span, not the
# span: 3 px bars on a 9 px cross and 2 px bars on a 6 px cross look equally
# blocky, just at different sizes. So the thin bar is what buys the fine look,
# and the arms are then free to be short enough to stay small.
#
# The cell is a *reference* size and is scaled with the image, so a star keeps
# the apparent size it was tuned at whatever resolution the host asks for. It
# used to lean on the host's unsmoothed blow-up for its crispness; now the blow
# -up is smooth (the wireframe is the point of the resolution) and the crispness
# comes from the cell being whole pixels of a `fillRect`, which is not
# antialiased. What that costs is the softening of the residual upscale, which
# at these sizes is 1.1x to 2.3x rather than the 6x it was.
_STAR_CELL = 1  # image px per star "pixel" at _REF_H (also the bar thickness)
_STAR_ARM_FAR = 2  # arm length in cells (so 5 cells across)
_STAR_ARM_NEAR = 3  # 7 cells across, for stars inside 35% of the far plane
# Stars are kick-driven: barely there between beats, full on the kick, then
# released slowly. Same fast-attack/slow-release shape as the fractal's level
# follower (max(new, prev * decay)), which is what makes that mode read as
# pulsing rather than flickering — a bare `pulse` would strobe, since the
# detector's own value collapses within a frame or two of the transient.
# Measured against a 128 BPM kick (14 frames a beat at 30 fps): the fractal's
# own 0.94 only falls to 0.45 before the next one lands, which reads as a mild
# throb rather than "dark until the kick". 0.82 troughs at 0.08, spends about
# 40% of each beat down there, and takes ~0.5 s to fall to nothing — still a
# fade rather than a strobe, and the release the visual was tuned to by eye.
_STAR_FLOOR = 0.15  # fraction of a star's depth alpha between kicks
_STAR_DECAY = 0.82  # per-frame release of the glow
_LOOP_SAMPLES = 4096

# 25 waypoints (x, y, z), generated once and frozen here so the app carries no
# RNG or seed dependency for the path. Layout: a deformed ring of left/right
# swerves with a vertical rise (the turns), broken by three runs of four
# collinear points (the straightaways).
_WAYPOINTS = (
    (52.76, 1.22, -2.22),
    (49.57, 1.22, 8.65),
    (46.38, 1.22, 19.52),
    (43.19, 1.22, 30.40),
    (30.07, -3.84, 34.70),
    (23.13, 0.70, 50.65),
    (6.48, 2.01, 45.09),
    (-7.76, -0.64, 53.97),
    (-19.90, -0.39, 48.92),
    (-28.46, -0.39, 41.50),
    (-37.03, -0.39, 34.08),
    (-45.59, -0.39, 26.65),
    (-53.65, 3.14, 15.75),
    (-45.44, -1.77, 0.00),
    (-52.62, -3.97, -15.45),
    (-38.18, 3.61, -24.54),
    (-36.46, 0.28, -42.08),
    (-23.94, -0.12, -47.07),
    (-12.72, -0.12, -48.68),
    (-1.51, -0.12, -50.30),
    (9.71, -0.12, -51.91),
    (23.22, 0.75, -50.84),
    (28.89, 3.98, -33.34),
    (45.48, -3.05, -29.23),
    (42.68, -2.99, -12.53),
)


def build_loop(waypoints=_WAYPOINTS, n_out: int = _LOOP_SAMPLES, per_seg: int = 256):
    """Build the closed path.

    Returns ``(pos, tan, normal, binormal, kappa, total)`` — the first four
    are ``(n, 3)`` arrays uniformly spaced by arc length around the loop,
    ``kappa`` is the curvature at each sample and ``total`` the loop length.
    """
    P = np.asarray(waypoints, float)
    m = len(P)
    closed = np.vstack([P, P[:1]])
    h = np.linalg.norm(np.diff(closed, axis=0), axis=1)  # chord lengths
    # Cyclic tridiagonal system for the knot second derivatives. m is 25, so a
    # dense solve costs ~0.1 ms and avoids importing scipy.interpolate, which
    # measured 194 ms for an identical path.
    A = np.zeros((m, m))
    rhs = np.zeros((m, 3))
    for i in range(m):
        hp, hn = h[(i - 1) % m], h[i]
        A[i, (i - 1) % m] += hp
        A[i, i] += 2 * (hp + hn)
        A[i, (i + 1) % m] += hn
        rhs[i] = 6 * ((P[(i + 1) % m] - P[i]) / hn - (P[i] - P[(i - 1) % m]) / hp)
    M = np.linalg.solve(A, rhs)
    pos, d1, d2 = [], [], []
    t = np.linspace(0, 1, per_seg, endpoint=False)[:, None]
    for i in range(m):
        a, b = P[i], P[(i + 1) % m]
        Ma, Mb = M[i], M[(i + 1) % m]
        H = h[i]
        pos.append(Ma * (1 - t) ** 3 * H * H / 6 + Mb * t**3 * H * H / 6
                   + (a - Ma * H * H / 6) * (1 - t) + (b - Mb * H * H / 6) * t)
        d1.append(-Ma * (1 - t) ** 2 * H / 2 + Mb * t**2 * H / 2
                  + (b - a) / H - (Mb - Ma) * H / 6)
        d2.append(Ma * (1 - t) + Mb * t)
    pos, d1, d2 = map(np.vstack, (pos, d1, d2))
    # Analytic curvature — see the module docstring on why not finite
    # differences over the resampled polyline.
    kappa = np.linalg.norm(np.cross(d1, d2), axis=1) / np.linalg.norm(d1, axis=1) ** 3
    tan = d1 / np.linalg.norm(d1, axis=1)[:, None]
    # Arc-length resample, so "advance by speed" is a plain index step.
    seg = np.linalg.norm(np.diff(np.vstack([pos, pos[:1]]), axis=0), axis=1)
    s = np.r_[0.0, np.cumsum(seg)[:-1]]
    total = float(seg.sum())
    su = np.linspace(0, total, n_out, endpoint=False)

    def resample(arr: np.ndarray) -> np.ndarray:
        return np.stack([np.interp(su, s, arr[:, k]) for k in range(arr.shape[1])], 1)

    pos_u = resample(pos)
    tan_u = resample(tan)
    tan_u /= np.linalg.norm(tan_u, axis=1)[:, None]
    kappa_u = np.interp(su, s, kappa)
    N, B = parallel_frames(tan_u)
    return pos_u, tan_u, N, B, kappa_u, total


def parallel_frames(tan: np.ndarray):
    """Rotation-minimising normal/binormal around the closed loop.

    A Frenet frame is undefined where curvature reaches zero — which is every
    straightaway — and spins on the way into a turn, so the tube and its spoke
    lines corkscrew. A transported frame never rolls; the leftover twist after
    one lap is spread linearly so the last sample hands off to the first with
    no visible jump at the seam.
    """
    n = len(tan)
    N = np.empty_like(tan)
    ref = np.array([0.0, 1.0, 0.0])
    if abs(np.dot(ref, tan[0])) > 0.9:
        ref = np.array([1.0, 0.0, 0.0])
    n0 = ref - np.dot(ref, tan[0]) * tan[0]
    N[0] = n0 / np.linalg.norm(n0)
    for i in range(1, n):
        v = N[i - 1] - np.dot(N[i - 1], tan[i]) * tan[i]
        N[i] = v / np.linalg.norm(v)
    # Transport once more onto tan[0] to measure the one-lap twist.
    v = N[-1] - np.dot(N[-1], tan[0]) * tan[0]
    v /= np.linalg.norm(v)
    B0 = np.cross(tan[0], N[0])
    twist = np.arctan2(np.dot(v, B0), np.dot(v, N[0]))
    ang = -twist * np.arange(n) / n
    B = np.cross(tan, N)
    N2 = N * np.cos(ang)[:, None] + B * np.sin(ang)[:, None]
    return N2, np.cross(tan, N2)


def path_stats(kappa: np.ndarray, total: float, turn_k: float = 0.12,
               straight_k: float = 0.035, min_straight: float = 18.0):
    """``(turn count, straight lengths, min radius of curvature)``.

    The oracle for the brief: turns are curvature maxima above *turn_k* merged
    within 4 units, straights are runs below *straight_k* longer than
    *min_straight*, and the minimum radius says whether the tunnel walls could
    fold into themselves on the sharpest turn.
    """
    n = len(kappa)
    ds = total / n
    peaks: list[int] = []
    for i in range(n):
        if kappa[i] >= turn_k and kappa[i] >= kappa[i - 1] and kappa[i] >= kappa[(i + 1) % n]:
            if not peaks or (i - peaks[-1]) * ds > 4.0:
                peaks.append(i)
    low = kappa < straight_k
    # Begin on a non-straight sample so a run isn't split by the seam.
    start = int(np.argmin(low))
    order = np.r_[np.arange(start, n), np.arange(0, start)]
    straights: list[float] = []
    run = 0
    for j in order:
        if low[j]:
            run += 1
        else:
            if run * ds >= min_straight:
                straights.append(run * ds)
            run = 0
    if run * ds >= min_straight:
        straights.append(run * ds)
    return len(peaks), straights, 1.0 / max(float(kappa.max()), 1e-9)


class LoopTunnelScene:
    """The loop tunnel's own state and image; driven by level and kick pulse."""

    def __init__(self) -> None:
        self._loop: tuple | None = None  # built on first render (~3-9 ms)
        self._s = 0.0
        self._color = QColor(Theme.WAVEFORM_DEFAULT)
        self._image = QImage(
            BACKDROP_CAP[0], BACKDROP_CAP[1], QImage.Format.Format_ARGB32_Premultiplied
        )
        self._image.fill(Qt.GlobalColor.transparent)
        # Vertical field of view is fixed, so a wider host simply shows more to
        # the sides rather than distorting. The focal length follows the image
        # height and is re-derived whenever that changes.
        self._focal = (self._image.height() / 2) / np.tan(np.radians(_FOV_DEG) / 2)
        self._far = _RINGS * _SPACING
        theta = np.linspace(0, 2 * np.pi, _SEGMENTS, endpoint=False)
        self._cos, self._sin = np.cos(theta), np.sin(theta)
        # Stars only; the path itself carries no randomness.
        self._rng = np.random.default_rng(1)
        self._stars = np.empty((_N_STARS, 3))
        self._prev_basis: np.ndarray | None = None
        self._prev_cam: np.ndarray | None = None
        self._ring_s = np.zeros(_RINGS)  # world arc-lengths of the last frame
        self._star_glow = 0.0
        self.reset()

    # ── Public API ─────────────────────────────────────────────────────────

    def image(self) -> QImage:
        return self._image

    def set_color(self, color: QColor | str) -> None:
        self._color = QColor(color)

    def star_cell(self) -> int:
        """Image pixels per star "pixel" at the current resolution.

        Public so a test can ask rather than assume: the cell is a reference
        size scaled with the image, and a test that hardcodes it is measuring a
        starfield the scene does not draw.
        """
        return max(1, int(round(_STAR_CELL * self._image.height() / _REF_H)))

    def reset(self) -> None:
        """Return to the start of the loop and re-scatter the stars."""
        self._s = 0.0
        self._prev_basis = None
        self._prev_cam = None
        self._star_glow = 0.0
        for i in range(_N_STARS):
            self._stars[i] = self._spawn_star(self._rng.uniform(1.0, self._far))
        self._image.fill(Qt.GlobalColor.transparent)

    def set_target_size(self, width: int, height: int, popout: bool = False) -> None:
        """Match the image to the host's shape and size, capped by frame cost.

        *width* and *height* are **device** pixels — the host's logical size
        times its own ``devicePixelRatioF``, read from the widget that paints
        and not from the primary screen, since a popout can be dragged to
        another display.

        The aspect is preserved exactly and the image is never upscaled: a
        stretched wireframe draws ellipses where the rings should be, and a host
        smaller than the cap is better served at its own size.

        Reallocates only when the size actually changes — this runs before every
        frame. A host that isn't on screen yet can report zero or negative; keep
        the previous size rather than collapsing to the floor.
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
        self._focal = (target_h / 2) / np.tan(np.radians(_FOV_DEG) / 2)

    def render(self, level: float, pulse: float) -> QImage:
        """Advance one frame and paint it. *level* and *pulse* are 0..1."""
        pos, _tan, N, B, _kappa, total = self._ensure_loop()
        n = len(pos)
        width, height = self._image.width(), self._image.height()

        self._s = (self._s + _BASE_SPEED * (1.0 + _SPEED_LEVEL * level)) % total
        self._star_glow = max(pulse, self._star_glow * _STAR_DECAY)
        cam = pos[self._index(self._s, n, total)]
        up_hint = N[self._index(self._s, n, total)]
        look = pos[self._index(self._s + _LOOK_AHEAD, n, total)]
        fwd = look - cam
        fwd /= np.linalg.norm(fwd)
        right = np.cross(up_hint, fwd)
        right /= np.linalg.norm(right)
        up = np.cross(fwd, right)
        basis = np.stack([right, up, fwd], axis=1)  # columns

        # Rings sit at fixed *world* arc-lengths, so they slide toward the
        # camera as it advances. Anchoring them at s + k*spacing instead would
        # make them ride along and only the bend would change.
        first = np.ceil(self._s / _SPACING) * _SPACING
        ring_s = first + np.arange(_RINGS) * _SPACING
        self._ring_s = ring_s
        idx = ((ring_s / total) * n).astype(int) % n
        centers, ring_n, ring_b = pos[idx], N[idx], B[idx]
        radius = TUNNEL_R * (
            1.0 + _PULSE_RIPPLE * pulse * np.exp(-(ring_s - self._s) / 4.0)
        )[:, None, None]
        points = centers[:, None, :] + radius * (
            self._cos[None, :, None] * ring_n[:, None, :]
            + self._sin[None, :, None] * ring_b[:, None, :]
        )  # (rings, segments, 3)
        rel = (points - cam) @ basis  # camera coordinates
        # A ring point can sit at the camera's own depth on the sharpest turn;
        # without the floor the divide throws it a million pixels away and the
        # antialiaser spends milliseconds on a line to nowhere.
        depth = np.maximum(rel[..., 2], 0.05)
        sx = width / 2 + self._focal * rel[..., 0] / depth
        sy = height / 2 - self._focal * rel[..., 1] / depth

        star_x, star_y, star_z = self._advance_stars(basis, cam, width, height)
        self._paint(sx, sy, ring_s, star_x, star_y, star_z, level, pulse)
        return self._image

    # ── Internals ──────────────────────────────────────────────────────────

    def _ensure_loop(self) -> tuple:
        """Build the path on first use — never at import or construction.

        A VisRenderer exists for the playlist backdrop from Player startup
        even when visuals are off, and this costs a few milliseconds.
        """
        if self._loop is None:
            self._loop = build_loop()
        return self._loop

    @staticmethod
    def _index(s: float, n: int, total: float) -> int:
        return int((s / total) * n) % n

    def _spawn_star(self, depth: float | None = None) -> np.ndarray:
        """A star in camera coordinates, outside the tunnel wall."""
        if depth is None:
            depth = self._rng.uniform(self._far * 0.6, self._far)
        aspect = self._image.width() / self._image.height()
        lim_x = depth * 0.9 * aspect
        lim_y = depth * 0.9
        while True:
            x = self._rng.uniform(-lim_x, lim_x)
            y = self._rng.uniform(-lim_y, lim_y)
            if x * x + y * y > (TUNNEL_R * 1.6) ** 2:
                return np.array([x, y, depth])

    def _advance_stars(self, basis: np.ndarray, cam: np.ndarray, width: int,
                       height: int):
        """Keep the stars still in the world by re-expressing them.

        They live in camera coordinates (so projecting is a divide), which
        means each frame applies the exact rigid transform between the old
        camera and the new one rather than re-deriving world positions.
        """
        if self._prev_basis is not None:
            rot = basis.T @ self._prev_basis
            self._stars = self._stars @ rot.T + (basis.T @ (self._prev_cam - cam))
        self._prev_basis, self._prev_cam = basis, cam
        z = self._stars[:, 2]
        dead = (z < 0.3) | (z > self._far * 1.2)
        for i in np.flatnonzero(dead):
            self._stars[i] = self._spawn_star()
        z = self._stars[:, 2]
        x = width / 2 + self._focal * self._stars[:, 0] / z
        y = height / 2 - self._focal * self._stars[:, 1] / z
        return x, y, z

    def _paint(self, sx, sy, ring_s, star_x, star_y, star_z, level, pulse) -> None:
        width, height = self._image.width(), self._image.height()
        # The pen and the star cell below are sizes at _REF_H. Scaling them with
        # the image is what keeps the *apparent* thickness of a line constant
        # while the resolution changes: the image is drawn into a fixed logical
        # rect, so a pen of `w * height / _REF_H` lands at `w * logical_height /
        # _REF_H` on screen whatever height the image happens to be.
        scale = height / _REF_H
        cell = self.star_cell()
        self._image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self._image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Stars first, behind the mesh: blocks snapped to a coarse grid, which
        # is the "pixelated" half of the brief (the tunnel is the smooth half).
        # The glow scales the whole field, so depth still orders them — a near
        # star between kicks stays brighter than a far one, just barely lit.
        glow = _STAR_FLOOR + (1.0 - _STAR_FLOOR) * self._star_glow
        for x, y, z in zip(star_x, star_y, star_z):
            if not (0 <= x < width and 0 <= y < height):
                continue
            depth_alpha = np.clip(255 * (1.1 - z / self._far), 40, 255)
            color = QColor(235, 235, 255, int(depth_alpha * glow))
            arm = _STAR_ARM_NEAR if z <= self._far * 0.35 else _STAR_ARM_FAR
            cx = int(x) // cell * cell
            cy = int(y) // cell * cell
            span = (2 * arm + 1) * cell
            painter.fillRect(cx - arm * cell, cy, span, cell, color)
            painter.fillRect(cx, cy - arm * cell, cell, span, color)
        fade = np.clip(1.0 - (ring_s - self._s) / self._far, 0.0, 1.0) ** _FADE_EXP
        bright = 0.55 + 0.45 * min(1.0, level * 1.5 + pulse)
        for k in range(_RINGS):
            alpha = int(255 * fade[k] * bright)
            if alpha <= 2:
                continue
            # A copy per ring: mutating self._color would darken every later
            # frame's colour too.
            col = QColor(self._color)
            col.setAlpha(alpha)
            painter.setPen(QPen(col, _PEN_WIDTH * scale))
            painter.drawPolygon(
                QPolygonF([QPointF(sx[k, m], sy[k, m]) for m in range(_SEGMENTS)])
            )
            if k + 1 < _RINGS:
                painter.drawLines([
                    QLineF(sx[k, m], sy[k, m], sx[k + 1, m], sy[k + 1, m])
                    for m in range(_SEGMENTS)
                ])
        painter.end()
