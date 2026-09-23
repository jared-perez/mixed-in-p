"""Settings → Keyboard Shortcuts: a collapsible reference table.

It starts closed, opens and closes from its header like the Player's
sections, says in its tooltip what the next click will do, and lists only
shortcuts the app really has (the guide once claimed Delete worked in
Analyze; it never did).
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel

from src.gui.widgets.settings_panel import SettingsPanel


@pytest.fixture
def panel(qtbot):
    widget = SettingsPanel()
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def _column(panel, col: int) -> list[str]:
    grid: QGridLayout = panel._shortcuts_frame.layout()
    out = []
    for row in range(1, grid.rowCount()):
        item = grid.itemAtPosition(row, col)
        if item is not None and isinstance(item.widget(), QLabel):
            out.append(item.widget().text())
    return out


def test_it_starts_closed(panel):
    assert panel._shortcuts_frame.isHidden()
    assert not panel._shortcuts_btn.isChecked()


def test_the_header_opens_and_closes_it(panel, qtbot):
    qtbot.mouseClick(panel._shortcuts_btn, Qt.MouseButton.LeftButton)
    assert not panel._shortcuts_frame.isHidden()
    assert panel._shortcuts_btn.text().startswith("▾")
    qtbot.mouseClick(panel._shortcuts_btn, Qt.MouseButton.LeftButton)
    assert panel._shortcuts_frame.isHidden()
    assert panel._shortcuts_btn.text().startswith("▸")


def test_the_tooltip_says_what_the_next_click_does(panel, qtbot):
    assert panel._shortcuts_btn.toolTip() == "Show the keyboard shortcuts"
    qtbot.mouseClick(panel._shortcuts_btn, Qt.MouseButton.LeftButton)
    assert panel._shortcuts_btn.toolTip() == "Hide the keyboard shortcuts"


def test_every_row_has_keys_an_action_and_a_place(panel):
    keys, does, where = (_column(panel, c) for c in range(3))
    assert len(keys) == len(does) == len(where) == 12
    assert all(keys) and all(does) and all(where)


def test_delete_is_not_claimed_for_analyze(panel):
    assert "Player, Rename" in _column(panel, 2)
    assert not any("Analyze" in w for w in _column(panel, 2))
