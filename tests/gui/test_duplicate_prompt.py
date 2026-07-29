"""The duplicate-tracks prompt: button sizing and verdict mapping.

Sizing is asserted as a *measurement*, not a rendering: the offscreen platform
does not reproduce QMacStyle (see tests/gui/README.md), but font metrics and
the widths the widget settles on are real, and the bug being guarded against
was purely a width-vs-text arithmetic error.
"""

import pytest
from PySide6.QtWidgets import QMessageBox

from src.gui.widgets.dialogs.duplicate_policy import DuplicatePrompt


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

    def test_a_short_label_keeps_the_standard_button_width(self, box):
        """Cancel must not shrink below what every other dialog uses."""
        cancel = box.button(QMessageBox.StandardButton.Cancel)
        assert cancel.minimumWidth() >= 80

    def test_sizing_is_measured_not_hardcoded(self, qtbot):
        """A translated label is longer or shorter than the English one, so a
        fixed width would clip it; the width has to track the text."""
        short = DuplicatePrompt(None, 1, 1, "x")
        qtbot.addWidget(short)
        wide = short.addButton(
            "A Very Much Longer Button Label Indeed", QMessageBox.ButtonRole.ActionRole
        )
        from src.gui.widgets.dialogs.duplicate_policy import _fit_buttons

        _fit_buttons(short)
        assert wide.minimumWidth() > short.button(
            QMessageBox.StandardButton.Cancel
        ).minimumWidth()


class TestVerdict:
    def test_add_returns_true(self, box, monkeypatch):
        monkeypatch.setattr(box, "exec", lambda: None)
        monkeypatch.setattr(box, "clickedButton", lambda: box._add_btn)
        assert box.ask() is True

    def test_skip_returns_false(self, box, monkeypatch):
        monkeypatch.setattr(box, "exec", lambda: None)
        monkeypatch.setattr(box, "clickedButton", lambda: box._skip_btn)
        assert box.ask() is False

    def test_anything_else_is_a_cancel(self, box, monkeypatch):
        """Esc is wired to Cancel, and a closed box reports no button at all —
        both must read as "do nothing", never as a silent Add."""
        monkeypatch.setattr(box, "exec", lambda: None)
        monkeypatch.setattr(box, "clickedButton", lambda: None)
        assert box.ask() is None

    def test_skip_is_the_default_and_cancel_takes_escape(self, box):
        assert box.defaultButton() is box._skip_btn
        assert box.escapeButton() is box.button(QMessageBox.StandardButton.Cancel)


class TestMessage:
    def test_it_names_the_playlist(self, box):
        assert '"New Playlist"' in box.text()

    def test_a_partial_collision_offers_the_rest(self, qtbot):
        prompt = DuplicatePrompt(None, 3, 8, "Set")
        qtbot.addWidget(prompt)
        assert "only the rest" in prompt.informativeText()

    def test_a_total_collision_does_not(self, box):
        assert "only the rest" not in box.informativeText()
