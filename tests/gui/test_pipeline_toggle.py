"""The step-toggle triangle: shape, states, tooltips.

Structure only. The suite runs offscreen with no application stylesheet and
under Fusion rather than the platform style, so nothing here may assert a
pixel or a width — how the triangle *looks* was settled by rendering it and
looking (see the W2 note in the handoff).
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt

from src.gui.widgets.pipeline_toggle import PipelineToggle


def test_it_is_a_checkable_button(qtbot):
    toggle = PipelineToggle()
    qtbot.addWidget(toggle)
    assert toggle.isCheckable()
    assert not toggle.isChecked()


def test_clicking_toggles_and_emits(qtbot):
    toggle = PipelineToggle()
    qtbot.addWidget(toggle)
    seen: list[bool] = []
    toggle.toggled.connect(seen.append)
    toggle.click()
    assert seen == [True]
    assert toggle.isChecked()


def test_the_two_sizes_are_square_and_fixed(qtbot):
    panel = PipelineToggle(PipelineToggle.SIZE_PANEL)
    mini = PipelineToggle(PipelineToggle.SIZE_MINI)
    qtbot.addWidget(panel)
    qtbot.addWidget(mini)
    for toggle, size in ((panel, PipelineToggle.SIZE_PANEL), (mini, PipelineToggle.SIZE_MINI)):
        assert toggle.sizeHint().width() == size
        assert toggle.sizeHint().height() == size
        assert toggle.minimumSize() == toggle.maximumSize()
    assert mini.sizeHint().width() < panel.sizeHint().width()


def test_the_hit_area_is_the_triangle_not_the_box(qtbot):
    """The corners the triangle leaves empty belong to whatever is behind it."""
    toggle = PipelineToggle(PipelineToggle.SIZE_PANEL)
    qtbot.addWidget(toggle)
    size = PipelineToggle.SIZE_PANEL
    # Low and central: inside. Top-left corner: outside (the apex is centred).
    assert toggle.hitButton(QPoint(size // 2, size - 3))
    assert not toggle.hitButton(QPoint(1, 1))
    assert not toggle.hitButton(QPoint(size - 2, 2))


def test_a_click_in_a_dead_corner_does_not_toggle(qtbot):
    toggle = PipelineToggle(PipelineToggle.SIZE_PANEL)
    qtbot.addWidget(toggle)
    toggle.show()
    qtbot.mouseClick(toggle, Qt.MouseButton.LeftButton, pos=QPoint(1, 1))
    assert not toggle.isChecked()
    qtbot.mouseClick(
        toggle,
        Qt.MouseButton.LeftButton,
        pos=QPoint(PipelineToggle.SIZE_PANEL // 2, PipelineToggle.SIZE_PANEL - 3),
    )
    assert toggle.isChecked()


def test_the_tooltip_states_what_the_next_click_does(qtbot):
    toggle = PipelineToggle()
    qtbot.addWidget(toggle)
    toggle.set_step_tooltips("Include this step", "Skip this step")
    assert toggle.toolTip() == "Include this step"
    toggle.setChecked(True)
    assert toggle.toolTip() == "Skip this step"
    toggle.setChecked(False)
    assert toggle.toolTip() == "Include this step"


def test_tooltips_set_while_checked_land_the_right_way_round(qtbot):
    toggle = PipelineToggle()
    qtbot.addWidget(toggle)
    toggle.setChecked(True)
    toggle.set_step_tooltips("Include this step", "Skip this step")
    assert toggle.toolTip() == "Skip this step"


def test_the_tooltip_follows_a_reflected_state_with_signals_blocked(qtbot):
    """The case this widget exists in: a step shows twice and each mirror
    reflects the other inside blockSignals, so a tooltip hung off `toggled`
    changes the picture and keeps the other state's sentence."""
    toggle = PipelineToggle()
    qtbot.addWidget(toggle)
    toggle.set_step_tooltips("Include this step", "Skip this step")

    blocked = toggle.blockSignals(True)
    toggle.setChecked(True)
    toggle.blockSignals(blocked)
    assert toggle.toolTip() == "Skip this step"

    blocked = toggle.blockSignals(True)
    toggle.setChecked(False)
    toggle.blockSignals(blocked)
    assert toggle.toolTip() == "Include this step"


def test_it_paints_in_every_state_without_a_stylesheet(qtbot):
    """A self-painted button still has to survive being drawn."""
    toggle = PipelineToggle()
    qtbot.addWidget(toggle)
    for checked in (False, True):
        for enabled in (True, False):
            toggle.setChecked(checked)
            toggle.setEnabled(enabled)
            image = toggle.grab().toImage()
            assert not image.isNull()


def _fill_color(toggle: PipelineToggle):
    """The colour inside the triangle, below the wave.

    Sampling a grab is normally off limits in this suite, but this widget
    paints every pixel itself from Theme tokens — no stylesheet, no QStyle —
    so what it draws offscreen is what it draws in the app. Device pixels,
    hence the ratio (the corner of a Retina grab is not the corner of the
    widget).
    """
    image = toggle.grab().toImage()
    ratio = image.devicePixelRatio() or 1
    return image.pixelColor(int(8 * ratio), int(22 * ratio))


def test_a_disabled_toggle_still_says_which_way_it_is_set(qtbot):
    """The panel toggles are greyed for the length of a run."""
    on = PipelineToggle(PipelineToggle.SIZE_PANEL)
    off = PipelineToggle(PipelineToggle.SIZE_PANEL)
    qtbot.addWidget(on)
    qtbot.addWidget(off)
    on.setChecked(True)
    for toggle in (on, off):
        toggle.setEnabled(False)
    assert _fill_color(on) != _fill_color(off)


def test_disabling_a_checked_toggle_dims_it(qtbot):
    """...and it must not simply look enabled either."""
    toggle = PipelineToggle(PipelineToggle.SIZE_PANEL)
    qtbot.addWidget(toggle)
    toggle.setChecked(True)
    lit = _fill_color(toggle)
    toggle.setEnabled(False)
    assert _fill_color(toggle) != lit
