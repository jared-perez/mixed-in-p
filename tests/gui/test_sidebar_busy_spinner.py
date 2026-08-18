"""The Convert and Analyze nav glyphs spin while their panel is working.

The point of the feature is that it survives a collapsed rail — with the
labels gone, a turning icon is the only thing that says a long batch is still
running, and its stopping is the only thing that says it finished. So the
assertions here are about the icon actually changing, not about a flag: a
spinner that sets state and paints the same pixmap every frame would pass any
test written against ``is_page_busy`` alone.

Both glyphs turn clockwise (see ``_SPIN_DIRECTION``), and only one of them can
be seen doing it: the Convert glyph is two opposing arrows and so is exactly
180-degree symmetric, which is asserted here rather than left to be
rediscovered as a bug in the sign.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSize

from src.gui.main_window import MainWindow
from src.gui.widgets.nav_icons import nav_icon
from src.gui.widgets.sidebar import _SPIN_FRAMES, Sidebar

_ICON = QSize(30, 30)


@pytest.fixture
def sidebar(qtbot):
    bar = Sidebar()
    qtbot.addWidget(bar)
    return bar


def button_image(sidebar: Sidebar, page_id: str):
    """What the button is actually showing, as a comparable image."""
    return sidebar._buttons[page_id].icon().pixmap(_ICON).toImage()


def glyph_image(page_id: str, angle: float):
    """The same glyph rendered independently at a known angle."""
    return nav_icon(page_id, angle).pixmap(_ICON).toImage()


# ------------------------------------------------------------------ mechanics


def test_nothing_spins_until_a_panel_says_it_is_working(sidebar):
    assert not sidebar.is_page_busy("convert")
    assert not sidebar.is_page_busy("analysis")
    assert sidebar._spin_timer is None


def test_the_glyph_changes_between_frames(sidebar):
    """The heart of it: successive frames must not paint the same pixels."""
    sidebar.set_page_busy("convert", True)
    first = button_image(sidebar, "convert")

    sidebar._advance_spin()
    second = button_image(sidebar, "convert")

    assert first != second


def test_the_timer_runs_only_while_something_is_working(sidebar):
    sidebar.set_page_busy("convert", True)
    assert sidebar._spin_timer.isActive()

    # A second busy page shares the one timer rather than starting another.
    timer = sidebar._spin_timer
    sidebar.set_page_busy("analysis", True)
    assert sidebar._spin_timer is timer
    assert timer.isActive()

    # ...and it keeps running until the *last* page is done.
    sidebar.set_page_busy("convert", False)
    assert timer.isActive()
    sidebar.set_page_busy("analysis", False)
    assert not timer.isActive()


def test_stopping_puts_the_upright_glyph_back(sidebar):
    upright = button_image(sidebar, "analysis")

    sidebar.set_page_busy("analysis", True)
    for _ in range(5):
        sidebar._advance_spin()
    assert button_image(sidebar, "analysis") != upright

    sidebar.set_page_busy("analysis", False)
    assert button_image(sidebar, "analysis") == upright


def test_a_restart_does_not_snap_the_glyph_back_upright(sidebar):
    """Analysis finishes and can immediately chain into the next queued batch.

    The frame counter carries across that gap on purpose — resetting it would
    jerk the glyph back to 0 degrees, which reads as a stop the user then has
    to second-guess.
    """
    sidebar.set_page_busy("analysis", True)
    for _ in range(5):
        sidebar._advance_spin()
    assert sidebar._spin_frame == 5

    sidebar.set_page_busy("analysis", False)
    sidebar.set_page_busy("analysis", True)

    assert sidebar._spin_frame == 5
    assert button_image(sidebar, "analysis") == glyph_image("analysis", 75.0)


def test_both_directions_are_idempotent(sidebar):
    """The callers are thread lifecycle handlers; Convert alone clears the
    spinner from three of them (finished, cancelled, error)."""
    sidebar.set_page_busy("convert", True)
    sidebar.set_page_busy("convert", True)
    assert sidebar.is_page_busy("convert")

    sidebar.set_page_busy("convert", False)
    sidebar.set_page_busy("convert", False)
    assert not sidebar.is_page_busy("convert")
    assert not sidebar._spin_timer.isActive()


def test_only_convert_and_analyze_spin(sidebar):
    """Every other panel's work is instant or has its own progress bar, so a
    stray call must be a no-op rather than starting a timer nothing stops."""
    upright = button_image(sidebar, "player")

    sidebar.set_page_busy("player", True)

    assert not sidebar.is_page_busy("player")
    assert sidebar._spin_timer is None
    assert button_image(sidebar, "player") == upright


# ------------------------------------------------------------------ direction


def test_convert_turns_clockwise(sidebar):
    sidebar.set_page_busy("convert", True)
    for _ in range(_SPIN_FRAMES // 4):  # a quarter turn
        sidebar._advance_spin()

    assert button_image(sidebar, "convert") == glyph_image("convert", 90.0)


def test_the_convert_glyphs_direction_is_not_observable(sidebar):
    """Stated so it isn't mistaken for a bug, or "fixed" by flipping the sign.

    Convert is two opposing arrows — a shape with exact 180-degree rotational
    symmetry — so its clockwise and counter-clockwise frames are the same
    pixels. It spins visibly, which is the whole feature; which way it spins is
    a property of the glyph, not of the code, and would take redrawing the icon
    to change.
    """
    assert glyph_image("convert", 90.0) == glyph_image("convert", 270.0)
    assert glyph_image("convert", 30.0) == glyph_image("convert", 210.0)
    # Analyze's magnifier has no such symmetry, which is why the test below
    # can assert a direction at all.
    assert glyph_image("analysis", 90.0) != glyph_image("analysis", 270.0)


def test_analyze_turns_clockwise_too(sidebar):
    """The magnifier is the one glyph whose direction is observable, so this
    is the assertion that would actually catch a flipped sign."""
    sidebar.set_page_busy("analysis", True)
    for _ in range(_SPIN_FRAMES // 4):
        sidebar._advance_spin()

    assert button_image(sidebar, "analysis") == glyph_image("analysis", 90.0)
    assert button_image(sidebar, "analysis") != glyph_image("analysis", 270.0)


def test_the_two_pages_spin_off_one_frame_counter(sidebar):
    """One timer, one counter — so two glyphs working at once stay in step
    with each other instead of drifting apart."""
    sidebar.set_page_busy("convert", True)
    sidebar.set_page_busy("analysis", True)
    sidebar._advance_spin()

    step = 360.0 / _SPIN_FRAMES
    assert button_image(sidebar, "convert") == glyph_image("convert", step)
    assert button_image(sidebar, "analysis") == glyph_image("analysis", step)


# -------------------------------------------------------------- window wiring


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    win._player_panel.shutdown_workers()


@pytest.mark.parametrize(
    "page_id, handler, args",
    [
        # Every path a batch can leave by has to stop the glyph, or it spins
        # for the rest of the session with nothing running behind it.
        ("convert", "_on_conversion_finished", ([],)),
        ("convert", "_on_conversion_cancelled", ()),
        ("convert", "_on_conversion_error", ("boom",)),
        ("analysis", "_on_analysis_finished", ([],)),
        ("analysis", "_on_analysis_cancelled", ()),
    ],
)
def test_every_end_of_batch_stops_the_spinner(window, page_id, handler, args):
    window._sidebar.set_page_busy(page_id, True)
    assert window._sidebar.is_page_busy(page_id)

    getattr(window, handler)(*args)

    assert not window._sidebar.is_page_busy(page_id)
