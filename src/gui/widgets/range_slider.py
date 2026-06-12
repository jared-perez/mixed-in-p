"""Custom dual-handle range slider widget for selecting start/end positions."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QMouseEvent, QPainter, QPen, QColor
from PySide6.QtWidgets import QWidget

from ..styles.theme import Theme


class RangeSlider(QWidget):
    """A dual-handle range slider with neon-yellow fill between handles.

    Handles are thin vertical lines with "start"/"end" text labels that track
    with their respective handles.
    """

    startValueChanged = Signal(int)
    endValueChanged = Signal(int)

    _GROOVE_HEIGHT = 6
    _HANDLE_WIDTH = 2
    _HANDLE_HEIGHT = 20
    _MARGIN_X = 12  # horizontal padding so handles aren't clipped at edges
    _GROOVE_COLOR = QColor(Theme.BG_MEDIUM)
    _GROOVE_BORDER = QColor(Theme.BG_LIGHT)
    _FILL_COLOR = QColor(Theme.NEON_YELLOW)
    _HANDLE_COLOR = QColor(Theme.CHROME)
    _HANDLE_HOVER = QColor(Theme.NEON_YELLOW)
    _LABEL_COLOR = QColor(Theme.TEXT_SECONDARY)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._min_val = 0
        self._max_val = 0
        self._start_val = 0
        self._end_val = 0
        self._dragging: str | None = None  # "start", "end", or None
        self._hover_handle: str | None = None

        self._label_font = QFont()
        self._label_font.setPixelSize(11)

        self.setFixedHeight(60)
        self.setMouseTracking(True)
        self.setSizePolicy(
            self.sizePolicy().horizontalPolicy().Expanding,  # type: ignore[arg-type]
            self.sizePolicy().verticalPolicy().Fixed,  # type: ignore[arg-type]
        )

    # ------------------------------------------------------------------ API

    def setRange(self, min_val: int, max_val: int) -> None:
        self._min_val = min_val
        self._max_val = max(min_val, max_val)
        self._start_val = max(self._start_val, min_val)
        self._end_val = min(self._end_val, self._max_val)
        self.update()

    def setStartValue(self, val: int) -> None:
        val = max(self._min_val, min(val, self._max_val))
        if val != self._start_val:
            self._start_val = val
            self.update()
            self.startValueChanged.emit(val)

    def setEndValue(self, val: int) -> None:
        val = max(self._min_val, min(val, self._max_val))
        if val != self._end_val:
            self._end_val = val
            self.update()
            self.endValueChanged.emit(val)

    def startValue(self) -> int:
        return self._start_val

    def endValue(self) -> int:
        return self._end_val

    # ------------------------------------------------------------------ geometry helpers

    def _track_left(self) -> int:
        return self._MARGIN_X

    def _track_right(self) -> int:
        return self.width() - self._MARGIN_X

    def _track_width(self) -> int:
        return self._track_right() - self._track_left()

    def _val_to_x(self, val: int) -> int:
        rng = self._max_val - self._min_val
        if rng <= 0:
            return self._track_left()
        ratio = (val - self._min_val) / rng
        return int(self._track_left() + ratio * self._track_width())

    def _x_to_val(self, x: int) -> int:
        rng = self._max_val - self._min_val
        if rng <= 0:
            return self._min_val
        ratio = (x - self._track_left()) / self._track_width()
        ratio = max(0.0, min(1.0, ratio))
        return int(self._min_val + ratio * rng)

    def _groove_y(self) -> int:
        """Vertical center of the groove."""
        return self.height() // 2

    # ------------------------------------------------------------------ painting

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        gy = self._groove_y()
        gh = self._GROOVE_HEIGHT
        tl = self._track_left()
        tr = self._track_right()

        # Groove background
        p.setPen(QPen(self._GROOVE_BORDER, 1))
        p.setBrush(self._GROOVE_COLOR)
        p.drawRoundedRect(tl, gy - gh // 2, tr - tl, gh, 3, 3)

        # Filled range
        sx = self._val_to_x(self._start_val)
        ex = self._val_to_x(self._end_val)
        if ex > sx:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._FILL_COLOR)
            p.drawRoundedRect(sx, gy - gh // 2, ex - sx, gh, 3, 3)

        # Handles
        hh = self._HANDLE_HEIGHT
        for handle_name, hx in [("start", sx), ("end", ex)]:
            is_hover = self._hover_handle == handle_name or self._dragging == handle_name
            color = self._HANDLE_HOVER if is_hover else self._HANDLE_COLOR
            p.setPen(QPen(color, self._HANDLE_WIDTH))
            p.drawLine(hx, gy - hh // 2, hx, gy + hh // 2)

        # Labels
        p.setFont(self._label_font)
        fm = QFontMetrics(self._label_font)

        # "start" label — trailing 't' sits above start handle
        start_text = "start"
        start_tw = fm.horizontalAdvance(start_text)
        # Position so the right edge of the text aligns with the handle x
        start_lx = sx - start_tw + fm.horizontalAdvance("t") // 2
        start_ly = gy - hh // 2 - 4
        start_color = self._HANDLE_HOVER if (self._hover_handle == "start" or self._dragging == "start") else self._LABEL_COLOR
        p.setPen(start_color)
        p.drawText(start_lx, start_ly, start_text)

        # "end" label — leading 'e' sits below end handle
        end_text = "end"
        end_lx = ex - fm.horizontalAdvance("e") // 2
        end_ly = gy + hh // 2 + fm.ascent() + 4
        end_color = self._HANDLE_HOVER if (self._hover_handle == "end" or self._dragging == "end") else self._LABEL_COLOR
        p.setPen(end_color)
        p.drawText(end_lx, end_ly, end_text)

        p.end()

    # ------------------------------------------------------------------ mouse interaction

    def _closest_handle(self, x: int) -> str:
        sx = self._val_to_x(self._start_val)
        ex = self._val_to_x(self._end_val)
        ds = abs(x - sx)
        de = abs(x - ex)
        if ds <= de:
            return "start"
        return "end"

    def _handle_hit(self, x: int, threshold: int = 10) -> str | None:
        sx = self._val_to_x(self._start_val)
        ex = self._val_to_x(self._end_val)
        ds = abs(x - sx)
        de = abs(x - ex)
        if ds <= threshold and ds <= de:
            return "start"
        if de <= threshold:
            return "end"
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._handle_hit(int(event.position().x()))
            if handle is None:
                handle = self._closest_handle(int(event.position().x()))
            self._dragging = handle
            self._apply_drag(int(event.position().x()))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging:
            self._apply_drag(int(event.position().x()))
        else:
            old = self._hover_handle
            self._hover_handle = self._handle_hit(int(event.position().x()))
            if old != self._hover_handle:
                self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = None

    def leaveEvent(self, event) -> None:
        if self._hover_handle is not None:
            self._hover_handle = None
            self.update()

    def _apply_drag(self, x: int) -> None:
        val = self._x_to_val(x)
        if self._dragging == "start":
            val = max(self._min_val, min(val, self._end_val - 1))
            if val != self._start_val:
                self._start_val = val
                self.update()
                self.startValueChanged.emit(val)
        elif self._dragging == "end":
            val = max(self._start_val + 1, min(val, self._max_val))
            if val != self._end_val:
                self._end_val = val
                self.update()
                self.endValueChanged.emit(val)
