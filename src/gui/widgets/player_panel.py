"""Audio player panel with playlist, transport controls, and seek/volume sliders."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import (
    QByteArray,
    QObject,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QDrag,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QFontMetrics,
    QIcon,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSlider,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionHeader,
    QStyleOptionSlider,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.metadata.tags import (
    TrackMetadata,
    delete_metadata_fields,
    read_metadata,
    write_comment,
    write_metadata,
)
from src.utils.config import load_config, save_config

from ..styles.theme import Theme
from ..workers.audio_decode_worker import AudioDecodeWorker
from ..workers.thread_keeper import keep_alive
from ..workers.waveform_worker import WaveformWorker, downsample_waveform
from .drop_zone import AUDIO_EXTENSIONS
from .droppable_table import SOURCE_PAGE_MIME, RubberBandSelectMixin, blank_drag_pixmap
from .player_engine import PlayerEngine
from .slice_section import SliceSection

logger = logging.getLogger(__name__)

# Whole decoded tracks held in RAM for instant play. Each entry can be ~100 MB
# (a few minutes of float32 stereo), so keep this small — enough for the current
# selection plus the next track or two.
_PCM_CACHE_MAX = 3
_PREFETCH_QUEUE_MAX = 4

# Transport glyph colour — grey, to read on the dark button without the old
# solid-yellow fill.
_TRANSPORT_GLYPH = "#c8c8c8"

# Side length of the album-art thumbnail shown in the header (opposite the
# "Player" title) while a track is loaded. Sized to sit within the title band.
_HEADER_ART_SIZE = 56


def _make_play_icon(color: str = _TRANSPORT_GLYPH, size: int = 14) -> QIcon:
    """A grey right-pointing triangle, drawn so it looks identical on every OS."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        m = size * 0.16
        p.drawPolygon(QPolygonF([
            QPointF(m, m),
            QPointF(m, size - m),
            QPointF(size - m, size / 2),
        ]))
    finally:
        p.end()
    return QIcon(pm)


def _make_pause_icon(color: str = _TRANSPORT_GLYPH, size: int = 14) -> QIcon:
    """Two grey vertical bars (the standard pause glyph)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        bar_w = size * 0.24
        gap = size * 0.18
        top, bottom = size * 0.16, size * 0.84
        x1 = size / 2 - gap / 2 - bar_w
        x2 = size / 2 + gap / 2
        p.drawRect(QRectF(x1, top, bar_w, bottom - top))
        p.drawRect(QRectF(x2, top, bar_w, bottom - top))
    finally:
        p.end()
    return QIcon(pm)


def _make_prev_icon(color: str = _TRANSPORT_GLYPH, size: int = 14) -> QIcon:
    """Skip-back glyph: a vertical bar with a left-pointing triangle (⏮)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        m = size * 0.16
        bar_w = size * 0.16
        p.drawRect(QRectF(m, m, bar_w, size - 2 * m))
        p.drawPolygon(QPolygonF([
            QPointF(size - m, m),
            QPointF(size - m, size - m),
            QPointF(m + bar_w, size / 2),
        ]))
    finally:
        p.end()
    return QIcon(pm)


def _make_next_icon(color: str = _TRANSPORT_GLYPH, size: int = 14) -> QIcon:
    """Skip-forward glyph: a right-pointing triangle with a vertical bar (⏭)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        m = size * 0.16
        bar_w = size * 0.16
        p.drawPolygon(QPolygonF([
            QPointF(m, m),
            QPointF(m, size - m),
            QPointF(size - m - bar_w, size / 2),
        ]))
        p.drawRect(QRectF(size - m - bar_w, m, bar_w, size - 2 * m))
    finally:
        p.end()
    return QIcon(pm)


def _make_stop_icon(color: str = _TRANSPORT_GLYPH, size: int = 14) -> QIcon:
    """Stop glyph: a centred square (⏹)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        m = size * 0.2
        p.drawRect(QRectF(m, m, size - 2 * m, size - 2 * m))
    finally:
        p.end()
    return QIcon(pm)


@dataclass
class PlaylistEntry:
    """A single track in the playlist."""

    file_path: str
    display_name: str
    artist: str = ""
    title: str = ""
    bpm: str = ""
    key: str = ""
    comment: str = ""
    duration: str = ""  # formatted "m:ss"
    year: str = ""


class SeparatorHeaderView(QHeaderView):
    """Playlist header that left-justifies its titles and draws a short, inset
    divider on each section's right edge.

    The label is painted by hand because macOS's QMacStyle centers header text
    and ignores ``setDefaultAlignment``; drawing it ourselves forces a left
    justify with a fixed 8px inset (matching the cells) so a title dragged
    narrower than its word stays readable from the start instead of clipping
    both ends. The divider is a subtle grab-hint between columns that stops
    short of the header's top and bottom so it floats rather than reading as a
    full border touching the rows above and below."""

    _SEP_COLOR = QColor(Theme.TEXT_DISABLED)
    _SEP_INSET = 6  # px trimmed off the top and bottom of each divider
    _TEXT_COLOR = QColor(Theme.CHROME)  # matches the global QHeaderView::section color
    _TEXT_PAD = 8  # px inset of the label from the section's left/right edges

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)

    def _title_font(self) -> QFont:
        """The bold font the section labels are painted in. Single source of
        truth so default column widths can be measured to fit the word."""
        font = QFont(self.font())
        font.setBold(True)
        return font

    def paintSection(self, painter: QPainter, rect, logicalIndex: int) -> None:
        # Draw the section chrome (background, bottom border, hover) via the
        # style with the text blanked, then render the label ourselves so its
        # alignment is honored on every platform.
        opt = QStyleOptionHeader()
        self.initStyleOptionForIndex(opt, logicalIndex)
        opt.rect = rect
        text = opt.text
        opt.text = ""
        painter.save()
        self.style().drawControl(QStyle.ControlElement.CE_Header, opt, painter, self)
        painter.restore()

        if text:
            painter.save()
            painter.setFont(self._title_font())
            painter.setPen(self._TEXT_COLOR)
            text_rect = rect.adjusted(self._TEXT_PAD, 0, -self._TEXT_PAD, 0)
            painter.drawText(
                text_rect,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                text,
            )
            painter.restore()

        # Draw the right-edge divider on every section, including the last one in
        # visual order: that column's right edge is still an interactive resize
        # handle (the header doesn't stretch the last section), so the divider is
        # a grab hint there too. Pull the last column's line 1px inward so it sits
        # just inside the viewport edge rather than under the table's frame border.
        painter.save()
        painter.setPen(QPen(self._SEP_COLOR, 1))
        is_last = self.visualIndex(logicalIndex) >= self.count() - 1
        x = rect.right() - 1 if is_last else rect.right()
        painter.drawLine(
            x, rect.top() + self._SEP_INSET, x, rect.bottom() - self._SEP_INSET
        )
        painter.restore()


class ReorderableTableWidget(RubberBandSelectMixin, QTableWidget):
    """QTableWidget with internal drag-drop row reordering and external file drops.

    The RubberBandSelectMixin adds drag-a-box selection from empty space (the
    same gesture as the Rename/Convert/Analyze tables); a press on a row still
    falls through to row reorder / drag-out untouched. Box-selecting many tracks
    is safe for memory because selection only ever prefetch-decodes the single
    current row (debounced, and suppressed during playback) — not every selected
    track."""

    order_changed = Signal()
    files_dropped = Signal(list)
    remove_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drag_active = False
        self._placeholder_text = self.tr("Drop audio files here")
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self._drag_page_id: str | None = None
        self._drag_data_fn = None
        # Predicate set by the panel: when it returns True (slice section open),
        # let S/Q/E bubble up to the panel instead of triggering type-ahead here.
        self._slice_keys_active = None

    # Keys the slice section claims while it is expanded.
    _SLICE_KEYS = frozenset({Qt.Key.Key_S, Qt.Key.Key_Q, Qt.Key.Key_E, Qt.Key.Key_L})

    def set_slice_keys_active(self, predicate) -> None:
        self._slice_keys_active = predicate

    def _slice_claims_key(self, event) -> bool:
        return (
            self._slice_keys_active is not None
            and self._slice_keys_active()
            and event.key() in self._SLICE_KEYS
            and not (event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier)
        )

    def keyPressEvent(self, event) -> None:
        # Backspace / Delete removes the selected track(s). Only fires while the
        # table has focus, so it never clashes with text editing elsewhere.
        if (
            event.key() in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete)
            and self.selectionModel().selectedRows()
        ):
            self.remove_requested.emit()
            event.accept()
            return
        if self._slice_claims_key(event):
            event.ignore()  # propagate to PlayerPanel.keyPressEvent
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if self._slice_claims_key(event):
            event.ignore()  # propagate to PlayerPanel.keyReleaseEvent
            return
        super().keyReleaseEvent(event)

    def enable_drag_out(self, page_id: str, drag_data_fn) -> None:
        """Allow dragging selected rows out as files (see DroppableTableMixin)."""
        self._drag_page_id = page_id
        self._drag_data_fn = drag_data_fn

    def startDrag(self, supportedActions) -> None:
        # Build ONE drag the in-list reorder machinery AND the sidebar both
        # understand: the model's internal-move data (so dropping back on this list
        # reorders, and the drop indicator shows) plus file URLs + a source marker
        # (so an allowed sidebar button can route the files). An internal reorder
        # drops on self as a CopyAction → no removal; a move drop on a sidebar
        # button returns MoveAction → remove the dragged rows from the playlist.
        data = self._drag_data_fn() if self._drag_data_fn is not None else None
        paths = data[0] if data else None
        remove_cb = data[1] if data else None
        if not paths:
            super().startDrag(supportedActions)
            return
        mime = self.model().mimeData(self.selectedIndexes())
        mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
        mime.setData(SOURCE_PAGE_MIME, self._drag_page_id.encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        # Hide Qt's default "file:///…" drag image; keep only the macOS file-count
        # badge the OS draws next to the cursor. See blank_drag_pixmap().
        drag.setPixmap(blank_drag_pixmap())
        result = drag.exec(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction)
        if result == Qt.DropAction.MoveAction and remove_cb is not None:
            remove_cb()

    def _has_audio_urls(self, mime_data) -> bool:
        """Check if mime data contains URLs with audio files or directories."""
        if not mime_data.hasUrls():
            return False
        for url in mime_data.urls():
            path = Path(url.toLocalFile())
            if path.is_dir() or path.suffix.lower() in AUDIO_EXTENSIONS:
                return True
        return False

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        # Self-drag = internal reorder. Check this first: our own outgoing drags
        # now carry file URLs, so we can't distinguish reorder by URL absence.
        if event.source() is self:
            super().dragEnterEvent(event)
        elif self._has_audio_urls(event.mimeData()):
            event.acceptProposedAction()
            self._drag_active = True
            self.viewport().update()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.source() is self:
            super().dragMoveEvent(event)
        elif self._has_audio_urls(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._drag_active = False
        self.viewport().update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        # Internal reorder first — handle ourselves because QTableWidget's default
        # internal-move deletes rows without reinserting them correctly. Must come
        # before the URL check: our own outgoing drags now carry file URLs, so a
        # self-drop would otherwise be mistaken for an external file add.
        if event.source() is self:
            self._drag_active = False
            self.viewport().update()
            self._handle_internal_reorder(event)
            return

        # External file drop (OS file explorer, etc.).
        if self._has_audio_urls(event.mimeData()):
            self._drag_active = False
            self.viewport().update()
            audio_files: list[str] = []
            for url in event.mimeData().urls():
                path = Path(url.toLocalFile())
                if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
                    audio_files.append(str(path.resolve()))
                elif path.is_dir():
                    audio_files.extend(self._find_audio_files(path))
            if audio_files:
                event.acceptProposedAction()
                self.files_dropped.emit(audio_files)
            return

        super().dropEvent(event)

    def _handle_internal_reorder(self, event: QDropEvent) -> None:
        pos = event.position().toPoint()
        drop_index = self.indexAt(pos)
        if drop_index.isValid():
            drop_row = drop_index.row()
            row_rect = self.visualRect(drop_index)
            if pos.y() > row_rect.center().y():
                drop_row += 1
        else:
            # Dropped below the last row in empty space — append.
            drop_row = self.rowCount()

        selected_rows = sorted({idx.row() for idx in self.selectionModel().selectedRows()})
        if not selected_rows:
            event.ignore()
            return

        # Detach items before removing rows so we can reinsert them at the target position.
        rows_data: list[list[QTableWidgetItem | None]] = []
        for r in selected_rows:
            rows_data.append([self.takeItem(r, c) for c in range(self.columnCount())])

        # Remove rows bottom-up to keep earlier indices valid; shift drop target for each
        # removal above it.
        adjusted_drop = drop_row
        for r in reversed(selected_rows):
            self.removeRow(r)
            if r < drop_row:
                adjusted_drop -= 1

        adjusted_drop = max(0, min(adjusted_drop, self.rowCount()))

        for i, row_items in enumerate(rows_data):
            self.insertRow(adjusted_drop + i)
            for c, item in enumerate(row_items):
                if item is not None:
                    self.setItem(adjusted_drop + i, c, item)

        self.clearSelection()
        if rows_data:
            self.selectRow(adjusted_drop)

        # We already moved rows ourselves — downgrade the action so Qt's default view does
        # NOT run its own post-drop source-row cleanup (which would delete the rows we
        # just reinserted).
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self.order_changed.emit()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.rowCount() == 0 or self._drag_active:
            painter = QPainter(self.viewport())
            try:
                if self._drag_active:
                    pen = QPen(QColor(Theme.NEON_YELLOW), 2, Qt.PenStyle.DashLine)
                    painter.setPen(pen)
                    rect = self.viewport().rect().adjusted(1, 1, -1, -1)
                    painter.drawRect(rect)
                if self.rowCount() == 0:
                    painter.setPen(QColor(Theme.TEXT_DISABLED))
                    font = QFont()
                    font.setPointSize(12)
                    painter.setFont(font)
                    painter.drawText(
                        self.viewport().rect(),
                        Qt.AlignmentFlag.AlignCenter,
                        self._placeholder_text,
                    )
            finally:
                painter.end()

    @staticmethod
    def _find_audio_files(directory: Path) -> list[str]:
        audio_files: list[str] = []
        try:
            for path in directory.rglob("*"):
                if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
                    audio_files.append(str(path.resolve()))
        except PermissionError:
            pass
        return sorted(audio_files)


class ScrubSlider(QSlider):
    """Horizontal slider that supports click-to-seek and defers seek until mouse release.

    Emits `scrub_committed` on mouse press (so click-to-seek is immediate) and again on
    mouse release (so drag-scrubbing only updates playback position when the user lets go).
    During a drag, `sliderMoved` still fires for visual handle tracking — audio consumers
    should listen to `scrub_committed`, not `sliderMoved`, to avoid audio glitching.
    """

    scrub_committed = Signal(int)

    def __init__(self, orientation: Qt.Orientation, parent: QWidget | None = None) -> None:
        super().__init__(orientation, parent)
        self._press_value: int | None = None

    def _value_at_pos(self, x: int) -> int:
        """Translate a pixel x-coordinate into a slider value."""
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderGroove, self
        )
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderHandle, self
        )
        slider_min = groove.x()
        slider_max = groove.right() - handle.width() + 1
        pos = x - handle.width() // 2
        return QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), pos - slider_min, slider_max - slider_min, opt.upsideDown
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.maximum() > self.minimum():
            value = self._value_at_pos(int(event.position().x()))
            self._press_value = value
            self.setValue(value)
            self.setSliderDown(True)
            self.sliderMoved.emit(value)
            self.scrub_committed.emit(value)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        was_down = self.isSliderDown()
        if event.button() == Qt.MouseButton.LeftButton:
            # We bypassed super().mousePressEvent to implement click-to-seek, so Qt never
            # registered the press — clear slider-down explicitly so isSliderDown() resets.
            self.setSliderDown(False)
        super().mouseReleaseEvent(event)
        if was_down and event.button() == Qt.MouseButton.LeftButton:
            # Only re-commit if the handle actually moved since press (a drag-scrub). For a
            # plain click the value is unchanged, so skipping this avoids a redundant
            # setPosition() — which on Windows' Media Foundation backend triggers a full
            # pipeline flush and is the source of click-to-seek latency.
            if self._press_value is None or self.value() != self._press_value:
                self.scrub_committed.emit(self.value())
            self._press_value = None


class CurrentRowDelegate(QStyledItemDelegate):
    """Item delegate for the `#` column that draws a yellow ring on the currently-playing row."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._current_row: int = -1

    def set_current_row(self, row: int) -> None:
        self._current_row = row

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        # Paint the cell background/selection via the base delegate, but suppress
        # its text and draw the number ourselves, centered in the full cell. The
        # base delegate insets text by the QSS item padding (8px), which on some
        # platforms clips a two-digit number in the narrow # column to nothing.
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        super().paint(painter, opt, index)
        if text:
            fg = index.data(Qt.ItemDataRole.ForegroundRole)
            if isinstance(fg, QBrush):
                color = fg.color()
            elif isinstance(fg, QColor):
                color = fg
            else:
                color = QColor(Theme.TEXT_PRIMARY)
            painter.save()
            painter.setPen(color)
            painter.setFont(opt.font)
            painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, text)
            painter.restore()

        if index.row() != self._current_row:
            return
        rect = option.rect
        diameter = min(rect.width(), rect.height()) - 6
        if diameter < 6:
            return
        painter.save()
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            cx = rect.center().x()
            cy = rect.center().y()
            circle = QRect(cx - diameter // 2, cy - diameter // 2, diameter, diameter)
            painter.setPen(QPen(QColor(Theme.NEON_YELLOW), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(circle)
        finally:
            painter.restore()


class NoElideDelegate(QStyledItemDelegate):
    """Default playlist delegate that never ellipsizes a value.

    macOS's QMacStyle ignores ``textElideMode`` for item views and always elides
    long text to '…' — neither ``view.setTextElideMode`` nor setting it on the
    style option takes effect there. So we draw the cell chrome via the style
    (text blanked) and paint the label ourselves, clipped to the cell with no
    elision, so a column dragged narrow shows its leading characters instead of
    an ellipsis. Text color follows the item's ForegroundRole (neon yellow for
    the playing row, primary text otherwise), mirroring CurrentRowDelegate.

    It also clears the focus rectangle, so it doubles as the window's
    NoFocusDelegate for this table (which must not be overridden — see
    MainWindow, which otherwise installs NoFocusDelegate on every table)."""

    _INSET = 5  # px from the column edge — matches the cells' intended inset
    _EDITOR_MIN_HEIGHT = 34  # px — taller than a row so the editor is comfortable to read

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        if editor is not None:
            editor.setMinimumHeight(self._EDITOR_MIN_HEIGHT)
        return editor

    def updateEditorGeometry(self, editor, option, index) -> None:
        # Default geometry is the (short) cell rect; grow it vertically and
        # centre it on the cell so the inline editor is easier to read.
        rect = QRect(option.rect)
        height = max(rect.height(), self._EDITOR_MIN_HEIGHT)
        rect.setTop(rect.top() - (height - rect.height()) // 2)
        rect.setHeight(height)
        editor.setGeometry(rect)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.state &= ~QStyle.StateFlag.State_HasFocus  # no native focus rectangle
        text = opt.text
        opt.text = ""  # draw background/selection/hover only; we render the text
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        if not text:
            return

        fg = index.data(Qt.ItemDataRole.ForegroundRole)
        if isinstance(fg, QBrush):
            color = fg.color()
        elif isinstance(fg, QColor):
            color = fg
        else:
            color = QColor(Theme.TEXT_PRIMARY)

        align = opt.displayAlignment
        if not int(align):
            align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        rect = opt.rect.adjusted(self._INSET, 0, -self._INSET, 0)
        painter.save()
        painter.setFont(opt.font)
        painter.setPen(color)
        painter.drawText(rect, int(align), text)
        painter.restore()


class PlayerPanel(QWidget):
    """Panel with playlist table, transport controls, seek bar, and volume slider."""

    files_dropped = Signal(list)
    open_in_metadata = Signal(str)
    # Re-emits the slicer's expand/collapse so the window sizer can widen the
    # window's minimum to fit the slicer controls while it is open.
    slice_expanded = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._playlist: list[PlaylistEntry] = []
        self._current_index: int = -1

        # In-memory PCM playback engine. Decoding the whole track to RAM makes
        # seeking instant (just an integer offset) — QMediaPlayer's setPosition
        # seek was sluggish on Windows. The engine is created eagerly; it only
        # opens the audio device on first play.
        self._engine = PlayerEngine(self)
        self._volume_pct: int = 70
        self._engine.set_volume(self._volume_pct / 100.0)

        # Background decode (single worker) feeding a small PCM prefetch cache.
        self._decode_thread: QThread | None = None
        self._decode_worker: AudioDecodeWorker | None = None
        self._decode_loading: bool = False
        self._decode_current_path: str | None = None
        # Strong refs to finished-but-not-yet-deleted threads/workers, kept alive
        # until their C++ objects are destroyed so a pending deleteLater can't
        # fire into a garbage-collected wrapper (SIGBUS). See thread_keeper.
        self._thread_keep: list = []
        # Speculative decode targets (selection / next track); pumped when idle.
        self._prefetch_queue: list[str] = []
        # Debounce for selection-driven prefetch: dragging through the playlist
        # fires itemSelectionChanged for every row it crosses. Coalesce that into
        # a single decode once the selection settles, so browsing doesn't spawn a
        # storm of decode workers that starve the audio callback of the GIL.
        self._prefetch_debounce = QTimer(self)
        self._prefetch_debounce.setSingleShot(True)
        self._prefetch_debounce.setInterval(350)
        self._prefetch_debounce.timeout.connect(self._on_prefetch_debounce)
        # path -> (pcm, sr), bounded LRU; lets a prefetched track start instantly.
        self._pcm_cache: dict[str, tuple] = {}
        # The track the user currently wants to hear — top decode priority, and
        # the key by which stale decode results are discarded.
        self._pending_play_path: str | None = None
        # Suppresses selection-driven prefetch while we rebuild the table.
        self._rebuilding: bool = False
        # Inline metadata editing is gated by the Edit Lock toggle; persisted.
        self._edit_locked: bool = load_config().player_edit_locked

        # One-shot waveform decode, used only when the slice section opens on a
        # track whose PCM was evicted from the cache (the common case builds the
        # waveform from cached PCM with no extra decode).
        self._wf_thread: QThread | None = None
        self._wf_worker: WaveformWorker | None = None
        self._wf_loading: bool = False
        self._wf_path: str | None = None

        self._setup_ui()
        self._connect_signals()
        self._update_transport_state()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Give the playlist keyboard focus when the panel becomes visible so the
        # Space play/pause shortcut is active without requiring a click first.
        self._table.setFocus(Qt.FocusReason.OtherFocusReason)
        # Warm the track they're most likely to hit Play on next.
        self._prefetch_default_target()

    # ── UI setup ────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        # The whole panel scrolls: when the slice section expands below the
        # playlist the content grows past the viewport and one vertical
        # scrollbar lets the user scroll down to the slicer. The playlist keeps
        # its own scrollbar and a fixed 12-row visible height while expanded
        # (see _apply_table_height); collapsed, everything fits and no outer
        # scrollbar appears. The faint background overlay stays on the panel
        # itself, so the transparent scroll area lets it show through.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self._scroll)

        # Player surface is the sidebar grey (BG_MEDIUM) down through the full
        # waveform; the slice detail/controls below sit on a near-black tray.
        # Labels/sliders are made transparent so the grey shows behind them.
        # Rules are id/type-scoped (not an unqualified `background:` which would
        # cascade onto buttons and strip the yellow #primaryButton fill).
        content = QWidget()
        content.setObjectName("playerContent")
        content.setStyleSheet(
            f"#playerContent {{ background-color: {Theme.BG_MEDIUM}; }}"
            "#playerContent QLabel { background-color: transparent; }"
            "#playerContent QSlider { background-color: transparent; }"
            "#seekRow { background-color: transparent; }"
            # Edit Lock: secondary-grey text + a circular indicator that fills
            # neon-yellow when locked (mirrors the Settings 'circleCheck' look).
            f"QCheckBox#editLockCheck {{ color: {Theme.TEXT_SECONDARY}; spacing: 6px;"
            " background-color: transparent; }"
            "QCheckBox#editLockCheck::indicator { width: 12px; height: 12px; }"
            f"QCheckBox#editLockCheck::indicator:checked {{ background-color: {Theme.NEON_YELLOW};"
            f" border: 2px solid {Theme.NEON_YELLOW}; border-radius: 6px; }}"
            f"QCheckBox#editLockCheck::indicator:unchecked {{ background-color: {Theme.BG_LIGHT};"
            f" border: 2px solid {Theme.CHROME_DARK}; border-radius: 6px; }}"
        )
        layout = QVBoxLayout(content)
        layout.setContentsMargins(Theme.PADDING, Theme.PADDING, Theme.PADDING, Theme.PADDING)
        layout.setSpacing(Theme.SPACING)

        # Title row: "Player" on the left, the loaded track's album art sitting
        # just after the title text (shown only while a track is loaded). The art
        # follows the end of the text with a little padding so the header stays
        # legible no matter how wide the translated title is; the trailing stretch
        # keeps both left-aligned.
        title_row = QHBoxLayout()
        title = QLabel(self.tr("Player"))
        title.setObjectName("sectionTitle")
        title.setStyleSheet(f"font-size: 24px; color: {Theme.NEON_YELLOW};")
        title_row.addWidget(title)
        title_row.addSpacing(12)

        self._art_label = QLabel()
        self._art_label.setFixedSize(_HEADER_ART_SIZE, _HEADER_ART_SIZE)
        self._art_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._art_label.hide()
        title_row.addWidget(self._art_label, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch()

        # Edit Lock: a text label with a trailing radial indicator ("Edit Lock ◯"),
        # sitting top-right opposite the "Player" title. Checked = locked = inline
        # playlist editing disabled. RightToLeft puts the circle after the text.
        self._edit_lock_cb = QCheckBox(self.tr("Edit Lock"))
        self._edit_lock_cb.setObjectName("editLockCheck")
        self._edit_lock_cb.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._edit_lock_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self._edit_lock_cb.setToolTip(self.tr("Lock metadata editing in the playlist"))
        self._edit_lock_cb.setChecked(self._edit_locked)
        self._edit_lock_cb.toggled.connect(self._on_edit_lock_toggled)
        title_row.addWidget(self._edit_lock_cb, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(title_row)

        # Playlist table
        self._table = ReorderableTableWidget()
        # Inset dividers between the column titles as a width-grab hint.
        self._table.setHorizontalHeader(SeparatorHeaderView(self._table))
        self._table.setColumnCount(9)
        self._table.setHorizontalHeaderLabels(
            [
                self.tr("#"),
                self.tr("Filename"),
                self.tr("Artist"),
                self.tr("Title"),
                self.tr("BPM"),
                self.tr("Key"),
                self.tr("Comment"),
                self.tr("Duration"),
                self.tr("Year"),
            ]
        )
        # Flat playlist surface in the sidebar's grey (no border / row stripes),
        # so the near-black slice tray below reads as the distinct work area.
        # Scoped to this table so other panels' tables keep the default styling.
        self._table.setAlternatingRowColors(False)
        # The cell text inset (5px) is owned by NoElideDelegate, which hand-draws
        # the label; CSS horizontal padding would not affect it. This rule only
        # keeps the 8px vertical padding that sets the row height.
        self._table.setStyleSheet(
            f"QTableWidget {{ background-color: {Theme.BG_MEDIUM}; border: none; }}"
            f"QHeaderView::section {{ background-color: {Theme.BG_MEDIUM}; }}"
            "QTableWidget::item { padding: 8px 0px; }"
            # The inline edit field otherwise inherits the global pill-shaped
            # QLineEdit (8px padding + rounded border), which clips the text in
            # a short row. Flatten it to a plain rectangle that fills the cell.
            "QTableWidget QLineEdit {"
            f" border: 1px solid {Theme.NEON_YELLOW}; border-radius: 0px;"
            f" background-color: #1e1e1e; color: {Theme.TEXT_PRIMARY};"
            " padding: 0px 4px; margin: 0px;"
            f" selection-background-color: {Theme.NEON_YELLOW}; selection-color: {Theme.BG_DARK}; }}"
        )
        self._table.verticalHeader().setVisible(False)
        # SelectedClicked gives Finder-style "slow double-click" editing (click an
        # already-selected cell to edit) without stealing the double-click-to-play
        # gesture. Gated by the Edit Lock toggle via _apply_edit_triggers().
        self._apply_edit_triggers()
        self._table.doubleClicked.connect(self._on_row_double_clicked)
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionsMovable(True)
        # Left-justify the column titles so a title dragged narrower than its
        # word stays readable from the start rather than clipping both ends.
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        for col in range(1, 9):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        self._table.setColumnWidth(0, 40)
        self._table.setColumnWidth(1, 300)  # Filename
        self._table.setColumnWidth(2, 180)  # Artist
        self._table.setColumnWidth(3, 180)  # Title
        self._table.setColumnWidth(6, 200)  # Comment
        # BPM, Key, Duration, Year default just wide enough to show the full
        # (bold) header word — measured from the header font so translated
        # labels fit too — rather than a fixed 70-80px that clips them. The
        # measured width is also kept as a floor (see _restore_column_state) so
        # these never reopen clipped, while staying Interactive for the user to
        # widen. ensurePolished() resolves the QSS font (set app-wide before
        # this panel is built) onto the header so the metrics match what's
        # painted; without it the font is unresolved here and widths come short.
        header.ensurePolished()
        header_fm = QFontMetrics(header._title_font())
        self._word_fit_widths: dict[int, int] = {}
        for col in (4, 5, 7, 8):
            label = self._table.horizontalHeaderItem(col).text()
            # 2× the header's text pad, plus a couple px so the word never
            # touches the right-edge divider.
            width = header_fm.horizontalAdvance(label) + 2 * SeparatorHeaderView._TEXT_PAD + 4
            self._word_fit_widths[col] = width
            self._table.setColumnWidth(col, width)

        # No '…' in any column — the no-elide delegate is the table default; the
        # '#' column then overrides it with its current-row delegate. NoElide also
        # suppresses the focus rect, so MainWindow must skip this table when it
        # installs its global NoFocusDelegate (or it would clobber this one).
        self._table.setItemDelegate(NoElideDelegate(self._table))
        self._row_number_delegate = CurrentRowDelegate(self._table)
        self._table.setItemDelegateForColumn(0, self._row_number_delegate)

        # Restore the user's saved column order/widths over the defaults above.
        self._restore_column_state()

        layout.addWidget(self._table, 1)

        # Transport controls
        transport_row = QHBoxLayout()
        transport_row.addStretch()

        # Transport controls are drawn glyphs (not text) so they read the same
        # in every language; the words live on as translated tooltips.
        self._prev_btn = QPushButton()
        self._prev_btn.setFixedWidth(48)
        self._prev_btn.setIcon(_make_prev_icon())
        self._prev_btn.setIconSize(QSize(14, 14))
        self._prev_btn.setToolTip(self.tr("Previous"))
        transport_row.addWidget(self._prev_btn)

        # Play/Pause uses a grey outline (default button style) with a drawn
        # play triangle / pause bars instead of text, toggled on state change.
        self._icon_play = _make_play_icon()
        self._icon_pause = _make_pause_icon()
        self._play_btn = QPushButton()
        self._play_btn.setFixedWidth(48)
        self._play_btn.setIcon(self._icon_play)
        self._play_btn.setIconSize(QSize(14, 14))
        self._play_btn.setToolTip(self.tr("Play / Pause  (Space)"))
        transport_row.addWidget(self._play_btn)

        self._stop_btn = QPushButton()
        self._stop_btn.setFixedWidth(48)
        self._stop_btn.setIcon(_make_stop_icon())
        self._stop_btn.setIconSize(QSize(14, 14))
        self._stop_btn.setToolTip(self.tr("Stop"))
        transport_row.addWidget(self._stop_btn)

        self._next_btn = QPushButton()
        self._next_btn.setFixedWidth(48)
        self._next_btn.setIcon(_make_next_icon())
        self._next_btn.setIconSize(QSize(14, 14))
        self._next_btn.setToolTip(self.tr("Next"))
        transport_row.addWidget(self._next_btn)

        # Transport buttons must not hold keyboard focus: otherwise a focused button
        # would consume the Space key (and could re-fire its own action) instead of
        # the play/pause shortcut. Standard for media transport controls.
        for btn in (self._prev_btn, self._play_btn, self._stop_btn, self._next_btn):
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        transport_row.addStretch()
        layout.addLayout(transport_row)

        # Seek bar — wrapped in a widget so it can be hidden when the slice
        # section's waveform takes over as the seek control.
        seek_row = QHBoxLayout()
        seek_row.setContentsMargins(0, 0, 0, 0)

        self._current_time_label = QLabel("0:00")
        self._current_time_label.setFixedWidth(45)
        self._current_time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._current_time_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        seek_row.addWidget(self._current_time_label)

        self._seek_slider = ScrubSlider(Qt.Orientation.Horizontal)
        self._seek_slider.setRange(0, 0)
        seek_row.addWidget(self._seek_slider)

        self._total_time_label = QLabel("0:00")
        self._total_time_label.setFixedWidth(45)
        self._total_time_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        seek_row.addWidget(self._total_time_label)

        self._seek_row_widget = QWidget()
        self._seek_row_widget.setObjectName("seekRow")
        self._seek_row_widget.setLayout(seek_row)
        layout.addWidget(self._seek_row_widget)

        # Volume row
        volume_row = QHBoxLayout()

        vol_label = QLabel(self.tr("Vol"))
        vol_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        vol_label.setMinimumWidth(25)
        volume_row.addWidget(vol_label)

        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setRange(0, 100)
        self._volume_slider.setValue(70)
        self._volume_slider.setFixedWidth(120)
        volume_row.addWidget(self._volume_slider)

        volume_row.addStretch()

        # Stats label
        self._stats_label = QLabel("")
        self._stats_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        volume_row.addWidget(self._stats_label)

        volume_row.addStretch()

        self._clear_btn = QPushButton(self.tr("Clear Playlist"))
        self._clear_btn.clicked.connect(self._on_clear_playlist)
        volume_row.addWidget(self._clear_btn)

        layout.addLayout(volume_row)

        # Collapsible slice section — shares the engine; builds its waveform
        # lazily on expand. Lets the user trim a slice from the loaded track.
        self._slice = SliceSection(self._engine, self)
        layout.addWidget(self._slice)
        # Route S/Q/E through the panel only while the section is open.
        self._table.set_slice_keys_active(self._slice.is_expanded)

        self._scroll.setWidget(content)

    # ── Signal wiring ───────────────────────────────────────────

    def _connect_signals(self) -> None:
        # Persist playlist column order/widths (debounced: one write per
        # interaction, not per pixel of a resize drag). Connected here — after
        # _setup_ui's restoreState — so restoring doesn't trigger a save.
        self._col_save_timer = QTimer(self)
        self._col_save_timer.setSingleShot(True)
        self._col_save_timer.setInterval(600)
        self._col_save_timer.timeout.connect(self._save_column_state)
        header = self._table.horizontalHeader()
        header.sectionMoved.connect(self._schedule_column_save)
        header.sectionResized.connect(self._schedule_column_save)

        # Playback engine
        self._engine.positionChanged.connect(self._on_position_changed)
        self._engine.durationChanged.connect(self._on_duration_changed)
        self._engine.stateChanged.connect(self._on_playback_state_changed)
        self._engine.finished.connect(self._on_track_finished)

        # Transport buttons
        self._prev_btn.clicked.connect(self._on_previous)
        self._play_btn.clicked.connect(self._on_play_pause)
        self._stop_btn.clicked.connect(self._on_stop)
        self._next_btn.clicked.connect(self._on_next)

        # Seek — scrub_committed fires on press + release so audio only jumps when the user
        # commits; sliderMoved just previews the time label during drag.
        self._seek_slider.scrub_committed.connect(self._on_seek)
        self._seek_slider.sliderMoved.connect(self._on_scrub_preview)

        # Volume
        self._volume_slider.valueChanged.connect(self._on_volume_changed)

        # Reorder
        self._table.order_changed.connect(self._sync_playlist_from_table)

        # External file drops
        self._table.files_dropped.connect(self.files_dropped.emit)

        # Backspace / Delete on a selected row removes it from the playlist.
        self._table.remove_requested.connect(self._on_remove_selected)

        # Drag selected tracks onto a sidebar nav button to route them. A move drop
        # removes them here (stopping playback if a dragged track was playing).
        self._table.enable_drag_out("player", self._drag_data)

        # Prefetch the track the user selects so pressing Play is instant.
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

        # Spacebar = play/pause, but only while focus is within this panel (so it
        # never collides with the Keyboard panel's keys or other pages).
        self._play_pause_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        self._play_pause_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._play_pause_shortcut.activated.connect(self._on_play_pause)

        # Slice section: swap the seek control on expand, supply the waveform
        # lazily, and forward its playhead seeks to the engine.
        self._slice.expanded_changed.connect(self._on_slice_expanded)
        self._slice.request_waveform.connect(self._build_waveform_for_current)
        self._slice.seek_requested.connect(self._on_seek)

    # ── Public API ──────────────────────────────────────────────

    def add_tracks(self, tracks: list[dict]) -> None:
        """Add tracks to the playlist.

        Each dict should have: file_path, display_name, and optionally artist, title,
        bpm, key, comment, year (str), duration (float seconds).
        """
        for t in tracks:
            artist = t.get("artist", "")
            title = t.get("title", "")
            comment = t.get("comment", "")
            year = t.get("year", "")
            duration_sec = t.get("duration")
            # Fall back to reading these from the file's tags when a caller didn't
            # supply them (e.g. tracks sent from the Analyze panel, which only
            # passes BPM/key), so the columns populate regardless of entry point.
            if (
                not artist
                or not title
                or not comment
                or not year
                or duration_sec is None
            ):
                try:
                    from src.metadata.tags import read_metadata

                    meta = read_metadata(t["file_path"])
                    artist = artist or (meta.artist or "")
                    title = title or (meta.title or "")
                    comment = comment or (meta.comment or "")
                    year = year or (str(meta.year) if meta.year else "")
                    if duration_sec is None:
                        duration_sec = meta.duration
                except Exception:
                    pass
            duration_str = (
                self._format_time(int(duration_sec * 1000))
                if isinstance(duration_sec, (int, float)) and duration_sec > 0
                else ""
            )
            entry = PlaylistEntry(
                file_path=t["file_path"],
                display_name=t["display_name"],
                artist=artist,
                title=title,
                bpm=t.get("bpm", ""),
                key=t.get("key", ""),
                comment=comment,
                duration=duration_str,
                year=year,
            )
            # Avoid duplicates by file path
            if any(e.file_path == entry.file_path for e in self._playlist):
                continue
            self._playlist.append(entry)

        self._rebuild_table()
        self._update_stats()
        # Re-enable Play/Stop now that the playlist is non-empty. Without this the
        # Play button stays disabled until a playback-state change (e.g. a double
        # click), which is why pressing Play after loading appeared to do nothing.
        self._update_transport_state()
        # Start decoding the first track in the background so the first Play is
        # instant instead of waiting on a full decode.
        self._prefetch_default_target()

    def stop_playback(self) -> None:
        """Stop playback (called on nav-away from the Player and on app close)."""
        self._engine.stop()

    def refresh(self) -> None:
        """Refresh UI state."""
        self._rebuild_table()
        self._update_stats()
        self._update_transport_state()

    # ── Table management ────────────────────────────────────────

    def _rebuild_table(self) -> None:
        self._rebuilding = True
        try:
            self._rebuild_table_rows()
        finally:
            self._rebuilding = False

    def _rebuild_table_rows(self) -> None:
        self._table.setRowCount(len(self._playlist))
        # Disable dropping ONTO items so Qt shows a between-row line indicator during
        # internal reorder instead of highlighting the hovered row.
        non_drop_flags = (
            Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsDragEnabled
        )
        # Tag columns (Artist/Title/BPM/Key/Comment/Year) are editable; the
        # ItemIsEditable flag is always present and the Edit Lock toggle gates
        # whether a click actually opens the editor (via setEditTriggers).
        editable_flags = non_drop_flags | Qt.ItemFlag.ItemIsEditable
        # The table is repopulated below; suppress itemChanged so building rows
        # doesn't look like user edits.
        self._table.blockSignals(True)
        try:
            for row, entry in enumerate(self._playlist):
                num_item = QTableWidgetItem(str(row + 1))
                num_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                num_item.setFlags(non_drop_flags)
                self._table.setItem(row, 0, num_item)

                name_item = QTableWidgetItem(entry.display_name)
                name_item.setFlags(non_drop_flags)
                self._table.setItem(row, 1, name_item)

                artist_item = QTableWidgetItem(entry.artist)
                artist_item.setFlags(editable_flags)
                self._table.setItem(row, 2, artist_item)

                title_item = QTableWidgetItem(entry.title)
                title_item.setFlags(editable_flags)
                self._table.setItem(row, 3, title_item)

                bpm_item = QTableWidgetItem(entry.bpm)
                bpm_item.setFlags(editable_flags)
                self._table.setItem(row, 4, bpm_item)

                key_item = QTableWidgetItem(entry.key)
                key_item.setFlags(editable_flags)
                self._table.setItem(row, 5, key_item)

                comment_item = QTableWidgetItem(entry.comment)
                comment_item.setFlags(editable_flags)
                self._table.setItem(row, 6, comment_item)

                duration_item = QTableWidgetItem(entry.duration)
                duration_item.setFlags(non_drop_flags)
                self._table.setItem(row, 7, duration_item)

                year_item = QTableWidgetItem(entry.year)
                year_item.setFlags(editable_flags)
                self._table.setItem(row, 8, year_item)
        finally:
            self._table.blockSignals(False)

        self._highlight_current_row()

    def _highlight_current_row(self) -> None:
        """Highlight the currently playing row in neon yellow with a bold name and # ring."""
        # setForeground/setFont mutate item roles, which also emit itemChanged —
        # block signals so the highlight isn't mistaken for a metadata edit.
        self._table.blockSignals(True)
        try:
            for row in range(self._table.rowCount()):
                is_current = row == self._current_index
                for col in range(self._table.columnCount()):
                    item = self._table.item(row, col)
                    if item is None:
                        continue
                    if is_current:
                        item.setForeground(QColor(Theme.NEON_YELLOW))
                    else:
                        item.setForeground(QColor(Theme.TEXT_PRIMARY))
                    if col == 1:
                        font = item.font()
                        font.setBold(is_current)
                        item.setFont(font)
        finally:
            self._table.blockSignals(False)

        self._row_number_delegate.set_current_row(self._current_index)
        self._table.viewport().update()

    # ── Inline metadata editing ─────────────────────────────────

    # Playlist column -> (PlaylistEntry attribute, tag field, kind).
    #   text  → writes a string verbatim; blank writes an empty value.
    #   bpm   → numeric; blank deletes the tag (no such thing as an empty number).
    #   year  → numeric; blank deletes the tag.
    #   comment → literal write via the shared write_comment helper.
    _EDITABLE_COLUMNS = {
        2: ("artist", "artist", "text"),
        3: ("title", "title", "text"),
        4: ("bpm", "bpm", "bpm"),
        5: ("key", "key", "text"),
        6: ("comment", "comment", "comment"),
        8: ("year", "year", "year"),
    }

    def _apply_edit_triggers(self) -> None:
        """Match the table's edit triggers to the Edit Lock state."""
        triggers = (
            QAbstractItemView.EditTrigger.NoEditTriggers
            if self._edit_locked
            else QAbstractItemView.EditTrigger.SelectedClicked
        )
        self._table.setEditTriggers(triggers)

    def _on_edit_lock_toggled(self, locked: bool) -> None:
        """Toggle inline editing and persist the choice."""
        self._edit_locked = locked
        self._apply_edit_triggers()
        # Re-load config first so we don't clobber a setting another panel changed.
        cfg = load_config()
        if cfg.player_edit_locked != locked:
            cfg.player_edit_locked = locked
            save_config(cfg)

    def _revert_cell(self, row: int, col: int, text: str) -> None:
        """Restore a cell's text without re-triggering itemChanged."""
        self._table.blockSignals(True)
        try:
            item = self._table.item(row, col)
            if item is not None:
                item.setText(text)
        finally:
            self._table.blockSignals(False)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        """Commit an inline metadata edit to the file's tags."""
        if self._rebuilding:
            return
        spec = self._EDITABLE_COLUMNS.get(item.column())
        if spec is None:
            return
        row = item.row()
        if not (0 <= row < len(self._playlist)):
            return
        attr, field, kind = spec
        entry = self._playlist[row]
        new_text = item.text().strip()
        old_text = getattr(entry, attr)
        if new_text == old_text:
            return

        path = entry.file_path
        try:
            if kind == "bpm":
                if new_text:
                    try:
                        bpm_val = float(new_text)
                    except ValueError:
                        self._revert_cell(row, item.column(), old_text)
                        return
                    write_metadata(path, TrackMetadata(bpm=bpm_val), fields=["bpm"])
                    new_text = str(int(round(bpm_val)))  # normalize for display
                else:
                    delete_metadata_fields(path, ["bpm"])
            elif kind == "year":
                if new_text:
                    try:
                        year_val = int(new_text)
                    except ValueError:
                        self._revert_cell(row, item.column(), old_text)
                        return
                    write_metadata(path, TrackMetadata(year=year_val), fields=["year"])
                    new_text = str(year_val)
                else:
                    delete_metadata_fields(path, ["year"])
            elif kind == "comment":
                write_comment(path, new_text)
            else:  # text: artist/title/key — blank writes an empty value
                write_metadata(path, TrackMetadata(**{field: new_text}), fields=[field])
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to write %s tag for %s: %s", field, path, exc)
            self._revert_cell(row, item.column(), old_text)
            return

        setattr(entry, attr, new_text)
        # Reflect any normalization (e.g. BPM "128.0" -> "128") back into the cell.
        if new_text != item.text():
            self._revert_cell(row, item.column(), new_text)

    def _reload_selected_metadata(self, fallback_row: int) -> None:
        """Re-read tags from disk for the selected rows (or the clicked row)."""
        selected = {idx.row() for idx in self._table.selectionModel().selectedRows()}
        if fallback_row not in selected:
            selected = {fallback_row}
        changed = False
        for row in sorted(selected):
            if not (0 <= row < len(self._playlist)):
                continue
            entry = self._playlist[row]
            try:
                meta = read_metadata(entry.file_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not reload metadata for %s: %s", entry.file_path, exc)
                continue
            entry.artist = meta.artist or ""
            entry.title = meta.title or ""
            entry.bpm = str(int(round(meta.bpm))) if meta.bpm else ""
            entry.key = meta.key or ""
            entry.comment = meta.comment or ""
            entry.year = str(meta.year) if meta.year else ""
            if meta.duration:
                entry.duration = self._format_time(int(meta.duration * 1000))
            changed = True
        if changed:
            self._rebuild_table()  # sets _rebuilding, so itemChanged stays quiet

    def _sync_playlist_from_table(self) -> None:
        """Rebuild the internal playlist list from table row order after drag-drop."""
        new_playlist: list[PlaylistEntry] = []
        old_current_path = (
            self._playlist[self._current_index].file_path
            if 0 <= self._current_index < len(self._playlist)
            else None
        )

        for row in range(self._table.rowCount()):
            name_item = self._table.item(row, 1)
            if name_item is None:
                continue
            name = name_item.text()
            for entry in self._playlist:
                if entry.display_name == name and entry not in new_playlist:
                    new_playlist.append(entry)
                    break

        self._playlist = new_playlist

        # Update current index to follow the playing track
        if old_current_path:
            for i, entry in enumerate(self._playlist):
                if entry.file_path == old_current_path:
                    self._current_index = i
                    break

        self._rebuild_table()

    def _update_stats(self) -> None:
        count = len(self._playlist)
        text = (
            self.tr("{0} track").format(count)
            if count == 1
            else self.tr("{0} tracks").format(count)
        )
        self._stats_label.setText(text)

    # ── Column layout persistence ───────────────────────────────

    def _restore_column_state(self) -> None:
        """Apply the saved playlist column order/widths, if any."""
        state = load_config().player_column_state
        if state:
            try:
                self._table.horizontalHeader().restoreState(
                    QByteArray.fromBase64(state.encode("ascii"))
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not restore player column layout: %s", exc)
        # Floor the word-fit columns so a previously-saved (or freshly dragged)
        # narrow width never reopens with the BPM/Key/Year/Duration header word
        # clipped. Wider saved widths are kept; the user can still widen freely.
        for col, min_width in self._word_fit_widths.items():
            if self._table.columnWidth(col) < min_width:
                self._table.setColumnWidth(col, min_width)

    def _schedule_column_save(self, *args) -> None:
        """Debounce saves so a drag-resize writes the config once, not per pixel."""
        self._col_save_timer.start()

    def _save_column_state(self) -> None:
        """Persist the current column order/widths. Re-loads config first so we
        don't clobber settings another panel changed since launch."""
        state = bytes(self._table.horizontalHeader().saveState().toBase64()).decode("ascii")
        cfg = load_config()
        if cfg.player_column_state == state:
            return
        cfg.player_column_state = state
        save_config(cfg)

    # ── Transport handlers ──────────────────────────────────────

    def _on_play_pause(self) -> None:
        if self._engine.is_playing():
            self._engine.pause()
        elif self._engine.is_paused():
            # Resume the loaded track from where it was paused.
            self._engine.play()
        else:
            # Stopped / nothing loaded – start from current selection or index 0.
            if self._current_index < 0:
                current = self._table.currentRow()
                if current >= 0:
                    self._current_index = current
                else:
                    rows = self._table.selectionModel().selectedRows()
                    if rows:
                        self._current_index = rows[0].row()
                    elif self._playlist:
                        self._current_index = 0
            if 0 <= self._current_index < len(self._playlist):
                self._play_track(self._current_index)

    def _on_stop(self) -> None:
        self._engine.stop()
        # Cancel any in-flight decode's deferred auto-play (user pressed Stop
        # before the track finished loading).
        self._pending_play_path = None
        self._seek_slider.setSliderDown(False)
        self._seek_slider.setValue(0)
        self._current_time_label.setText(self._format_time(0))

    def _on_previous(self) -> None:
        if self._current_index > 0:
            self._play_track(self._current_index - 1)
        elif self._playlist:
            self._play_track(0)

    def _on_next(self) -> None:
        if self._current_index < len(self._playlist) - 1:
            self._play_track(self._current_index + 1)

    def _on_row_double_clicked(self, index) -> None:
        self._play_track(index.row())

    def _play_track(self, index: int) -> None:
        if index < 0 or index >= len(self._playlist):
            return
        self._current_index = index
        entry = self._playlist[index]
        logger.info(f"Playing: {entry.display_name}")
        self._engine.stop()
        # Reset the seek UI *before* loading. A cache hit calls engine.load()
        # synchronously below, which emits durationChanged and sets the slider
        # range — so this reset must come first or it would clobber that range
        # back to (0, 0) and make the track unseekable.
        self._seek_slider.setSliderDown(False)
        self._seek_slider.setRange(0, 0)
        self._seek_slider.setValue(0)
        self._current_time_label.setText(self._format_time(0))
        self._total_time_label.setText(self._format_time(0))
        cached = self._cache_get(entry.file_path)
        if cached is not None:
            # Instant start — the PCM was prefetched into RAM already.
            self._pending_play_path = None
            pcm, sr = cached
            self._engine.load(pcm, sr)
            self._engine.play()
        else:
            # Decode in the background; the engine starts playing in _on_decoded
            # once the PCM is ready (durationChanged sets the slider range then).
            self._request_play_decode(entry.file_path)
        self._highlight_current_row()
        self._update_transport_state()
        self._show_current_artwork()
        # Warm the next track so auto-advance / Next is instant too.
        self._prefetch_next()

    # ── Header album art ────────────────────────────────────────

    def _show_current_artwork(self) -> None:
        """Show the current track's embedded album art in the header, or hide it."""
        path = self._current_path()
        data = None
        if path is not None:
            try:
                from src.metadata.tags import read_metadata

                data = read_metadata(path).artwork
            except Exception:
                data = None
        if not data:
            self._hide_artwork()
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            self._hide_artwork()
            return
        self._art_label.setPixmap(
            pixmap.scaled(
                _HEADER_ART_SIZE,
                _HEADER_ART_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self._art_label.show()

    def _hide_artwork(self) -> None:
        self._art_label.clear()
        self._art_label.hide()

    # ── Background decode + PCM prefetch cache ──────────────────

    def _request_play_decode(self, path: str) -> None:
        """Mark `path` as the play target and pump the decode pipeline."""
        self._pending_play_path = path
        self._pump_decode()

    def _prefetch(self, path: str) -> None:
        """Speculatively decode `path` into the cache so a later Play is instant.

        No-ops if it's already cached, currently decoding, queued, or the active
        play target. The play target always preempts prefetches for the next slot.
        """
        if not path or path in self._pcm_cache:
            return
        if path == self._decode_current_path or path == self._pending_play_path:
            return
        if path in self._prefetch_queue:
            return
        self._prefetch_queue.append(path)
        # Keep the queue bounded (newest requests win — they reflect where the
        # user's attention just moved).
        if len(self._prefetch_queue) > _PREFETCH_QUEUE_MAX:
            del self._prefetch_queue[:-_PREFETCH_QUEUE_MAX]
        self._pump_decode()

    def _pump_decode(self) -> None:
        """Start the next decode if the single worker is idle.

        Priority: the pending play target first (so pressing Play is never stuck
        behind speculative prefetches), then the prefetch queue. Only one decode
        runs at a time — decoding a whole track is CPU/IO heavy.
        """
        if self._decode_loading:
            return
        next_path: str | None = None
        if self._pending_play_path and self._pending_play_path not in self._pcm_cache:
            next_path = self._pending_play_path
        else:
            while self._prefetch_queue:
                cand = self._prefetch_queue.pop(0)
                if cand not in self._pcm_cache:
                    next_path = cand
                    break
        if next_path is None:
            return
        self._decode_loading = True
        self._decode_current_path = next_path
        thread = QThread()
        worker = AudioDecodeWorker(next_path)
        worker.moveToThread(thread)
        self._decode_thread = thread
        self._decode_worker = worker
        # Hold both wrappers alive until their C++ objects are actually destroyed
        # — reassigning the attributes above on the next decode is not enough, as
        # the prior deleteLater may still be queued (rapid track switches → SIGBUS).
        keep_alive(self._thread_keep, thread, worker)
        thread.started.connect(worker.run)
        worker.decoded.connect(self._on_decoded)
        worker.error.connect(self._on_decode_error)
        worker.decoded.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_decode_thread_finished)
        thread.start()

    @Slot(str, object, int)
    def _on_decoded(self, path: str, pcm, sr: int) -> None:
        # Cache every decode (even a now-stale one) so returning to it is instant.
        self._cache_put(path, pcm, sr)
        if path == self._pending_play_path:
            self._pending_play_path = None
            self._engine.load(pcm, sr)
            self._engine.play()

    @Slot(str, str)
    def _on_decode_error(self, path: str, msg: str) -> None:
        logger.warning(f"Could not load '{path}': {msg}")
        if path == self._pending_play_path:
            self._pending_play_path = None

    @Slot()
    def _on_decode_thread_finished(self) -> None:
        self._decode_loading = False
        self._decode_current_path = None
        self._pump_decode()

    # ── PCM cache (bounded LRU) + prefetch triggers ─────────────

    def _cache_get(self, path: str):
        entry = self._pcm_cache.pop(path, None)
        if entry is not None:
            self._pcm_cache[path] = entry  # touch: mark most-recently-used
        return entry

    def _cache_put(self, path: str, pcm, sr: int) -> None:
        self._pcm_cache.pop(path, None)
        self._pcm_cache[path] = (pcm, sr)
        while len(self._pcm_cache) > _PCM_CACHE_MAX:
            # Evict least-recently-used. The engine holds its own reference to the
            # playing track's buffer, so eviction never interrupts playback.
            self._pcm_cache.pop(next(iter(self._pcm_cache)))

    def _cache_discard(self, paths) -> None:
        for p in paths:
            self._pcm_cache.pop(p, None)

    def _prefetch_index(self, index: int) -> None:
        if 0 <= index < len(self._playlist):
            self._prefetch(self._playlist[index].file_path)

    def _prefetch_next(self) -> None:
        self._prefetch_index(self._current_index + 1)

    def _prefetch_default_target(self) -> None:
        """Warm the track most likely to be played next: the selection, else the first."""
        if self._engine.is_playing():
            return
        row = self._table.currentRow()
        if row < 0 and self._playlist:
            row = 0
        self._prefetch_index(row)

    def _on_selection_changed(self) -> None:
        if self._rebuilding or not self.isVisible():
            return
        # While a track is playing, do NOT speculatively decode whatever the user
        # browses to — decoding fights the audio callback for the GIL and is the
        # main cause of dropouts while clicking around mid-set. The next autoplay
        # track is already warmed by _prefetch_next(), and pressing Play decodes
        # the chosen track immediately (the play target preempts prefetches), so
        # nothing is lost but the contention. When stopped/paused, warm the
        # selection — but debounced, so dragging across rows fires one decode.
        if self._engine.is_playing():
            return
        self._prefetch_debounce.start()

    def _on_prefetch_debounce(self) -> None:
        """Prefetch the settled selection (debounced; only when not playing)."""
        if self._rebuilding or not self.isVisible() or self._engine.is_playing():
            return
        row = self._table.currentRow()
        if row >= 0:
            self._prefetch_index(row)

    def _update_transport_state(self) -> None:
        has_tracks = len(self._playlist) > 0
        self._play_btn.setEnabled(has_tracks)
        self._stop_btn.setEnabled(has_tracks)
        self._prev_btn.setEnabled(self._current_index > 0)
        self._next_btn.setEnabled(self._current_index < len(self._playlist) - 1)

    # ── Playback engine callbacks ───────────────────────────────

    @Slot(int)
    def _on_position_changed(self, position: int) -> None:
        if not self._seek_slider.isSliderDown():
            self._seek_slider.setValue(position)
            self._current_time_label.setText(self._format_time(position))
        # The section guards its own playhead while the user is scrubbing it.
        self._slice.set_position(position)

    @Slot(int)
    def _on_scrub_preview(self, value: int) -> None:
        """Update the current-time label to follow the handle while scrubbing."""
        self._current_time_label.setText(self._format_time(value))

    @Slot(int)
    def _on_duration_changed(self, duration: int) -> None:
        self._seek_slider.setRange(0, duration)
        self._total_time_label.setText(self._format_time(duration))
        # Point the slice section at the now-loaded track (sets marker range,
        # default filename/format; rebuilds the waveform if it's open).
        self._slice.set_track(self._current_path(), duration)

    def set_waveform_color(self, color: str) -> None:
        """Recolor the full-length waveform body (from Settings)."""
        self._slice.set_waveform_color(color)

    @Slot()
    def _on_track_finished(self) -> None:
        # Auto-advance to the next track, or stop at the end of the playlist.
        if self._current_index < len(self._playlist) - 1:
            self._play_track(self._current_index + 1)
        else:
            self._engine.stop()

    @Slot(bool)
    def _on_playback_state_changed(self, playing: bool) -> None:
        self._play_btn.setIcon(self._icon_pause if playing else self._icon_play)
        self._update_transport_state()
        # Zoom scrubbing is paused-only.
        self._slice.set_playing(playing)
        # Keep the header art up while loaded (playing or paused); drop it once
        # the track is fully stopped (incl. end-of-playlist via engine.stop()).
        if not playing and not self._engine.is_paused():
            self._hide_artwork()

    # ── Seek / Volume ───────────────────────────────────────────

    def _on_seek(self, position: int) -> None:
        self._engine.seek_ms(position)

    def _on_volume_changed(self, value: int) -> None:
        self._volume_pct = value
        self._engine.set_volume(value / 100.0)

    # ── Slice section ───────────────────────────────────────────

    def _current_path(self) -> str | None:
        if 0 <= self._current_index < len(self._playlist):
            return self._playlist[self._current_index].file_path
        return None

    # Number of playlist rows kept visible when the slice section is open.
    _ROWS_VISIBLE_WHEN_SLICING = 12

    def slice_time_row_min_width(self) -> int:
        """Min width the slicer's time-info + Mark-buttons row needs to fit."""
        return self._slice.time_row_min_width()

    def _on_slice_expanded(self, expanded: bool) -> None:
        """Swap the seek control and reflow for the expanded slicer.

        Open: the waveform is the seek control (hide the plain slider), the
        playlist is pinned to a fixed visible height so it can't be squished,
        and the panel grows past the viewport so the outer scrollbar reveals the
        slicer below. Closed: restore the stretchy playlist and plain slider.
        """
        self._seek_row_widget.setVisible(not expanded)
        self._apply_table_height(expanded)
        if not expanded:
            # Return to the top so the user isn't left scrolled past the slicer.
            self._scroll.verticalScrollBar().setValue(0)
        self.slice_expanded.emit(expanded)

    def _apply_table_height(self, fixed: bool) -> None:
        """Pin the playlist to N visible rows while slicing, else let it stretch."""
        if fixed:
            header_h = self._table.horizontalHeader().height()
            row_h = (
                self._table.rowHeight(0)
                if self._table.rowCount() > 0
                else self._table.verticalHeader().defaultSectionSize()
            )
            if row_h <= 0:
                row_h = 28
            h = header_h + self._ROWS_VISIBLE_WHEN_SLICING * row_h + 2 * self._table.frameWidth() + 4
            self._table.setMinimumHeight(h)
            self._table.setMaximumHeight(h)
        else:
            self._table.setMinimumHeight(0)
            self._table.setMaximumHeight(16_777_215)  # QWIDGETSIZE_MAX — stretch freely

    def _build_waveform_for_current(self) -> None:
        """Supply the slice section a waveform for the current track.

        Built from the PCM already in the cache so there's no second decode;
        falls back to a one-shot decode only if the buffer was evicted.
        """
        path = self._current_path()
        if path is None:
            return
        cached = self._cache_get(path)
        if cached is not None:
            pcm, sr = cached
            try:
                cmin, cmax, _dur, dmin, dmax, bps = downsample_waveform(pcm, sr)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Waveform build failed for {path}: {e}")
                return
            self._slice.set_waveform(cmin, cmax, dmin, dmax, bps)
            return
        # Cache miss — decode just for the waveform off the UI thread.
        self._start_waveform_fallback(path)

    def _start_waveform_fallback(self, path: str) -> None:
        if self._wf_loading:
            return
        self._wf_loading = True
        self._wf_path = path
        thread = QThread()
        worker = WaveformWorker(path)
        worker.moveToThread(thread)
        self._wf_thread = thread
        self._wf_worker = worker
        # Keep the wrappers alive until C++ destroys them (see _pump_decode).
        keep_alive(self._thread_keep, thread, worker)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_waveform_fallback_ready)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_waveform_fallback_finished)
        thread.start()

    @Slot(object, object, int, object, object, float)
    def _on_waveform_fallback_ready(self, cmin, cmax, _dur, dmin, dmax, bps) -> None:
        # Only render if the section is still open on the same track.
        if self._wf_path == self._current_path() and self._slice.is_expanded():
            self._slice.set_waveform(cmin, cmax, dmin, dmax, bps)

    @Slot()
    def _on_waveform_fallback_finished(self) -> None:
        self._wf_loading = False
        self._wf_path = None

    # ── Slice keyboard shortcuts (active only while the section is open) ──

    def keyPressEvent(self, event) -> None:
        if self._slice.is_expanded() and not isinstance(QApplication.focusWidget(), QLineEdit):
            key = event.key()
            if key == Qt.Key.Key_Q and not event.isAutoRepeat():
                self._slice.on_mark_start()
                event.accept()
                return
            if key == Qt.Key.Key_E and not event.isAutoRepeat():
                self._slice.on_mark_end()
                event.accept()
                return
            if key == Qt.Key.Key_S and not event.isAutoRepeat():
                self._slice.on_preview_start()
                event.accept()
                return
            if key == Qt.Key.Key_L and not event.isAutoRepeat():
                self._slice.toggle_loop()
                event.accept()
                return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if (
            self._slice.is_expanded()
            and not isinstance(QApplication.focusWidget(), QLineEdit)
            and event.key() == Qt.Key.Key_S
            and not event.isAutoRepeat()
        ):
            self._slice.on_preview_end()
            event.accept()
            return
        super().keyReleaseEvent(event)

    # ── Drag-out ────────────────────────────────────────────────

    def _drag_data(self):
        """Provide (paths, remove-on-move callback) for an outgoing drag.

        On a move drop, `_on_remove_selected` removes the dragged rows and stops
        playback if one was the playing track. A copy drop (e.g. onto Metadata)
        returns CopyAction, so nothing is removed and playback is untouched.
        """
        rows = sorted({idx.row() for idx in self._table.selectionModel().selectedRows()})
        paths = [self._playlist[r].file_path for r in rows if 0 <= r < len(self._playlist)]
        if not paths:
            return None
        return paths, self._on_remove_selected

    # ── Remove / Clear ──────────────────────────────────────────

    def _on_remove_selected(self) -> None:
        rows = sorted({idx.row() for idx in self._table.selectionModel().selectedRows()}, reverse=True)
        if not rows:
            return

        playing_path = (
            self._playlist[self._current_index].file_path
            if 0 <= self._current_index < len(self._playlist)
            else None
        )

        for row in rows:
            if 0 <= row < len(self._playlist):
                removed = self._playlist.pop(row)
                self._cache_discard([removed.file_path])
                if playing_path and removed.file_path == playing_path:
                    # Unload to release the audio device and free the buffer
                    # — required for ejecting USB drives the file lived on.
                    self._engine.unload()
                    self._slice.set_track(None, 0)
                    self._pending_play_path = None
                    playing_path = None
                    self._current_index = -1
                    self._hide_artwork()

        # Recalculate current index
        if playing_path:
            self._current_index = next(
                (i for i, e in enumerate(self._playlist) if e.file_path == playing_path),
                -1,
            )

        self._rebuild_table()
        self._update_stats()
        self._update_transport_state()

    def _on_clear_playlist(self) -> None:
        # Unload to release the audio device and free the decoded buffer.
        self._engine.unload()
        self._slice.set_track(None, 0)
        self._pending_play_path = None
        self._prefetch_queue.clear()
        self._pcm_cache.clear()
        self._playlist.clear()
        self._current_index = -1
        self._hide_artwork()
        self._rebuild_table()
        self._update_stats()
        self._update_transport_state()

    # ── Context menu ────────────────────────────────────────────

    def _on_context_menu(self, pos: QPoint) -> None:
        """Show a right-click menu on the playlist row under the cursor."""
        index = self._table.indexAt(pos)
        if not index.isValid():
            return
        row = index.row()
        if not (0 <= row < len(self._playlist)):
            return
        entry = self._playlist[row]

        menu = QMenu(self._table)
        open_folder_action = menu.addAction(self.tr("Open File Location"))
        open_metadata_action = menu.addAction(self.tr("Open in Metadata Panel"))
        reload_action = menu.addAction(self.tr("Reload Metadata from File"))
        menu.addSeparator()
        remove_action = menu.addAction(self.tr("Remove from Playlist"))

        chosen = menu.exec(self._table.viewport().mapToGlobal(pos))
        if chosen is open_folder_action:
            self._reveal_in_explorer(entry.file_path)
        elif chosen is open_metadata_action:
            self.open_in_metadata.emit(entry.file_path)
        elif chosen is reload_action:
            self._reload_selected_metadata(row)
        elif chosen is remove_action:
            # Remove the current selection; if the right-clicked row isn't part
            # of it, act on just that row instead.
            selected = {idx.row() for idx in self._table.selectionModel().selectedRows()}
            if row not in selected:
                self._table.selectRow(row)
            self._on_remove_selected()

    @staticmethod
    def _reveal_in_explorer(file_path: str) -> None:
        """Open the OS file manager to the folder containing the given file."""
        import os
        import sys

        path = Path(file_path)
        folder = path.parent if path.parent.exists() else path
        if sys.platform == "win32":
            os.startfile(str(folder))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # ── Helpers ─────────────────────────────────────────────────

    @staticmethod
    def _format_time(ms: int) -> str:
        """Format milliseconds as m:ss."""
        total_seconds = max(0, ms // 1000)
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes}:{seconds:02d}"
