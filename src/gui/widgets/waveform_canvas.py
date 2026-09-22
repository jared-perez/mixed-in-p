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
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap, QPolygon
from PySide6.QtWidgets import QWidget

from ..styles.theme import Theme
from ..waveform_palette import core_shading

# Hit-test tolerance for grabbing markers (pixels)
_MARKER_GRAB_PX = 8

# Minimum heights of the two canvases in full (mirrored) view. Half view draws
# only the upper envelope, so it keeps the same peak height in half the room.
_FULL_MIN_HEIGHT = 160
_ZOOM_FULL_MIN_HEIGHT = 120


def _half_envelope(min_arr: np.ndarray, max_arr: np.ndarray) -> np.ndarray:
    """Peak magnitude per bin, for half view: the louder of the two halves.

    Taking only ``max`` would drop a transient that swings negative first.
    """
    return np.maximum(np.maximum(max_arr, -min_arr), 0.0)


def _usable_colors(colors: np.ndarray | None, n: int) -> np.ndarray | None:
    """*colors* if it is one RGB row per waveform column, else None (solid)."""
    if colors is None or len(colors) != n:
        return None
    return colors


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
        # Per-column RGB (N, 3) uint8 from waveform_palette, or None for solid.
        self._column_colors: np.ndarray | None = None
        # Bright at the axis, darker toward each column's tip (the shaded
        # frequency palette's look; see waveform_palette.core_shading).
        self._core_shading: bool = False
        self._half: bool = False
        # The waveform body, rendered once and blitted on every position tick.
        # Rebuilt when its key (size, dpr) goes stale or an input changes.
        self._cache: QPixmap | None = None
        self._cache_key: tuple | None = None
        self.setMinimumHeight(_FULL_MIN_HEIGHT)
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
        self._invalidate()

    def set_waveform_color(self, color: str) -> None:
        """Set the waveform body color (#RRGGBB). The playhead stays white."""
        c = QColor(color)
        if c.isValid():
            self._waveform_color = c
            self._invalidate()

    def set_column_colors(self, colors: np.ndarray | None) -> None:
        """Colour each waveform column: ``(N, 3)`` uint8 RGB aligned with the
        min/max arrays, or None to draw the whole body in the waveform color."""
        self._column_colors = colors
        self._invalidate()

    def set_core_shading(self, on: bool) -> None:
        """Shade each column from bright at the axis to darker at its tip."""
        on = bool(on)
        if on != self._core_shading:
            self._core_shading = on
            self._invalidate()

    def set_half(self, half: bool) -> None:
        """Draw only the top half (from Settings), in half the height."""
        half = bool(half)
        if half == self._half:
            return
        self._half = half
        self.setMinimumHeight(_FULL_MIN_HEIGHT // 2 if half else _FULL_MIN_HEIGHT)
        self.updateGeometry()
        self._invalidate()

    def is_half(self) -> bool:
        return self._half

    def clear(self) -> None:
        self._duration_ms = 0
        self._start_ms = 0
        self._end_ms = 0
        self._position_ms = 0
        self._min_arr = None
        self._max_arr = None
        self._column_colors = None
        self._core_shading = False
        self._dragging = None
        self._invalidate()

    def _invalidate(self) -> None:
        self._cache = None
        self._cache_key = None
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

            # Waveform body, from the cache
            if self._min_arr is not None and self._max_arr is not None and len(self._min_arr):
                dpr = self.devicePixelRatioF()
                key = (w, h, dpr)
                if self._cache is None or self._cache_key != key:
                    self._cache = self._render_waveform(w, h, dpr)
                    self._cache_key = key
                p.drawPixmap(0, 0, self._cache)

            # Axis line: the centre, or the baseline in half view
            axis_y = h - 1 if self._half else h // 2
            p.setPen(QPen(QColor(Theme.WAVE_AXIS), 1))
            p.drawLine(0, axis_y, w, axis_y)

            # Markers
            self._draw_marker(p, sx, h, QColor(Theme.NEON_GREEN), "S")
            self._draw_marker(p, ex, h, QColor(Theme.ERROR), "E")

            # Playhead
            px = self._ms_to_x(self._position_ms)
            p.setPen(QPen(QColor(Theme.PLAYHEAD), 2))
            p.drawLine(px, 0, px, h)
        finally:
            p.end()

    def _render_waveform(self, w: int, h: int, dpr: float) -> QPixmap:
        """The waveform body as a transparent pixmap at physical resolution.

        Built with numpy rather than a drawLine per column: the canvas repaints
        on every position tick, and a blit is ~11x cheaper than the loop (and
        per-column colour would otherwise mean a setPen per column).
        """
        pw = max(1, int(round(w * dpr)))
        ph = max(1, int(round(h * dpr)))
        n = len(self._min_arr)
        # Max/min over each physical column's bins, so a narrow canvas keeps
        # its transients; a wide one repeats bins. reduceat reduces over
        # [starts[i], starts[i+1]) and returns a[starts[i]] for equal starts.
        starts = np.minimum((np.arange(pw, dtype=np.int64) * n) // pw, n - 1)
        seg_max = np.maximum.reduceat(self._max_arr, starts)
        seg_min = np.minimum.reduceat(self._min_arr, starts)

        # Geometry in logical pixels, as the old per-line painter drew it.
        if self._half:
            # Rise from a baseline at the bottom edge (2px padding at the top).
            y_bot = np.full(pw, h - 1.0)
            y_top = y_bot - _half_envelope(seg_min, seg_max) * (h - 3)
        else:
            mid = h / 2
            amp = (h - 4) / 2  # leave 2px padding top/bottom
            y_top = mid - seg_max * amp
            y_bot = mid - seg_min * amp
        # A logical row covers dpr physical rows; fill all of the bottom one.
        top = np.clip(np.floor(y_top.astype(np.int64) * dpr), 0, ph - 1).astype(np.int64)
        bot = np.floor((y_bot.astype(np.int64) + 1) * dpr) - 1
        bot = np.clip(np.maximum(bot, top), 0, ph - 1).astype(np.int64)
        rows = np.arange(ph)[:, None]
        mask = (rows >= top[None, :]) & (rows <= bot[None, :])
        shade = None
        if self._core_shading:
            # Distance from the axis as a fraction of that side's own reach,
            # so a lopsided column still peaks at the axis and dims at each tip.
            axis = ph - 1 if self._half else int(round(h / 2 * dpr))
            up = np.maximum(axis - top, 1)[None, :]
            down = np.maximum(bot - axis, 1)[None, :]
            dist = np.where(rows < axis, (axis - rows) / up, (rows - axis) / down)
            shade = core_shading(dist)[..., None]

        colors = _usable_colors(self._column_colors, n)
        if colors is None:
            c = self._waveform_color
            rgb = np.broadcast_to(
                np.array([c.red(), c.green(), c.blue()], dtype=np.uint8), (pw, 3)
            )
        else:
            rgb = colors[starts]
        body = np.broadcast_to(rgb[None, :, :], (ph, pw, 3))
        if shade is not None:
            body = np.rint(body * shade).astype(np.uint8)
        # Format_ARGB32 is B, G, R, A in memory on every platform Qt ships on.
        buf = np.zeros((ph, pw, 4), dtype=np.uint8)
        buf[..., 0] = np.where(mask, body[..., 2], 0)
        buf[..., 1] = np.where(mask, body[..., 1], 0)
        buf[..., 2] = np.where(mask, body[..., 0], 0)
        buf[..., 3] = np.where(mask, 255, 0)
        image = QImage(buf.data, pw, ph, pw * 4, QImage.Format.Format_ARGB32).copy()
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(dpr)
        return pixmap

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
        self._half: bool = False
        self._waveform_color = QColor(Theme.NEON_YELLOW)
        # The overview's per-column RGB (see WaveformCanvas.set_column_colors),
        # sampled by time: colour is necessarily far coarser than this view's
        # shape (a band needs a ~23 ms window to see bass), and reusing the
        # overview's costs nothing at load.
        self._column_colors: np.ndarray | None = None
        self.setMinimumHeight(_ZOOM_FULL_MIN_HEIGHT)
        self.setMouseTracking(True)

    # ------------------------------------------------------------------ API

    def set_waveform(self, min_arr: np.ndarray, max_arr: np.ndarray, bins_per_sec: float) -> None:
        self._min_arr = min_arr
        self._max_arr = max_arr
        self._bins_per_sec = float(bins_per_sec)
        self.update()

    def set_waveform_color(self, color: str) -> None:
        """Set the waveform body color (#RRGGBB) used where there are no column colours."""
        c = QColor(color)
        if c.isValid():
            self._waveform_color = c
            self.update()

    def set_column_colors(self, colors: np.ndarray | None) -> None:
        """The overview's per-column RGB, spread over the whole track, or None for solid."""
        self._column_colors = colors
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

    def set_half(self, half: bool) -> None:
        """Draw only the top half (from Settings), in half the height."""
        half = bool(half)
        if half == self._half:
            return
        self._half = half
        self.setMinimumHeight(
            _ZOOM_FULL_MIN_HEIGHT // 2 if half else _ZOOM_FULL_MIN_HEIGHT
        )
        self.updateGeometry()
        self.update()

    def is_half(self) -> bool:
        return self._half

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
        self._column_colors = None
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

            # Axis line: the centre, or the baseline in half view
            axis_y = h - 1 if self._half else h // 2
            p.setPen(QPen(QColor(Theme.WAVE_AXIS), 1))
            p.drawLine(0, axis_y, w, axis_y)

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

        if self._half:
            # Rise from a baseline at the bottom edge (2px padding at the top).
            y_bot = np.full(cols, h - 1.0)
            y_top = y_bot - _half_envelope(seg_min, seg_max) * (h - 3)
        else:
            mid = h / 2
            amp = (h - 4) / 2  # 2 px padding top/bottom
            y_top = mid - seg_max * amp
            y_bot = mid - seg_min * amp
        xs = np.arange(cols) / dpr

        pen = QPen(self._waveform_color)
        pen.setCosmetic(True)  # 1 physical pixel wide regardless of DPI
        colors = self._column_colors
        if colors is None or not len(colors) or self._duration_ms <= 0:
            p.setPen(pen)
            p.drawLines([QLineF(x, t, x, b) for x, t, b in zip(xs, y_top, y_bot)])
            return
        # Each physical column takes the colour of the overview column its
        # time falls in. Only ~20 distinct ones cross a 1 s window, so draw one
        # run of same-coloured lines per setPen, never a setPen per column.
        n_colors = len(colors)
        ms = (start_bin + starts) / bins_per_ms
        idx = np.clip((ms * n_colors / self._duration_ms).astype(np.int64), 0, n_colors - 1)
        breaks = np.flatnonzero(np.diff(idx)) + 1
        bounds = np.concatenate(([0], breaks, [cols]))
        for a, b in zip(bounds[:-1], bounds[1:]):
            r, g, bl = colors[idx[a]]
            pen.setColor(QColor(int(r), int(g), int(bl)))
            p.setPen(pen)
            p.drawLines([
                QLineF(x, t, x, bt)
                for x, t, bt in zip(xs[a:b], y_top[a:b], y_bot[a:b])
            ])

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
