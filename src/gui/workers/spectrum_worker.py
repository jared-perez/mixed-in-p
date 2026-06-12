"""Background worker that decodes an audio file and renders a Spek-style
linear-frequency spectrogram into a QImage off the UI thread.

The heavy work (decode + STFT + colour mapping) is fully vectorised with
numpy, so a full track resolves in well under a second. No new dependencies:
decoding reuses ``WaveformWorker._read_audio`` and the FFT is ``numpy.fft``.
"""

from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage

from .waveform_worker import WaveformWorker

logger = logging.getLogger(__name__)


def _build_colormap() -> np.ndarray:
    """Return a 256x3 uint8 LUT, Spek-like black->blue->green->yellow->white.

    Index 0 is silence (black); index 255 is the loudest (white). Intermediate
    stops sweep through the cool-to-warm ramp that reads as a spectrogram.
    """
    stops = [
        (0.00, (0, 0, 0)),
        (0.15, (0, 0, 60)),
        (0.30, (30, 0, 120)),
        (0.45, (0, 60, 200)),
        (0.60, (0, 180, 160)),
        (0.75, (120, 220, 0)),
        (0.88, (255, 200, 0)),
        (1.00, (255, 255, 255)),
    ]
    xs = np.array([s[0] for s in stops])
    rgb = np.array([s[1] for s in stops], dtype=np.float64)
    grid = np.linspace(0.0, 1.0, 256)
    lut = np.empty((256, 3), dtype=np.uint8)
    for ch in range(3):
        lut[:, ch] = np.interp(grid, xs, rgb[:, ch]).round().astype(np.uint8)
    return lut


# Built once at import — the colour ramp never changes.
_COLORMAP = _build_colormap()

# Default dynamic range shown below the loudest bin, in dB. Anything quieter
# than (peak - range) clamps to the colormap floor (black). A LARGER range
# lifts more quiet content into bright colours (higher sensitivity). This is
# only the fallback default — the live value comes from the panel's slider.
DYNAMIC_RANGE_DB = 110.0


def colorize(db: np.ndarray, peak: float, dynamic_range_db: float) -> QImage:
    """Map an oriented dB matrix to an RGB QImage over *dynamic_range_db*.

    ``db`` is shaped (freq_bins, time_cols), already oriented so row 0 is the
    highest frequency and the last row is 0 Hz. A smaller ``dynamic_range_db``
    raises sensitivity: quieter signal maps to brighter colours. Cheap enough
    to call live on the UI thread when the slider moves (no FFT rerun).
    """
    floor = peak - dynamic_range_db
    norm = np.clip((db - floor) / dynamic_range_db, 0.0, 1.0)
    lut_idx = (norm * 255.0).astype(np.uint8)
    rgb = np.ascontiguousarray(_COLORMAP[lut_idx], dtype=np.uint8)  # (h, w, 3)
    h, w = rgb.shape[0], rgb.shape[1]
    # Copy so the QImage owns its pixels (the numpy buffer is local here).
    return QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()


class SpectrumWorker(QObject):
    """Decode a file and emit a ready-to-paint spectrogram QImage.

    finished: (db: np.ndarray, peak: float, sample_rate: int, duration_ms: int)
      - db is (freq_bins, time_cols), oriented high-freq (top) to 0 Hz (bottom).
      - The panel colorizes it with the live dynamic range (see ``colorize``).
    """

    # db_matrix, peak_db, sample_rate, duration_ms
    finished = Signal(object, float, int, int)
    error = Signal(str)

    # FFT window size (frequency resolution). 2048 @ 44.1 kHz -> ~21 Hz/bin.
    N_FFT = 2048
    # Upper bound on time columns so memory/time stay flat regardless of length.
    MAX_COLUMNS = 1800

    def __init__(self, file_path: str) -> None:
        super().__init__()
        self._file_path = file_path

    @Slot()
    def run(self) -> None:
        try:
            db, peak, sr, duration_ms = self._render(self._file_path)
        except Exception as e:  # noqa: BLE001 — surface any decode/FFT failure to the panel
            logger.warning(f"Spectrum render failed for {self._file_path}: {e}")
            self.error.emit(str(e))
            return
        self.finished.emit(db, peak, sr, duration_ms)

    @classmethod
    def _render(cls, path: str) -> tuple[np.ndarray, float, int, int]:
        pcm, sr = WaveformWorker._read_audio(path)
        n_samples = pcm.shape[0]
        if n_samples == 0 or sr <= 0:
            raise ValueError("Empty audio")

        mono = pcm.mean(axis=1).astype(np.float32)
        duration_ms = int(round(n_samples * 1000 / sr))

        n_fft = cls.N_FFT
        if mono.shape[0] < n_fft:
            mono = np.pad(mono, (0, n_fft - mono.shape[0]))
            n_samples = mono.shape[0]

        # Hop is the larger of a 75%-overlap step and whatever keeps the column
        # count under MAX_COLUMNS — so short clips get a dense view and long
        # tracks degrade gracefully instead of blowing up the image size.
        min_hop = n_fft // 4
        hop = max(min_hop, int(np.ceil((n_samples - n_fft) / cls.MAX_COLUMNS)) or 1)
        num_frames = 1 + (n_samples - n_fft) // hop

        # Frame the signal: (num_frames, n_fft) view via fancy indexing.
        idx = np.arange(n_fft)[None, :] + hop * np.arange(num_frames)[:, None]
        frames = mono[idx]
        window = np.hanning(n_fft).astype(np.float32)
        spec = np.fft.rfft(frames * window, axis=1)
        mag = np.abs(spec)  # (num_frames, n_bins)

        # Magnitude -> dB. Orient once so colorize() can map directly: rows run
        # high frequency (top) to 0 Hz (bottom), columns are time.
        db = 20.0 * np.log10(mag + 1e-9)        # (frames, bins)
        db = np.flipud(db.T)                    # (bins, frames): high freq on top
        db = np.ascontiguousarray(db, dtype=np.float32)
        peak = float(db.max())
        return db, peak, int(sr), duration_ms
