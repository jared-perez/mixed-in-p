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
    assert not sidebar._nav_page.isHidden() and sidebar._playlists_page.isHidden()


def test_playlists_mode_releases_width_pin(qtbot):
    sidebar = _make_sidebar(qtbot)
    sidebar.set_playlists_mode(True)
    assert sidebar.minimumWidth() == Theme.SIDEBAR_PLAYLISTS_MIN
    assert sidebar.maximumWidth() == Theme.SIDEBAR_PLAYLISTS_MAX
    assert not sidebar._playlists_page.isHidden() and sidebar._nav_page.isHidden()
    assert sidebar._playlists_btn.isChecked()

    sidebar.set_playlists_mode(False)
    assert sidebar.minimumWidth() == sidebar.maximumWidth() == Theme.SIDEBAR_WIDTH
    assert not sidebar._nav_page.isHidden() and sidebar._playlists_page.isHidden()


def test_collapse_in_playlists_mode_pins_but_keeps_mode(qtbot):
    sidebar = _make_sidebar(qtbot)
    sidebar.set_playlists_mode(True)
    sidebar.set_collapsed(True)

    # Collapsed: icon rail at 56px, tree hidden, toggle hidden — mode retained.
    assert sidebar.minimumWidth() == sidebar.maximumWidth() == Theme.SIDEBAR_WIDTH_COLLAPSED
    assert not sidebar._nav_page.isHidden() and sidebar._playlists_page.isHidden()
    assert sidebar._playlists_btn.isHidden()
    assert sidebar.playlists_mode

    # Re-expanding restores the tree and the released width pin.
    sidebar.set_collapsed(False)
    assert sidebar.minimumWidth() == Theme.SIDEBAR_PLAYLISTS_MIN
    assert sidebar.maximumWidth() == Theme.SIDEBAR_PLAYLISTS_MAX
    assert not sidebar._playlists_page.isHidden() and sidebar._nav_page.isHidden()
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
    assert not sidebar._playlists_page.isHidden() and sidebar._nav_page.isHidden()

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
        assert not sidebar._nav_page.isHidden() and sidebar._playlists_page.isHidden()

        sidebar.toggle_playlists_mode()

        assert not sidebar.collapsed
        assert sidebar.playlists_mode
        assert not sidebar._playlists_page.isHidden() and sidebar._nav_page.isHidden()


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


# ------------------------------------------------------------------ split view


def test_split_shows_tree_and_icon_only_nav_side_by_side(qtbot):
    sidebar = _make_sidebar(qtbot)
    sidebar.set_split_mode(True)

    assert not sidebar._playlists_page.isHidden()
    assert not sidebar._nav_page.isHidden()
    # Tree on the left, nav on the right.
    layout = sidebar._mode_stack.layout()
    assert layout.indexOf(sidebar._playlists_page) < layout.indexOf(sidebar._nav_page)
    # Nav glyphs only; the words move to tooltips.
    player = sidebar._buttons["player"]
    assert player.text() == "" and player.toolTip()
    # Settings and History sit under both halves and keep their labels.
    assert sidebar._settings_btn.text()
    assert not sidebar._history_btn.isHidden() and sidebar._history_btn.text()
    # The width pin is released, as in playlists mode.
    assert sidebar.minimumWidth() < sidebar.maximumWidth() == Theme.SIDEBAR_PLAYLISTS_MAX
    assert sidebar.tree_shown()

    sidebar.set_split_mode(False)
    assert sidebar._playlists_page.isHidden()
    assert player.text() == "Player" and player.toolTip() == ""
    assert sidebar.minimumWidth() == sidebar.maximumWidth() == Theme.SIDEBAR_WIDTH


def test_split_overrides_playlists_mode_and_returns_to_it(qtbot):
    sidebar = _make_sidebar(qtbot)
    sidebar.set_playlists_mode(True)
    sidebar.set_split_mode(True)
    assert not sidebar._playlists_btn.isEnabled()
    assert not sidebar._nav_page.isHidden()

    sidebar.set_split_mode(False)
    assert sidebar._playlists_btn.isEnabled()
    assert not sidebar._playlists_page.isHidden() and sidebar._nav_page.isHidden()


def test_collapse_wins_over_split(qtbot):
    sidebar = _make_sidebar(qtbot)
    sidebar.set_split_mode(True)
    sidebar.set_collapsed(True)
    assert sidebar._playlists_page.isHidden()
    assert sidebar._split_btn.isHidden()
    assert sidebar.minimumWidth() == sidebar.maximumWidth() == Theme.SIDEBAR_WIDTH_COLLAPSED
    # Collapsed nav is icon-only everywhere, Settings included.
    assert sidebar._settings_btn.text() == ""

    sidebar.set_collapsed(False)
    assert sidebar.split_mode
    assert not sidebar._playlists_page.isHidden() and not sidebar._nav_page.isHidden()
    assert sidebar._settings_btn.text()
    assert sidebar._buttons["player"].text() == ""


def test_split_tooltip_describes_the_next_click(qtbot):
    sidebar = _make_sidebar(qtbot)
    off = sidebar._split_btn.toolTip()
    assert "both" in off
    sidebar.set_split_mode(True)
    assert sidebar._split_btn.toolTip() != off
    sidebar.set_split_mode(False)
    assert sidebar._split_btn.toolTip() == off


def test_the_hotkey_leaves_split_for_the_tree_alone(qtbot):
    """Split already shows the tree, so the key can only mean "one view"."""
    sidebar = _make_sidebar(qtbot)
    sidebar.set_split_mode(True)
    sidebar.toggle_playlists_mode()
    assert not sidebar.split_mode
    assert sidebar.playlists_mode
    assert not sidebar._playlists_page.isHidden() and sidebar._nav_page.isHidden()


def test_split_uses_the_auto_dot_on_the_narrow_analyze_button(qtbot):
    sidebar = _make_sidebar(qtbot)
    sidebar.set_auto_analyze_badge(True)
    sidebar.set_split_mode(True)
    assert sidebar._auto_badge.isHidden() and not sidebar._auto_dot.isHidden()
    sidebar.set_split_mode(False)
    assert not sidebar._auto_badge.isHidden() and sidebar._auto_dot.isHidden()


def test_chevron_is_half_the_collapsed_button_beside_playlists(qtbot):
    """Expanded, the chevron gives its room to the Playlists label; collapsed,
    it is alone on the row and takes the rail's width again."""
    from src.gui.widgets.sidebar import _RAIL_MARGIN

    sidebar = _make_sidebar(qtbot)
    collapsed_w = Theme.SIDEBAR_WIDTH_COLLAPSED - 2 * _RAIL_MARGIN
    chevron = sidebar._toggle_btn
    assert chevron.minimumWidth() == chevron.maximumWidth() == collapsed_w // 2
    # The glyph fits the thin button; the row height is kept.
    assert chevron.iconSize().width() < chevron.maximumWidth()

    sidebar.set_collapsed(True)
    assert chevron.maximumWidth() > collapsed_w
    sidebar.set_collapsed(False)
    assert chevron.maximumWidth() == collapsed_w // 2


def test_top_row_buttons_get_their_widths_even_with_a_long_label(qtbot):
    """A QPushButton won't shrink below its text, so an overlong Playlists
    label used to squeeze the fixed-width buttons (the split toggle measured
    7px of its 24). The label must be what gives way."""
    from src.gui.widgets.sidebar import _SPLIT_BTN_WIDTH

    sidebar = _make_sidebar(qtbot)
    sidebar._playlists_btn.setText("Playlists" * 6)
    sidebar.show()
    qtbot.wait(10)
    assert sidebar._split_btn.width() == _SPLIT_BTN_WIDTH
    assert sidebar._toggle_btn.width() == sidebar._toggle_btn.maximumWidth()
