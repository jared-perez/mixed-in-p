"""Mono mix-down and the per-column spectral analysis behind waveform colour.

Pure numpy, no QApplication. ``spectral_columns`` returns band SHARES and the
centroid in Hz, so nothing here depends on the colour mode or normalisation.
"""

import numpy as np
import pytest

from src.gui.workers.waveform_worker import (
    downsample_waveform,
    mono_mix,
    spectral_columns,
)

SR = 44100


def tone(freq, seconds=2.0, amp=0.5):
    t = np.arange(int(SR * seconds), dtype=np.float32) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


class TestMonoMix:
    @pytest.mark.parametrize("channels", [1, 2, 3])
    def test_equals_the_mean_over_channels(self, channels):
        pcm = np.random.default_rng(0).standard_normal((5000, channels)).astype(np.float32)
        out = mono_mix(pcm)
        assert out.dtype == np.float32
        np.testing.assert_allclose(out, pcm.mean(axis=1).astype(np.float32), rtol=1e-6, atol=1e-7)

    def test_works_on_a_non_contiguous_slice(self):
        """The player engine mixes ``pcm[start:end]`` per call."""
        pcm = np.random.default_rng(1).standard_normal((8000, 2)).astype(np.float32)
        view = pcm[1000:3000:2]
        assert not view.flags.c_contiguous
        np.testing.assert_allclose(mono_mix(view), view.mean(axis=1), rtol=1e-6, atol=1e-7)

    def test_a_1d_array_is_already_mono(self):
        x = np.arange(10, dtype=np.float32)
        np.testing.assert_array_equal(mono_mix(x), x)


class TestSpectralColumns:
    def test_returns_four_float32_arrays_of_the_column_count(self):
        out = spectral_columns(tone(440), SR, columns=300)
        assert len(out) == 4
        for arr in out:
            assert arr.dtype == np.float32
            assert arr.shape == (300,)

    def test_columns_match_the_waveform_it_colours(self):
        mono = tone(440, seconds=3)
        cmin, *_ = downsample_waveform(mono.reshape(-1, 1), SR)
        assert len(spectral_columns(mono, SR, len(cmin))[0]) == len(cmin)

    def test_shares_sum_to_one(self):
        low, mid, high, _ = spectral_columns(tone(60) + tone(1000) + tone(9000), SR, 100)
        np.testing.assert_allclose(low + mid + high, 1.0, rtol=1e-5)

    @pytest.mark.parametrize(
        "freq, band", [(60, 0), (1000, 1), (10_000, 2)], ids=["bass", "mid", "high"]
    )
    def test_a_pure_tone_lands_in_its_band(self, freq, band):
        shares = spectral_columns(tone(freq), SR, 100)[:3]
        assert np.all(shares[band] > 0.9)

    @pytest.mark.parametrize("freq", [200, 1000, 5000])
    def test_a_pure_tones_centroid_is_its_frequency(self, freq):
        """Within a few bins (a bin is ~21.5 Hz at n_fft 2048; window leakage
        spreads a little magnitude either side)."""
        centroid = spectral_columns(tone(freq), SR, 50)[3]
        assert np.median(centroid) == pytest.approx(freq, abs=4 * SR / 2048)

    def test_silence_is_flagged_without_nan(self):
        low, mid, high, centroid = spectral_columns(np.zeros(SR, np.float32), SR, 50)
        for arr in (low, mid, high, centroid):
            assert np.all(np.isfinite(arr))
        assert np.all(centroid == 0)
        np.testing.assert_allclose(low, 1 / 3)

    def test_only_the_silent_columns_are_flagged(self):
        mono = np.concatenate([np.zeros(SR, np.float32), tone(1000, seconds=1)])
        centroid = spectral_columns(mono, SR, 20)[3]
        assert np.all(centroid[:9] == 0)
        assert np.all(centroid[11:] > 0)

    def test_a_clip_shorter_than_one_frame(self):
        out = spectral_columns(tone(1000, seconds=0.01), SR, 100)
        assert all(np.all(np.isfinite(a)) for a in out)
        assert out[3][0] > 0

    def test_more_columns_than_frames_borrow_their_frame(self):
        """A short track at 2000 columns: every column still gets a value."""
        centroid = spectral_columns(tone(1000, seconds=0.5), SR, 2000)[3]
        assert np.all(centroid > 0)

    def test_empty_audio_raises(self):
        with pytest.raises(ValueError):
            spectral_columns(np.zeros(0, np.float32), SR)
