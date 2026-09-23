"""A transient card of text floated over the window's pages."""

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtWidgets import QLabel, QWidget

from ..styles.theme import Theme


class FloatingNotice(QLabel):
    """Say one thing over the pages for 3s, then get out of the way.

    The app has no status bar, and a panel's progress line is owned by its
    run (a starting worker overwrites it a moment later), so this is where a
    one-off word to the user goes — above all the "I skipped that, and here
    is why" that would otherwise reach only the log.

    It belongs to the window, not to a panel: what it reports often happens
    on a page the user is not looking at (an auto-rename after the user has
    moved on, a sidebar drop, which holds the current page on purpose). It is
    a child of `parent` centred over `anchor` (the page stack), and follows
    the anchor's resizes and moves itself. Styled as #floatingNotice in
    app.qss.template; the card carries its own background because it can
    land over anything, the Player's visuals included.
    """

    TIMEOUT_MS = 3000
    # Inner margin of the card, and the QSS border drawn outside it.
    _MARGIN_H = 20
    _MARGIN_V = 12
    _BORDER = 1
    _MAX_SHARE = 0.6

    def __init__(self, parent: QWidget, anchor: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("floatingNotice")
        self._anchor = anchor
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # It carries sentences, not two words, so it wraps rather than
        # running off both edges of the pages.
        self.setWordWrap(True)
        self.setContentsMargins(self._MARGIN_H, self._MARGIN_V,
                                self._MARGIN_H, self._MARGIN_V)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.TIMEOUT_MS)
        self._timer.timeout.connect(self.dismiss)
        anchor.installEventFilter(self)

    def show_text(self, text: str) -> None:
        """Show text centred over the pages and (re)start the timeout."""
        self.setText(text)
        self.reposition()
        self.show()
        self.raise_()  # above the pages, whichever is current
        self._timer.start()

    def dismiss(self) -> None:
        self._timer.stop()
        self.hide()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._anchor and event.type() in (QEvent.Type.Resize, QEvent.Type.Move):
            self.reposition()
        return False

    def reposition(self) -> None:
        """Size and centre the card over the anchor.

        Sized by hand rather than by adjustSize(): word wrap is on, so the
        label is only as tall as the width it is given, and it is floated
        rather than laid out — there is no parent to ask heightForWidth for
        it. Measured off the string with QFontMetrics, never asked of the
        label, and capped at the anchor so a long sentence wraps instead of
        overhanging both edges.
        """
        self.ensurePolished()  # the QSS font, before measuring with it
        chrome_h = 2 * (self._MARGIN_H + self._BORDER)
        chrome_v = 2 * (self._MARGIN_V + self._BORDER)
        anchor = self._anchor
        # At most _MAX_SHARE of the pages wide: a card, not a banner.
        available = max(1, min(int(anchor.width() * self._MAX_SHARE),
                               anchor.width() - Theme.PADDING * 2) - chrome_h)
        metrics = self.fontMetrics()
        text = self.text()
        # +2: an advance can round just under what the wrapper needs, which
        # would break a fitting line in two.
        width = min(available, metrics.horizontalAdvance(text) + 2)
        rect = metrics.boundingRect(
            0, 0, width, 0,
            int(Qt.TextFlag.TextWordWrap) | int(Qt.AlignmentFlag.AlignCenter),
            text,
        )
        self.resize(width + chrome_h, rect.height() + chrome_v)
        origin = anchor.mapTo(self.parentWidget(), QPoint(0, 0))
        x = origin.x() + (anchor.width() - self.width()) // 2
        y = origin.y() + (anchor.height() - self.height()) // 2
        self.move(max(0, x), max(0, y))
