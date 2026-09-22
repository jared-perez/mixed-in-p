"""The beat tunnel — the visual the menu calls Wormhole: its turn schedule,
its path, its picture, and its wiring.

The loop tunnel's tests are the template, with one change of substance: its
"rings slide past" and "silence still travels" tests encode *level drives
speed*, and here speed is the tempo. The shape of those tests is ported; the
assertions are not.

Pixel counting is numpy over the whole frame, never ``pixelColor`` in a loop
sampling every other pixel — a star arm is one pixel wide and a sampled test
steps straight over it.
"""

import math
import time

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter

from src.gui.widgets import vis_beat_tunnel as tc
from src.gui.widgets.beat_clock import DEFAULT_BPM
from src.gui.widgets.player_panel import _BACKDROP_VIS_MAP, PlayerPanel
from src.gui.widgets.vis_canvas import (
    FFT_SIZE,
    FRAME_MS,
    POPOUT_MODES,
    RENDER_MODES,
    FAST_FRAME_MS,
    VisRenderer,
)
from src.gui.widgets.vis_beat_tunnel import (
    BACKDROP_CAP,
    DS,
    POPOUT_CAP,
    TUNNEL_R,
    UNITS_PER_BEAT,
    _STAR_FLOOR,
    PathAhead,
    BeatTunnelScene,
    schedule_turns,
)
from src.gui.styles.theme import Theme
from src.utils.config import _VALID_VIS_MODES


# ── The schedule ───────────────────────────────────────────────────────────


def test_turns_land_on_the_bar_and_on_the_phrase():
    """The brief: beat 1 of every bar, plus beat 3 of every fourth bar."""
    turns = schedule_turns(0, 64, np.random.default_rng(1))
    beats = [beat for beat, _direction, _heading in turns]
    assert beats == [b for b in range(64) if b % 4 == 0 or b % 16 == 2]


def test_the_schedule_continues_across_calls():
    """It is generated ahead of the camera in chunks, not all at once."""
    rng = np.random.default_rng(1)
    first = schedule_turns(0, 32, rng)
    second = schedule_turns(32, 64, rng)
    assert [b for b, _d, _h in first + second] == [
        b for b in range(64) if b % 4 == 0 or b % 16 == 2
    ]


def test_no_turn_repeats_or_reverses_the_one_before_it():
    """Both read as a wobble rather than as a course change."""
    turns = schedule_turns(0, 256, np.random.default_rng(1))
    for (_b0, first, _h0), (_b1, second, _h1) in zip(turns, turns[1:]):
        delta = (second - first) % (2 * np.pi)
        assert min(delta, 2 * np.pi - delta) > 0.1  # not the same direction
        assert abs(delta - np.pi) > 0.1  # and not its reverse


def test_the_phrase_turn_is_the_gentler_one():
    """The extra swing inside a bar is a flourish, not another course change."""
    turns = schedule_turns(0, 256, np.random.default_rng(1))
    bar = [h for b, _d, h in turns if b % 4 == 0]
    phrase = [h for b, _d, h in turns if b % 16 == 2]
    assert max(phrase) < max(bar)
    assert np.mean(phrase) < np.mean(bar)


# ── The path ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def long_path():
    """Forty bars of the shipped seed — the path a listener actually flies."""
    path = PathAhead()
    path.extend_to(40 * 4 * UNITS_PER_BEAT)
    return path


def test_the_frames_stay_orthonormal(long_path):
    """A Bishop frame is rotation-minimising by construction; drift would roll the mesh."""
    tan = np.array(long_path.tan)
    normal = np.array(long_path.normal)
    binormal = np.array(long_path.binormal)
    for vectors in (tan, normal, binormal):
        assert np.abs(np.linalg.norm(vectors, axis=1) - 1.0).max() < 1e-9
    assert np.abs((tan * normal).sum(axis=1)).max() < 1e-9
    assert np.abs((tan * binormal).sum(axis=1)).max() < 1e-9
    assert np.abs((normal * binormal).sum(axis=1)).max() < 1e-9


def test_the_path_is_stepped_by_arc_length(long_path):
    steps = np.linalg.norm(np.diff(np.array(long_path.pos), axis=0), axis=1)
    assert np.abs(steps - DS).max() < 1e-9


def test_the_walls_never_fold_into_themselves(long_path):
    """Curvature comes from the bump sum, not from differences over the polyline."""
    assert long_path.min_radius() >= 2.0 * TUNNEL_R


def test_the_turns_are_a_lean_rather_than_an_elbow(long_path):
    """The first version turned too fast, and it read as a series of corners.

    The bump's integral is the heading change, so widening it lowers the peak
    curvature in proportion — the turn still happens, it just takes longer.
    Measured: 0.9 beats gave a sharpest turn of 2.27 R, 1.6 gives 3.4.
    """
    assert long_path.min_radius() >= 3.0 * TUNNEL_R


def test_a_straightaway_is_a_long_lazy_curve(long_path):
    """Mostly not straight — but not restlessly curving either.

    A **band**, not a ceiling, because this was tuned from both directions.
    Before any drift, 53% of the flight was straighter than 1/50 R and every
    turn was therefore a departure from nothing, which is what made them feel
    abrupt. The first drift amplitude took that to 3.3%, which overshot — the
    tunnel never settled. It sits around 10% now, and both neighbours are
    regressions from a judgement someone made by watching it.

    The band is half-to-double around the tuned figure, which is about as
    tight as this measure deserves: it is hypersensitive at this amplitude
    (1/50 R is roughly the amplitude itself) and it moves with how much path
    is sampled (the same setting reads 8.9% over these 40 bars and 10.1% over
    60). It still fails at both settings that were tried and rejected — no
    drift at all reads 27.8%, and the first attempt's 0.05 reads 3.3% — though
    note the lower bound clears that second one by only 0.3 of a point.
    """
    kappa = np.array(long_path.kappa[1:])
    assert 0.036 < float((kappa < 0.02).mean()) < 0.14
    # ...and the wander is gentle enough never to read as a turn of its own.
    assert np.median(kappa) < 1.0 / (5.0 * TUNNEL_R)


def test_the_curvature_is_continuous(long_path):
    """A bump whose leading half was never scheduled would show up as a step.

    The schedule is generated ahead of the camera in chunks, and a turn
    centred up to _TURN_WIDTH beats away already bends the path here — so a
    lookahead shorter than the bump's own reach would truncate it. Nothing in
    the shape of the path may jump.
    """
    steps = np.abs(np.diff(np.array(long_path.kappa[1:])))
    assert steps.max() < 0.05


def test_the_schedule_always_covers_the_frontier():
    """The invariant behind the test above, asserted rather than inferred."""
    path = PathAhead()
    for target in (10.0, 60.0, 200.0, 700.0):
        path.extend_to(target)
        frontier = path.s0 + (len(path.pos) - 1) * DS
        reach = frontier / UNITS_PER_BEAT + tc._TURN_WIDTH
        assert path._scheduled_to >= reach


def test_the_path_is_forgotten_behind_the_camera():
    path = PathAhead()
    path.extend_to(400.0)
    path.trim(380.0)
    assert path.s0 > 0
    # ...and what is left still answers for where the camera is.
    position, _n, _b = path.at(380.0)
    assert np.isfinite(position).all()
    assert len(path.turns) < 200  # the schedule is trimmed with it


# ── The scene ──────────────────────────────────────────────────────────────


@pytest.fixture
def scene(qapp):
    """A scene at backdrop size. qapp because painting a QImage needs QGuiApplication."""
    scene = BeatTunnelScene()
    scene.set_target_size(1216, 512)
    return scene


def _pixels(image):
    """``(h, w, 4)`` BGRA as numpy — the whole frame, not a sample of it.

    The ``.copy()`` is load-bearing, and leaving it off is a use-after-free
    rather than an inefficiency. A scene renders ``ARGB32_Premultiplied``, so
    ``convertToFormat`` really does allocate — the converted image is a
    *temporary* owned by nothing but this frame — and the memoryview
    ``constBits()`` hands back keeps no reference to the ``QImage`` it points
    into. So the view outlives its buffer: measured, a returned view read the
    0x7F fill of whatever ``QImage`` next took that block (alpha sum 19.7M
    against the frame's real 2.38M), and when the block went back to the OS
    instead the first read was an access violation that took the whole run
    down. It is load- and allocator-dependent, so the crash lands on a
    different test each run and passes outright on macOS.
    """
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    raw = np.frombuffer(image.constBits(), dtype=np.uint8)
    frame = raw.reshape(image.height(), image.bytesPerLine() // 4, 4)
    return frame[:, : image.width()].copy()


def _fly(scene, from_beat=0.0, to_beat=8.0, fps=60, bpm=128.0, pulse_at=None):
    """Feed the scene a run of frames and return the last image."""
    step = bpm / 60.0 / fps
    beat = from_beat
    image = None
    while beat <= to_beat:
        pulse = 1.0 if (pulse_at is not None and abs(beat - pulse_at) < step) else 0.0
        image = scene.render(beat, 0.6, pulse)
        beat += step
    return image


def test_speed_is_the_tempo_not_the_level(scene):
    """The loop tunnel's level-driven travel is exactly what this replaces."""
    scene.render(0.0, 0.0, 0.0)
    scene.render(4.0, 0.0, 0.0)
    quiet = scene._cam_s
    scene.reset()
    scene.render(0.0, 1.0, 0.0)
    scene.render(4.0, 1.0, 0.0)
    assert scene._cam_s == quiet == 4.0 * UNITS_PER_BEAT


def test_rings_slide_past_rather_than_riding_along(scene):
    """Rings sit at fixed world arc-lengths; anchored to the camera they would only bend."""
    scene.render(0.1, 0.5, 0.0)  # camera at 0.25 units, first ring at 1.0
    first_ring = scene._ring_s[0]
    camera = scene._cam_s
    scene.render(0.2, 0.5, 0.0)
    assert scene._cam_s > camera  # the camera advanced...
    assert scene._ring_s[0] == first_ring  # ...and the ring stayed put


def test_a_ring_reaching_the_camera_has_already_faded_to_nothing(scene):
    """The bright chord across the lens, and why it is a fade and not a clip.

    A ring passing beside the camera on a bend projects a correct but
    startling chord right across the frame. Raising the near plane to hide it
    makes rings pop out of existence instead; fading them over the last 0.9
    units means that by the time any vertex is behind the plane the ring is
    already drawing at zero alpha.
    """
    dissolving = 0
    for beat in np.arange(0.0, 24.0, 0.05):
        scene.render(float(beat), 0.6, 0.0)
        geometry = scene._geometry
        for k in range(len(geometry["ring_fade"])):
            if not geometry["ahead"][k].all():
                dissolving += 1
                # The very number the painter takes its alpha from.
                assert geometry["ring_fade"][k] == 0.0
    assert dissolving > 20  # rings really did pass the camera in that run


def test_spokes_are_clipped_at_the_near_plane_not_dropped(scene):
    """Dropping them leaves a cone floating mid-frame instead of a tube around you.

    A spoke whose near end is beside or behind the camera still has to be drawn
    from the frame edge inward — those lines are what put the viewer inside.
    """
    clipped_frames = 0
    for beat in np.arange(0.0, 24.0, 0.05):
        scene.render(float(beat), 0.6, 0.0)
        geometry = scene._geometry
        if geometry["nearest"][0] < tc._NEAR:
            clipped_frames += 1
            # Every spoke of the ring being passed survives, moved up to the
            # plane rather than discarded.
            assert geometry["spoke_ok"][0].all()
    assert clipped_frames > 10


def test_the_bore_stays_open_so_the_tunnel_reads_as_a_tunnel(scene):
    """The round-2 lesson, and why the puffs are not anchored on the wall.

    Anchored at the wall radius itself the cloud smears across the flight path
    and the tunnel stops reading as one — the bore fills in. Every puff is
    therefore pushed radially outward off the wall, in *world* space: the
    obvious screen-space version scales each vertex away from the ring's
    projected centroid, and a ring partly behind the camera has a vertex
    thousands of pixels out, so its centroid is nowhere near the tube. The
    near rings are always partly behind on a bend.

    Measured against the projected centroid of the rings that are wholly
    ahead — where the centroid is a fair stand-in for the centre — the closest
    puff of a ring still sits 1.26× as far out as the wall it hangs off. The
    bound below is a good deal looser than that and still fails outright at
    ``_NEBULA_WALL_R = 1.0``, which is the regression it is here for.

    *Enclosure* — whether the cloud reaches past the lens the way the spokes
    used to — is deliberately not asserted anywhere. It is a judgement from
    the running app and it is on the tuning agenda; a test written before that
    lands would pin the untuned look.
    """
    checked = 0
    for beat in np.arange(6.0, 20.0, 0.05):
        scene.render(float(beat), 0.6, 0.0)
        geometry = scene._geometry
        for k in range(tc._RINGS):
            if not geometry["ahead"][k].all():
                continue
            checked += 1
            cx = geometry["sx"][k].mean()
            cy = geometry["sy"][k].mean()
            wall = np.hypot(geometry["sx"][k] - cx, geometry["sy"][k] - cy)
            cloud = np.hypot(geometry["puff_x"][k] - cx, geometry["puff_y"][k] - cy)
            assert (cloud > wall * 1.1).all()
    assert checked > 1000


def test_it_draws_a_nebula_wall_and_stars(scene):
    """Cloud down the middle, pale sky behind it.

    The wall used to be the theme gold and the mask used to look for it. It is
    the nebula's own palette now — blue, violet, magenta, teal, green, every
    one of which leaves red a long way behind, which nothing in the sky does:
    stars are washed toward white and the greys are balanced.
    """
    image = _fly(scene, 0.0, 4.0, pulse_at=4.0)
    raw = _pixels(image)
    blue, green, red, alpha = (raw[..., i].astype(int) for i in range(4))
    lit = alpha > 0
    cloud = lit & ((blue > red + 40) | (green > red + 40))
    pale = lit & (red > 120) & (green > 120) & (blue > 120) & (abs(red - blue) < 60)
    cores = lit & (red > 230) & (green > 230) & (blue > 230)
    gold = lit & (red > 150) & (green > 150) & (blue < 80)
    assert cloud.sum() > 50_000
    assert pale.sum() > 100
    # Presence, not a count: how many white star centres a fixed flight lands
    # is pure seed noise. Measured over six seeds it ranges 11 to 38 here and
    # ranged 6 to 27 before the planets were removed, so the old `> 20` was
    # passing on seed 1's luck rather than on the mechanism. Nothing but the
    # cores draws white, so a broken one goes to zero and any floor catches it.
    assert cores.sum() > 3  # the white centres of the near four-point stars
    # The wireframe was replaced, not joined: `_NEBULA_MESH_ALPHA` is 0, so
    # the only gold left in the frame is what the sky's own tints carry.
    assert gold.sum() < 500


def test_the_cloud_is_anchored_to_the_world_not_to_the_ring_slot(scene):
    """Hash a puff from the ring *slot* and the whole texture swims forward.

    Rings sit at fixed world arc-lengths and re-seat a slot at a time as the
    camera advances, so slot k holds a different piece of tube every
    ``_SPACING`` units. Advance by exactly one spacing and every ring must be
    wearing the cloud it wore in the slot above — same colours, same shapes,
    one row down. Anchored to k they would instead sit still and the cloud
    would ride along with the camera rather than stream past it.
    """
    one_slot = tc._SPACING / UNITS_PER_BEAT
    _fly(scene, 0.0, 9.0)
    scene.render(9.0, 0.6, 0.0)
    before = scene._puff_field(scene._geometry, scene._ring_s, 0.6, 0.0, 1.0)
    slots = scene._ring_s.copy()

    _fly(scene, 9.0, 9.0 + one_slot)
    scene.render(9.0 + one_slot, 0.6, 0.0)
    after = scene._puff_field(scene._geometry, scene._ring_s, 0.6, 0.0, 1.0)

    assert np.allclose(slots[1:], scene._ring_s[:-1])  # everything moved down one
    assert np.array_equal(before["hue"][1:], after["hue"][:-1])
    assert np.array_equal(before["variant"][1:], after["variant"][:-1])


def test_the_cloud_is_the_same_world_at_either_frame_rate(qapp):
    """The sibling of the star glow's two-rate test, from the other direction.

    The glow needed ``set_frame_interval`` because a decay written per frame is
    a duration only at one rate. The nebula is stateless — a pure function of
    arc length — so it needs nothing there, and this is what says so: the same
    second of flight fed at 16 ms and at 33 ms leaves an identical wall.
    """
    fields = []
    for frame_ms, fps in ((1000.0 / 60.0, 60), (1000.0 / 30.0, 30)):
        scene = BeatTunnelScene()
        scene.set_target_size(1216, 512)
        scene.set_frame_interval(frame_ms)
        _fly(scene, 0.0, 8.0, fps=fps)
        scene.render(8.0, 0.6, 0.0)
        fields.append(scene._puff_field(scene._geometry, scene._ring_s, 0.6, 0.0, 1.0))
    for key in ("hue", "variant", "sprite", "radius", "alpha", "keep"):
        assert np.array_equal(fields[0][key], fields[1][key]), key


def test_the_culls_bound_what_is_drawn(scene):
    """The guardrails are in code, not in hope — and they are counted, not eyeballed.

    The cost of the wall is per pixel covered, so every cull is a coverage cap:
    the alpha floor, the minimum size, half the puffs on the far rings, the
    screen-radius ceiling and the off-screen reject. Together they take roughly
    half the grid out of the frame. Counted as survivors rather than as pixels,
    because that is the number the blit loop runs over.
    """
    counts = []
    for beat in np.arange(0.0, 20.0, 0.05):
        scene.render(float(beat), 0.6, 0.0)
        field = scene._puff_field(scene._geometry, scene._ring_s, 0.6, 0.0, 1.0)
        counts.append(int(field["keep"].sum()))
    grid = tc._RINGS * tc._SEGMENTS
    assert max(counts) < 0.6 * grid  # measured 250-270 of 560
    assert min(counts) > 100  # ...and never so few that the wall goes missing


# ── The cloud layer: the wall drawn small and added back ──────────────────
#
# The saving is resolution and nothing else, so these are written as
# comparisons against `_CLOUD_DOWNSCALE = 1.0` — the same scene with the layer
# skipped — rather than against remembered numbers.


def _composited(image, background, opacity):
    """What a viewer actually sees: the frame over a ground, at its opacity.

    Never diff the raw frames. A scene renders premultiplied ARGB onto
    transparency, and ``convertToFormat`` un-premultiplies: a pixel carrying
    alpha 1 and a premultiplied channel of 1 comes back as 255, so an
    off-by-one in the faintest corner of the cloud reports as a maximum
    difference of 255. Measured, diffing raw frames called this render 16%
    changed when the composited difference is a maximum of 4/255.
    """
    canvas = QImage(image.width(), image.height(), QImage.Format.Format_ARGB32)
    canvas.fill(background)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.setOpacity(opacity)
    painter.drawImage(canvas.rect(), image)
    painter.end()
    return _pixels(canvas)[..., :3].astype(int)


def _flight_at_downscale(monkeypatch, downscale, size=(1216, 512)):
    """One frame of the same seeded flight, rendered at a given layer size."""
    monkeypatch.setattr(tc, "_CLOUD_DOWNSCALE", downscale)
    scene = BeatTunnelScene()
    scene.set_target_size(*size)
    return _fly(scene, 0.0, 12.0, fps=30).copy()


def test_the_layer_changes_the_resolution_not_the_wall(scene):
    """Which puffs are drawn, and in what colour, is the same at any layer size.

    This is what lets the other `_puff_field` tests go on describing the wall
    while asking for the full-resolution field: every cull in there is written
    against *frame* pixels, both sides carrying the same divide, so the layer
    cannot quietly thin the wall. Only the radii move, and they move exactly.

    A cull expressed in the layer's own pixels instead would drop puffs as the
    layer shrank — a change to the picture wearing the costume of a
    performance setting, and invisible in a timing test.
    """
    _fly(scene, 0.0, 9.0)
    scene.render(9.0, 0.6, 0.0)
    full = scene._puff_field(scene._geometry, scene._ring_s, 0.6, 0.0, 1.0, 1.0)
    for factor in (1.5, 2.0, 3.0):
        small = scene._puff_field(
            scene._geometry, scene._ring_s, 0.6, 0.0, 1.0, factor
        )
        assert np.array_equal(full["keep"], small["keep"]), factor
        assert np.array_equal(full["hue"], small["hue"]), factor
        assert np.array_equal(full["variant"], small["variant"]), factor
        assert np.allclose(full["alpha"], small["alpha"]), factor
        assert np.allclose(full["radius"], small["radius"] * factor), factor
        assert np.allclose(full["x"], small["x"] * factor), factor


def test_the_layer_is_invisible_where_the_viewer_meets_it(monkeypatch):
    """The whole case for the layer, as a picture rather than as a clock.

    Both contexts, because they are not equally forgiving: the popout shows
    the frame at full opacity on black, the backdrop at 0.40 over the
    playlist. Measured at the shipped 2.0 the worst pixel is 10/255 in the
    popout and 4/255 on the backdrop, and no pixel anywhere moves by more
    than 8; the bounds below leave room for a resampler that rounds
    differently without leaving room for the wall actually changing.

    What it deliberately does **not** pin is the upscale filter: nearest
    measures 11/255 here against smooth's 10, and a bound that separated those
    would be a knife edge rather than a test. The case for smooth is in
    `_paint_cloud_layer`'s own comment, as a measurement.
    """
    for size, background, opacity, bound in (
        ((1600, 720), QColor(0, 0, 0), 1.0, 16),
        ((1216, 512), QColor(Theme.BG_DARK), 0.40, 10),
    ):
        full = _composited(
            _flight_at_downscale(monkeypatch, 1.0, size), background, opacity
        )
        layered = _composited(
            _flight_at_downscale(monkeypatch, tc._CLOUD_DOWNSCALE, size),
            background, opacity,
        )
        diff = np.abs(full - layered)
        assert diff.max() <= bound, (size, diff.max())
        assert (diff.max(axis=2) > 8).mean() < 0.001, size


def test_a_downscale_of_one_really_skips_the_layer(monkeypatch, scene):
    """The revert path is a skip, not a factor of one.

    Rounding through a same-size layer would land within the bound above and
    still cost the allocation and the resample, so "1.0 restores the old
    render" has to mean the layer is never built.
    """
    monkeypatch.setattr(tc, "_CLOUD_DOWNSCALE", 1.0)
    _fly(scene, 0.0, 4.0)
    assert scene._cloud is None


def test_the_layer_is_kept_across_frames_and_rebuilt_only_on_a_resize(scene):
    """One fill a frame, not one allocation a frame."""
    _fly(scene, 0.0, 4.0)
    first = scene._cloud
    assert first is not None
    assert first.width() == math.ceil(scene.image().width() / tc._CLOUD_DOWNSCALE)
    _fly(scene, 4.0, 6.0)
    assert scene._cloud is first  # same object, refilled

    scene.set_target_size(800, 400)
    _fly(scene, 6.0, 8.0)
    assert scene._cloud is not first
    assert scene._cloud.width() == math.ceil(
        scene.image().width() / tc._CLOUD_DOWNSCALE
    )


def _cloud_layer_only(scene, background):
    """Composite the layer alone onto *background*, and hand back the painter."""
    canvas = QImage(
        scene.image().width(), scene.image().height(),
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    canvas.fill(background)
    painter = QPainter(canvas)
    scene._paint_cloud_layer(
        painter, scene._geometry, scene._ring_s, 0.6, 0.0,
        canvas.height() / tc._REF_H,
    )
    return canvas, painter


def test_the_layer_composite_is_additive_like_the_puffs_it_replaces(scene):
    """The sibling of the puff pass's own test, one level up.

    The puffs being additive is no use if the blit that carries their total
    onto the frame is a `SourceOver`: that would dim every star the cloud
    covers, which is the difference the wall exists to avoid.
    """
    _fly(scene, 0.0, 6.0)
    canvas, painter = _cloud_layer_only(scene, QColor(40, 40, 40))
    painter.end()
    raw = _pixels(canvas)[..., :3].astype(int)
    assert (raw >= 40).all()  # nothing the cloud covered got darker...
    assert (raw > 60).any()  # ...and the cloud really arrived


def test_the_layer_hands_the_painter_back_as_it_was_found(scene):
    """As the puff pass does: Plus and the smooth hint are painter-wide."""
    _fly(scene, 0.0, 6.0)
    canvas, painter = _cloud_layer_only(scene, QColor(0, 0, 0))
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    scene._paint_cloud_layer(
        painter, scene._geometry, scene._ring_s, 0.6, 0.0,
        canvas.height() / tc._REF_H,
    )
    assert painter.compositionMode() == QPainter.CompositionMode.CompositionMode_SourceOver
    assert painter.opacity() == 1.0
    assert not painter.testRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.end()


def _nebula_only(scene, background):
    """Paint the wall alone onto *background*, and hand back the painter used."""
    canvas = QImage(
        scene.image().width(), scene.image().height(),
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    canvas.fill(background)
    painter = QPainter(canvas)
    scene._paint_nebula(
        painter, scene._geometry, scene._ring_s, 0.6, 0.0,
        canvas.height() / tc._REF_H,
    )
    return canvas, painter


def test_the_wall_never_paints_opaque_over_the_sky(scene):
    """The brief in one assertion: the stars still show through the cloud.

    The wall is drawn last, over the galaxies and stars already down, and
    it is additive — so it can only ever brighten what it covers. An ordinary
    ``SourceOver`` pass at the same alphas would dim the sky behind every puff,
    which is the difference between a nebula and a painted tube.
    """
    _fly(scene, 0.0, 6.0)
    canvas, painter = _nebula_only(scene, QColor(40, 40, 40))
    painter.end()
    raw = _pixels(canvas)[..., :3].astype(int)
    assert (raw >= 40).all()  # nothing the cloud covered got darker...
    assert (raw > 60).any()  # ...and the cloud is really there


def test_the_painter_is_handed_back_as_it_was_found(scene):
    """Nothing follows the wall today; the next pass added after it would inherit.

    The puff pass switches to ``Plus``, drops the opacity per blit and turns
    smooth transforms off, and every one of those is painter-wide state.
    """
    _fly(scene, 0.0, 6.0)
    canvas, painter = _nebula_only(scene, QColor(0, 0, 0))
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    scene._paint_nebula(
        painter, scene._geometry, scene._ring_s, 0.6, 0.0,
        canvas.height() / tc._REF_H,
    )
    assert painter.compositionMode() == QPainter.CompositionMode.CompositionMode_SourceOver
    assert painter.opacity() == 1.0
    assert painter.testRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.end()


def test_the_sky_is_paler_than_the_accent(scene):
    """The brief: stars pale versions of the colour, plus some grey.

    The accent used to be the wall's colour too. The wall is the nebula's own
    palette now, so the sky is the last thing wearing it — which is exactly
    why `_palette()` was left alone by that change.
    """
    _fly(scene, 0.0, 4.0, pulse_at=4.0)
    palette = scene._palette()
    mesh = scene._color
    for colour in palette:
        assert colour.blue() > mesh.blue()


# ── The sky thins out: rests, galaxies, and spiky stars ───────────────────


def test_an_emptied_sky_slot_rests_before_it_refills(scene):
    """Sparse is the brief: the stream's rate is lifetime *plus* rest.

    The rest is in world units, not seconds or frames, so it scales with the
    tempo exactly as the churn it thins does and both frame-rate hosts agree.
    Kill the galaxy by hand: the next frame parks it far behind the lens with
    a wake arc-length, it stays parked until the camera has flown the gap, and
    it refills on its own once it has.
    """
    step = 128.0 / 60.0 / 60.0
    beat = 1.0
    scene.render(beat, 0.6, 0.0)
    scene._galaxies[0] = [0.0, 0.0, 0.1, 3.0]  # in the sky, past the near bound
    beat += step
    scene.render(beat, 0.6, 0.0)
    assert scene._galaxies[0, 2] == tc._SKY_PARKED
    wake = float(scene._galaxy_wake[0])
    assert scene._cam_s < wake  # a real rest, not an instant refill
    while (beat + step) * UNITS_PER_BEAT < wake:
        beat += step
        scene.render(beat, 0.6, 0.0)
        assert scene._galaxies[0, 2] == tc._SKY_PARKED  # still resting
    beat = wake / UNITS_PER_BEAT + step
    scene.render(beat, 0.6, 0.0)
    assert scene._galaxies[0, 2] > 0  # back in the sky, ahead of the camera


def test_a_fresh_sky_owes_its_first_galaxy_a_full_rest(scene):
    """Sparse is the brief, so a reset does not open on a galaxy.

    It also keeps every short deterministic flight in this file galaxy-free:
    the shortest rest is 12 units and the picture fixtures fly fewer.
    """
    assert (scene._galaxies[:, 2] == tc._SKY_PARKED).all()
    assert (scene._galaxy_wake >= tc._GALAXY_REST[0]).all()


def test_a_galaxy_comes_round_rarely_and_the_rest_gap_is_what_thins_it(scene):
    """Counted over one 200-beat flight, against a band with a fix on each side.

    The band has to fail in both directions or it is only testing that the
    spy runs. Measured across three seeds: **13 to 15** as built, **0** with
    the galaxy slot dead, and **21 to 26** with `_GALAXY_REST` zeroed — so the
    ceiling is what pins "sparse", and the floor is what pins "at all".
    """
    count = 0
    real = type(scene)._spawn_galaxy

    def spy(self, index):
        nonlocal count
        count += 1
        real(self, index)

    type(scene)._spawn_galaxy = spy
    try:
        _fly(scene, 0.0, 200.0)
    finally:
        type(scene)._spawn_galaxy = real
    assert 8 < count < 19


def _galaxy_alone(scene, depth=20.0, radius=3.0, size=400):
    """One face-on galaxy dead ahead, painted on its own layer."""
    scene.reset()
    scene._galaxies[0] = [0.0, 0.0, depth, radius]
    scene._galaxy_basis[0] = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    scene._galaxy_twist[0] = 4.4  # what _spawn_galaxy would roll, pinned
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    scene._paint_galaxies(painter, size, size, 1.0, 1.0)
    painter.end()
    return image


def test_a_galaxy_is_a_translucent_disc_with_a_brighter_heart(scene):
    """The two passes in one sample: haze that fades outward, a bulge at centre.

    Translucent because it is the farthest thing in the frame and the sky is
    depth behind the tunnel — nothing in it may reach full alpha.
    """
    alpha = _pixels(_galaxy_alone(scene))[..., 3].astype(int)
    assert (alpha > 0).sum() > 500  # really there
    assert alpha.max() < 255  # and haze, never a solid body
    centre = alpha[200, 200]
    reach = int(scene._focal * 3.0 / 20.0 * 0.8)
    assert centre > alpha[200, 200 + reach]  # the bulge outshines the disc


def test_the_disc_carries_spiral_arms_not_just_haze(scene):
    """Sampled around a circle at half the disc's radius, sector by sector.

    The haze is a radial gradient, which is *flat* around any circle centred
    on the bulge — so all the angular contrast on that ring is the arms, and
    a regression to the armless disc reads as near-zero range here.
    """
    alpha = _pixels(_galaxy_alone(scene))[..., 3].astype(int)
    reach = scene._focal * 3.0 / 20.0  # the disc's projected radius
    angles = np.linspace(0, 2 * np.pi, 72, endpoint=False)
    ring = alpha[
        (200 + 0.55 * reach * np.sin(angles)).astype(int),
        (200 + 0.55 * reach * np.cos(angles)).astype(int),
    ]
    assert int(ring.max()) - int(ring.min()) > 25


def test_an_edge_on_galaxy_is_a_sliver_not_a_wheel(scene):
    """The disc is a circle in its *own* plane, so the tilt is free.

    Its plane's two axes are projected and the unit circle mapped through
    them — turn the plane edge-on and the picture must collapse in one
    direction while keeping the other, with no per-case code.
    """
    face_on = _pixels(_galaxy_alone(scene))[..., 3] > 0
    scene._galaxy_basis[0] = np.array([[1.0, 0.0, 0.0], [0.0, 0.06, 0.998]])
    image = QImage(400, 400, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    scene._paint_galaxies(painter, 400, 400, 1.0, 1.0)
    painter.end()
    edge_on = _pixels(image)[..., 3] > 0
    tall = face_on.any(axis=1).sum()
    thin = edge_on.any(axis=1).sum()
    assert thin < tall * 0.5  # squashed vertically...
    assert edge_on.any(axis=0).sum() > face_on.any(axis=0).sum() * 0.7  # ...not shrunk


def test_star_crosses_vary_in_how_far_they_poke_out(scene):
    """Spikiness is rolled per star at spawn, so the field mixes tight and long."""
    spikes = scene._star_spike
    assert (spikes >= tc._STAR_SPIKE[0]).all()
    assert (spikes <= tc._STAR_SPIKE[1]).all()
    assert np.unique(spikes.round(3)).size > 10  # a distribution, not a constant


def test_most_stars_are_small_and_the_small_ones_are_the_compact_ones(scene):
    """Two asks in one roll: more smaller stars, and less spiky means tighter.

    The size skew is the bias exponent (a uniform roll would put the median at
    the range's midpoint); the coupling is that spike and size ride the same
    roll, so sorting the field by either order sorts it by both — a compact
    star never wears the long arms.
    """
    sizes = scene._star_size
    assert (sizes >= tc._STAR_SIZE[0]).all()
    assert (sizes <= tc._STAR_SIZE[1]).all()
    assert np.median(sizes) < (tc._STAR_SIZE[0] + tc._STAR_SIZE[1]) / 2
    assert (np.argsort(sizes) == np.argsort(scene._star_spike)).all()


def _lone_star_coverage(scene, spike, size=200):
    """Pixels lit by one near star drawn at *spike*."""
    scene._stars[:, 2] = -1.0
    scene._stars[0] = [0.0, 0.0, 3.0]  # near enough to be a four-point star
    scene._star_kind[0] = 0
    scene._star_spike[0] = spike
    scene._star_size[0] = 1.0  # pin the size roll: this test is about the arms
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    scene._paint_stars(painter, scene._palette(), size, size, 1.0, 1.0)
    painter.end()
    return int((_pixels(image)[..., 3] > 0).sum())


def test_the_painter_really_draws_the_rolled_spike(scene):
    """The same star at the two ends of the range, differenced by coverage."""
    tight = _lone_star_coverage(scene, tc._STAR_SPIKE[0])
    long_armed = _lone_star_coverage(scene, tc._STAR_SPIKE[1])
    assert long_armed > tight * 1.3


# ── Stars respond to the kick ──────────────────────────────────────────────


def _brightest_star(image):
    raw = _pixels(image)
    blue, red, alpha = raw[..., 0].astype(int), raw[..., 2].astype(int), raw[..., 3].astype(int)
    sky = (alpha > 0) & (blue > 120) & (red > 120)
    return int(alpha[sky].max()) if sky.any() else 0


def test_stars_are_lit_by_the_kick(scene):
    _fly(scene, 0.0, 4.0)  # settle with no kicks at all
    quiet = _brightest_star(scene.image())
    scene.render(4.1, 0.3, 1.0)
    assert _brightest_star(scene.image()) > 2 * quiet


def test_the_kick_glow_fades_rather_than_snapping_back(scene):
    scene.render(1.0, 0.3, 1.0)
    assert scene._star_glow == 1.0
    glows = []
    beat = 1.0
    for _ in range(6):
        beat += 0.05
        scene.render(beat, 0.3, 0.0)
        glows.append(scene._star_glow)
    assert glows == sorted(glows, reverse=True)
    assert 0.0 < glows[-1] < 1.0


def test_the_glow_release_is_the_same_length_of_time_at_both_frame_rates(qapp):
    """0.82 a frame is half a second at 33 ms and a quarter at 16 — a different visual."""
    half_second = []
    for frame_ms in (33.0, 1000.0 / 60.0):
        scene = BeatTunnelScene()
        scene.set_frame_interval(frame_ms)
        scene.render(0.0, 0.3, 1.0)
        beat, elapsed = 0.0, 0.0
        while elapsed < 0.5:
            beat += 128.0 / 60.0 * frame_ms / 1000.0
            elapsed += frame_ms / 1000.0
            scene.render(beat, 0.3, 0.0)
        half_second.append(scene._star_glow)
    assert half_second[0] == pytest.approx(half_second[1], abs=0.02)


def test_stars_never_go_out_entirely(scene):
    """The floor keeps a starfield there for a track with no kick in it."""
    scene.render(0.0, 0.3, 1.0)
    _fly(scene, 0.05, 20.0)
    assert scene._star_glow < 0.01
    assert _brightest_star(scene.image()) > 0


# ── The image ──────────────────────────────────────────────────────────────


def test_the_image_follows_the_host_aspect(scene):
    scene.set_target_size(1000, 500)
    assert (scene.image().width(), scene.image().height()) == (1000, 500)


def test_a_retina_popout_is_capped_and_left_to_the_host_to_upscale(qapp):
    """1400x800 logical at 2x: 1260x720, not 2800x1600 (~10 ms a frame)."""
    scene = BeatTunnelScene()
    scene.set_target_size(2800, 1600, popout=True)
    assert (scene.image().width(), scene.image().height()) == (1260, 720)
    assert scene.image().height() <= POPOUT_CAP[1]


def test_the_backdrop_gets_the_smaller_budget(qapp):
    """The playlist repaint behind it costs ~11 ms; the frame must not add to that."""
    scene = BeatTunnelScene()
    scene.set_target_size(2800, 1600)
    assert scene.image().height() <= BACKDROP_CAP[1]
    assert scene.image().width() <= BACKDROP_CAP[0]


def test_the_cap_never_distorts_the_aspect(qapp):
    """A stretched tube draws ellipses where the rings should be."""
    scene = BeatTunnelScene()
    for width, height in ((3000, 600), (2800, 1600), (600, 1200)):
        scene.set_target_size(width, height, popout=True)
        image = scene.image()
        assert image.width() / image.height() == pytest.approx(width / height, rel=0.01)


def test_a_host_smaller_than_the_cap_renders_at_its_own_size(qapp):
    scene = BeatTunnelScene()
    scene.set_target_size(400, 200)
    assert (scene.image().width(), scene.image().height()) == (400, 200)


def test_target_size_ignores_an_unshown_host(scene):
    before = scene.image()
    scene.set_target_size(0, 0)
    scene.set_target_size(-4, 300)
    assert scene.image() is before


def test_target_size_does_not_reallocate_when_unchanged(scene):
    """This runs before every frame."""
    first = scene.image()
    scene.set_target_size(1216, 512)
    assert scene.image() is first


def test_a_frame_stays_cheap(scene):
    """A loose guard against an accidental O(pixels) rewrite.

    It measures ~1.9 ms at this size against a 16 ms budget; the bound is
    generous so it cannot flake under a full-suite load. If it flakes anyway,
    delete it rather than widen it — the real cost lives in the plan.
    """
    _fly(scene, 0.0, 2.0)
    times = []
    beat = 2.0
    for _ in range(40):
        beat += 128.0 / 60.0 / 60.0
        start = time.perf_counter()
        scene.render(beat, 0.6, 0.0)
        times.append(time.perf_counter() - start)
    assert float(np.median(times)) * 1000 < 20.0


def test_reset_returns_to_the_start_of_a_fresh_path(scene):
    _fly(scene, 0.0, 8.0, pulse_at=4.0)
    scene.reset()
    assert scene._cam_s == 0.0
    assert scene._star_glow == 0.0
    assert scene._path.s0 == 0.0
    assert _pixels(scene.image())[..., 3].sum() == 0


# ── VisRenderer integration ────────────────────────────────────────────────


def _noise(rng):
    return (rng.standard_normal(FFT_SIZE) * 0.2).astype(np.float32)


def test_the_renderer_returns_the_scenes_own_image(qapp):
    renderer = VisRenderer()
    renderer.set_mode("beat_tunnel")
    renderer.set_target_size(1000, 500)
    image = renderer.render(_noise(np.random.default_rng(0)), 44100)
    assert (image.width(), image.height()) == (1000, 500)
    assert renderer.image() is image


def test_switching_away_leaves_the_other_modes_at_their_own_size(qapp):
    """The scene's image must never land in VisRenderer._image.

    The scope and spectrum renderers paint into that at 152x64; a 1216-wide one
    left there would have them drawing into a corner of it, and every host
    would happily stretch the result.
    """
    renderer = VisRenderer()
    renderer.set_mode("beat_tunnel")
    renderer.set_target_size(1216, 512)
    renderer.render(_noise(np.random.default_rng(0)), 44100)
    renderer.set_mode("spectrum")
    image = renderer.render(_noise(np.random.default_rng(1)), 44100)
    assert (image.width(), image.height()) == (152, 64)


def test_the_frame_rate_and_the_smoothing_are_per_mode(qapp):
    """60 fps for this one and the popout scope; interpolation for the tunnels.

    The two are separate axes and only look like one here. The frame rate is
    about the beat clock (33 ms is too coarse a kick flux to lock on); the
    smoothing is about what the mode draws — line work rendered near the host's
    own size, where a nearest-neighbour blow-up undoes the resolution, against
    the retro modes, which are meant to look like big pixels.

    The oscilloscope's own answer lives in test_vis_analog_scope.py: it used to
    split per host and no longer does, because the chunky face it split for is
    retired.
    """
    renderer = VisRenderer()
    renderer.set_mode("beat_tunnel")
    assert renderer.frame_ms() == FAST_FRAME_MS
    assert renderer.smooth_upscale() is True
    renderer.set_mode("loop_tunnel")
    assert renderer.frame_ms() == FRAME_MS
    assert renderer.smooth_upscale() is True
    for mode in ("spectrum", "fire", "fractal", "fractal_power", "fractal_trap"):
        renderer.set_mode(mode)
        assert renderer.frame_ms() == FRAME_MS
        assert renderer.smooth_upscale() is False
    renderer.set_mode("oscilloscope")
    assert renderer.smooth_upscale() is True
    renderer.set_mode("stream")
    assert renderer.frame_ms() == FRAME_MS
    assert renderer.smooth_upscale() is True


def test_the_bass_average_keeps_its_time_constant_at_either_rate(qapp):
    """0.97 a frame is 1.1 s at 33 ms and half that at 16 — a different pulse."""
    settled = []
    for frame_ms in (FRAME_MS, FAST_FRAME_MS):
        renderer = VisRenderer()
        renderer.set_frame_interval(frame_ms)
        renderer.set_mode("beat_tunnel")
        rng = np.random.default_rng(0)
        elapsed = 0.0
        while elapsed < 1.0:  # one second of the same audio, either way
            renderer.render(_noise(rng), 44100)
            elapsed += frame_ms / 1000.0
        settled.append(renderer._bass_att)
    assert settled[0] == pytest.approx(settled[1], rel=0.15)


def test_the_kick_flux_is_only_computed_where_it_is_used(qapp):
    """A log1p over 1025 bins is cheap, and still a tax on five modes."""
    renderer = VisRenderer()
    renderer.set_mode("spectrum")
    for _ in range(4):
        renderer.render(_noise(np.random.default_rng(0)), 44100)
    assert renderer._prev_log is None
    assert renderer._kick_flux == 0.0
    renderer.set_mode("beat_tunnel")
    for _ in range(4):
        renderer.render(_noise(np.random.default_rng(0)), 44100)
    assert renderer._prev_log is not None


def test_a_tag_reaches_the_beat_clock_and_no_tag_falls_back(qapp):
    renderer = VisRenderer()
    renderer.set_mode("beat_tunnel")
    renderer.set_track_tempo(135.0)
    assert renderer.beat_state()["tempo_bpm"] == pytest.approx(135.0)
    renderer.set_track_tempo(None)
    assert renderer.beat_state()["tempo_bpm"] == pytest.approx(DEFAULT_BPM)


def test_beat_state_is_only_offered_by_the_mode_that_has_one(qapp):
    renderer = VisRenderer()
    renderer.set_mode("loop_tunnel")
    assert renderer.beat_state() is None


def test_a_seek_drops_the_evidence_and_keeps_the_flight(qapp):
    renderer = VisRenderer()
    renderer.set_mode("beat_tunnel")
    renderer.set_track_tempo(128.0)
    rng = np.random.default_rng(0)
    for _ in range(30):
        renderer.render(_noise(rng), 44100)
    phase = renderer.beat_state()["phase"]
    renderer.reset_beat_clock()
    assert renderer.beat_state()["phase"] == phase
    assert renderer.beat_state()["locked"] is False


def test_mode_is_allow_listed_and_offered_by_both_hosts():
    assert "beat_tunnel" in RENDER_MODES
    assert "beat_tunnel" in POPOUT_MODES
    assert "beat_tunnel" in _VALID_VIS_MODES
    assert "backdrop_beat_tunnel" in _VALID_VIS_MODES
    assert _BACKDROP_VIS_MAP["backdrop_beat_tunnel"] == "beat_tunnel"


# ── PlayerPanel wiring ─────────────────────────────────────────────────────


@pytest.fixture
def player(qtbot):
    panel = PlayerPanel()
    qtbot.addWidget(panel)
    return panel


def _track(tmp_path, name="a.wav", bpm="128"):
    """A real (very short) file, so the Player's decode path is the fast one."""
    soundfile = pytest.importorskip("soundfile")
    path = tmp_path / name
    soundfile.write(str(path), np.zeros(4410, dtype=np.float32), 44100)
    return {"file_path": str(path), "display_name": name, "bpm": bpm}


def test_playing_a_track_pushes_its_tag_to_the_backdrop(player, tmp_path):
    player._select_vis_mode("backdrop_beat_tunnel")
    player.add_tracks([_track(tmp_path)])
    player._play_track(0)
    assert player._backdrop_renderer.beat_state()["tempo_bpm"] == pytest.approx(128.0)


def test_a_popout_opened_mid_track_is_given_the_tempo_too(player, tmp_path):
    """The loop tunnel had no per-track state at all, so this plumbing is new."""
    player.add_tracks([_track(tmp_path, bpm="135")])
    player._play_track(0)
    player._select_vis_mode("beat_tunnel")
    canvas = player._vis_window._canvas
    assert canvas._renderer.beat_state()["tempo_bpm"] == pytest.approx(135.0)


def test_an_untagged_track_leaves_the_clock_to_work_it_out(player, tmp_path):
    """entry.bpm is a tag string, and an empty one is not a float."""
    player._select_vis_mode("backdrop_beat_tunnel")
    player.add_tracks([_track(tmp_path, bpm="")])
    player._play_track(0)
    assert player._backdrop_renderer.beat_state()["tempo_bpm"] == pytest.approx(
        DEFAULT_BPM
    )


def test_a_seek_reaches_the_backdrops_clock(player, tmp_path, qtbot):
    player._select_vis_mode("backdrop_beat_tunnel")
    player.add_tracks([_track(tmp_path)])
    player._play_track(0)
    player._backdrop_renderer._clock._locked_bin = 3  # pretend it locked
    player._engine.seeked.emit()
    assert player._backdrop_renderer.beat_state()["locked"] is False


def test_the_popout_timer_follows_the_modes_frame_rate(player, qtbot):
    player._select_vis_mode("loop_tunnel")
    assert player._vis_window._timer.interval() == FRAME_MS
    player._select_vis_mode("beat_tunnel")
    assert player._vis_window._timer.interval() == FAST_FRAME_MS
    player._select_vis_mode("fractal")
    assert player._vis_window._timer.interval() == FRAME_MS


def test_the_backdrop_stays_at_thirty_whatever_the_mode(player):
    """Its cost is the host: repainting the rows behind the frame is ~11 ms."""
    player._select_vis_mode("backdrop_beat_tunnel")
    assert player._vis_tick_timer.interval() == FRAME_MS
    assert player._vis_decay_frames() == 2000 // FRAME_MS


def test_both_rows_are_in_the_visuals_menu(player):
    labels = [player._vis_actions[m].text() for m in ("backdrop_beat_tunnel", "beat_tunnel")]
    assert all(labels)
    modes = list(player._vis_actions)
    # It no longer sits beside the loop tunnel it is a sibling of: the user
    # placed the wormhole — which is this mode, the labels being crossed
    # against the ids on purpose — directly below spectrum in each half.
    assert modes.index("backdrop_beat_tunnel") == modes.index("backdrop_spectrum") + 1
    assert modes.index("beat_tunnel") == modes.index("spectrum") + 1
