"""Drag-and-drop enabled table widgets for accepting audio files."""

from pathlib import Path

from PySide6.QtCore import (
    QItemSelection,
    QItemSelectionModel,
    QMimeData,
    QRect,
    QSize,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QDrag,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QPainter,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QRubberBand,
    QTableView,
    QTableWidget,
    QWidget,
)

from ..styles.theme import Theme
from .drop_zone import AUDIO_EXTENSIONS

# MIME key marking a drag that originated from one of our panels (value = page id).
# Lets the sidebar nav buttons tell an internal panel-drag from an external OS drop
# and enforce the per-source routing allow-list.
SOURCE_PAGE_MIME = "application/x-mixedinp-source-page"


def start_file_drag(widget, page_id: str, paths: list[str]) -> Qt.DropAction:
    """Begin a drag carrying file URLs plus a marker identifying the source panel.

    Returns the resulting drop action so the caller can remove the dragged rows
    when the drop was accepted as a MoveAction (vs CopyAction = leave them in place).
    """
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
    mime.setData(SOURCE_PAGE_MIME, page_id.encode("utf-8"))
    drag = QDrag(widget)
    drag.setMimeData(mime)
    return drag.exec(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction)


class RubberBandSelectMixin:
    """Drag-a-box (rubber-band) selection for an item view that has drag-out
    enabled.

    ``setDragEnabled(True)`` makes a press on a row start a drag, so a box
    select can't begin on a row. We implement it ourselves: a left-press on
    EMPTY space drags a selection rectangle; a press on a row falls through to
    the normal drag/selection machinery untouched. Cooperative — every
    non-band path calls ``super()``, so it composes in front of a concrete
    ``QTableView``/``QTableWidget`` (and the player's reorderable table)."""

    _rb_origin = None  # viewport-space press point while box-selecting, else None
    _rubber_band = None  # lazily-created QRubberBand

    def _viewport_pos(self, event):
        """Cursor position in viewport coordinates.

        Mapping via the global position is robust: the raw event position is in
        the view's own coordinate space (offset by the header/frame), but
        ``indexAt``/``setSelection`` and the viewport-parented rubber band all
        expect viewport coordinates.
        """
        return self.viewport().mapFromGlobal(event.globalPosition().toPoint())

    def mousePressEvent(self, event) -> None:
        pos = self._viewport_pos(event)
        if (
            event.button() == Qt.MouseButton.LeftButton
            and not self.indexAt(pos).isValid()
            and self.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection
        ):
            self._rb_origin = pos
            if self._rubber_band is None:
                self._rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, self.viewport())
            self._rubber_band.setGeometry(QRect(pos, QSize()))
            self._rubber_band.show()
            if not (event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)):
                self.clearSelection()
            event.accept()
            return
        self._rb_origin = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._rb_origin is not None:
            rect = QRect(self._rb_origin, self._viewport_pos(event)).normalized()
            self._rubber_band.setGeometry(rect)
            self._select_rows_in_band(rect)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def _select_rows_in_band(self, rect: QRect) -> None:
        """Select every row whose vertical span intersects the band rectangle.

        We hit-test rows ourselves rather than calling ``setSelection(rect, …)``:
        the latter derives the range from ``indexAt`` on the rect's corners, and
        a box dragged from empty space has a corner on an invalid index, so it
        selects nothing — the exact case we need to support.
        """
        model = self.model()
        sel_model = self.selectionModel()
        if model is None or sel_model is None:
            return
        top, bottom = rect.top(), rect.bottom()
        last_col = model.columnCount() - 1
        selection = QItemSelection()
        for row in range(model.rowCount()):
            if self.isRowHidden(row):
                continue
            y0 = self.rowViewportPosition(row)
            y1 = y0 + self.rowHeight(row)
            if y1 > top and y0 < bottom:  # row span intersects the band
                selection.select(model.index(row, 0), model.index(row, last_col))
        sel_model.select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)

    def mouseReleaseEvent(self, event) -> None:
        if self._rb_origin is not None:
            if self._rubber_band is not None:
                self._rubber_band.hide()
            self._rb_origin = None
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _DroppableTableMixin(RubberBandSelectMixin):
    """Shared drag-drop logic for table views and table widgets."""

    files_dropped = Signal(list)

    _placeholder_text: str = "Drop audio files here"
    _drag_active: bool = False
    _placeholder_bottom_quarter: bool = False
    _drag_page_id: str | None = None
    _drag_data_fn = None  # () -> tuple[list[str], Callable[[], None] | None] | None

    def _init_drop(self, placeholder: str = "Drop audio files here", bottom_quarter: bool = False) -> None:
        self._placeholder_text = placeholder
        self._drag_active = False
        self._placeholder_bottom_quarter = bottom_quarter
        self.setAcceptDrops(True)
        # Rubber-band (box) selection state — see the mouse* overrides below.
        self._rb_origin = None
        self._rubber_band = None

    def enable_drag_out(self, page_id: str, drag_data_fn) -> None:
        """Allow this table to start drags carrying its selected files.

        `drag_data_fn` is called when a drag begins and must return
        `(paths, remove_callback)`: `paths` are the file paths to put in the drag
        (e.g. effective/converted output paths), and `remove_callback` (or None) is
        invoked only if the drop is accepted as a move, to remove the dragged rows
        from this panel. Return None / empty paths to cancel the drag.
        """
        self._drag_page_id = page_id
        self._drag_data_fn = drag_data_fn
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)

    def startDrag(self, supportedActions) -> None:
        if self._drag_data_fn is None:
            super().startDrag(supportedActions)
            return
        data = self._drag_data_fn()
        if not data:
            return
        paths, remove_cb = data
        if not paths:
            return
        result = start_file_drag(self, self._drag_page_id, paths)
        if result == Qt.DropAction.MoveAction and remove_cb is not None:
            remove_cb()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        # A self-drag (this table is the drag source) carries our file URLs now;
        # ignore it so it isn't mistaken for an external file add. These tables
        # have no internal reorder, so a self-drop is simply a no-op.
        if event.source() is self:
            event.ignore()
            return
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                path = Path(url.toLocalFile())
                if path.is_dir() or path.suffix.lower() in AUDIO_EXTENSIONS:
                    event.acceptProposedAction()
                    self._drag_active = True
                    self.viewport().update()
                    return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.source() is self:
            event.ignore()
            return
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._drag_active = False
        self.viewport().update()

    def dropEvent(self, event: QDropEvent) -> None:
        self._drag_active = False
        self.viewport().update()

        if event.source() is self:
            event.ignore()
            return
        if not event.mimeData().hasUrls():
            return

        audio_files: list[str] = []
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.name.startswith("."):
                continue  # skip macOS dot-files / hidden sidecars
            if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
                audio_files.append(str(path.resolve()))
            elif path.is_dir():
                audio_files.extend(self._find_audio_files(path))

        if audio_files:
            event.acceptProposedAction()
            self.files_dropped.emit(audio_files)

    def _find_audio_files(self, directory: Path) -> list[str]:
        audio_files: list[str] = []
        try:
            for path in directory.rglob("*"):
                if path.name.startswith("."):
                    continue  # skip macOS dot-files / hidden sidecars
                if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
                    audio_files.append(str(path.resolve()))
        except PermissionError:
            pass
        return sorted(audio_files)

    def _is_table_empty(self) -> bool:
        """Check if the table has no rows. Subclasses must implement."""
        raise NotImplementedError

    def _paint_placeholder(self, event) -> None:
        """Draw placeholder text and drag-over highlight on the viewport."""
        if self._is_table_empty() or self._drag_active:
            painter = QPainter(self.viewport())
            try:
                if self._drag_active:
                    # Draw border highlight
                    from PySide6.QtGui import QColor, QPen
                    pen = QPen(QColor(Theme.NEON_YELLOW), 2, Qt.PenStyle.DashLine)
                    painter.setPen(pen)
                    rect = self.viewport().rect().adjusted(1, 1, -1, -1)
                    painter.drawRect(rect)

                if self._is_table_empty():
                    from PySide6.QtGui import QColor
                    painter.setPen(QColor(Theme.TEXT_DISABLED))
                    font = QFont()
                    font.setPointSize(12)
                    painter.setFont(font)
                    if self._placeholder_bottom_quarter:
                        vp = self.viewport().rect()
                        draw_rect = vp.adjusted(0, vp.height() // 2, 0, 0)
                    else:
                        draw_rect = self.viewport().rect()
                    painter.drawText(
                        draw_rect,
                        Qt.AlignmentFlag.AlignCenter,
                        self._placeholder_text,
                    )
            finally:
                painter.end()


class DroppableTableView(_DroppableTableMixin, QTableView):
    """QTableView with drag-and-drop file support and empty placeholder."""

    files_dropped = Signal(list)

    def __init__(
        self,
        placeholder: str = "Drop audio files here",
        parent: QWidget | None = None,
        bottom_quarter: bool = False,
    ) -> None:
        QTableView.__init__(self, parent)
        self._init_drop(placeholder, bottom_quarter)

    def _is_table_empty(self) -> bool:
        model = self.model()
        return model is None or model.rowCount() == 0

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        self._paint_placeholder(event)


class DroppableTableWidget(_DroppableTableMixin, QTableWidget):
    """QTableWidget with drag-and-drop file support and empty placeholder."""

    files_dropped = Signal(list)

    def __init__(
        self,
        placeholder: str = "Drop audio files here",
        parent: QWidget | None = None,
        bottom_quarter: bool = False,
    ) -> None:
        QTableWidget.__init__(self, parent)
        self._init_drop(placeholder, bottom_quarter)

    def _is_table_empty(self) -> bool:
        return self.rowCount() == 0

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        self._paint_placeholder(event)
