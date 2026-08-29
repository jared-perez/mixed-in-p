"""The triangle that says whether a panel's step is part of a pipeline run.

One of these sits in the Rename, Convert and Analyze panels, and three minis
mirror them in the header. Checked means "this step runs"; unchecked means a
run passes the step by entirely. The shape is the tsunami hazard sign — a
barrelling wave in a rounded triangle, which is the pipeline's other reading
(the surf break, not the plumbing) and the one thing about the word that
survives into all eleven languages. Symbol only, no label, so the tooltip
carries the meaning and nothing has to be re-measured per language.

The sign is drawn as *ink and negative space* rather than as a fill with a
glyph on top: the ink is the rim plus the wave, and everything the reference
artwork paints yellow is left alone. Unchecked that negative space is the
panel behind, so the toggle reads as a line drawing; checked it fills with the
accent and the sign lights up whole. One path drives both states, so the two
cannot drift apart.

Checked, the sign also wears a grey hairline on its outer edge. Without it the
silhouette is drawn only by the rim, which is BG_DARK ink — a dark line on a
dark panel, so the lit sign reads as a yellow blob with no border, and on a
surface that *is* BG_DARK (the About dialog's slides) the edge disappears
completely. The hairline is TEXT_SECONDARY, the same colour the unchecked rim
is drawn in, so the outer edge is one colour in both states and only the fill
changes. Unchecked wants none of it: the rim is already that grey and a second
line would just double it.

Self-painted from a ``QAbstractButton`` rather than styled from QSS: the shape
is not a box, and the global button padding inside a box this small leaves no
contents rect at all and would silently draw nothing (the #discogsApplyButton
law). The only QSS it wants is a transparent background, because the global
``QWidget`` rule would otherwise paint BG_DARK over whatever it sits on.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, QPointF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPolygonF,
)
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

# Where the wave meets the sign's field, traced from the artwork in
# spitball/mip-pip/evidence/wave-hazard.png rather than eyeballed: these are
# the boundary between that sign's yellow region and its black wave, run
# through Douglas-Peucker at 0.26% of the sign's width, in coordinates
# normalized to the sign's bounding box (x and y both 0..1, y downward).
#
# It reads right to left: it starts on the right-hand edge, sweeps left along
# the underside of the barrel, spirals in to the lip's tip at the middle pair,
# then comes back out over the crest to the left-hand edge. Both ends are
# extrapolated past the sign in `_wave_region`, so the rim can be any
# thickness without the curve needing to be re-traced to meet it.
_WAVE_EDGE = (
    (0.864, 0.833),
    (0.767, 0.850),
    (0.681, 0.847),
    (0.600, 0.825),
    (0.562, 0.805),
    (0.537, 0.784),
    (0.518, 0.759),
    (0.508, 0.737),
    (0.501, 0.698),
    (0.508, 0.653),
    (0.531, 0.620),
    (0.558, 0.603),
    (0.592, 0.597),
    (0.636, 0.608),
    (0.674, 0.635),
    (0.683, 0.628),
    (0.650, 0.565),
    (0.613, 0.527),
    (0.575, 0.503),
    (0.513, 0.486),
    (0.436, 0.490),
    (0.358, 0.514),
    (0.273, 0.557),
)

# The one place this deviates from the artwork, and it is a legibility fix
# rather than a taste one. The field is a single connected region only through
# the channel between the wave's lip and the right-hand rim, which the artwork
# draws at ~8% of the width — 1.4px on the 18px header mini, i.e. gone once
# antialiasing has had it. The checked toggle then reads as two unrelated
# yellow blobs instead of a barrel. Squeezing the wave horizontally toward the
# point where it meets the left edge widens that channel and leaves everything
# else where it was; measured across 18/22/28px, 0.88 is where the mini holds
# together without the panel-size triangle looking cramped.
_WAVE_SQUEEZE = 0.88
_WAVE_PIVOT = 0.30


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

    def checkStateSet(self) -> None:
        """Qt's hook for "the checked state was set", however it was set.

        The tooltip hung off `toggled` until 2026-08-25, which is wrong for
        exactly the case this widget exists in: a step appears twice — panel
        triangle and header mini — and each reflects the other inside
        `blockSignals(True)`, so the *reflected* one changed its picture and
        kept the other state's sentence. Clicking a header mini left its panel
        triangle saying "Include Rename…" over a step that was now on.

        Nothing about that is visible to a test of `toggled`, and the panel
        that read its own state from config at startup (Convert, unblocked)
        looked right while the two that only ever learn theirs through the
        mirror did not — which is what made it read as three panels
        disagreeing rather than as one missing call.
        """
        super().checkStateSet()
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
        # belong to whatever is behind it, not to this button. Note this is the
        # whole triangle, not the ink: the field inside the rim is part of the
        # button even when nothing is painted there.
        return self.triangle().containsPoint(QPointF(pos), Qt.FillRule.OddEvenFill)

    def _rim(self) -> float:
        """How thick the sign's border is.

        6% of the width in the reference artwork, floored so that the mini in
        the header does not come out at a single hairline pixel.
        """
        return max(1.1, self._size * 0.065)

    def _outline(self) -> float:
        """How thick the checked state's hairline is.

        Thinner than `_rim()` on purpose — it is a border on the sign, not a
        second rim — and stroked *centred* on the outline rather than outside
        it, so it costs no room: the triangle already sits 1px in from the
        widget's edge, and an outward-only band that wide would put the apex
        on the boundary at the header size.
        """
        return max(0.9, self._size * 0.045)

    def _sign(self) -> QPainterPath:
        return self._rounded(list(self.triangle()), radius=self._size * 0.16)

    def _wave_region(self) -> QPainterPath:
        """The wave, closed into a region that reaches well past the sign.

        `_WAVE_EDGE` only describes where the wave meets the field; the rest of
        this shape is deliberately oversized so the caller can clip it against
        whatever the current rim leaves. Both ends carry on along their last
        segment rather than stopping on the edge they were traced against —
        a thicker rim then simply eats more of the curve, instead of leaving a
        sliver of field between the wave and the border.
        """
        inset = 1.0
        w = float(self.width())
        h = float(self.height())
        span_x, span_y = w - 2.0 * inset, h - 2.0 * inset
        points = [
            QPointF(
                inset + (_WAVE_PIVOT + (nx - _WAVE_PIVOT) * _WAVE_SQUEEZE) * span_x,
                inset + ny * span_y,
            )
            for nx, ny in _WAVE_EDGE
        ]

        reach = max(w, h)

        def onward(origin: QPointF, tip: QPointF) -> QPointF:
            """`reach` px past `tip`, heading away from `origin`."""
            dx, dy = tip.x() - origin.x(), tip.y() - origin.y()
            length = math.hypot(dx, dy) or 1.0
            return QPointF(tip.x() + dx / length * reach, tip.y() + dy / length * reach)

        polygon = QPolygonF([
            onward(points[1], points[0]),
            *points,
            onward(points[-2], points[-1]),
            QPointF(-reach, h + reach),
            QPointF(w + reach, h + reach),
        ])
        path = QPainterPath()
        path.addPolygon(polygon)
        path.closeSubpath()
        return path

    def _field(self) -> QPainterPath:
        """The sign's negative space: inside the rim, above the wave."""
        sign = self._sign()
        stroker = QPainterPathStroker()
        stroker.setWidth(self._rim() * 2.0)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        # A band centred on the outline, subtracted, insets every edge evenly —
        # scaling the triangle about its centroid would not, since its three
        # edges sit at different distances from it.
        inner = sign.subtracted(stroker.createStroke(sign))
        return inner.subtracted(self._wave_region())

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

    @staticmethod
    def _dim(color: QColor, amount: float = 0.55) -> QColor:
        """`color` faded toward the panel behind it."""
        back = QColor(Theme.BG_MEDIUM)
        return QColor(
            int(color.red() + (back.red() - color.red()) * amount),
            int(color.green() + (back.green() - color.green()) * amount),
            int(color.blue() + (back.blue() - color.blue()) * amount),
        )

    def _colors(self) -> tuple[QColor | None, QColor, QColor | None]:
        """(field, ink, outline) for the current state.

        A `None` field means "leave the negative space alone", which is what
        makes an unchecked toggle a line drawing on the panel rather than a
        second box sitting on it. A `None` outline means the ink already draws
        the silhouette, which is exactly the unchecked case.
        """
        if not self.isEnabled():
            # A disabled toggle still has to say which way it is set: these are
            # greyed out for the length of a run, and an ON step that reads as
            # OFF the whole time it is running is worse than no toggle at all.
            if self.isChecked():
                return (
                    self._dim(QColor(Theme.NEON_YELLOW)),
                    self._dim(QColor(Theme.BG_DARK), 0.35),
                    # Dimmed with the rest of it: a full-strength border around
                    # a faded sign reads as enabled from across the room, which
                    # is the one thing the disabled state must not do.
                    self._dim(QColor(Theme.TEXT_SECONDARY)),
                )
            return None, QColor(Theme.TEXT_DISABLED), None
        hovered = self.underMouse()
        if self.isChecked():
            if self.isDown():
                field = QColor(Theme.ACCENT_PRESSED)
            elif hovered:
                field = QColor(Theme.ACCENT_HOVER)
            else:
                field = QColor(Theme.NEON_YELLOW)
            # The border stays put through hover and press — the field already
            # answers the mouse, and a silhouette that moves with it would read
            # as the whole widget changing size.
            return field, QColor(Theme.BG_DARK), QColor(Theme.TEXT_SECONDARY)
        return (
            None,
            QColor(
                Theme.TEXT_PRIMARY
                if (hovered or self.isDown())
                else Theme.TEXT_SECONDARY
            ),
            None,
        )

    def paintEvent(self, event) -> None:  # noqa: ARG002
        field_color, ink, outline = self._colors()
        sign = self._sign()
        field = self._field()
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            if field_color is not None:
                painter.fillPath(field, field_color)
            # The ink is whatever the field does not claim, so the rim and the
            # wave are one shape and cannot come out at different weights.
            painter.fillPath(sign.subtracted(field), ink)
            if outline is not None:
                # Last, and over the ink: the inner half of a centred stroke
                # lands on the rim, which is what keeps the sign the same size
                # lit as unlit.
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(outline, self._outline()))
                painter.drawPath(sign)
        finally:
            painter.end()

    # Hover changes the colours, and QAbstractButton only repaints on press.
    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()
