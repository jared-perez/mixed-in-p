"""Box-selecting a full playlist from its "#" column.

A full playlist has no empty space to start a rubber band from, so the Player
table treats its narrow "#" column as a gutter: a press there that moves draws
the band, one that doesn't is an ordinary click (select, double-click to play).
Anywhere else a press on a row still arms the row drag.
"""

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QTableWidgetItem

from src.gui.widgets.player_panel import ReorderableTableWidget

ROWS = 30


@pytest.fixture
def table(qtbot):
    t = ReorderableTableWidget()
    t.setColumnCount(3)
    t.setRowCount(ROWS)
    for row in range(ROWS):
        for col in range(3):
            t.setItem(row, col, QTableWidgetItem(f"{row}-{col}"))
    t.setColumnWidth(0, 40)
    t.setColumnWidth(1, 300)
    t.setColumnWidth(2, 300)
    t.resize(500, 300)  # far fewer rows fit than exist: no empty space
    qtbot.addWidget(t)
    t.show()
    qtbot.waitExposed(t)
    qtbot.wait(10)
    return t


def _event(table, kind, point, button=Qt.MouseButton.LeftButton,
           modifiers=Qt.KeyboardModifier.NoModifier):
    # Real mouse events reach an item view through its viewport, so their
    # local position is viewport space; Qt's own handlers read that one.
    glob = QPointF(table.viewport().mapToGlobal(point))
    local = QPointF(point)
    buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else button
    return QMouseEvent(kind, local, glob, button, buttons, modifiers)


def _cell_point(table, row, col):
    rect = table.visualRect(table.model().index(row, col))
    return rect.center()


def _drag(table, start, end):
    table.mousePressEvent(_event(table, QEvent.Type.MouseButtonPress, start))
    table.mouseMoveEvent(_event(table, QEvent.Type.MouseMove, end))
    table.mouseReleaseEvent(_event(table, QEvent.Type.MouseButtonRelease, end))


def _selected_rows(table):
    return sorted({i.row() for i in table.selectionModel().selectedRows()})


def test_the_view_is_full(table):
    last_visible = table.rowAt(table.viewport().height() - 1)
    assert last_visible != -1 and last_visible < ROWS - 1


def test_dragging_down_the_number_column_box_selects(table):
    _drag(table, _cell_point(table, 1, 0), _cell_point(table, 4, 0))
    assert _selected_rows(table) == [1, 2, 3, 4]


def test_the_band_may_sweep_across_the_other_columns(table):
    _drag(table, _cell_point(table, 5, 0), _cell_point(table, 2, 2))
    assert _selected_rows(table) == [2, 3, 4, 5]


def test_a_gutter_drag_never_arms_a_row_drag(table, monkeypatch):
    started = []
    monkeypatch.setattr(table, "startDrag", lambda actions: started.append(actions))
    _drag(table, _cell_point(table, 1, 0), _cell_point(table, 6, 0))
    assert started == []


def test_a_jitter_below_the_drag_distance_is_still_a_click(table):
    start = _cell_point(table, 3, 0)
    nudge = start + QPoint(max(QApplication.startDragDistance() - 2, 0), 0)
    _drag(table, start, nudge)
    assert _selected_rows(table) == [3]
    assert table._rubber_band is None or table._rubber_band.isHidden()


def test_a_click_on_the_number_selects_its_row(table):
    table.selectRow(8)
    point = _cell_point(table, 2, 0)
    table.mousePressEvent(_event(table, QEvent.Type.MouseButtonPress, point))
    table.mouseReleaseEvent(_event(table, QEvent.Type.MouseButtonRelease, point))
    assert _selected_rows(table) == [2]


def test_a_double_click_on_the_number_still_plays(table, qtbot):
    point = _cell_point(table, 4, 0)
    with qtbot.waitSignal(table.doubleClicked, timeout=500) as blocker:
        table.mousePressEvent(_event(table, QEvent.Type.MouseButtonPress, point))
        table.mouseReleaseEvent(_event(table, QEvent.Type.MouseButtonRelease, point))
        table.mouseDoubleClickEvent(_event(table, QEvent.Type.MouseButtonDblClick, point))
        table.mouseReleaseEvent(_event(table, QEvent.Type.MouseButtonRelease, point))
    assert blocker.args[0].row() == 4


def test_a_press_on_another_column_still_drags_the_row(table, monkeypatch):
    started = []
    monkeypatch.setattr(table, "startDrag", lambda actions: started.append(actions))
    _drag(table, _cell_point(table, 1, 1), _cell_point(table, 6, 1))
    assert started, "a press on Filename must still pick the row up"
    assert table._rubber_band is None or table._rubber_band.isHidden()
