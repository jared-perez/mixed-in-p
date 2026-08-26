"""Spin-box arrows, drawn to PNG in the active palette's colours.

Why this exists at all. The rest of the app's sub-controls are deliberately
left unstyled so the platform draws them (see the QComboBox note in
``app.qss.template``) — but a QSpinBox is the one place where that answer is
wrong on macOS, and it is wrong in two ways at once. QMacStyle draws the
stepper as a native NSStepper over the *border* box, so it paints out the
right-hand edge of the frame: the focus ring stops dead where the stepper
starts, which reads as a half-drawn box. And the stepper's own arrows are
hairline chevrons at the app's control height — the user's report was "the
up/down buttons have only a dot for the symbol". Windows 11 draws a pair of
proper side-by-side triangles and looks right, so the two platforms disagreed
about a control the app uses in two panels.

Styling the sub-controls is what fixes both (the frame is then ours to draw and
nothing paints over it), and the standing warning about that stands: styling
``::up-button`` stops Qt drawing the style's own arrow, and the web-CSS
triangle trick that was reached for last time — a zero-size box with a thick
border and transparent sides — is not implemented by Qt's stylesheet engine,
which fills the sub-control with the border colour instead. An *image* is the
alternative that works, and the reason one was not committed then holds now:
``theme.py`` ships four palettes and an arrow baked at one palette's
``TEXT_PRIMARY`` is invisible on another. So the image is not committed — it is
rendered here, in whatever colour the active palette asks for, at stylesheet
load, and cached under the app data directory by colour.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPolygonF

# Logical size of one triangle. The QSS states the same numbers as the
# ::up-arrow / ::down-arrow width and height, so keep the two in step.
ARROW_W = 9
ARROW_H = 6

# Qt loads the "@2x"/"@3x" sibling of a stylesheet image on a scaled screen and
# falls back to the 1x file otherwise, so each arrow is written at all three and
# referenced by its 1x path. A Retina Mac reads the @2x one.
_SCALES = (1, 2, 3)


def _render(path: Path, down: bool, colour: str, scale: int) -> None:
    """Draw one solid triangle, transparent everywhere else."""
    img = QImage(
        ARROW_W * scale, ARROW_H * scale, QImage.Format.Format_ARGB32_Premultiplied
    )
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(scale, scale)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colour))
        if down:
            points = [QPointF(0, 0), QPointF(ARROW_W, 0), QPointF(ARROW_W / 2, ARROW_H)]
        else:
            points = [QPointF(0, ARROW_H), QPointF(ARROW_W, ARROW_H), QPointF(ARROW_W / 2, 0)]
        painter.drawPolygon(QPolygonF(points))
    finally:
        painter.end()
    img.save(str(path), "PNG")


def _cache_dir() -> Path:
    # Imported inside the function on purpose: the suite's isolation patches
    # get_app_data_dir on its own module, so a name bound at import time here
    # would write to the developer's real application-support directory.
    from src.utils.app_dirs import get_app_data_dir

    path = get_app_data_dir() / "generated"
    path.mkdir(parents=True, exist_ok=True)
    return path


def arrow_urls(colour: str, off_colour: str) -> dict[str, str] | None:
    """Paths for the four arrows, as QSS ``url()`` bodies.

    Keys: ``up``, ``down``, ``up_off``, ``down_off``. The "off" pair is the
    dimmed arrow Qt asks for at a spin box's limit (``:off``) and when the whole
    widget is disabled. Files are named after the colour they were drawn in, so
    a palette change writes new ones rather than reusing a stale picture, and
    the set stays bounded no matter how many times the app is launched.

    Returns None if the files cannot be written, which leaves the caller to drop
    the styled rules and fall back to the platform's own stepper — worse-looking
    on macOS, but never an empty box where an arrow should be.
    """
    try:
        cache = _cache_dir()
        urls: dict[str, str] = {}
        for key, down, hex_colour in (
            ("up", False, colour),
            ("down", True, colour),
            ("up_off", False, off_colour),
            ("down_off", True, off_colour),
        ):
            stem = f"spin_{'down' if down else 'up'}_{hex_colour.lstrip('#')}"
            for scale in _SCALES:
                suffix = "" if scale == 1 else f"@{scale}x"
                target = cache / f"{stem}{suffix}.png"
                if not target.exists():
                    _render(target, down, hex_colour, scale)
            # Forward slashes, always: a Windows path's backslashes are escape
            # characters to Qt's CSS parser, and the app data directory there
            # sits under a user name that may well contain one.
            urls[key] = (cache / f"{stem}.png").as_posix()
        return urls
    except Exception:  # pragma: no cover - depends on a read-only data dir
        return None
