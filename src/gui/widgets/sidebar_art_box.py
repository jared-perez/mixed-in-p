"""The big album-art box that lives at the foot of the sidebar.

Opened by clicking the Player's 56px header art, which is too small to look
at; this shows the same cover at the full inner width of the nav rail. It is
a *view* of whatever the engine is playing, so it follows the track and shows
a placeholder rather than vanishing when nothing is playing — a box that
disappears on Stop reads as a crash rather than as an empty state.

The side is an INPUT (``set_side``), never derived from the widget's own
hints: a QLabel holding a pixmap reports *that pixmap* as its size hint, so a
box that scaled its picture to its own width would converge on whatever it
happened to start at and could never grow again (the Metadata panel's cover
column, CLAUDE.md). The sidebar budgets the number from the room it has.

Note this widget has no layout — the close button sits *over* the art, which
a layout cannot express — so its own ``sizeHint()`` is (-1, -1) and it
contributes nothing to the rail's own height arithmetic, open or closed. That
is why the sidebar reserves room for it explicitly rather than trusting the
layout to notice.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QPushButton

from src.gui.styles.theme import Theme

# Side of the round close button, and the inset it sits at from the corner.
_CLOSE_SIDE = 18
_CLOSE_INSET = 4

# A sane square to exist at before a caller says otherwise; the sidebar
# always calls set_side with a budgeted number.
_DEFAULT_SIDE = 164


class _ArtCanvas(QLabel):
    """The picture itself, or a dim placeholder when there is no picture.

    The placeholder is painted rather than set as a stylesheet background:
    this sits inside a QFrame that has already been told to be transparent,
    and a bare background rule here would fight that.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pixmap_source: QPixmap | None = None

    def set_source(self, pixmap: QPixmap | None) -> None:
        self._pixmap_source = pixmap
        self._rescale()

    def set_side(self, side: int) -> None:
        self.setFixedSize(side, side)
        self._rescale()

    def _rescale(self) -> None:
        if self._pixmap_source is None or self._pixmap_source.isNull():
            self.clear()
            self.update()
            return
        self.setPixmap(
            self._pixmap_source.scaled(
                self.width(),
                self.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def paintEvent(self, event) -> None:  # type: ignore[override]
        if self._pixmap_source is not None and not self._pixmap_source.isNull():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        rect = self.rect()
        painter.fillRect(rect, QColor(Theme.BG_LIGHT))
        painter.setPen(QColor(Theme.TEXT_SECONDARY))
        glyph = QFont(painter.font())
        glyph.setPointSize(max(18, rect.height() // 3))
        painter.setFont(glyph)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "♪")
        painter.end()


class SidebarArtBox(QFrame):
    """A square cover with a small close button in its top-left corner."""

    # The user asked for the box to go away.
    closed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebarArtBox")
        self._canvas = _ArtCanvas()
        self._canvas.setParent(self)
        self._canvas.move(0, 0)

        # No layout: the close button sits *over* the art, which a layout
        # cannot express. Both children are absolutely placed instead, and
        # set_side is the one place that knows the geometry.
        self._close_btn = QPushButton("✕", self)
        self._close_btn.setObjectName("sidebarArtClose")
        self._close_btn.setFixedSize(_CLOSE_SIDE, _CLOSE_SIDE)
        self._close_btn.move(_CLOSE_INSET, _CLOSE_INSET)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setToolTip(self.tr("Hide the cover"))
        self._close_btn.clicked.connect(self.closed.emit)
        self._close_btn.raise_()

        self.set_side(_DEFAULT_SIDE)

    def set_side(self, side: int) -> None:
        """Set the box's square edge. The caller decides this, not the art."""
        self.setFixedSize(side, side)
        self._canvas.set_side(side)
        self._close_btn.raise_()

    def set_artwork(self, data: bytes | None) -> None:
        """Show *data* as the cover, or the placeholder when there is none."""
        pixmap: QPixmap | None = None
        if data:
            candidate = QPixmap()
            if candidate.loadFromData(data):
                pixmap = candidate
        self._canvas.set_source(pixmap)

    def has_artwork(self) -> bool:
        """Whether a real cover is showing rather than the placeholder."""
        source = self._canvas._pixmap_source
        return source is not None and not source.isNull()

    def art_rect(self) -> QRect:
        """The square the cover is drawn in — for tests that sample pixels."""
        return self._canvas.geometry()
