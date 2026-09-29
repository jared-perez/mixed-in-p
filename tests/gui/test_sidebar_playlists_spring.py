"""Holding a track drag over the Playlists toggle brings the nav buttons back.

In playlists mode the tree hides the nav buttons, so a track dragged out of a
playlist had nowhere to go but the tree. A two-second hold over the toggle
springs the nav rail back into view mid-drag, the way a spring-loaded folder
opens in Finder, and the drag carries on to a panel.
"""

from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent

from src.gui.widgets.droppable_table import SOURCE_PAGE_MIME
from src.gui.widgets.sidebar import _SPRING_DELAY_MS, Sidebar

_ACTIONS = Qt.DropAction.MoveAction | Qt.DropAction.CopyAction


def _mime(source: bytes | None = b"player") -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile("/music/track.wav")])
    if source is not None:
        mime.setData(SOURCE_PAGE_MIME, source)
    return mime


def _enter(btn, mime: QMimeData) -> QDragEnterEvent:
    # The caller holds `mime`: the event keeps only a raw pointer (CLAUDE.md).
    event = QDragEnterEvent(
        QPoint(5, 5), _ACTIONS, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    btn.dragEnterEvent(event)
    return event


def _sidebar(qtbot, *, playlists: bool = True) -> Sidebar:
    sidebar = Sidebar()
    qtbot.addWidget(sidebar)
    sidebar.set_playlists_mode(playlists)
    # Shortened so the suite doesn't sit out the real delay.
    sidebar._playlists_btn._spring_timer.setInterval(20)
    return sidebar


def test_the_delay_is_two_seconds(qtbot):
    sidebar = Sidebar()
    qtbot.addWidget(sidebar)
    assert _SPRING_DELAY_MS == 2000
    assert sidebar._playlists_btn._spring_timer.interval() == 2000


def test_a_held_track_drag_brings_the_nav_buttons_back(qtbot):
    sidebar = _sidebar(qtbot)
    btn = sidebar._playlists_btn
    toggled = []
    sidebar.playlists_toggled.connect(toggled.append)

    mime = _mime()
    assert _enter(btn, mime).isAccepted()
    assert btn.spring_pending()
    qtbot.waitUntil(lambda: not sidebar.playlists_mode, timeout=1000)

    assert toggled == [False]
    assert not btn.isChecked()
    assert not sidebar._nav_page.isHidden() and sidebar._playlists_page.isHidden()
    assert btn.styleSheet() == ""


def test_an_external_audio_file_drag_springs_too(qtbot):
    sidebar = _sidebar(qtbot)
    mime = _mime(source=None)
    assert _enter(sidebar._playlists_btn, mime).isAccepted()
    qtbot.waitUntil(lambda: not sidebar.playlists_mode, timeout=1000)


def test_leaving_before_the_delay_cancels(qtbot):
    sidebar = _sidebar(qtbot)
    btn = sidebar._playlists_btn
    btn._spring_timer.setInterval(200)
    mime = _mime()
    _enter(btn, mime)
    btn.dragLeaveEvent(QDragLeaveEvent())
    assert not btn.spring_pending()
    assert btn.styleSheet() == ""
    qtbot.wait(300)
    assert sidebar.playlists_mode


def test_a_drop_on_the_toggle_is_refused_and_cancels(qtbot):
    sidebar = _sidebar(qtbot)
    btn = sidebar._playlists_btn
    btn._spring_timer.setInterval(200)
    mime = _mime()
    _enter(btn, mime)
    drop = QDropEvent(
        QPoint(5, 5), _ACTIONS, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    btn.dropEvent(drop)
    assert not drop.isAccepted()
    assert not btn.spring_pending()
    qtbot.wait(300)
    assert sidebar.playlists_mode


def test_nothing_springs_in_nav_mode(qtbot):
    sidebar = _sidebar(qtbot, playlists=False)
    mime = _mime()
    assert not _enter(sidebar._playlists_btn, mime).isAccepted()
    assert not sidebar._playlists_btn.spring_pending()


def test_nothing_springs_in_split_view(qtbot):
    sidebar = _sidebar(qtbot)
    sidebar.set_split_mode(True)
    mime = _mime()
    assert not _enter(sidebar._playlists_btn, mime).isAccepted()


def test_a_drag_no_nav_button_takes_does_not_spring(qtbot):
    # A playlist node dragged out of the tree has no route to any panel.
    sidebar = _sidebar(qtbot)
    mime = _mime(source=b"playlists")
    assert not _enter(sidebar._playlists_btn, mime).isAccepted()
    assert not sidebar._playlists_btn.spring_pending()


def test_a_view_change_during_the_hold_is_not_undone(qtbot):
    # Shift+Tab mid-drag already left playlists mode; the spring must not
    # then emit a second, stale toggle.
    sidebar = _sidebar(qtbot)
    btn = sidebar._playlists_btn
    toggled = []
    sidebar.playlists_toggled.connect(toggled.append)
    mime = _mime()
    _enter(btn, mime)
    sidebar.set_playlists_mode(False)
    qtbot.waitUntil(lambda: not btn.spring_pending(), timeout=1000)
    assert toggled == []
