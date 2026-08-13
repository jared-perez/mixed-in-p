"""Filtering the playlist tree by node name (the expandable box in its header).

Distinct from the highlight trail, which lights playlists holding a searched
*track*; this hides rows whose *name* doesn't match. The two coexist, and one
test here says so.
"""

import pytest

from src.gui.widgets.playlist_tree import (
    _SEARCH_BTN_WIDTH,
    NODE_ID_ROLE,
    PlaylistTreePanel,
)
from src.library import SCRATCH_NODE_ID


@pytest.fixture
def panel(qtbot, tmp_path):
    p = PlaylistTreePanel(db_path=tmp_path / "library.db")
    qtbot.addWidget(p)
    p.resize(260, 400)
    p.ensure_loaded()
    return p


@pytest.fixture
def tree(panel):
    return panel.tree


@pytest.fixture
def nodes(tree):
    """A small tree with a match two levels deep.

    Scratch
    Breaks
    Crates/
      Peak Time Techno
      Warm Up
      Archive/
        Old Techno 2019
    """
    lib = tree.library
    ids = {
        "breaks": lib.create_playlist("Breaks"),
        "crates": lib.create_folder("Crates"),
    }
    ids["peak"] = lib.create_playlist("Peak Time Techno", ids["crates"])
    ids["warm"] = lib.create_playlist("Warm Up", ids["crates"])
    ids["archive"] = lib.create_folder("Archive", ids["crates"])
    ids["old"] = lib.create_playlist("Old Techno 2019", ids["archive"])
    tree._rebuild()
    return ids


def item(tree, node_id):
    return tree._find_item(node_id)


def hidden(tree, node_id) -> bool:
    """Is this node's row hidden, as the view sees it?"""
    it = item(tree, node_id)
    parent = it.parent()
    parent_index = parent.index() if parent is not None else tree._model.index(-1, -1)
    return tree.isRowHidden(it.row(), parent_index)


def visible_ids(tree, parent_item=None) -> list[int]:
    """Every node still showing, in the order the tree holds them."""
    parent_item = parent_item or tree._model.invisibleRootItem()
    out = []
    for row in range(parent_item.rowCount()):
        child = parent_item.child(row)
        if not tree.isRowHidden(row, parent_item.index()):
            out.append(child.data(NODE_ID_ROLE))
        out += visible_ids(tree, child)
    return out


class TestFiltering:
    def test_it_shows_matches_and_hides_the_rest(self, tree, nodes):
        tree.set_name_filter("techno")

        assert not hidden(tree, nodes["peak"])
        assert not hidden(tree, nodes["old"])
        assert hidden(tree, nodes["breaks"])
        assert hidden(tree, nodes["warm"])
        assert hidden(tree, SCRATCH_NODE_ID)

    def test_matching_is_case_insensitive_and_substring(self, tree, nodes):
        tree.set_name_filter("EAK TIM")

        assert not hidden(tree, nodes["peak"])
        assert hidden(tree, nodes["warm"])

    def test_a_match_keeps_its_ancestors_and_opens_them(self, tree, nodes):
        """A hit the user cannot see is not a hit."""
        tree.set_name_filter("old techno")

        assert not hidden(tree, nodes["crates"])
        assert not hidden(tree, nodes["archive"])
        assert tree.isExpanded(item(tree, nodes["crates"]).index())
        assert tree.isExpanded(item(tree, nodes["archive"]).index())

    def test_a_matching_folder_shows_what_is_in_it(self, tree, nodes):
        tree.set_name_filter("crates")

        assert not hidden(tree, nodes["crates"])
        assert not hidden(tree, nodes["warm"])
        assert not hidden(tree, nodes["old"])
        assert hidden(tree, nodes["breaks"])

    def test_nothing_matches_hides_everything(self, tree, nodes):
        tree.set_name_filter("zzzz")

        assert visible_ids(tree) == []

    def test_it_never_reorders(self, tree, nodes):
        """Manual order is the truth — a filter subtracts rows, it does not
        rearrange them, and sorting must stay off."""
        before = visible_ids(tree)

        tree.set_name_filter("e")  # matches most things, in place
        during = visible_ids(tree)
        tree.clear_name_filter()

        assert during == [i for i in before if i in during]
        assert visible_ids(tree) == before
        assert tree.isSortingEnabled() is False


class TestClearingRestoresTheTree:
    def test_everything_comes_back(self, tree, nodes):
        before = visible_ids(tree)
        tree.set_name_filter("techno")

        tree.clear_name_filter()

        assert visible_ids(tree) == before

    def test_folders_go_back_to_how_the_user_had_them(self, tree, nodes):
        """Revealing matches force-expands ancestors; clearing must undo that
        and not leave the tree hanging open."""
        tree.setExpanded(item(tree, nodes["crates"]).index(), True)
        tree.setExpanded(item(tree, nodes["archive"]).index(), False)

        tree.set_name_filter("old techno")
        assert tree.isExpanded(item(tree, nodes["archive"]).index())  # forced open
        tree.clear_name_filter()

        assert tree.isExpanded(item(tree, nodes["crates"]).index())
        assert not tree.isExpanded(item(tree, nodes["archive"]).index())

    def test_filtering_never_touches_the_stored_expansion(self, tree, nodes):
        """The database records the tree's shape on every toggle. A search is
        not the user opening a folder, so nothing here may reach it — else a
        quit mid-search brings the app back wearing the filter's shape.
        """
        lib = tree.library
        tree.setExpanded(item(tree, nodes["crates"]).index(), True)
        assert lib.expanded_node_ids() == {nodes["crates"]}

        tree.set_name_filter("old techno")
        assert lib.expanded_node_ids() == {nodes["crates"]}  # not archive

        tree.clear_name_filter()
        assert lib.expanded_node_ids() == {nodes["crates"]}

    def test_a_rebuild_mid_filter_keeps_filtering(self, tree, nodes):
        """Rows are replaced wholesale by a rebuild, and hidden-ness belongs
        to the row — a rename during a search must not restore the tree."""
        tree.set_name_filter("techno")

        tree._rebuild()

        assert hidden(tree, nodes["breaks"])
        assert not hidden(tree, nodes["peak"])


class TestTheBox:
    def test_it_swaps_the_create_buttons_for_the_box(self, panel, qtbot):
        """The sidebar is too narrow to carry both at once."""
        panel.show()
        qtbot.waitExposed(panel)
        assert not panel._search_field.isVisible()

        panel._search_btn.setChecked(True)

        assert panel._search_field.isVisible()
        assert not panel._new_playlist_btn.isVisible()
        assert not panel._new_folder_btn.isVisible()

    def test_closing_drops_the_filter(self, panel, tree, nodes, qtbot):
        """A box that is out of sight must not still be hiding playlists."""
        panel.show()
        qtbot.waitExposed(panel)
        panel._search_btn.setChecked(True)
        panel._search_field.setText("techno")
        panel._apply_filter()
        assert hidden(tree, nodes["breaks"])

        panel._search_btn.setChecked(False)

        assert panel._search_field.text() == ""
        assert not hidden(tree, nodes["breaks"])
        assert panel._new_playlist_btn.isVisible()

    def test_typing_filters_after_the_debounce(self, panel, tree, nodes, qtbot):
        panel._search_btn.setChecked(True)

        panel._search_field.setText("techno")
        assert not hidden(tree, nodes["breaks"])  # debounced, not yet applied
        qtbot.waitUntil(lambda: hidden(tree, nodes["breaks"]), timeout=1000)

        assert not hidden(tree, nodes["peak"])

    def test_emptying_the_box_restores_at_once(self, panel, tree, nodes, qtbot):
        """No debounce on the way back: there is no query to wait for, and a
        pause before the tree returns reads as lag."""
        panel._search_btn.setChecked(True)
        panel._search_field.setText("techno")
        qtbot.waitUntil(lambda: hidden(tree, nodes["breaks"]), timeout=1000)

        panel._search_field.setText("")

        assert not hidden(tree, nodes["breaks"])

    def test_the_toggle_tooltip_says_what_the_next_click_does(self, panel):
        closed = panel._search_btn.toolTip()

        panel._search_btn.setChecked(True)

        assert panel._search_btn.toolTip() != closed
        assert closed and panel._search_btn.toolTip()


class TestItFitsTheRealSidebar:
    """This header row is the narrowest in the app.

    A QPushButton centres its label rather than eliding it, so room taken
    from "+ Playlist" doesn't overflow — it cuts the label at BOTH ends. The
    first version of this toggle was a normal 32px bordered button; the row
    looked fine standing alone at 260px and clipped to "⊦ Playlis" at the
    sidebar's actual width, which is where it lives.

    Only the structure is asserted here. This suite runs offscreen with
    Fusion and no app stylesheet, so its pixel metrics are not the app's
    (see tests/gui/README.md) — the fit itself was checked against a
    screenshot of the real window, and `scripts/visual_pass.py` covers the
    translated labels at the end of the batch.
    """

    def test_the_toggle_stays_a_sliver(self, panel):
        assert _SEARCH_BTN_WIDTH <= 24
        assert panel._search_btn.width() == _SEARCH_BTN_WIDTH
        assert not panel._search_btn.text()  # icon-only: no label to translate

    def test_the_open_box_gives_the_row_back(self, panel, qtbot):
        """The box is only affordable because it takes the buttons' place —
        all three at once would not fit."""
        panel.show()
        qtbot.waitExposed(panel)

        panel._search_btn.setChecked(True)

        assert panel._search_field.isVisible()
        assert not panel._new_playlist_btn.isVisible()


class TestCoexistsWithTheTrackHighlight:
    def test_the_highlight_survives_a_filter(self, tree, nodes):
        """Different features: one lights playlists holding a found track,
        the other hides names that don't match."""
        tree.set_highlight({nodes["peak"]}, {nodes["crates"]: 1})

        tree.set_name_filter("techno")
        tree.clear_name_filter()

        assert tree._hl_playlists == {nodes["peak"]}
        assert tree._hl_folders == {nodes["crates"]: 1}
