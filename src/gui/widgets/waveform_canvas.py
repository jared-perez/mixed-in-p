"""Waveform display widget for the player's slice section.

Combines what used to be two separate sliders:
- Start/end slice markers (was: RangeSlider)
- Playback position head (was: QSlider seek)

Exposes a range-slider- and seek-slider-compatible API so the slice section's
handlers can treat it as both. The waveform itself is supplied via set_waveform().
"""

from __future__ import annotations

import numpy as np

from PySide6.QtCore import Qt, QLineF, QPoint, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygon
from PySide6.QtWidgets import QWidget

from ..styles.theme import Theme

# Hit-test tolerance for grabbing markers (pixels)
_MARKER_GRAB_PX = 8


class WaveformCanvas(QWidget):
    """Custom-painted waveform with draggable start/end markers and playhead."""

    # Range-slider-compatible signals
    startValueChanged = Signal(int)  # ms
    endValueChanged = Signal(int)    # ms
    # Seek-slider-compatible signal
    sliderMoved = Signal(int)        # ms — user moved the playhead

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._duration_ms: int = 0
        self._start_ms: int = 0
        self._end_ms: int = 0
        self._position_ms: int = 0
        self._min_arr: np.ndarray | None = None
        self._max_arr: np.ndarray | None = None
        self._dragging: str | None = None  # 'start' | 'end' | 'position'
        self._waveform_color = QColor(Theme.NEON_YELLOW)
        self.setMinimumHeight(160)
        self.setMouseTracking(True)
        # Take focus on click so the parent's keyboard shortcuts work
        # without the user first having to click elsewhere.
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

    # ------------------------------------------------------------------ API

    # Range slider compatibility
    def setRange(self, lo: int, hi: int) -> None:  # noqa: ARG002 (lo always 0 here)
        self._duration_ms = max(0, hi)
        self._start_ms = min(self._start_ms, self._duration_ms)
        self._end_ms = min(self._end_ms, self._duration_ms)
        self.update()

    def setStartValue(self, ms: int) -> None:
        ms = max(0, min(int(ms), self._duration_ms))
        if ms == self._start_ms:
            return
        self._start_ms = ms
        if self._end_ms < self._start_ms:
            self._end_ms = self._start_ms
            self.endValueChanged.emit(self._end_ms)
        self.startValueChanged.emit(self._start_ms)
        self.update()

    def setEndValue(self, ms: int) -> None:
        ms = max(0, min(int(ms), self._duration_ms))
        if ms == self._end_ms:
            return
        self._end_ms = ms
        if self._start_ms > self._end_ms:
            self._start_ms = self._end_ms
            self.startValueChanged.emit(self._start_ms)
        self.endValueChanged.emit(self._end_ms)
        self.update()

    def startValue(self) -> int:
        return self._start_ms

    def endValue(self) -> int:
        return self._end_ms

    # Seek slider compatibility
    def setSliderValue(self, ms: int) -> None:
        ms = max(0, min(int(ms), self._duration_ms))
        if ms == self._position_ms:
            return
        self._position_ms = ms
        self.update()

    def isSliderDown(self) -> bool:
        return self._dragging == "position"

    # Waveform-specific
    def set_waveform(self, min_arr: np.ndarray, max_arr: np.ndarray) -> None:
        """Install downsampled min/max arrays (produced by WaveformWorker)."""
        self._min_arr = min_arr
        self._max_arr = max_arr
        self.update()

    def set_waveform_color(self, color: str) -> None:
        """Set the waveform body color (#RRGGBB). The playhead stays white."""
        c = QColor(color)
        if c.isValid():
            self._waveform_color = c
            self.update()

    def clear(self) -> None:
        self._duration_ms = 0
        self._start_ms = 0
        self._end_ms = 0
        self._position_ms = 0
        self._min_arr = None
        self._max_arr = None
        self._dragging = None
        self.update()

    # ----------------------------------------------------------- coord maps

    def _x_to_ms(self, x: int) -> int:
        w = self.width()
        if w <= 0 or self._duration_ms <= 0:
            return 0
        return int(round(x * self._duration_ms / w))

    def _ms_to_x(self, ms: int) -> int:
        if self._duration_ms <= 0:
            return 0
        return int(round(ms * self.width() / self._duration_ms))

    # ------------------------------------------------------------- painting

    def paintEvent(self, event) -> None:  # noqa: ARG002
        p = QPainter(self)
        try:
            w = self.width()
            h = self.height()

            # Background — the player grey, so the full waveform blends into the
            # player area above the dark slice tray.
            p.fillRect(0, 0, w, h, QColor(Theme.BG_MEDIUM))

            if self._duration_ms <= 0:
                return

            # Selection band between start and end
            sx = self._ms_to_x(self._start_ms)
            ex = self._ms_to_x(self._end_ms)
            if ex > sx:
                band = QColor(Theme.NEON_YELLOW)
                band.setAlpha(32)
                p.fillRect(sx, 0, ex - sx, h, band)

            # Waveform (filled, neon yellow)
            if self._min_arr is not None and self._max_arr is not None and len(self._min_arr):
                self._draw_waveform(p, w, h)

            # Center axis line
            p.setPen(QPen(QColor(Theme.WAVE_AXIS), 1))
            p.drawLine(0, h // 2, w, h // 2)

            # Markers
            self._draw_marker(p, sx, h, QColor(Theme.NEON_GREEN), "S")
            self._draw_marker(p, ex, h, QColor(Theme.ERROR), "E")

            # Playhead
            px = self._ms_to_x(self._position_ms)
            p.setPen(QPen(QColor(Theme.PLAYHEAD), 2))
            p.drawLine(px, 0, px, h)
        finally:
            p.end()

    def _draw_waveform(self, p: QPainter, w: int, h: int) -> None:
        n = len(self._min_arr)
        mid = h / 2
        amp = (h - 4) / 2  # leave 2px padding top/bottom
        pen = QPen(self._waveform_color, 1)
        p.setPen(pen)
        for x in range(w):
            bin_idx = min(int(x * n / w), n - 1)
            y_top = int(mid - self._max_arr[bin_idx] * amp)
            y_bot = int(mid - self._min_arr[bin_idx] * amp)
            p.drawLine(x, y_top, x, y_bot)

    @staticmethod
    def _draw_marker(p: QPainter, x: int, h: int, color: QColor, _letter: str) -> None:
        p.setPen(QPen(color, 2))
        p.drawLine(x, 0, x, h)
        # Small flag at the top
        p.setBrush(color)
        p.drawRect(x - 5, 0, 10, 6)
        # Upward-pointing triangle at the bottom for clearer feedback — the
        # top flag is easy to miss, so anchor a second cue at the line's base.
        p.drawPolygon(
            QPolygon([
                QPoint(x, h - 7),       # apex (points up)
                QPoint(x - 5, h - 1),   # base left
                QPoint(x + 5, h - 1),   # base right
            ])
        )

    # --------------------------------------------------------------- mouse

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._duration_ms <= 0:
            return
        x = int(event.position().x())
        sx = self._ms_to_x(self._start_ms)
        ex = self._ms_to_x(self._end_ms)
        # If start and end overlap, prefer whichever is closer; default to end.
        if abs(x - sx) <= _MARKER_GRAB_PX and abs(x - sx) <= abs(x - ex):
            self._dragging = "start"
        elif abs(x - ex) <= _MARKER_GRAB_PX:
            self._dragging = "end"
        else:
            self._dragging = "position"
            self._position_ms = max(0, min(self._x_to_ms(x), self._duration_ms))
            self.sliderMoved.emit(self._position_ms)
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._dragging is None or self._duration_ms <= 0:
            return
        ms = max(0, min(self._x_to_ms(int(event.position().x())), self._duration_ms))
        if self._dragging == "start":
            if ms >= self._end_ms:
                ms = max(0, self._end_ms - 1)
            if ms != self._start_ms:
                self._start_ms = ms
                self.startValueChanged.emit(ms)
        elif self._dragging == "end":
            if ms <= self._start_ms:
                ms = min(self._duration_ms, self._start_ms + 1)
            if ms != self._end_ms:
                self._end_ms = ms
                self.endValueChanged.emit(ms)
        else:  # position
            if ms != self._position_ms:
                self._position_ms = ms
                self.sliderMoved.emit(ms)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._dragging = None
        self.update()


class ZoomedWaveformCanvas(QWidget):
    """Centred ±500 ms scrubber view over the high-resolution detail waveform.

    The playhead is fixed at the centre of the widget; audio scrolls under it
    as ``setPosition`` advances. Click + drag emits ``sliderMoved`` so the
    slice panel can drive ``QMediaPlayer.setPosition``, but only while the
    track is paused/stopped (see ``set_scrub_enabled``).
    """

    sliderMoved = Signal(int)  # ms — user dragged the playhead

    WINDOW_MS = 1000  # total visible span

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._duration_ms: int = 0
        self._position_ms: int = 0
        self._start_ms: int = 0
        self._end_ms: int = 0
        self._min_arr: np.ndarray | None = None
        self._max_arr: np.ndarray | None = None
        self._bins_per_sec: float = 0.0
        self._scrub_enabled: bool = True
        self._dragging: bool = False
        # Anchor captured on mousedown so dragging shifts the playhead by the
        # cursor delta instead of jumping to the click point.
        self._drag_anchor_x: int = 0
        self._drag_anchor_position_ms: int = 0
        self._drag_ms_per_px: float = 0.0
        self.setMinimumHeight(120)
        self.setMouseTracking(True)

    # ------------------------------------------------------------------ API

    def set_waveform(self, min_arr: np.ndarray, max_arr: np.ndarray, bins_per_sec: float) -> None:
        self._min_arr = min_arr
        self._max_arr = max_arr
        self._bins_per_sec = float(bins_per_sec)
        self.update()

    def setRange(self, lo: int, hi: int) -> None:  # noqa: ARG002 (lo always 0)
        self._duration_ms = max(0, hi)
        self._position_ms = min(self._position_ms, self._duration_ms)
        self.update()

    def setPosition(self, ms: int) -> None:
        ms = max(0, min(int(ms), self._duration_ms))
        if ms == self._position_ms:
            return
        self._position_ms = ms
        self.update()

    def setStartValue(self, ms: int) -> None:
        self._start_ms = max(0, min(int(ms), self._duration_ms))
        self.update()

    def setEndValue(self, ms: int) -> None:
        self._end_ms = max(0, min(int(ms), self._duration_ms))
        self.update()

    def set_scrub_enabled(self, enabled: bool) -> None:
        self._scrub_enabled = bool(enabled)
        if not enabled:
            self._dragging = False

    def clear(self) -> None:
        self._duration_ms = 0
        self._position_ms = 0
        self._start_ms = 0
        self._end_ms = 0
        self._min_arr = None
        self._max_arr = None
        self._bins_per_sec = 0.0
        self._dragging = False
        self.update()

    # ------------------------------------------------------- coord helpers

    def _visible_window_ms(self) -> tuple[int, int]:
        """Visible window [start, end] in ms, clamped to track bounds.

        Within the body of the track the window stays centred on the
        playhead. Near the edges the window stops at 0 / duration and the
        playhead slides off-centre instead of leaving the canvas blank.
        """
        half = self.WINDOW_MS // 2
        view_start = self._position_ms - half
        view_end = self._position_ms + half
        if view_start < 0:
            view_end -= view_start
            view_start = 0
        if view_end > self._duration_ms:
            shift = view_end - self._duration_ms
            view_start = max(0, view_start - shift)
            view_end = self._duration_ms
        return view_start, view_end

    def _ms_to_x(self, ms: int) -> int:
        view_start, view_end = self._visible_window_ms()
        span = max(1, view_end - view_start)
        return int(round((ms - view_start) * self.width() / span))

    def _x_to_ms(self, x: int) -> int:
        view_start, view_end = self._visible_window_ms()
        span = max(1, view_end - view_start)
        w = max(1, self.width())
        return view_start + int(round(x * span / w))

    # ------------------------------------------------------------- paint

    def paintEvent(self, event) -> None:  # noqa: ARG002
        p = QPainter(self)
        try:
            w = self.width()
            h = self.height()
            p.fillRect(0, 0, w, h, QColor(Theme.TRAY_BG))

            if self._duration_ms <= 0:
                return

            view_start, view_end = self._visible_window_ms()

            if (
                self._min_arr is not None
                and self._max_arr is not None
                and len(self._min_arr)
                and self._bins_per_sec > 0
            ):
                self._draw_waveform(p, w, h, view_start, view_end)

            # Centre axis line
            p.setPen(QPen(QColor(Theme.WAVE_AXIS), 1))
            p.drawLine(0, h // 2, w, h // 2)

            # Start / end markers (when in view)
            if view_start <= self._start_ms <= view_end:
                sx = self._ms_to_x(self._start_ms)
                p.setPen(QPen(QColor(Theme.NEON_GREEN), 2))
                p.drawLine(sx, 0, sx, h)
            if view_start <= self._end_ms <= view_end:
                ex = self._ms_to_x(self._end_ms)
                p.setPen(QPen(QColor(Theme.ERROR), 2))
                p.drawLine(ex, 0, ex, h)

            # Playhead
            px = self._ms_to_x(self._position_ms)
            p.setPen(QPen(QColor(Theme.NEON_YELLOW), 2))
            p.drawLine(px, 0, px, h)
        finally:
            p.end()

    def _draw_waveform(
        self,
        p: QPainter,
        w: int,
        h: int,
        view_start_ms: int,
        view_end_ms: int,
    ) -> None:
        mid = h / 2
        amp = (h - 4) / 2  # 2 px padding top/bottom
        n = len(self._min_arr)
        bins_per_ms = self._bins_per_sec / 1000.0
        start_bin = max(0, int(view_start_ms * bins_per_ms))
        end_bin = min(n, int(view_end_ms * bins_per_ms))
        visible_bins = end_bin - start_bin
        if visible_bins <= 0:
            return

        # Render at physical-pixel resolution so the waveform stays crisp on
        # high-DPI (Retina) displays rather than being drawn at logical width
        # and upscaled by the backing store.
        dpr = self.devicePixelRatioF()
        cols = max(1, int(round(w * dpr)))

        # min/max-decimate each column's bin span (vectorised) so transient
        # peaks survive instead of being point-sampled away. reduceat reduces
        # over [starts[i], starts[i+1]); the final group runs to the slice end.
        sl_min = self._min_arr[start_bin:end_bin]
        sl_max = self._max_arr[start_bin:end_bin]
        starts = (np.arange(cols, dtype=np.int64) * visible_bins) // cols
        np.clip(starts, 0, visible_bins - 1, out=starts)
        seg_max = np.maximum.reduceat(sl_max, starts)
        seg_min = np.minimum.reduceat(sl_min, starts)

        y_top = mid - seg_max * amp
        y_bot = mid - seg_min * amp
        xs = np.arange(cols) / dpr

        pen = QPen(QColor(Theme.NEON_YELLOW))
        pen.setCosmetic(True)  # 1 physical pixel wide regardless of DPI
        p.setPen(pen)
        p.drawLines([QLineF(x, t, x, b) for x, t, b in zip(xs, y_top, y_bot)])

    # ------------------------------------------------------------- mouse

    def mousePressEvent(self, event) -> None:
        if not self._scrub_enabled or event.button() != Qt.MouseButton.LeftButton:
            return
        if self._duration_ms <= 0:
            return
        # Capture an anchor: where the cursor landed, where the playhead is
        # right now, and the current ms-per-pixel ratio. Don't seek — the
        # click alone shouldn't move playback (no "jump on click").
        view_start, view_end = self._visible_window_ms()
        self._drag_anchor_x = int(event.position().x())
        self._drag_anchor_position_ms = self._position_ms
        self._drag_ms_per_px = (view_end - view_start) / max(1, self.width())
        self._dragging = True

    def mouseMoveEvent(self, event) -> None:
        if not self._scrub_enabled or not self._dragging or self._duration_ms <= 0:
            return
        # Cursor moves right → waveform pulled right → playhead shows earlier
        # audio → position decreases. Hence the minus sign.
        delta_x = int(event.position().x()) - self._drag_anchor_x
        delta_ms = delta_x * self._drag_ms_per_px
        new_pos = self._drag_anchor_position_ms - int(round(delta_ms))
        new_pos = max(0, min(new_pos, self._duration_ms))
        self.sliderMoved.emit(new_pos)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._dragging = False
