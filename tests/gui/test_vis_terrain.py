"""The terrain flight — the visual the menu calls Mountain flight.

The brief: a wireframe range built on the horizon from the volume, mirrored
overhead, flown by a camera that banks through slow turns. Each of those is
asserted here on the scene's own state or on its rendered frame, never on
constants.
"""

import time

import numpy as np
import pytest
from PySide6.QtGui import QImage

from src.gui.widgets.player_panel import _BACKDROP_VIS_MAP
from src.gui.widgets.vis_canvas import FFT_SIZE, POPOUT_MODES, RENDER_MODES, VisRenderer
from src.gui.widgets.vis_terrain import (
    ALT,
    BACKDROP_CAP,
    MAX_H,
    POPOUT_CAP,
    ROWS,
    SPACING,
    TerrainScene,
)
from src.utils.config import _VALID_VIS_MODES


def _alpha(image: QImage) -> np.ndarray:
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    raw = np.frombuffer(image.constBits(), dtype=np.uint8)
    raw = raw.reshape(image.height(), image.bytesPerLine() // 4, 4)[:, : image.width()]
    return raw[..., 3].astype(int)


@pytest.fixture
def scene(qapp):
    """A TerrainScene at a modest size. Needs qapp: painting a QImage needs QGuiApplication."""
    s = TerrainScene()
    s.set_target_size(800, 400)
    return s


def _fly(scene: TerrainScene, frames: int, level: float, pulse: float = 0.0) -> None:
    for _ in range(frames):
        scene.render(level, pulse)


# ── The range is built from the volume ─────────────────────────────────────


def test_rows_slide_past_rather_than_riding_along(scene):
    """Rows sit at fixed world depths; the camera advances through them.

    Anchored to the camera they would only change shape, never approach.
    """
    scene.render(0.0, 0.0)
    before = scene.row_depths()
    born = scene._born
    scene.render(0.0, 0.0)
    if scene._born == born:  # no row retired in between: every depth fell
        assert np.all(scene.row_depths() < before)
    else:  # one did: the buffer rolled, and the old second row is the new first
        assert before[1] - SPACING < scene.row_depths()[0] < before[1]


def test_silence_still_travels(scene):
    scene.render(0.0, 0.0)
    quiet = scene._s
    _fly(scene, 5, 0.0)
    assert scene._s > quiet


def test_level_speeds_travel_up(qapp):
    quiet, loud = TerrainScene(), TerrainScene()
    quiet.render(0.0, 0.0)
    loud.render(1.0, 0.0)
    assert loud._s > quiet._s


def test_a_loud_passage_builds_a_range_and_a_quiet_one_a_plain(qapp):
    """New rows are born from the level at the moment of their birth."""
    quiet, loud = TerrainScene(), TerrainScene()
    _fly(quiet, 90, 0.0)
    _fly(loud, 90, 1.0)
    assert loud.heights().mean() > 2.0 * quiet.heights().mean()
    assert quiet.heights().max() > 0.0  # silence is a low plain, not a void


def test_the_kick_plants_a_peak(qapp):
    """The same flight with one kick in it grows a taller mountain."""
    plain, kicked = TerrainScene(), TerrainScene()
    _fly(plain, 40, 0.3)
    _fly(kicked, 40, 0.3)
    plain.render(0.3, 0.0)
    kicked.render(0.3, 1.0)
    _fly(plain, 20, 0.3)
    _fly(kicked, 20, 0.3)
    # The newest rows are the ones born since the kick.
    assert kicked.heights()[-12:].max() > plain.heights()[-12:].max() + 0.2


def test_a_kick_between_two_births_is_not_lost(qapp):
    """Rows are born every few frames; a one-frame pulse in between must
    still reach the next row."""
    scene = TerrainScene()
    _fly(scene, 30, 0.2)
    born = scene._born
    scene.render(0.2, 1.0)
    # Whether or not that frame bore a row, the next birth carries the kick.
    while scene._born <= born + 1:
        scene.render(0.2, 0.0)
    assert scene._peak is not None or scene.heights()[-3:].max() > 0.5


def test_peaks_never_reach_the_camera(qapp):
    """Whatever the music does, the buffer stays under MAX_H of ALT."""
    scene = TerrainScene()
    for i in range(200):
        scene.render(1.0, 1.0 if i % 3 == 0 else 0.0)
    assert scene.heights().max() <= 1.0
    assert MAX_H < ALT


# ── Mirrored overhead, horizon at mid-screen ───────────────────────────────


def test_the_ceiling_mirrors_the_ground(scene):
    """With the camera on a rail, the top half is the bottom half flipped."""
    scene.set_sway(0.0)
    for i in range(60):
        scene.render(0.7, 1.0 if i % 10 == 0 else 0.0)
    alpha = _alpha(scene.image())
    top, bottom = alpha[: alpha.shape[0] // 2], alpha[alpha.shape[0] // 2 :][::-1]
    lit_top, lit_bottom = top > 40, bottom > 40
    assert lit_top.sum() > 500  # something was drawn in each half
    assert lit_bottom.sum() > 500
    overlap = (lit_top & lit_bottom).sum() / (lit_top | lit_bottom).sum()
    assert overlap > 0.8


def test_the_range_is_built_around_the_middle_of_the_frame(scene):
    """The far edge sits on the horizon — mid-screen — with a gap between the
    two ranges, and the near rows reach the frame's top and bottom edges."""
    scene.set_sway(0.0)
    _fly(scene, 80, 0.7)
    lit = _alpha(scene.image()) > 40
    height = lit.shape[0]
    rows_lit = lit.any(axis=1)
    middle = height // 2
    assert not rows_lit[middle - 2 : middle + 2].any()  # the horizon gap
    top_of_ground = np.flatnonzero(rows_lit[middle:])[0]  # px below the middle
    assert top_of_ground < 0.25 * height
    assert rows_lit[height - 1] and rows_lit[0]


def test_a_nearer_ridge_hides_the_rows_behind_it(scene):
    """Hidden-line removal: the surface is opaque to the lines behind it.

    A full-height ridge is set on one near row and the rows behind it
    flattened; on a rail, those flat rows project *below* the ridgeline (the
    ridge is closer to the horizon than they are) and must not show there.
    Without the erase every one of them crosses the band.
    """
    scene.set_sway(0.0)
    scene.render(0.0, 0.0)
    scene._rows[:] = 0.0
    scene._rows[3] = 1.0
    scene.render(0.0, 0.0)
    scene._rows[:] = 0.0  # keep the same rows in place for the paint below
    scene._rows[3] = 1.0
    image = scene.image()
    width, height = image.width(), image.height()
    z3 = scene.row_depths()[3]
    ridge_y = int(height / 2 + scene._focal * (ALT - MAX_H) / z3)
    lit = _alpha(image) > 40
    band = lit[ridge_y + 4 :, width * 3 // 8 : width * 5 // 8]
    assert band.shape[0] > 20
    # Spokes down the near face cross each pixel row a few pixels wide; a
    # ridgeline of a hidden row would light most of the band's width.
    assert band.mean(axis=1).max() < 0.5


# ── The camera soars ───────────────────────────────────────────────────────


def test_the_camera_banks_yaws_and_pitches(qapp):
    scene = TerrainScene()
    t = np.arange(0.0, 60.0, 0.1)
    angles = np.array([scene.camera_angles(x) for x in t])
    yaw, pitch, roll = angles.T
    for series in (yaw, pitch, roll):
        assert series.min() < 0.0 < series.max()
    assert np.abs(roll).max() >= 8.0
    assert np.abs(yaw).max() >= 5.0


def test_the_bank_follows_the_turn(qapp):
    """A bird leans into its turn: roll tracks the yaw *rate*, not the yaw."""
    scene = TerrainScene()
    t = np.arange(0.0, 60.0, 0.1)
    angles = np.array([scene.camera_angles(x) for x in t])
    yaw, _pitch, roll = angles.T
    yaw_rate = np.gradient(yaw, t)
    assert np.corrcoef(roll, yaw_rate)[0, 1] > 0.8
    assert abs(np.corrcoef(roll, yaw)[0, 1]) < 0.5


def test_sway_off_is_a_rail(qapp):
    scene = TerrainScene()
    scene.set_sway(0.0)
    assert scene.camera_angles(12.3) == (0.0, 0.0, 0.0)


def test_the_flight_is_the_same_at_16_and_33_ms(qapp):
    """Every rate is per second: the popout host and the backdrop host fly
    the same second of music to the same place, and the level follower
    releases over the same time."""
    fast, slow = TerrainScene(), TerrainScene()
    fast.set_frame_interval(16.0)
    slow.set_frame_interval(33.0)

    def level_at(t: float) -> float:
        return 1.0 if t < 0.4 else 0.0

    for scene, dt in ((fast, 0.016), (slow, 0.033)):
        t = 0.0
        while t < 1.5:
            scene.render(level_at(t), 0.0)
            t += dt
    assert fast._s == pytest.approx(slow._s, rel=0.03)
    assert fast._time == pytest.approx(slow._time, abs=0.04)
    assert fast._amp == pytest.approx(slow._amp, rel=0.1)
    assert 0.0 < slow._amp < 0.5  # released, not held and not gone


# ── Sizing and cost ────────────────────────────────────────────────────────


def test_the_image_is_half_the_host_under_the_cap(qapp):
    """A one-pixel pen at half the host's resolution is the line weight."""
    scene = TerrainScene()
    scene.set_target_size(1000, 500)
    assert (scene.image().width(), scene.image().height()) == (500, 250)
    scene.set_target_size(2800, 1600, popout=True)
    assert scene.image().height() == POPOUT_CAP[1]
    assert scene.image().width() / scene.image().height() == pytest.approx(2800 / 1600, rel=0.01)


def test_the_backdrop_gets_the_smaller_budget(qapp):
    scene = TerrainScene()
    scene.set_target_size(2800, 1600)
    assert scene.image().width() <= BACKDROP_CAP[0]
    assert scene.image().height() <= BACKDROP_CAP[1]
    assert BACKDROP_CAP[1] < POPOUT_CAP[1]


def test_the_cap_never_distorts_the_aspect(qapp):
    scene = TerrainScene()
    for width, height in ((3000, 600), (2800, 1600), (600, 1200)):
        scene.set_target_size(width, height, popout=True)
        image = scene.image()
        assert image.width() / image.height() == pytest.approx(width / height, rel=0.02)


def test_the_focal_length_follows_the_image_height(qapp):
    scene = TerrainScene()
    scene.set_target_size(500, 250)
    half = scene._focal
    scene.set_target_size(1000, 500)
    assert scene._focal == pytest.approx(half * 2)


def test_target_size_does_not_reallocate_when_unchanged(scene):
    first = scene.image()
    scene.set_target_size(800, 400)
    assert scene.image() is first


def test_target_size_ignores_an_unshown_host(scene):
    before = scene.image()
    scene.set_target_size(0, 0)
    scene.set_target_size(-4, 300)
    assert scene.image() is before


def test_a_frame_stays_cheap(qapp):
    """A loose guard against an accidental slow path (a pen over one pixel
    wide, an antialiased erase): measured ~4 ms at the popout cap against a
    33 ms budget. Delete rather than widen if it flakes."""
    renderer = VisRenderer()
    renderer.set_mode("terrain")
    renderer.set_target_size(2800, 1600, popout=True)
    rng = np.random.default_rng(0)

    def noise():
        return (rng.standard_normal(FFT_SIZE) * 0.2).astype(np.float32)

    for _ in range(20):
        renderer.render(noise(), 44100)
    times = []
    for _ in range(40):
        start = time.perf_counter()
        renderer.render(noise(), 44100)
        times.append(time.perf_counter() - start)
    assert float(np.median(times)) * 1000 < 15.0


# ── VisRenderer integration ────────────────────────────────────────────────


def _noise(rng):
    return (rng.standard_normal(FFT_SIZE) * 0.2).astype(np.float32)


def test_renderer_returns_the_terrains_own_image(qapp):
    renderer = VisRenderer()
    renderer.set_mode("terrain")
    renderer.set_target_size(1000, 500)
    image = renderer.render(_noise(np.random.default_rng(0)), 44100)
    assert (image.width(), image.height()) == (500, 250)
    assert renderer.image() is image


def test_switching_away_leaves_the_other_modes_at_their_own_size(qapp):
    renderer = VisRenderer()
    renderer.set_mode("terrain")
    renderer.set_target_size(1000, 500)
    renderer.render(_noise(np.random.default_rng(0)), 44100)
    renderer.set_mode("spectrum")
    image = renderer.render(_noise(np.random.default_rng(1)), 44100)
    assert (image.width(), image.height()) == (152, 64)


def test_the_renderer_resets_the_flight_on_mode_entry(qapp):
    renderer = VisRenderer()
    renderer.set_mode("terrain")
    for _ in range(10):
        renderer.render(_noise(np.random.default_rng(0)), 44100)
    assert renderer._terrain._s > 0.0
    renderer.set_mode("terrain")
    assert renderer._terrain._s == 0.0


def test_the_renderer_forwards_the_frame_interval(qapp):
    renderer = VisRenderer()
    renderer.set_frame_interval(16.0)
    assert renderer._terrain._dt == pytest.approx(0.016)


def test_mode_is_allow_listed_and_offered_by_both_hosts():
    assert "terrain" in RENDER_MODES
    assert "terrain" in POPOUT_MODES
    assert "terrain" in _VALID_VIS_MODES
    assert "backdrop_terrain" in _VALID_VIS_MODES
    assert _BACKDROP_VIS_MAP["backdrop_terrain"] == "terrain"


def test_the_mode_wants_a_smooth_upscale(qapp):
    """Drawn at half the host's size with one-pixel lines; a nearest-neighbour
    blow-up would turn every line into a staircase."""
    renderer = VisRenderer()
    renderer.set_mode("terrain")
    assert renderer.smooth_upscale()
