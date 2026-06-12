"""Musical key detection using librosa chroma features.

Implements the Krumhansl-Schmuckler key-finding algorithm, which correlates
chroma features with major and minor key profiles to determine the most
likely key of a piece of music.
"""

import librosa
import numpy as np

# Krumhansl-Kessler key profiles (normalized)
# These represent the typical distribution of pitch classes in major and minor keys
# Index 0 = C, 1 = C#, 2 = D, etc.
MAJOR_PROFILE = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
)
MINOR_PROFILE = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
)

# Normalize profiles
MAJOR_PROFILE = MAJOR_PROFILE / np.linalg.norm(MAJOR_PROFILE)
MINOR_PROFILE = MINOR_PROFILE / np.linalg.norm(MINOR_PROFILE)

# Pitch class names (using sharps as canonical)
PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def detect_key(file_path: str) -> tuple[str, float]:
    """Detect the musical key of an audio file.

    Uses chroma features and the Krumhansl-Schmuckler algorithm to
    estimate the most likely key.

    Args:
        file_path: Path to the audio file

    Returns:
        Tuple of (key, confidence) where:
        - key: Detected key as string (e.g., 'Am', 'F#', 'Bbm')
        - confidence: Confidence score from 0.0 to 1.0

    Raises:
        FileNotFoundError: If the audio file doesn't exist
        librosa.util.exceptions.ParameterError: If the file can't be decoded
    """
    # Load audio
    y, sr = librosa.load(file_path, sr=None, mono=True)

    # Extract chroma features using CQT (better for music than STFT)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)

    # Average chroma across time to get overall pitch class distribution
    chroma_avg = np.mean(chroma, axis=1)

    # Normalize
    chroma_norm = chroma_avg / np.linalg.norm(chroma_avg)

    # Find best key by correlating with all possible key profiles
    best_key, best_correlation = _find_best_key(chroma_norm)

    # Convert correlation to confidence (correlation ranges from -1 to 1)
    # Typical good matches have correlation 0.6-0.9
    confidence = _correlation_to_confidence(best_correlation)

    return best_key, round(confidence, 3)


def _find_best_key(chroma: np.ndarray) -> tuple[str, float]:
    """Find the key that best matches the chroma distribution.

    Tests all 24 major and minor keys by rotating the key profiles
    and correlating with the observed chroma distribution.

    Args:
        chroma: Normalized 12-element chroma vector

    Returns:
        Tuple of (key_name, correlation)
    """
    best_key = "C"
    best_corr = -1.0

    # Test all 12 pitch classes as both major and minor
    for i, pitch in enumerate(PITCH_CLASSES):
        # Rotate profiles to match this root note
        major_rotated = np.roll(MAJOR_PROFILE, i)
        minor_rotated = np.roll(MINOR_PROFILE, i)

        # Correlate with chroma
        major_corr = float(np.corrcoef(chroma, major_rotated)[0, 1])
        minor_corr = float(np.corrcoef(chroma, minor_rotated)[0, 1])

        if major_corr > best_corr:
            best_corr = major_corr
            best_key = pitch

        if minor_corr > best_corr:
            best_corr = minor_corr
            best_key = f"{pitch}m"

    return best_key, best_corr


def _correlation_to_confidence(correlation: float) -> float:
    """Convert correlation coefficient to confidence score.

    Maps the correlation range to a 0-1 confidence score, with
    typical good key detection correlations (0.5-0.9) mapping to
    reasonable confidence values.

    Args:
        correlation: Pearson correlation coefficient (-1 to 1)

    Returns:
        Confidence score from 0.0 to 1.0
    """
    # Correlations below 0.3 are essentially noise
    if correlation < 0.3:
        return 0.0

    # Map 0.3-0.9 to 0.0-1.0 (linear scaling)
    # Correlations above 0.9 are excellent
    confidence = (correlation - 0.3) / 0.6
    return float(np.clip(confidence, 0.0, 1.0))


def get_key_alternatives(file_path: str, top_n: int = 3) -> list[tuple[str, float]]:
    """Get the top N most likely keys for an audio file.

    Useful when the primary key detection is uncertain and the user
    might want to choose from alternatives.

    Args:
        file_path: Path to the audio file
        top_n: Number of alternatives to return (default 3)

    Returns:
        List of (key, confidence) tuples, sorted by confidence descending
    """
    y, sr = librosa.load(file_path, sr=None, mono=True)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    chroma_avg = np.mean(chroma, axis=1)
    chroma_norm = chroma_avg / np.linalg.norm(chroma_avg)

    # Collect all correlations
    all_keys: list[tuple[str, float]] = []

    for i, pitch in enumerate(PITCH_CLASSES):
        major_rotated = np.roll(MAJOR_PROFILE, i)
        minor_rotated = np.roll(MINOR_PROFILE, i)

        major_corr = float(np.corrcoef(chroma_norm, major_rotated)[0, 1])
        minor_corr = float(np.corrcoef(chroma_norm, minor_rotated)[0, 1])

        all_keys.append((pitch, _correlation_to_confidence(major_corr)))
        all_keys.append((f"{pitch}m", _correlation_to_confidence(minor_corr)))

    # Sort by confidence descending
    all_keys.sort(key=lambda x: x[1], reverse=True)

    return [(key, round(conf, 3)) for key, conf in all_keys[:top_n]]
