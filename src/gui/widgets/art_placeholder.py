"""The empty cover square, and reading a cover out of a drop.

Shared by the Player's 56px header art and the sidebar's big cover box, which
both stand in for the playing track's artwork and both take an image dropped
on them as its new cover.

The words are painted, not laid out in a QLabel: the header square is 56px
and its words are translated, so they are fitted to the square here — shrunk
until the longest word fits, then elided — rather than cut at both ends by a
label that never elides (CLAUDE.md).
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QMimeData, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen, QPixmap

from ..styles.theme import Theme
from .artwork_widget import IMAGE_EXTENSIONS, mime_for_path

# Smallest point size a placeholder line shrinks to before it elides instead.
_MIN_POINT_SIZE = 6.0
# Width of the outline drawn while an image is dragged over the square.
_DROP_OUTLINE = 2

# What word-wrap can't break: a run of non-space text, except that Chinese
# and Japanese break between any two characters, so each of those is its own
# unit. Without that, "アートワークなし" counts as one long word and the header
# square shrinks it to the floor.
_UNBREAKABLE = re.compile(r"[\u3000-\u9fff\uff00-\uffef]|[^\s\u3000-\u9fff\uff00-\uffef]+")


def image_urls(mime: QMimeData) -> list[Path]:
    """The local image files in a drag, in the order they were dragged."""
    if not mime.hasUrls():
        return []
    paths = [Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile()]
    return [p for p in paths if p.suffix.lower() in IMAGE_EXTENSIONS]


def dropped_image(mime: QMimeData) -> tuple[bytes, str] | None:
    """The first dragged image that is really an image, as (bytes, mime type).

    Decoded before it is accepted: the suffix only says what a file claims to
    be, and these bytes are about to be written into an audio file's tags.
    """
    for path in image_urls(mime):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if QPixmap().loadFromData(data):
            return data, mime_for_path(path)
    return None


def _point_size(font: QFont) -> float:
    """The font's size in points, whichever unit it was set in.

    A QSS ``font-size`` in px leaves ``pointSizeF()`` at -1, and the app's
    stylesheet sets every size in px.
    """
    if font.pointSizeF() > 0:
        return font.pointSizeF()
    return max(_MIN_POINT_SIZE, font.pixelSize() * 0.75)


def _fit_font(base: QFont, lines: list[str], width: float, max_pt: float) -> QFont:
    """The largest size up to *max_pt* at which every line's longest word fits.

    Words, not lines: the lines word-wrap, so what can't be allowed to
    overflow is a single word ("Перетащите" in the header square).
    """
    font = QFont(base)
    size = max_pt
    words = [w for line in lines for w in _UNBREAKABLE.findall(line)]
    while True:
        font.setPointSizeF(size)
        metrics = QFontMetricsF(font)
        if size <= _MIN_POINT_SIZE or all(
            metrics.horizontalAdvance(w) <= width for w in words
        ):
            return font
        size = max(_MIN_POINT_SIZE, size - 0.5)


def paint_placeholder(
    painter: QPainter,
    rect,
    title: str,
    hint: str = "",
    *,
    scale: float = 1.0,
    padding: int = 4,
) -> None:
    """Fill *rect* as an empty cover, with *title* and an optional *hint*
    under it, centred as one block, at up to *scale* times the painter's
    font size."""
    painter.fillRect(rect, QColor(Theme.BG_LIGHT))
    inner = QRectF(rect).adjusted(padding, padding, -padding, -padding)
    lines = [title] + ([hint] if hint else [])
    max_pt = max(_MIN_POINT_SIZE, _point_size(painter.font()) * scale)
    font = _fit_font(painter.font(), lines, inner.width(), max_pt)
    painter.setFont(font)
    painter.setPen(QColor(Theme.TEXT_SECONDARY))
    metrics = QFontMetricsF(font)
    flags = Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap
    # Measure each line wrapped, then stack them centred in the square.
    blocks = [
        metrics.boundingRect(inner, int(flags), line).height() for line in lines
    ]
    gap = metrics.height() * 0.3 if hint else 0.0
    top = inner.top() + max(0.0, (inner.height() - sum(blocks) - gap) / 2)
    for line, height in zip(lines, blocks):
        box = QRectF(inner.left(), top, inner.width(), height)
        text = line
        if len(_UNBREAKABLE.findall(line)) == 1 and metrics.horizontalAdvance(line) > inner.width():
            text = metrics.elidedText(line, Qt.TextElideMode.ElideRight, inner.width())
        painter.drawText(box, int(flags), text)
        top += height + gap


def paint_drop_outline(painter: QPainter, rect) -> None:
    """The outline that says "let go here", over art or placeholder alike."""
    pen = QPen(QColor(Theme.NEON_YELLOW))
    pen.setWidth(_DROP_OUTLINE)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    half = _DROP_OUTLINE / 2
    painter.drawRect(QRectF(rect).adjusted(half, half, -half, -half))
