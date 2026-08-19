"""Playlist tree for the sidebar's playlists mode.

A QTreeView over the library's node tree (folders + playlists + the pinned
Scratch row). The database is the source of truth: every structural edit
(create, rename, delete, drag-move) writes through ``src.library`` first and
the model is rebuilt from it, preserving expansion and selection. Manual
order is authoritative — the view must never enable sorting (a stray
``setSortingEnabled(True)`` would scramble ``nodes.position`` under
auto-save; there is a unit test asserting it stays off).

Drag behavior (see the research doc §4c and ``PlaylistTable.startDrag``):
one drag carries both the node id (internal reparent/reorder) and the
member tracks' file URLs + source marker, so the same gesture reorders
inside the tree AND exports to Finder or a DJ app.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from PySide6.QtCore import (
    QMimeData,
    QPoint,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QDrag,
    QFont,
    QIcon,
    QKeySequence,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QPolygonF,
    QShortcut,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QStyledItemDelegate,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from src.library import SCRATCH_NODE_ID, Library
from src.library.playlist_export import (
    FORMATS,
    M3U8,
    TXT,
    export_tracks,
    export_tree,
    safe_filename,
    unique_path,
    write_playlist,
)
from src.metadata.tags import read_metadata
from src.utils.config import load_config
from src.utils.paths import normalize_track_path
from ..models.undo_stack import UndoStack
from ..styles.theme import Theme
from ..workers.playlist_copy_worker import PlaylistCopyThread
from .dialogs.duplicate_policy import resolve_additions
from .drop_zone import AUDIO_EXTENSIONS
from .droppable_table import SOURCE_PAGE_MIME, blank_drag_pixmap

logger = logging.getLogger(__name__)

NODE_ID_ROLE = Qt.ItemDataRole.UserRole + 1
KIND_ROLE = Qt.ItemDataRole.UserRole + 2
# §10 highlight trail — paint-only roles, read by the delegate at draw time.
# HL_PLAYLIST (bool): this playlist contains the searched track(s).
# HL_COUNT (int): folder — how many lit playlists sit beneath it.
HL_PLAYLIST_ROLE = Qt.ItemDataRole.UserRole + 3
HL_COUNT_ROLE = Qt.ItemDataRole.UserRole + 4

# Internal drag payload: the dragged node's id, as ASCII digits.
NODE_MIME = "application/x-mixedinp-node"

_ICON_DRAW = 40  # painted at 2x, displayed at 20 for HiDPI crispness

# The filter toggle beside "+ Playlist" / "+ Folder". Icon-only and flat: this
# row is the narrowest in the app and every pixel here is taken from a
# translated button label that would centre-clip rather than elide.
_SEARCH_BTN_WIDTH = 22

# The per-row create button, floating at the tree's right edge over whichever
# row the cursor is on. It is a child of the viewport at an absolute position,
# never part of the row: the column is ResizeToContents with ElideNone (§4b),
# so an item rect ends at its own text and cannot reach the right edge.
_ROW_ADD_SIZE = 18
_ROW_ADD_MARGIN = 4


def _with_playlist_suffix(path: str, chosen_filter: str) -> str:
    """Make sure an exported path carries a format extension.

    Native dialogs append the selected filter's extension; the offscreen and
    non-native ones don't, and a user who types "Summer Set" would otherwise
    get an extensionless file that ``write_playlist`` can't type.
    """
    if Path(path).suffix.lstrip(".").lower() in FORMATS:
        return path
    for fmt in FORMATS:
        if f"*.{fmt}" in chosen_filter:
            return f"{path}.{fmt}"
    return f"{path}.{M3U8}"


def _widen(box: QMessageBox, width: int) -> None:
    """Give a message box a minimum width.

    QMessageBox sizes itself to its text and ignores setMinimumWidth, so the
    only lever is a zero-height spacer stretched across its grid. Worth the
    hack here: export dialogs carry a full filesystem path and a list of
    import routes, and at the default width a long path pushes those routes
    into wrapping against each other. Silently skipped if a future Qt stops
    using a grid.
    """
    layout = box.layout()
    if isinstance(layout, QGridLayout):
        layout.addItem(
            QSpacerItem(width, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed),
            layout.rowCount(),
            0,
            1,
            layout.columnCount(),
        )


def _tree_icon(kind: str) -> QIcon:
    """Small single-color glyph for a tree row (folder / playlist)."""
    pm = QPixmap(_ICON_DRAW, _ICON_DRAW)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        s = _ICON_DRAW
        pen = QPen(QColor(Theme.TEXT_SECONDARY))
        pen.setWidthF(s * 0.07)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        if kind == "folder":
            # Folder: tab + body outline.
            p.drawPolyline(QPolygonF([
                QPointF(s * 0.15, s * 0.32),
                QPointF(s * 0.15, s * 0.78),
                QPointF(s * 0.85, s * 0.78),
                QPointF(s * 0.85, s * 0.38),
                QPointF(s * 0.48, s * 0.38),
                QPointF(s * 0.40, s * 0.26),
                QPointF(s * 0.15, s * 0.26),
                QPointF(s * 0.15, s * 0.32),
            ]))
        else:
            # Playlist: two list lines + a note (head + stem).
            p.drawLine(QPointF(s * 0.18, s * 0.30), QPointF(s * 0.82, s * 0.30))
            p.drawLine(QPointF(s * 0.18, s * 0.50), QPointF(s * 0.50, s * 0.50))
            p.drawLine(QPointF(s * 0.72, s * 0.46), QPointF(s * 0.72, s * 0.74))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(Theme.TEXT_SECONDARY))
            p.drawEllipse(QPointF(s * 0.645, s * 0.76), s * 0.085, s * 0.07)
    finally:
        p.end()
    icon = QIcon()
    icon.addPixmap(pm)
    return icon


def _make_search_icon() -> QIcon:
    """A magnifier for the tree's filter toggle, drawn to match _tree_icon."""
    pm = QPixmap(_ICON_DRAW, _ICON_DRAW)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        s = _ICON_DRAW
        pen = QPen(QColor(Theme.TEXT_SECONDARY))
        pen.setWidthF(s * 0.09)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(s * 0.16, s * 0.16, s * 0.48, s * 0.48))
        p.drawLine(QPointF(s * 0.62, s * 0.62), QPointF(s * 0.84, s * 0.84))
    finally:
        p.end()
    icon = QIcon()
    icon.addPixmap(pm)
    return icon


def _make_add_icon() -> QIcon:
    """A plus for the per-row create button, drawn to match _tree_icon."""
    pm = QPixmap(_ICON_DRAW, _ICON_DRAW)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        s = _ICON_DRAW
        pen = QPen(QColor(Theme.TEXT_SECONDARY))
        pen.setWidthF(s * 0.11)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(s * 0.5, s * 0.2), QPointF(s * 0.5, s * 0.8))
        p.drawLine(QPointF(s * 0.2, s * 0.5), QPointF(s * 0.8, s * 0.5))
    finally:
        p.end()
    icon = QIcon()
    icon.addPixmap(pm)
    return icon


class _TreeItemDelegate(QStyledItemDelegate):
    """Rename-editor geometry plus the §10 highlight trail's two looks.

    Highlight painting: the two states must never look the same, or the
    user can't tell "arrived" from "keep digging". A playlist holding the
    searched track(s) is arrived — bold ``SEARCH_HIT`` text on a matching
    wash. A folder with lit playlists beneath is keep-going — ``SEARCH_HIT``
    text and a trailing count ("Crates · 2"), no wash. The trail rides the
    *secondary* accent, never the primary: a selected row already paints its
    text ``NEON_YELLOW``, and a yellow trail is unreadable against it. Both
    are paint-only, driven by data roles the view sets; order, expansion,
    and selection are never touched here.

    Editor geometry: the default editor is confined to the item rect, which
    is sized to the OLD text and can be shorter than the editor's own
    chrome — the name being typed ends up invisible. Stretch to the
    viewport's right edge and floor the height at the editor's size hint.
    """

    def __init__(self, view: QTreeView) -> None:
        super().__init__(view)
        self._view = view

    def initStyleOption(self, option, index) -> None:  # noqa: N802 (Qt override)
        super().initStyleOption(option, index)
        if index.data(HL_PLAYLIST_ROLE):
            option.font.setBold(True)
            option.backgroundBrush = QBrush(QColor(Theme.SEARCH_HIT_WASH))
        else:
            count = index.data(HL_COUNT_ROLE)
            if not count:
                return
            option.text = f"{option.text} · {count}"
        # HighlightedText too, so the trail colour survives selection: a lit
        # row that is also selected keeps reading as part of the trail, and
        # selection is carried by the background fill alone.
        for role in (QPalette.ColorRole.Text, QPalette.ColorRole.HighlightedText):
            option.palette.setColor(role, QColor(Theme.SEARCH_HIT))

    def updateEditorGeometry(self, editor, option, index) -> None:  # noqa: N802
        super().updateEditorGeometry(editor, option, index)
        rect = editor.geometry()
        rect.setRight(self._view.viewport().width() - 4)
        min_h = editor.sizeHint().height()
        if rect.height() < min_h:
            rect.setHeight(min_h)
        editor.setGeometry(rect)


class PlaylistTree(QTreeView):
    """The tree view itself. Use :class:`PlaylistTreePanel` in layouts."""

    # Emitted when the user clicks a playlist (or Scratch); the Player
    # integration step loads the clicked list.
    playlist_activated = Signal(int)
    # Something about the nodes themselves changed — created, renamed, deleted,
    # moved. For anything holding a node's *name* outside this tree (the
    # Player's "In Playlist" link), which would otherwise go on showing a name
    # the database no longer has. Carries no payload on purpose: every listener
    # so far re-reads what it needs, and a per-node signal would have to fire
    # once per row for a folder delete's cascade.
    nodes_changed = Signal()
    # Tracks were dropped into a node. The window reloads the Player when
    # this is the list it is showing — otherwise the Player's next
    # auto-save would write its stale visible list back over the drop.
    tracks_added = Signal(int)

    def __init__(self, db_path=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._db_path = db_path
        self._library: Library | None = None
        self._loaded = False
        self._building = False
        # Session undo stack (§11), owned by MainWindow. None until
        # set_undo_stack — deletes and moves then simply aren't recorded.
        self._undo: UndoStack | None = None
        # "Export and Copy Tracks…" runs on a thread (GBs of audio); the
        # folder is remembered so a cancel or failure can remove exactly the
        # one we created, and nothing else.
        self._copy_thread: PlaylistCopyThread | None = None
        self._copy_dialog: QProgressDialog | None = None
        self._copy_target: Path | None = None
        # §10 highlight trail state, kept so it survives DB-driven rebuilds
        # (and a set_highlight arriving before the first load).
        self._hl_playlists: set[int] = set()
        self._hl_folders: dict[int, int] = {}
        # Row a track drag is currently hovering, painted as the drop target.
        # Tracks land IN a playlist, never between two, so this replaces Qt's
        # between-rows indicator for the duration of a file drag.
        self._track_drop_index = None
        # True while _rebuild replays the stored expansion — those setExpanded
        # calls are us restoring the database's state, not the user opening
        # anything, and must not be written back.
        self._restoring_expansion = False
        # Name filter (§5): the lower-cased query, and the view's expansion as
        # it was before the first keystroke. Revealing a match force-expands
        # its ancestors, so without the snapshot a search would silently
        # rewrite the tree's shape — and those expands must not reach the
        # database either, which is what _filtering guards.
        self._name_filter = ""
        self._pre_filter_expanded: set[int] | None = None
        self._filtering = False
        # Which node the floating create button is currently offering to add
        # under. Stored as an id, not a QModelIndex: every structural edit
        # rebuilds the model, and a stale index would still answer isValid().
        self._row_add_node_id: int | None = None

        self.setObjectName("playlistTree")
        self._model = QStandardItemModel(self)
        self.setModel(self._model)

        self.setHeaderHidden(True)
        self.setUniformRowHeights(True)
        self.setIconSize(QSize(20, 20))
        # Long names scroll horizontally instead of eliding (§4b).
        self.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)

        # Manual order is the truth: sorting must NEVER be enabled here.
        self.setSortingEnabled(False)

        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragEnabled(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(True)

        delegate = _TreeItemDelegate(self)
        self.setItemDelegate(delegate)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self._model.itemChanged.connect(self._on_item_changed)
        self.clicked.connect(self._on_clicked)
        # Column width tracks content so the horizontal scrollbar stays honest;
        # the same two signals are where expansion is persisted.
        self.expanded.connect(lambda index: self._on_expansion_changed(index, True))
        self.collapsed.connect(lambda index: self._on_expansion_changed(index, False))

        # Floating per-row create button. A child of the viewport rather than
        # of the view, so it scrolls out of the way with the rows and never
        # covers the scrollbars.
        self.viewport().setMouseTracking(True)
        self._row_add_btn = QPushButton(self.viewport())
        self._row_add_btn.setObjectName("treeRowAddButton")
        self._row_add_btn.setIcon(_make_add_icon())
        self._row_add_btn.setIconSize(QSize(12, 12))
        self._row_add_btn.setFixedSize(_ROW_ADD_SIZE, _ROW_ADD_SIZE)
        self._row_add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._row_add_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._row_add_btn.hide()
        self._row_add_btn.clicked.connect(self._on_row_add_clicked)
        # Scrolling moves rows under a stationary cursor, so the button has to
        # re-aim without a mouse event; closeEditor brings it back after the
        # inline rename it opened for itself.
        self.verticalScrollBar().valueChanged.connect(self._refresh_row_add_button)
        self.horizontalScrollBar().valueChanged.connect(self._refresh_row_add_button)
        delegate.closeEditor.connect(lambda *_: self._refresh_row_add_button())

    # ----------------------------------------------------------------- loading

    def set_library(self, library: Library) -> None:
        """Use a shared library instance (the main window's) instead of
        opening our own connection."""
        self._library = library

    def set_undo_stack(self, stack: UndoStack) -> None:
        """Attach the session undo stack that deletes and moves record onto."""
        self._undo = stack

    def ensure_loaded(self) -> None:
        """Populate on first use. Opens its own library connection only if a
        shared one wasn't attached via set_library()."""
        if self._library is None:
            self._library = Library(self._db_path)
        if not self._loaded:
            self._loaded = True
            self._rebuild()

    def refresh(self) -> None:
        """Re-read the tree from the database (no-op before first load)."""
        if self._loaded:
            self._rebuild()

    def select_node(self, node_id: int) -> None:
        """Reveal and select a node, opening whatever folders enclose it.

        For selections the Player makes on the user's behalf (the "In Playlist"
        link), so the tree agrees with what the Player is showing. A no-op
        before first load: building the tree here would undo the laziness that
        keeps it off the startup path, and a tree nobody has opened has no
        selection to be wrong about.

        The expanding is deliberately *not* suppressed the way `_rebuild`'s and
        the filter's are — the user asked to be taken to this playlist, so its
        folders being open afterwards is the state they should come back to.
        """
        if not self._loaded:
            return
        item = self._find_item(node_id)
        if item is None:
            return
        index = item.index()
        parent = index.parent()
        while parent.isValid():
            self.setExpanded(parent, True)
            parent = parent.parent()
        self.setCurrentIndex(index)
        self.scrollTo(index)

    @property
    def library(self) -> Library | None:
        return self._library

    def _rebuild(self) -> None:
        """Repopulate from the database, preserving expansion, selection, scroll.

        Expansion comes from the database, not from the view we are about to
        clear: every expand/collapse writes through as it happens, so the
        stored set is always current, and reading it here is also what makes
        the tree come back the way it was left in the previous session.

        The scroll matters because most rebuilds change nothing the user can
        see: dropping tracks onto a playlist rebuilds the whole tree and alters
        not one row of it, so a tree scrolled down to the playlist being filled
        jumped back to the top on every drop.
        """
        expanded = (
            self._library.expanded_node_ids() if self._library is not None else set()
        )
        selected = self._current_id()
        scroll = self.verticalScrollBar().value()
        self._building = True
        try:
            self._model.clear()
            root = self._model.invisibleRootItem()
            root.appendRow(self._make_item(SCRATCH_NODE_ID, "scratch", self.tr("Scratch")))
            self._append_children(root, None)
        finally:
            self._building = False
        self._restoring_expansion = True
        try:
            for node_id in expanded:
                item = self._find_item(node_id)
                if item is not None:
                    self.setExpanded(item.index(), True)
        finally:
            self._restoring_expansion = False
        if selected is not None:
            item = self._find_item(selected)
            if item is not None:
                self.setCurrentIndex(item.index())
        if self._hl_playlists or self._hl_folders:
            self._apply_highlight()
        # A rebuild replaces every row, and hidden-ness belongs to the row, so
        # an active filter has to be re-applied or a rename mid-search brings
        # the whole tree back.
        if self._name_filter:
            self._apply_name_filter()
        self.resizeColumnToContents(0)
        # Last, because restoring the selection *scrolls to it*: setCurrentIndex
        # calls scrollTo, so putting this any earlier would have it overwritten
        # by the very restore above. Qt has already recomputed the range by
        # here (measured), so an out-of-date position clamps rather than
        # silently landing at 0, and a rebuild that really did move things —
        # _create_node's — scrolls to its new row after this returns.
        self.verticalScrollBar().setValue(scroll)
        # Every row the button could have been aimed at is gone. Re-aim on the
        # next tick rather than now: a rebuild from _create_node is followed by
        # an edit() in the same call, and the deferred pass sees the editor.
        self._hide_row_add_button()
        QTimer.singleShot(0, self, self._refresh_row_add_button)
        # Every create, delete and move funnels through here. A rename does
        # not — it edits the item in place — so _on_item_changed emits too.
        self.nodes_changed.emit()

    def _append_children(self, parent_item: QStandardItem, parent_id: int | None) -> None:
        for node in self._library.get_children(parent_id):
            item = self._make_item(node.id, node.kind, node.name)
            parent_item.appendRow(item)
            if node.kind == "folder":
                self._append_children(item, node.id)

    def _make_item(self, node_id: int, kind: str, name: str) -> QStandardItem:
        item = QStandardItem(name)
        item.setData(node_id, NODE_ID_ROLE)
        item.setData(kind, KIND_ROLE)
        if kind == "scratch":
            # Pinned working list: not editable, not draggable, not a target.
            item.setEditable(False)
            item.setDragEnabled(False)
            item.setDropEnabled(False)
            font = QFont()
            font.setItalic(True)
            item.setFont(font)
        elif kind == "playlist":
            item.setIcon(_tree_icon("playlist"))
            item.setDropEnabled(False)  # nodes can't be dropped INTO a playlist
        else:
            item.setIcon(_tree_icon("folder"))
        return item

    # -------------------------------------------------- highlight trail (§10)

    def set_highlight(
        self, playlist_ids: set[int], folder_counts: dict[int, int]
    ) -> None:
        """Light the trail for a search selection: every playlist holding the
        track(s), and every ancestor folder with how many lit playlists sit
        beneath it.

        Paint only — nothing expands, nothing scrolls, nothing moves, and
        selection is untouched. The user follows the lit folders down at
        their own pace (or ignores them). State persists across rebuilds
        until replaced or cleared.
        """
        playlist_ids = set(playlist_ids)
        folder_counts = dict(folder_counts)
        if playlist_ids == self._hl_playlists and folder_counts == self._hl_folders:
            return
        self._hl_playlists = playlist_ids
        self._hl_folders = folder_counts
        if self._loaded:
            self._apply_highlight()

    def clear_highlight(self) -> None:
        self.set_highlight(set(), {})

    def _apply_highlight(self, parent: QStandardItem | None = None) -> None:
        at_root = parent is None
        parent = parent or self._model.invisibleRootItem()
        if at_root:
            self._building = True  # role writes are not rename commits
        try:
            for row in range(parent.rowCount()):
                child = parent.child(row)
                node_id = child.data(NODE_ID_ROLE)
                kind = child.data(KIND_ROLE)
                lit = kind == "playlist" and node_id in self._hl_playlists
                count = self._hl_folders.get(node_id, 0) if kind == "folder" else 0
                if bool(child.data(HL_PLAYLIST_ROLE)) != lit:
                    child.setData(lit or None, HL_PLAYLIST_ROLE)
                if (child.data(HL_COUNT_ROLE) or 0) != count:
                    child.setData(count or None, HL_COUNT_ROLE)
                self._apply_highlight(child)
        finally:
            if at_root:
                self._building = False
        if at_root:
            # The " · N" suffixes change row widths; keep the horizontal
            # scrollbar honest without touching anything positional.
            self.resizeColumnToContents(0)
            self.viewport().update()

    # ------------------------------------------------- name filter (§5)

    def set_name_filter(self, text: str) -> None:
        """Show only nodes whose name contains *text*, plus their ancestors.

        A different feature from the highlight trail above, which lights
        playlists holding a searched *track*. This one filters by node name
        and hides what doesn't match; the two coexist untouched.

        Hiding rows, never sorting or re-parenting them: manual order is the
        truth here (see ``setSortingEnabled(False)``), so a filtered tree is
        the same tree with rows missing.
        """
        query = text.strip().lower()
        if query == self._name_filter:
            return
        if query and self._pre_filter_expanded is None:
            # Before the first keystroke only: mid-search expansions are the
            # filter's doing and must not become the state we restore to.
            self._pre_filter_expanded = self._expanded_ids()
        self._name_filter = query
        self._apply_name_filter()

    def clear_name_filter(self) -> None:
        """Drop the filter and put the tree back the way the user had it."""
        self.set_name_filter("")

    def _apply_name_filter(self) -> None:
        if not self._loaded:
            return
        root = self._model.invisibleRootItem()
        # Nothing in here is a user gesture, so none of it is persisted.
        self._filtering = True
        try:
            if self._name_filter:
                self._filter_children(root, self._name_filter, forced=False)
            else:
                self._show_all(root)
                snapshot, self._pre_filter_expanded = self._pre_filter_expanded, None
                if snapshot is not None:
                    self._restore_expansion(root, snapshot)
        finally:
            self._filtering = False
        self.resizeColumnToContents(0)

    def _filter_children(
        self, parent_item: QStandardItem, query: str, *, forced: bool
    ) -> bool:
        """Hide non-matching rows under *parent_item*. True if any is shown.

        ``forced`` means an ancestor matched, so everything below it stays
        visible — searching for a folder shows what is in it.
        """
        parent_index = parent_item.index()  # invalid at the root, as Qt wants
        any_shown = False
        for row in range(parent_item.rowCount()):
            child = parent_item.child(row)
            matches = forced or query in child.text().lower()
            below = self._filter_children(child, query, forced=matches)
            shown = matches or below
            self.setRowHidden(row, parent_index, not shown)
            if below and not forced:
                # Open the folder the match is buried in — otherwise the
                # filter reports a hit the user cannot see.
                self.setExpanded(child.index(), True)
            any_shown = any_shown or shown
        return any_shown

    def _show_all(self, parent_item: QStandardItem) -> None:
        parent_index = parent_item.index()
        for row in range(parent_item.rowCount()):
            self.setRowHidden(row, parent_index, False)
            self._show_all(parent_item.child(row))

    def _restore_expansion(self, parent_item: QStandardItem, open_ids: set[int]) -> None:
        for row in range(parent_item.rowCount()):
            child = parent_item.child(row)
            self.setExpanded(child.index(), child.data(NODE_ID_ROLE) in open_ids)
            self._restore_expansion(child, open_ids)

    # ----------------------------------------------------- id <-> item helpers

    def _find_item(self, node_id: int, parent: QStandardItem | None = None) -> QStandardItem | None:
        parent = parent or self._model.invisibleRootItem()
        for row in range(parent.rowCount()):
            child = parent.child(row)
            if child.data(NODE_ID_ROLE) == node_id:
                return child
            found = self._find_item(node_id, child)
            if found is not None:
                return found
        return None

    def _expanded_ids(self, parent: QStandardItem | None = None) -> set[int]:
        """Which folders the VIEW currently has open (the database is the
        record of it — see `_on_expansion_changed`)."""
        parent = parent or self._model.invisibleRootItem()
        ids: set[int] = set()
        for row in range(parent.rowCount()):
            child = parent.child(row)
            if self.isExpanded(child.index()):
                ids.add(child.data(NODE_ID_ROLE))
            ids |= self._expanded_ids(child)
        return ids

    def _on_expansion_changed(self, index, expanded: bool) -> None:
        """Persist a folder's open/closed state, so it survives a restart.

        Written on every toggle rather than at shutdown: there is no reliable
        close hook for a panel, and a crash or a force-quit should not be the
        difference between remembering the tree's shape and losing it.
        """
        self.resizeColumnToContents(0)
        if (
            self._restoring_expansion
            or self._filtering
            or self._building
            or self._library is None
        ):
            return
        node_id = index.data(NODE_ID_ROLE)
        if node_id is not None:
            self._library.set_node_expanded(node_id, expanded)

    def _current_id(self) -> int | None:
        index = self.currentIndex()
        return index.data(NODE_ID_ROLE) if index.isValid() else None

    # ------------------------------------------------- floating create button

    def _row_index_at(self, pos):
        """The row at *pos*'s height, whatever its horizontal position.

        ``indexAt`` answers about a **cell**, and the one column is sized to
        its own content (ResizeToContents, no stretch) — so a point out at the
        viewport's right edge is past the end of the only column and reads as
        empty space, even with a row plainly drawn at that height. That is
        precisely where the button lives, and where the cursor has to travel
        to click it, so hit-testing with ``indexAt`` alone made the button
        disappear the moment the user reached for it.
        """
        index = self.indexAt(pos)
        if index.isValid():
            return index
        # Retake at the column's own left edge (clamped into view, since a
        # horizontal scroll puts that edge at a negative x).
        return self.indexAt(QPoint(max(0, self.columnViewportPosition(0)), pos.y()))

    def _aim_row_add_button(self, pos) -> None:
        """Park the create button on the row at viewport point *pos*.

        Pinned to the viewport's right edge, not to the row: the column is
        ResizeToContents with ElideNone, so the item rect stops at the end of
        the name and a long name scrolls sideways underneath the button.
        """
        if self.state() == QAbstractItemView.State.EditingState:
            self._hide_row_add_button()
            return
        index = self._row_index_at(pos)
        kind = index.data(KIND_ROLE) if index.isValid() else None
        # Scratch is pinned and owns no siblings the user arranges — offering
        # to create beside it would be a third route to the "+ Playlist"
        # button already sitting above the tree.
        if kind not in ("playlist", "folder"):
            self._hide_row_add_button()
            return
        rect = self.visualRect(index)
        if rect.isEmpty():
            self._hide_row_add_button()
            return
        btn = self._row_add_btn
        node_id = index.data(NODE_ID_ROLE)
        if node_id != self._row_add_node_id:
            self._row_add_node_id = node_id
            btn.setToolTip(
                self.tr("New playlist inside this folder")
                if kind == "folder"
                else self.tr("New playlist below this one")
            )
        btn.move(
            self.viewport().width() - btn.width() - _ROW_ADD_MARGIN,
            rect.center().y() - btn.height() // 2,
        )
        btn.show()
        btn.raise_()

    def _refresh_row_add_button(self) -> None:
        """Re-aim from the real cursor position, for the times there is no
        mouse event to read one off (a scroll, a rebuild, an editor closing)."""
        if not self._loaded:
            self._hide_row_add_button()
            return
        pos = self.viewport().mapFromGlobal(QCursor.pos())
        if not self.viewport().rect().contains(pos):
            self._hide_row_add_button()
            return
        self._aim_row_add_button(pos)

    def _hide_row_add_button(self) -> None:
        self._row_add_node_id = None
        self._row_add_btn.hide()

    def _on_row_add_clicked(self) -> None:
        """Create a playlist: below a playlist row, or at the top inside a folder.

        Always a playlist, never a folder — a folder inside a folder is what
        the row's own right-click menu is for, and a button that made one was
        a second route to the same thing on the row least in need of it.
        ``create_playlist`` inserts at position 0, which is the top of the
        folder's children with no move to replay.

        Read back from the database rather than trusted from the row: the
        button is aimed by hover and the tree can have been rebuilt (a drop, a
        delete, an undo) since it last moved.
        """
        node_id = self._row_add_node_id
        if node_id is None or self._library is None:
            return
        node = self._library.get_node(node_id)
        if node is None:
            return
        self._hide_row_add_button()
        if node.kind == "folder":
            self._create_node("playlist", node_id)
        elif node.kind == "playlist":
            self._create_node("playlist", node.parent_id, after_id=node_id)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().mouseMoveEvent(event)
        self._aim_row_add_button(event.position().toPoint())

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # Not an unconditional hide: entering the button is itself a Leave for
        # the viewport it is a child of, and hiding there would snatch the
        # button out from under the click it was reached for. Re-aiming
        # instead keeps it up (the cursor is still inside the viewport) and
        # drops it only when the cursor has really gone.
        self._refresh_row_add_button()
        super().leaveEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._refresh_row_add_button()

    # -------------------------------------------------------------------- CRUD

    def create_playlist(self, parent_id: int | None = None) -> None:
        self._create_node("playlist", parent_id)

    def create_folder(self, parent_id: int | None = None) -> None:
        self._create_node("folder", parent_id)

    def _create_node(
        self, kind: str, parent_id: int | None, *, after_id: int | None = None
    ) -> None:
        """Create a folder or playlist, optionally right below a sibling.

        ``after_id`` is what the floating row button uses: "new playlist below
        this one" has to survive ``Library._create_node`` inserting at the
        *top* of the parent's children, so the position is taken before the
        insert and replayed as a move afterwards.
        """
        self.ensure_loaded()
        name = self.tr("New Playlist") if kind == "playlist" else self.tr("New Folder")
        anchor_pos: int | None = None
        if after_id is not None:
            anchor = self._library.get_node(after_id)
            if anchor is not None and anchor.parent_id == parent_id:
                anchor_pos = anchor.position
        if kind == "playlist":
            node_id = self._library.create_playlist(name, parent_id)
        else:
            node_id = self._library.create_folder(name, parent_id)
        if anchor_pos is not None:
            # The new node went in at 0, so the anchor sits one lower than the
            # position read above — but move_node counts siblings with the
            # moved node removed, which is the pre-insert order, and there the
            # anchor is still at anchor_pos. Slot after it.
            self._library.move_node(node_id, parent_id, anchor_pos + 1)
        self._rebuild()
        item = self._find_item(node_id)
        if item is not None:
            if parent_id is not None:
                parent_item = self._find_item(parent_id)
                if parent_item is not None:
                    self.setExpanded(parent_item.index(), True)
            self.setCurrentIndex(item.index())
            # Reveals the new row on its own — nothing extra needed here even
            # now that _rebuild keeps the scroll. A scrollTo was written for
            # this and removed again: with the tree really on screen a
            # mutation test would not fail against its absence, so it was a
            # comment asserting a trap that isn't there.
            self.edit(item.index())  # name it right away

    def _on_item_changed(self, item: QStandardItem) -> None:
        """Inline rename committed — write through, or revert an empty name."""
        if self._building or self._library is None:
            return
        node_id = item.data(NODE_ID_ROLE)
        node = self._library.get_node(node_id)
        if node is None:
            return
        name = item.text().strip()
        if not name:
            self._building = True
            item.setText(node.name)
            self._building = False
            return
        if name != node.name:
            self._library.rename_node(node_id, name)
            if name != item.text():
                self._building = True
                item.setText(name)  # normalize stripped whitespace
                self._building = False
            self.nodes_changed.emit()
        self.resizeColumnToContents(0)

    def _delete_node(self, node_id: int) -> None:
        node = self._library.get_node(node_id)
        if node is None:
            return
        if node.kind == "folder":
            text = self.tr('Delete folder "{0}" and everything inside it?').format(node.name)
        else:
            text = self.tr('Delete playlist "{0}"?').format(node.name)
        reply = QMessageBox.question(
            self,
            self.tr("Delete"),
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        # The confirm is the first line of defence; undo is the second (§11).
        # Snapshot before the cascade — a folder delete takes every playlist
        # underneath it, and their contents, with it.
        snapshot = self._library.snapshot_subtree(node_id)
        self._library.delete_node(node_id)
        if self._undo is not None:
            # Untranslated on purpose — an internal identifier, not UI prose;
            # nothing displays undo labels yet.
            label = "Delete Folder" if node.kind == "folder" else "Delete Playlist"
            library = self._library
            self._undo.push(label, lambda: library.restore_subtree(snapshot))
        self._rebuild()

    # ------------------------------------------------------------ context menu

    def _on_context_menu(self, pos) -> None:
        self.ensure_loaded()
        index = self.indexAt(pos)
        item = self._model.itemFromIndex(index) if index.isValid() else None
        kind = item.data(KIND_ROLE) if item is not None else None
        node_id = item.data(NODE_ID_ROLE) if item is not None else None

        menu = QMenu(self)
        if kind == "folder":
            menu.addAction(self.tr("New Playlist"), lambda: self.create_playlist(node_id))
            menu.addAction(self.tr("New Folder"), lambda: self.create_folder(node_id))
            menu.addSeparator()
            menu.addAction(self.tr("Rename"), lambda: self.edit(index))
            menu.addAction(self.tr("Delete…"), lambda: self._delete_node(node_id))
            menu.addSeparator()
            menu.addAction(self.tr("Export Folder…"), lambda: self._export_folder(node_id))
        elif kind in ("playlist", "scratch"):
            if kind == "playlist":
                menu.addAction(self.tr("Rename"), lambda: self.edit(index))
                menu.addAction(self.tr("Delete…"), lambda: self._delete_node(node_id))
                menu.addSeparator()
            # Scratch is a real playlist with real contents — exporting it is
            # how you get a set out without naming it first.
            menu.addAction(self.tr("Export…"), lambda: self._export_playlist(node_id))
            menu.addAction(
                self.tr("Export and Copy Tracks…"),
                lambda: self._export_with_tracks(node_id),
            )
        else:  # empty background: create at the root
            menu.addAction(self.tr("New Playlist"), lambda: self.create_playlist(None))
            menu.addAction(self.tr("New Folder"), lambda: self.create_folder(None))
        menu.exec(self.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------ export

    def _export_playlist(self, node_id: int) -> None:
        """Write one playlist out as .m3u8 / .m3u / .txt (§5, §6)."""
        node = self._library.get_node(node_id)
        if node is None:
            return
        tracks = export_tracks(self._library, node_id)
        if not tracks:
            QMessageBox.information(
                self,
                self.tr("Export Playlist"),
                self.tr("This playlist is empty — there is nothing to export."),
            )
            return
        # Filter string is not wrapped: file-glob filters are config, not prose.
        path, chosen = QFileDialog.getSaveFileName(
            self,
            self.tr("Export Playlist"),
            f"{safe_filename(node.name)}.{M3U8}",
            "Playlist (*.m3u8);;Playlist (*.m3u);;Tracklist (*.txt)",
        )
        if not path:
            return
        path = _with_playlist_suffix(path, chosen)
        try:
            count = write_playlist(
                path, tracks, absolute=self._absolute_paths(), title=node.name
            )
        except (OSError, ValueError) as exc:
            self._export_failed(exc)
            return
        self._export_complete(
            self.tr("Exported {0} tracks to:\n{1}").format(count, path),
            # A .txt tracklist isn't going into any DJ app — no import routes.
            hint=Path(path).suffix.lower() != f".{TXT}",
        )

    def _export_folder(self, node_id: int) -> None:
        """Write a folder's whole subtree out as a mirrored directory."""
        node = self._library.get_node(node_id)
        if node is None:
            return
        directory = QFileDialog.getExistingDirectory(self, self.tr("Export Folder"))
        if not directory:
            return
        try:
            # Everything lands inside a folder of its own rather than
            # scattering playlists into whatever the user picked.
            target = unique_path(directory, safe_filename(node.name), "")
            target.mkdir(parents=True, exist_ok=True)
            playlists, tracks = export_tree(
                self._library,
                target,
                parent_id=node_id,
                absolute=self._absolute_paths(),
            )
        except (OSError, ValueError) as exc:
            self._export_failed(exc)
            return
        self._export_complete(
            self.tr("Exported {0} playlists ({1} tracks) to:\n{2}").format(
                playlists, tracks, target
            )
        )

    def _export_with_tracks(self, node_id: int) -> None:
        """Copy a playlist's audio into a new folder with a playlist beside it.

        §5's third option, and the one DJs actually want for sharing: one
        action produces a zip-and-send-ready folder that works on any machine
        because every path in it is relative.
        """
        node = self._library.get_node(node_id)
        if node is None:
            return
        tracks = export_tracks(self._library, node_id)
        if not tracks:
            QMessageBox.information(
                self,
                self.tr("Export and Copy Tracks"),
                self.tr("This playlist is empty — there is nothing to export."),
            )
            return
        if self._copy_thread is not None and self._copy_thread.isRunning():
            QMessageBox.warning(
                self,
                self.tr("Export in Progress"),
                self.tr("An export is already running. Please wait."),
            )
            return
        parent_dir = QFileDialog.getExistingDirectory(
            self, self.tr("Choose Where to Create the Folder")
        )
        if not parent_dir:
            return
        try:
            target = unique_path(parent_dir, safe_filename(node.name), "")
            target.mkdir(parents=True)
        except OSError as exc:
            self._export_failed(exc)
            return

        self._copy_target = target
        self._copy_dialog = QProgressDialog(
            self.tr("Copying tracks…"), self.tr("Cancel"), 0, len(tracks), self
        )
        self._copy_dialog.setWindowTitle(self.tr("Export and Copy Tracks"))
        self._copy_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._copy_dialog.setMinimumDuration(0)
        self._copy_dialog.setAutoClose(False)
        self._copy_dialog.setAutoReset(False)

        thread = PlaylistCopyThread(tracks, target, node.name, parent=self)
        self._copy_dialog.canceled.connect(thread.cancel)
        thread.progress.connect(self._on_copy_progress)
        thread.completed.connect(self._on_copy_complete)
        thread.failed.connect(self._on_copy_failed)
        thread.cancelled.connect(self._on_copy_cancelled)
        thread.finished.connect(self._close_copy_dialog)
        self._copy_thread = thread
        thread.start()

    def _on_copy_progress(self, progress) -> None:
        # Held locally: setValue() on a modal QProgressDialog pumps the event
        # loop, so the copy can finish and clear self._copy_dialog part-way
        # through this very method.
        dialog = self._copy_dialog
        if dialog is None:
            return
        dialog.setValue(progress.completed)
        if progress.current_file:
            dialog.setLabelText(self.tr("Copying {0}").format(progress.current_file))

    def _close_copy_dialog(self) -> None:
        if self._copy_dialog is not None:
            self._copy_dialog.close()
            self._copy_dialog = None
        self._copy_thread = None

    def _on_copy_complete(self, path: str, count: int, missing: list) -> None:
        message = self.tr("Exported {0} tracks to:\n{1}").format(count, path)
        if missing:
            # Skipped rather than copied as broken entries — one unresolvable
            # path would have forced the whole playlist onto absolute paths.
            # %n + the count argument is Qt's plural form; several target
            # languages have more than two, so this can't be concatenation.
            message += "\n\n" + self.tr(
                "%n track(s) could not be found and were skipped.", "", len(missing)
            )
        self._export_complete(message)

    def _on_copy_failed(self, error: str) -> None:
        self._remove_partial_copy()
        QMessageBox.warning(
            self,
            self.tr("Export failed"),
            self.tr("Could not write the file:\n{0}").format(error),
        )

    def _on_copy_cancelled(self) -> None:
        """Clean up: a half-copied folder is worse than no folder."""
        self._remove_partial_copy()

    def _remove_partial_copy(self) -> None:
        """Delete the folder we created, and only ever that one."""
        target, self._copy_target = self._copy_target, None
        if target is None:
            return
        try:
            shutil.rmtree(target)
        except OSError as exc:
            logger.warning("Could not clean up %s: %s", target, exc)

    def _absolute_paths(self) -> bool:
        """The Settings override; read per export so it is always current."""
        return load_config().export_absolute_paths

    def _import_hint(self) -> str:
        """Where to import the file, since Rekordbox's menu is buried (§6).

        One app per line: as a single sentence the three routes wrapped into
        each other in the dialog and read as one run-on instruction. Kept as
        separate tr() strings so a translation can grow without re-wrapping
        the others.
        """
        return "\n".join(
            (
                self.tr("Serato — drag the file onto the crate panel"),
                self.tr("Rekordbox — File → Import Playlist"),
                self.tr("Traktor — File → Import"),
            )
        )

    def _export_complete(self, message: str, *, hint: bool = True) -> None:
        """Success dialog, with the import routes as Qt's informative text.

        Informative text renders below the main line in normal weight, which
        separates "here is your file" from "here is how to use it" without
        the two becoming one bold paragraph.
        """
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(self.tr("Export complete"))
        box.setText(message)
        if hint:
            box.setInformativeText(self.tr("To import it:") + "\n" + self._import_hint())
        _widen(box, 520)
        box.exec()

    def _export_failed(self, exc: Exception) -> None:
        logger.error("Playlist export failed: %s", exc)
        QMessageBox.warning(
            self,
            self.tr("Export failed"),
            self.tr("Could not write the file:\n{0}").format(exc),
        )

    # -------------------------------------------------------------- activation

    def _on_clicked(self, index) -> None:
        kind = index.data(KIND_ROLE)
        if kind in ("playlist", "scratch"):
            self.playlist_activated.emit(index.data(NODE_ID_ROLE))

    # ---------------------------------------------------------------- drag out

    def _paths_under(self, node_id: int, kind: str) -> list[str]:
        """Member track paths: a playlist's items in order; a folder's whole
        subtree flattened (deduped, first occurrence wins)."""
        if kind == "playlist":
            paths = [t.path for t in self._library.get_items(node_id)]
        else:
            paths = []
            for child in self._library.get_children(node_id):
                paths.extend(self._paths_under(child.id, child.kind))
        seen: set[str] = set()
        out: list[str] = []
        for p in paths:
            if p not in seen:
                seen.add(p)
                out.append(p)
        return out

    def startDrag(self, supportedActions) -> None:  # noqa: N802 (Qt override)
        index = self.currentIndex()
        if not index.isValid():
            return
        kind = index.data(KIND_ROLE)
        node_id = index.data(NODE_ID_ROLE)
        if kind == "scratch":
            return
        # One drag, two payloads (§4c): the node id for internal moves, and
        # the member tracks' file URLs + source marker for dragging out to
        # Finder / Rekordbox / Serato / Traktor.
        mime = QMimeData()
        mime.setData(NODE_MIME, str(node_id).encode("ascii"))
        paths = self._paths_under(node_id, kind)
        if paths:
            mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
            mime.setData(SOURCE_PAGE_MIME, b"playlists")
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(blank_drag_pixmap())
        drag.exec(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction)
        # No cleanup here: an internal move already rewrote the database in
        # dropEvent; an external drop is a copy and removes nothing.

    # ------------------------------------------------------------ drop (moves)

    @staticmethod
    def _is_track_drag(mime) -> bool:
        """A drag of audio files rather than of a tree node.

        NODE_MIME is checked first everywhere, because the tree's own drags
        carry file URLs too (§4c) — a playlist dragged onto another playlist
        must keep meaning "move the node", which the node branch refuses.
        """
        if mime.hasFormat(NODE_MIME) or not mime.hasUrls():
            return False
        return any(
            Path(url.toLocalFile()).suffix.lower() in AUDIO_EXTENSIONS
            for url in mime.urls()
        )

    def _track_drop_target(self, pos) -> int | None:
        """The node id a track drop at *pos* would land in, if any.

        Deliberately ignores the drop indicator and just takes the row under
        the cursor: playlist rows are ``setDropEnabled(False)`` (so nodes
        can't be dropped into them), which means Qt would only ever report
        Above/Below over one. Tracks have no meaningful "between" anyway.
        """
        index = self.indexAt(pos)
        if not index.isValid():
            return None
        if index.data(KIND_ROLE) not in ("playlist", "scratch"):
            return None  # a folder holds nodes, not tracks
        return index.data(NODE_ID_ROLE)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # Nothing floating over the rows while a drag is picking one out.
        self._hide_row_add_button()
        if event.mimeData().hasFormat(NODE_MIME):
            event.acceptProposedAction()
        elif self._is_track_drag(event.mimeData()):
            # Our own indicator takes over for the duration of the drag.
            self.setDropIndicatorShown(False)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # Let the base class run so the drop indicator tracks the cursor,
        # then force our own verdict (the default model would reject NODE_MIME).
        super().dragMoveEvent(event)
        if event.mimeData().hasFormat(NODE_MIME):
            event.acceptProposedAction()
            return
        if self._is_track_drag(event.mimeData()):
            pos = event.position().toPoint()
            target = self._track_drop_target(pos)
            self._set_track_drop_index(self.indexAt(pos) if target is not None else None)
            if target is None:
                event.ignore()
            else:
                event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._clear_track_drop_row()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self._is_track_drag(event.mimeData()):
            self._drop_tracks(event)
            return
        self._clear_track_drop_row()
        if not event.mimeData().hasFormat(NODE_MIME):
            event.ignore()
            return
        node_id = int(bytes(event.mimeData().data(NODE_MIME)))

        index = self.indexAt(event.position().toPoint())
        drop_pos = self.dropIndicatorPosition()
        dip = QAbstractItemView.DropIndicatorPosition

        if not index.isValid() or drop_pos == dip.OnViewport:
            parent_id = None
            row = len(self._library.get_children(None))  # append at root
        elif drop_pos == dip.OnItem:
            if index.data(KIND_ROLE) != "folder":
                event.ignore()
                return
            parent_id = index.data(NODE_ID_ROLE)
            row = len(self._library.get_children(parent_id))  # append inside
        else:  # AboveItem / BelowItem — sibling insert relative to the target
            parent_index = index.parent()
            parent_id = parent_index.data(NODE_ID_ROLE) if parent_index.isValid() else None
            row = index.row() + (1 if drop_pos == dip.BelowItem else 0)
            if parent_id is None:
                row = max(0, row - 1)  # Scratch occupies model row 0 at the root

        if not self._apply_move(node_id, parent_id, row):
            event.ignore()
            return
        event.acceptProposedAction()

    # ------------------------------------------------------- drop (add tracks)

    def _set_track_drop_index(self, index) -> None:
        if index is not None and not index.isValid():
            index = None
        current = self._track_drop_index
        same = (
            current is not None
            and index is not None
            and current.row() == index.row()
            and current.parent() == index.parent()
        )
        if same or (current is None and index is None):
            return
        self._track_drop_index = index
        self.viewport().update()

    def _clear_track_drop_row(self) -> None:
        self._set_track_drop_index(None)
        self.setDropIndicatorShown(True)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().paintEvent(event)
        if self._track_drop_index is None:
            return
        rect = self.visualRect(self._track_drop_index)
        if rect.isNull():
            return
        # Outline rather than a fill: the row underneath keeps its own text
        # colours (including a lit search-trail row), and an outline reads as
        # "into this one" where a wash reads as selection.
        painter = QPainter(self.viewport())
        pen = QPen(QColor(Theme.NEON_YELLOW))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawRect(rect.adjusted(1, 1, -2, -2))
        painter.end()

    def _drop_tracks(self, event) -> None:
        """Add dragged audio files to the playlist under the cursor.

        Always a **copy**: the drop action is downgraded so the source view
        (the Player's ``startDrag``, which removes rows on a MoveAction)
        keeps everything it dragged. Removing a track stays an explicit
        right-click action.
        """
        self._clear_track_drop_row()
        node_id = self._track_drop_target(event.position().toPoint())
        if node_id is None or self._library is None:
            event.ignore()
            return
        node = self._library.get_node(node_id)
        if node is None:
            event.ignore()
            return
        # Normalized, not raw: on Windows toLocalFile() hands back forward
        # slashes, and a path that disagrees with the one every other add
        # route stores is a second library row for the same file — with
        # duplicate detection blind to it. See src/utils/paths.py.
        paths = [
            normalize_track_path(url.toLocalFile())
            for url in event.mimeData().urls()
            if Path(url.toLocalFile()).suffix.lower() in AUDIO_EXTENSIONS
        ]
        if not paths:
            event.ignore()
            return
        # Downgrade to a copy BEFORE accepting: this is the whole "dragging
        # to another playlist doesn't remove it from this one" behaviour.
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        # Accept before the add, not after: a duplicate prompt defers the add
        # past the end of this handler, so there is no verdict to wait for.
        # Safe precisely because this is a copy — an add that resolves to
        # nothing simply leaves the source view untouched, as it would anyway.
        self._add_paths_to_node(node_id, paths)

    def _add_paths_to_node(self, node_id: int, paths: list[str]) -> bool:
        """Append tracks to a playlist, with undo. The one add chokepoint.

        Duplicates the playlist already holds are resolved first — added,
        skipped, or put to the user, per the ``duplicate_policy`` setting.
        That resolution can be **asynchronous** (the prompt cannot open inside
        a drop event), so a ``True`` return means "the add was started", not
        "the tracks are in". Anything that must run afterwards belongs in
        ``_commit_added_paths`` or on ``tracks_added``.

        Resolving before ``_track_id_for`` matters: a skipped file must not
        leave a new library row behind, and must not be tag-read at all.
        """
        library = self._library
        if library is None:
            return False
        node = library.get_node(node_id)
        if node is None:
            return False
        resolve_additions(
            self,
            paths,
            lambda: [t.path for t in library.get_items(node_id)],
            node.name,
            lambda resolved: self._commit_added_paths(node_id, resolved),
        )
        return True

    def _commit_added_paths(self, node_id: int, paths: list[str]) -> None:
        """Write a resolved add through to the database and refresh the view.

        A resolution of nothing (everything skipped, or the user cancelled) is
        a no-op down to the undo stack: pushing an entry for an add that added
        nothing would eat the Cmd+Z the user meant for the edit before it.
        """
        library = self._library
        if library is None or not paths or library.get_node(node_id) is None:
            return
        before = library.snapshot_items(node_id)
        track_ids = [self._track_id_for(path) for path in paths]
        library.add_items(node_id, track_ids)
        if self._undo is not None:
            self._undo.push(
                "Add Tracks", lambda: library.restore_items(node_id, before)
            )
        self._rebuild()
        self.tracks_added.emit(node_id)

    def _track_id_for(self, path: str) -> int:
        """The library row for a dropped file, reading its tags if it's new.

        A path the library already knows keeps its stored tags untouched —
        they may have been edited inline in the Player since, and re-reading
        the file would quietly roll that back.
        """
        library = self._library
        existing = library.get_track_by_path(path)
        if existing is not None:
            return existing.id
        try:
            meta = read_metadata(path)
        except Exception as exc:  # noqa: BLE001 — an unreadable tag is not fatal
            logger.warning("Could not read tags for %s: %s", path, exc)
            return library.add_track(path)
        return library.add_track(
            path,
            artist=meta.artist or "",
            title=meta.title or "",
            album=meta.album or "",
            genre=meta.genre or "",
            comment=meta.comment or "",
            bpm=meta.bpm,
            key=meta.key or "",
            year=str(meta.year) if meta.year else None,
            track_number=str(meta.track_number) if meta.track_number else None,
            label=meta.label or None,
            bitrate=meta.bitrate,
            energy=meta.energy,
            duration=meta.duration,
        )

    def _apply_move(self, node_id: int, parent_id: int | None, row: int) -> bool:
        """Write a drag-move through to the database and refresh the view.

        ``row`` is the insertion index counted with the node still in place
        (Qt's convention); adjust when moving down within the same parent.
        """
        node = self._library.get_node(node_id)
        if node is None:
            return False
        if node.parent_id == parent_id and node.position < row:
            row -= 1
        try:
            self._library.move_node(node_id, parent_id, row)
        except ValueError:
            return False  # cycle, playlist parent, or scratch — refuse the drop
        if self._undo is not None and (node.parent_id, node.position) != (
            parent_id,
            row,
        ):
            # move_node's position counts siblings with the node removed,
            # which is exactly how the old slot was recorded — so replaying
            # the old (parent, position) lands it back where it started.
            library, old_parent, old_pos = self._library, node.parent_id, node.position
            self._undo.push(
                "Move Playlist" if node.kind == "playlist" else "Move Folder",
                lambda: library.move_node(node_id, old_parent, old_pos),
            )
        self._rebuild()
        if parent_id is not None:
            parent_item = self._find_item(parent_id)
            if parent_item is not None:
                self.setExpanded(parent_item.index(), True)
        return True


class PlaylistTreePanel(QWidget):
    """Playlists-mode sidebar content: create buttons + the tree."""

    def __init__(self, db_path=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Transparent in the stylesheet: the global `QWidget` rule paints
        # BG_DARK, and the tree only covers the lower part of this panel — the
        # remainder would read as a dark strip banding the create buttons.
        self.setObjectName("playlistTreePanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        self._new_playlist_btn = QPushButton(self.tr("+ Playlist"))
        self._new_folder_btn = QPushButton(self.tr("+ Folder"))
        for btn in (self._new_playlist_btn, self._new_folder_btn):
            btn.setObjectName("treeCreateButton")
            buttons.addWidget(btn)

        # Name filter, expandable: the sidebar is too narrow to carry a box
        # and both create buttons at once, so the box takes the row over while
        # it is open and gives it back on Escape.
        self._search_btn = QPushButton()
        self._search_btn.setObjectName("treeSearchButton")
        self._search_btn.setIcon(_make_search_icon())
        self._search_btn.setCheckable(True)
        self._search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # Icon-only and borderless, so it takes the smallest sliver the row
        # can spare: the two create buttons carry translated text and a
        # QPushButton centres rather than elides, so anything this one takes
        # comes straight out of their labels.
        self._search_btn.setFixedWidth(_SEARCH_BTN_WIDTH)
        buttons.addWidget(self._search_btn)

        self._search_field = QLineEdit()
        self._search_field.setObjectName("treeSearchField")
        self._search_field.setClearButtonEnabled(True)
        self._search_field.setPlaceholderText(self.tr("Playlist name…"))
        self._search_field.hide()
        buttons.addWidget(self._search_field, 1)
        layout.addLayout(buttons)

        self.tree = PlaylistTree(db_path)
        layout.addWidget(self.tree, 1)

        # Debounced like the player's search, so a fast typist gets one filter
        # pass per pause rather than one per keystroke.
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(150)
        self._filter_timer.timeout.connect(self._apply_filter)

        self._new_playlist_btn.clicked.connect(lambda: self.tree.create_playlist(None))
        self._new_folder_btn.clicked.connect(lambda: self.tree.create_folder(None))
        self._search_btn.toggled.connect(self._set_search_open)
        self._search_field.textChanged.connect(self._on_filter_text_changed)
        # Widget-scoped, so Escape still means "cancel the edit" while a node
        # is being renamed in the tree.
        esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self._search_field)
        esc.setContext(Qt.ShortcutContext.WidgetShortcut)
        esc.activated.connect(lambda: self._search_btn.setChecked(False))
        self._sync_search_tooltip()

    # ------------------------------------------------------- name filter

    def _set_search_open(self, open_: bool) -> None:
        """Swap the create buttons for the filter box, or back.

        Closing always drops the filter: a box that is out of sight must not
        still be hiding half the user's playlists.
        """
        self._new_playlist_btn.setVisible(not open_)
        self._new_folder_btn.setVisible(not open_)
        self._search_field.setVisible(open_)
        self._sync_search_tooltip()
        if open_:
            self._search_field.setFocus()
        else:
            self._filter_timer.stop()
            self._search_field.clear()
            self.tree.clear_name_filter()

    def _sync_search_tooltip(self) -> None:
        self._search_btn.setToolTip(
            self.tr("Close the playlist filter")
            if self._search_btn.isChecked()
            else self.tr("Filter playlists by name")
        )

    def _on_filter_text_changed(self, text: str) -> None:
        if text.strip():
            self._filter_timer.start()
        else:
            # Emptying the box shows everything again at once — there is no
            # query to debounce, and waiting reads as lag.
            self._filter_timer.stop()
            self.tree.clear_name_filter()

    def _apply_filter(self) -> None:
        self.tree.set_name_filter(self._search_field.text())

    def ensure_loaded(self) -> None:
        self.tree.ensure_loaded()

    def set_library(self, library: Library) -> None:
        self.tree.set_library(library)

    def set_undo_stack(self, stack: UndoStack) -> None:
        self.tree.set_undo_stack(stack)
