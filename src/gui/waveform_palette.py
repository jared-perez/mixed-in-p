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

The frequency modes have two palettes. By default they SHADE the picker
colour — a deep shade for bassy columns, the colour itself in the middle,
near-white for bright ones, the way rekordbox's Blue waveform runs navy to
white — so the data shows in lightness while the waveform stays the user's
colour. Full-spectrum (``hue_mapped``) spreads the same data over the hue
wheel instead: more separable, and more of a rainbow.

Silent columns (``centroid == 0``, see ``spectral_columns``) are painted the
base colour in the frequency modes, and are left out of the per-track spread.
"""

from __future__ import annotations

import colorsys

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

# Shaded palette (the frequency modes' default): three anchors derived from
# the picker colour. Deep = hue nudged by DEEP_HUE_SHIFT at DEEP_VALUE of its
# brightness; middle = the colour itself, hue nudged by MID_HUE_SHIFT (blue
# leans cyan, as rekordbox's does); bright = the hue at WHITE_SATURATION of its
# saturation and full brightness, i.e. near-white with a trace of the colour.
SHADE_DEEP_HUE_SHIFT = 0.04
SHADE_DEEP_VALUE = 0.55
SHADE_MID_HUE_SHIFT = -0.03
SHADE_MID_VALUE = 1.1
SHADE_WHITE_SATURATION = 0.10
# The shaded palette's columns are brightest at the axis and fall to
# 1 - SHADE_CORE_FALLOFF of that at their tips (see core_shading).
SHADE_CORE_FALLOFF = 0.55
SHADE_CORE_EXPONENT = 1.5

# Full-spectrum centroid: a hue ramp from blue (bassy) to red (bright).
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


def shades_core(mode: str, hue_mapped: bool) -> bool:
    """Whether the canvas should shade each column bright-core-to-dark-tips:
    the shaded palette's look, which a single flat colour per column lacks."""
    return mode in FREQUENCY_MODES and not hue_mapped


def core_shading(distance: np.ndarray) -> np.ndarray:
    """Brightness factor at *distance* from the axis, 0 (axis) .. 1 (tip)."""
    d = np.clip(distance, 0.0, 1.0)
    return 1.0 - SHADE_CORE_FALLOFF * d ** SHADE_CORE_EXPONENT


def needs_spectral(mode: str) -> bool:
    """Whether *mode* needs ``spectral_columns`` — Solid and Loudness never pay for the FFT."""
    return mode in FREQUENCY_MODES


def column_colors(
    mode: str,
    absolute: bool,
    *,
    base_color: str,
    columns: int,
    hue_mapped: bool = False,
    peaks: np.ndarray | None = None,
    low: np.ndarray | None = None,
    mid: np.ndarray | None = None,
    high: np.ndarray | None = None,
    centroid: np.ndarray | None = None,
) -> np.ndarray:
    """-> ``(columns, 3)`` uint8 RGB, one row per waveform column.

    *peaks* (per-column peak magnitude, 0..1) drives loudness; *low*, *mid*,
    *high* (band shares) and *centroid* (Hz) come from ``spectral_columns``.
    *hue_mapped* picks the full-spectrum palette for bands and centroid, in
    place of shades of *base_color*.
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
        levels = {
            name: _band_level(np.asarray(share, dtype=np.float32), silent, absolute)
            for name, share in (("low", low), ("mid", mid), ("high", high))
        }
        if hue_mapped:
            # R = low, G = high, B = mid.
            rgb = np.stack([levels["low"], levels["high"], levels["mid"]], axis=1) * 255.0
        else:
            # Each band pulls toward its anchor: bass deep, mids the colour,
            # highs near-white.
            weights = np.stack([levels["low"], levels["mid"], levels["high"]], axis=1) + 1e-6
            weights /= weights.sum(axis=1, keepdims=True)
            rgb = weights @ _shade_anchors(base_color) * 255.0
        return _to_uint8(np.where(silent[:, None], solid, rgb))

    if mode == "centroid" and centroid is not None:
        cen = np.asarray(centroid, dtype=np.float32)
        silent = _silent(cen, columns)
        position = _centroid_position(cen, silent, absolute)
        if hue_mapped:
            hue = CENTROID_HUE_DARK + (CENTROID_HUE_BRIGHT - CENTROID_HUE_DARK) * position
            rgb = _hsv_to_rgb(hue, CENTROID_SATURATION, 1.0) * 255.0
        else:
            rgb = _shade_ramp(_shade_anchors(base_color), position) * 255.0
        return _to_uint8(np.where(silent[:, None], solid, rgb))

    return _to_uint8(solid)


def _shade_anchors(base_color: str) -> np.ndarray:
    """``(3, 3)`` RGB floats: deep, middle and near-white shades of *base_color*."""
    r, g, b = (c / 255.0 for c in hex_to_rgb(base_color))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    deep = colorsys.hsv_to_rgb((h + SHADE_DEEP_HUE_SHIFT) % 1.0, s, v * SHADE_DEEP_VALUE)
    middle = colorsys.hsv_to_rgb((h + SHADE_MID_HUE_SHIFT) % 1.0, s, min(1.0, v * SHADE_MID_VALUE))
    white = colorsys.hsv_to_rgb(h, s * SHADE_WHITE_SATURATION, 1.0)
    return np.array([deep, middle, white], dtype=np.float32)


def _shade_ramp(anchors: np.ndarray, position: np.ndarray) -> np.ndarray:
    """Deep at 0, the middle anchor at 0.5, near-white at 1."""
    t = position[:, None]
    lower = anchors[0] + (anchors[1] - anchors[0]) * (t * 2.0)
    upper = anchors[1] + (anchors[2] - anchors[1]) * (t * 2.0 - 1.0)
    return np.where(t < 0.5, lower, upper)


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
