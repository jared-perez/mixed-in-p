"""Show a cover at size, over the window, until the next click.

Deliberately not a dialog. A modal would take the keyboard, stack a title bar
and a close button over a picture, and make "look at this for a second" into a
thing you have to dismiss properly. This is a child of the window that paints
over it and goes away when touched — the same posture as ``BackgroundOverlay``,
which is also a full-parent child widget that draws and gets out of the way.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from ..styles.theme import Theme

# How much of the window the cover may take, leaving enough of the app visible
# behind the dimming that it reads as an overlay rather than a new screen.
_VIEWPORT_FRACTION = 0.85

# The smallest a cover is blown up to. Below this an "enlarged" view of a
# postage-stamp cover renders at nearly its inline size and looks broken; above
# the source's own size it is inventing pixels, so this is the one place
# upscaling is allowed and it is capped hard.
_MIN_ENLARGED = 320

# Dimming behind the cover. Enough to lift the picture off the panel, not so
# much that the app underneath stops being visible.
_SCRIM_ALPHA = 200

# Gap between the cover and the hint under it.
_HINT_GAP = 12


class ArtworkLightbox(QWidget):
    """The cover, centred over the whole window, dismissed by any click."""

    def __init__(self, source: QPixmap, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("artworkLightbox")
        # `app.qss.template` opens with a global `QWidget { background-color:
        # BG_DARK }`, so without this the scrim is painted opaque before
        # paintEvent runs and the window behind it disappears entirely.
        self.setStyleSheet("#artworkLightbox { background: transparent; }")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._source = source
        self._scaled = QPixmap()
        self._hint = self.tr("Click anywhere to close")
        # The window is what gets covered, and it can be resized while this is
        # up. Following it is cheaper than the alternatives: closing on resize
        # loses the picture for a window nudge, and not following leaves a
        # scrim over part of a window, which reads as a paint bug.
        parent.installEventFilter(self)

    # ------------------------------------------------------------------ show

    def show_over_parent(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.setGeometry(parent.rect())
        self._rescale()
        self.show()
        self.raise_()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _rescale(self) -> None:
        """Fit the cover to the window, within the bounds set above."""
        if self._source.isNull():
            self._scaled = QPixmap()
            return
        box_w = int(self.width() * _VIEWPORT_FRACTION)
        box_h = int(self.height() * _VIEWPORT_FRACTION)
        if box_w < 1 or box_h < 1:
            return
        # Never past the source's own size — an enlargement that invents pixels
        # is a blurry lie about what the file contains — except up to
        # _MIN_ENLARGED, where a cover too small to be worth opening otherwise
        # is worth a little softness.
        ceiling = max(self._source.width(), self._source.height(), _MIN_ENLARGED)
        box_w = min(box_w, ceiling)
        box_h = min(box_h, ceiling)
        self._scaled = self._source.scaled(
            box_w,
            box_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    # --------------------------------------------------------------- events

    def eventFilter(self, watched, event) -> bool:
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parentWidget().rect())
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._rescale()

    def mousePressEvent(self, event) -> None:
        # Any button, anywhere: this is a look, not a mode.
        event.accept()
        self.close()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Space, Qt.Key.Key_Return):
            event.accept()
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        parent = self.parentWidget()
        if parent is not None:
            parent.removeEventFilter(self)
        super().closeEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, _SCRIM_ALPHA))
        if self._scaled.isNull():
            return
        x = (self.width() - self._scaled.width()) // 2
        y = (self.height() - self._scaled.height()) // 2
        painter.drawPixmap(x, y, self._scaled)
        painter.setPen(QColor(Theme.TEXT_SECONDARY))
        painter.drawText(
            QRect(0, y + self._scaled.height() + _HINT_GAP, self.width(), 24),
            int(Qt.AlignmentFlag.AlignHCenter) | int(Qt.AlignmentFlag.AlignTop),
            self._hint,
        )
