"""The duplicate-tracks prompt: button sizing and verdict mapping.

Sizing is asserted as a *measurement*, not a rendering: the offscreen platform
does not reproduce QMacStyle (see tests/gui/README.md), but font metrics and
the widths the widget settles on are real, and the bug being guarded against
was purely a width-vs-text arithmetic error.
"""

import pytest
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialogButtonBox, QMessageBox

from src.gui.widgets.dialogs.duplicate_policy import (
    _BUTTON_MIN,
    DuplicatePrompt,
    _fit_buttons,
)


@pytest.fixture
def box(qtbot):
    prompt = DuplicatePrompt(None, 1, 1, "New Playlist")
    qtbot.addWidget(prompt)
    return prompt


class TestButtonsFitTheirLabels:
    """Regression: the stylesheet's 8px/16px padding is invisible to the
    native size hint, so a label wider than the 80px QDialogButtonBox minimum
    was drawn into a narrower contents rect — and QMessageBox centres rather
    than eliding, clipping it at BOTH ends ("kip Duplicate")."""

    def test_every_button_is_wider_than_its_text(self, box):
        for button in box.buttons():
            label = button.text().replace("&", "")
            text_width = button.fontMetrics().horizontalAdvance(label)
            assert button.minimumWidth() > text_width, label

    def test_the_padding_still_fits_around_the_text(self, box):
        """Not just wider — wide enough for the stylesheet's own padding,
        or the text would sit flush against the border."""
        for button in box.buttons():
            label = button.text().replace("&", "")
            text_width = button.fontMetrics().horizontalAdvance(label)
            assert button.minimumWidth() - text_width >= 32, label

    def test_no_button_shrinks_below_the_standard_width(self, box):
        """However short a label gets translated, a button here is still the
        size every other dialog in the app uses."""
        for button in box.buttons():
            assert button.minimumWidth() >= _BUTTON_MIN, button.text()

    def test_sizing_is_measured_not_hardcoded(self, qtbot):
        """A translated label is longer or shorter than the English one, so a
        fixed width would clip it; the width has to track the text."""
        short = DuplicatePrompt(None, 1, 1, "x")
        qtbot.addWidget(short)
        wide = short.addButton(
            "A Very Much Longer Button Label Indeed", QMessageBox.ButtonRole.ActionRole
        )
        _fit_buttons(short)
        assert wide.minimumWidth() > _BUTTON_MIN
        assert wide.minimumWidth() > short._skip_btn.minimumWidth()


class TestTheBoxIsNarrow:
    """The Cancel button was 90px of width buying an outcome the window's own
    close box already gives, so it went. Measured offscreen/Fusion, the hint
    went 474x116 -> 384x116."""

    def test_there_are_only_two_buttons(self, box):
        assert len(box.buttons()) == 2
        assert box.button(QMessageBox.StandardButton.Cancel) is None

    def test_it_is_narrower_than_it_was_with_cancel(self, box, qtbot):
        """Not a pixel count — a comparison against the same box wearing the
        button that used to be there, so it survives a restyle.

        Measured on the *button row* rather than on the whole box, because a
        QMessageBox is as wide as the wider of its text and its buttons, and
        which of the two wins is a fact about the platform's font. Under
        Fusion on macOS the buttons win and the whole box shrank 474 -> 384;
        on Windows the message text is 581px on its own and swallows the
        change, leaving 581 against 586 — a five-pixel margin that any
        restyle, translator or DPI change flips, and did, intermittently and
        only in a full run. The button row states the same thing with the
        text's width taken out of it: 442 against 564 here.
        """
        wide = DuplicatePrompt(None, 1, 1, "New Playlist")
        qtbot.addWidget(wide)
        wide.addButton(QMessageBox.StandardButton.Cancel)
        _fit_buttons(wide)

        row = box.findChild(QDialogButtonBox)
        wide_row = wide.findChild(QDialogButtonBox)
        assert row.sizeHint().width() < wide_row.sizeHint().width()
        # ...and nothing else grew to spend the width the buttons gave back.
        assert box.sizeHint().width() <= wide.sizeHint().width()


class TestVerdict:
    def test_add_returns_true(self, box, monkeypatch):
        monkeypatch.setattr(box, "exec", lambda: None)
        monkeypatch.setattr(box, "clickedButton", lambda: box._add_btn)
        assert box.ask() is True

    def test_skip_returns_false(self, box, monkeypatch):
        monkeypatch.setattr(box, "exec", lambda: None)
        monkeypatch.setattr(box, "clickedButton", lambda: box._skip_btn)
        assert box.ask() is False

    def test_no_button_at_all_abandons_the_add(self, box, monkeypatch):
        """A box that reports no clicked button was closed, not answered, and
        must read as "do nothing" — never as a silent Add."""
        monkeypatch.setattr(box, "exec", lambda: None)
        monkeypatch.setattr(box, "clickedButton", lambda: None)
        assert box.ask() is None

    def test_skip_is_the_default(self, box):
        assert box.defaultButton() is box._skip_btn


class TestLeavingWithoutAnswering:
    """The two ways out that are not a button, which now differ on purpose."""

    def test_escape_skips(self, box):
        """Qt detects the lone RejectRole button as the escape button once
        Cancel is gone, so Esc lands on Skip — the conservative answer, and
        already the default.

        Read through the *base class's* close path, which answers with that
        same detected button: Qt exposes it nowhere public (``escapeButton()``
        returns only an explicitly set one, and here that is None), the
        detection runs on show, and driving the real key needs an ``exec()``
        whose nested event loop pumps every other test's pending events —
        which measurably destabilised the suite.
        """
        box.show()
        QMessageBox.closeEvent(box, QCloseEvent())
        assert box.clickedButton() is box._skip_btn

    def test_closing_the_window_abandons_everything(self, box, qtbot):
        """The close box is not a choice. Qt would have answered it with the
        detected escape button (Skip); ``DuplicatePrompt.closeEvent`` goes
        straight to QDialog so no button is recorded and ``ask()`` says None.

        Run it with the override removed and this returns Skip instead."""
        box.show()
        box.close()
        assert box.clickedButton() is None
        assert box.isHidden()


class TestMessage:
    def test_it_names_the_playlist(self, box):
        assert '"New Playlist"' in box.text()

    def test_a_partial_collision_offers_the_rest(self, qtbot):
        prompt = DuplicatePrompt(None, 3, 8, "Set")
        qtbot.addWidget(prompt)
        assert "only the rest" in prompt.informativeText()

    def test_a_total_collision_does_not(self, box):
        assert "only the rest" not in box.informativeText()
