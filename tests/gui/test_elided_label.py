"""ElidedLabel: the panel-header hint that truncates instead of running off.

What is worth pinning down is not that it draws an ellipsis — that is Qt's
``elidedText`` doing its job — but the three things around it that were easy to
get wrong and would fail silently: that the full text survives in ``text()``,
that it keeps out of the way when the window sizer turns wrapping back on, and
that the tooltip appears only when something is actually hidden.
"""

from __future__ import annotations

import pytest

from src.gui.widgets.elided_label import ElidedLabel

LONG = (
    "Drop a single audio file to see its acoustic spectrum. Frequency runs "
    "bottom (0 Hz) to top (Nyquist); time runs left to right."
)


@pytest.fixture
def label(qtbot):
    widget = ElidedLabel(LONG)
    qtbot.addWidget(widget)
    widget.show()
    return widget


def test_the_full_text_is_still_the_text(label):
    """Only the painting is shortened.

    Retranslation, the tests and anything reading the label back all go through
    text(); a version that stored the elided string here would quietly corrupt
    every one of them.
    """
    label.resize(120, 20)
    assert label.text() == LONG


def test_a_clipped_label_offers_the_rest_as_a_tooltip(label, qtbot):
    label.resize(120, 20)
    qtbot.waitUntil(lambda: label.toolTip() != "", timeout=1000)
    assert label.toolTip() == LONG


def test_a_label_with_room_has_no_tooltip(label):
    """A tooltip repeating text the user can already read is noise."""
    label.resize(4000, 20)
    assert label.toolTip() == ""


def test_wrapping_wins_when_the_sizer_turns_it_on(label):
    """The window sizer wraps these hints whenever the window is wide enough
    (theme.set_description_wrap), and eliding a wrapped label would throw away
    every line but the first. Wrapping mode must stay Qt's."""
    label.setWordWrap(True)
    label.resize(120, 200)

    assert label._fits() is True
    assert label.toolTip() == ""


def test_it_can_be_made_narrower_than_its_text(label):
    """The size policy is the load-bearing half: without it the label keeps
    demanding its full width and pushes the panel wider instead of eliding,
    which is the original bug one level up."""
    label.resize(80, 20)
    assert label.width() == 80
