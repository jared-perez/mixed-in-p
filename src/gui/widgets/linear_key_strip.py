"""Linear key strip — harmonic key reference as 12 stacked bars.

Exposes ``segment_pressed`` / ``segment_released`` signals carrying the key-code
number 1-12, and ``add_highlight`` / ``remove_highlight`` / ``clear_highlights``
taking codes like ``"5A"`` / ``"8B"``, so ``KeyboardPanel`` drives it directly.

While a chord is held the matching row expands by a small amount, harmonically
compatible neighbours (same number, +/-1) widen slightly and glow, and the rest
dim — a restrained take on the "reveal" effect from harmonic-grid.jsx VIEW 3.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from src.analysis.keycode import keycode_to_open_key

from ..styles.theme import Theme

# id 1..12 -> (minor_label, major_label, color)
# Palette centred on the app's neon yellow (#f0ff00, Theme.NEON_YELLOW): a gradient
# from yellow-green/chartreuse, through the neon yellow itself, down into gold/amber/orange.
STRIP_KEYS: list[tuple[int, str, str, str]] = [
    (1, "A♭m", "B", "#aaff44"),
    (2, "E♭m", "F♯", "#bcff33"),
    (3, "B♭m", "D♭", "#ccff22"),
    (4, "Fm", "A♭", "#ddff14"),
    (5, "Cm", "E♭", "#ecff0a"),
    (6, "Gm", "B♭", "#f0ff00"),  # Theme.NEON_YELLOW — the app accent
    (7, "Dm", "F", "#f6ee00"),
    (8, "Am", "C", "#fbdb00"),
    (9, "Em", "G", "#ffc800"),
    (10, "Bm", "D", "#ffb500"),
    (11, "F♯m", "A", "#ffa200"),
    (12, "C♯m", "E", "#ff8f00"),
]

ROW_HEIGHT = 30
ROW_GAP = 8
LABEL_COL_WIDTH = 28  # room for the "1".."12" number label left of each bar

# Bar width in pixels: a fixed base, expanding only a little when a row is held
# or harmonically compatible (the reveal is a small nudge, not a full-width fan).
BAR_BASE_W = 300
EXPAND_COMPAT = 12
EXPAND_HELD = 28

DIM_OPACITY = 0.25

# Animation: lerp current values toward target each tick.
ANIM_INTERVAL_MS = 16  # ~60 fps
ANIM_SPEED = 0.30  # fraction of remaining distance per tick
ANIM_EPSILON = 0.005


def _compatible_numbers(n: int) -> set[int]:
    """Adjacent key-code numbers (self, prev, next), wrapping 1-12."""
    prev = ((n - 2) % 12) + 1
    nxt = (n % 12) + 1
    return {n, prev, nxt}


class LinearKeyStrip(QWidget):
    """Canvas widget that draws the 12 key-code keys as a vertical linear strip."""

    # Emitted when the user presses / releases a row.
    # Payload is the segment number 1-12 (caller decides A vs B from master mode).
    segment_pressed = Signal(int)
    segment_released = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(len(STRIP_KEYS) * (ROW_HEIGHT + ROW_GAP))
        # Fixed width sized to the widest (held) bar — the strip no longer
        # stretches, so it can be pushed to the right of the hex grid.
        self.setFixedWidth(LABEL_COL_WIDTH + 8 + BAR_BASE_W + EXPAND_HELD + 8)

        self._highlighted: set[str] = set()  # e.g. {"5A", "8B"}
        self._mouse_segment: int | None = None
        self._notation = "keycode"

        # Per-row animated state, keyed by row index 0..11: bar width (px) + opacity.
        self._width: list[float] = [float(BAR_BASE_W)] * len(STRIP_KEYS)
        self._opacity: list[float] = [1.0] * len(STRIP_KEYS)

        self._anim = QTimer(self)
        self._anim.setInterval(ANIM_INTERVAL_MS)
        self._anim.timeout.connect(self._tick)

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

    # --- Highlight API ---

    def add_highlight(self, code: str) -> None:
        if not code or code in self._highlighted:
            return
        self._highlighted.add(code)
        self._start_anim()

    def remove_highlight(self, code: str) -> None:
        if code not in self._highlighted:
            return
        self._highlighted.discard(code)
        self._start_anim()

    def clear_highlights(self) -> None:
        if not self._highlighted:
            return
        self._highlighted.clear()
        self._start_anim()

    # --- State helpers ---

    def _held_numbers(self) -> set[int]:
        return {int(code[:-1]) for code in self._highlighted}

    def _targets(self) -> tuple[list[float], list[float]]:
        """Target (bar width px, opacity) per row given the held set."""
        held = self._held_numbers()
        compat: set[int] = set()
        for n in held:
            compat |= _compatible_numbers(n)

        widths: list[float] = []
        opacities: list[float] = []
        for num, _minor, _major, _color in STRIP_KEYS:
            is_held = num in held
            is_compat = num in compat and not is_held
            is_dimmed = bool(held) and num not in compat
            if is_held:
                widths.append(float(BAR_BASE_W + EXPAND_HELD))
            elif is_compat:
                widths.append(float(BAR_BASE_W + EXPAND_COMPAT))
            else:
                widths.append(float(BAR_BASE_W))
            opacities.append(DIM_OPACITY if is_dimmed else 1.0)
        return widths, opacities

    def _start_anim(self) -> None:
        if not self._anim.isActive():
            self._anim.start()
        self.update()

    def _tick(self) -> None:
        widths, opacities = self._targets()
        done = True
        for i in range(len(STRIP_KEYS)):
            for cur, tgt, store in (
                (self._width[i], widths[i], self._width),
                (self._opacity[i], opacities[i], self._opacity),
            ):
                diff = tgt - cur
                if abs(diff) < ANIM_EPSILON:
                    store[i] = tgt
                else:
                    store[i] = cur + diff * ANIM_SPEED
                    done = False
        self.update()
        if done:
            self._anim.stop()

    # --- Hit testing / mouse events ---

    def _hit_row(self, y: int) -> int | None:
        """Return the key-code number (1-12) under the y coordinate, or None."""
        idx = y // (ROW_HEIGHT + ROW_GAP)
        if idx < 0 or idx >= len(STRIP_KEYS):
            return None
        # Ignore clicks landing in the gap below a row.
        if y % (ROW_HEIGHT + ROW_GAP) >= ROW_HEIGHT:
            return None
        return STRIP_KEYS[idx][0]

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        num = self._hit_row(int(pos.y()))
        if num is None:
            return
        self._mouse_segment = num
        self.segment_pressed.emit(num)

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

        held = self._held_numbers()
        bar_x = LABEL_COL_WIDTH + 8
        avail_w = max(40, self.width() - bar_x - 8)

        num_font = QFont("Menlo", 11)
        num_font.setBold(True)
        label_font = QFont("Menlo", 11)
        label_font.setBold(True)

        for i, (num, minor, major, color_hex) in enumerate(STRIP_KEYS):
            top = i * (ROW_HEIGHT + ROW_GAP)
            color = QColor(color_hex)
            is_held = num in held
            opacity = self._opacity[i]
            bar_w = int(self._width[i])

            painter.setOpacity(opacity)

            # Number label (left column), tinted with the key colour when held.
            painter.setFont(num_font)
            painter.setPen(QColor(color_hex) if is_held else QColor(Theme.TEXT_SECONDARY))
            painter.drawText(
                0,
                top,
                LABEL_COL_WIDTH,
                ROW_HEIGHT,
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                self._num_label(num),
            )

            # Bar fill: full colour (held), translucent colour (compatible), or base bg.
            if is_held:
                fill = QColor(color)
            elif self._width[i] > BAR_BASE_W + EXPAND_COMPAT / 2:
                fill = QColor(color)
                fill.setAlpha(0x77)
            else:
                fill = QColor(Theme.BG_LIGHT)
            painter.setBrush(fill)

            if is_held:
                pen = QPen(color, 2)
            else:
                pen = QPen(Qt.PenStyle.NoPen)
            painter.setPen(pen)
            painter.drawRoundedRect(bar_x, top, bar_w, ROW_HEIGHT, 4, 4)

            # Soft glow approximation: a lighter outline just inside the held bar.
            if is_held:
                glow = QColor(color).lighter(150)
                glow.setAlpha(0x66)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(glow, 1))
                painter.drawRoundedRect(bar_x + 1, top + 1, bar_w - 2, ROW_HEIGHT - 2, 3, 3)

            # Key labels inside the bar: "minor  ·  major".
            # Emphasise the half matching the held letter (A=minor, B=major).
            painter.setFont(label_font)
            minor_lit = f"{num}A" in self._highlighted
            major_lit = f"{num}B" in self._highlighted

            text_y = top
            text_x = bar_x + 12
            painter.setPen(
                QColor(Theme.TEXT_PRIMARY) if minor_lit else QColor("#e0e0e0")
            )
            minor_metrics_w = painter.fontMetrics().horizontalAdvance(minor)
            painter.drawText(
                text_x, text_y, minor_metrics_w + 4, ROW_HEIGHT,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                minor,
            )

            sep_x = text_x + minor_metrics_w + 8
            painter.setPen(QColor("#cccccc"))
            painter.drawText(
                sep_x, text_y, 12, ROW_HEIGHT,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                "·",
            )

            major_x = sep_x + 16
            painter.setPen(
                QColor(Theme.TEXT_PRIMARY) if major_lit else QColor("#cccccc")
            )
            painter.drawText(
                major_x, text_y, avail_w, ROW_HEIGHT,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                major,
            )

        painter.setOpacity(1.0)
        painter.end()
