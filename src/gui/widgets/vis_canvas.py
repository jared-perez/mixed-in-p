"""Classic-style audio visualizer rendering, popout canvas, and popout window.

Three retro visuals rendered into a small internal QImage and upscaled with
fast (non-smooth) transformation for a chunky pixel look:

- ``oscilloscope`` — time-domain trace of the last ~576 samples, vertically
  quantized to a small number of levels.
- ``spectrum`` — log-banded FFT bars with instant attack, linear falloff and
  peak-hold caps that drop with accelerating speed.
- ``fire`` — the classic heat-propagation fire effect, stoked from the bottom
  row by the same log-band energies.
- ``fractal`` — a spinning escape-time Julia set (the Mandelbrot family). The
  Julia constant orbits the classic radius so the branches continuously morph
  between dendrites and spirals; overall level drives morph/spin speed and
  brightness, and the kick pulse punches the zoom.

The rendering lives in :class:`VisRenderer` (no widget), shared by two hosts:
the popout :class:`VisCanvas`, and the Player playlist's backdrop (which blits
the frames dimmed behind the rows). Frames use a transparent background so the
backdrop composites over the playlist grey; the popout fills black first, which
looks identical to drawing opaque.

All constants are original reimplementations informed by publicly documented
behaviour of classic visualizers (see docs/visualizations-plan.md); nothing is
derived from proprietary sources. DSP is plain numpy on ~2048-sample blocks —
well under a millisecond per frame.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..styles.theme import Theme

# Internal render resolution; hosts scale it up without smoothing.
_W, _H = 152, 64
FRAME_MS = 33  # ~30 fps
FFT_SIZE = 2048
_N_BARS = 19
_BAR_W = _W // _N_BARS  # px per bar incl. 1px gap
_DB_FLOOR = -65.0
# Bar ballistics per frame (normalized 0..1 units): instant attack, linear
# release; peak caps hold then fall with multiplicative acceleration.
_BAR_FALL = 0.22
_PEAK_START = 0.05
_PEAK_ACCEL = 1.1
_SCOPE_SAMPLES = 576
_SCOPE_LEVELS = 16
_FIRE_STOKE_GAIN = 1.25
# Fractal (Julia set) tuning. The constant moves on the classic morphing-Julia
# circle |c| = 0.7885, but swings back and forth through the arc around angle π
# (measured sweep: the sets there are rich branches/spirals) instead of
# circling through the near-empty dust zone around angle 0. The view plane
# spins and the kick pulse punches a momentary zoom.
_JULIA_ITERATIONS = 26
_JULIA_ORBIT_RADIUS = 0.7885
_JULIA_ORBIT_SWING = 2.2  # max angular deviation from π on the c-circle
_JULIA_VIEW_SPAN = 3.1  # complex-plane width of the (pre-zoom) viewport
_JULIA_SPIN_BASE = 0.006  # radians/frame with no audio
_JULIA_SPIN_LEVEL = 0.045  # extra spin at full level
_JULIA_MORPH_BASE = 0.002  # c-orbit advance per frame (silence)
_JULIA_MORPH_LEVEL = 0.022  # extra orbit speed at full level
_JULIA_KICK_ZOOM = 0.14  # fraction of zoom-in on a full-strength kick

RENDER_MODES = ("oscilloscope", "spectrum", "fire", "fractal")
POPOUT_MODES = RENDER_MODES


def _fire_palette(color: QColor) -> np.ndarray:
    """256 RGB rows: a heat ramp of *color* — black → color → white.

    The classic red/orange fire is exactly this ramp for pure red; deriving it
    from the waveform color instead ties the flames to the same setting as the
    other visuals. Rebuilt only on color change; per-frame cost (a LUT lookup)
    is unaffected by the palette's contents.
    """
    t = np.linspace(0.0, 1.0, 256)[:, None]
    base = np.array([color.red(), color.green(), color.blue()], dtype=np.float64)
    up = np.clip(t / 0.6, 0.0, 1.0)  # black → color over the cooler range
    hot = np.clip((t - 0.6) / 0.4, 0.0, 1.0)  # color → white at the hottest
    rgb = base * up
    rgb = rgb + (255.0 - rgb) * hot
    return rgb.astype(np.uint8)


class VisRenderer:
    """Renders one visualization mode from mono sample blocks into a QImage."""

    def __init__(self) -> None:
        self._mode: str = "spectrum"
        self._color = QColor(Theme.WAVEFORM_DEFAULT)
        self._image = QImage(_W, _H, QImage.Format.Format_ARGB32)
        self._image.fill(Qt.GlobalColor.transparent)
        self._window = np.hanning(FFT_SIZE).astype(np.float32)
        self._band_slices: list[slice] | None = None
        self._band_sr: int = 0
        # Ballistics state (normalized 0..1 per bar).
        self._bars = np.zeros(_N_BARS, dtype=np.float64)
        self._peaks = np.zeros(_N_BARS, dtype=np.float64)
        self._peak_vel = np.full(_N_BARS, _PEAK_START, dtype=np.float64)
        self._heat = np.zeros((_H, _W), dtype=np.float32)
        self._fire_lut = _fire_palette(self._color)
        # Beat pulse (Milkdrop-style): instantaneous bass energy against its
        # own smoothed average. Chosen over a precomputed librosa onset
        # envelope because heavy DSP during playback fights the audio callback
        # for the GIL (the same reason the player suppresses prefetch-decode
        # while playing); this is a few numpy ops per frame.
        self._bass_att: float = 0.0
        self._pulse: float = 0.0
        # Fractal state: view rotation, c-orbit phase, and a fast-attack /
        # slow-release level follower so the image fades out over silence.
        self._fract_angle: float = 0.0
        self._fract_phase: float = 0.0
        self._fract_level: float = 0.0
        # Pixel → complex-plane grid, built once (square pixels, centered).
        xs = np.linspace(-0.5, 0.5, _W) * _JULIA_VIEW_SPAN
        ys = np.linspace(-0.5, 0.5, _H) * (_JULIA_VIEW_SPAN * _H / _W)
        self._fract_grid = (xs[None, :] + 1j * ys[:, None]).astype(np.complex64)

    # ── Public API ─────────────────────────────────────────────────────────

    def image(self) -> QImage:
        return self._image

    def set_mode(self, mode: str) -> None:
        if mode not in RENDER_MODES:
            return
        self._mode = mode
        self._bars[:] = 0.0
        self._peaks[:] = 0.0
        self._peak_vel[:] = _PEAK_START
        self._heat[:] = 0.0
        self._bass_att = 0.0
        self._pulse = 0.0
        self._fract_angle = 0.0
        self._fract_phase = 0.0
        self._fract_level = 0.0

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self._fire_lut = _fire_palette(self._color)

    def render(self, samples: np.ndarray | None, sr: int) -> QImage:
        """Advance one frame from a mono block (zeros/None = silence)."""
        if samples is None or len(samples) < FFT_SIZE:
            samples = np.zeros(FFT_SIZE, dtype=np.float32)
        else:
            samples = samples[-FFT_SIZE:]
        if self._mode == "oscilloscope":
            self._render_scope(samples)
        else:
            heights = self._band_heights(samples, sr)
            if self._mode == "spectrum":
                self._render_spectrum(heights)
            elif self._mode == "fractal":
                self._render_fractal(heights)
            else:
                self._render_fire(heights)
        return self._image

    # ── DSP ────────────────────────────────────────────────────────────────

    def _ensure_bands(self, sr: int) -> None:
        """Log-spaced band → FFT-bin slices, rebuilt when the rate changes."""
        if self._band_slices is not None and self._band_sr == sr:
            return
        freqs = np.fft.rfftfreq(FFT_SIZE, 1.0 / max(sr, 1))
        f_lo, f_hi = 50.0, min(16000.0, sr / 2.0 if sr > 0 else 16000.0)
        edges = f_lo * (f_hi / f_lo) ** (np.arange(_N_BARS + 1) / _N_BARS)
        idx = np.searchsorted(freqs, edges).astype(int)
        # Every band gets at least one bin (low bands can span <1 bin).
        for k in range(1, len(idx)):
            idx[k] = max(idx[k], idx[k - 1] + 1)
        idx = np.clip(idx, 1, len(freqs) - 1)
        self._band_slices = [slice(idx[k], max(idx[k + 1], idx[k] + 1)) for k in range(_N_BARS)]
        self._band_sr = sr

    def _band_heights(self, samples: np.ndarray, sr: int) -> np.ndarray:
        """Normalized 0..1 dB heights per log band."""
        self._ensure_bands(sr if sr > 0 else 44100)
        spectrum = np.abs(np.fft.rfft(samples * self._window))
        # Hann coherent gain is 0.5 → a full-scale sine peaks its bin at N/4.
        spectrum /= FFT_SIZE / 4.0
        self._update_pulse(spectrum)
        db = 20.0 * np.log10(spectrum + 1e-9)
        heights = np.array([db[s].max() for s in self._band_slices])
        return np.clip((heights - _DB_FLOOR) / -_DB_FLOOR, 0.0, 1.0)

    def _update_pulse(self, spectrum: np.ndarray) -> None:
        """Kick-locked pulse: linear bass energy vs its smoothed average."""
        # The first two log bands cover ~50-120 Hz — the kick-drum range.
        bass = float(
            (spectrum[self._band_slices[0]] ** 2).mean()
            + (spectrum[self._band_slices[1]] ** 2).mean()
        )
        self._bass_att = 0.97 * self._bass_att + 0.03 * bass
        if self._bass_att < 1e-7:
            self._pulse = 0.0
            return
        ratio = bass / self._bass_att
        # >1.2 counts as a beat; saturate by ~1.8 for a 0..1 accent value.
        self._pulse = float(np.clip((ratio - 1.2) / 0.6, 0.0, 1.0))

    def _apply_ballistics(self, heights: np.ndarray) -> None:
        """Instant attack, linear release; accelerating peak-cap fall."""
        self._bars = np.maximum(heights, self._bars - _BAR_FALL)
        rising = self._bars >= self._peaks
        self._peaks = np.where(rising, self._bars, self._peaks - self._peak_vel)
        self._peak_vel = np.where(rising, _PEAK_START, self._peak_vel * _PEAK_ACCEL)
        self._peaks = np.clip(self._peaks, 0.0, 1.0)

    # ── Renderers (into the internal low-res image) ────────────────────────

    def _render_scope(self, samples: np.ndarray) -> None:
        self._image.fill(Qt.GlobalColor.transparent)
        trace = samples[-_SCOPE_SAMPLES:]
        cols = np.linspace(0, len(trace) - 1, _W).astype(int)
        # Quantize to a few vertical levels for the chunky retro trace.
        levels = np.round(np.clip(trace[cols], -1.0, 1.0) * (_SCOPE_LEVELS / 2))
        ys = (_H / 2 - levels * (_H / _SCOPE_LEVELS)).astype(int).clip(1, _H - 2)
        painter = QPainter(self._image)
        painter.setPen(QPen(self._color, 1))
        for x in range(1, _W):
            painter.drawLine(x - 1, int(ys[x - 1]), x, int(ys[x]))
        painter.end()

    def _spectrum_gradient(self) -> QLinearGradient:
        gradient = QLinearGradient(0, _H, 0, 0)
        gradient.setColorAt(0.0, self._color.darker(300))
        gradient.setColorAt(0.6, self._color)
        gradient.setColorAt(1.0, self._color.lighter(160))
        return gradient

    def _render_spectrum(self, heights: np.ndarray) -> None:
        self._apply_ballistics(heights)
        self._image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self._image)
        if self._pulse > 0.0:
            # Kick accent: the whole background glows faintly with the beat.
            flash = QColor(self._color)
            flash.setAlpha(int(28 * self._pulse))
            painter.fillRect(0, 0, _W, _H, flash)
        gradient = self._spectrum_gradient()
        cap_color = QColor(Theme.CHROME)
        for i in range(_N_BARS):
            x = i * _BAR_W
            bar_h = int(self._bars[i] * (_H - 2))
            if bar_h > 0:
                painter.fillRect(x, _H - bar_h, _BAR_W - 1, bar_h, gradient)
            peak_y = _H - 1 - int(self._peaks[i] * (_H - 2))
            painter.fillRect(x, peak_y, _BAR_W - 1, 1, cap_color)
        painter.end()

    def _render_fire(self, heights: np.ndarray) -> None:
        heat = self._heat
        # Stoke the bottom row from band energies spread across the width.
        stoke = np.interp(
            np.arange(_W), np.linspace(0, _W - 1, _N_BARS), heights
        ).astype(np.float32)
        # Kick accent: flames leap on the beat.
        gain = _FIRE_STOKE_GAIN * (1.0 + 0.8 * self._pulse)
        heat[_H - 1] = np.maximum(heat[_H - 1] * 0.5, stoke * gain)
        # Classic propagation: each cell becomes a cooled average of the cells
        # below it (straight + diagonal), so flames rise, waver, and die out.
        below = heat[1:]
        avg = (below + np.roll(below, 1, axis=1) + np.roll(below, -1, axis=1)) / 3.0
        heat[:-1] = np.maximum(avg - 0.028, 0.0)
        np.clip(heat, 0.0, 1.0, out=heat)

        rgb = self._fire_lut[(heat * 255).astype(np.uint8)]
        # QImage wants 32-bit rows; build BGRA from the palette lookup. Alpha
        # follows heat so cold pixels are transparent (the backdrop host
        # composites over grey; the popout fills black first — same look).
        bgra = np.empty((_H, _W, 4), dtype=np.uint8)
        bgra[..., 0] = rgb[..., 2]
        bgra[..., 1] = rgb[..., 1]
        bgra[..., 2] = rgb[..., 0]
        bgra[..., 3] = (np.clip(heat * 2.5, 0.0, 1.0) * 255).astype(np.uint8)
        self._image = QImage(
            bgra.tobytes(), _W, _H, _W * 4, QImage.Format.Format_ARGB32
        ).copy()

    def _render_fractal(self, heights: np.ndarray) -> None:
        # Blend mean and max band height: mean alone leaves sparse spectra
        # (e.g. a lone bass line) nearly invisible, max alone never breathes.
        level = float(np.clip(0.5 * heights.mean() + 0.6 * heights.max(), 0.0, 1.0))
        # Fast attack, slow release: the fractal lights up with the music and
        # fades out over ~2s of silence (0.94^60 ≈ 0.02) instead of freezing.
        self._fract_level = max(level, self._fract_level * 0.94)
        self._fract_angle += _JULIA_SPIN_BASE + _JULIA_SPIN_LEVEL * level
        self._fract_phase += _JULIA_MORPH_BASE + _JULIA_MORPH_LEVEL * level

        theta = np.pi + _JULIA_ORBIT_SWING * np.sin(self._fract_phase)
        c = _JULIA_ORBIT_RADIUS * np.exp(1j * theta)
        zoom = 1.0 - _JULIA_KICK_ZOOM * self._pulse
        z = (self._fract_grid * (np.exp(-1j * self._fract_angle) * zoom)).ravel()

        # Escape-time iteration; points that never escape (the set's interior)
        # keep count 0 and are recolored to full brightness below.
        count = np.zeros(z.shape, dtype=np.float32)
        alive = np.ones(z.shape, dtype=bool)
        for i in range(1, _JULIA_ITERATIONS + 1):
            za = z[alive]
            za = za * za + c
            z[alive] = za
            escaped = np.abs(za) > 2.0
            idx = np.flatnonzero(alive)[escaped]
            count[idx] = i
            alive[idx] = False
            if not alive.any():
                break

        # Late escape = close to the set = bright branch edge. The interior
        # sits at mid brightness (body in the theme color) so the near-white
        # top of the ramp is reserved for the dendrite fringe — full-bright
        # interiors render as flat washed-out blobs. The exponent darkens the
        # far field for contrast.
        intensity = (count / _JULIA_ITERATIONS) ** 1.6
        intensity[alive] = 0.5
        brightness = self._fract_level * (0.8 + 0.5 * self._pulse)
        intensity = (intensity * np.clip(brightness, 0.0, 1.0)).reshape(_H, _W)

        rgb = self._fire_lut[(intensity * 255).astype(np.uint8)]
        bgra = np.empty((_H, _W, 4), dtype=np.uint8)
        bgra[..., 0] = rgb[..., 2]
        bgra[..., 1] = rgb[..., 1]
        bgra[..., 2] = rgb[..., 0]
        bgra[..., 3] = (np.clip(intensity * 2.2, 0.0, 1.0) * 255).astype(np.uint8)
        self._image = QImage(
            bgra.tobytes(), _W, _H, _W * 4, QImage.Format.Format_ARGB32
        ).copy()


class VisCanvas(QWidget):
    """Popout widget that renders one visualization mode from fed samples."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(_W * 2, _H * 2)
        self._renderer = VisRenderer()

    def set_mode(self, mode: str) -> None:
        self._renderer.set_mode(mode)

    def set_color(self, color: str) -> None:
        self._renderer.set_color(color)

    def feed(self, samples: np.ndarray | None, sr: int) -> None:
        self._renderer.render(samples, sr)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.fillRect(self.rect(), QColor("#0a0a0a"))
        painter.drawImage(self.rect(), self._renderer.image())
        painter.end()


class VisualizerWindow(QWidget):
    """Popout window hosting a VisCanvas, fed from the player engine."""

    closed = Signal()

    def __init__(self, engine, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle(self.tr("Visualizer"))
        self.setStyleSheet("background-color: #0a0a0a;")
        self.resize(_W * 4, _H * 4)
        self._engine = engine
        self._canvas = VisCanvas(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._canvas)
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._on_tick)

    def set_mode(self, mode: str) -> None:
        self._canvas.set_mode(mode)

    def set_color(self, color: str) -> None:
        self._canvas.set_color(color)

    def _on_tick(self) -> None:
        # While paused/stopped keep ticking with silence so bars fall and the
        # fire burns down instead of freezing mid-frame.
        samples = self._engine.recent_mono(FFT_SIZE) if self._engine.is_playing() else None
        self._canvas.feed(samples, self._engine.sample_rate())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._timer.stop()

    def closeEvent(self, event) -> None:
        self._timer.stop()
        super().closeEvent(event)
        self.closed.emit()
