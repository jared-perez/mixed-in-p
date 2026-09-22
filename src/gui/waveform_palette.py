"""Per-column colours for the Player's waveforms, from the colour mode setting.

Qt-free on purpose, like play_context.py: the rules for turning analysis into
colour are what is worth testing, and they need no QApplication.

The analysis (``spectral_columns`` in waveform_worker, plus the coarse min/max
the waveform already has) is deliberately normalisation-free: band SHARES and
centroid in Hz. The normalisation setting only changes the mapping here, so
flipping it re-colours without re-analysing.

Normalisation:

- **absolute** — one fixed mapping, the same for every track, so two tracks
  compare. At overview scale a track's centroid barely moves, so under this
  mapping the Tone mode collapses into one colour.
- **per-track** (the default) — this track's own spread, stretched across the
  colours, so every mode looks alive on first use. The cost: a spectrally
  uniform track (a drone, an a cappella) has its noise stretched into colour
  that means nothing. Rare in DJ material, and the toggle is right there.

Silent columns (``centroid == 0``, see ``spectral_columns``) are painted the
base colour in the frequency modes, and are left out of the per-track spread.
"""

from __future__ import annotations

import numpy as np

from src.utils.config import WAVEFORM_COLOR_MODES

# The modes whose hue carries data, and which need spectral_columns.
FREQUENCY_MODES = frozenset({"bands", "centroid"})

# Loudness: the base colour dimmed to this fraction at silence, full at peak.
LOUDNESS_FLOOR = 0.25
# Loudness, per-track: this percentile of the track's peaks reaches full.
LOUDNESS_TRACK_PERCENTILE = 99.0

# Bands: R = low, G = high, B = mid, so bass reads red and hats cyan.
# Absolute: a band holding this share of the column saturates its channel.
BANDS_ABSOLUTE_SATURATION = 0.6
# Per-track: this percentile of the track's own share saturates it.
BANDS_TRACK_PERCENTILE = 97.0

# Centroid: a hue ramp from blue (bassy) to red (bright).
CENTROID_HUE_DARK = 0.62
CENTROID_HUE_BRIGHT = 0.0
CENTROID_SATURATION = 0.85
# Absolute: a log span over this range of centroid frequencies.
CENTROID_ABSOLUTE_LOW_HZ = 80.0
CENTROID_ABSOLUTE_HIGH_HZ = 8000.0
# Per-track: this percentile band of the track's centroids spans the ramp.
CENTROID_TRACK_PERCENTILES = (5.0, 95.0)


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    """``#RRGGBB`` -> ``(r, g, b)``."""
    value = color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def peak_envelope(min_arr: np.ndarray, max_arr: np.ndarray) -> np.ndarray:
    """Per-column peak magnitude, the loudness mode's input: the louder half."""
    return np.maximum(np.maximum(max_arr, -min_arr), 0.0)


def needs_spectral(mode: str) -> bool:
    """Whether *mode* needs ``spectral_columns`` — Solid and Loudness never pay for the FFT."""
    return mode in FREQUENCY_MODES


def column_colors(
    mode: str,
    absolute: bool,
    *,
    base_color: str,
    columns: int,
    peaks: np.ndarray | None = None,
    low: np.ndarray | None = None,
    mid: np.ndarray | None = None,
    high: np.ndarray | None = None,
    centroid: np.ndarray | None = None,
) -> np.ndarray:
    """-> ``(columns, 3)`` uint8 RGB, one row per waveform column.

    *peaks* (per-column peak magnitude, 0..1) drives loudness; *low*, *mid*,
    *high* (band shares) and *centroid* (Hz) come from ``spectral_columns``.
    A mode whose inputs are missing falls back to the solid base colour, so a
    caller still waiting on analysis draws something sensible.
    """
    if mode not in WAVEFORM_COLOR_MODES:
        mode = "solid"
    base = np.array(hex_to_rgb(base_color), dtype=np.float32)
    solid = np.broadcast_to(base, (columns, 3))

    if mode == "loudness" and peaks is not None:
        level = _loudness_level(np.asarray(peaks, dtype=np.float32), absolute)
        factor = LOUDNESS_FLOOR + (1.0 - LOUDNESS_FLOOR) * level
        return _to_uint8(solid * factor[:, None])

    if mode == "bands" and low is not None and mid is not None and high is not None:
        silent = _silent(centroid, columns)
        channels = [
            _band_level(np.asarray(share, dtype=np.float32), silent, absolute)
            for share in (low, high, mid)  # R, G, B
        ]
        rgb = np.stack(channels, axis=1) * 255.0
        return _to_uint8(np.where(silent[:, None], solid, rgb))

    if mode == "centroid" and centroid is not None:
        cen = np.asarray(centroid, dtype=np.float32)
        silent = _silent(cen, columns)
        position = _centroid_position(cen, silent, absolute)
        hue = CENTROID_HUE_DARK + (CENTROID_HUE_BRIGHT - CENTROID_HUE_DARK) * position
        rgb = _hsv_to_rgb(hue, CENTROID_SATURATION, 1.0) * 255.0
        return _to_uint8(np.where(silent[:, None], solid, rgb))

    return _to_uint8(solid)


def _silent(centroid: np.ndarray | None, columns: int) -> np.ndarray:
    if centroid is None:
        return np.zeros(columns, dtype=bool)
    return np.asarray(centroid) <= 0


def _loudness_level(peaks: np.ndarray, absolute: bool) -> np.ndarray:
    if absolute:
        ref = 1.0  # full scale
    else:
        ref = float(np.percentile(peaks, LOUDNESS_TRACK_PERCENTILE)) if len(peaks) else 1.0
    if ref <= 0:
        return np.zeros_like(peaks)
    return np.clip(peaks / ref, 0.0, 1.0)


def _band_level(share: np.ndarray, silent: np.ndarray, absolute: bool) -> np.ndarray:
    if absolute:
        ref = BANDS_ABSOLUTE_SATURATION
    else:
        live = share[~silent]
        ref = float(np.percentile(live, BANDS_TRACK_PERCENTILE)) if len(live) else 1.0
    if ref <= 0:
        return np.zeros_like(share)
    return np.clip(share / ref, 0.0, 1.0)


def _centroid_position(cen: np.ndarray, silent: np.ndarray, absolute: bool) -> np.ndarray:
    """0 (bassy) .. 1 (bright) along the hue ramp."""
    if absolute:
        lo = np.log2(CENTROID_ABSOLUTE_LOW_HZ)
        hi = np.log2(CENTROID_ABSOLUTE_HIGH_HZ)
        pos = (np.log2(np.maximum(cen, 1.0)) - lo) / (hi - lo)
        return np.clip(pos, 0.0, 1.0)
    live = cen[~silent]
    if not len(live):
        return np.zeros_like(cen)
    lo, hi = (float(v) for v in np.percentile(live, CENTROID_TRACK_PERCENTILES))
    if hi <= lo:
        return np.full_like(cen, 0.5)
    return np.clip((cen - lo) / (hi - lo), 0.0, 1.0)


def _hsv_to_rgb(h: np.ndarray, s: float, v: float) -> np.ndarray:
    """Vectorised HSV -> RGB floats in 0..1, shape ``(N, 3)``."""
    h = np.mod(np.asarray(h, dtype=np.float32), 1.0) * 6.0
    i = np.floor(h).astype(np.int32) % 6
    f = h - np.floor(h)
    p = np.full_like(h, v * (1.0 - s))
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    vv = np.full_like(h, v)
    r = np.choose(i, [vv, q, p, p, t, vv])
    g = np.choose(i, [t, vv, vv, q, p, p])
    b = np.choose(i, [p, p, t, vv, vv, q])
    return np.stack([r, g, b], axis=1)


def _to_uint8(rgb: np.ndarray) -> np.ndarray:
    return np.clip(np.rint(rgb), 0, 255).astype(np.uint8)
