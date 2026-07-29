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

from PySide6.QtCore import QMimeData, QPointF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDrag,
    QFont,
    QIcon,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QPolygonF,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyledItemDelegate,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from src.library import SCRATCH_NODE_ID, Library
from ..styles.theme import Theme
from .droppable_table import SOURCE_PAGE_MIME, blank_drag_pixmap

NODE_ID_ROLE = Qt.ItemDataRole.UserRole + 1
KIND_ROLE = Qt.ItemDataRole.UserRole + 2
#: §10 highlight trail — paint-only roles, read by the delegate at draw time.
#: HL_PLAYLIST (bool): this playlist contains the searched track(s).
#: HL_COUNT (int): folder — how many lit playlists sit beneath it.
HL_PLAYLIST_ROLE = Qt.ItemDataRole.UserRole + 3
HL_COUNT_ROLE = Qt.ItemDataRole.UserRole + 4

#: Internal drag payload: the dragged node's id, as ASCII digits.
NODE_MIME = "application/x-mixedinp-node"

#: Background wash behind a highlighted playlist row — a dim neon-yellow so
#: "arrived" reads solid without drowning the selection highlight.
_HL_WASH = "#3a3410"

_ICON_DRAW = 40  # painted at 2x, displayed at 20 for HiDPI crispness


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


class _TreeItemDelegate(QStyledItemDelegate):
    """Rename-editor geometry plus the §10 highlight trail's two looks.

    Highlight painting: the two states must never look the same, or the
    user can't tell "arrived" from "keep digging". A playlist holding the
    searched track(s) is arrived — bold, neon text on a yellow wash. A
    folder with lit playlists beneath is keep-going — neon text and a
    trailing count ("Crates · 2"), no wash. Both are paint-only, driven by
    data roles the view sets; order, expansion, and selection are never
    touched here.

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
            option.backgroundBrush = QBrush(QColor(_HL_WASH))
        else:
            count = index.data(HL_COUNT_ROLE)
            if not count:
                return
            option.text = f"{option.text} · {count}"
        for role in (QPalette.ColorRole.Text, QPalette.ColorRole.HighlightedText):
            option.palette.setColor(role, QColor(Theme.NEON_YELLOW))

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

    #: Emitted when the user clicks a playlist (or Scratch); the Player
    #: integration step loads the clicked list.
    playlist_activated = Signal(int)

    def __init__(self, db_path=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._db_path = db_path
        self._library: Library | None = None
        self._loaded = False
        self._building = False
        # §10 highlight trail state, kept so it survives DB-driven rebuilds
        # (and a set_highlight arriving before the first load).
        self._hl_playlists: set[int] = set()
        self._hl_folders: dict[int, int] = {}

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

        self.setItemDelegate(_TreeItemDelegate(self))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self._model.itemChanged.connect(self._on_item_changed)
        self.clicked.connect(self._on_clicked)
        # Column width tracks content so the horizontal scrollbar stays honest.
        self.expanded.connect(lambda _i: self.resizeColumnToContents(0))
        self.collapsed.connect(lambda _i: self.resizeColumnToContents(0))

    # ----------------------------------------------------------------- loading

    def set_library(self, library: Library) -> None:
        """Use a shared library instance (the main window's) instead of
        opening our own connection."""
        self._library = library

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

    @property
    def library(self) -> Library | None:
        return self._library

    def _rebuild(self) -> None:
        """Repopulate from the database, preserving expansion + selection."""
        expanded = self._expanded_ids()
        selected = self._current_id()
        self._building = True
        try:
            self._model.clear()
            root = self._model.invisibleRootItem()
            root.appendRow(self._make_item(SCRATCH_NODE_ID, "scratch", self.tr("Scratch")))
            self._append_children(root, None)
        finally:
            self._building = False
        for node_id in expanded:
            item = self._find_item(node_id)
            if item is not None:
                self.setExpanded(item.index(), True)
        if selected is not None:
            item = self._find_item(selected)
            if item is not None:
                self.setCurrentIndex(item.index())
        if self._hl_playlists or self._hl_folders:
            self._apply_highlight()
        self.resizeColumnToContents(0)

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
        parent = parent or self._model.invisibleRootItem()
        ids: set[int] = set()
        for row in range(parent.rowCount()):
            child = parent.child(row)
            if self.isExpanded(child.index()):
                ids.add(child.data(NODE_ID_ROLE))
            ids |= self._expanded_ids(child)
        return ids

    def _current_id(self) -> int | None:
        index = self.currentIndex()
        return index.data(NODE_ID_ROLE) if index.isValid() else None

    # -------------------------------------------------------------------- CRUD

    def create_playlist(self, parent_id: int | None = None) -> None:
        self._create_node("playlist", parent_id)

    def create_folder(self, parent_id: int | None = None) -> None:
        self._create_node("folder", parent_id)

    def _create_node(self, kind: str, parent_id: int | None) -> None:
        self.ensure_loaded()
        name = self.tr("New Playlist") if kind == "playlist" else self.tr("New Folder")
        if kind == "playlist":
            node_id = self._library.create_playlist(name, parent_id)
        else:
            node_id = self._library.create_folder(name, parent_id)
        self._rebuild()
        item = self._find_item(node_id)
        if item is not None:
            if parent_id is not None:
                parent_item = self._find_item(parent_id)
                if parent_item is not None:
                    self.setExpanded(parent_item.index(), True)
            self.setCurrentIndex(item.index())
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
        self._library.delete_node(node_id)
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
        elif kind == "playlist":
            menu.addAction(self.tr("Rename"), lambda: self.edit(index))
            menu.addAction(self.tr("Delete…"), lambda: self._delete_node(node_id))
        else:  # background or Scratch: create at the root
            menu.addAction(self.tr("New Playlist"), lambda: self.create_playlist(None))
            menu.addAction(self.tr("New Folder"), lambda: self.create_folder(None))
        menu.exec(self.viewport().mapToGlobal(pos))

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

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.mimeData().hasFormat(NODE_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # Let the base class run so the drop indicator tracks the cursor,
        # then force our own verdict (the default model would reject NODE_MIME).
        super().dragMoveEvent(event)
        if event.mimeData().hasFormat(NODE_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt override)
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
        layout.addLayout(buttons)

        self.tree = PlaylistTree(db_path)
        layout.addWidget(self.tree, 1)

        self._new_playlist_btn.clicked.connect(lambda: self.tree.create_playlist(None))
        self._new_folder_btn.clicked.connect(lambda: self.tree.create_folder(None))

    def ensure_loaded(self) -> None:
        self.tree.ensure_loaded()

    def set_library(self, library: Library) -> None:
        self.tree.set_library(library)
