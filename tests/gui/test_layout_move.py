"""Re-homing a widget between layouts must not leave PySide a dangling item.

A plain ``addWidget`` of a widget another layout holds makes Qt free that
layout's item in C++ without telling PySide, whose wrapper for it then answers
for a freed address — and the next QObject allocated there crashes in
``SignalManager::retrieveMetaObject`` (see ``layout_move``). The crash itself
depends on the allocator reusing that address, so it is not what these tests
look for: they look for the cause, which is deterministic. A wrapper PySide was
told about reads invalid after the move; one it was not told about still reads
valid, although its layout has let go of it.
"""

from __future__ import annotations

import pytest
import shiboken6
from PySide6.QtWidgets import QHBoxLayout, QLayout, QPushButton, QVBoxLayout, QWidget

from src.gui.widgets.layout_move import detach_from_layout
from src.gui.widgets.player_panel import PlayerPanel


def item_for(widget: QWidget):
    """The layout item currently holding *widget*, found by pointer."""
    parent = widget.parentWidget()
    for layout in [parent.layout(), *parent.findChildren(QLayout)]:
        index = layout.indexOf(widget)
        if index >= 0:
            return layout.itemAt(index)
    raise AssertionError(f"no layout holds {widget!r}")


@pytest.fixture
def rows(qtbot):
    """A widget in a row nested with addLayout, and a second row to move it to."""
    host = QWidget()
    qtbot.addWidget(host)
    outer = QVBoxLayout(host)
    home = QHBoxLayout()
    button = QPushButton("M")
    home.addWidget(button)
    outer.addLayout(home)
    dock = QWidget(host)
    away = QHBoxLayout(dock)
    outer.addWidget(dock)
    # The host rides along so it outlives the test: qtbot does not keep a
    # widget alive, and the layouts die with it.
    return home, away, button, host


class TestTheMechanism:
    def test_a_plain_move_leaves_the_old_item_answering(self, rows):
        """Pins the PySide behaviour the helper exists for. If this ever fails,
        PySide has started tracking the move itself and the helper is moot."""
        home, away, button, _host = rows
        old = home.itemAt(0)

        away.addWidget(button)

        assert home.count() == 0
        assert shiboken6.isValid(old)

    def test_detaching_first_retires_the_old_item(self, rows):
        home, away, button, _host = rows
        old = home.itemAt(0)

        detach_from_layout(button)
        away.addWidget(button)

        assert not shiboken6.isValid(old)
        assert away.indexOf(button) == 0

    def test_a_widget_no_layout_holds_is_left_alone(self, qtbot):
        parent = QWidget()
        qtbot.addWidget(parent)
        loose = QPushButton("x", parent)

        detach_from_layout(loose)

        assert loose.parentWidget() is parent


@pytest.fixture
def player(qtbot):
    panel = PlayerPanel()
    qtbot.addWidget(panel)
    panel._metronome_section.view._stream_factory = lambda: None
    yield panel
    panel.shutdown_metronome()


class TestTheMetronomeHeader:
    """Docked beside Loop Slicer when closed, on its own row when open: the one
    widget that moves between layouts for as long as the app runs."""

    def test_opening_retires_the_docked_item(self, player):
        section = player._metronome_section
        assert section.is_docked()
        docked = item_for(section._header_btn)

        section.set_expanded(True)

        assert not shiboken6.isValid(docked)

    def test_closing_retires_the_row_item(self, player):
        section = player._metronome_section
        section.set_expanded(True)
        on_row = item_for(section._header_btn)

        section.set_expanded(False)

        assert not shiboken6.isValid(on_row)
