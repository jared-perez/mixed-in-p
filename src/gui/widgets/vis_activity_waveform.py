"""Animated waveform strip shown while analysis/conversion work runs.

Purely decorative "activity" visual: the wave shape is synthesized (layered
sines with drifting phase), not derived from the audio being processed — the
workers churn through files and real per-block audio isn't worth plumbing out
for an indicator. Doubles as a progress bar: columns left of the completed
fraction are painted at full intensity, the remainder dimmed.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

# One phase step per frame at ~30 fps; tuned so the wave rolls noticeably but
# doesn't strobe next to the static progress bar below it.
_FRAME_MS = 33
_PHASE_STEP = 0.09
_BAR_STEP = 3  # px per waveform column (2px line + 1px gap)


class VisActivityWaveform(QWidget):
    """Self-animating synthetic waveform with a progress-fraction highlight."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(44)
        self._color = QColor("#f0ff00")
        self._phase: float = 0.0
        self._fraction: float = 0.0
        self._running: bool = False
        self._timer = QTimer(self)
        self._timer.setInterval(_FRAME_MS)
        self._timer.timeout.connect(self._on_tick)

    # ── Public API ─────────────────────────────────────────────────────────

    def set_color(self, color: str) -> None:
        """Set the waveform body color (#RRGGBB)."""
        self._color = QColor(color)
        if self.isVisible():
            self.update()

    def set_fraction(self, fraction: float) -> None:
        """Set the completed fraction (0..1) for the brightness sweep."""
        self._fraction = max(0.0, min(1.0, fraction))

    def start(self) -> None:
        """Begin animating (timer only runs while the widget is visible)."""
        self._running = True
        self._phase = 0.0
        self._fraction = 0.0
        if self.isVisible():
            self._timer.start()

    def stop(self) -> None:
        """Freeze the animation (e.g. on completion or error)."""
        self._running = False
        self._timer.stop()

    # ── Internals ──────────────────────────────────────────────────────────

    def _on_tick(self) -> None:
        self._phase += _PHASE_STEP
        self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._running:
            self._timer.start()

    def hideEvent(self, event) -> None:
        # Don't burn frames while another page is shown; showEvent resumes.
        super().hideEvent(event)
        self._timer.stop()

    def paintEvent(self, event) -> None:
        w, h = self.width(), self.height()
        if w < _BAR_STEP or h < 4:
            return

        n = w // _BAR_STEP
        mid = h / 2.0
        half = mid - 2.0

        # Layered sines: the product of two travelling waves gives an
        # irregular, music-like envelope; the slow third wave swells whole
        # regions in and out so it never reads as a repeating texture.
        i = np.arange(n, dtype=np.float64)
        t = self._phase
        amp = 0.55 + 0.45 * np.sin(0.35 * i - 2.1 * t) * np.sin(0.13 * i + 1.3 * t)
        amp *= 0.60 + 0.40 * np.sin(0.021 * i - 0.7 * t)
        heights = np.maximum(amp, 0.06) * half

        painter = QPainter(self)
        done_cols = int(self._fraction * n)

        bright = QColor(self._color)
        dim = QColor(self._color)
        dim.setAlpha(80)

        pen = QPen()
        pen.setWidth(2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        for color, start, end in ((bright, 0, done_cols), (dim, done_cols, n)):
            pen.setColor(color)
            painter.setPen(pen)
            for col in range(start, end):
                x = col * _BAR_STEP + 1
                hh = heights[col]
                painter.drawLine(x, int(mid - hh), x, int(mid + hh))
        painter.end()
