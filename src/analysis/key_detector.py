"""Musical key detection using librosa chroma features.

Pipeline tuned for DJ/electronic material:

1. Harmonic-percussive separation — kicks, hats, and snares smear broadband
   energy across all 12 chroma bins, so only the harmonic component is used.
2. Tuning correction — tracks pitched on vinyl or mastered off A=440 land
   between chroma bins; the CQT is aligned to the estimated tuning.
3. Two-band chroma — a harmony chroma from C2 up (the 32-65 Hz sub-bass
   octave has poor CQT pitch resolution and its kick/sub energy dominates
   the fold, corrupting the profile match) plus a down-weighted bass chroma
   (C1-C3). The bassline carries the root in most dance music and often the
   third that separates parallel major/minor, so it anchors the estimate
   without being allowed to swamp the harmony.
4. edma key profiles — pitch-class weightings trained on electronic dance
   music corpora (Faraldo et al., the "edma"/"edmm" profiles shipped with
   Essentia's key extractor). They replace the classical Krumhansl-Kessler
   profiles, which systematically confuse relative major/minor on
   harmonically sparse tracks.
5. Segment voting — the track is scored in ~20 s segments weighted by
   harmonic energy, so drum intros, breakdowns, and FX sweeps don't vote
   with the same weight as harmonically clear sections.
6. Margin-based confidence — confidence reflects how decisively the best key
   beats the runner-up (the classic failure is a near-tie between relative
   major/minor) and how consistently segments agree, not just the absolute
   profile correlation.
"""

import librosa
import numpy as np

# edma/edmm key profiles: relative pitch-class weights for major and minor
# keys, trained on electronic dance music (Faraldo et al. / Essentia).
# Index 0 = tonic, then ascending semitones.
MAJOR_PROFILE = np.array(
    [0.16519551, 0.04749026, 0.08293076, 0.06687112, 0.09994645, 0.09274123,
     0.05294487, 0.13159476, 0.05218986, 0.07443653, 0.06940723, 0.0642515]
)
MINOR_PROFILE = np.array(
    [0.17235348, 0.05336489, 0.0761009, 0.10043649, 0.05621498, 0.08527853,
     0.0497915, 0.13451001, 0.07458916, 0.05003023, 0.09187879, 0.05545106]
)

# Pitch class names (using sharps as canonical)
PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Chroma resolves fine below 11 kHz; analysing at 22050 Hz roughly halves the
# cost of HPSS and the CQT versus native-rate loading with no accuracy loss.
TARGET_SR = 22050
HOP_LENGTH = 512
SEGMENT_SECONDS = 20.0

# Two-band chroma ranges and blend (see module docstring, point 3)
HARMONY_FMIN_NOTE = "C2"
HARMONY_OCTAVES = 6
BASS_FMIN_NOTE = "C1"
BASS_OCTAVES = 2
BASS_WEIGHT = 0.2

# Correlation calibration: profile correlations below NOISE_CORR are noise,
# above STRONG_CORR are an excellent fit. Real-world material lands in the
# 0.3-0.5 range even when the detected key is right (validated on tagged DJ
# tracks); synthetic/clean signals reach 0.8+. A best-vs-runner-up margin of
# DECISIVE_MARGIN or more means the key choice is unambiguous.
NOISE_CORR = 0.15
STRONG_CORR = 0.65
DECISIVE_MARGIN = 0.08


def _build_profiles() -> tuple[np.ndarray, list[str]]:
    """Build the 24x12 matrix of rotated key profiles and their key names."""
    rows: list[np.ndarray] = []
    names: list[str] = []
    for i, pitch in enumerate(PITCH_CLASSES):
        rows.append(np.roll(MAJOR_PROFILE, i))
        names.append(pitch)
        rows.append(np.roll(MINOR_PROFILE, i))
        names.append(f"{pitch}m")
    return np.asarray(rows, dtype=np.float64), names


_PROFILES, _KEY_NAMES = _build_profiles()
_PROFILES_CENTERED = _PROFILES - _PROFILES.mean(axis=1, keepdims=True)
_PROFILE_NORMS = np.linalg.norm(_PROFILES_CENTERED, axis=1)


def detect_key(file_path: str) -> tuple[str, float]:
    """Detect the musical key of an audio file.

    Args:
        file_path: Path to the audio file

    Returns:
        Tuple of (key, confidence) where:
        - key: Detected key as string (e.g., 'Am', 'F#'), or '' for
          silent/atonal audio
        - confidence: Confidence score from 0.0 to 1.0

    Raises:
        FileNotFoundError: If the audio file doesn't exist
        librosa.util.exceptions.ParameterError: If the file can't be decoded
    """
    ranked, agreement = _rank_keys(file_path)
    if not ranked:
        return "", 0.0
    return _score_ranked(ranked, agreement, 1)[0]


def detect_key_with_alternatives(
    file_path: str, top_n: int = 3
) -> tuple[str, float, list[tuple[str, float]]]:
    """Detect the key and runner-up candidates in a single analysis pass.

    Args:
        file_path: Path to the audio file
        top_n: Total number of keys to score, including the primary

    Returns:
        Tuple of (key, confidence, alternatives) where key/confidence match
        detect_key() and alternatives holds the 2nd..top_n ranked keys as
        (key, confidence) tuples (empty for silent/atonal audio).
    """
    ranked, agreement = _rank_keys(file_path)
    if not ranked:
        return "", 0.0, []
    scored = _score_ranked(ranked, agreement, top_n)
    key, confidence = scored[0]
    return key, confidence, scored[1:]


def get_key_alternatives(file_path: str, top_n: int = 3) -> list[tuple[str, float]]:
    """Get the top N most likely keys for an audio file.

    Useful when the primary key detection is uncertain and the user
    might want to choose from alternatives.

    Args:
        file_path: Path to the audio file
        top_n: Number of alternatives to return (default 3)

    Returns:
        List of (key, confidence) tuples, sorted by confidence descending.
        The first entry matches detect_key(); the rest are scaled by how
        closely their profile fit approaches the winner's.
    """
    ranked, agreement = _rank_keys(file_path)
    if not ranked:
        return []
    return _score_ranked(ranked, agreement, top_n)


def _score_ranked(
    ranked: list[tuple[str, float]], agreement: float, top_n: int
) -> list[tuple[str, float]]:
    """Map the top N ranked (key, correlation) pairs to (key, confidence).

    The best key gets the full margin/agreement-aware confidence; the rest
    are scaled by how closely their profile fit approaches the winner's.
    """
    best_corr = ranked[0][1]
    margin = best_corr - ranked[1][1] if len(ranked) > 1 else DECISIVE_MARGIN
    top_confidence = _confidence(best_corr, margin, agreement)
    top_strength = _fit_strength(best_corr)

    scored: list[tuple[str, float]] = []
    for key, corr in ranked[:top_n]:
        if top_strength <= 0.0:
            confidence = 0.0
        else:
            confidence = top_confidence * _fit_strength(corr) / top_strength
        scored.append((key, round(confidence, 3)))
    return scored


def _rank_keys(file_path: str) -> tuple[list[tuple[str, float]], float]:
    """Score all 24 keys against segment-wise harmonic chroma.

    Args:
        file_path: Path to the audio file

    Returns:
        Tuple of (ranked, agreement) where ranked is a list of
        (key_name, aggregated_correlation) sorted best-first (empty for
        silent/atonal audio), and agreement is the harmonic-energy-weighted
        fraction of segments whose individual best key matches the winner.
    """
    y, sr = librosa.load(file_path, sr=TARGET_SR, mono=True)
    if not np.any(y):
        return [], 0.0

    # margin=4 suppresses percussive bleed more aggressively than the
    # default; residual harmonic level doesn't matter since chroma is
    # correlated per segment, not compared across segments.
    y_harm = librosa.effects.harmonic(y, margin=4.0)

    tuning = librosa.estimate_tuning(y=y_harm, sr=sr)
    if not np.isfinite(tuning):
        tuning = 0.0

    harmony = librosa.feature.chroma_cqt(
        y=y_harm, sr=sr, hop_length=HOP_LENGTH, tuning=tuning,
        fmin=librosa.note_to_hz(HARMONY_FMIN_NOTE), n_octaves=HARMONY_OCTAVES,
    )
    bass = librosa.feature.chroma_cqt(
        y=y_harm, sr=sr, hop_length=HOP_LENGTH, tuning=tuning,
        fmin=librosa.note_to_hz(BASS_FMIN_NOTE), n_octaves=BASS_OCTAVES,
    )
    n_chroma_frames = min(harmony.shape[1], bass.shape[1])
    chroma = (
        harmony[:, :n_chroma_frames]
        + BASS_WEIGHT * bass[:, :n_chroma_frames]
    )
    rms = librosa.feature.rms(y=y_harm, hop_length=HOP_LENGTH)[0]

    # CQT and STFT framing can differ by a frame or two at the edges
    n_frames = min(chroma.shape[1], rms.size)
    if n_frames == 0:
        return [], 0.0
    chroma = chroma[:, :n_frames]
    rms = rms[:n_frames]

    frames_per_segment = max(1, int(SEGMENT_SECONDS * sr / HOP_LENGTH))
    n_segments = max(1, round(n_frames / frames_per_segment))
    segment_indices = np.array_split(np.arange(n_frames), n_segments)

    segment_corrs: list[np.ndarray] = []
    segment_weights: list[float] = []
    segment_best: list[int] = []

    for indices in segment_indices:
        weight = float(rms[indices].mean())
        corrs = _correlate_profiles(chroma[:, indices].mean(axis=1))
        if corrs is None or weight <= 0.0:
            continue
        segment_corrs.append(corrs)
        segment_weights.append(weight)
        segment_best.append(int(np.argmax(corrs)))

    if not segment_corrs:
        return [], 0.0

    weights = np.asarray(segment_weights)
    weights = weights / weights.sum()
    aggregated = np.average(np.vstack(segment_corrs), axis=0, weights=weights)

    best_idx = int(np.argmax(aggregated))
    agreement = float(weights[np.asarray(segment_best) == best_idx].sum())

    order = np.argsort(aggregated)[::-1]
    ranked = [(_KEY_NAMES[i], float(aggregated[i])) for i in order]
    return ranked, agreement


def _correlate_profiles(chroma_vec: np.ndarray) -> np.ndarray | None:
    """Pearson-correlate one 12-bin chroma vector against all 24 key profiles.

    Args:
        chroma_vec: 12-element mean chroma for a segment

    Returns:
        24-element correlation array ordered like _KEY_NAMES, or None if the
        vector is (near-)constant and correlation is undefined.
    """
    centered = chroma_vec - chroma_vec.mean()
    norm = float(np.linalg.norm(centered))
    if norm < 1e-9:
        return None
    return (_PROFILES_CENTERED @ centered) / (norm * _PROFILE_NORMS)


def _fit_strength(correlation: float) -> float:
    """Map an absolute profile correlation to a 0-1 fit strength."""
    strength = (correlation - NOISE_CORR) / (STRONG_CORR - NOISE_CORR)
    return float(np.clip(strength, 0.0, 1.0))


def _confidence(best_corr: float, margin: float, agreement: float) -> float:
    """Combine fit strength, runner-up margin, and segment agreement.

    Full confidence requires all three: a strong absolute fit, a decisive
    margin over the second-best key (a 0.85-vs-0.84 near-tie between relative
    major and minor is a coin flip, not a confident call), and segments that
    agree with each other. The blend weights are heuristic: separation is
    weighted highest because near-ties are the dominant real-world error.

    Args:
        best_corr: Aggregated correlation of the winning key
        margin: Correlation gap between the best and second-best key
        agreement: Weighted fraction of segments that voted for the winner

    Returns:
        Confidence score from 0.0 to 1.0
    """
    separation = float(np.clip(margin / DECISIVE_MARGIN, 0.0, 1.0))
    blend = 0.35 + 0.45 * separation + 0.20 * agreement
    return float(np.clip(_fit_strength(best_corr) * blend, 0.0, 1.0))
