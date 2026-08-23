"""The wormhole visualization: its path, its image, and its wiring.

The brief the path has to meet is asserted directly (§5.1) — at least 13
turns, at least three straightaways, walls that never fold into themselves —
so a regenerated loop can't quietly stop being a wormhole.
"""

import time

import numpy as np
import pytest
from PySide6.QtGui import QImage

from src.gui.widgets.player_panel import _BACKDROP_VIS_MAP
from src.gui.widgets.vis_canvas import FFT_SIZE, POPOUT_MODES, RENDER_MODES, VisRenderer
from src.gui.widgets import vis_wormhole
from src.gui.widgets.vis_wormhole import (
    TUNNEL_R,
    WormholeScene,
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
    """A WormholeScene. Needs qapp because painting a QImage needs QGuiApplication."""
    return WormholeScene()


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
    loud = WormholeScene()
    scene.render(0.0, 0.0)
    loud.render(1.0, 0.0)
    assert loud._s > scene._s


def test_target_size_follows_the_host_aspect(scene):
    scene.set_target_size(1000, 500)
    assert scene.image().width() == 512  # round(256 * 2)
    assert scene.image().height() == 256


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


def test_target_size_clamps(scene):
    scene.set_target_size(10000, 100)  # absurdly wide
    assert scene.image().width() == 1024
    scene.set_target_size(10, 1000)  # absurdly tall
    assert scene.image().width() == 128


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


def test_renderer_returns_the_wormholes_own_image(qapp):
    renderer = VisRenderer()
    renderer.set_mode("wormhole")
    renderer.set_target_size(1000, 500)
    image = renderer.render(_noise(np.random.default_rng(0)), 44100)
    assert (image.width(), image.height()) == (512, 256)
    assert renderer.image() is image


def test_switching_away_leaves_the_other_modes_at_their_own_size(qapp):
    """The wormhole image must never land in VisRenderer._image (trap 7.1).

    The scope and spectrum renderers paint into that image at 152x64; if a
    608-wide one were left there they would draw into a corner of it and every
    host would happily stretch the result.
    """
    renderer = VisRenderer()
    renderer.set_mode("wormhole")
    renderer.render(_noise(np.random.default_rng(0)), 44100)
    renderer.set_mode("spectrum")
    image = renderer.render(_noise(np.random.default_rng(1)), 44100)
    assert (image.width(), image.height()) == (152, 64)
    renderer.set_mode("oscilloscope")
    image = renderer.render(_noise(np.random.default_rng(2)), 44100)
    assert (image.width(), image.height()) == (152, 64)


def test_set_target_size_is_harmless_for_the_other_modes(qapp):
    renderer = VisRenderer()
    renderer.set_mode("fire")
    renderer.set_target_size(1000, 500)
    image = renderer.render(_noise(np.random.default_rng(0)), 44100)
    assert (image.width(), image.height()) == (152, 64)


def test_mode_is_allow_listed_and_offered_by_both_hosts():
    assert "wormhole" in RENDER_MODES
    assert "wormhole" in POPOUT_MODES
    assert "wormhole" in _VALID_VIS_MODES
    assert "backdrop_wormhole" in _VALID_VIS_MODES
    assert _BACKDROP_VIS_MAP["backdrop_wormhole"] == "wormhole"


def test_a_frame_stays_cheap(qapp):
    """A loose guard against an accidental O(pixels) rewrite.

    The mode measures ~1.6 ms/frame against a 33 ms budget; the bound here is
    an order of magnitude above that so it can't flake under a full-suite
    load. If it ever does flake anyway, delete it rather than widen it — the
    real cost lives in the plan, not in this number.
    """
    renderer = VisRenderer()
    renderer.set_mode("wormhole")
    renderer.set_target_size(608, 256)
    rng = np.random.default_rng(0)
    renderer.render(_noise(rng), 44100)  # first frame builds the loop path
    times = []
    for _ in range(60):
        start = time.perf_counter()
        renderer.render(_noise(rng), 44100)
        times.append(time.perf_counter() - start)
    assert float(np.median(times)) * 1000 < 15.0


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
    cell = vis_wormhole._STAR_CELL

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
