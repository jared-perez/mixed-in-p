"""A combo's popup is never narrower than the combo itself.

Read ``src/gui/widgets/fitted_combo.py`` first. The short version: on a style
whose combo popup is a menu — QMacStyle and QFusionStyle both say so — the
popup is sized from the combo's *frame*, coming out narrower than the combo,
and each row then spends part of what is left on the check column. So a combo
sized tightly to its own text opens onto its own labels cut off while the
closed box looks perfectly correct. That is what ``#compactCombo``'s trimmed
padding did to the three Convert selectors, in all twelve languages, and to
the Keyboard view switcher in ru, fr and ja.

What this suite can and cannot say about it. It runs offscreen, which resolves
to Fusion, and there the popup already comes out exactly as wide as the combo
— so measuring an open popup and finding it wide enough passes just as well
against the broken build. The assertions below are on the *mechanism* (the
minimum the widget imposes, which is 0 without the fix) rather than on the
resulting pixels, and the pixels were settled the only way they can be: by
rendering the real window in all twelve languages on macOS and looking at the
popups, before and against a control with the fix disabled.
"""

import pytest
from PySide6.QtWidgets import QComboBox

from src.gui.widgets.fitted_combo import FittedComboBox


@pytest.fixture
def combo(qtbot):
    box = FittedComboBox()
    box.addItems(["Keep source", "96 kHz (DVD)", "44.1 kHz (CD)"])
    qtbot.addWidget(box)
    box.show()
    qtbot.waitExposed(box)
    return box


class TestPopupWidth:
    def test_the_popup_may_not_be_narrower_than_the_box(self, combo):
        combo._fit_popup_width()
        assert combo.view().minimumWidth() == combo.width()

    def test_it_is_a_minimum_not_a_ceiling(self, combo):
        """A style that has worked out a wider popup keeps it."""
        combo._fit_popup_width()
        assert combo.view().maximumWidth() > combo.width()

    def test_opening_the_popup_applies_it(self, combo, qtbot):
        combo.showPopup()
        try:
            assert combo.view().width() >= combo.width()
        finally:
            combo.hidePopup()

    def test_it_is_measured_again_on_every_open(self, combo, qtbot):
        """A width set once is wrong the moment the row is laid out again.

        The Convert selectors are re-laid-out whenever the target format
        switches between MP3 and the lossless three, so a popup pinned to the
        width the combo had at construction would be the old width.
        """
        combo.resize(combo.width() + 120, combo.height())
        combo._fit_popup_width()
        assert combo.view().minimumWidth() == combo.width()

    def test_an_empty_combo_asks_for_nothing(self, qtbot):
        box = FittedComboBox()
        qtbot.addWidget(box)
        box._fit_popup_width()
        assert box.view().minimumWidth() == 0


class TestEveryComboIsFitted:
    """No bare ``QComboBox`` anywhere in the GUI.

    The defect is invisible to this suite (Fusion does not reproduce it) and
    invisible to ``visual_pass`` — which measures widgets that are on screen,
    and a popup is neither a child of the panel nor open when it looks. So a
    plain combo added later would ship cut off with nothing to catch it.
    """

    def test_no_plain_combo_is_constructed_in_the_gui(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[2] / "src" / "gui"
        offenders = [
            f"{path.relative_to(root)}:{number}"
            for path in sorted(root.rglob("*.py"))
            for number, line in enumerate(path.read_text().splitlines(), 1)
            if "QComboBox()" in line
        ]
        assert offenders == [], (
            "these construct a bare QComboBox, whose popup opens cut off on "
            f"macOS; use FittedComboBox instead: {offenders}"
        )
