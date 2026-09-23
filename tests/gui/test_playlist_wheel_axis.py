"""A long swipe down the playlist runs on down the page, not sideways.

Reported on a macOS trackpad: once the rows reached the bottom, the rest of
the swipe crawled the columns to the far right before the page moved. The
momentum tail's sideways drift outweighs its shrinking y, and Qt had latched
the whole gesture onto the table. See ``AxisLockedWheelMixin`` in
``src/gui/widgets/wheel_guard.py``.

Each test asserts the page's scroll position as well as the table's, since a
fix that only swallowed the drift would pass the "columns did not move" half
and leave the page dead.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.gui.widgets.player_panel import ReorderableTableWidget


def swipe(table, phase, dx: int, dy: int, modifiers=Qt.KeyboardModifier.NoModifier) -> None:
    """One trackpad (or, with ``NoScrollPhase``, mouse) wheel event over the rows."""
    viewport = table.viewport()
    centre = viewport.rect().center()
    QApplication.sendEvent(
        viewport,
        QWheelEvent(
            QPointF(centre),
            viewport.mapToGlobal(centre).toPointF(),
            QPoint(dx, dy),
            QPoint(dx * 3, dy * 3),
            Qt.MouseButton.NoButton,
            modifiers,
            phase,
            False,
        ),
    )


@pytest.fixture
def page(qtbot):
    """A scrolling page with a playlist table (both scroll bars live) in it."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    content = QWidget()
    layout = QVBoxLayout(content)
    table = ReorderableTableWidget()
    table.setRowCount(60)
    table.setColumnCount(20)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.setFixedHeight(200)
    layout.addWidget(table)
    for _ in range(20):
        filler = QWidget()
        filler.setMinimumHeight(40)
        layout.addWidget(filler)
    area.setWidget(content)
    qtbot.addWidget(area)
    area.resize(320, 300)
    area.show()
    qtbot.wait(10)
    assert area.verticalScrollBar().maximum() > 0, "the page must be scrollable"
    assert table.horizontalScrollBar().maximum() > 0, "the columns must overflow"
    return area, table


def test_drift_at_the_bottom_scrolls_the_page_not_the_columns(page):
    area, table = page
    table.verticalScrollBar().setValue(table.verticalScrollBar().maximum())
    swipe(table, Qt.ScrollPhase.ScrollBegin, 0, 0)
    swipe(table, Qt.ScrollPhase.ScrollUpdate, -1, -20)
    for _ in range(10):
        # The momentum tail: y dying away, sideways drift outweighing it.
        swipe(table, Qt.ScrollPhase.ScrollMomentum, -6, -3)
    swipe(table, Qt.ScrollPhase.ScrollEnd, 0, 0)
    assert table.horizontalScrollBar().value() == 0
    assert area.verticalScrollBar().value() > 0


def test_vertical_swipe_still_scrolls_the_rows_first(page):
    area, table = page
    swipe(table, Qt.ScrollPhase.ScrollBegin, 0, 0)
    swipe(table, Qt.ScrollPhase.ScrollUpdate, -2, -20)
    assert table.verticalScrollBar().value() > 0
    assert area.verticalScrollBar().value() == 0


def test_sideways_swipe_scrolls_the_columns_and_never_the_page(page):
    area, table = page
    swipe(table, Qt.ScrollPhase.ScrollBegin, 0, 0)
    swipe(table, Qt.ScrollPhase.ScrollUpdate, -20, -2)
    for _ in range(5):
        swipe(table, Qt.ScrollPhase.ScrollMomentum, -2, -8)
    assert table.horizontalScrollBar().value() > 0
    assert table.verticalScrollBar().value() == 0
    assert area.verticalScrollBar().value() == 0


def test_mouse_wheel_at_the_bottom_scrolls_the_page(page):
    area, table = page
    table.verticalScrollBar().setValue(table.verticalScrollBar().maximum())
    swipe(table, Qt.ScrollPhase.NoScrollPhase, 0, -40)
    assert area.verticalScrollBar().value() > 0
