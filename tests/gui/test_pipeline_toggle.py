"""The step-toggle triangle: shape, states, tooltips.

Structure only. The suite runs offscreen with no application stylesheet and
under Fusion rather than the platform style, so nothing here may assert a
pixel or a width — how the triangle *looks* was settled by rendering it and
looking (see the W2 note in the handoff).
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QWidget

from src.gui.styles.theme import Theme
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


# The panel behind the toggle, as a colour the widget never paints, so any
# pixel still wearing it is one the toggle deliberately left alone.
_BEHIND = "#ff00ff"


def _on_a_panel(toggle: PipelineToggle) -> QImage:
    """The toggle drawn over `_BEHIND`, the way it sits on a real panel.

    `DrawChildren` alone on purpose: the default flags paint the palette's
    window colour first, which would fill the negative space with something
    and make the test below pass against a toggle that fills it too.
    """
    image = QImage(toggle.size(), QImage.Format.Format_ARGB32)
    image.fill(QColor(_BEHIND))
    toggle.render(image, QPoint(), toggle.rect(), QWidget.RenderFlag.DrawChildren)
    return image


def test_an_unchecked_toggle_leaves_its_field_transparent(qtbot):
    """Unchecked is a line drawing: rim and wave only, panel showing through.

    Sampled above the crest and inside the rim, which is field in both states.
    """
    toggle = PipelineToggle(PipelineToggle.SIZE_PANEL)
    qtbot.addWidget(toggle)
    assert _on_a_panel(toggle).pixelColor(14, 8).name() == _BEHIND
    toggle.setChecked(True)
    assert _on_a_panel(toggle).pixelColor(14, 8) == QColor(Theme.NEON_YELLOW)


def _field_regions(image: QImage) -> int:
    """How many separate patches the lit field breaks into.

    A pixel counts as field where it leans nearer the accent than the ink,
    which is the call the eye makes — insisting on a fully saturated pixel
    would fail on the antialiased channel that legitimately carries the two
    halves together at this size.
    """
    accent, ink = QColor(Theme.NEON_YELLOW), QColor(Theme.BG_DARK)

    def gap(colour: QColor, other: QColor) -> int:
        return (
            (colour.red() - other.red()) ** 2
            + (colour.green() - other.green()) ** 2
            + (colour.blue() - other.blue()) ** 2
        )

    def is_field(x: int, y: int) -> bool:
        colour = image.pixelColor(x, y)
        return gap(colour, accent) < gap(colour, ink)

    width, height = image.width(), image.height()
    seen: set[tuple[int, int]] = set()
    regions = 0
    for y in range(height):
        for x in range(width):
            if (x, y) in seen or not is_field(x, y):
                continue
            regions += 1
            stack = [(x, y)]
            seen.add((x, y))
            while stack:
                cx, cy = stack.pop()
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in seen:
                        if is_field(nx, ny):
                            seen.add((nx, ny))
                            stack.append((nx, ny))
    return regions


def test_the_lit_field_is_one_shape_at_both_sizes(qtbot):
    """The barrel has to stay open, and at 18px that is not free.

    The field is connected only through the channel between the wave's lip
    and the right-hand rim. Drawn at the artwork's own proportions that
    channel is about 1.4px on the header mini, so a checked toggle came out
    as two unrelated blobs; `_WAVE_SQUEEZE` is what reopens it, and 0.88 is
    the least distortion that does (measured at 18/20/22/28px). Without it
    this reports 3 regions at 18px and 2 at 20px.
    """
    for size in (PipelineToggle.SIZE_MINI, PipelineToggle.SIZE_PANEL):
        toggle = PipelineToggle(size)
        qtbot.addWidget(toggle)
        toggle.setChecked(True)
        assert _field_regions(_on_a_panel(toggle)) == 1, f"broken up at {size}px"
