"""The triangle that says whether a panel's step is part of a pipeline run.

One of these sits in the Rename, Convert and Analyze panels, and three minis
mirror them in the header. Checked means "this step runs"; unchecked means a
run passes the step by entirely. The shape is a hazard sign with a wave
through it — symbol only, no label, so the tooltip carries the meaning and
nothing has to be re-measured in eleven languages.

Self-painted from a ``QAbstractButton`` rather than styled from QSS: the shape
is not a box, and the global button padding inside a box this small leaves no
contents rect at all and would silently draw nothing (the #discogsApplyButton
law). The only QSS it wants is a transparent background, because the global
``QWidget`` rule would otherwise paint BG_DARK over whatever it sits on.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, QPointF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QAbstractButton

from ..convert_pipeline import STEP_ANALYZE, STEP_CONVERT, STEP_RENAME
from ..styles.theme import Theme

# What each toggle says the next click will do, off state first. Marked here
# and translated at the display site so the panel triangle and its header mini
# share one pair of strings rather than six pairs of the same sentence — they
# mean the same thing, and a translator should only have to say it once.
#
# QT_TRANSLATE_NOOP rather than a bare literal because the display site passes
# a variable, which lupdate cannot read; this is what puts them in the .ts.
STEP_TOOLTIPS = {
    STEP_RENAME: (
        QT_TRANSLATE_NOOP("PipelineToggle", "Include Rename in pipeline runs"),
        QT_TRANSLATE_NOOP("PipelineToggle", "Leave Rename out of pipeline runs"),
    ),
    STEP_CONVERT: (
        QT_TRANSLATE_NOOP("PipelineToggle", "Include Convert in pipeline runs"),
        QT_TRANSLATE_NOOP("PipelineToggle", "Leave Convert out of pipeline runs"),
    ),
    STEP_ANALYZE: (
        QT_TRANSLATE_NOOP("PipelineToggle", "Include Analyze in pipeline runs"),
        QT_TRANSLATE_NOOP("PipelineToggle", "Leave Analyze out of pipeline runs"),
    ),
}


class PipelineToggle(QAbstractButton):
    """Checkable triangle marking one step as part of the pipeline."""

    # Panel-size, matching the 28px box the Convert panel's `|` toggle wore.
    SIZE_PANEL = 28
    # Header-size, small enough for three of them beside the Add button.
    SIZE_MINI = 18

    def __init__(self, size: int = SIZE_PANEL, parent=None) -> None:
        super().__init__(parent)
        self._size = size
        self.setCheckable(True)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._tip_on = ""
        self._tip_off = ""
        self.toggled.connect(lambda _checked: self._sync_tooltip())

    @classmethod
    def for_step(cls, step: str, size: int = SIZE_PANEL, parent=None) -> "PipelineToggle":
        """A toggle for one pipeline step, already carrying its tooltips."""
        toggle = cls(size, parent)
        off, on = STEP_TOOLTIPS[step]
        toggle.set_step_tooltips(
            # The context is spelled out at every call: a module constant here
            # extracts nothing and falls back to English in eleven languages.
            QCoreApplication.translate("PipelineToggle", off),
            QCoreApplication.translate("PipelineToggle", on),
        )
        return toggle

    # ------------------------------------------------------------- tooltips

    def set_step_tooltips(self, when_off: str, when_on: str) -> None:
        """The two tooltips, each stating what the *next* click does.

        `when_off` shows while the step is off (so it describes switching it
        on), `when_on` while it is on. Held here rather than re-set by the
        panel on every toggle so the pairing cannot drift out of step.
        """
        self._tip_off = when_off
        self._tip_on = when_on
        self._sync_tooltip()

    def _sync_tooltip(self) -> None:
        self.setToolTip(self._tip_on if self.isChecked() else self._tip_off)

    # -------------------------------------------------------------- geometry

    def sizeHint(self) -> QSize:
        return QSize(self._size, self._size)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def triangle(self) -> QPolygonF:
        """The clickable shape: apex up, base along the bottom edge."""
        inset = 1.0
        w = float(self.width())
        h = float(self.height())
        return QPolygonF([
            QPointF(w / 2.0, inset),
            QPointF(w - inset, h - inset),
            QPointF(inset, h - inset),
        ])

    def hitButton(self, pos) -> bool:
        # Only the triangle answers to the mouse — the corners it leaves empty
        # belong to whatever is behind it, not to this button.
        return self.triangle().containsPoint(QPointF(pos), Qt.FillRule.OddEvenFill)

    # --------------------------------------------------------------- painting

    @staticmethod
    def _rounded(points: list[QPointF], radius: float) -> QPainterPath:
        """`points` as a closed path with its corners pulled round.

        Quadratic corners with the vertex as the control point: at 18-28px
        that is indistinguishable from a true arc and costs no trigonometry.
        """
        def toward(origin: QPointF, target: QPointF) -> QPointF:
            dx, dy = target.x() - origin.x(), target.y() - origin.y()
            length = math.hypot(dx, dy) or 1.0
            step = min(radius, length / 2.0)
            return QPointF(origin.x() + dx / length * step, origin.y() + dy / length * step)

        path = QPainterPath()
        count = len(points)
        path.moveTo(toward(points[0], points[1]))
        for i in range(count):
            corner = points[(i + 1) % count]
            path.lineTo(toward(corner, points[i]))
            path.quadTo(corner, toward(corner, points[(i + 2) % count]))
        path.closeSubpath()
        return path

    def _wave(self) -> QPainterPath:
        """One period of a sine, sitting where the triangle is widest."""
        w = float(self.width())
        h = float(self.height())
        span = w * 0.44
        amp = h * 0.10
        cx, cy = w / 2.0, h * 0.66
        path = QPainterPath()
        steps = 16
        for i in range(steps + 1):
            t = i / steps
            point = QPointF(cx - span / 2.0 + span * t, cy - amp * math.sin(2 * math.pi * t))
            path.moveTo(point) if i == 0 else path.lineTo(point)
        return path

    @staticmethod
    def _dim(color: QColor, amount: float = 0.55) -> QColor:
        """`color` faded toward the panel behind it."""
        back = QColor(Theme.BG_MEDIUM)
        return QColor(
            int(color.red() + (back.red() - color.red()) * amount),
            int(color.green() + (back.green() - color.green()) * amount),
            int(color.blue() + (back.blue() - color.blue()) * amount),
        )

    def _colors(self) -> tuple[QColor, QColor, QColor]:
        """(fill, border, glyph) for the current state."""
        if not self.isEnabled():
            # A disabled toggle still has to say which way it is set: these are
            # greyed out for the length of a run, and an ON step that reads as
            # OFF the whole time it is running is worse than no toggle at all.
            if self.isChecked():
                fill = self._dim(QColor(Theme.NEON_YELLOW))
                return fill, fill, self._dim(QColor(Theme.BG_DARK), 0.35)
            return (
                QColor(Theme.BG_MEDIUM),
                QColor(Theme.CHROME_DARK),
                QColor(Theme.TEXT_DISABLED),
            )
        hovered = self.underMouse()
        if self.isChecked():
            if self.isDown():
                fill = QColor(Theme.ACCENT_PRESSED)
            elif hovered:
                fill = QColor(Theme.ACCENT_HOVER)
            else:
                fill = QColor(Theme.NEON_YELLOW)
            return fill, fill, QColor(Theme.BG_DARK)
        return (
            QColor(Theme.BG_MEDIUM),
            QColor(Theme.CHROME if hovered else Theme.CHROME_DARK),
            QColor(Theme.TEXT_PRIMARY if hovered else Theme.TEXT_SECONDARY),
        )

    def paintEvent(self, event) -> None:  # noqa: ARG002
        fill, border, glyph = self._colors()
        stroke = max(1.4, self._size / 16.0)
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            shape = self._rounded(list(self.triangle()), radius=self._size * 0.16)
            painter.setBrush(fill)
            painter.setPen(QPen(border, 1.0))
            painter.drawPath(shape)

            pen = QPen(glyph, stroke)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(self._wave())
        finally:
            painter.end()

    # Hover changes the colours, and QAbstractButton only repaints on press.
    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()
