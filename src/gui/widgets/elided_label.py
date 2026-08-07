"""A label that truncates with an ellipsis instead of running off the panel.

``QLabel`` has no elide mode: give it more text than it has room for and it
simply draws past its own edge, with no ellipsis to show that it did. The panel
header hints are exactly that shape — a sentence sitting beside a title, on one
line, in whatever width is left over — so they were being cut mid-word **in
English**, and every translation inherited it and made it worse. Measured at
the default window size, the Spectrum hint overran by 463px in English and by
up to 964px translated.

Eliding fixes all twelve languages at once and needs no copy changes, which is
why it beat the alternatives: wrapping would make the header a different height
in every language, and shortening the English would re-open six strings across
eleven translations to solve a layout problem.

The full text stays in ``text()`` — only the painting is shortened — so
retranslation, tests and anything reading the label back are unaffected.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QLabel, QSizePolicy, QStyleOption, QWidget


class ElidedLabel(QLabel):
    """A single-line QLabel that elides on the right when short of room.

    Not for wrapped text: a label that wraps grows downward instead and has no
    need of this.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        # Ignored, so the layout may make it narrower than its text wants.
        # Without this the label keeps demanding its full width and pushes the
        # panel wider instead of eliding — which is the bug, one level up.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def _fits(self) -> bool:
        if self.wordWrap():
            return True
        return (
            self.fontMetrics().horizontalAdvance(self.text())
            <= self.contentsRect().width()
        )

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        # Wrapping is Qt's job and the window sizer turns it on whenever there
        # is room (see theme.set_description_wrap). This class only improves
        # the *other* mode — the deliberate single-line clip used once the
        # window narrows, which cut mid-word with nothing to show it had.
        if self.wordWrap():
            super().paintEvent(event)
            return

        painter = QPainter(self)
        # The stylesheet sets these labels' colour, which lands in the palette
        # at polish time. Painting by hand means picking it up explicitly —
        # miss this and every hint reverts to the default foreground.
        option = QStyleOption()
        option.initFrom(self)
        painter.setPen(option.palette.color(self.foregroundRole()))

        rect = self.contentsRect()
        painter.drawText(
            rect,
            int(self.alignment()),
            self.fontMetrics().elidedText(
                self.text(), Qt.TextElideMode.ElideRight, rect.width()
            ),
        )

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        # Only while it is actually cut off: a tooltip repeating text the user
        # can already read in full is noise.
        self.setToolTip("" if self._fits() else self.text())
