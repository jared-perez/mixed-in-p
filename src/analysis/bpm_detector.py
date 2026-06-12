"""BPM detection using librosa beat tracking.

Detects tempo from audio files, handling the common half/double tempo
ambiguity in electronic music by constraining results to DJ-typical ranges.
"""

import librosa
import numpy as np


def detect_bpm(
    file_path: str,
    min_bpm: float = 85.0,
    max_bpm: float = 175.0,
) -> tuple[float, float]:
    """Detect the BPM of an audio file.

    Uses librosa's beat tracking algorithm and constrains the result
    to a typical DJ range to avoid half/double tempo confusion.

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
    # Load audio file (mono, default sample rate)
    y, sr = librosa.load(file_path, sr=None, mono=True)

    # Get tempo and beat frames
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)

    # librosa may return an array; extract scalar
    if isinstance(tempo, np.ndarray):
        tempo = float(tempo[0]) if tempo.size > 0 else 0.0
    else:
        tempo = float(tempo)

    # Handle half/double tempo ambiguity
    tempo = _adjust_tempo_to_range(tempo, min_bpm, max_bpm)

    # Calculate confidence based on beat regularity
    confidence = _calculate_beat_confidence(y, sr, beat_frames)

    return round(tempo, 2), round(confidence, 3)


def _adjust_tempo_to_range(tempo: float, min_bpm: float, max_bpm: float) -> float:
    """Adjust tempo to fall within the expected range.

    Electronic music often has ambiguous tempo (64 vs 128 vs 256 BPM).
    This adjusts by halving or doubling to fit the DJ-typical range.

    Args:
        tempo: Detected tempo
        min_bpm: Minimum expected BPM
        max_bpm: Maximum expected BPM

    Returns:
        Adjusted tempo within the range, or closest to range if impossible
    """
    if tempo <= 0:
        return 0.0

    # Try to get into range by halving if too high
    adjusted = tempo
    while adjusted > max_bpm and adjusted > min_bpm:
        adjusted /= 2

    # Try to get into range by doubling if too low
    while adjusted < min_bpm and adjusted * 2 <= max_bpm:
        adjusted *= 2

    return adjusted


def _calculate_beat_confidence(
    y: np.ndarray, sr: int, beat_frames: np.ndarray
) -> float:
    """Calculate confidence score for the beat detection.

    Higher confidence indicates more regular, consistent beats.

    Args:
        y: Audio time series
        sr: Sample rate
        beat_frames: Detected beat frame positions

    Returns:
        Confidence score from 0.0 to 1.0
    """
    if len(beat_frames) < 4:
        return 0.0

    # Calculate inter-beat intervals
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    intervals = np.diff(beat_times)

    if len(intervals) < 2:
        return 0.0

    # Confidence based on interval consistency (lower variance = higher confidence)
    mean_interval = np.mean(intervals)
    if mean_interval <= 0:
        return 0.0

    # Coefficient of variation (std/mean)
    cv = np.std(intervals) / mean_interval

    # Convert to confidence: cv of 0 = confidence 1.0, cv of 0.5+ = confidence ~0
    # Using exponential decay for smoother scaling
    confidence = np.exp(-3 * cv)

    return float(np.clip(confidence, 0.0, 1.0))
