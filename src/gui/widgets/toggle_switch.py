"""A sliding on/off toggle switch.

Subclasses ``QCheckBox`` so it's a drop-in replacement anywhere a checkbox is
used — same ``toggled`` signal and ``isChecked()`` / ``setChecked()`` API — but
paints a pill track with a knob that slides left (off) to right (on) and lights
the track neon yellow when on. The knob animates between states.
"""

from __future__ import annotations

from PySide6.QtCore import Property, QPropertyAnimation, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QCheckBox

from ..styles.theme import Theme


class ToggleSwitch(QCheckBox):
    """Checkbox rendered as an animated left/right sliding switch."""

    _TRACK_W = 46
    _TRACK_H = 24
    _MARGIN = 3

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(self._TRACK_W, self._TRACK_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # 0.0 = knob fully left (off), 1.0 = fully right (on).
        self._pos = 1.0 if self.isChecked() else 0.0
        self._anim = QPropertyAnimation(self, b"knobPos", self)
        self._anim.setDuration(140)
        self.toggled.connect(self._animate)

    # Animated knob position (registered Qt property so QPropertyAnimation works)
    def _get_pos(self) -> float:
        return self._pos

    def _set_pos(self, value: float) -> None:
        self._pos = value
        self.update()

    knobPos = Property(float, _get_pos, _set_pos)

    def _animate(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def sizeHint(self) -> QSize:
        return QSize(self._TRACK_W, self._TRACK_H)

    def hitButton(self, pos) -> bool:
        # Whole widget toggles on click, not just the (hidden) indicator rect.
        return self.rect().contains(pos)

    @staticmethod
    def _blend(a: QColor, b: QColor, t: float) -> QColor:
        return QColor(
            int(a.red() + (b.red() - a.red()) * t),
            int(a.green() + (b.green() - a.green()) * t),
            int(a.blue() + (b.blue() - a.blue()) * t),
        )

    def paintEvent(self, event) -> None:  # noqa: ARG002
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setPen(Qt.PenStyle.NoPen)

            t = self._pos
            rect = QRectF(self.rect().adjusted(0, 0, -1, -1))
            radius = rect.height() / 2

            # Track: grey when off → neon yellow when on.
            track = self._blend(QColor(Theme.BG_LIGHT), QColor(Theme.NEON_YELLOW), t)
            p.setBrush(track)
            p.drawRoundedRect(rect, radius, radius)

            # Knob: light grey on the off (dark) track, dark on the on (yellow)
            # track so it stays legible at both ends.
            d = self._TRACK_H - 2 * self._MARGIN
            travel = self._TRACK_W - 2 * self._MARGIN - d
            x = self._MARGIN + t * travel
            knob = self._blend(QColor(Theme.CHROME), QColor(Theme.BG_DARK), t)
            p.setBrush(knob)
            p.drawEllipse(QRectF(x, self._MARGIN, d, d))
        finally:
            p.end()
