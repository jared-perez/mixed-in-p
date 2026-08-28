"""The line/outline shown while dragging a playlist or folder to reorder it.

Qt paints no drop indicator for these drags and never did: its own indicator
is only drawn when the *model* accepts the drag's mime type, and
QStandardItemModel refuses NODE_MIME — so ``dragMoveEvent`` leaves its
indicator rect null while still updating ``dropIndicatorPosition``, which is
why the drop always worked and nothing was ever visible. The tree paints its
own marker instead, from the same plan the drop uses.

The panel is shown rather than the bare tree (a child of a hidden parent is
never really visible), and the paint assertion samples a real render — a
marker the view was never told to draw still reads back fine from the
attribute.
"""

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QColor, QDragMoveEvent, QDropEvent

from src.gui.styles.theme import Theme
from src.gui.widgets.playlist_tree import NODE_MIME, NODE_ID_ROLE, PlaylistTreePanel
from src.library import SCRATCH_NODE_ID


@pytest.fixture
def panel(qtbot, tmp_path):
    p = PlaylistTreePanel(db_path=tmp_path / "library.db")
    qtbot.addWidget(p)
    p.resize(240, 400)
    p.show()
    p.ensure_loaded()
    return p


@pytest.fixture
def tree(panel):
    return panel.tree


def node_mime(node_id: int) -> QMimeData:
    mime = QMimeData()
    mime.setData(NODE_MIME, str(node_id).encode("ascii"))
    return mime


def drag_move(tree, mime, point):
    """Deliver a real dragMoveEvent and hand back its verdict.

    *mime* must be held by the caller for the event's lifetime — the event
    keeps only a raw pointer to it.
    """
    event = QDragMoveEvent(
        point,
        Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    tree.dragMoveEvent(event)
    return event


def rect_of(tree, node_id):
    return tree.visualRect(tree._find_item(node_id).index())


class TestMarker:
    def test_gap_between_two_rows_draws_a_line_at_that_gap(self, tree):
        lib = tree.library
        a = lib.create_playlist("A")
        b = lib.create_playlist("B")  # order: B, A
        tree.refresh()

        top = rect_of(tree, b)
        mime = node_mime(a)
        event = drag_move(tree, mime, QPointF(50, top.top() + 1).toPoint())

        assert event.isAccepted()
        kind, line = tree._node_drop_marker
        assert kind == "line"
        assert line.y() == top.top()
        assert line.left() == top.left()

    def test_hovering_a_folder_outlines_it(self, tree):
        lib = tree.library
        a = lib.create_playlist("A")
        f = lib.create_folder("F")
        tree.refresh()

        folder = rect_of(tree, f)
        mime = node_mime(a)
        event = drag_move(tree, mime, folder.center())

        assert event.isAccepted()
        assert tree._node_drop_marker == ("into", folder)

    def test_empty_space_below_marks_the_root_end_at_the_root_indent(self, tree):
        lib = tree.library
        f = lib.create_folder("F")
        child = lib.create_playlist("Child", f)
        a = lib.create_playlist("A")
        tree.refresh()
        tree.setExpanded(tree._find_item(f).index(), True)

        child_rect = rect_of(tree, child)
        assert not child_rect.isNull(), "the folder's child must be on screen"

        mime = node_mime(a)
        event = drag_move(tree, mime, QPointF(50, child_rect.bottom() + 40).toPoint())

        assert event.isAccepted()
        kind, line = tree._node_drop_marker
        assert kind == "line"
        # Under the bottom-most row…
        assert line.y() == child_rect.bottom() + 1
        # …but at the ROOT's indent, not the nested child's: the drop appends
        # at the root, and a line at the child's indent would claim otherwise.
        assert line.left() == rect_of(tree, f).left()
        assert line.left() < child_rect.left()

    def test_a_refused_drop_shows_nothing(self, tree):
        lib = tree.library
        outer = lib.create_folder("Outer")
        inner = lib.create_folder("Inner")
        tree.refresh()
        assert tree._apply_move(inner, outer, 0)
        tree.setExpanded(tree._find_item(outer).index(), True)

        mime = node_mime(outer)  # Outer into its own child
        event = drag_move(tree, mime, rect_of(tree, inner).center())

        assert not event.isAccepted()
        assert tree._node_drop_marker is None

    def test_marker_clears_on_leave(self, tree):
        lib = tree.library
        a = lib.create_playlist("A")
        f = lib.create_folder("F")
        tree.refresh()

        mime = node_mime(a)
        drag_move(tree, mime, rect_of(tree, f).center())
        assert tree._node_drop_marker is not None

        tree.dragLeaveEvent(None)
        assert tree._node_drop_marker is None


class TestMarkerMatchesTheDrop:
    """The line is only worth drawing if it is where the node lands."""

    @staticmethod
    def _drop(tree, mime, point):
        event = QDropEvent(
            QPointF(point),
            Qt.DropAction.MoveAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        tree.dropEvent(event)
        return event

    def test_line_above_a_row_inserts_above_it(self, tree):
        lib = tree.library
        a = lib.create_playlist("A")
        b = lib.create_playlist("B")
        c = lib.create_playlist("C")  # order: C, B, A
        tree.refresh()

        target = rect_of(tree, b)
        mime = node_mime(a)
        point = QPointF(50, target.top() + 1).toPoint()
        drag_move(tree, mime, point)
        _kind, line = tree._node_drop_marker
        assert line.y() == target.top()  # the gap above B

        self._drop(tree, mime, point)
        assert [n.id for n in lib.get_children()] == [c, a, b]
        assert tree._node_drop_marker is None

    def test_outline_on_a_folder_moves_into_it(self, tree):
        lib = tree.library
        a = lib.create_playlist("A")
        f = lib.create_folder("F")
        tree.refresh()

        mime = node_mime(a)
        point = rect_of(tree, f).center()
        drag_move(tree, mime, point)
        assert tree._node_drop_marker[0] == "into"

        self._drop(tree, mime, point)
        assert [n.id for n in lib.get_children(f)] == [a]

    def test_line_below_everything_appends_at_the_root(self, tree):
        lib = tree.library
        a = lib.create_playlist("A")
        b = lib.create_playlist("B")
        c = lib.create_playlist("C")  # order: C, B, A
        tree.refresh()

        mime = node_mime(c)
        point = QPointF(50, rect_of(tree, a).bottom() + 60).toPoint()
        drag_move(tree, mime, point)
        assert tree._node_drop_marker[0] == "line"

        self._drop(tree, mime, point)
        assert [n.id for n in lib.get_children()] == [b, a, c]

    def test_a_refused_drop_moves_nothing(self, tree):
        lib = tree.library
        outer = lib.create_folder("Outer")
        inner = lib.create_folder("Inner")
        tree.refresh()
        tree._apply_move(inner, outer, 0)
        tree.setExpanded(tree._find_item(outer).index(), True)

        mime = node_mime(outer)
        point = rect_of(tree, inner).center()
        event = self._drop(tree, mime, point)

        assert not event.isAccepted()
        assert lib.get_node(outer).parent_id is None
        assert lib.get_node(inner).parent_id == outer


class TestItIsActuallyPainted:
    """A marker only the attribute knows about is the bug being fixed."""

    @staticmethod
    def _accent_rows(tree):
        image = tree.viewport().grab().toImage()
        ratio = image.devicePixelRatio()
        accent = QColor(Theme.NEON_YELLOW)
        rows = set()
        for y in range(image.height()):
            for x in range(0, image.width(), 3):
                if QColor(image.pixelColor(x, y)) == accent:
                    rows.add(int(y / ratio))
                    break
        return rows

    def test_the_line_lands_on_the_gap_it_names(self, qtbot, tree):
        lib = tree.library
        a = lib.create_playlist("A")
        b = lib.create_playlist("B")
        tree.refresh()
        qtbot.wait(10)

        assert not self._accent_rows(tree), "nothing drawn before the drag"

        target = rect_of(tree, b)
        mime = node_mime(a)
        drag_move(tree, mime, QPointF(50, target.top() + 1).toPoint())
        qtbot.wait(10)

        rows = self._accent_rows(tree)
        assert rows, "the drop line must actually be painted"
        # Within one pen width of the gap the marker named.
        assert min(abs(y - target.top()) for y in rows) <= 2

    def test_nothing_is_painted_once_the_drag_leaves(self, qtbot, tree):
        lib = tree.library
        a = lib.create_playlist("A")
        f = lib.create_folder("F")
        tree.refresh()

        mime = node_mime(a)
        drag_move(tree, mime, rect_of(tree, f).center())
        qtbot.wait(10)
        assert self._accent_rows(tree)

        tree.dragLeaveEvent(None)
        qtbot.wait(10)
        assert not self._accent_rows(tree)


def test_scratch_still_sits_at_root_row_zero(tree):
    """The Scratch offset the row arithmetic corrects for."""
    tree.refresh()
    assert tree._model.index(0, 0).data(NODE_ID_ROLE) == SCRATCH_NODE_ID
