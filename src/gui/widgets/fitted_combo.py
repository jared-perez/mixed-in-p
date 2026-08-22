"""A combo box whose popup is never narrower than the box it drops from.

On a style whose combo popup is a *menu* — ``SH_ComboBox_Popup`` is 1 on both
QMacStyle and QFusionStyle — each row of the popup reserves a check column for
the tick beside the current item, and the popup is sized from the combo's
frame rather than from its items. Measured on macOS: the popup comes out 16px
narrower than the combo, and the row then spends 29px of what is left on the
check column. So a combo sized tightly to its own text opens onto its own
labels cut off, with the closed box looking perfectly correct.

That is what ``#compactCombo`` hit. Trimming ``padding-right`` from 30px to 4px
(the Convert format row needed the width, and the native drop-down is about
half what the old rule reserved) left the closed box fitting its widest item to
the pixel — and took away exactly the slack the check column had been
borrowing. All three Convert selectors opened 15px short in every one of the
twelve languages, and the Keyboard view switcher, sized from a constant, opened
short in ru, fr and ja ("Шестиугольная сетка" drew as "Шестиугольная сетк").

The rule is the modest one: **the popup is at least as wide as the combo.**
Three things recommend it over fitting the popup to its widest item.

It is bounded. The release switcher in the lookup dialog holds free text
("Artist - Title (Label, Cat#, 1998, Vinyl)"), and fitting *that* would drop a
screen-wide dropdown out of a 400px control.

It is enough, because the closed box is what was sized to the text in the first
place: its width is the text plus the padding plus the arrow, and handing all
of that to the popup covers the check column with room to spare on every combo
in the app — verified by rendering the real window in all twelve languages and
looking at the popups, not by arithmetic.

And it is a near no-op everywhere the bug does not exist, which matters because
the alternative is not. Asking the popup's delegate what a row reserves — the
obvious way to size this exactly — gets an answer QFusionStyle does not honour
when it paints: it claims 51px of menu chrome, draws its text at the left edge
like any list, and would have been handed 36px of dead margin for a popup that
was already correct. QWindowsStyle answers the question a third way again
(``SH_ComboBox_Popup`` 0, a list delegate, no chrome at all). A width the style
merely *claims* is not the width it *paints*, and only one of the three could
be checked by looking.
"""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox


class FittedComboBox(QComboBox):
    """A ``QComboBox`` that widens its popup to its own width before opening."""

    def showPopup(self) -> None:  # noqa: N802 - Qt naming
        self._fit_popup_width()
        super().showPopup()

    def _fit_popup_width(self) -> None:
        view = self.view()
        if view is None or self.count() == 0:
            return
        # A minimum, never a fixed width: a style that has already worked out a
        # wider popup for itself must keep it. Recomputed on every open rather
        # than set once, so a combo that is resized, retranslated or refilled
        # is measured as it now is.
        view.setMinimumWidth(self.width())
