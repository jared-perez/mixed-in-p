"""The fire backdrop's height, fade, tongues and wind (2026-09-22).

The fire used to die 36 rows up a 64-row grid — never past half the playlist —
and what rose in it was horizontal *bands* of heat, one per frame of band
energy, because every column of the bottom row was stoked by the same smooth
curve. Bending those bands (the first fix) looked like rippled water. What
these tests pin: the reach (about 3/4 of the height) and the fade above it
that keeps the top rows clean; that the source is a bed of embers so the
heat rises as tongues that narrow to points; that the wind leans them; and
that the fire's clock is in seconds, the same for a second of audio at either
frame interval.
"""

import numpy as np
import pytest

from src.gui.widgets.vis_canvas import (
    FAST_FRAME_MS,
    FFT_SIZE,
    FRAME_MS,
    VisRenderer,
    _H,
    _W,
)

SR = 44100
SILENCE = np.zeros(FFT_SIZE, dtype=np.float32)


def loud(seed=0):
    """Broadband noise: every log band lit, a full-width stoke."""
    rng = np.random.default_rng(seed)
    return rng.normal(0, 0.4, FFT_SIZE).astype(np.float32)


def alpha(image):
    w, h = image.width(), image.height()
    buf = image.constBits()
    return np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)[..., 3]


def rows_from_bottom(alpha_plane, threshold):
    """How many rows up the highest pixel at or over *threshold* sits."""
    lit = np.flatnonzero(alpha_plane.max(axis=1) >= threshold)
    return _H - lit[0] if len(lit) else 0


def runs(mask):
    """Number of separate runs of True along a 1-D mask."""
    padded = np.concatenate([[False], mask, [False]])
    return int(np.count_nonzero(padded[1:] & ~padded[:-1]))


@pytest.fixture
def fire(qapp):
    renderer = VisRenderer()
    renderer.set_mode("fire")
    renderer.set_frame_interval(FRAME_MS)
    return renderer


def burn(renderer, frames=120):
    image = None
    for i in range(frames):
        image = renderer.render(loud(i), SR)
    return alpha(image)


class TestReachAndFade:
    def test_a_loud_track_reaches_about_three_quarters(self, fire):
        # 0.25 alpha is 10% over the grey at the backdrop's 0.40 — the faintest
        # thing the eye still reads as fire. The old fire stopped at 34 rows.
        reach = rows_from_bottom(burn(fire), 64)
        assert 0.62 * _H <= reach <= 0.82 * _H, reach

    def test_the_rows_above_the_fade_stay_clean(self, fire):
        plane = burn(fire)
        top = int(_H * (1 - 0.9))
        assert plane[:top].max() == 0

    def test_the_fade_is_gradual(self, fire):
        # Mean alpha over slices going up falls monotonically, and the top
        # slice is well under the body's.
        plane = burn(fire).astype(float)
        body = plane[int(_H * 0.7) : int(_H * 0.8)].mean()
        low = plane[int(_H * 0.40) : int(_H * 0.48)].mean()
        mid = plane[int(_H * 0.30) : int(_H * 0.38)].mean()
        high = plane[int(_H * 0.20) : int(_H * 0.28)].mean()
        assert body > low > mid > high
        assert high < 0.25 * body

    def test_silence_still_burns_down(self, fire):
        burn(fire)
        for _ in range(250):
            image = fire.render(SILENCE, SR)
        assert alpha(image).max() == 0


class TestTongues:
    def test_the_base_is_a_bed_with_hot_spots(self, fire):
        embers = fire._fire_embers_now()
        assert embers.shape == (_W,)
        assert embers.min() >= 0.19 and embers.max() > 0.9
        # Several spots, not one: the hot columns come in separate runs.
        assert runs(embers > 0.6) >= 3

    def test_the_spots_wander(self, fire):
        before = fire._fire_embers_now().copy()
        fire._fire_time += 3.0
        after = fire._fire_embers_now()
        assert np.abs(after - before).max() > 0.3

    def test_heat_narrows_to_points_as_it_rises(self, fire):
        # A steady, even stoke: the picture's lit width must shrink with
        # height (the blur spreads a spot, the cooling clips its edges), and
        # near the reach what is left is a few separate tips, not a band.
        for _ in range(120):
            fire.render(loud(1), SR)
        plane = alpha(fire.render(loud(1), SR))
        lit = plane >= 64
        width_at = lambda frac: int(lit[_H - 1 - int(frac * _H)].sum())  # noqa: E731
        assert width_at(0.1) > width_at(0.4) > width_at(0.6) > 0
        reach = rows_from_bottom(plane, 64)
        # Six rows under the very top (which may be one tongue's last pixel).
        tip_row = _H - reach + 6
        assert width_at(0.1) >= 0.8 * _W  # the bed spans the width
        assert lit[tip_row].sum() < 0.4 * _W  # the tips do not
        assert runs(lit[tip_row]) >= 2  # and they are separate points

    def test_a_surge_reaches_the_hot_spots_first(self, qapp):
        # From cold, two loud frames: the hottest ember column is most of the
        # way to its own target while the bed is still well short of its own —
        # the surge does not rise as one shelf. The target is what a renderer
        # with an instant attack holds after the same frames.
        def cold_then_loud(renderer):
            renderer.set_mode("fire")
            for _ in range(30):
                renderer.render(SILENCE, SR)
            for _ in range(2):
                renderer.render(loud(3), SR)

        instant = VisRenderer()
        instant._fire_attack = lambda embers: np.ones(_W, dtype=np.float32)
        cold_then_loud(instant)
        fire = VisRenderer()
        cold_then_loud(fire)
        fraction = fire._fire_stoke / np.maximum(instant._fire_stoke, 1e-6)
        embers = fire._fire_embers_now()
        hot = int(embers.argmax())
        bed = int(embers.argmin())
        assert fraction[hot] > 0.5
        assert fraction[bed] < 0.35
        assert fraction[bed] < 0.5 * fraction[hot]
        # And the attack itself varies across the width, not just between
        # the two extremes: a per-patch jitter, not a two-speed switch.
        attack = fire._fire_attack(embers)
        assert len(np.unique(np.round(attack, 2))) > 10

    def test_a_kick_lifts_the_flame_then_settles(self, fire):
        # The pulse is recomputed from the audio inside render, so it is
        # planted after the band analysis, where the fire reads it.
        original = fire._band_heights

        def plant(value):
            def band_heights(samples, sr):
                heights = original(samples, sr)
                fire._pulse = value
                return heights

            fire._band_heights = band_heights

        fire.render(SILENCE, SR)
        plant(1.0)
        fire.render(loud(0), SR)
        assert fire._fire_kick == 1.0
        plant(0.0)
        levels = []
        for _ in range(3):
            fire.render(loud(0), SR)
            levels.append(fire._fire_kick)
        assert 0.8 < levels[0] < 1.0 and levels[0] > levels[1] > levels[2] > 0.5

    def test_the_stoke_holds_between_hits(self, fire):
        # A loud frame then silence: the base curve releases over frames
        # rather than halving at once, so one hit does not stamp a row.
        fire.render(loud(0), SR)
        peak = fire._fire_stoke.max()
        fire.render(SILENCE, SR)
        assert 0.85 * peak <= fire._fire_stoke.max() < peak


class TestWind:
    def _lean(self, fire, sign):
        # Force the wind one way and measure where the heat sits high up
        # against where it sits at the base.
        fire._fire_wind = lambda embers: sign * np.full((_H - 1, 1), 0.9, dtype=np.float32)
        for _ in range(120):
            fire.render(loud(2), SR)
        heat = fire._heat
        cols = np.arange(_W, dtype=float)

        def centroid(row):
            weights = heat[row]
            return float((weights * cols).sum() / max(weights.sum(), 1e-9))

        return centroid(int(_H * 0.5)) - centroid(_H - 1)

    def test_the_wind_leans_the_flames(self, qapp):
        leans = []
        for sign in (1.0, -1.0):
            renderer = VisRenderer()
            renderer.set_mode("fire")
            leans.append(self._lean(renderer, sign))
        assert leans[0] > 2.0  # a positive wind carries heat rightward
        assert leans[1] < -2.0

    def test_the_wind_is_anchored_at_the_base_and_swings(self, fire):
        embers = fire._fire_embers_now()
        wind = fire._fire_wind(embers)
        assert wind.shape == (_H - 1, _W)
        assert np.abs(wind[-1]).max() < 0.1  # the row above the base: nearly still
        fire._fire_time += 1.0
        assert np.abs(fire._fire_wind(embers) - wind).max() > 0.5

    def test_each_tongue_sways_on_its_own(self, fire):
        # Half-way up, at any moment, some patches lean left while others
        # lean right — the tongues cross, they do not lean as one.
        embers = fire._fire_embers_now()
        for t in (0.0, 0.7, 1.9):
            fire._fire_time = t
            row = fire._fire_wind(embers)[int(_H * 0.5)]
            assert row.max() > 0.3 and row.min() < -0.3
        # And the phase is per patch, not per pixel: neighbours agree.
        assert np.abs(np.diff(fire._fire_wind_phase)).max() < 0.7

    def test_big_flames_sway_slower(self, fire):
        embers = fire._fire_embers_now()
        rate = fire._fire_wind_rate(embers)
        assert rate[int(embers.argmax())] < 0.6 * rate[int(embers.argmin())]

    def test_the_fire_clock_is_in_seconds(self, qapp):
        # A second of frames at 16 ms and at 33 ms lands on the same time
        # and the same stoke, so the wind's phase, the embers' drift and the
        # attack/release are rates, not per-frame increments wearing a frame
        # count.
        times, stokes = [], []
        for frame_ms in (FRAME_MS, FAST_FRAME_MS):
            renderer = VisRenderer()
            renderer.set_mode("fire")
            renderer.set_frame_interval(frame_ms)
            for _ in range(round(1000 / frame_ms)):
                renderer.render(loud(4), SR)
            times.append(renderer._fire_time)
            stokes.append(renderer._fire_stoke.copy())
        assert abs(times[0] - times[1]) < 0.02
        assert np.abs(stokes[0] - stokes[1]).max() < 0.1
