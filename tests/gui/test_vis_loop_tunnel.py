"""The loop tunnel — the visual the menu calls Tunnel chase: its path, its
image, and its wiring.

The brief the path has to meet is asserted directly (§5.1) — at least 13
turns, at least three straightaways, walls that never fold into themselves —
so a regenerated loop can't quietly stop being a tunnel.
"""

import time

import numpy as np
import pytest
from PySide6.QtGui import QImage

from src.gui.widgets.player_panel import _BACKDROP_VIS_MAP
from src.gui.widgets.vis_canvas import FFT_SIZE, POPOUT_MODES, RENDER_MODES, VisRenderer
from src.gui.widgets import vis_loop_tunnel
from src.gui.widgets.vis_loop_tunnel import (
    BACKDROP_CAP,
    POPOUT_CAP,
    TUNNEL_R,
    LoopTunnelScene,
    build_loop,
    path_stats,
)
from src.utils.config import _VALID_VIS_MODES


@pytest.fixture(scope="module")
def loop():
    return build_loop()


def test_path_meets_the_brief(loop):
    """>=13 turns, >=3 straightaways, and walls that never self-intersect."""
    _pos, _tan, _n, _b, kappa, total = loop
    turns, straights, min_radius = path_stats(kappa, total)
    assert turns >= 13
    assert len(straights) >= 3
    assert all(length >= 18.0 for length in straights)
    # A radius of curvature below the tunnel radius would fold the inside
    # wall of a turn through itself.
    assert min_radius >= 2.4 * TUNNEL_R


def test_loop_closes_seamlessly(loop):
    """The last sample hands off to the first with no jump in the frame."""
    pos, _tan, normal, _b, _kappa, total = loop
    ds = total / len(pos)
    assert np.linalg.norm(pos[-1] - pos[0]) < 2 * ds
    # Frenet frames would flip here; the transported ones are spread so the
    # one-lap twist vanishes at the seam.
    assert float(normal[-1] @ normal[0]) > 0.999


# ── The scene ──────────────────────────────────────────────────────────────


def _star_pixels(image):
    """``(alpha, star mask)`` for a frame, as numpy arrays.

    Not ``pixelColor`` in a loop: a 608x256 frame is 150k calls, and sampling
    every other pixel to make that bearable would step straight over a one
    pixel star arm. Stars are white-blue and the mesh is the waveform colour,
    so the hue is what separates them; alpha is what the kick drives.
    """
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    raw = np.frombuffer(image.constBits(), dtype=np.uint8)
    raw = raw.reshape(image.height(), image.bytesPerLine() // 4, 4)[:, : image.width()]
    blue, red = raw[..., 0].astype(int), raw[..., 2].astype(int)
    alpha = raw[..., 3].astype(int)
    return alpha, (alpha > 0) & (blue > red) & (red >= 200)


def _brightest_star(image):
    alpha, stars = _star_pixels(image)
    return int(alpha[stars].max()) if stars.any() else 0


@pytest.fixture
def scene(qapp):
    """A LoopTunnelScene. Needs qapp because painting a QImage needs QGuiApplication."""
    return LoopTunnelScene()


def test_rings_slide_past_rather_than_riding_along(scene):
    """Rings sit at fixed world arc-lengths, not at s + k*spacing.

    Anchoring them to the camera looks identical in a still frame and kills
    the motion entirely: the tunnel would only bend, never approach.
    """
    scene.render(0.0, 0.0)
    first_ring, camera = scene._ring_s[0], scene._s
    scene.render(0.0, 0.0)
    assert scene._s > camera  # the camera advanced...
    assert scene._ring_s[0] == first_ring  # ...and the ring stayed put


def test_silence_still_travels(scene):
    """No audio is a crawl, never a freeze — the loop keeps moving."""
    scene.render(0.0, 0.0)
    quiet = scene._s
    for _ in range(5):
        scene.render(0.0, 0.0)
    assert scene._s > quiet


def test_level_speeds_travel_up(scene):
    loud = LoopTunnelScene()
    scene.render(0.0, 0.0)
    loud.render(1.0, 0.0)
    assert loud._s > scene._s


def test_target_size_follows_the_host_aspect_and_size(scene):
    """Under the cap it renders at the host's own resolution, not a fixed one."""
    scene.set_target_size(1000, 500)
    assert (scene.image().width(), scene.image().height()) == (1000, 500)


def test_a_retina_popout_is_capped_and_left_to_the_host_to_upscale(qapp):
    """1400x800 logical at 2x: 2100x1200 — not 2800x1600, and not the old 448x256.

    The cap bounds a frame at about 8 ms of the 33 this mode has; native would
    be 10.7 here and unbounded on a larger display.
    """
    scene = LoopTunnelScene()
    scene.set_target_size(2800, 1600, popout=True)
    assert (scene.image().width(), scene.image().height()) == (2100, 1200)
    assert scene.image().height() <= POPOUT_CAP[1]


def test_the_backdrop_gets_the_smaller_budget(qapp):
    """The playlist repaint behind it costs ~11 ms; the frame must not add to that."""
    scene = LoopTunnelScene()
    scene.set_target_size(2800, 1600)
    assert scene.image().width() <= BACKDROP_CAP[0]
    assert scene.image().height() <= BACKDROP_CAP[1]


def test_the_focal_length_follows_the_image_height(qapp):
    """Fixed vertical field of view: it is derived from the height, not frozen.

    Left at construction's value, every resize would silently change the field
    of view — a taller image would show *less* of the tunnel, not more of it at
    a finer grain.
    """
    scene = LoopTunnelScene()
    scene.set_target_size(500, 250)  # both sizes under the cap, so both are native
    half = scene._focal
    scene.set_target_size(1000, 500)
    assert scene._focal == pytest.approx(half * 2)


def test_target_size_does_not_reallocate_when_unchanged(scene):
    scene.set_target_size(1000, 500)
    first = scene.image()
    scene.set_target_size(1000, 500)
    # Same object, not merely the same size: this runs before every frame.
    assert scene.image() is first


def test_target_size_ignores_an_unshown_host(scene):
    """A viewport on a non-current page can report nothing; keep what we had."""
    scene.set_target_size(1000, 500)
    before = scene.image()
    scene.set_target_size(0, 0)
    scene.set_target_size(-4, 300)
    assert scene.image() is before


def test_the_cap_never_distorts_the_aspect(qapp):
    """A stretched wireframe draws ellipses where the rings should be."""
    scene = LoopTunnelScene()
    for width, height in ((3000, 600), (2800, 1600), (600, 1200)):
        scene.set_target_size(width, height, popout=True)
        image = scene.image()
        assert image.width() / image.height() == pytest.approx(width / height, rel=0.01)


def test_a_star_keeps_its_apparent_size_as_the_resolution_changes(qapp):
    """The cell is a size at _REF_H, scaled with the image.

    This is the property that lets the render resolution move at all: the image
    is drawn into a fixed logical rect, so a star cell of ``n * height /
    _REF_H`` lands at the same size on screen whatever height the image is. Left
    as a constant, raising the resolution would have shrunk the stars to
    hairlines — the wireframe would have got its detail by deleting the sky.
    """
    scene = LoopTunnelScene()
    scene.set_target_size(512, 256, popout=True)
    small = scene.star_cell()
    scene.set_target_size(2048, 1024, popout=True)  # popout: both under its cap
    assert scene.star_cell() == small * 4


def test_the_pen_keeps_its_apparent_width_as_the_resolution_changes(qapp):
    """Same rule for the wireframe: finer, not thinner.

    Measured on the rendered frame rather than on the constant, because the
    constant is applied at the paint and a test on it would pass against a paint
    that ignored it. A ring at the same place in the same flight should cover
    the same *fraction* of the frame at either resolution.
    """
    def lit_fraction(height: int) -> float:
        scene = LoopTunnelScene()
        scene.set_target_size(height * 2, height)
        for _ in range(6):
            scene.render(0.6, 0.0)
        image = scene.image().convertToFormat(QImage.Format.Format_ARGB32)
        raw = np.frombuffer(image.constBits(), dtype=np.uint8)
        raw = raw.reshape(image.height(), image.bytesPerLine() // 4, 4)[:, : image.width()]
        return float((raw[..., 3] > 80).mean())

    assert lit_fraction(512) == pytest.approx(lit_fraction(256), rel=0.25)


def test_a_host_smaller_than_the_cap_renders_at_its_own_size(qapp):
    scene = LoopTunnelScene()
    scene.set_target_size(400, 200)
    assert (scene.image().width(), scene.image().height()) == (400, 200)


def test_it_draws_a_tunnel_and_stars(scene):
    """Rings down the middle, and stars off to the side."""
    for _ in range(4):
        scene.render(0.6, 0.0)
    image = scene.image()
    width, height = image.width(), image.height()
    band = range(height // 2 - 8, height // 2 + 8)
    centre = [
        image.pixelColor(x, y).alpha()
        for y in band
        for x in range(width // 2 - 40, width // 2 + 40)
    ]
    assert max(centre) > 0

    assert _star_pixels(image)[1].any()


# ── VisRenderer integration ────────────────────────────────────────────────


def _noise(rng):
    return (rng.standard_normal(FFT_SIZE) * 0.2).astype(np.float32)


def test_renderer_returns_the_loop_tunnels_own_image(qapp):
    renderer = VisRenderer()
    renderer.set_mode("loop_tunnel")
    renderer.set_target_size(1000, 500)
    image = renderer.render(_noise(np.random.default_rng(0)), 44100)
    assert (image.width(), image.height()) == (1000, 500)
    assert renderer.image() is image


def test_the_renderer_tells_the_scene_which_host_is_asking(qapp):
    """The popout's cap is more than twice the backdrop's, and only this passes it.

    Dropped, the fix is half-applied and silent: the popout renders at the
    backdrop's 512 and looks better than it did but not as it should, with
    nothing anywhere to say why.
    """
    renderer = VisRenderer()
    renderer.set_mode("loop_tunnel")
    renderer.set_target_size(2800, 1600, popout=True)
    popout = renderer.render(_noise(np.random.default_rng(0)), 44100)
    assert popout.height() > BACKDROP_CAP[1]

    renderer.set_target_size(2800, 1600)
    backdrop = renderer.render(_noise(np.random.default_rng(0)), 44100)
    assert backdrop.height() <= BACKDROP_CAP[1]


def test_switching_away_leaves_the_other_modes_at_their_own_size(qapp):
    """The loop tunnel image must never land in VisRenderer._image (trap 7.1).

    The scope and spectrum renderers paint into that image at 152x64; if a
    608-wide one were left there they would draw into a corner of it and every
    host would happily stretch the result.
    """
    renderer = VisRenderer()
    renderer.set_mode("loop_tunnel")
    renderer.render(_noise(np.random.default_rng(0)), 44100)
    renderer.set_mode("spectrum")
    image = renderer.render(_noise(np.random.default_rng(1)), 44100)
    assert (image.width(), image.height()) == (152, 64)
    renderer.set_mode("spectrum")
    image = renderer.render(_noise(np.random.default_rng(2)), 44100)
    assert (image.width(), image.height()) == (152, 64)


def test_set_target_size_is_harmless_for_the_other_modes(qapp):
    renderer = VisRenderer()
    renderer.set_mode("fire")
    renderer.set_target_size(1000, 500)
    image = renderer.render(_noise(np.random.default_rng(0)), 44100)
    assert (image.width(), image.height()) == (152, 64)


def test_mode_is_allow_listed_and_offered_by_both_hosts():
    assert "loop_tunnel" in RENDER_MODES
    assert "loop_tunnel" in POPOUT_MODES
    assert "loop_tunnel" in _VALID_VIS_MODES
    assert "backdrop_loop_tunnel" in _VALID_VIS_MODES
    assert _BACKDROP_VIS_MAP["backdrop_loop_tunnel"] == "loop_tunnel"


def test_a_frame_stays_cheap(qapp):
    """A loose guard against an accidental O(pixels) rewrite.

    At the popout's cap — which is where the mode is most expensive, and what
    it renders on a Retina display — it measures ~8 ms against a 33 ms budget.
    The bound here is well above that so it can't flake under a full-suite
    load. If it ever does flake anyway, delete it rather than widen it — the
    real cost lives in the plan, not in this number.
    """
    renderer = VisRenderer()
    renderer.set_mode("loop_tunnel")
    renderer.set_target_size(2800, 1600, popout=True)
    rng = np.random.default_rng(0)
    renderer.render(_noise(rng), 44100)  # first frame builds the loop path
    times = []
    for _ in range(60):
        start = time.perf_counter()
        renderer.render(_noise(rng), 44100)
        times.append(time.perf_counter() - start)
    assert float(np.median(times)) * 1000 < 25.0


# ── Stars respond to the kick ──────────────────────────────────────────────


def test_stars_are_lit_by_the_kick(scene):
    """Barely there between beats, full on the kick."""
    for _ in range(30):  # settle: no kicks at all
        scene.render(0.3, 0.0)
    quiet = _brightest_star(scene.image())
    scene.render(0.3, 1.0)
    assert _brightest_star(scene.image()) > 3 * quiet


def test_the_kick_glow_fades_rather_than_snapping_back(scene):
    """Fast attack, slow release — the fractal's shape, driven by the pulse.

    A bare `pulse` would strobe: the detector's own value collapses within a
    frame or two of the transient.
    """
    scene.render(0.3, 1.0)
    lit = _brightest_star(scene.image())
    assert scene._star_glow == 1.0
    glows = []
    for _ in range(6):
        scene.render(0.3, 0.0)
        glows.append(scene._star_glow)
    assert glows == sorted(glows, reverse=True)
    assert 0.0 < glows[-1] < 1.0
    assert _brightest_star(scene.image()) < lit


def test_stars_never_go_out_entirely(scene):
    """The floor keeps a starfield there for a track with no kick in it."""
    scene.render(0.3, 1.0)
    for _ in range(200):
        scene.render(0.3, 0.0)
    assert scene._star_glow < 0.01  # the glow really has gone
    assert _brightest_star(scene.image()) > 0  # the stars have not



def test_stars_are_crosses_rather_than_blocks(scene):
    """A star's diagonal cells are empty; a solid block's would not be.

    Counting rather than picking one star, because stars overlap each other
    and the mesh — so the question is the shape of the field, not of a
    hand-chosen sample.
    """
    for _ in range(3):
        scene.render(0.3, 1.0)  # kick-lit, so the arms are at full alpha
    _alpha, lit = _star_pixels(scene.image())
    cell = scene.star_cell()

    def shifted(dx, dy):
        return np.roll(np.roll(lit, dy * cell, axis=0), dx * cell, axis=1)

    # A "core" is a cell lit on all four sides — the centre of a cross, or an
    # interior cell of a block.
    core = lit & shifted(1, 0) & shifted(-1, 0) & shifted(0, 1) & shifted(0, -1)
    diagonals = sum(
        shifted(dx, dy).astype(int) for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1))
    )
    assert core.sum() >= 10  # enough cores to be talking about the field
    assert float(diagonals[core].mean()) < 1.0  # a block would score 4
