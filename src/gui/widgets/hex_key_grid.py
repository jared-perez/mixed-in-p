"""Hex key grid — harmonic key reference as a honeycomb of 12 hexagons.

Mirrors ``LinearKeyStrip``'s contract: exposes ``segment_pressed`` /
``segment_released`` signals carrying the key-code number 1-12, and
``add_highlight`` / ``remove_highlight`` / ``clear_highlights`` taking codes like
``"5A"`` / ``"8B"`` so ``KeyboardPanel`` drives it in lockstep with the strip.

While a chord is held the matching hexagon lights up, harmonically compatible
neighbours (same number, +/-1) glow, and the rest dim — the "reveal" effect from
harmonic-grid.jsx VIEW 1. Shares ``STRIP_KEYS`` (the neon-yellow gradient palette)
and ``_compatible_numbers`` with the linear strip.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from src.analysis.keycode import keycode_to_open_key

from ..styles.theme import Theme
from .linear_key_strip import STRIP_KEYS, _compatible_numbers

# Honeycomb geometry (pointy-top hexes, 4 columns x 3 rows, odd rows offset).
COLS = 4
ROWS = 3
HEX_W = 135
HEX_H = 120
HEX_R = 57
MARGIN = 18

# The honeycomb is laid out at this natural size, then uniformly scaled (painter
# + hit-testing) so the whole grid fits within 552 x 342 keeping its proportions.
_NATURAL_W = COLS * HEX_W + HEX_W * 0.5 + 2 * MARGIN
_NATURAL_H = MARGIN + HEX_R + (ROWS - 1) * HEX_H * 0.87 + HEX_R + 4
_SCALE = min(552 / _NATURAL_W, 342 / _NATURAL_H)

BASE_FILL = QColor(Theme.BG_MEDIUM)
BASE_STROKE = QColor("#444444")


def _blend(a: QColor, b: QColor, t: float) -> QColor:
    """Linear RGB blend: a at t=0, b at t=1."""
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    )


# Non-compatible keys dim while a chord is held. These are the *fully* dimmed
# target colors; the grid only dims DIM_STRENGTH of the way toward them from the
# undimmed appearance, so the unlit keys stay more legible. 1.0 = full dim,
# 0.5 = half as dim.
DIM_STRENGTH = 0.5
_FULL_DIM_FILL = QColor("#222230")
_FULL_DIM_STROKE = QColor("#2a2a3a")
_FULL_DIM_NUM = QColor("#444444")
_FULL_DIM_LABEL = QColor("#3a3a3a")

DIM_FILL = _blend(BASE_FILL, _FULL_DIM_FILL, DIM_STRENGTH)
DIM_STROKE = _blend(BASE_STROKE, _FULL_DIM_STROKE, DIM_STRENGTH)
DIM_NUM = _blend(QColor(Theme.TEXT_PRIMARY), _FULL_DIM_NUM, DIM_STRENGTH)
DIM_MINOR = _blend(QColor(Theme.TEXT_PRIMARY), _FULL_DIM_LABEL, DIM_STRENGTH)
DIM_MAJOR = _blend(QColor(Theme.TEXT_SECONDARY), _FULL_DIM_LABEL, DIM_STRENGTH)


class HexKeyGrid(QWidget):
    """Canvas widget drawing the 12 key codes as a hex honeycomb."""

    # Emitted when the user presses / releases a hexagon.
    # Payload is the segment number 1-12 (caller decides A vs B from master mode).
    segment_pressed = Signal(int)
    segment_released = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._highlighted: set[str] = set()  # e.g. {"5A", "8B"}
        self._mouse_segment: int | None = None
        self._notation = "keycode"

        # Precompute each hexagon's polygon + center, indexed alongside STRIP_KEYS.
        self._hexes: list[tuple[int, QPolygonF, QPointF]] = []
        for i, (num, _minor, _major, _color) in enumerate(STRIP_KEYS):
            col = i % COLS
            row = i // COLS
            offset = 0.0 if row % 2 == 0 else HEX_W * 0.5
            cx = MARGIN + HEX_R + col * HEX_W + offset
            cy = MARGIN + HEX_R + row * HEX_H * 0.87
            self._hexes.append((num, self._hex_polygon(cx, cy, HEX_R), QPointF(cx, cy)))

        # Natural layout is _NATURAL_W x _NATURAL_H; the widget (and everything
        # painted in it) is uniformly scaled down by _SCALE to fit the panel.
        self.setFixedSize(int(_NATURAL_W * _SCALE), int(_NATURAL_H * _SCALE))

    @staticmethod
    def _hex_polygon(cx: float, cy: float, r: float) -> QPolygonF:
        """Pointy-top hexagon: 6 vertices at 60*i - 30 degrees."""
        poly = QPolygonF()
        for i in range(6):
            a = math.radians(60 * i - 30)
            poly.append(QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))
        return poly

    # --- Notation ---

    def set_key_notation(self, notation: str) -> None:
        """Set the notation that drives the 1-12 number labels."""
        if notation == self._notation:
            return
        self._notation = notation
        self.update()

    def _num_label(self, num: int) -> str:
        """Number label for a key-code number in the current notation.

        Open Key renumbers the keys (key code 8 -> Open Key 1); traditional and
        key-code notation both keep the original key-code number.
        """
        if self._notation == "open_key":
            return keycode_to_open_key(f"{num}A")[:-1]
        return str(num)

    # --- Highlight API (matches LinearKeyStrip) ---

    def add_highlight(self, code: str) -> None:
        if not code or code in self._highlighted:
            return
        self._highlighted.add(code)
        self.update()

    def remove_highlight(self, code: str) -> None:
        if code not in self._highlighted:
            return
        self._highlighted.discard(code)
        self.update()

    def clear_highlights(self) -> None:
        if not self._highlighted:
            return
        self._highlighted.clear()
        self.update()

    # --- State helpers ---

    def _held_numbers(self) -> set[int]:
        return {int(code[:-1]) for code in self._highlighted}

    # --- Mouse events ---

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        # Map the click back into natural coordinates to hit-test the polygons.
        pos = event.position() / _SCALE
        for num, poly, _center in self._hexes:
            if poly.containsPoint(pos, Qt.FillRule.OddEvenFill):
                self._mouse_segment = num
                self.segment_pressed.emit(num)
                return

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        num = self._mouse_segment
        self._mouse_segment = None
        if num is not None:
            self.segment_released.emit(num)

    # --- Painting ---

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Draw in natural coordinates; the scale shrinks it to the widget size.
        painter.scale(_SCALE, _SCALE)

        held = self._held_numbers()
        compat: set[int] = set()
        for n in held:
            compat |= _compatible_numbers(n)

        num_font = QFont("Menlo", 16)
        num_font.setBold(True)
        key_font = QFont("Menlo", 13)

        for i, (num, minor, major, color_hex) in enumerate(STRIP_KEYS):
            _n, poly, center = self._hexes[i]
            color = QColor(color_hex)

            is_held = num in held
            is_compat = num in compat and not is_held
            is_dimmed = bool(held) and num not in compat

            # Fill + stroke per state.
            if is_held:
                fill = QColor(color)
                stroke = QPen(QColor(Theme.TEXT_PRIMARY), 2.5)
            elif is_compat:
                fill = QColor(color)
                fill.setAlpha(0x99)
                stroke = QPen(color, 1.5)
            elif is_dimmed:
                fill = QColor(DIM_FILL)
                stroke = QPen(DIM_STROKE, 1.5)
            else:
                fill = QColor(BASE_FILL)
                stroke = QPen(QColor("#444444"), 1.5)

            painter.setBrush(fill)
            painter.setPen(stroke)
            painter.drawPolygon(poly)

            # Text colors: muted when dimmed, key color (number) when held.
            if is_dimmed:
                num_color = QColor(DIM_NUM)
                minor_color = QColor(DIM_MINOR)
                major_color = QColor(DIM_MAJOR)
            else:
                num_color = QColor(color_hex) if is_held else QColor(Theme.TEXT_PRIMARY)
                minor_color = QColor(Theme.TEXT_PRIMARY)
                major_color = QColor(Theme.TEXT_SECONDARY)

            cx = center.x()
            cy = center.y()

            painter.setFont(num_font)
            painter.setPen(num_color)
            painter.drawText(
                int(cx - HEX_R), int(cy - 33), int(HEX_R * 2), 24,
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                self._num_label(num),
            )

            painter.setFont(key_font)
            painter.setPen(minor_color)
            painter.drawText(
                int(cx - HEX_R), int(cy - 6), int(HEX_R * 2), 21,
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                minor,
            )
            painter.setPen(major_color)
            painter.drawText(
                int(cx - HEX_R), int(cy + 15), int(HEX_R * 2), 21,
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                major,
            )

        painter.end()
