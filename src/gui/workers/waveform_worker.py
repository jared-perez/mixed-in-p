"""Background worker that loads an audio file and downsamples it to a
min/max waveform suitable for display in WaveformCanvas.
"""

from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

logger = logging.getLogger(__name__)

# Target resolution for the detail (zoom) waveform. At 44.1 kHz this rounds to
# 11 samples per bin (~4 009 bins/sec) — enough to fill a wide high-DPI (Retina)
# widget at 1 bin per physical pixel for the 1 s zoom window, so the scrubber
# stays crisp. ~4.8 MB per array for a 5-minute track.
DETAIL_BINS_PER_SEC = 4000


def mono_mix(pcm: np.ndarray) -> np.ndarray:
    """Mono mix-down of ``(frames, channels)`` PCM as float32.

    NOT ``pcm.mean(axis=1)``: numpy reduces a length-2 fast axis
    pathologically (67.8 ms vs 3.8 ms on a 5-minute stereo track). Works on a
    slice, since the player engine mixes ``pcm[start:end]``.
    """
    if pcm.ndim == 1:
        return pcm.astype(np.float32, copy=False)
    channels = pcm.shape[1]
    if channels == 1:
        return pcm[:, 0].astype(np.float32)
    if channels == 2:
        return ((pcm[:, 0] + pcm[:, 1]) * 0.5).astype(np.float32, copy=False)
    return pcm.mean(axis=1).astype(np.float32)


def timed_envelope(pcm: np.ndarray, sr: int, bins_per_sec: int = 200):
    """Time-indexed mono min/max envelope at ~*bins_per_sec* resolution.

    For the playlist backdrop's scrolling zoom window, which maps time → bins
    directly (unlike the fixed-column overview the slicer uses, or the much
    denser detail arrays its 1 s scrubber needs). Cheap enough to run on the
    GUI thread at track start; ~200 bins/s keeps a 5-minute track under 0.5 MB.
    Returns ``(env_min, env_max, actual_bins_per_sec)``. Raises ValueError on
    empty audio.
    """
    if pcm.ndim == 1:
        pcm = pcm.reshape(-1, 1)
    n_samples = pcm.shape[0]
    if n_samples == 0 or sr <= 0:
        raise ValueError("Empty audio")
    mono = mono_mix(pcm)
    samples_per_bin = max(1, int(round(sr / bins_per_sec)))
    if n_samples < samples_per_bin:
        return (
            np.array([mono.min()], dtype=np.float32),
            np.array([mono.max()], dtype=np.float32),
            sr / n_samples,
        )
    cols = n_samples // samples_per_bin
    trimmed = mono[: samples_per_bin * cols]
    reshaped = trimmed.reshape(cols, samples_per_bin)
    return (
        reshaped.min(axis=1).astype(np.float32),
        reshaped.max(axis=1).astype(np.float32),
        sr / samples_per_bin,
    )


def downsample_waveform(
    pcm: np.ndarray,
    sr: int,
    target_columns: int = 2000,
    detail_bins_per_sec: int = DETAIL_BINS_PER_SEC,
):
    """Downsample already-decoded PCM to coarse + detail min/max arrays.

    Returns ``(coarse_min, coarse_max, duration_ms, detail_min, detail_max,
    detail_bins_per_sec)`` — the same tuple ``WaveformWorker.finished`` carries.
    Pure numpy and file-free, so the player can build a waveform from PCM it has
    already decoded without a second disk read. Raises ValueError on empty audio.
    """
    target_columns = max(100, target_columns)
    if pcm.ndim == 1:
        pcm = pcm.reshape(-1, 1)
    n_samples = pcm.shape[0]
    if n_samples == 0 or sr <= 0:
        raise ValueError("Empty audio")

    # Mono mix drives the displayed waveform.
    mono = mono_mix(pcm)
    duration_ms = int(round(n_samples * 1000 / sr))

    # --- Coarse (overview) ---
    cols = min(target_columns, n_samples)
    samples_per_col = n_samples // cols
    trimmed = mono[: samples_per_col * cols]
    reshaped = trimmed.reshape(cols, samples_per_col)
    coarse_min = reshaped.min(axis=1).astype(np.float32)
    coarse_max = reshaped.max(axis=1).astype(np.float32)

    # --- Detail (zoom) ---
    samples_per_detail = max(1, sr // detail_bins_per_sec)
    detail_cols = n_samples // samples_per_detail
    if detail_cols > 0:
        detail_trimmed = mono[: samples_per_detail * detail_cols]
        detail_reshaped = detail_trimmed.reshape(detail_cols, samples_per_detail)
        detail_min = detail_reshaped.min(axis=1).astype(np.float32)
        detail_max = detail_reshaped.max(axis=1).astype(np.float32)
        detail_bps = sr / samples_per_detail
    else:
        # Sub-second clip: skip detail; zoom view will degrade gracefully.
        detail_min = np.zeros(0, dtype=np.float32)
        detail_max = np.zeros(0, dtype=np.float32)
        detail_bps = 0.0

    return coarse_min, coarse_max, duration_ms, detail_min, detail_max, float(detail_bps)


# Spectral colouring (``spectral_columns``). Non-overlapping frames give 100%
# sample coverage for ~30 ms on a 5-minute track; 2048 at 44.1 kHz resolves
# down to ~21 Hz, so bass lands in the low band rather than smearing into mid.
SPECTRAL_N_FFT = 2048
# Band edges in Hz: low < 250 <= mid < 4000 <= high.
SPECTRAL_LOW_MID_HZ = 250.0
SPECTRAL_MID_HIGH_HZ = 4000.0
# A column quieter than this RMS (-60 dBFS) is silence: it reports centroid 0
# and equal shares, and the palette paints it the base colour rather than
# stretching dither into colour.
SPECTRAL_SILENCE_RMS = 1e-3


def spectral_columns(mono: np.ndarray, sr: int, columns: int = 2000):
    """Per-column band shares and spectral centroid, for waveform colouring.

    Returns ``(low, mid, high, centroid_hz)``, each float32 of length
    *columns*, aligned with ``downsample_waveform``'s coarse columns for the
    same *columns*. low/mid/high are SHARES summing to 1 — loudness is already
    divided out, so the result depends on neither the colour mode nor the
    normalisation setting, and flipping either needs no re-analysis. A silent
    column reports centroid 0 and shares of 1/3.
    """
    mono = np.asarray(mono, dtype=np.float32)
    n_samples = mono.shape[0]
    if n_samples == 0 or sr <= 0:
        raise ValueError("Empty audio")
    columns = max(1, min(int(columns), n_samples))
    n_fft = SPECTRAL_N_FFT
    if n_samples < n_fft:
        mono = np.pad(mono, (0, n_fft - n_samples))
    frames = max(1, mono.shape[0] // n_fft)
    framed = mono[: frames * n_fft].reshape(frames, n_fft)

    spec = np.abs(np.fft.rfft(framed * np.hanning(n_fft).astype(np.float32), axis=1))
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    k_low = int(np.searchsorted(freqs, SPECTRAL_LOW_MID_HZ))
    k_high = int(np.searchsorted(freqs, SPECTRAL_MID_HIGH_HZ))
    low_f = spec[:, :k_low].sum(axis=1)
    mid_f = spec[:, k_low:k_high].sum(axis=1)
    high_f = spec[:, k_high:].sum(axis=1)
    mag_f = low_f + mid_f + high_f
    weighted_f = spec @ freqs  # sum(|X| * f) per frame
    energy_f = np.einsum("ij,ij->i", framed, framed)

    # Frames -> columns by where each frame's centre falls, in the same
    # sample space as downsample_waveform's coarse columns. Sums, so centroid
    # is energy-weighted (sum(cen*mag)/sum(mag)), never a mean of centroids.
    samples_per_col = max(1, n_samples // columns)
    centres = (np.arange(frames) * n_fft + n_fft // 2) // samples_per_col
    col_of_frame = np.minimum(centres, columns - 1)

    def per_col(values):
        return np.bincount(col_of_frame, weights=values, minlength=columns)

    count = per_col(np.ones(frames))
    low, mid, high = per_col(low_f), per_col(mid_f), per_col(high_f)
    mag, weighted, energy = per_col(mag_f), per_col(weighted_f), per_col(energy_f)

    # A column narrower than a frame holds no frame centre: borrow the frame
    # its own centre falls in.
    empty = count == 0
    if empty.any():
        cols = np.nonzero(empty)[0]
        src = np.minimum((cols * samples_per_col + samples_per_col // 2) // n_fft, frames - 1)
        low[cols], mid[cols], high[cols] = low_f[src], mid_f[src], high_f[src]
        mag[cols], weighted[cols], energy[cols] = mag_f[src], weighted_f[src], energy_f[src]
        count[cols] = 1

    rms = np.sqrt(energy / (count * n_fft))
    silent = (rms < SPECTRAL_SILENCE_RMS) | (mag <= 0)
    safe = np.where(silent, 1.0, mag)
    third = np.float32(1.0 / 3.0)
    low_s = np.where(silent, third, low / safe).astype(np.float32)
    mid_s = np.where(silent, third, mid / safe).astype(np.float32)
    high_s = np.where(silent, third, high / safe).astype(np.float32)
    centroid = np.where(silent, 0.0, weighted / safe).astype(np.float32)
    return low_s, mid_s, high_s, centroid


class WaveformWorker(QObject):
    """Reads a file and produces two downsampled (min, max) representations:

    - Coarse: ``target_columns`` total bins for the full-track overview.
    - Detail: ~``DETAIL_BINS_PER_SEC`` bins per second of audio for the
      zoom-scrubber view (~1-second window centred on the playhead).

    Both arrays come from the same decode pass — no extra I/O.
    """

    DETAIL_BINS_PER_SEC = DETAIL_BINS_PER_SEC

    # coarse_min, coarse_max, duration_ms, detail_min, detail_max, detail_bins_per_sec
    finished = Signal(object, object, int, object, object, float)
    # Full-resolution PCM for gapless playback: float32 (frames, channels), sr.
    # Emitted from the same decode pass so the loop player needn't decode again.
    audio_ready = Signal(object, int)
    error = Signal(str)

    def __init__(self, file_path: str, target_columns: int = 2000) -> None:
        super().__init__()
        self._file_path = file_path
        self._target_columns = max(100, target_columns)

    @Slot()
    def run(self) -> None:
        try:
            pcm, sr = self._read_audio(self._file_path)
        except Exception as e:
            logger.warning(f"Waveform load failed for {self._file_path}: {e}")
            self.error.emit(str(e))
            return

        if pcm.shape[0] == 0 or sr <= 0:
            self.error.emit("Empty audio")
            return

        # Hand the full-resolution PCM to the player straight away (before the
        # downsampling work below) so gapless looping is ready ASAP.
        self.audio_ready.emit(pcm, int(sr))

        coarse_min, coarse_max, duration_ms, detail_min, detail_max, detail_bins_per_sec = (
            downsample_waveform(pcm, int(sr), self._target_columns, self.DETAIL_BINS_PER_SEC)
        )

        self.finished.emit(
            coarse_min, coarse_max, duration_ms,
            detail_min, detail_max, detail_bins_per_sec,
        )

    @staticmethod
    def _read_audio(path: str) -> tuple[np.ndarray, int]:
        """Return (float32 PCM shaped (frames, channels) in [-1, 1], sample rate).

        Tries soundfile first (fast). Falls back to librosa for formats
        soundfile can't decode (older libsndfile builds lack MP3 support).
        The caller mixes to mono for display; the 2-D array also feeds the
        gapless loop player.
        """
        # Decode with soundfile if it's installed. A genuine decode failure
        # (unsupported format) falls through to librosa; a *missing* soundfile
        # is recorded separately so we don't mask it with a librosa import
        # error — the usual cause is launching with the wrong interpreter
        # (global Python) instead of the project venv.
        try:
            import soundfile as sf
        except ImportError:
            sf = None
        else:
            try:
                data, sr = sf.read(path, always_2d=True, dtype="float32")
                return np.ascontiguousarray(data, dtype=np.float32), int(sr)
            except Exception:  # noqa: BLE001 — try librosa for formats sf can't read
                pass

        try:
            import librosa
        except ImportError as e:
            if sf is None:
                raise RuntimeError(
                    "Cannot decode audio: neither 'soundfile' nor 'librosa' is "
                    "installed. Run the app with the project venv "
                    "(venv\\Scripts\\python.exe -m src.main)."
                ) from e
            raise  # soundfile is present but couldn't read this file
        y, sr = librosa.load(path, sr=None, mono=False)
        if y.ndim == 1:
            y = y.reshape(1, -1)
        return np.ascontiguousarray(y.T, dtype=np.float32), int(sr)
