"""Per-column waveform colours from the analysis (src/gui/waveform_palette.py).

Qt-free. The distinction the normalisation setting exists for is pinned here:
absolute maps one band share to one colour in every track, per-track does not.
"""

import numpy as np
import pytest

from src.gui import waveform_palette as wp
from src.gui.waveform_palette import column_colors
from src.utils.config import WAVEFORM_COLOR_MODES

BASE = "#f0ff00"
N = 200


def analysis(seed=0, n=N):
    rng = np.random.default_rng(seed)
    raw = rng.random((n, 3)) + 0.05
    shares = raw / raw.sum(axis=1, keepdims=True)
    low, mid, high = (shares[:, i].astype(np.float32) for i in range(3))
    centroid = (200 + 3000 * rng.random(n)).astype(np.float32)
    peaks = rng.random(n).astype(np.float32)
    return dict(peaks=peaks, low=low, mid=mid, high=high, centroid=centroid)


@pytest.mark.parametrize("absolute", [False, True])
@pytest.mark.parametrize("mode", WAVEFORM_COLOR_MODES)
def test_every_mode_returns_one_rgb_row_per_column(mode, absolute):
    out = column_colors(mode, absolute, base_color=BASE, columns=N, **analysis())
    assert out.shape == (N, 3)
    assert out.dtype == np.uint8


def test_the_frequency_modes_are_the_ones_that_need_the_fft():
    assert {m for m in WAVEFORM_COLOR_MODES if wp.needs_spectral(m)} == {"bands", "centroid"}


def test_solid_ignores_the_analysis():
    a = column_colors("solid", False, base_color=BASE, columns=N, **analysis(1))
    b = column_colors("solid", True, base_color=BASE, columns=N, **analysis(2))
    assert np.all(a == (0xF0, 0xFF, 0x00))
    np.testing.assert_array_equal(a, b)


def test_an_unknown_mode_draws_solid():
    out = column_colors("tone", False, base_color=BASE, columns=N, **analysis())
    assert np.all(out == (0xF0, 0xFF, 0x00))


def test_a_mode_waiting_on_its_analysis_draws_solid():
    out = column_colors("bands", False, base_color=BASE, columns=N)
    assert np.all(out == (0xF0, 0xFF, 0x00))


class TestLoudness:
    def test_keeps_the_hue_and_follows_the_peak(self):
        peaks = np.linspace(0, 1, N, dtype=np.float32)
        out = column_colors("loudness", True, base_color="#804020", columns=N, peaks=peaks)
        assert tuple(out[-1]) == (0x80, 0x40, 0x20)
        assert out[0, 0] < out[-1, 0]
        # Same hue: the channel ratios hold as it dims.
        assert out[N // 2, 0] == pytest.approx(2 * out[N // 2, 1], abs=2)

    def test_per_track_brings_a_quiet_track_up_to_full(self):
        quiet = np.linspace(0, 0.2, N, dtype=np.float32)
        absolute = column_colors("loudness", True, base_color=BASE, columns=N, peaks=quiet)
        per_track = column_colors("loudness", False, base_color=BASE, columns=N, peaks=quiet)
        assert per_track[-1, 0] > absolute[-1, 0]


class TestNormalisation:
    def test_absolute_gives_one_share_one_colour_in_every_track(self):
        """Two tracks that share a column's band shares but differ elsewhere."""
        a, b = analysis(3), analysis(4)
        for key in ("low", "mid", "high"):
            b[key][0] = a[key][0]
        b["centroid"][0] = a["centroid"][0]
        for mode in ("bands", "centroid"):
            ca = column_colors(mode, True, base_color=BASE, columns=N, **a)
            cb = column_colors(mode, True, base_color=BASE, columns=N, **b)
            np.testing.assert_array_equal(ca[0], cb[0])

    def test_per_track_colours_the_same_share_by_its_own_track(self):
        a = analysis(5)
        b = {k: v.copy() for k, v in a.items()}
        # Track B is uniformly bassier everywhere but column 0.
        b["low"][1:] = np.minimum(b["low"][1:] * 1.8, 0.95)
        b["centroid"][1:] *= 0.5
        for mode in ("bands", "centroid"):
            ca = column_colors(mode, False, base_color=BASE, columns=N, **a)
            cb = column_colors(mode, False, base_color=BASE, columns=N, **b)
            assert not np.array_equal(ca[0], cb[0]), mode

    def test_centroid_collapses_under_absolute_and_spreads_per_track(self):
        """The reason the toggle exists: at overview scale a track's centroid
        barely moves, so the fixed 80 Hz..8 kHz span paints it one colour."""
        cen = np.linspace(1800, 2200, N, dtype=np.float32)
        absolute = column_colors("centroid", True, base_color=BASE, columns=N, centroid=cen)
        per_track = column_colors("centroid", False, base_color=BASE, columns=N, centroid=cen)
        spread = lambda c: int(np.ptp(c.astype(int), axis=0).max())  # noqa: E731
        assert spread(per_track) > 4 * spread(absolute)

    def test_a_spectrally_uniform_track_is_stretched_per_track(self):
        """The known cost of per-track: a drone's noise-level wobble in centroid
        is stretched across the whole ramp. Pinned so a change to the
        percentile bounds shows up here."""
        rng = np.random.default_rng(6)
        cen = (1000 + rng.standard_normal(N)).astype(np.float32)  # +-1 Hz of noise
        out = column_colors("centroid", False, base_color=BASE, columns=N, centroid=cen)
        blue_to_red = column_colors(
            "centroid", True, base_color=BASE, columns=2,
            centroid=np.array([80, 8000], np.float32),
        )
        assert tuple(out[np.argmin(cen)]) == tuple(blue_to_red[0])
        assert tuple(out[np.argmax(cen)]) == tuple(blue_to_red[1])


class TestSilence:
    @pytest.mark.parametrize("absolute", [False, True])
    @pytest.mark.parametrize("mode", ["bands", "centroid"])
    def test_silent_columns_are_the_base_colour(self, mode, absolute):
        a = analysis(7)
        a["centroid"][:20] = 0
        for key in ("low", "mid", "high"):
            a[key][:20] = 1 / 3
        out = column_colors(mode, absolute, base_color=BASE, columns=N, **a)
        assert np.all(out[:20] == (0xF0, 0xFF, 0x00))
        assert not np.all(out[20:] == (0xF0, 0xFF, 0x00))

    def test_all_silent_is_all_base_colour(self):
        z = np.zeros(N, np.float32)
        third = np.full(N, 1 / 3, np.float32)
        for mode in ("bands", "centroid"):
            out = column_colors(
                mode, False, base_color=BASE, columns=N,
                low=third, mid=third, high=third, centroid=z,
            )
            assert np.all(out == (0xF0, 0xFF, 0x00))


def test_bands_channel_mapping():
    """R = low, G = high, B = mid: bass reads red, hats cyan-green."""
    one, zero = np.ones(3, np.float32), np.zeros(3, np.float32)
    cen = np.full(3, 1000, np.float32)
    bass = column_colors("bands", True, base_color=BASE, columns=3,
                         low=one, mid=zero, high=zero, centroid=cen)
    hats = column_colors("bands", True, base_color=BASE, columns=3,
                         low=zero, mid=zero, high=one, centroid=cen)
    assert tuple(bass[0]) == (255, 0, 0)
    assert tuple(hats[0]) == (0, 255, 0)
