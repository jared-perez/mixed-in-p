"""Tests for key detection on synthetic audio."""

import numpy as np
import pytest

librosa = pytest.importorskip("librosa")
sf = pytest.importorskip("soundfile")

from src.analysis.key_detector import (
    _confidence,
    _correlate_profiles,
    _fit_strength,
    detect_key,
    detect_key_with_alternatives,
    get_key_alternatives,
)

SR = 22050

# Chord progressions as MIDI note lists. The minor progression uses the
# harmonic-minor dominant (E major, with G#) so its pitch content is not
# identical to C major's — that's what distinguishes Am from its relative.
C_MAJOR_PROGRESSION = [
    (60, 64, 67),  # C
    (65, 69, 72),  # F
    (67, 71, 74),  # G
    (60, 64, 67),  # C
]
A_MINOR_PROGRESSION = [
    (57, 60, 64),  # Am
    (62, 65, 69),  # Dm
    (64, 68, 71),  # E (harmonic-minor dominant)
    (57, 60, 64),  # Am
]


def _render_chords(
    chords,
    seconds_per_chord: float = 2.5,
    repeats: int = 2,
    detune_cents: float = 0.0,
) -> np.ndarray:
    """Render a chord progression as summed sines with a few harmonics."""
    n = int(SR * seconds_per_chord)
    t = np.arange(n) / SR
    fade = np.minimum(1.0, np.minimum(t, t[::-1]) / 0.02)  # declick edges
    segments = []
    for midi_notes in chords * repeats:
        seg = np.zeros(n)
        for note in midi_notes:
            freq = 440.0 * 2 ** ((note - 69 + detune_cents / 100.0) / 12.0)
            for harmonic, amp in ((1, 1.0), (2, 0.5), (3, 0.33)):
                seg += amp * np.sin(2 * np.pi * freq * harmonic * t)
        segments.append(seg * fade)
    y = np.concatenate(segments)
    return (0.3 * y / np.abs(y).max()).astype(np.float32)


def _add_percussion(y: np.ndarray, bpm: float = 128.0) -> np.ndarray:
    """Overlay loud broadband noise bursts (kick/hat stand-ins) on a signal."""
    rng = np.random.default_rng(42)
    y = y.copy()
    period = 60.0 / bpm
    burst_len = int(0.03 * SR)
    envelope = np.linspace(1.0, 0.0, burst_len)
    n_bursts = int(len(y) / SR / period)
    for i in range(n_bursts):
        start = int(i * period * SR)
        end = min(start + burst_len, len(y))
        burst = rng.standard_normal(end - start) * envelope[: end - start]
        y[start:end] += 0.5 * burst.astype(np.float32)
    return (0.9 * y / np.abs(y).max()).astype(np.float32)


def _write(path, y: np.ndarray) -> str:
    sf.write(path, y, SR)
    return str(path)


class TestDetectKey:
    def test_major_progression(self, tmp_path):
        path = _write(tmp_path / "cmaj.wav", _render_chords(C_MAJOR_PROGRESSION))
        key, confidence = detect_key(path)
        assert key == "C"
        assert confidence > 0.5

    def test_minor_progression(self, tmp_path):
        path = _write(tmp_path / "amin.wav", _render_chords(A_MINOR_PROGRESSION))
        key, confidence = detect_key(path)
        assert key == "Am"
        assert confidence > 0.5

    def test_survives_heavy_percussion(self, tmp_path):
        # HPSS should keep broadband drum bursts out of the chroma
        y = _add_percussion(_render_chords(C_MAJOR_PROGRESSION))
        path = _write(tmp_path / "cmaj_drums.wav", y)
        key, _ = detect_key(path)
        assert key == "C"

    def test_detuned_track_still_detected(self, tmp_path):
        # 40 cents flat of A=440 — tuning estimation must realign the bins
        y = _render_chords(C_MAJOR_PROGRESSION, detune_cents=-40.0)
        path = _write(tmp_path / "cmaj_detuned.wav", y)
        key, _ = detect_key(path)
        assert key == "C"

    def test_silence_returns_empty(self, tmp_path):
        path = _write(tmp_path / "silence.wav", np.zeros(SR * 5, dtype=np.float32))
        key, confidence = detect_key(path)
        assert key == ""
        assert confidence == 0.0

    def test_noise_has_low_confidence(self, tmp_path):
        rng = np.random.default_rng(7)
        y = (0.3 * rng.standard_normal(SR * 10)).astype(np.float32)
        path = _write(tmp_path / "noise.wav", y)
        _, confidence = detect_key(path)
        assert confidence < 0.3

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            detect_key("/nonexistent/audio.wav")


class TestGetKeyAlternatives:
    def test_top_alternative_matches_detect_key(self, tmp_path):
        path = _write(tmp_path / "cmaj.wav", _render_chords(C_MAJOR_PROGRESSION))
        alternatives = get_key_alternatives(path, top_n=3)
        assert len(alternatives) == 3
        assert alternatives[0] == detect_key(path)

    def test_sorted_descending(self, tmp_path):
        path = _write(tmp_path / "amin.wav", _render_chords(A_MINOR_PROGRESSION))
        confidences = [c for _, c in get_key_alternatives(path, top_n=3)]
        assert confidences == sorted(confidences, reverse=True)

    def test_silence_returns_empty_list(self, tmp_path):
        path = _write(tmp_path / "silence.wav", np.zeros(SR * 5, dtype=np.float32))
        assert get_key_alternatives(path) == []


class TestDetectKeyWithAlternatives:
    def test_primary_matches_detect_key_and_alternatives_exclude_it(self, tmp_path):
        path = _write(tmp_path / "cmaj.wav", _render_chords(C_MAJOR_PROGRESSION))
        key, confidence, alternatives = detect_key_with_alternatives(path, top_n=3)
        assert (key, confidence) == detect_key(path)
        assert len(alternatives) == 2
        assert key not in [k for k, _ in alternatives]
        assert all(c <= confidence for _, c in alternatives)

    def test_silence_returns_empty(self, tmp_path):
        path = _write(tmp_path / "silence.wav", np.zeros(SR * 5, dtype=np.float32))
        assert detect_key_with_alternatives(path) == ("", 0.0, [])


class TestConfidence:
    def test_near_tie_scores_below_decisive_margin(self):
        # Same strong fit: a 0.01 gap over the runner-up must score well
        # below a decisive 0.2 gap
        near_tie = _confidence(0.85, margin=0.01, agreement=1.0)
        decisive = _confidence(0.85, margin=0.2, agreement=1.0)
        assert near_tie < decisive
        assert near_tie < 0.7

    def test_segment_disagreement_lowers_confidence(self):
        agreed = _confidence(0.85, margin=0.2, agreement=1.0)
        contested = _confidence(0.85, margin=0.2, agreement=0.4)
        assert contested < agreed

    def test_weak_fit_scores_zero(self):
        assert _confidence(0.1, margin=0.2, agreement=1.0) == 0.0

    def test_bounds(self):
        assert 0.0 <= _confidence(0.99, margin=0.5, agreement=1.0) <= 1.0
        assert _fit_strength(1.0) == 1.0
        assert _fit_strength(0.0) == 0.0


class TestCorrelateProfiles:
    def test_flat_chroma_returns_none(self):
        assert _correlate_profiles(np.ones(12)) is None

    def test_profile_itself_correlates_perfectly(self):
        from src.analysis.key_detector import MAJOR_PROFILE, _KEY_NAMES

        corrs = _correlate_profiles(MAJOR_PROFILE.astype(np.float64))
        assert _KEY_NAMES[int(np.argmax(corrs))] == "C"
        assert float(np.max(corrs)) == pytest.approx(1.0)
