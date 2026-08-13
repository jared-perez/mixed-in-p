"""The order of the nav rail, and the fact that nothing else depends on it.

Keyboard sits at the bottom of the rail, below Spectrum: it is the one panel
that isn't part of a file's journey through the app, so it reads better after
the working panels than in the middle of them.

The guard that matters here is the second test. The rail's order and the page
stack's order are deliberately *different* — the stack's first widget is
Rename while the rail's first button is Player — and navigation works because
every id is looked up by name, never by position. Anyone reordering the rail
is one "let's make these consistent" away from breaking that.
"""

from __future__ import annotations

from PySide6.QtWidgets import QPushButton

from src.gui.widgets.sidebar import Sidebar

EXPECTED_ORDER = [
    "player",
    "rename",
    "convert",
    "analysis",
    "metadata",
    "spectrum",
    "keyboard",
]


def _rail_order(sidebar: Sidebar) -> list[str]:
    """Read the ids off the laid-out rail, top to bottom.

    Taken from the layout rather than from ``_buttons`` so this measures what
    is actually on screen — a dict would report insertion order even if the
    widgets were added to the layout in some other sequence.
    """
    by_button = {btn: page_id for page_id, btn in sidebar._buttons.items()}
    layout = sidebar._nav_page.layout()
    order = []
    for i in range(layout.count()):
        widget = layout.itemAt(i).widget()
        if isinstance(widget, QPushButton) and widget in by_button:
            order.append(by_button[widget])
    return order


def test_keyboard_sits_at_the_bottom_of_the_rail(qtbot):
    sidebar = Sidebar()
    qtbot.addWidget(sidebar)

    assert _rail_order(sidebar) == EXPECTED_ORDER


def test_settings_and_history_stay_below_the_stretch(qtbot):
    """They are pinned to the bottom by their own code, outside the list —
    so a reorder of the nav list must not pull them up into it."""
    sidebar = Sidebar()
    qtbot.addWidget(sidebar)

    assert "settings" not in _rail_order(sidebar)
    assert "history" not in _rail_order(sidebar)
    assert sidebar._buttons["settings"] is sidebar._settings_btn
    assert sidebar._buttons["history"] is sidebar._history_btn


def test_the_rail_order_is_not_the_page_stack_order(qtbot):
    """The decoupling, asserted so it cannot be quietly "tidied up".

    Every consumer looks a page up by its string id. If someone reorders
    MainWindow._create_pages to match the rail, navigation breaks while
    looking more consistent — this test says the mismatch is the design.
    """
    sidebar = Sidebar()
    qtbot.addWidget(sidebar)

    # The stack is built Rename-first (main_window._create_pages); the rail is
    # Player-first. Same ids, different sequence, on purpose.
    assert _rail_order(sidebar)[0] == "player"
    assert _rail_order(sidebar) != ["rename", "convert", "analysis", "player",
                                    "keyboard", "metadata", "spectrum"]


def test_every_rail_button_carries_its_own_icon(qtbot):
    """Icons are keyed by page id, so a reorder must not shuffle them."""
    sidebar = Sidebar()
    qtbot.addWidget(sidebar)

    for page_id in EXPECTED_ORDER:
        assert not sidebar._buttons[page_id].icon().isNull(), page_id


def test_keyboard_is_still_the_one_button_that_refuses_drops(qtbot):
    """There is nothing to do with a dropped file on a piano. Keyed by id,
    so moving the row must not hand it a drop target."""
    from src.gui.widgets.sidebar import _DroppableSidebarButton

    sidebar = Sidebar()
    qtbot.addWidget(sidebar)

    assert not isinstance(sidebar._buttons["keyboard"], _DroppableSidebarButton)
    for page_id in EXPECTED_ORDER:
        if page_id != "keyboard":
            assert isinstance(sidebar._buttons[page_id], _DroppableSidebarButton), page_id
