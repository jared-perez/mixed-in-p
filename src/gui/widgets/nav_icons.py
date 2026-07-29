"""Hand-drawn navigation glyphs for the sidebar rail.

Each nav item is drawn with QPainter (no external asset files, consistent
with the transport glyphs in ``player_panel``) and composed into a
state-aware ``QIcon`` so the icon recolours to match the button label:

- Normal / Off  -> grey   (matches the default nav text colour)
- Active / Off  -> white  (keyboard focus, matches the hover text colour)
- *      / On   -> yellow (selected page, matches the ``:checked`` text colour)

Glyphs are rendered at 2x the display size and let Qt downscale, so they
stay crisp on both standard and HiDPI displays.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF

from ..styles.theme import Theme

# Colours mirror the sidebarButton text states in the QSS template. Read from
# the active palette at import time (app.py applies the palette before widget
# modules load — see the import-ordering note in app.py).
NAV_GREY = Theme.TEXT_SECONDARY
NAV_HOVER = Theme.TEXT_PRIMARY
NAV_ACTIVE = Theme.NEON_YELLOW

# Draw at ~2x the display size so downscaling stays crisp on HiDPI too.
_DRAW = 64


def _pen(color: str, width_frac: float) -> QPen:
    pen = QPen(QColor(color))
    pen.setWidthF(_DRAW * width_frac)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _paint_rename(p: QPainter, c: str) -> None:
    """Solid edit pencil (pointing bottom-left) over a writing line."""
    s = _DRAW
    # Pencil: drawn horizontally about the centre, then rotated to the diagonal.
    p.save()
    p.translate(s * 0.5, s * 0.47)
    p.rotate(135)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(c))
    hl, h, nib = s * 0.23, s * 0.072, s * 0.10
    p.drawRect(QRectF(-hl, -h, 2 * hl - nib, 2 * h))            # body
    p.drawPolygon(QPolygonF([                                   # nib -> point
        QPointF(hl - nib, -h),
        QPointF(hl - nib, h),
        QPointF(hl, 0.0),
    ]))
    p.restore()
    p.setPen(_pen(c, 0.085))                                    # writing line
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(s * 0.24, s * 0.80), QPointF(s * 0.60, s * 0.80))


def _paint_convert(p: QPainter, c: str) -> None:
    """Two opposing horizontal arrows (swap)."""
    s = _DRAW
    p.setPen(_pen(c, 0.09))
    p.setBrush(Qt.BrushStyle.NoBrush)
    y1 = s * 0.36
    p.drawLine(QPointF(s * 0.22, y1), QPointF(s * 0.72, y1))
    p.drawLine(QPointF(s * 0.72, y1), QPointF(s * 0.62, y1 - s * 0.075))
    p.drawLine(QPointF(s * 0.72, y1), QPointF(s * 0.62, y1 + s * 0.075))
    y2 = s * 0.64
    p.drawLine(QPointF(s * 0.78, y2), QPointF(s * 0.28, y2))
    p.drawLine(QPointF(s * 0.28, y2), QPointF(s * 0.38, y2 - s * 0.075))
    p.drawLine(QPointF(s * 0.28, y2), QPointF(s * 0.38, y2 + s * 0.075))


def _paint_analyze(p: QPainter, c: str) -> None:
    """Magnifying glass."""
    s = _DRAW
    p.setPen(_pen(c, 0.1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    r = s * 0.20
    cx, cy = s * 0.44, s * 0.42
    p.drawEllipse(QPointF(cx, cy), r, r)
    ex, ey = cx + r * 0.7071, cy + r * 0.7071
    p.drawLine(QPointF(ex, ey), QPointF(s * 0.74, s * 0.72))


def _paint_player(p: QPainter, c: str) -> None:
    """Play triangle (matches the transport glyphs)."""
    s = _DRAW
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(c))
    p.drawPolygon(QPolygonF([
        QPointF(s * 0.34, s * 0.26),
        QPointF(s * 0.34, s * 0.74),
        QPointF(s * 0.74, s * 0.50),
    ]))


def _paint_keyboard(p: QPainter, c: str) -> None:
    """Piano keys."""
    s = _DRAW
    p.setPen(_pen(c, 0.08))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(s * 0.18, s * 0.30, s * 0.64, s * 0.40), s * 0.04, s * 0.04)
    for fx in (0.385, 0.615):
        p.drawLine(QPointF(s * fx, s * 0.30), QPointF(s * fx, s * 0.70))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(c))
    bw, bh = s * 0.075, s * 0.22
    for fx in (0.385, 0.615):
        p.drawRect(QRectF(s * fx - bw / 2, s * 0.30, bw, bh))


def _paint_metadata(p: QPainter, c: str) -> None:
    """Tag with a hole."""
    s = _DRAW
    p.setPen(_pen(c, 0.09))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolygon(QPolygonF([
        QPointF(s * 0.22, s * 0.30),
        QPointF(s * 0.56, s * 0.30),
        QPointF(s * 0.78, s * 0.50),
        QPointF(s * 0.56, s * 0.70),
        QPointF(s * 0.22, s * 0.70),
    ]))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(c))
    p.drawEllipse(QPointF(s * 0.33, s * 0.50), s * 0.045, s * 0.045)


def _paint_spectrum(p: QPainter, c: str) -> None:
    """Vertical bars of varying height."""
    s = _DRAW
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(c))
    base, bw = s * 0.74, s * 0.12
    for fx, top in ((0.28, 0.46), (0.44, 0.28), (0.60, 0.52), (0.76, 0.38)):
        p.drawRoundedRect(QRectF(s * fx - bw / 2, s * top, bw, base - s * top), s * 0.02, s * 0.02)


def _paint_settings(p: QPainter, c: str) -> None:
    """Three slider tracks with knobs (adjustments)."""
    s = _DRAW
    rows = ((0.34, 0.64), (0.50, 0.38), (0.66, 0.56))  # (track y, knob x)
    p.setPen(_pen(c, 0.085))
    p.setBrush(Qt.BrushStyle.NoBrush)
    for yf, _ in rows:
        p.drawLine(QPointF(s * 0.20, s * yf), QPointF(s * 0.80, s * yf))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(c))
    for yf, kx in rows:
        p.drawEllipse(QPointF(s * kx, s * yf), s * 0.075, s * 0.075)


def _paint_history(p: QPainter, c: str) -> None:
    """Clock face (recent / history)."""
    s = _DRAW
    p.setPen(_pen(c, 0.09))
    p.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy, r = s * 0.5, s * 0.5, s * 0.26
    p.drawEllipse(QPointF(cx, cy), r, r)
    p.drawLine(QPointF(cx, cy), QPointF(cx, cy - r * 0.55))
    p.drawLine(QPointF(cx, cy), QPointF(cx + r * 0.52, cy + r * 0.12))


def _paint_collapse(p: QPainter, c: str) -> None:
    """Double chevron pointing left (collapse the rail)."""
    s = _DRAW
    p.setPen(_pen(c, 0.1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    for off in (0.0, 0.20):
        xr = s * (0.50 + off)
        p.drawPolyline(QPolygonF([
            QPointF(xr, s * 0.30),
            QPointF(xr - s * 0.17, s * 0.50),
            QPointF(xr, s * 0.70),
        ]))


def _paint_expand(p: QPainter, c: str) -> None:
    """Double chevron pointing right (expand the rail)."""
    s = _DRAW
    p.setPen(_pen(c, 0.1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    for off in (0.0, 0.20):
        xl = s * (0.30 + off)
        p.drawPolyline(QPolygonF([
            QPointF(xl, s * 0.30),
            QPointF(xl + s * 0.17, s * 0.50),
            QPointF(xl, s * 0.70),
        ]))


_PAINTERS = {
    "rename": _paint_rename,
    "convert": _paint_convert,
    "analysis": _paint_analyze,
    "player": _paint_player,
    "keyboard": _paint_keyboard,
    "metadata": _paint_metadata,
    "spectrum": _paint_spectrum,
    "settings": _paint_settings,
    "history": _paint_history,
    "collapse": _paint_collapse,
    "expand": _paint_expand,
}

# (mode, state, colour): Off = unselected, On = selected (:checked),
# Active = keyboard focus.
_STATES = (
    (QIcon.Mode.Normal, QIcon.State.Off, NAV_GREY),
    (QIcon.Mode.Active, QIcon.State.Off, NAV_HOVER),
    (QIcon.Mode.Normal, QIcon.State.On, NAV_ACTIVE),
    (QIcon.Mode.Active, QIcon.State.On, NAV_ACTIVE),
)


def nav_icon(page_id: str) -> QIcon:
    """Build a state-aware QIcon for a sidebar nav page, or an empty icon
    if the page has no glyph defined."""
    paint = _PAINTERS.get(page_id)
    icon = QIcon()
    if paint is None:
        return icon
    for mode, state, color in _STATES:
        pm = QPixmap(_DRAW, _DRAW)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            paint(p, color)
        finally:
            p.end()
        icon.addPixmap(pm, mode, state)
    return icon
