"""A page scroll must not set the value of a control it passes over.

Reported against the Settings panel: scrolling down the page with the pointer
over Lowest/Highest BPM spun the number instead of moving the page.

Read ``src/gui/widgets/wheel_guard.py`` before changing any of this. The one
thing to know here is why every test asserts the **scroll position** as well
as the value: a guard that merely swallowed the wheel would leave the value
alone and kill the page scroll, and every "the value did not change"
assertion would pass against it.
"""

from __future__ import annotations

import pathlib

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.gui.widgets.fitted_combo import FittedComboBox
from src.gui.widgets.wheel_guard import NoWheelSlider, NoWheelSpinBox


def wheel_over(widget, dy: int = -120) -> None:
    """One notch of the wheel with the pointer over ``widget``."""
    centre = widget.rect().center()
    QApplication.sendEvent(
        widget,
        QWheelEvent(
            QPointF(centre),
            widget.mapToGlobal(centre).toPointF(),
            QPoint(0, dy),
            QPoint(0, dy),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        ),
    )


@pytest.fixture
def page(qtbot):
    """A scrolling page with a guarded control halfway down it.

    Tall enough to scroll: the whole point is a control the pointer crosses on
    its way past, and a page that fits its viewport has nothing to cross.
    """

    def build(make_control):
        area = QScrollArea()
        area.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        control = None
        for index in range(40):
            widget = make_control() if index == 20 else QWidget()
            widget.setMinimumHeight(24)
            if index == 20:
                control = widget
            layout.addWidget(widget)
        area.setWidget(content)
        qtbot.addWidget(area)
        area.resize(320, 200)
        area.show()
        qtbot.wait(10)
        assert area.verticalScrollBar().maximum() > 0, "the page must be scrollable"
        return area, control

    return build


class TestTheWheelScrollsThePage:
    def test_a_spin_box_keeps_its_value_and_the_page_moves(self, page):
        area, spin = page(lambda: NoWheelSpinBox())
        spin.setRange(0, 500)
        spin.setValue(99)
        bar = area.verticalScrollBar()

        wheel_over(spin)

        assert spin.value() == 99
        assert bar.value() > 0

    def test_a_combo_keeps_its_selection_and_the_page_moves(self, page):
        area, combo = page(lambda: FittedComboBox())
        combo.addItems(["one", "two", "three"])
        combo.setCurrentIndex(1)
        bar = area.verticalScrollBar()

        wheel_over(combo)

        assert combo.currentIndex() == 1
        assert bar.value() > 0

    def test_a_slider_keeps_its_value_and_the_page_moves(self, page):
        area, slider = page(lambda: NoWheelSlider(Qt.Orientation.Horizontal))
        slider.setRange(0, 100)
        slider.setValue(70)
        bar = area.verticalScrollBar()

        wheel_over(slider)

        assert slider.value() == 70
        assert bar.value() > 0

    def test_it_scrolls_back_up_again(self, page):
        area, spin = page(lambda: NoWheelSpinBox())
        bar = area.verticalScrollBar()
        for _ in range(4):
            wheel_over(spin, dy=-120)
        scrolled = bar.value()
        assert scrolled > 0

        for _ in range(4):
            wheel_over(spin, dy=120)

        assert bar.value() < scrolled

    def test_the_wheel_is_harmless_outside_a_scroll_area(self, qtbot):
        """No ancestor to hand it to is not a crash, and not a value change."""
        spin = NoWheelSpinBox()
        qtbot.addWidget(spin)
        spin.setRange(0, 500)
        spin.setValue(99)
        spin.show()

        wheel_over(spin)

        assert spin.value() == 99


class TestTheWheelNoLongerTakesFocus:
    """Qt hands a ``WheelFocus`` widget the caret *before* delivering the
    wheel (``giveFocusAccordingToFocusPolicy``), so a spin box grabbed the
    keyboard during a page scroll even once it stopped changing its value —
    which is the "it starts editing" half of the report. It cannot be driven
    from a synthetic event, so the mechanism is what is asserted.
    """

    def test_a_guarded_spin_box_is_not_wheel_focusable(self, qtbot):
        spin = NoWheelSpinBox()
        qtbot.addWidget(spin)
        assert QSpinBox().focusPolicy() == Qt.FocusPolicy.WheelFocus  # the default
        assert spin.focusPolicy() == Qt.FocusPolicy.StrongFocus

    def test_a_policy_without_the_wheel_bit_is_left_alone(self, qtbot):
        """A slider's policy comes from a style hint; don't overwrite it."""
        slider = NoWheelSlider(Qt.Orientation.Horizontal)
        qtbot.addWidget(slider)
        from PySide6.QtWidgets import QSlider

        assert slider.focusPolicy() == QSlider(
            Qt.Orientation.Horizontal
        ).focusPolicy()
        assert slider.focusPolicy() != Qt.FocusPolicy.WheelFocus


class TestNothingInTheGuiIsLeftOnTheWheel:
    """The rule is app-wide, so a control added later must not opt out of it
    by accident. Same shape as the bare-``QComboBox`` ban in
    ``test_combo_popup_width`` — and combos are covered by that one, since
    every combo in the GUI is a ``FittedComboBox`` and that carries the guard.
    """

    @pytest.mark.parametrize(
        "needle, replacement",
        [("QSpinBox()", "NoWheelSpinBox"), ("QSlider(", "NoWheelSlider")],
    )
    def test_no_bare_wheel_control_is_constructed_in_the_gui(self, needle, replacement):
        root = pathlib.Path(__file__).resolve().parents[2] / "src" / "gui"
        offenders = [
            f"{path.relative_to(root)}:{number}"
            # encoding="utf-8" explicitly: the default is the locale encoding,
            # cp1252 on Windows, and this source is full of em-dashes — without
            # it the guard dies before it checks anything on that platform.
            for path in sorted(root.rglob("*.py"))
            if path.name != "wheel_guard.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            )
            if needle in line and "NoWheel" not in line and "import" not in line
        ]
        assert offenders == [], (
            f"these construct a bare {needle.rstrip('(')}, which steals the wheel "
            f"from a page scrolling underneath it; use {replacement}: {offenders}"
        )
