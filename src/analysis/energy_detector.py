"""Energy level detection using librosa audio features.

Combines RMS loudness, spectral centroid, and onset density
to produce a 1-10 energy rating similar to Mixed In Key.
"""

from __future__ import annotations

import logging

import librosa
import numpy as np

logger = logging.getLogger(__name__)


def detect_energy(file_path: str) -> tuple[int, float]:
    """Detect the energy level of an audio track.

    Combines three features:
      - RMS loudness (overall volume/power)
      - Spectral centroid (brightness/frequency content)
      - Onset strength density (rhythmic intensity)

    Each feature is normalized against typical DJ music ranges
    and combined with weights to produce a 1-10 energy level.

    Args:
        file_path: Path to the audio file.

    Returns:
        Tuple of (energy_level, confidence) where energy_level is 1-10
        and confidence is 0.0-1.0.
    """
    # Load audio (mono, 22050 Hz is librosa default)
    y, sr = librosa.load(file_path, sr=22050, mono=True)

    if len(y) == 0:
        return 5, 0.0

    # --- Feature 1: RMS loudness ---
    rms = librosa.feature.rms(y=y)[0]
    rms_mean = float(np.mean(rms))
    # Typical DJ music RMS range: 0.02 (ambient) to 0.25 (loud EDM)
    rms_norm = np.clip((rms_mean - 0.02) / (0.25 - 0.02), 0.0, 1.0)

    # --- Feature 2: Spectral centroid (brightness) ---
    centroid = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
    centroid_mean = float(np.mean(centroid))
    # Typical range: 1000 Hz (dark/bass-heavy) to 5000 Hz (bright/energetic)
    centroid_norm = np.clip((centroid_mean - 1000) / (5000 - 1000), 0.0, 1.0)

    # --- Feature 3: Onset density (rhythmic intensity) ---
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    onset_mean = float(np.mean(onset_env))
    # Typical range: 0.5 (sparse) to 8.0 (dense rhythmic content)
    onset_norm = np.clip((onset_mean - 0.5) / (8.0 - 0.5), 0.0, 1.0)

    # --- Weighted combination ---
    # Loudness is the strongest indicator, onset density next, brightness last
    weights = (0.45, 0.20, 0.35)
    combined = (
        weights[0] * rms_norm
        + weights[1] * centroid_norm
        + weights[2] * onset_norm
    )

    # Map 0.0-1.0 to 1-10
    energy_level = int(round(combined * 9 + 1))
    energy_level = max(1, min(10, energy_level))

    # Confidence: how much the features agree with each other
    feature_values = [rms_norm, centroid_norm, onset_norm]
    spread = float(np.std(feature_values))
    # Low spread = high agreement = high confidence
    confidence = round(max(0.0, min(1.0, 1.0 - spread * 2)), 2)

    logger.debug(
        "Energy for %s: rms=%.3f centroid=%.3f onset=%.3f → level=%d (conf=%.2f)",
        file_path,
        rms_norm,
        centroid_norm,
        onset_norm,
        energy_level,
        confidence,
    )

    return energy_level, confidence
