"""The wormhole visualization: its path, its image, and its wiring.

The brief the path has to meet is asserted directly (§5.1) — at least 13
turns, at least three straightaways, walls that never fold into themselves —
so a regenerated loop can't quietly stop being a wormhole.
"""

import time

import numpy as np
import pytest

from src.gui.widgets.player_panel import _BACKDROP_VIS_MAP
from src.gui.widgets.vis_canvas import FFT_SIZE, POPOUT_MODES, RENDER_MODES, VisRenderer
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
    """Rings down the middle, and at least one star block off to the side."""
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

    # Stars are white-blue blocks; the mesh is the waveform colour, so look
    # for a bluish pixel well outside the tunnel mouth.
    def is_star(color):
        return color.alpha() > 0 and color.blue() > color.red() >= 200

    found = any(
        is_star(image.pixelColor(x, y))
        for y in range(0, height, 2)
        for x in range(0, width, 2)
    )
    assert found


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
