"""Sidebar playlists-mode mechanics: width pins, mode stack, collapse interplay."""

from PySide6.QtGui import QKeySequence

from src.gui.styles.theme import Theme
from src.gui.widgets.sidebar import PLAYLISTS_SHORTCUT, Sidebar


def _make_sidebar(qtbot) -> Sidebar:
    sidebar = Sidebar()
    qtbot.addWidget(sidebar)
    return sidebar


def test_default_state_is_pinned_nav(qtbot):
    sidebar = _make_sidebar(qtbot)
    assert not sidebar.playlists_mode
    assert sidebar.minimumWidth() == sidebar.maximumWidth() == Theme.SIDEBAR_WIDTH
    assert sidebar._mode_stack.currentWidget() is sidebar._nav_page


def test_playlists_mode_releases_width_pin(qtbot):
    sidebar = _make_sidebar(qtbot)
    sidebar.set_playlists_mode(True)
    assert sidebar.minimumWidth() == Theme.SIDEBAR_PLAYLISTS_MIN
    assert sidebar.maximumWidth() == Theme.SIDEBAR_PLAYLISTS_MAX
    assert sidebar._mode_stack.currentWidget() is sidebar._playlists_page
    assert sidebar._playlists_btn.isChecked()

    sidebar.set_playlists_mode(False)
    assert sidebar.minimumWidth() == sidebar.maximumWidth() == Theme.SIDEBAR_WIDTH
    assert sidebar._mode_stack.currentWidget() is sidebar._nav_page


def test_collapse_in_playlists_mode_pins_but_keeps_mode(qtbot):
    sidebar = _make_sidebar(qtbot)
    sidebar.set_playlists_mode(True)
    sidebar.set_collapsed(True)

    # Collapsed: icon rail at 56px, tree hidden, toggle hidden — mode retained.
    assert sidebar.minimumWidth() == sidebar.maximumWidth() == Theme.SIDEBAR_WIDTH_COLLAPSED
    assert sidebar._mode_stack.currentWidget() is sidebar._nav_page
    assert sidebar._playlists_btn.isHidden()
    assert sidebar.playlists_mode

    # Re-expanding restores the tree and the released width pin.
    sidebar.set_collapsed(False)
    assert sidebar.minimumWidth() == Theme.SIDEBAR_PLAYLISTS_MIN
    assert sidebar.maximumWidth() == Theme.SIDEBAR_PLAYLISTS_MAX
    assert sidebar._mode_stack.currentWidget() is sidebar._playlists_page
    assert not sidebar._playlists_btn.isHidden()


def test_playlists_mode_hides_history_but_keeps_settings(qtbot):
    """History gives up its row to the tree; Settings stays reachable."""
    sidebar = _make_sidebar(qtbot)
    assert not sidebar._history_btn.isHidden()

    sidebar.set_playlists_mode(True)
    assert sidebar._history_btn.isHidden()
    assert not sidebar._settings_btn.isHidden()

    sidebar.set_playlists_mode(False)
    assert not sidebar._history_btn.isHidden()

    # Collapsed shows the icon rail, so History comes back even in the mode.
    sidebar.set_playlists_mode(True)
    sidebar.set_collapsed(True)
    assert not sidebar._history_btn.isHidden()
    sidebar.set_collapsed(False)
    assert sidebar._history_btn.isHidden()


def test_playlists_button_stays_out_of_nav_group(qtbot):
    sidebar = _make_sidebar(qtbot)
    assert sidebar._playlists_btn not in sidebar._button_group.buttons()
    # Toggling the mode must not deselect the active page button.
    sidebar.set_current_page("player")
    sidebar.set_playlists_mode(True)
    assert sidebar._buttons["player"].isChecked()


def test_collapse_signal_fires(qtbot):
    sidebar = _make_sidebar(qtbot)
    seen = []
    sidebar.collapsed_changed.connect(seen.append)
    sidebar.set_collapsed(True)
    sidebar.set_collapsed(False)
    assert seen == [True, False]


def test_playlists_tooltip_describes_the_next_click(qtbot):
    """The toggle swaps the nav buttons out rather than opening a panel, which
    a checked button doesn't convey — so the tooltip names both directions."""
    sidebar = _make_sidebar(qtbot)
    off = sidebar._playlists_btn.toolTip()
    assert "Show" in off and "navigation buttons" in off

    sidebar.set_playlists_mode(True)
    on = sidebar._playlists_btn.toolTip()
    assert "Hide" in on and on != off

    sidebar.set_playlists_mode(False)
    assert sidebar._playlists_btn.toolTip() == off


def test_the_hotkey_toggles_the_mode_and_reports_it(qtbot):
    """`toggle_playlists_mode` is the shortcut's door in, and it must be the
    same door the button uses: the checked state, the tooltip and the signal
    MainWindow listens to for the tree's lazy load all hang off that one path.
    """
    sidebar = _make_sidebar(qtbot)
    seen = []
    sidebar.playlists_toggled.connect(seen.append)

    sidebar.toggle_playlists_mode()
    assert sidebar.playlists_mode
    assert sidebar._playlists_btn.isChecked()
    assert sidebar._mode_stack.currentWidget() is sidebar._playlists_page

    sidebar.toggle_playlists_mode()
    assert not sidebar.playlists_mode
    assert not sidebar._playlists_btn.isChecked()
    assert seen == [True, False]


def test_the_hotkey_expands_a_collapsed_rail_in_one_press(qtbot):
    """Collapsed, the Playlists button is hidden and the stack refuses to show
    the tree at all — so a bare flip would emit its signal and change nothing
    visible, which reads as a broken key. One press expands and lands on the
    tree; it never toggles *off* from collapsed, because "show me my playlists"
    is the only thing pressing it can sensibly mean there.
    """
    sidebar = _make_sidebar(qtbot)
    for mode_underneath in (False, True):
        sidebar.set_playlists_mode(mode_underneath)
        sidebar.set_collapsed(True)
        assert sidebar._mode_stack.currentWidget() is sidebar._nav_page

        sidebar.toggle_playlists_mode()

        assert not sidebar.collapsed
        assert sidebar.playlists_mode
        assert sidebar._mode_stack.currentWidget() is sidebar._playlists_page


def test_the_tooltip_advertises_the_shortcut(qtbot):
    """A hotkey nobody can discover is a hotkey nobody uses, and the button is
    the only place to say so. Appended outside the translated sentence on
    purpose — editing an existing tr() source orphans it in eleven languages.
    """
    sidebar = _make_sidebar(qtbot)
    key = PLAYLISTS_SHORTCUT.toString(QKeySequence.SequenceFormat.NativeText)
    assert key
    for mode in (False, True):
        sidebar.set_playlists_mode(mode)
        tip = sidebar._playlists_btn.toolTip()
        assert tip.endswith(f"({key})")
        # The sentence itself is still one of the two authored strings.
        assert ("Show" in tip) is (not mode)
