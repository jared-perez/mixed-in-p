"""A step toggle shows twice — panel triangle and header mini — and mirrors.

MainWindow is the one owner: both widgets emit a request, both are reflected
from it with signals blocked. Driven through a real window rather than stubs,
because what broke here was the *reflect* half, which a stub cannot have.

Structure, never pixels: the suite runs with no application stylesheet.
"""

from __future__ import annotations

import pytest

from src.gui.convert_pipeline import STEP_ANALYZE, STEP_CONVERT, STEP_ORDER, STEP_RENAME
from src.utils.config import AppConfig, load_config, save_config


@pytest.fixture
def window(qtbot):
    made = []

    def build(**cfg):
        save_config(AppConfig(**cfg))
        from src.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)
        made.append(win)
        return win

    yield build
    for win in made:
        win._player_panel.shutdown_workers()


def panel_toggle(win, step):
    return win._panel_for_step(step)._pipeline_toggle


def mini(win, step):
    return win._header.pipeline._toggles[step]


# ------------------------------------------------------------- both directions


@pytest.mark.parametrize("step", STEP_ORDER)
def test_a_header_mini_moves_its_panel_triangle(window, step):
    win = window()
    mini(win, step).click()
    assert panel_toggle(win, step).isChecked()
    assert win._step_enabled(step)


@pytest.mark.parametrize("step", STEP_ORDER)
def test_a_panel_triangle_moves_its_header_mini(window, step):
    win = window()
    panel_toggle(win, step).click()
    assert mini(win, step).isChecked()
    assert win._step_enabled(step)


@pytest.mark.parametrize("step", STEP_ORDER)
def test_a_reflection_does_not_come_back_round(window, step):
    """Both mirrors write config, so a signal loop would double-write it and
    could not settle. Applying twice is the check — one pass is stable even
    in a build that echoes."""
    win = window()
    for _ in range(2):
        mini(win, step).click()
        assert panel_toggle(win, step).isChecked() == mini(win, step).isChecked()
        panel_toggle(win, step).click()
        assert panel_toggle(win, step).isChecked() == mini(win, step).isChecked()
    assert not win._step_enabled(step)


def test_the_steps_reach_both_mirrors_at_startup(window):
    win = window(pipeline_rename_enabled=True, pipeline_analyze_enabled=True)
    for step, expected in (
        (STEP_RENAME, True),
        (STEP_CONVERT, False),
        (STEP_ANALYZE, True),
    ):
        assert panel_toggle(win, step).isChecked() is expected
        assert mini(win, step).isChecked() is expected


def test_a_step_is_persisted_from_either_side(window):
    win = window()
    mini(win, STEP_RENAME).click()
    assert load_config().pipeline_rename_enabled is True
    panel_toggle(win, STEP_CONVERT).click()
    assert load_config().pipeline_convert_enabled is True


# ------------------------------------------------------------------- tooltips


@pytest.mark.parametrize("step", STEP_ORDER)
def test_a_mini_click_updates_the_panel_triangles_tooltip(window, step):
    """The bug the user found in the running app: the reflect half sets the
    state inside blockSignals, so a tooltip driven by `toggled` never moved —
    the triangle lit up still offering to switch the step on."""
    win = window()
    off = panel_toggle(win, step).toolTip()
    mini(win, step).click()
    on = panel_toggle(win, step).toolTip()
    assert on and on != off
    assert "Leave" in on and "Include" in off


@pytest.mark.parametrize("step", STEP_ORDER)
def test_a_panel_click_updates_the_minis_tooltip(window, step):
    win = window()
    off = mini(win, step).toolTip()
    panel_toggle(win, step).click()
    on = mini(win, step).toolTip()
    assert on and on != off
    assert "Leave" in on and "Include" in off


def test_startup_tooltips_match_the_stored_state(window):
    """Convert read its own state from config and looked right; the two that
    only learn theirs through the mirror did not, which is what made one
    missing call read as three panels disagreeing."""
    win = window(
        pipeline_rename_enabled=True,
        pipeline_convert_enabled=True,
        pipeline_analyze_enabled=True,
    )
    for step in STEP_ORDER:
        for widget in (panel_toggle(win, step), mini(win, step)):
            assert "Leave" in widget.toolTip(), (step, widget.toolTip())
