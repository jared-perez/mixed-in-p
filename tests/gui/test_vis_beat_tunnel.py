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
    """``(h, w, 4)`` BGRA as numpy — the whole frame, not a sample of it."""
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    raw = np.frombuffer(image.constBits(), dtype=np.uint8)
    return raw.reshape(image.height(), image.bytesPerLine() // 4, 4)[:, : image.width()]


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


def test_it_draws_a_nebula_wall_stars_and_planets(scene):
    """Cloud down the middle, pale sky behind it, a shaded disc among it.

    The wall used to be the theme gold and the mask used to look for it. It is
    the nebula's own palette now — blue, violet, magenta, teal, green, every
    one of which leaves red a long way behind, which nothing in the sky does:
    stars and planets are washed toward white and the greys are balanced.
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
    assert cores.sum() > 20  # the white centres of the near four-point stars
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

    The wall is drawn last, over planets and stars that are already down, and
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
    """The brief: stars and planets pale versions of the colour, plus some grey.

    The accent used to be the wall's colour too. The wall is the nebula's own
    palette now, so this is the last thing wearing it — which is exactly why
    `_palette()` and `_planet_tints()` were left alone by that change.
    """
    _fly(scene, 0.0, 4.0, pulse_at=4.0)
    palette = scene._palette()
    mesh = scene._color
    for colour in palette:
        assert colour.blue() > mesh.blue()


# ── Planets: three tints, and rings on a few ───────────────────────────────


def _place_planet(scene, kind=0, rings=(), depth=12.0, radius=1.4, seed=4):
    """One planet dead ahead, everything else in the sky moved out of frame.

    The stars go behind the camera rather than being deleted so the arrays keep
    their shape; nothing with a negative depth is drawn.
    """
    scene.reset()
    scene._stars[:, 2] = -1.0
    scene._planets[:] = 0.0
    scene._planets[:, 2] = -1.0
    scene._planet_ring_radii[:] = 0.0
    scene._planets[0] = [0.0, 0.0, depth, radius]
    scene._planet_kind[0] = kind
    rng = np.random.default_rng(seed)
    normal = rng.normal(size=3)
    normal /= np.linalg.norm(normal)
    aside = np.array([0.0, 0.0, 1.0]) if abs(normal[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    u = np.cross(normal, aside)
    u /= np.linalg.norm(u)
    scene._planet_ring_basis[0] = np.stack([u, np.cross(normal, u)])
    for slot, value in enumerate(rings):
        scene._planet_ring_radii[0, slot] = value
    return scene


def test_the_planet_tints_are_the_old_one_plus_four(scene):
    """Most planets are exactly the shade they were; the others vary from it.

    The brightness of the pale one was settled by eye in the running app, so
    this pins it to the star palette's own wash rather than to a number: if that
    wash moves, the planets should move with it.
    """
    pale, dark, tint, red, blue = scene._planet_tints()
    assert pale == scene._palette()[1]  # unchanged, and still the same wash
    for channel in ("red", "green", "blue"):
        assert getattr(dark, channel)() < getattr(pale, channel)()
    # Less washed toward white is more of the accent's own colour, and the
    # theme colour is what the wash is pulling away from.
    assert abs(tint.blue() - scene._color.blue()) < abs(pale.blue() - scene._color.blue())
    # The red one leans red, the blue one blue — and both are *dull*: no
    # channel outshines the pale planet's, so they read as different rock in
    # the same sky rather than as new bright objects.
    assert red.red() > red.blue() and red.red() > red.green()
    assert blue.blue() > blue.red() and blue.blue() > blue.green()
    for colour in (red, blue):
        for channel in ("red", "green", "blue"):
            assert getattr(colour, channel)() < max(pale.red(), pale.green(), pale.blue())


def test_a_planet_keeps_its_tint_and_rings_until_it_is_replaced(scene):
    """Everything about a planet is rolled at spawn, so it cannot change on screen."""
    spawned = []
    real = type(scene)._spawn_planet

    def spy(self, index, depth=None):
        spawned.append(index)
        real(self, index, depth)

    type(scene)._spawn_planet = spy
    try:
        step = 128.0 / 60.0 / 60.0
        beat = 0.0
        before = scene._planet_kind.copy()
        for _ in range(400):
            spawned.clear()
            scene.render(beat, 0.6, 0.0)
            beat += step
            unchanged = [i for i in range(tc._N_PLANETS) if i not in spawned]
            assert (scene._planet_kind[unchanged] == before[unchanged]).all()
            before = scene._planet_kind.copy()
    finally:
        type(scene)._spawn_planet = real


def test_only_a_few_planets_are_dusky_tinted_or_ringed(scene):
    """"A small percentage" of a stream of three at a time — most stay pale."""
    kinds: list[int] = []
    ringed = 0
    real = type(scene)._spawn_planet

    def spy(self, index, depth=None):
        real(self, index, depth)
        nonlocal ringed
        kinds.append(int(self._planet_kind[index]))
        ringed += bool((self._planet_ring_radii[index] > 0).any())

    type(scene)._spawn_planet = spy
    try:
        _fly(scene, 0.0, 240.0)
    finally:
        type(scene)._spawn_planet = real
    assert len(kinds) > 60  # the sample is big enough to say anything at all
    # Pale is still the commonest by a distance — a plurality rather than a
    # majority now that red and blue joined the dusky and tinted exceptions.
    assert kinds.count(0) > 2 * max(kinds.count(k) for k in (1, 2, 3, 4))
    for kind in (1, 2, 3, 4):  # dusky, accent-tinted, dull red, dull blue
        assert 0 < kinds.count(kind) < len(kinds) * 0.35
    assert 0 < ringed < len(kinds) * 0.4


def test_a_ring_is_drawn_around_the_planet_and_not_only_over_it(scene):
    """The same planet with and without rings, differenced.

    Differential because the mesh and the stars are in the frame too and are
    identical between the two renders — the only thing that moved is the rings.
    Whether they are *legible* is not a question this can answer; that was
    settled by rendering a real flight (``planet_sheet.py --flight``), and the
    first cut of them passed a test like this while being invisible in the app.
    """
    plain = _pixels(_place_planet(scene, rings=()).render(0.0, 0.6, 1.0)).copy()
    ringed = _pixels(_place_planet(scene, rings=(1.5, 2.0)).render(0.0, 0.6, 1.0))
    changed = (plain != ringed).any(axis=2)
    assert changed.sum() > 200

    # The outer ring sits at 2.0 planet radii, so most of what changed has to be
    # outside the disc rather than crossing its face.
    height, width = changed.shape
    ys, xs = np.nonzero(changed)
    radius = scene._focal * 1.4 / 12.0
    beyond = np.hypot(xs - width / 2, ys - height / 2) > radius
    assert beyond.mean() > 0.5


def _chain_segments(chains):
    """How many of the ring's segments a list of polyline chains carries."""
    return sum(chain.size() - 1 for chain in chains)


def test_a_ring_passes_behind_the_planet_as_well_as_in_front(scene):
    """A tilted ring is split at the planet's own depth — the Saturn silhouette."""
    _place_planet(scene, rings=(1.6,))
    behind, in_front = scene._ring_arcs(0, 1216, 512)
    assert behind and in_front
    assert _chain_segments(behind) + _chain_segments(in_front) <= tc._PLANET_RING_SEGMENTS


def test_the_far_half_is_dropped_where_the_planet_covers_it(scene):
    """The disc is translucent, so draw order cannot occlude — dropping does.

    A near-edge-on ring sends its far half straight across the planet's face;
    painted and merely overdrawn it shows through the gradient disc, which
    reads as the ring passing in *front* — the bug the running app showed.
    So the stretch inside the silhouette must be missing from the chains
    entirely, and no surviving behind-point may sit deep inside the disc.
    """
    _place_planet(scene, rings=(1.6,))
    scene._planet_ring_basis[0] = np.array([[1.0, 0.0, 0.0], [0.0, 0.1, 0.995]])
    behind, in_front = scene._ring_arcs(0, 1216, 512)
    assert _chain_segments(behind) + _chain_segments(in_front) < tc._PLANET_RING_SEGMENTS
    depth, radius = scene._planets[0, 2], scene._planets[0, 3]
    pr = scene._focal * radius / depth
    for chain in behind:
        for m in range(chain.size()):
            point = chain.at(m)
            assert np.hypot(point.x() - 1216 / 2, point.y() - 512 / 2) > pr * 0.8


def test_a_ring_is_chains_not_beads(scene):
    """One face-on ring is a single closed chain, and paints with no dots.

    Drawn one line at a time, every shared endpoint of a translucent pen
    double-paints, and the ring wears a bead of 36 dots — exactly what the
    running app showed. A stroked polyline double-paints nothing, so no
    pixel of the band may exceed the pen's own alpha.
    """
    _place_planet(scene, rings=(1.8,))
    scene._planet_ring_basis[0] = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    behind, in_front = scene._ring_arcs(0, 1216, 512)
    chains = behind + in_front
    assert len(chains) == 1  # one unbroken chain...
    assert chains[0].size() == tc._PLANET_RING_SEGMENTS + 1  # ...closed on itself

    depth, radius = scene._planets[0, 2], scene._planets[0, 3]
    alpha = _pixels(_planets_alone(scene, glow=1.0))[..., 3].astype(int)
    ys, xs = np.indices(alpha.shape)
    span = np.hypot(xs - 200, ys - 200) / (scene._focal * radius / depth)
    band = alpha[(span > 1.6) & (span < 2.0)]
    disc = QColor(scene._planet_tints()[0])
    disc.setAlphaF(1.0)
    pen_alpha = scene._ring_colour(disc).alphaF() * 255
    assert band.max() <= pen_alpha + 5  # nothing double-painted anywhere


def test_a_planet_without_rings_has_no_arcs(scene):
    _place_planet(scene, rings=())
    assert scene._ring_arcs(0, 1216, 512) == ([], [])


def _planets_alone(scene, size=400, glow=_STAR_FLOOR):
    """The planet layer on its own, with no mesh over it to confuse a sample.

    *glow* defaults to the floor the sky sits at between kicks, which is where a
    planet spends most of its life and the state the rings had to read in.
    """
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    scene._paint_planets(painter, scene._planet_tints(), size, size, glow, 1.0)
    painter.end()
    return image


def test_a_ring_is_brighter_than_the_planet_it_circles(scene):
    """A one-pixel line needs more alpha than a disc does, or it is not there.

    The disc spreads its alpha over thousands of pixels and the ring over a
    line, so matching them — which is what the first cut did — leaves the rings
    invisible in the app. *How much* more is a judgement made by rendering a
    real flight (``planet_sheet.py --flight``), not here; this pins the shape of
    the rule and its ceiling.
    """
    disc = QColor(scene._planet_tints()[0])
    disc.setAlphaF(0.4)  # about what the depth fade and the glow floor leave
    assert scene._ring_colour(disc).alphaF() > disc.alphaF() * 1.25

    close = QColor(disc)
    close.setAlphaF(1.0)  # a rare close pass, where the disc is at full alpha
    assert scene._ring_colour(close).alphaF() < 1.0  # never as bright as the mesh


def test_the_painted_ring_really_is_the_brighter_colour(scene):
    """That the rule above is the one the painter uses, and not bypassed.

    Against the value the rule gives for *this* disc rather than against the
    disc itself: the ring's two arcs composite where they meet, which alone puts
    the band's brightest pixel half again above the disc — so "brighter than the
    disc" is satisfied by a ring drawn at the disc's own colour, which is the
    version that could not be seen in the app.
    """
    _place_planet(scene, rings=(1.8,))
    depth, radius = scene._planets[0, 2], scene._planets[0, 3]
    alpha = _pixels(_planets_alone(scene))[..., 3].astype(int)
    height, width = alpha.shape
    ys, xs = np.indices(alpha.shape)
    span = np.hypot(xs - width / 2, ys - height / 2) / (scene._focal * radius / depth)

    disc = QColor(scene._planet_tints()[0])
    disc.setAlphaF(float(alpha[span < 0.9].max()) / 255)  # the gradient's own peak
    expected = scene._ring_colour(disc).alphaF() * 255
    assert alpha[(span > 1.5) & (span < 2.1)].max() >= expected - 2


def test_the_ring_plane_is_fixed_in_the_world_not_to_the_camera(scene):
    """It rotates with the camera each frame, and stays a rotation while it does.

    Two halves of one property. If the rigid transform were not applied to the
    basis the vectors would simply never change, and the rings would face the
    camera the same way through every turn; if it were applied wrongly they
    would stop being orthonormal within a few frames and the ring would shear
    into an ellipse of its own.
    """
    _place_planet(scene, rings=(1.6,))
    scene._planets[0, 2] = 20.0  # far enough not to be culled during the run
    first = scene._planet_ring_basis[0].copy()
    step = 128.0 / 60.0 / 60.0
    beat = 0.0
    for _ in range(240):  # four beats: a scheduled turn is inside this
        scene.render(beat, 0.6, 0.0)
        beat += step
        u, v = scene._planet_ring_basis[0]
        assert np.isclose(np.linalg.norm(u), 1.0, atol=1e-6)
        assert np.isclose(np.linalg.norm(v), 1.0, atol=1e-6)
        assert abs(float(u @ v)) < 1e-6
    assert not np.allclose(scene._planet_ring_basis[0], first, atol=1e-3)


# ── The sky thins out: rests, galaxies, and spiky stars ───────────────────


def test_an_emptied_planet_slot_rests_before_it_refills(scene):
    """"About 20% fewer planets": the stream's rate is lifetime *plus* rest.

    The rest is in world units, not seconds or frames, so it scales with the
    tempo exactly as the churn it thins does and both frame-rate hosts agree.
    Kill a planet by hand: the next frame parks it far behind the lens with a
    wake arc-length, it stays parked until the camera has flown the gap, and
    it refills on its own once it has.
    """
    step = 128.0 / 60.0 / 60.0
    beat = 1.0
    scene.render(beat, 0.6, 0.0)
    scene._planets[0, 2] = 0.1  # shove it past the near bound
    beat += step
    scene.render(beat, 0.6, 0.0)
    assert scene._planets[0, 2] == tc._SKY_PARKED
    wake = float(scene._planet_wake[0])
    assert scene._cam_s < wake  # a real rest, not an instant refill
    while (beat + step) * UNITS_PER_BEAT < wake:
        beat += step
        scene.render(beat, 0.6, 0.0)
        assert scene._planets[0, 2] == tc._SKY_PARKED  # still resting
    beat = wake / UNITS_PER_BEAT + step
    scene.render(beat, 0.6, 0.0)
    assert scene._planets[0, 2] > 0  # back in the sky, ahead of the camera


def test_a_fresh_sky_owes_its_first_galaxy_a_full_rest(scene):
    """Sparse is the brief, so a reset does not open on a galaxy.

    It also keeps every short deterministic flight in this file galaxy-free:
    the shortest rest is 12 units and the planet fixtures fly 10.
    """
    assert (scene._galaxies[:, 2] == tc._SKY_PARKED).all()
    assert (scene._galaxy_wake >= tc._GALAXY_REST[0]).all()


def test_galaxies_are_about_a_fifth_of_the_planet_stream(scene):
    """Both streams counted over the same flight: a ratio, and a planet ceiling.

    Two instruments because they catch different regressions, checked by
    running this with each fix removed. The ratio fails outright with the
    galaxy slot dead (zero) but *survives* the planet rest gap being deleted
    (0.14 against 0.23 — both inside any honest band for a 16-galaxy sample),
    so the ceiling on the planet count is what pins the "20% fewer": this
    flight spawns 70 with the rest and 90 without it.
    """
    counts = {"planet": 0, "galaxy": 0}
    real_planet = type(scene)._spawn_planet
    real_galaxy = type(scene)._spawn_galaxy

    def spy_planet(self, index, depth=None):
        counts["planet"] += 1
        real_planet(self, index, depth)

    def spy_galaxy(self, index):
        counts["galaxy"] += 1
        real_galaxy(self, index)

    type(scene)._spawn_planet = spy_planet
    type(scene)._spawn_galaxy = spy_galaxy
    try:
        _fly(scene, 0.0, 200.0)
    finally:
        type(scene)._spawn_planet = real_planet
        type(scene)._spawn_galaxy = real_galaxy
    assert 40 < counts["planet"] < 80
    assert 0.08 < counts["galaxy"] / counts["planet"] < 0.4


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

    It measures ~3.4 ms at this size against a 16 ms budget; the bound is
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
    for mode in ("spectrum", "fire", "fractal"):
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
