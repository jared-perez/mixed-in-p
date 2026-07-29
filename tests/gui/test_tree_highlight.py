"""§10 highlight trail on the playlist tree: paint-only, two distinct states.

The invariants under test:
- A playlist holding the track lights via HL_PLAYLIST_ROLE; every ancestor
  folder lights via HL_COUNT_ROLE with the number of lit playlists beneath.
- Highlighting is paint, not arrangement: nothing expands, order never
  changes, sorting stays off.
- State survives DB-driven rebuilds and can be set before the first load.
"""

import pytest

from src.gui.widgets.playlist_tree import (
    HL_COUNT_ROLE,
    HL_PLAYLIST_ROLE,
    PlaylistTreePanel,
)
from src.library import Library


@pytest.fixture
def panel(qtbot, tmp_path):
    p = PlaylistTreePanel(db_path=tmp_path / "library.db")
    qtbot.addWidget(p)
    p.ensure_loaded()
    return p


@pytest.fixture
def tree(panel):
    return panel.tree


@pytest.fixture
def nested(tree):
    """F > G > P1;  F > P2;  P3 at the root."""
    lib = tree.library
    f = lib.create_folder("F")
    g = lib.create_folder("G", f)
    p1 = lib.create_playlist("P1", g)
    p2 = lib.create_playlist("P2", f)
    p3 = lib.create_playlist("P3")
    tree.refresh()
    return {"f": f, "g": g, "p1": p1, "p2": p2, "p3": p3}


def dfs_texts(tree, parent=None):
    parent = parent or tree._model.invisibleRootItem()
    out = []
    for row in range(parent.rowCount()):
        child = parent.child(row)
        out.append(child.text())
        out.extend(dfs_texts(tree, child))
    return out


class TestHighlightRoles:
    def test_playlist_and_ancestor_folders_light(self, tree, nested):
        tree.set_highlight({nested["p1"]}, {nested["g"]: 1, nested["f"]: 1})
        assert tree._find_item(nested["p1"]).data(HL_PLAYLIST_ROLE)
        assert tree._find_item(nested["g"]).data(HL_COUNT_ROLE) == 1
        assert tree._find_item(nested["f"]).data(HL_COUNT_ROLE) == 1
        assert not tree._find_item(nested["p2"]).data(HL_PLAYLIST_ROLE)
        assert not tree._find_item(nested["p3"]).data(HL_PLAYLIST_ROLE)

    def test_clear_removes_every_role(self, tree, nested):
        tree.set_highlight({nested["p1"], nested["p2"]}, {nested["f"]: 2})
        tree.clear_highlight()
        for key in ("p1", "p2", "p3"):
            assert not tree._find_item(nested[key]).data(HL_PLAYLIST_ROLE)
        for key in ("f", "g"):
            assert not tree._find_item(nested[key]).data(HL_COUNT_ROLE)

    def test_highlight_survives_rebuild(self, tree, nested):
        tree.set_highlight({nested["p2"]}, {nested["f"]: 1})
        tree.refresh()  # DB-driven rebuild (e.g. Save Playlist elsewhere)
        assert tree._find_item(nested["p2"]).data(HL_PLAYLIST_ROLE)
        assert tree._find_item(nested["f"]).data(HL_COUNT_ROLE) == 1

    def test_set_before_first_load_applies_on_build(self, qtbot, tmp_path):
        db = tmp_path / "library.db"
        with Library(db) as lib:
            pid = lib.create_playlist("Early")
        p = PlaylistTreePanel(db_path=db)
        qtbot.addWidget(p)
        p.tree.set_highlight({pid}, {})  # before ensure_loaded
        p.ensure_loaded()
        assert p.tree._find_item(pid).data(HL_PLAYLIST_ROLE)


class TestPaintNotArrangement:
    def test_nothing_expands_and_order_is_stable(self, tree, nested):
        assert not tree.isExpanded(tree._find_item(nested["f"]).index())
        before = dfs_texts(tree)

        tree.set_highlight({nested["p1"]}, {nested["g"]: 1, nested["f"]: 1})
        assert dfs_texts(tree) == before
        assert not tree.isExpanded(tree._find_item(nested["f"]).index())
        assert not tree.isExpanded(tree._find_item(nested["g"]).index())

        tree.clear_highlight()
        assert dfs_texts(tree) == before
        # The one real risk (§10): sorting must never come on.
        assert tree.isSortingEnabled() is False

    def test_highlight_does_not_rename_nodes(self, tree, nested):
        # Role writes go through itemChanged; the guard must keep them from
        # being treated as rename commits (the " · N" suffix is paint-only).
        tree.set_highlight({nested["p2"]}, {nested["f"]: 1})
        assert tree.library.get_node(nested["f"]).name == "F"
        assert tree._find_item(nested["f"]).text() == "F"
