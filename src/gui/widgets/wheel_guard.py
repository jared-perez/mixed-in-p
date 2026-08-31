"""Controls that keep their value when the page scrolls under them.

A ``QSpinBox``, ``QSlider`` or ``QComboBox`` accepts a wheel event and steps
its value. Put one inside a ``QScrollArea`` and that is a bug rather than a
feature: the user is scrolling the *page*, the pointer happens to pass over
the control, and the wheel silently sets a value they never aimed at. It was
reported against the Settings panel's Lowest/Highest BPM boxes, which sit in
the middle of a page most people scroll straight past.

Two separate things go wrong on the way past, and stopping only one of them
leaves the report standing.

**The value.** The wheel is *accepted* by the control, so the scroll area
never sees it — the page stops moving and the number moves instead. The
control therefore has to hand the wheel on, and it does so by **sending it to
the enclosing scroll area's viewport itself** rather than by calling
``ignore()`` and trusting Qt to walk the parent chain. Two reasons, and the
second is why the obvious one-liner was backed out.

Swallowing it with an ``eventFilter`` that returns True stops the value
changing *and* stops the page scrolling, which trades one wrong behaviour for
another. That much is well known. What is not is that ``ignore()`` cannot be
checked: ``QApplication``'s wheel propagation loop runs only for a
**spontaneous** event, i.e. one that came from the window system, and a
``QWheelEvent`` a test constructs is never spontaneous and PySide6 exposes no
way to make it so. Measured here — with an event filter on the content
widget, the viewport and the scroll area — an ignored synthetic wheel reaches
**none** of the three, while the same wheel sent straight at the viewport
scrolls it 180px. So an ``ignore()`` version behaves identically, in every
test that can be written for it, to one that swallows the event and leaves the
page dead: the assertion that the value did not change passes, and the half
that matters is unobservable. Forwarding by hand is the same behaviour on the
path the user is on, and the only one that can be shown to work.

The forwarded event is a fresh ``QWheelEvent`` with the position remapped into
the viewport, and the original is then **accepted** rather than ignored — so
if Qt's own loop does run (it will, on a real spontaneous wheel) it stops here
instead of scrolling the page a second time.

**The focus.** Qt gives the wheel its own focus rule: ``Qt::WheelFocus``
means "this widget takes keyboard focus when the wheel turns over it", and
``QApplicationPrivate::giveFocusAccordingToFocusPolicy`` applies it *before*
the event is delivered — so a spin box grabs the caret during a page scroll
even though it never handled the wheel. ``QSpinBox`` is 15 (``WheelFocus``)
out of the box while ``QSlider`` is 11 and ``QComboBox`` 1, so the bit is
stripped where it is set rather than every policy being forced to
``StrongFocus``: a slider's focus policy comes from a style hint
(``SH_Button_FocusPolicy``) and overwriting it would move focus rings around
on some platforms for no reason.

The rule this settles on is the blanket one — **the wheel scrolls, it never
sets a value** — and not the narrower "unless the control has focus", for
two reasons. A focus gate leaves a live residual on exactly the control where
it hurts most: click a combo to pick a language, and that combo now has focus
and is armed to be changed by the next scroll that passes over it. And it
would make the *same panel* answer two ways — the Player's page scrolls while
its pinned footer does not — so "does the wheel set values here?" would depend
on where in a panel the pointer is. One rule that is always true is worth more
than a gesture nobody reports missing: every value here is still settable by
dragging, typing, the arrow keys and the spin box's own steppers, and an open
combo popup is a separate window whose list still scrolls normally.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QSlider, QSpinBox


class WheelGuardMixin:
    """Mix in ahead of a Qt control to take it off the wheel.

    Ahead of it in the bases, so ``__init__`` runs before the control is used
    and ``wheelEvent`` wins the lookup.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if self.focusPolicy() == Qt.FocusPolicy.WheelFocus:
            # WheelFocus IS StrongFocus plus the wheel bit, so this swap is
            # the whole of "drop the wheel bit" with no arithmetic to get
            # wrong -- and it leaves any other policy the style chose alone.
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _scrolling_ancestor(self) -> QAbstractScrollArea | None:
        """The scroll area this control sits inside, if any."""
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QAbstractScrollArea):
                return parent
            parent = parent.parentWidget()
        return None

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt naming
        area = self._scrolling_ancestor()
        if area is None:
            # Nothing above us scrolls, so there is nobody to hand it to. The
            # wheel simply does nothing here, which is the whole rule.
            event.ignore()
            return
        viewport = area.viewport()
        forwarded = QWheelEvent(
            QPointF(self.mapTo(viewport, event.position().toPoint())),
            event.globalPosition(),
            event.pixelDelta(),
            event.angleDelta(),
            event.buttons(),
            event.modifiers(),
            event.phase(),
            event.inverted(),
            event.source(),
        )
        QApplication.sendEvent(viewport, forwarded)
        # Accept, not ignore: we have dealt with it by delegating, so Qt's own
        # parent-chain walk must not deliver it to the viewport a second time.
        event.accept()


class NoWheelSpinBox(WheelGuardMixin, QSpinBox):
    """A ``QSpinBox`` that a page scroll passes straight over."""


class NoWheelSlider(WheelGuardMixin, QSlider):
    """A ``QSlider`` that a page scroll passes straight over."""
