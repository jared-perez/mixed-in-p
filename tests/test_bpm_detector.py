"""Tests for BPM detection on synthetic audio."""

import numpy as np
import pytest

librosa = pytest.importorskip("librosa")
sf = pytest.importorskip("soundfile")

from src.analysis.bpm_detector import (
    _adjust_tempo_to_range,
    _metrical_candidates,
    _range_prior,
    _refine_bpm,
    detect_bpm,
)

SR = 22050


def _write_click_track(path, bpm: float, duration: float = 40.0) -> None:
    """Write a WAV of short 1 kHz clicks at the given tempo."""
    y = np.zeros(int(SR * duration), dtype=np.float32)
    period = 60.0 / bpm
    click = (0.8 * np.sin(2 * np.pi * 1000 * np.arange(220) / SR)).astype(
        np.float32
    )
    n_clicks = int((duration - 0.1) / period)
    for i in range(n_clicks):
        start = int(i * period * SR)
        y[start : start + len(click)] += click
    sf.write(path, y, SR)


class TestDetectBpm:
    @pytest.mark.parametrize("bpm", [95.0, 128.0, 146.0])
    def test_click_track_detected_precisely(self, tmp_path, bpm):
        path = str(tmp_path / "click.wav")
        _write_click_track(path, bpm)
        detected, confidence = detect_bpm(path)
        assert detected == pytest.approx(bpm, abs=0.1)
        assert confidence > 0.8

    def test_range_resolves_half_double_ambiguity(self, tmp_path):
        # A bare 174 BPM metronome is indistinguishable from 87; the
        # configured range must decide which level is reported.
        path = str(tmp_path / "click174.wav")
        _write_click_track(path, 174.0)
        detected, _ = detect_bpm(path, min_bpm=100.0, max_bpm=200.0)
        assert detected == pytest.approx(174.0, abs=0.1)

    def test_silence_returns_zero(self, tmp_path):
        path = str(tmp_path / "silence.wav")
        sf.write(path, np.zeros(SR * 5, dtype=np.float32), SR)
        detected, confidence = detect_bpm(path)
        assert detected == 0.0
        assert confidence == 0.0

    def test_out_of_range_tempo_folds_into_range(self, tmp_path):
        # 70 BPM clicks with default range 85-175: expect the double, 140.
        # No in-range level has autocorrelation support for a bare 70 BPM
        # pulse, so this exercises the low-evidence fallback path, which
        # reports reduced confidence.
        path = str(tmp_path / "slow.wav")
        _write_click_track(path, 70.0)
        detected, confidence = detect_bpm(path)
        assert detected == pytest.approx(140.0, abs=0.5)
        assert confidence < 0.8

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            detect_bpm("/nonexistent/audio.wav")


class TestMetricalCandidates:
    def test_includes_related_levels_in_range(self):
        candidates = _metrical_candidates(97.0, 85.0, 175.0)
        # 97 itself, 4/3 (129.3) and 3/2 (145.5) are all in range
        assert any(abs(c - 97.0) < 1 for c in candidates)
        assert any(abs(c - 129.3) < 1 for c in candidates)
        assert any(abs(c - 145.5) < 1 for c in candidates)

    def test_out_of_range_levels_excluded(self):
        candidates = _metrical_candidates(128.0, 85.0, 175.0)
        assert all(85.0 / 1.02 <= c <= 175.0 * 1.02 for c in candidates)

    def test_never_empty(self):
        assert _metrical_candidates(500.0, 85.0, 175.0)


class TestRefineBpm:
    def test_recovers_tempo_from_quantized_beats(self):
        # Beat times quantized to a hop grid, as librosa produces them
        true_period = 60.0 / 146.0
        hop_seconds = 512 / 44100
        times = np.round(np.arange(200) * true_period / hop_seconds) * hop_seconds
        refined, confidence = _refine_bpm(times, 144.0)
        assert refined == pytest.approx(146.0, abs=0.05)
        assert confidence > 0.8

    def test_tolerates_skipped_beats(self):
        true_period = 60.0 / 128.0
        times = np.arange(100) * true_period
        times = np.delete(times, [30, 31, 60])  # tracker missed some beats
        refined, _ = _refine_bpm(times, 128.0)
        assert refined == pytest.approx(128.0, abs=0.05)

    def test_too_few_beats_low_confidence(self):
        refined, confidence = _refine_bpm(np.array([0.0, 0.5, 1.0]), 120.0)
        assert refined == 120.0
        assert confidence <= 0.1


class TestRangePrior:
    def test_peaks_near_range_center(self):
        center = np.sqrt(85.0 * 175.0)
        assert _range_prior(center, 85.0, 175.0) == pytest.approx(1.0)
        assert _range_prior(90.0, 85.0, 175.0) < _range_prior(128.0, 85.0, 175.0)

    def test_zero_for_invalid(self):
        assert _range_prior(0.0, 85.0, 175.0) == 0.0


class TestAdjustTempoToRange:
    def test_halves_high_tempo(self):
        assert _adjust_tempo_to_range(256.0, 85.0, 175.0) == 128.0

    def test_doubles_low_tempo(self):
        assert _adjust_tempo_to_range(64.0, 85.0, 175.0) == 128.0

    def test_in_range_unchanged(self):
        assert _adjust_tempo_to_range(128.0, 85.0, 175.0) == 128.0

    def test_zero_returns_zero(self):
        assert _adjust_tempo_to_range(0.0, 85.0, 175.0) == 0.0
