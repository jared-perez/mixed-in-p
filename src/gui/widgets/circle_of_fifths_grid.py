"""Circle of Fifths — harmonic key reference as a wheel of 24 circles.

Mirrors ``HexKeyGrid`` / ``LinearKeyStrip``'s contract: exposes
``segment_pressed`` / ``segment_released`` signals carrying the key-code number
1-12, and ``add_highlight`` / ``remove_highlight`` / ``clear_highlights`` taking
codes like ``"5A"`` / ``"8B"`` so ``KeyboardPanel`` drives it in lockstep with
the other references.

The wheel is two concentric rings of 12 small circles: the OUTER ring is the
minor scale (``NA`` codes), the INNER ring is the major scale (``NB`` codes),
with 12A at the top (12 o'clock) and the numbers winding clockwise ascending
(12 → 1 → 2 → … → 11) — each clockwise step is a perfect fifth up. Radially
aligned circles share a number, so the top spoke is 12A (outer) over 12B
(inner), its relative major.

While a chord is held the matching circle lights up, harmonically compatible
neighbours (same number, +/-1) glow, and the rest dim — the same "reveal"
effect as the hex grid. Shares ``STRIP_KEYS`` (the neon-yellow gradient palette)
and ``_compatible_numbers`` with the linear strip.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from src.analysis.keycode import keycode_to_open_key

from ..styles.theme import Theme
from .linear_key_strip import STRIP_KEYS, _compatible_numbers

# Wheel geometry: two rings of 12 circles around a shared centre. With 12 per
# ring, adjacent centres sit 2·R·sin(15°) ≈ 0.518·R apart, so a ring's radius
# must exceed ~3.86·(circle radius) for its circles not to overlap. The outer
# (minor) circles are a bit larger, and the outer ring sits just clear of the
# inner one (a small gap = R_OUTER − R_INNER − OUTER_CIRCLE_R − INNER_CIRCLE_R).
INNER_CIRCLE_R = 26  # radius of each inner (major) circle
OUTER_CIRCLE_R = 32  # radius of each outer (minor) circle — a touch larger
R_INNER = 110        # centre-to-centre radius of the inner (major) ring
R_OUTER = 174        # centre-to-centre radius of the outer (minor) ring (~6px gap)
PAD = 6              # margin between the outermost circles and the widget edge

_SIZE = 2 * (R_OUTER + OUTER_CIRCLE_R) + 2 * PAD

BASE_FILL = QColor(Theme.BG_MEDIUM)
BASE_STROKE = QColor("#444444")


def _blend(a: QColor, b: QColor, t: float) -> QColor:
    """Linear RGB blend: a at t=0, b at t=1."""
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    )


# Non-compatible circles dim while a chord is held. Matches the hex grid: only
# dim DIM_STRENGTH of the way toward the fully-dimmed colors so unlit circles
# stay legible.
DIM_STRENGTH = 0.5
_FULL_DIM_FILL = QColor("#222230")
_FULL_DIM_STROKE = QColor("#2a2a3a")
_FULL_DIM_TEXT = QColor("#3a3a3a")

DIM_FILL = _blend(BASE_FILL, _FULL_DIM_FILL, DIM_STRENGTH)
DIM_STROKE = _blend(BASE_STROKE, _FULL_DIM_STROKE, DIM_STRENGTH)
DIM_TEXT = _blend(QColor(Theme.TEXT_PRIMARY), _FULL_DIM_TEXT, DIM_STRENGTH)


class CircleOfFifthsGrid(QWidget):
    """Canvas widget drawing the 12 key codes as a circle-of-fifths wheel."""

    # Emitted when the user presses / releases a circle.
    # Payload is the segment number 1-12 (caller decides A vs B from master mode).
    segment_pressed = Signal(int)
    segment_released = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._highlighted: set[str] = set()  # e.g. {"5A", "8B"}
        self._mouse_segment: int | None = None
        self._notation = "keycode"

        # Precompute every circle: (num, code, minor/major label, color, center,
        # circle_radius), indexed by position. 12A sits at the top; numbers wind
        # clockwise ascending.
        cx = cy = _SIZE / 2
        self._circles: list[tuple[int, str, str, str, QPointF, int]] = []
        for p in range(12):
            num = ((p + 11) % 12) + 1
            _n, minor, major, color_hex = STRIP_KEYS[num - 1]
            angle = math.radians(-90 + p * 30)  # top = -90°, clockwise (y down)
            for ring_r, code, label, circle_r in (
                (R_OUTER, f"{num}A", minor, OUTER_CIRCLE_R),
                (R_INNER, f"{num}B", major, INNER_CIRCLE_R),
            ):
                center = QPointF(
                    cx + ring_r * math.cos(angle),
                    cy + ring_r * math.sin(angle),
                )
                self._circles.append((num, code, label, color_hex, center, circle_r))

        self.setFixedSize(int(_SIZE), int(_SIZE))

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

    # --- Highlight API (matches HexKeyGrid) ---

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
        pos = event.position()
        for num, _code, _label, _color, center, circle_r in self._circles:
            if math.hypot(pos.x() - center.x(), pos.y() - center.y()) <= circle_r:
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

    def paintEvent(self, event) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        held = self._held_numbers()
        compat: set[int] = set()
        for n in held:
            compat |= _compatible_numbers(n)

        num_font = QFont("Menlo", 12)
        num_font.setBold(True)
        key_font = QFont("Menlo", 11)
        key_font.setBold(True)

        for num, code, label, color_hex, center, circle_r in self._circles:
            color = QColor(color_hex)
            is_held = code in self._highlighted
            is_compat = num in compat and not is_held
            is_dimmed = bool(held) and num not in compat

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
            painter.drawEllipse(center, circle_r, circle_r)

            if is_dimmed:
                num_color = QColor(DIM_TEXT)
                label_color = QColor(DIM_TEXT)
            elif is_held:
                # The palette fills are bright; use dark ink so the number and
                # key name stay legible on the lit circle (like dark labels on a
                # pressed piano key).
                num_color = QColor("#1a1a1a")
                label_color = QColor("#1a1a1a")
            else:
                num_color = QColor(Theme.TEXT_PRIMARY)
                label_color = QColor(Theme.TEXT_PRIMARY)

            cx = center.x()
            cy = center.y()

            painter.setFont(num_font)
            painter.setPen(num_color)
            painter.drawText(
                int(cx - circle_r), int(cy - 16), int(circle_r * 2), 18,
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                self._num_label(num),
            )

            painter.setFont(key_font)
            painter.setPen(label_color)
            painter.drawText(
                int(cx - circle_r), int(cy - 1), int(circle_r * 2), 18,
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                label,
            )

        painter.end()
