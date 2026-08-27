"""Shift+Tab shows and hides the playlists tree, from anywhere in the window.

The sidebar's own mechanics are covered in `test_sidebar_playlists_mode.py`;
what is tested here is the part that only exists once MainWindow has built the
QShortcut — that the key sequence is spelled the way Qt delivers the event, and
that its context is narrow enough to leave a dialog's keyboard alone.

Also here: the cost. Shift+Tab is Qt's backward focus-navigation key, so
binding it is a trade rather than a free win, and the things that were checked
before choosing it are asserted rather than remembered — forward Tab still
walks the chain, typing is untouched, and the shortcut fires from inside a
text field (which is exactly the behaviour that costs backward navigation).
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QLineEdit, QVBoxLayout

from src.gui.main_window import MainWindow
from src.gui.widgets.sidebar import PLAYLISTS_SHORTCUT


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    yield win
    win._player_panel.shutdown_workers()


def press_hotkey(target) -> None:
    """Send the shortcut the way the platform actually delivers it.

    Qt turns Shift+Tab into Key_Backtab before anyone sees it, so a test that
    sends Shift + Key_Tab is testing a key press that never happens.
    """
    QTest.keyClick(target, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
    # And let Shift back up. keyClick presses a modifier without releasing it,
    # and QGuiApplication.keyboardModifiers() is application state that outlives
    # the test — a later test's programmatic selectRow() reads it and extends
    # its selection instead of replacing it. See the no_latched_modifiers guard
    # in conftest, which is what caught this.
    QTest.keyRelease(target, Qt.Key.Key_Shift)


def test_the_hotkey_shows_and_hides_the_tree(window, qtbot):
    sidebar = window._sidebar
    assert not sidebar.playlists_mode

    press_hotkey(window)
    assert sidebar.playlists_mode
    assert sidebar._mode_stack.currentWidget() is sidebar._playlists_page

    press_hotkey(window)
    assert not sidebar.playlists_mode


def test_the_hotkey_reaches_the_window_from_a_focused_field(window, qtbot):
    """"From anywhere in the window" is the whole point, so it is asserted from
    the deepest thing that could swallow it — a focused line edit on the
    visible page. Note the page has to be the *current* one: a widget on a
    hidden page cannot take focus, so a check run there passes against nothing.
    """
    field = window._player_panel._search_field
    assert field.isVisible()
    field.setFocus()
    qtbot.waitUntil(lambda: field.hasFocus())

    press_hotkey(field)
    assert window._sidebar.playlists_mode


def test_a_modal_dialog_keeps_its_own_keyboard(window, qtbot):
    """A modal on top keeps its keyboard — the sidebar must not move behind it.

    Read what this does and does not pin. It pins the *behaviour*; it does not
    pin the shortcut's `WindowShortcut` context, which is the reason it looks
    like it exists. Qt's modal event blocking stops the delivery on its own, so
    this passes under `ApplicationShortcut` too — verified by mutating the line
    and watching this test stay green. Don't read it as cover for that choice.

    It also has to be a genuine modal with focus inside it. A bare
    `QDialog.show()` *does* fire the shortcut — offscreen leaves a non-modal
    child window unactivated, so the match still resolves to MainWindow's
    window — and the first draft of this test was written that way and failed.
    """
    dialog = QDialog(window)
    qtbot.addWidget(dialog)
    dialog.setModal(True)
    field = QLineEdit(dialog)
    QVBoxLayout(dialog).addWidget(field)
    dialog.show()
    qtbot.waitExposed(dialog)
    field.setFocus()
    qtbot.waitUntil(lambda: field.hasFocus())
    assert dialog.isModal()

    before = window._sidebar.playlists_mode
    press_hotkey(field)
    assert window._sidebar.playlists_mode == before

    dialog.close()


def test_plain_tab_still_walks_the_chain_and_typing_is_untouched(window, qtbot):
    """The two things that made Shift+Tab acceptable where plain Tab was not.

    Plain Tab as the shortcut was measured taking focus navigation in both
    directions app-wide; this binding takes only the backward half, and these
    assertions are what say so out loud.
    """
    field = window._player_panel._search_field
    field.setFocus()
    qtbot.waitUntil(lambda: field.hasFocus())

    field.clear()
    QTest.keyClicks(field, "hello")
    assert field.text() == "hello"

    before = field
    QTest.keyClick(field, Qt.Key.Key_Tab)
    assert window.focusWidget() is not before
    assert not window._sidebar.playlists_mode  # plain Tab must never toggle


def test_the_bound_sequence_is_the_one_the_tooltip_advertises(window):
    """One source for the key, so the binding and its label cannot drift."""
    shortcuts = [
        sc
        for sc in window.findChildren(object)
        if hasattr(sc, "key") and callable(getattr(sc, "key", None))
        and isinstance(getattr(sc, "key")(), QKeySequence)
        and sc.key() == PLAYLISTS_SHORTCUT
    ]
    assert shortcuts, "no QShortcut bound to PLAYLISTS_SHORTCUT"
    key = PLAYLISTS_SHORTCUT.toString(QKeySequence.SequenceFormat.NativeText)
    assert window._sidebar._playlists_btn.toolTip().endswith(f"({key})")
