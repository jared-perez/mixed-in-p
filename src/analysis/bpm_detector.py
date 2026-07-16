"""BPM detection using librosa beat tracking.

Detects tempo from audio files, handling the common half/double (and 2:3, 3:4)
metrical ambiguity in electronic music by scoring candidate tempos against the
onset envelope, then refining the winner from the actual beat positions.

Pipeline:
1. Load the file and select the loudest (highest-RMS) analysis window so
   intros/outros/breakdowns don't pollute the onset envelope.
2. Beat-track on the percussive component (HPSS) for a cleaner pulse.
3. Get a rough tempo estimate, expand it into related metrical candidates
   (x1/2, x2/3, x3/4, x1, x4/3, x3/2, x2 ...), and keep those in the DJ range.
4. Beat-track each candidate and refine its tempo by regressing beat times
   against beat indices, which recovers sub-0.1 BPM precision lost to
   tempogram quantization.
5. Pick the winner by combining three signals: how tightly the beats fit a
   constant-tempo grid, the onset autocorrelation at the refined period, and
   a soft prior over the expected BPM range. (No single signal suffices:
   offbeat-heavy tracks produce plausible grids at 2/3 or 3/4 of the true
   tempo that fool any one of them.)
"""

import librosa
import numpy as np

# Analysis hop for onset envelope / beat tracking (samples).
_HOP = 512

# Length of the loudest-section analysis window (seconds).
_WINDOW_SECONDS = 90.0

# Metrical ratios relating a rough tempo estimate to plausible true tempos.
# Includes 2:3 / 3:4 relations, which trip up plain beat tracking on techno.
_CANDIDATE_RATIOS = (1 / 3, 1 / 2, 2 / 3, 3 / 4, 1.0, 4 / 3, 3 / 2, 2.0, 3.0)

# Candidates may exceed the DJ range by this factor before being discarded,
# so a 176 BPM track isn't forcibly halved by a 175 BPM ceiling.
_RANGE_TOLERANCE = 1.02

# Minimum combined score (fit x autocorrelation x prior) for a candidate to
# count as evidence-backed. Real detections score >0.05; when nothing in range
# clears this floor (e.g. the true tempo's every in-range multiple lands
# between repetitions), fold the rough estimate into range instead of
# confidently reporting the least-bad garbage candidate.
_MIN_EVIDENCE = 0.01

# Below this confidence, retry on the percussive (HPSS) component. Separation
# rescues tracks whose beat is buried under harmonic content, but it's ~10x
# slower than the plain pass and slightly hurts already-clean tracks, so it
# only runs as a second opinion.
_HPSS_RETRY_CONFIDENCE = 0.6


def detect_bpm(
    file_path: str,
    min_bpm: float = 85.0,
    max_bpm: float = 175.0,
) -> tuple[float, float]:
    """Detect the BPM of an audio file.

    Args:
        file_path: Path to the audio file (WAV, MP3, FLAC, AIFF, etc.)
        min_bpm: Minimum expected BPM (default 85)
        max_bpm: Maximum expected BPM (default 175)

    Returns:
        Tuple of (bpm, confidence) where:
        - bpm: Detected tempo as a float (e.g., 128.0)
        - confidence: Confidence score from 0.0 to 1.0

    Raises:
        FileNotFoundError: If the audio file doesn't exist
        librosa.util.exceptions.ParameterError: If the file can't be decoded
    """
    y, sr = librosa.load(file_path, sr=None, mono=True)
    y = _strongest_window(y, sr)

    if y.size == 0 or not np.any(y):
        return 0.0, 0.0

    bpm, confidence = _detect_from_signal(y, sr, min_bpm, max_bpm)

    if confidence < _HPSS_RETRY_CONFIDENCE:
        y_perc = librosa.effects.percussive(y)
        bpm_p, conf_p = _detect_from_signal(y_perc, sr, min_bpm, max_bpm)
        if conf_p > confidence:
            bpm, confidence = bpm_p, conf_p

    return round(bpm, 2), round(confidence, 3)


def _detect_from_signal(
    y: np.ndarray, sr: int, min_bpm: float, max_bpm: float
) -> tuple[float, float]:
    """Run the candidate-scoring tempo pipeline on a prepared signal."""
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=_HOP)

    if not np.any(onset_env):
        return 0.0, 0.0

    rough = librosa.feature.tempo(
        onset_envelope=onset_env, sr=sr, hop_length=_HOP
    )
    rough = float(rough[0]) if np.size(rough) else 0.0
    if rough <= 0:
        return 0.0, 0.0

    candidates = _metrical_candidates(rough, min_bpm, max_bpm)
    autocorr = librosa.autocorrelate(onset_env)
    frames_per_second = sr / _HOP

    best_bpm = 0.0
    best_conf = 0.0
    best_score = 0.0
    for candidate in candidates:
        _, beat_frames = librosa.beat.beat_track(
            onset_envelope=onset_env, sr=sr, hop_length=_HOP, bpm=candidate
        )
        beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=_HOP)
        refined, conf = _refine_bpm(beat_times, candidate)
        score = (
            conf
            * _autocorr_strength(autocorr, refined, frames_per_second)
            * _range_prior(refined, min_bpm, max_bpm)
        )
        if score > best_score:
            best_bpm, best_conf, best_score = refined, conf, score

    if best_bpm <= 0 or best_score < _MIN_EVIDENCE:
        fallback = _adjust_tempo_to_range(rough, min_bpm, max_bpm)
        if fallback <= 0:
            return 0.0, 0.0
        _, beat_frames = librosa.beat.beat_track(
            onset_envelope=onset_env, sr=sr, hop_length=_HOP, bpm=fallback
        )
        beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=_HOP)
        refined, conf = _refine_bpm(beat_times, fallback)
        # Halve confidence: the tempo grid may fit tightly, but no in-range
        # metrical level had autocorrelation support.
        return refined, conf * 0.5

    return best_bpm, best_conf


def _strongest_window(
    y: np.ndarray, sr: int, duration: float = _WINDOW_SECONDS
) -> np.ndarray:
    """Return the contiguous window of `duration` seconds with the highest RMS.

    Analyzing only the loudest section keeps weak-beat intros, ambient
    breakdowns and fade-outs from diluting the onset envelope.
    """
    window_samples = int(duration * sr)
    if y.size <= window_samples:
        return y

    hop = 4096
    rms = librosa.feature.rms(y=y, frame_length=8192, hop_length=hop)[0]
    window_frames = max(1, window_samples // hop)
    if rms.size <= window_frames:
        return y

    # Sliding-window RMS energy via cumulative sum
    energy = np.cumsum(rms**2)
    window_energy = energy[window_frames:] - energy[:-window_frames]
    start_frame = int(np.argmax(window_energy))
    start = start_frame * hop
    return y[start : start + window_samples]


def _metrical_candidates(
    rough: float, min_bpm: float, max_bpm: float
) -> list[float]:
    """Expand a rough tempo into related metrical levels within the DJ range."""
    candidates: list[float] = []
    lo = min_bpm / _RANGE_TOLERANCE
    hi = max_bpm * _RANGE_TOLERANCE
    for ratio in _CANDIDATE_RATIOS:
        bpm = rough * ratio
        if lo <= bpm <= hi and not any(
            abs(bpm - c) < 1.0 for c in candidates
        ):
            candidates.append(bpm)
    if not candidates:
        candidates.append(_adjust_tempo_to_range(rough, min_bpm, max_bpm))
    return candidates


def _autocorr_strength(
    autocorr: np.ndarray, bpm: float, frames_per_second: float
) -> float:
    """Onset-envelope autocorrelation at this tempo's beat period.

    The true beat period is a repetition period of the music, so the
    autocorrelation peaks there; a 3/4- or 2/3-tempo grid's period usually
    isn't, so its value is low even when beat tracking finds a tight grid.
    """
    if bpm <= 0 or autocorr[0] <= 0:
        return 0.0
    lag = int(round(60.0 / bpm * frames_per_second))
    if lag <= 0 or lag >= len(autocorr):
        return 0.0
    return float(max(0.0, autocorr[lag] / autocorr[0]))


def _range_prior(bpm: float, min_bpm: float, max_bpm: float) -> float:
    """Soft log-normal prior centered on the expected BPM range.

    Breaks ties between metrically related grids that both fit well (e.g.
    2/3-tempo shadows of offbeat-heavy techno) in favor of tempos near the
    middle of the configured range, without hard-clamping outliers.
    """
    if bpm <= 0:
        return 0.0
    center = float(np.sqrt(min_bpm * max_bpm))
    octaves_out = np.log2(bpm / center)
    return float(np.exp(-0.5 * (octaves_out / 0.35) ** 2))


def _refine_bpm(beat_times: np.ndarray, bpm_estimate: float) -> tuple[float, float]:
    """Refine a tempo estimate from tracked beat times.

    The tempogram quantizes tempo coarsely (~1-3 BPM near 130). Regressing
    beat times against integer beat indices recovers the true period with
    sub-0.1 BPM precision on a steady track. Indices are derived by rounding
    (elapsed time / period), which tolerates occasional skipped beats.

    Returns (refined_bpm, confidence). Confidence reflects how tightly the
    beats fit a constant-tempo grid.
    """
    if len(beat_times) < 8:
        return bpm_estimate, 0.1

    intervals = np.diff(beat_times)
    period = float(np.median(intervals))
    if period <= 0:
        return bpm_estimate, 0.0

    # Assign an integer beat index to each beat. Increments come from each
    # local interval (1 normally, 2 across a skipped beat), so quantization
    # error can't accumulate the way rounding total-elapsed-time/period would.
    steps = np.maximum(1, np.round(intervals / period))
    indices = np.concatenate(([0.0], np.cumsum(steps)))

    slope, intercept = np.polyfit(indices, beat_times, 1)
    if slope <= 0:
        return bpm_estimate, 0.0
    period = float(slope)

    residuals = beat_times - (slope * indices + intercept)
    inliers = np.abs(residuals) < 0.1 * period
    inlier_frac = float(np.mean(inliers))
    if np.count_nonzero(inliers) >= 8:
        slope, intercept = np.polyfit(
            indices[inliers], beat_times[inliers], 1
        )
        period = float(slope)
        residuals = beat_times[inliers] - (slope * indices[inliers] + intercept)

    bpm = 60.0 / period

    # Confidence: tight residuals and few outliers => high confidence
    resid_ratio = float(np.std(residuals)) / period
    confidence = inlier_frac * float(np.exp(-8 * resid_ratio))
    return bpm, float(np.clip(confidence, 0.0, 1.0))


def _adjust_tempo_to_range(tempo: float, min_bpm: float, max_bpm: float) -> float:
    """Halve/double a tempo into the expected range (last-resort fallback)."""
    if tempo <= 0:
        return 0.0

    adjusted = tempo
    while adjusted > max_bpm and adjusted > min_bpm:
        adjusted /= 2
    while adjusted < min_bpm and adjusted * 2 <= max_bpm:
        adjusted *= 2

    return adjusted
