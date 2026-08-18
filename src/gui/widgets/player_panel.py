"""Audio player panel with playlist, transport controls, and seek/volume sliders."""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

import shiboken6
from PySide6.QtCore import (
    QT_TRANSLATE_NOOP,
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
    QAction,
    QActionGroup,
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
    QImage,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPainterPath,
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
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
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

from src.library import SCRATCH_NODE_ID, Library
from src.metadata.tags import (
    TrackMetadata,
    delete_metadata_fields,
    read_metadata,
    write_comment,
    write_metadata,
)
from src.utils.config import load_config, save_config

from ..models.undo_stack import UndoStack
from ..styles.theme import Theme
from ..workers.audio_decode_worker import AudioDecodeWorker
from ..workers.artwork_worker import ArtworkThread, ArtworkWorker
from ..workers.thread_keeper import keep_alive, wait_for_threads
from ..workers.waveform_worker import WaveformWorker, downsample_waveform, timed_envelope
from .vis_canvas import FFT_SIZE, FRAME_MS, POPOUT_MODES, VisRenderer, VisualizerWindow

# Backdrop visualizer modes → the VisRenderer mode that draws them.
_BACKDROP_VIS_MAP = {
    "backdrop_scope": "oscilloscope",
    "backdrop_spectrum": "spectrum",
    "backdrop_fire": "fire",
    "backdrop_fractal": "fractal",
}
from .dialogs.duplicate_policy import ADD as DUPLICATES_ADD
from .dialogs.duplicate_policy import SKIP as DUPLICATES_SKIP
from .dialogs.duplicate_policy import resolve_additions
from .dialogs.relocate_dialog import RelocateDialog
from .drop_zone import AUDIO_EXTENSIONS
from .droppable_table import (
    SOURCE_PAGE_MIME,
    RubberBandSelectMixin,
    blank_drag_pixmap,
    start_file_drag,
)
from .compatible_panel import CompatibleTracksPanel
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

# Opening width of the Compatible Tracks panel, and the share of the playlist
# area it may never exceed — past about half, the panel has taken over the
# thing it is meant to sit beside.
_COMPAT_DEFAULT_WIDTH = 340
_COMPAT_MAX_SHARE = 0.5

# Span of the playlist backdrop's scrolling zoom window (playhead centered, so
# half of this is upcoming audio). Wide enough to read musical phrasing, slow
# enough not to strobe behind the row text.
_BACKDROP_WINDOW_MS = 12_000

# Opacity for visualizer-frame backdrops (scope/spectrum/fire/fractal behind
# the playlist) — dim enough that the row text stays readable.
_BACKDROP_VIS_OPACITY = 0.40

# After pause/stop, keep feeding a visualizer backdrop silence for this many
# frames so bars fall and fire burns down, then stop its timer.
_VIS_DECAY_FRAMES = 60

# Most search matches shown at once. Past the cap the stats label reads
# "2000+ results", so the count never lies about how many tracks matched.
#
# 2000 rather than the original 500 because a real library outgrew it: a
# common word matched more tracks than the search would show. Measured before
# raising it, at the cap, against a 20,000-track library in All-playlists
# scope — the expensive path, which also fetches membership counts and builds
# a tooltip per row: 70-85 ms end to end. The queries are not the cost (search
# 5 ms, get_tracks 6 ms, counts 2 ms, and all 2000 playlists_containing calls
# together 16 ms); the rest is the table rebuild. So the tooltips stay eager —
# there is nothing here to optimise. See the batch plan §4.
_SEARCH_LIMIT = 2000


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


def _make_compat_icon(color: str = _TRANSPORT_GLYPH, size: int = 18) -> QIcon:
    """Two interlocking rings — the harmonic-mixing glyph for the panel toggle.

    Drawn rather than lettered for the same reason as the transport glyphs:
    it reads identically in every language, and follows the grey glyph colour.
    """
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(color), max(1.0, size * 0.09))
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        r = size * 0.28
        mid = size / 2.0
        # Overlapping by a third of a radius: enough to read as linked at
        # 18px without the two rings merging into one blob.
        offset = r * 0.62
        p.drawEllipse(QPointF(mid - offset, mid), r, r)
        p.drawEllipse(QPointF(mid + offset, mid), r, r)
    finally:
        p.end()
    return QIcon(pm)


def _make_eye_icon(color: str = _TRANSPORT_GLYPH, size: int = 18) -> QIcon:
    """Eye glyph (👁 outline + iris) for the visuals menu button.

    Drawn (not text/emoji) like the transport glyphs, so it reads the same in
    every language and follows the grey glyph colour instead of emoji fonts.
    """
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        c = QColor(color)
        mid = size / 2.0
        m = size * 0.08
        bow = size * 0.62  # how far the lid curves from the midline
        # Almond outline: two mirrored quadratic lids meeting at the corners.
        path = QPainterPath(QPointF(m, mid))
        path.quadTo(QPointF(mid, mid - bow), QPointF(size - m, mid))
        path.quadTo(QPointF(mid, mid + bow), QPointF(m, mid))
        pen = QPen(c, max(1.0, size * 0.09))
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        # Iris.
        r = size * 0.16
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawEllipse(QPointF(mid, mid), r, r)
    finally:
        p.end()
    return QIcon(pm)


def _make_scope_this_icon(color: str = _TRANSPORT_GLYPH, size: int = 18) -> QIcon:
    """A single box — the 'This playlist' search scope."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(QColor(color), max(1.0, size * 0.09)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        m = size * 0.22
        p.drawRoundedRect(QRectF(m, m, size - 2 * m, size - 2 * m), 2, 2)
    finally:
        p.end()
    return QIcon(pm)


def _make_scope_all_icon(color: str = _TRANSPORT_GLYPH, size: int = 18) -> QIcon:
    """Stacked boxes — the 'All playlists' search scope."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(color), max(1.0, size * 0.09))
        m = size * 0.14
        off = size * 0.18  # diagonal offset between the stacked boxes
        side = size - 2 * m - off
        back = QRectF(m + off, m, side, side)
        front = QRectF(m, m + off, side, side)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(back, 2, 2)
        # Punch the front box's footprint out of the back one so the stack
        # reads as layered cards, not a lattice of crossing lines.
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0))
        pad = pen.widthF()
        p.drawRoundedRect(front.adjusted(-pad, -pad, pad, pad), 2, 2)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(front, 2, 2)
    finally:
        p.end()
    return QIcon(pm)


# Playlist text-size presets, in px. Small/medium/large rather than a free
# number: the row height, the column minimums and the header all follow the
# font, so three tested sizes beat an unbounded one.
TEXT_SIZES = {"small": 12, "medium": 14, "large": 17}
DEFAULT_TEXT_SIZE = "medium"

# What the Art column shows. "top"/"middle" are a band one row tall cut from a
# cover scaled to _ART_STRIP_SCALE rows either way — so switching between them
# changes only which part of the sleeve is on screen, never the layout. "full"
# keeps that same scaled square whole and lets the row grow to fit it, which is
# the only one of the three that changes the row height.
ARTWORK_VIEWS = ("top", "middle", "full")
DEFAULT_ARTWORK_VIEW = "top"


@dataclass
class PlaylistEntry:
    """A single track in the playlist."""

    file_path: str
    display_name: str
    artist: str = ""
    title: str = ""
    album: str = ""
    genre: str = ""
    bpm: str = ""
    key: str = ""
    comment: str = ""
    duration: str = ""  # formatted "m:ss"
    year: str = ""
    track_number: str = ""
    label: str = ""
    bitrate: str = ""  # kbps, unformatted
    energy: str = ""  # 1-10, read from the file's own energy field


def _parse_bpm(text: str) -> float | None:
    """Entry BPM string -> float for the library row, or None if unparsable."""
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _parse_int(text: str) -> int | None:
    """Entry bitrate string -> int for the library row, or None if unparsable."""
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _parse_duration(text: str) -> float | None:
    """Entry 'm:ss' duration -> seconds for the library row."""
    try:
        minutes, seconds = text.split(":")
        return int(minutes) * 60 + int(seconds)
    except (AttributeError, ValueError):
        return None


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
        self._default_placeholder = self._placeholder_text
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self._drag_page_id: str | None = None
        self._drag_data_fn = None
        self._drag_guard_fn = None
        # Predicate set by the panel: when it returns True (slice section open),
        # let S/Q/E bubble up to the panel instead of triggering type-ahead here.
        self._slice_keys_active = None
        # Backdrop waveform (visualizations feature): a zoomed window of the
        # playing track's envelope painted behind the rows, scrolling with the
        # playhead (which stays centered) — the CDJ-style moving waveform.
        # Repainted per position tick, so nothing is cached: the visible bin
        # range changes every frame.
        self._backdrop_env: tuple | None = None  # (min_array, max_array)
        self._backdrop_bps: float = 0.0  # envelope bins per second
        self._backdrop_color = QColor(Theme.WAVEFORM_DEFAULT)
        self._backdrop_pos_ms: int = 0
        # Alternative backdrop kind: a visualizer frame (scope/spectrum/fire)
        # blitted dimmed behind the rows. Mutually exclusive with the envelope.
        self._backdrop_image: QImage | None = None

    # Keys the slice section claims while it is expanded.
    _SLICE_KEYS = frozenset({Qt.Key.Key_S, Qt.Key.Key_Q, Qt.Key.Key_E, Qt.Key.Key_L})

    def set_slice_keys_active(self, predicate) -> None:
        self._slice_keys_active = predicate

    def set_placeholder(self, text: str | None) -> None:
        """Override the empty-table hint (None restores the default)."""
        self._placeholder_text = text if text is not None else self._default_placeholder
        self.viewport().update()

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

    def enable_drag_out(self, page_id: str, drag_data_fn, guard_fn=None) -> None:
        """Allow dragging selected rows out as files (see DroppableTableMixin).

        ``guard_fn`` (optional) vetoes a drag before it starts — the Player
        uses it to refuse dragging a file that is no longer on disk.
        """
        self._drag_page_id = page_id
        self._drag_data_fn = drag_data_fn
        self._drag_guard_fn = guard_fn

    def startDrag(self, supportedActions) -> None:
        # A veto has to happen here, before any drag exists: a track can be
        # playing from the PCM cache long after its file moved, and dropping
        # that nowhere-file into a playlist or onto Finder would only produce
        # a broken entry.
        if self._drag_guard_fn is not None and not self._drag_guard_fn():
            return
        # Build ONE drag the in-list reorder machinery AND the sidebar both
        # understand: the model's internal-move data (so dropping back on this list
        # reorders, and the drop indicator shows) plus file URLs + a source marker
        # (so an allowed sidebar button can route the files). Removal is opt-in
        # per source: `remove_cb` runs only on a MoveAction drop, and the Player
        # passes None (see `_drag_data`) so a playlist never loses a row this way.
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

    # ── Backdrop waveform (visualizations) ─────────────────────────────────

    def set_backdrop_envelope(self, env_min, env_max, bins_per_sec: float) -> None:
        """Show the given time-indexed envelope behind the playlist rows."""
        self._backdrop_env = (env_min, env_max)
        self._backdrop_bps = float(bins_per_sec)
        self._backdrop_image = None
        self.viewport().update()

    def set_backdrop_image(self, image: QImage) -> None:
        """Show a visualizer frame behind the rows (replaces the envelope)."""
        self._backdrop_image = image
        self._backdrop_env = None
        self._backdrop_bps = 0.0
        self.viewport().update()

    def clear_backdrop(self) -> None:
        if self._backdrop_env is None and self._backdrop_image is None:
            return
        self._backdrop_env = None
        self._backdrop_bps = 0.0
        self._backdrop_pos_ms = 0
        self._backdrop_image = None
        self.viewport().update()

    def set_backdrop_color(self, color: str) -> None:
        self._backdrop_color = QColor(color)
        if self._backdrop_env is not None:
            self.viewport().update()

    def set_backdrop_position_ms(self, ms: int) -> None:
        """Scroll the zoom window to the playhead; no-op without a backdrop."""
        if self._backdrop_env is None:
            return
        self._backdrop_pos_ms = max(0, int(ms))
        self.viewport().update()

    def _paint_backdrop(self, painter: QPainter) -> None:
        if self._backdrop_image is not None:
            # Visualizer frame: stretch the low-res image over the viewport
            # without smoothing (chunky retro pixels), dimmed so text reads.
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            painter.setOpacity(_BACKDROP_VIS_OPACITY)
            painter.drawImage(self.viewport().rect(), self._backdrop_image)
            painter.setOpacity(1.0)
            return
        env_min, env_max = self._backdrop_env
        if self._backdrop_bps <= 0:
            return
        w, h = self.viewport().width(), self.viewport().height()
        if w <= 0 or h <= 4:
            return
        mid = h / 2.0
        half = max(1.0, mid - 4.0)
        n = len(env_min)
        window_bins = _BACKDROP_WINDOW_MS / 1000.0 * self._backdrop_bps
        start = self._backdrop_pos_ms / 1000.0 * self._backdrop_bps - window_bins / 2.0
        center_x = w // 2
        bright = QColor(self._backdrop_color)
        bright.setAlpha(96)
        dim = QColor(self._backdrop_color)
        dim.setAlpha(46)
        pen = QPen(bright, 1)
        painter.setPen(pen)
        for x in range(w):
            if x == center_x:
                # Played half (left of the centered playhead) is brighter.
                pen.setColor(dim)
                painter.setPen(pen)
            b = int(start + x / w * window_bins)
            if b < 0 or b >= n:
                continue  # before the track start / past its end
            y_top = mid + env_min[b] * half  # env_min is negative
            y_bot = mid + env_max[b] * half
            painter.drawLine(x, int(min(y_top, y_bot)), x, int(max(y_top, y_bot)))
        head_color = QColor(self._backdrop_color)
        head_color.setAlpha(150)
        painter.setPen(QPen(head_color, 2))
        painter.drawLine(center_x, 0, center_x, h)

    def paintEvent(self, event) -> None:
        # Backdrop goes under everything, so before super() paints the rows.
        # Requires the table's own QSS background to be transparent — an opaque
        # style background is filled inside super().paintEvent, over this.
        if self._backdrop_env is not None or self._backdrop_image is not None:
            painter = QPainter(self.viewport())
            try:
                self._paint_backdrop(painter)
            finally:
                painter.end()
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


class NowPlayingLabel(QLabel):
    """The "Playing: …" line, draggable as the file it names.

    The list below can be showing something else entirely — a search result
    set, or a different playlist — while a track plays on, and then there is
    no row to grab. This line always names the loaded track, so it is the one
    handle that's always there: drag it onto a playlist in the sidebar (or
    onto a nav button, or out to Finder) exactly like a row.

    Always a copy — the label isn't a list position, so a move drop has
    nothing to remove. ``set_drag_source`` supplies the path and gets the
    veto (a file that has moved off disk), mirroring the table's guard.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._press_pos: QPoint | None = None
        self._drag_fn = None

    def set_drag_source(self, fn) -> None:
        """Install the callback returning the path to drag, or None to veto."""
        self._drag_fn = fn

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._press_pos is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and (event.position().toPoint() - self._press_pos).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            # Cleared before the (blocking) exec so the veto path can't leave a
            # live press behind and re-fire on the next twitch of the mouse.
            self._press_pos = None
            path = self._drag_fn() if self._drag_fn is not None else None
            if path:
                start_file_drag(self, "player", [path])
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._press_pos = None
        super().mouseReleaseEvent(event)


class PlayerPanel(QWidget):
    """Panel with playlist table, transport controls, seek bar, and volume slider."""

    files_dropped = Signal(list)
    open_in_metadata = Signal(str)
    # Re-emits the slicer's expand/collapse so the window sizer can widen the
    # window's minimum to fit the slicer controls while it is open.
    slice_expanded = Signal(bool)
    # A new saved playlist was created via Save Playlist (payload: node id).
    playlist_saved = Signal(int)
    # §10 highlight trail: which tree nodes to light for the current search
    # selection — (set of playlist ids, {folder id: lit playlists beneath}).
    # Emitted empty whenever there is nothing to light.
    tree_highlight_changed = Signal(object, object)
    # Compatible Tracks opened/closed — the window sizer widens the window's
    # minimum while it is open, the same way the slicer does.
    compat_panel_toggled = Signal(bool)

    # Playlist columns, in logical order. The first nine are the shipped
    # defaults; everything after them is optional and hidden until the user
    # asks for it via the header's right-click menu. Only ever APPEND here —
    # a saved header state addresses sections by number.
    #
    # Marked with QT_TRANSLATE_NOOP because the labels are declared here and
    # displayed in _setup_ui; self.tr() wraps them at the display site.
    _COLUMN_LABELS = (
        QT_TRANSLATE_NOOP("PlayerPanel", "#"),
        QT_TRANSLATE_NOOP("PlayerPanel", "Filename"),
        QT_TRANSLATE_NOOP("PlayerPanel", "Artist"),
        QT_TRANSLATE_NOOP("PlayerPanel", "Title"),
        QT_TRANSLATE_NOOP("PlayerPanel", "BPM"),
        QT_TRANSLATE_NOOP("PlayerPanel", "Key"),
        QT_TRANSLATE_NOOP("PlayerPanel", "Comment"),
        QT_TRANSLATE_NOOP("PlayerPanel", "Duration"),
        QT_TRANSLATE_NOOP("PlayerPanel", "Year"),
        QT_TRANSLATE_NOOP("PlayerPanel", "Album"),
        QT_TRANSLATE_NOOP("PlayerPanel", "Genre"),
        QT_TRANSLATE_NOOP("PlayerPanel", "Track #"),
        QT_TRANSLATE_NOOP("PlayerPanel", "Label"),
        QT_TRANSLATE_NOOP("PlayerPanel", "Bitrate"),
        QT_TRANSLATE_NOOP("PlayerPanel", "Energy"),
        QT_TRANSLATE_NOOP("PlayerPanel", "Art"),
    )
    # Optional columns: (logical index, PlaylistEntry attribute). A None
    # attribute has no text of its own — Art carries a thumbnail instead, read
    # in the background for the rows on screen.
    _OPTIONAL_COLUMNS = (
        (9, "album"),
        (10, "genre"),
        (11, "track_number"),
        (12, "label"),
        (13, "bitrate"),
        (14, "energy"),
        (15, None),
    )
    _ARTWORK_COLUMN = 15
    # The shipped layout, as a *visual* order over those fixed logical indexes:
    # #, Art, Artist, Title, BPM, Key, Comment, Duration, Year, Filename, and
    # then the optional ones in their own order. Expressed this way because the
    # logical order can never change (a saved state addresses sections by
    # number, and every existing user has one), so "the default order" is a
    # separate thing from "the order the columns were declared in".
    _DEFAULT_COLUMN_ORDER = (0, 15, 2, 3, 4, 5, 6, 7, 8, 1, 9, 10, 11, 12, 13, 14)
    # Optional columns that are nonetheless shown out of the box. Art earns it:
    # it is the one column that says what a track *is* at a glance.
    _DEFAULT_SHOWN_OPTIONAL = frozenset({_ARTWORK_COLUMN})
    # Bumped whenever the two constants above change. A saved state beats the
    # defaults, so without this a new default layout would only ever be seen by
    # someone who had never opened the app — see _restore_column_state.
    #
    # 2 rather than 1 because version 1 was written by a build that was still
    # being edited: it stamped the version onto layouts that had not been fully
    # migrated, which left the shipped order in place but four of the ten
    # default columns switched off. Version 1 never shipped, so re-running the
    # migration costs nobody anything and repairs those.
    #
    # 3 for the same reason one step on: a layout saved between those builds
    # could have Art switched off, which the migration then had no reason to
    # touch — a column hidden before the defaults changed is indistinguishable
    # from one the user hid on purpose. Neither 1 nor 2 shipped. `Reset
    # Columns` in the header menu exists so this is the last time a bump is
    # the only way back.
    _COLUMN_DEFAULTS_VERSION = 3
    # Starting widths for the columns that are not sized from their own header
    # word. Measured against the English labels, so they are a *base* rather
    # than the answer: _apply_header_fit_floor raises any that a translation
    # outgrows. Kept as a constant so that floor can be recomputed from
    # scratch when the header font changes, instead of ratcheting.
    _BASE_COLUMN_WIDTHS = {
        0: 40,
        1: 300,   # Filename
        2: 180,   # Artist
        3: 180,   # Title
        6: 200,   # Comment
        # Art: overwritten with the band's real width by _apply_art_icon_size,
        # which knows the row height.
        15: 80,
        9: 180,   # Album
        10: 120,  # Genre
        11: 70,   # Track #
        12: 150,  # Label
        13: 80,   # Bitrate
        14: 70,   # Energy
    }
    # Never offered in the hide menu. Filename is the row's identity, and '#'
    # doubles as the membership-count column during an All-playlists search
    # (_set_count_column) — hiding either would leave a table you cannot read
    # or a swap fighting a visibility flag.
    _LOCKED_COLUMNS = frozenset({0, 1})

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._playlist: list[PlaylistEntry] = []
        self._current_index: int = -1
        # Path of the track loaded in the engine. Playback is deliberately
        # independent of the visible list: switching playlists must not stop
        # the music. _current_index is just this track's row in the visible
        # list (-1 when it isn't there).
        self._playing_path: str | None = None
        # Playlist library binding (set_library): the visible list persists
        # into the loaded node — Scratch by default, or a saved playlist the
        # user clicked in the tree (auto-save: every edit writes through).
        self._library: Library | None = None
        self._loaded_node_id: int = SCRATCH_NODE_ID
        self._loading_playlist = False
        # Session undo stack (§11), owned by MainWindow — auto-save's safety
        # net. None until set_undo_stack, so the Player still works standalone.
        self._undo: UndoStack | None = None
        # Search-as-scope (§9): while active, _playlist holds the search
        # results and _base_entries keeps the loaded node's list to restore.
        # Search results are display-only in the library sense — they must
        # never be written through to the loaded node.
        self._search_active = False
        self._search_scope_all = True
        self._base_entries: list[PlaylistEntry] | None = None
        # Parallel to _playlist while an All-playlists search is showing:
        # per-row membership counts + tooltip of the playlist names, and the
        # rows' track ids (feeds the tree highlight trail on selection).
        self._search_counts: list[int] | None = None
        self._search_tooltips: list[str] | None = None
        self._search_track_ids: list[int] | None = None
        self._search_capped = False
        self._count_column_active = False
        # A column show/hide made during a search: the save is suppressed
        # while '#' wears its temporary search width, so it waits here.
        self._columns_changed_while_searching = False
        # Playlist text size; the table's inline QSS is rebuilt from it.
        self._text_size = DEFAULT_TEXT_SIZE
        # Which part of the cover the Art column shows. Read before the table
        # exists, so it is set here rather than in the artwork section below.
        self._art_view = DEFAULT_ARTWORK_VIEW
        # Artwork thumbnails, for the optional Art column. Keyed (path, mtime)
        # so a file re-tagged elsewhere shows its new cover; _art_missing
        # remembers the files that simply have none, which is most of them in
        # a lot of libraries and the difference between one wasted tag read
        # and one per scroll.
        self._art_cache: "OrderedDict[tuple[str, float], QPixmap]" = OrderedDict()
        self._art_missing: set[tuple[str, float]] = set()
        # (edge, view) of the thumbnails currently cached. The view is in it
        # because top and middle produce images of identical size: comparing
        # the edge alone would serve a cached top band under the middle
        # setting, and the change would appear to do nothing at all.
        self._art_size_loaded: tuple[int, str] = (0, "")
        self._art_worker: ArtworkWorker | None = None
        self._art_thread: ArtworkThread | None = None
        self._num_col_width = 40
        # path -> "the file is gone", for the "!" marker (step 10). Memoised
        # because the table rebuilds on every list edit and a stat per row
        # per rebuild is wasted work; invalidated wholesale whenever the
        # list is reloaded, a file is relocated, or the panel is shown, so a
        # file restored outside the app stops being marked.
        self._missing_cache: dict[str, bool] = {}
        # Rows the last rebuild marked as missing (drives the dimming).
        self._missing_rows: set[int] = set()
        # Compatible Tracks: the panel that splits the playlist area. Width is
        # remembered for the session only — the same reasoning as the
        # playlists sidebar, where a width chosen on one screen is wrong on
        # the next — and so is the open state, which starts closed.
        self._compat_width = _COMPAT_DEFAULT_WIDTH

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
        _cfg = load_config()
        self._edit_locked: bool = _cfg.player_edit_locked
        # Visualizations: master switch (Settings) and last chosen visual.
        self._visualizations_enabled: bool = _cfg.visualizations_enabled
        self._vis_mode: str = _cfg.visualization_mode
        # A popout visual doesn't survive a restart (a visualizer window
        # popping up at launch, before the main window, would be jarring);
        # the backdrop does. Downgrade without persisting — the next explicit
        # dropdown change writes the config anyway.
        if self._vis_mode in POPOUT_MODES:
            self._vis_mode = "off"
        # Source PCM behind the playlist backdrop waveform: the track loaded
        # into the engine (a reference, not a copy). The envelope is computed
        # lazily so switching modes mid-track can build it on demand.
        self._backdrop_src: tuple | None = None  # (pcm, sr)
        self._backdrop_env: tuple | None = None  # (min, max, bins_per_sec)
        self._backdrop_env_path: str | None = None
        # Popout visualizer (oscilloscope/spectrum/fire/fractal); created on
        # first use.
        self._vis_window: VisualizerWindow | None = None
        # Backdrop visualizer: same renderers, blitted behind the playlist.
        # Ticks only while playing (plus a short silence decay after pause).
        self._backdrop_renderer: VisRenderer | None = None
        self._vis_decay: int = 0
        self._vis_tick_timer = QTimer(self)
        self._vis_tick_timer.setInterval(FRAME_MS)
        self._vis_tick_timer.timeout.connect(self._on_vis_backdrop_tick)
        # True while WE close the popout (mode/setting change), so the closed
        # handler only resets the dropdown when the USER dismissed the window.
        self._vis_closing: bool = False
        self._waveform_color: str = Theme.WAVEFORM_DEFAULT

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
        # Coming back to the Player is the moment a remounted drive should
        # stop being marked as missing (and a newly unplugged one start).
        self._refresh_missing_marks()
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
            # Icon menu buttons (visuals eye, search scope): keep the default
            # (Clear Playlist-style) light fill/border but drop the wide text
            # padding so the icon centres in its compact fixed size.
            "QPushButton#visMenuButton, QPushButton#scopeMenuButton,"
            " QPushButton#compatMenuButton { padding: 2px; }"
            # The checked state has to read as "this panel is open" — the same
            # neon the Edit Lock indicator uses, as a border rather than a fill
            # so the grey glyph inside stays legible.
            f"QPushButton#compatMenuButton:checked {{ border: 1px solid {Theme.NEON_YELLOW};"
            f" background-color: {Theme.BG_LIGHT}; }}"
            # A QSplitter is a QFrame, so without this it wears the global
            # BG_MEDIUM fill *and* a 1px border — a box drawn around the
            # playlist. Same trap as #sidebarModeStack (see CLAUDE.md).
            "QSplitter#playlistSplitter { background-color: transparent; border: none; }"
            "QWidget#compatiblePanel { background-color: transparent; }"
        )
        layout = QVBoxLayout(content)
        layout.setContentsMargins(Theme.PADDING, Theme.PADDING, Theme.PADDING, Theme.PADDING)
        layout.setSpacing(Theme.SPACING)

        # Title row: "Player" on the left, the loaded track's album art sitting
        # just after the title text (shown only while a track is loaded). The art
        # follows the end of the text with a little padding so the header stays
        # legible no matter how wide the translated title is; the trailing stretch
        # keeps both left-aligned.
        #
        # It lives in its own widget so its width can be pinned to the visible
        # viewport (see _sync_title_row_width). Without that pin the row inherits
        # the content width, which the transport row below holds at ~690px — so
        # on a narrow window the right-hand group would stop moving left while a
        # dead gap sat between it and the scope button.
        self._title_row_widget = QWidget()
        self._title_row_widget.setObjectName("playerTitleRow")
        title_row = QHBoxLayout(self._title_row_widget)
        title_row.setContentsMargins(0, 0, 0, 0)
        # Explicit: a nested layout inherited Theme.SPACING from the parent
        # layout, but a widget's own layout falls back to the style default.
        title_row.setSpacing(Theme.SPACING)
        title = QLabel(self.tr("Player"))
        title.setObjectName("sectionTitle")
        title.setStyleSheet(f"font-size: 24px; color: {Theme.NEON_YELLOW};")
        title_row.addWidget(title)

        # Breadcrumb: which list the Player is showing ("› Scratch",
        # "› Summer Set"). Quieter color so the panel identity stays "Player".
        self._context_label = QLabel("")
        self._context_label.setStyleSheet(
            f"font-size: 24px; color: {Theme.TEXT_SECONDARY};"
        )
        title_row.addWidget(self._context_label)
        title_row.addSpacing(12)

        self._art_label = QLabel()
        self._art_label.setFixedSize(_HEADER_ART_SIZE, _HEADER_ART_SIZE)
        self._art_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._art_label.hide()
        title_row.addWidget(self._art_label, 0, Qt.AlignmentFlag.AlignVCenter)

        # Search-as-scope: results are just another list, shown in the same
        # table and playable immediately. Both widgets stay hidden until a
        # library is attached (set_library) — there is nothing to search
        # before that. The visible placeholder is the discoverability hook
        # (§9: a search box announces less than a button, so it must speak).
        title_row.addSpacing(16)
        self._search_field = QLineEdit()
        self._search_field.setObjectName("playerSearchField")
        self._search_field.setClearButtonEnabled(True)
        self._search_field.setFixedWidth(180)
        self._search_field.setPlaceholderText(self.tr("Search all playlists…"))
        self._search_field.hide()
        title_row.addWidget(self._search_field, 0, Qt.AlignmentFlag.AlignVCenter)

        # Scope picker: a compact icon button (mirroring the visuals eye
        # button) whose glyph shows the current scope — one box for "This
        # playlist", stacked boxes for "All playlists" — with the words in
        # its checkable menu and tooltip.
        self._scope_this_icon = _make_scope_this_icon()
        self._scope_all_icon = _make_scope_all_icon()
        self._scope_btn = QPushButton()
        self._scope_btn.setObjectName("scopeMenuButton")
        self._scope_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._scope_btn.setFixedSize(40, 26)
        self._scope_menu = QMenu(self)
        scope_group = QActionGroup(self)
        scope_group.setExclusive(True)
        self._scope_actions: dict[bool, QAction] = {}
        for scope_all, label in (
            (False, self.tr("This playlist")),
            (True, self.tr("All playlists")),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.triggered.connect(
                lambda _=False, s=scope_all: self._select_search_scope(s)
            )
            scope_group.addAction(action)
            self._scope_menu.addAction(action)
            self._scope_actions[scope_all] = action
        self._scope_btn.clicked.connect(self._show_scope_menu)
        self._scope_btn.hide()
        title_row.addWidget(self._scope_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self._apply_search_scope(True)  # default: All playlists

        title_row.addStretch()

        # Visuals selector: a compact eye-icon button (default QPushButton
        # style — the same light fill as Clear Playlist) that opens a checkable
        # menu of modes. Shown only when visualizations are enabled in
        # Settings. Mode ids are persisted in config (visualization_mode);
        # the menu labels are translated UI prose.
        self._vis_button = QPushButton()
        self._vis_button.setObjectName("visMenuButton")
        self._vis_button.setIcon(_make_eye_icon())
        self._vis_button.setToolTip(self.tr("Choose a visualization"))
        self._vis_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._vis_button.setFixedSize(40, 26)
        self._vis_menu = QMenu(self)
        self._vis_action_group = QActionGroup(self)
        self._vis_action_group.setExclusive(True)
        self._vis_actions: dict[str, QAction] = {}
        for mode, label in (
            ("off", self.tr("Visuals off")),
            ("backdrop", self.tr("Backdrop waveform")),
            ("backdrop_scope", self.tr("Backdrop oscilloscope")),
            ("backdrop_spectrum", self.tr("Backdrop spectrum")),
            ("backdrop_fire", self.tr("Backdrop fire")),
            ("backdrop_fractal", self.tr("Backdrop fractal")),
            ("oscilloscope", self.tr("Popout oscilloscope")),
            ("spectrum", self.tr("Popout spectrum bars")),
            ("fire", self.tr("Popout fire")),
            ("fractal", self.tr("Popout fractal")),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.triggered.connect(lambda _=False, m=mode: self._select_vis_mode(m))
            self._vis_action_group.addAction(action)
            self._vis_menu.addAction(action)
            self._vis_actions[mode] = action
        # A separator sets the popouts apart from the backdrop modes.
        self._vis_menu.insertSeparator(self._vis_actions["oscilloscope"])
        if self._vis_mode in self._vis_actions:
            self._vis_actions[self._vis_mode].setChecked(True)
        self._vis_button.clicked.connect(self._show_vis_menu)
        self._vis_button.setVisible(self._visualizations_enabled)
        title_row.addWidget(self._vis_button, 0, Qt.AlignmentFlag.AlignVCenter)

        # Compatible Tracks: the same 40×26 icon button, checkable, sitting
        # beside the visuals eye. No master switch — the feature is offline
        # and costs nothing when closed (the eye has one because a GPU
        # visualizer does not).
        self._compat_button = QPushButton()
        self._compat_button.setObjectName("compatMenuButton")
        self._compat_button.setIcon(_make_compat_icon())
        self._compat_button.setCheckable(True)
        self._compat_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._compat_button.setFixedSize(40, 26)
        self._compat_button.toggled.connect(self._on_compat_toggled)
        title_row.addWidget(self._compat_button, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addSpacing(16)

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
        layout.addWidget(self._title_row_widget)

        # Playlist table
        self._table = ReorderableTableWidget()
        # Inset dividers between the column titles as a width-grab hint.
        self._table.setHorizontalHeader(SeparatorHeaderView(self._table))
        # The nine default columns keep logical indexes 0-8 and the optional
        # ones are appended after them, never inserted between: a saved header
        # state refers to sections by number, so inserting would silently
        # re-point every existing user's widths and order at the wrong columns.
        self._table.setColumnCount(len(self._COLUMN_LABELS))
        self._table.setHorizontalHeaderLabels(
            [self.tr(label) for label in self._COLUMN_LABELS]
        )
        # Flat playlist surface in the sidebar's grey (no border / row stripes),
        # so the near-black slice tray below reads as the distinct work area.
        # Scoped to this table so other panels' tables keep the default styling.
        self._table.setAlternatingRowColors(False)
        # The cell text inset (5px) is owned by NoElideDelegate, which hand-draws
        # the label; CSS horizontal padding would not affect it. This rule only
        # keeps the 8px vertical padding that sets the row height.
        # Transparent (not BG_MEDIUM) so the backdrop waveform painted in
        # paintEvent isn't covered by the style's background fill; the panel
        # behind the table is BG_MEDIUM, so the resting look is identical.
        self._table.setStyleSheet(self._table_stylesheet())
        self._table.verticalHeader().setVisible(False)
        # The shipped row height, captured before anything scales it: the
        # text-size presets are multiples of this, so Medium is exactly today.
        self._base_row_height = self._table.verticalHeader().defaultSectionSize()
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
        for col in range(1, self._table.columnCount()):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        # Kept so a refused saved state can be replaced by the defaults rather
        # than by whatever a half-applied restore left behind.
        self._default_column_widths = dict(self._BASE_COLUMN_WIDTHS)
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
            self._default_column_widths[col] = width
        # The rest keep their English-measured base width unless a translation
        # needs more room than it allows for.
        self._apply_header_fit_floor(header_fm)
        for col, width in self._default_column_widths.items():
            self._table.setColumnWidth(col, width)
        # Width the # column grows to while it shows membership counts under
        # the "Playlists" header (All-playlists search), measured the same way.
        self._playlists_col_width = (
            header_fm.horizontalAdvance(self.tr("Playlists"))
            + 2 * SeparatorHeaderView._TEXT_PAD
            + 4
        )

        # No '…' in any column — the no-elide delegate is the table default; the
        # '#' column then overrides it with its current-row delegate. NoElide also
        # suppresses the focus rect, so MainWindow must skip this table when it
        # installs its global NoFocusDelegate (or it would clobber this one).
        self._table.setItemDelegate(NoElideDelegate(self._table))
        self._row_number_delegate = CurrentRowDelegate(self._table)
        self._table.setItemDelegateForColumn(0, self._row_number_delegate)

        # Restore the user's saved column order/widths over the defaults above.
        self._restore_column_state()
        # After the restore, so it can also floor a saved Art width that
        # predates the current band size (the same reasoning as the word-fit
        # columns above). Needed at all because a column restored *visible*
        # never passes through _set_column_visible, and so would otherwise
        # paint its strips at Qt's 16px default icon size.
        self._apply_art_icon_size()
        if self._default_columns_applied:
            # Art is shown out of the box, so nobody has dragged it and it has
            # no saved width — but it does have Qt's default section size,
            # which is wider than the band. _apply_art_icon_size only ever
            # widens (a width the user chose is theirs to keep), so the exact
            # default is set here, where it is known that there isn't one.
            self._table.setColumnWidth(
                self._ARTWORK_COLUMN,
                self._default_column_widths[self._ARTWORK_COLUMN],
            )

        # The playlist and the Compatible Tracks panel share the row, split by
        # a draggable handle. While the panel is hidden the splitter has one
        # visible child and behaves exactly as the bare table did, handle
        # included (Qt hides a handle whose neighbour is hidden).
        self._compat_panel = CompatibleTracksPanel(self)
        self._compat_panel.hide()
        self._compat_panel.track_activated.connect(self._on_compat_track_activated)
        self._compat_panel.audition_started.connect(self._on_audition_started)
        self._compat_panel.set_volume(self._volume_pct / 100.0)
        self._playlist_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._playlist_splitter.setObjectName("playlistSplitter")
        self._playlist_splitter.setChildrenCollapsible(False)
        self._playlist_splitter.setHandleWidth(10)
        self._playlist_splitter.addWidget(self._table)
        self._playlist_splitter.addWidget(self._compat_panel)
        self._playlist_splitter.setStretchFactor(0, 1)
        self._playlist_splitter.setStretchFactor(1, 0)
        self._playlist_splitter.splitterMoved.connect(self._on_compat_splitter_moved)
        layout.addWidget(self._playlist_splitter, 1)
        self._sync_compat_tooltip()

        # Seek bar — wrapped in a widget so it can be hidden when the slice
        # section's waveform takes over as the seek control. It sits directly
        # above the combined controls row so the scrub bar reads as part of the
        # transport cluster, and vanishing while the slicer is open just tucks
        # the controls row up under the playlist.
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

        # Combined controls row: volume on the left, transport buttons centered,
        # then track-count stats and Clear Playlist on the right. Folding the
        # transport buttons onto the volume/Clear line (instead of a row of their
        # own) saves vertical space and puts them just under the seek bar. This
        # row stays put when the seek bar is hidden for the slicer's waveform.
        controls_row = QHBoxLayout()

        vol_label = QLabel(self.tr("Vol"))
        vol_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        vol_label.setMinimumWidth(25)
        controls_row.addWidget(vol_label)

        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setRange(0, 100)
        self._volume_slider.setValue(70)
        self._volume_slider.setFixedWidth(120)
        controls_row.addWidget(self._volume_slider)

        controls_row.addStretch()

        # Transport controls are drawn glyphs (not text) so they read the same
        # in every language; the words live on as translated tooltips.
        self._prev_btn = QPushButton()
        self._prev_btn.setFixedWidth(48)
        self._prev_btn.setIcon(_make_prev_icon())
        self._prev_btn.setIconSize(QSize(14, 14))
        self._prev_btn.setToolTip(self.tr("Previous"))
        controls_row.addWidget(self._prev_btn)

        # Play/Pause uses a grey outline (default button style) with a drawn
        # play triangle / pause bars instead of text, toggled on state change.
        self._icon_play = _make_play_icon()
        self._icon_pause = _make_pause_icon()
        self._play_btn = QPushButton()
        self._play_btn.setFixedWidth(48)
        self._play_btn.setIcon(self._icon_play)
        self._play_btn.setIconSize(QSize(14, 14))
        self._play_btn.setToolTip(self.tr("Play / Pause  (Space)"))
        controls_row.addWidget(self._play_btn)

        self._stop_btn = QPushButton()
        self._stop_btn.setFixedWidth(48)
        self._stop_btn.setIcon(_make_stop_icon())
        self._stop_btn.setIconSize(QSize(14, 14))
        self._stop_btn.setToolTip(self.tr("Stop"))
        controls_row.addWidget(self._stop_btn)

        self._next_btn = QPushButton()
        self._next_btn.setFixedWidth(48)
        self._next_btn.setIcon(_make_next_icon())
        self._next_btn.setIconSize(QSize(14, 14))
        self._next_btn.setToolTip(self.tr("Next"))
        controls_row.addWidget(self._next_btn)

        # Transport buttons must not hold keyboard focus: otherwise a focused button
        # would consume the Space key (and could re-fire its own action) instead of
        # the play/pause shortcut. Standard for media transport controls.
        for btn in (self._prev_btn, self._play_btn, self._stop_btn, self._next_btn):
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        controls_row.addStretch()

        # Stats label
        self._stats_label = QLabel("")
        self._stats_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        controls_row.addWidget(self._stats_label)

        # Hidden until a library is attached (set_library) — saving needs
        # somewhere to save to.
        self._save_btn = QPushButton(self.tr("Save Playlist"))
        self._save_btn.clicked.connect(self._on_save_playlist)
        self._save_btn.hide()
        controls_row.addWidget(self._save_btn)

        self._clear_btn = QPushButton(self.tr("Clear Playlist"))
        self._clear_btn.clicked.connect(self._on_clear_playlist)
        controls_row.addWidget(self._clear_btn)

        layout.addLayout(controls_row)

        # Now-playing line: names the track loaded in the engine. Playback is
        # independent of the visible list (switching playlists doesn't stop
        # it), so while browsing other lists this is the one place that says
        # what's actually playing.
        # It's also the drag handle for the playing track — see NowPlayingLabel.
        self._now_playing_label = NowPlayingLabel()
        self._now_playing_label.setObjectName("nowPlayingLabel")
        self._now_playing_label.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: 13px;"
        )
        self._now_playing_label.setCursor(Qt.CursorShape.OpenHandCursor)
        self._now_playing_label.setToolTip(
            self.tr("Drag this onto a playlist to add the playing track")
        )
        self._now_playing_label.set_drag_source(self._now_playing_drag_path)
        # Only as wide as the text, so the grab cursor doesn't claim the whole
        # row's dead space to the right.
        self._now_playing_label.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
        )
        self._now_playing_label.hide()
        layout.addWidget(self._now_playing_label)

        # Collapsible slice section — shares the engine; builds its waveform
        # lazily on expand. Lets the user trim a slice from the loaded track.
        self._slice = SliceSection(self._engine, self)
        layout.addWidget(self._slice)
        # Route S/Q/E through the panel only while the section is open.
        self._table.set_slice_keys_active(self._slice.is_expanded)

        self._scroll.setWidget(content)
        # Keep the header inside the visible width (see _sync_title_row_width).
        # The panel's own resize covers the window being dragged; the scrollbar
        # signal covers the vertical bar appearing when the slicer expands,
        # which narrows the viewport without resizing the panel.
        self._scroll.verticalScrollBar().rangeChanged.connect(
            lambda *_: self._sync_title_row_width()
        )
        self._sync_title_row_width()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_title_row_width()

    def _sync_title_row_width(self) -> None:
        """Cap the header at the visible width so it never rides the scroll.

        Everything below it (transport row, table) may be wider than the
        viewport and scroll horizontally; the header is chrome and should
        stay put. Capping it also makes its trailing stretch collapse when
        space runs short, so the visuals button settles one layout spacing
        from the scope button instead of stranding a gap.
        """
        visible = self._scroll.viewport().width() - 2 * Theme.PADDING
        # Never below the row's own minimum: squeezing past it makes the
        # fixed-width search field and scope button overlap instead of
        # clipping. Past this point the header overflows like any other row.
        floor = self._title_row_widget.minimumSizeHint().width()
        self._title_row_widget.setMaximumWidth(max(visible, floor))

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
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_column_menu)

        # Artwork thumbnails are read for the rows on screen only, so the
        # triggers are "the visible range may have changed": scrolling, and
        # anything that resizes the viewport. Debounced — both fire
        # continuously, and a thread per scrolled pixel is not a plan.
        self._art_timer = QTimer(self)
        self._art_timer.setSingleShot(True)
        self._art_timer.setInterval(120)
        self._art_timer.timeout.connect(self._load_visible_artwork)
        self._table.verticalScrollBar().valueChanged.connect(
            self._schedule_artwork_load
        )

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
        self._table.enable_drag_out("player", self._drag_data, self._guard_drag)

        # Prefetch the track the user selects so pressing Play is instant.
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

        # Spacebar = play/pause, but only while focus is within this panel (so it
        # never collides with the Keyboard panel's keys or other pages).
        self._play_pause_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        self._play_pause_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._play_pause_shortcut.activated.connect(self._on_play_pause)

        # Search: debounced so a fast typist gets one query per pause, not one
        # per keystroke (each run repopulates the table).
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self._run_search)
        self._search_field.textChanged.connect(self._on_search_text_changed)
        # Escape backs out of a search from the field or the table. Widget-
        # scoped so it never fires while an inline cell editor has focus
        # (there Escape must keep meaning "cancel the edit").
        for widget in (self._search_field, self._table):
            esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), widget)
            esc.setContext(Qt.ShortcutContext.WidgetShortcut)
            esc.activated.connect(self._exit_search)

        # Slice section: swap the seek control when the waveform is up, supply
        # the waveform lazily, and forward its playhead seeks to the engine.
        # Both toggles land on one slot, which recomputes from both states.
        self._slice.expanded_changed.connect(self._on_slice_view_changed)
        self._slice.waveform_shown_changed.connect(self._on_slice_view_changed)
        self._slice.request_waveform.connect(self._build_waveform_for_current)
        self._slice.seek_requested.connect(self._on_seek)

    # ── Public API ──────────────────────────────────────────────

    def add_tracks(
        self,
        tracks: list[dict],
        allow_duplicates: bool | None = None,
        *,
        scroll_to_end: bool = True,
    ) -> None:
        """Add tracks to the playlist.

        Each dict should have: file_path, display_name, and optionally artist, title,
        bpm, key, comment, year (str), duration (float seconds).

        ``allow_duplicates`` forces the answer to the duplicate question and
        stays silent: ``True`` keeps every incoming file (used when loading a
        saved playlist, where a deliberately repeated track must survive),
        ``False`` drops the ones already here. The default ``None`` consults
        the ``duplicate_policy`` setting, which may put it to the user — and
        that prompt is **deferred**, so this can return before the tracks land.
        Anything that must run afterwards belongs in ``_append_tracks``.

        ``scroll_to_end`` brings the newly appended rows into view, which is
        what an *add* means. It rides along to ``_append_tracks`` rather than
        being done here for the same deferral reason: when the policy is ASK
        the rows do not exist yet when this returns. Two callers turn it off,
        and both want the top of the list instead — ``load_node`` (opening a
        playlist shows its beginning) and the file-open path (which plays row
        1, so scrolling away would hide the track that just started).
        """
        # Files added while a search is showing target the loaded playlist —
        # leave the search so the user sees where they landed. Must happen
        # before the duplicate check: mid-search ``_playlist`` holds the search
        # results, not the playlist the files are actually going into.
        if self._search_active:
            self._exit_search()
        by_path: dict[str, dict] = {}
        for t in tracks:
            by_path.setdefault(t["file_path"], t)
        resolve_additions(
            self,
            [t["file_path"] for t in tracks],
            lambda: [e.file_path for e in self._playlist],
            self._playlist_display_name(),
            lambda resolved: self._append_tracks(
                [by_path[p] for p in resolved if p in by_path],
                proposed=len(tracks),
                scroll_to_end=scroll_to_end,
            ),
            # None consults the setting; a forced answer never asks.
            policy=None
            if allow_duplicates is None
            else (DUPLICATES_ADD if allow_duplicates else DUPLICATES_SKIP),
        )

    def _playlist_display_name(self) -> str:
        """The loaded playlist's name, for the duplicate prompt."""
        if self._library is not None:
            node = self._library.get_node(self._loaded_node_id)
            if node is not None:
                return node.name
        return self.tr("Scratch")

    def _append_tracks(
        self, tracks: list[dict], *, proposed: int = 0, scroll_to_end: bool = True
    ) -> None:
        """Append resolved tracks to the visible list and refresh around them.

        ``proposed`` is how many were offered before the duplicate filter ran.
        An add that was *resolved away* — everything skipped, or cancelled —
        leaves the list and the undo stack alone; an add that was empty to
        begin with still refreshes, because that is how loading an empty
        playlist clears the table.

        ``scroll_to_end`` is the end of the deferred path from ``add_tracks``:
        this is the first moment the new rows exist to scroll to.
        """
        if not tracks and proposed:
            return
        for t in tracks:
            artist = t.get("artist", "")
            title = t.get("title", "")
            album = t.get("album", "")
            genre = t.get("genre", "")
            bpm = t.get("bpm", "")
            key = t.get("key", "")
            comment = t.get("comment", "")
            year = t.get("year", "")
            track_number = t.get("track_number", "")
            label = t.get("label", "")
            bitrate = t.get("bitrate", "")
            energy = t.get("energy", "")
            duration_sec = t.get("duration")
            # Fall back to reading these from the file's tags when a caller didn't
            # supply them (e.g. tracks sent from the Analyze panel, which only
            # passes BPM/key), so the columns populate regardless of entry point.
            #
            # Track number, label and bitrate are filled by this read but do NOT
            # trigger it: plenty of files have no label or track number at all,
            # so testing them here would open every such file on every add,
            # forever, to learn nothing.
            if (
                not artist
                or not title
                or not bpm
                or not key
                or not comment
                or not year
                or duration_sec is None
            ):
                try:
                    from src.metadata.tags import read_metadata

                    meta = read_metadata(t["file_path"])
                    artist = artist or (meta.artist or "")
                    title = title or (meta.title or "")
                    album = album or (meta.album or "")
                    genre = genre or (meta.genre or "")
                    bpm = bpm or (str(int(round(meta.bpm))) if meta.bpm else "")
                    key = key or (meta.key or "")
                    comment = comment or (meta.comment or "")
                    year = year or (str(meta.year) if meta.year else "")
                    track_number = track_number or (
                        str(meta.track_number) if meta.track_number else ""
                    )
                    label = label or (meta.label or "")
                    bitrate = bitrate or (str(meta.bitrate) if meta.bitrate else "")
                    energy = energy or (str(meta.energy) if meta.energy else "")
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
                album=album,
                genre=genre,
                bpm=bpm,
                key=key,
                comment=comment,
                duration=duration_str,
                year=year,
                track_number=track_number,
                label=label,
                bitrate=bitrate,
                energy=energy,
            )
            # Duplicates were already resolved by add_tracks — whatever
            # reaches here has been cleared to land.
            self._playlist.append(entry)

        self._rebuild_table()
        # Show where they landed. Only when rows were actually added — the
        # empty-refresh case above is a clear, not an add. Scroll only: the
        # selection stays where the user left it.
        if scroll_to_end and tracks:
            self._table.scrollToBottom()
        self._update_stats()
        # Re-enable Play/Stop now that the playlist is non-empty. Without this the
        # Play button stays disabled until a playback-state change (e.g. a double
        # click), which is why pressing Play after loading appeared to do nothing.
        self._update_transport_state()
        # Start decoding the first track in the background so the first Play is
        # instant instead of waiting on a full decode.
        self._prefetch_default_target()
        self._persist_playlist()

    def play_path_if_idle(self, path: str) -> bool:
        """Start playing *path*, but only if nothing is under way. True if it did.

        This is what "Open with Mixed in P" needs and why it is public rather
        than the caller reaching into ``_play_track``: on a cold start playing
        the file *is* the whole point, while a file arriving mid-set must not
        cut the DJ off. Idle is the deciding question, and it is a wider
        question than ``is_playing``:

        - **Paused counts as busy.** A paused track still holds a position the
          user chose and expects to resume from; replacing it loses that as
          surely as interrupting playback does.
        - **A pending decode counts as busy.** Between ``_play_track`` and the
          PCM arriving, the engine is genuinely stopped — acting on that would
          hijack a track that is a few hundred milliseconds from starting.

        The search runs from the end of the list because additions force
        duplicates: if the file was already here, the copy that just landed is
        the last one, and that is the one the user asked for.
        """
        if (
            self._engine.is_playing()
            or self._engine.is_paused()
            or self._pending_play_path is not None
        ):
            return False
        for index in range(len(self._playlist) - 1, -1, -1):
            if self._playlist[index].file_path == path:
                self._play_track(index)
                return True
        return False

    def stop_playback(self) -> None:
        """Stop playback (called on nav-away from the Player and on app close)."""
        self._engine.stop()

    def wait_for_readers(self, timeout_ms: int = 5000) -> bool:
        """Block until nothing here has an audio file open. False on timeout.

        Adding tracks warms the likely-next one (``_prefetch_default_target``)
        on a background thread, so for a short window after ``add_tracks`` the
        panel holds a read handle on a file the caller has no way to know
        about. On POSIX that is invisible — an open handle does not block an
        unlink or a rename. On Windows it is ``WinError 32``.

        This is the panel's way of saying "I am done with that path". Public
        because the alternative for a caller is to guess at a sleep.
        """
        return wait_for_threads(self._thread_keep, timeout_ms)

    def shutdown_workers(self) -> None:
        """Wait for any decode or waveform thread still reading a file.

        Separate from ``stop_playback``: that ends the audio output, this ends
        the *readers*. Called from ``closeEvent``, which is what stops a
        running QThread being destroyed under Qt when the panel goes away.

        The artwork reader is asked to stop first: its run() is a plain loop,
        not an event loop, so quit() means nothing to it and the wait would
        otherwise sit through every remaining file in the batch.
        """
        self._cancel_artwork_worker()
        self._compat_panel.shutdown_workers()
        self.wait_for_readers()

    def closeEvent(self, event) -> None:
        self.shutdown_workers()
        super().closeEvent(event)

    def refresh(self) -> None:
        """Refresh UI state."""
        self._rebuild_table()
        self._update_stats()
        self._update_transport_state()

    # ── Playlist library binding ─────────────────────────────────

    def set_library(self, library: Library) -> None:
        """Attach the playlist library.

        From here on the visible list persists into the loaded node (Scratch
        by default) and Save Playlist becomes available.
        """
        self._library = library
        self._save_btn.show()
        self._search_field.show()
        self._scope_btn.show()
        self._compat_panel.set_library(library)
        self._update_context_label()

    def set_undo_stack(self, stack: UndoStack) -> None:
        """Attach the session undo stack that list edits record onto."""
        self._undo = stack

    @property
    def loaded_node_id(self) -> int:
        return self._loaded_node_id

    def load_node(self, node_id: int) -> None:
        """Show a saved playlist (or Scratch) in the Player.

        Replaces the visible list only — the previous node keeps its saved
        contents; edits from now on write through to *this* node.
        """
        if self._library is None or self._library.get_node(node_id) is None:
            return
        # Loading a playlist ends a search (§10: click a highlighted playlist
        # → it loads and the search clears). No list restore — the node's
        # list is about to replace whatever is showing.
        if self._search_active:
            self._dismiss_search()
        tracks = self._library.get_items(node_id)
        # Swap only the visible list — the engine keeps playing whatever it
        # was playing. The now-playing label (above the slicer) carries the
        # track's identity while it isn't a row in the visible list.
        self._loading_playlist = True
        try:
            self._loaded_node_id = node_id
            self._playlist = []
            self._current_index = -1
            # Hand add_tracks everything the library row already carries, so
            # a load doesn't depend on (or wait for) per-file tag reads —
            # and a track whose file is missing still shows its stored tags.
            # The tag-read fallback then only fills what the DB lacks: the
            # comment for rows written before there was a column for it (see
            # _store_read_comments), and year/track number/label/bitrate for
            # rows added before schema v5 gave them one.
            self.add_tracks(
                [
                    {
                        "file_path": t.path,
                        "display_name": Path(t.path).name,
                        "artist": t.artist,
                        "title": t.title,
                        "album": t.album,
                        "genre": t.genre,
                        "bpm": str(int(round(t.bpm))) if t.bpm else "",
                        "key": t.key,
                        "comment": t.comment,
                        "year": t.year or "",
                        "track_number": t.track_number or "",
                        "label": t.label or "",
                        "bitrate": str(t.bitrate) if t.bitrate else "",
                        "energy": str(t.energy) if t.energy else "",
                        "duration": t.duration,
                    }
                    for t in tracks
                ],
                allow_duplicates=True,  # a saved list may repeat a track on purpose
                scroll_to_end=False,  # a playlist opens at its top, not its end
            )
            self._table.scrollToTop()
        finally:
            self._loading_playlist = False
        self._store_read_comments(tracks)
        # Re-link the playing track to its row if this list contains it.
        if self._playing_path is not None:
            self._relink_playing_row()
            self._highlight_current_row()
            self._update_transport_state()
        self._update_context_label()

    def _store_read_comments(self, tracks) -> None:
        """Keep comments the load just read from the files.

        The comment column arrived after the library did, so rows written by
        an earlier build carry none — and a field the database doesn't hold is
        a field search can't find. A load already reads tags for whatever the
        row lacks, so storing that one column costs nothing and makes the
        playlist comment-searchable from the first time it is opened.

        Deliberately not `_persist_playlist`: that is suppressed during a load
        (it would rewrite the list it is loading, and push undo). This writes
        tags only — never membership, never the undo stack. It also only ever
        fills a comment in, so a file that failed to read can't blank one.
        """
        if self._library is None:
            return
        by_path = {t.path: t for t in tracks}
        for entry in self._playlist:
            track = by_path.get(entry.file_path)
            if track is not None and entry.comment and entry.comment != track.comment:
                self._library.update_track_tags(track.id, comment=entry.comment)

    def _persist_playlist(self) -> None:
        """Auto-save: write the visible list through to the loaded node."""
        # A visible search result list is NOT the loaded node's content —
        # persisting it would overwrite the playlist with the search hits.
        if self._library is None or self._loading_playlist or self._search_active:
            return
        if self._library.get_node(self._loaded_node_id) is None:
            # The loaded playlist was deleted from the tree; fall back to
            # Scratch rather than writing into a void.
            self._loaded_node_id = SCRATCH_NODE_ID
            self._update_context_label()
        # Every list mutation lands here, so this is where undo is captured
        # (§11) — one snapshot covers remove, Clear, drag-reorder, and add
        # alike. Taken before the write, and only kept if the contents
        # actually changed, which is what keeps inline tag edits (they route
        # through here too) off the stack.
        before = self._library.snapshot_items(self._loaded_node_id)
        # Entry fields mirror the file's tags (read at add time), so they're
        # passed through even when empty — clearing a tag clears the row.
        track_ids = [
            self._library.add_track(
                e.file_path,
                artist=e.artist,
                title=e.title,
                album=e.album,
                genre=e.genre,
                comment=e.comment,
                bpm=_parse_bpm(e.bpm),
                key=e.key,
                year=e.year,
                track_number=e.track_number,
                label=e.label,
                bitrate=_parse_int(e.bitrate),
                energy=_parse_int(e.energy),
                duration=_parse_duration(e.duration),
            )
            for e in self._playlist
        ]
        self._library.set_items(self._loaded_node_id, track_ids)
        self._push_items_undo(self._loaded_node_id, before, track_ids)

    def _push_items_undo(
        self, node_id: int, before: list, after_ids: list[int]
    ) -> None:
        """Record how to put *node_id* back the way it was, if it changed."""
        if self._undo is None:
            return
        before_ids = [t.id for t in before]
        if before_ids == after_ids:
            return  # a tag edit, or a no-op rewrite: nothing to reverse
        # Labels are internal identifiers, NOT translated: nothing displays
        # them yet (there is no Edit menu and no toast surface). Wrap them
        # when something shows them — that is also when their English copy
        # settles, which is the order the i18n notes ask for.
        if not after_ids:
            label = "Clear Playlist"
        elif len(after_ids) < len(before_ids):
            label = "Remove Tracks"
        elif len(after_ids) > len(before_ids):
            label = "Add Tracks"
        else:
            label = "Reorder Playlist"
        library = self._library

        def restore() -> None:
            if library.get_node(node_id) is not None:
                library.restore_items(node_id, before)

        self._undo.push(label, restore)

    def _update_now_playing(self) -> None:
        """Show the loaded track's filename above the slicer, or hide the line.

        Also the single place the Compatible Tracks seed follows from: this
        runs wherever the loaded track changes — played, removed from under
        the player, or cleared — and Stop is deliberately not one of those,
        since the track stays loaded and the matches stay useful.
        """
        self._compat_panel.set_seed_path(self._playing_path)
        if self._playing_path:
            self._now_playing_label.setText(
                self.tr("Playing: {0}").format(Path(self._playing_path).name)
            )
            self._now_playing_label.show()
        else:
            self._now_playing_label.hide()

    def _update_context_label(self) -> None:
        if self._library is None:
            self._context_label.setText("")
            return
        if self._search_active:
            query = self._search_field.text().strip()
            self._context_label.setText("› " + self.tr("Search: {0}").format(query))
            return
        if self._loaded_node_id == SCRATCH_NODE_ID:
            name = self.tr("Scratch")
        else:
            node = self._library.get_node(self._loaded_node_id)
            name = node.name if node is not None else ""
        self._context_label.setText(f"› {name}")

    def _on_save_playlist(self) -> None:
        """Save the visible list as a new named playlist at the top of the tree."""
        if self._library is None:
            return
        if not self._playlist:
            QMessageBox.information(
                self,
                self.tr("Save Playlist"),
                self.tr("The playlist is empty — add some tracks first."),
            )
            return
        name, ok = QInputDialog.getText(
            self, self.tr("Save Playlist"), self.tr("Playlist name:")
        )
        name = name.strip()
        if not ok or not name:
            return
        self._persist_playlist()  # library rows current before copying
        track_ids = self._library.get_item_track_ids(self._loaded_node_id)
        node_id = self._library.create_playlist(name)
        self._library.set_items(node_id, track_ids)
        self.playlist_saved.emit(node_id)

    # ── Search-as-scope (§9) ────────────────────────────────────

    def _on_search_text_changed(self, text: str) -> None:
        if text.strip():
            self._search_timer.start()
        else:
            self._search_timer.stop()
            self._exit_search()

    def _show_scope_menu(self) -> None:
        """Open the scope menu just below its button."""
        self._scope_menu.exec(
            self._scope_btn.mapToGlobal(self._scope_btn.rect().bottomLeft())
        )

    def _apply_search_scope(self, scope_all: bool) -> None:
        """Reflect a scope everywhere it shows: state, glyph, tooltip,
        checked menu action, and the field's placeholder."""
        self._search_scope_all = scope_all
        self._scope_actions[scope_all].setChecked(True)
        self._scope_btn.setIcon(
            self._scope_all_icon if scope_all else self._scope_this_icon
        )
        self._scope_btn.setToolTip(
            self.tr("Search scope: {0}").format(self._scope_actions[scope_all].text())
        )
        self._search_field.setPlaceholderText(
            self.tr("Search all playlists…")
            if scope_all
            else self.tr("Search this playlist…")
        )

    def _select_search_scope(self, scope_all: bool) -> None:
        self._apply_search_scope(scope_all)
        if self._search_field.text().strip():
            self._search_timer.stop()
            self._run_search()

    def _run_search(self) -> None:
        query = self._search_field.text().strip()
        if not query or self._library is None:
            return
        if not self._search_active:
            self._search_active = True
            self._base_entries = self._playlist
            # Search results take no drops: internal reorder has no order to
            # persist, and dropped files have no defined destination here.
            self._table.setAcceptDrops(False)
            self._table.set_placeholder(self.tr("No matching tracks"))
            self._save_btn.setEnabled(False)
            self._clear_btn.setEnabled(False)
        counts: list[int] | None = None
        tooltips: list[str] | None = None
        track_ids: list[int] | None = None
        capped = False
        if self._search_scope_all:
            ids = self._library.search(query, limit=_SEARCH_LIMIT + 1)
            capped = len(ids) > _SEARCH_LIMIT
            found = self._library.get_tracks(ids[:_SEARCH_LIMIT])
            # A track already in the loaded list reuses that entry, keeping
            # year (the one displayed field with no library column) — and
            # letting inline edits flow back to the loaded list for free.
            by_path = {e.file_path: e for e in self._base_entries or []}
            entries = [
                by_path.get(t.path) or self._entry_from_track(t) for t in found
            ]
            track_ids = [t.id for t in found]
            count_map = self._library.membership_counts(track_ids)
            counts = [count_map.get(t.id, 0) for t in found]
            tooltips = [
                "\n".join(
                    n.name for n in self._library.playlists_containing(t.id)
                )
                for t in found
            ]
        else:
            entries = [
                e
                for e in self._base_entries or []
                if self._entry_matches(e, query)
            ]
        self._playlist = entries
        self._search_counts = counts
        self._search_tooltips = tooltips
        self._search_track_ids = track_ids
        self._search_capped = capped
        self._set_count_column(counts is not None)
        self._relink_playing_row()
        self._rebuild_table()
        self._update_stats()
        self._update_transport_state()
        self._update_context_label()
        self._update_search_highlight()

    def _exit_search(self) -> None:
        """Clear the search and put the loaded playlist back on screen."""
        if not self._search_active:
            return
        entries = self._base_entries or []
        self._dismiss_search()
        self._playlist = entries
        self._relink_playing_row()
        self._rebuild_table()
        self._update_stats()
        self._update_transport_state()
        self._update_context_label()

    def _dismiss_search(self) -> None:
        """Tear down the search UI without restoring the previous list (the
        caller installs a new one — load_node — or _exit_search restores)."""
        self._search_timer.stop()
        self._search_field.blockSignals(True)
        self._search_field.clear()
        self._search_field.blockSignals(False)
        self._search_active = False
        self._base_entries = None
        self._search_counts = None
        self._search_tooltips = None
        self._search_track_ids = None
        self._search_capped = False
        self._set_count_column(False)
        self._table.setAcceptDrops(True)
        self._table.set_placeholder(None)
        self._save_btn.setEnabled(True)
        self._clear_btn.setEnabled(True)
        self._update_search_highlight()  # nothing to light — clears the tree

    def _set_count_column(self, counts: bool) -> None:
        """Swap column 0 between row numbers ('#') and membership counts
        ('Playlists') — the one column All-playlists search needs that
        playlist view doesn't (§9)."""
        if counts == self._count_column_active:
            return
        self._count_column_active = counts
        header_item = self._table.horizontalHeaderItem(0)
        if counts:
            self._num_col_width = self._table.columnWidth(0)
            header_item.setText(self.tr("Playlists"))
            self._table.setColumnWidth(0, self._playlists_col_width)
        else:
            header_item.setText(self.tr("#"))
            self._table.setColumnWidth(0, self._num_col_width)
            # '#' is back at its own width, so a layout change the search
            # suppressed is now safe to persist.
            if self._columns_changed_while_searching:
                self._columns_changed_while_searching = False
                self._col_save_timer.start()

    def _relink_playing_row(self) -> None:
        """Point _current_index at the engine's track in the visible list
        (-1 when this list doesn't contain it)."""
        if self._playing_path is None:
            self._current_index = -1
            return
        self._current_index = next(
            (
                i
                for i, e in enumerate(self._playlist)
                if e.file_path == self._playing_path
            ),
            -1,
        )

    def _entry_from_track(self, track) -> PlaylistEntry:
        """A displayable entry for a library track that isn't in the loaded
        list. Every field comes from the row — no file is opened for a search
        result, however many of them come back."""
        bpm = str(int(round(track.bpm))) if track.bpm else ""
        duration = (
            self._format_time(int(track.duration * 1000)) if track.duration else ""
        )
        return PlaylistEntry(
            file_path=track.path,
            display_name=track.filename,
            artist=track.artist,
            title=track.title,
            album=track.album,
            genre=track.genre,
            bpm=bpm,
            key=track.key,
            comment=track.comment,
            duration=duration,
            year=track.year or "",
            track_number=track.track_number or "",
            label=track.label or "",
            bitrate=str(track.bitrate) if track.bitrate else "",
            energy=str(track.energy) if track.energy else "",
        )

    @staticmethod
    def _entry_matches(entry: PlaylistEntry, query: str) -> bool:
        """This-playlist scope: substring-match every word against the row's
        visible text (search what you see)."""
        blob = " ".join(
            (
                entry.display_name,
                entry.artist,
                entry.title,
                entry.comment,
                entry.key,
                entry.year,
            )
        ).lower()
        return all(token in blob for token in query.lower().split())

    def _update_search_highlight(self) -> None:
        """Light the sidebar trail for the selected search result(s) (§10).

        Union across a multi-select — the question is "where does any of
        this live". Each lit playlist adds one to every ancestor folder's
        count. Emits empty sets whenever there is nothing to light (search
        over, This-playlist scope, no selection).
        """
        playlist_ids: set[int] = set()
        folder_counts: dict[int, int] = {}
        if (
            self._search_active
            and self._search_track_ids is not None
            and self._library is not None
        ):
            rows = {idx.row() for idx in self._table.selectionModel().selectedRows()}
            track_ids = {
                self._search_track_ids[r]
                for r in rows
                if 0 <= r < len(self._search_track_ids)
            }
            for track_id in track_ids:
                playlist_ids |= {
                    n.id for n in self._library.playlists_containing(track_id)
                }
            for playlist_id in playlist_ids:
                for ancestor in self._library.ancestor_ids(playlist_id):
                    folder_counts[ancestor] = folder_counts.get(ancestor, 0) + 1
        self.tree_highlight_changed.emit(playlist_ids, folder_counts)

    def _refresh_library_track(self, entry: PlaylistEntry) -> None:
        """Write an edited search row's tags to its library track (edits reach
        every playlist holding the track via the track_id indirection)."""
        if self._library is None:
            return
        track = self._library.get_track_by_path(entry.file_path)
        if track is None:
            return
        self._library.update_track_tags(
            track.id,
            artist=entry.artist,
            title=entry.title,
            comment=entry.comment,
            bpm=_parse_bpm(entry.bpm),
            key=entry.key,
            energy=_parse_int(entry.energy),
        )

    # ── Table management ────────────────────────────────────────

    # ── Missing files (step 10) ─────────────────────────────────

    def _is_missing(self, file_path: str) -> bool:
        """Whether this track's file is gone, memoised for the rebuild."""
        cached = self._missing_cache.get(file_path)
        if cached is None:
            cached = not Path(file_path).is_file()
            self._missing_cache[file_path] = cached
        return cached

    def _refresh_missing_marks(self) -> None:
        """Re-stat the visible rows; rebuild only if a mark actually changed.

        The rebuild is conditional because it is not free (and it re-reads
        the current row highlight); the common case is that nothing moved
        and this is just a handful of stat calls.
        """
        before = {e.file_path: self._missing_cache.get(e.file_path) for e in self._playlist}
        self._missing_cache = {}
        if any(before[path] != self._is_missing(path) for path in before):
            self._rebuild_table()

    def _locate_missing(self, row: int) -> None:
        """Open the relocate dialog for a row whose file has gone (§1)."""
        if not (0 <= row < len(self._playlist)) or self._library is None:
            return
        entry = self._playlist[row]
        dialog = RelocateDialog(self._library, entry.file_path, self)
        dialog.exec()
        if dialog.new_path is None and not dialog.relinked:
            return
        self._missing_cache = {}
        # The library rows moved under us, so the visible list has to come
        # from the library again — otherwise the next auto-save would write
        # the old, missing paths straight back in via add_track().
        if dialog.new_path is not None:
            entry.file_path = dialog.new_path
            entry.display_name = Path(dialog.new_path).name
        if self._search_active:
            self._run_search()
        elif dialog.relinked:
            self.load_node(self._loaded_node_id)
        else:
            # No library row existed for the old path (so nothing was
            # relinked); the visible entry now points at the new file and
            # auto-save writes that through.
            self._rebuild_table()
            self._persist_playlist()

    def _rebuild_table(self) -> None:
        self._rebuilding = True
        try:
            self._rebuild_table_rows()
        finally:
            self._rebuilding = False
        # Different rows are on screen now; cached thumbnails were applied as
        # the rows were built, so this only reads what is genuinely new.
        self._schedule_artwork_load()

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
            self._missing_rows = set()
            for row, entry in enumerate(self._playlist):
                # All-playlists search: column 0 is the membership count, with
                # the playlist names as its tooltip (§10 — the answer without
                # touching the tree). Otherwise it's the row number.
                if self._search_counts is not None and row < len(self._search_counts):
                    num_item = QTableWidgetItem(str(self._search_counts[row]))
                    if self._search_tooltips is not None:
                        num_item.setToolTip(self._search_tooltips[row])
                else:
                    num_item = QTableWidgetItem(str(row + 1))
                num_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                num_item.setFlags(non_drop_flags)
                self._table.setItem(row, 0, num_item)

                # A missing file is marked in the Name column: "!" in front
                # of the name, the row dimmed by _highlight_current_row, and
                # the last known path in the tooltip. The entry's index rides
                # along in UserRole because the marker makes the cell text an
                # unreliable way to identify the row again after a drag —
                # see _sync_playlist_from_table.
                missing = self._is_missing(entry.file_path)
                if missing:
                    self._missing_rows.add(row)
                name_item = QTableWidgetItem(
                    f"! {entry.display_name}" if missing else entry.display_name
                )
                name_item.setData(Qt.ItemDataRole.UserRole, row)
                if missing:
                    name_item.setToolTip(
                        self.tr("File not found:\n{0}").format(entry.file_path)
                    )
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

                # The optional columns. Built whether or not they are showing:
                # they cost a QTableWidgetItem each, and populating them here
                # means unhiding one displays its data immediately rather than
                # waiting for the next rebuild. Read-only for now — the
                # editable set above is a deliberate list, and widening it is
                # its own conversation.
                for col, attribute in self._OPTIONAL_COLUMNS:
                    item = QTableWidgetItem(
                        getattr(entry, attribute) if attribute else ""
                    )
                    item.setFlags(non_drop_flags)
                    if col == self._ARTWORK_COLUMN:
                        thumb = self._art_cache.get(self._art_key(entry.file_path))
                        if thumb is not None and not thumb.isNull():
                            item.setData(Qt.ItemDataRole.DecorationRole, thumb)
                    self._table.setItem(row, col, item)
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
                # A missing file reads as dimmed, except while it is the
                # playing row: that highlight is about where playback is,
                # and losing it would be the more confusing of the two.
                is_missing = row in self._missing_rows
                for col in range(self._table.columnCount()):
                    item = self._table.item(row, col)
                    if item is None:
                        continue
                    if is_current:
                        item.setForeground(QColor(Theme.NEON_YELLOW))
                    elif is_missing:
                        item.setForeground(QColor(Theme.TEXT_DISABLED))
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

    def _show_vis_menu(self) -> None:
        """Open the visuals menu just below the eye button."""
        self._vis_menu.exec(
            self._vis_button.mapToGlobal(self._vis_button.rect().bottomLeft())
        )

    def _select_vis_mode(self, mode: str) -> None:
        """Remember the chosen visual and persist it (like Edit Lock)."""
        if mode not in self._vis_actions:
            return
        self._vis_actions[mode].setChecked(True)
        self._vis_mode = mode
        cfg = load_config()
        if cfg.visualization_mode != mode:
            cfg.visualization_mode = mode
            save_config(cfg)
        self._apply_vis_mode()

    # ── Compatible Tracks ────────────────────────────────────────

    def _on_compat_toggled(self, open_: bool) -> None:
        """Split the playlist area with the Compatible Tracks panel, or don't."""
        self._compat_panel.setVisible(open_)
        if not open_:
            # A panel the user has just closed must not still be making noise.
            self._compat_panel.stop_audition()
        if open_:
            # The seed only matters while the panel is showing, so it is set
            # here as well as on play: opening mid-track must not wait for the
            # next one.
            self._compat_panel.set_seed_path(self._playing_path)
            self._apply_compat_sizes()
        self._sync_compat_tooltip()
        self.compat_panel_toggled.emit(open_)

    def _apply_compat_sizes(self) -> None:
        """Give the panel its remembered width, clamped to a sane share."""
        total = sum(self._playlist_splitter.sizes())
        if total <= 0:
            return
        width = max(
            self._compat_panel.minimum_useful_width(),
            min(self._compat_width, int(total * _COMPAT_MAX_SHARE)),
        )
        self._playlist_splitter.setSizes([max(0, total - width), width])

    def _on_compat_splitter_moved(self, _pos: int, _index: int) -> None:
        """Remember the width the user dragged to (session only)."""
        if self.compat_panel_open:
            self._compat_width = self._playlist_splitter.sizes()[1]

    def _sync_compat_tooltip(self) -> None:
        """A toggle's tooltip says what the NEXT click does (house rule)."""
        self._compat_button.setToolTip(
            self.tr("Hide tracks that mix with the playing track")
            if self._compat_button.isChecked()
            else self.tr("Show tracks that mix with the playing track")
        )

    def _on_audition_started(self, _path: str) -> None:
        """An audition began — stop the main player and leave it stopped.

        Full stop rather than pause, and deliberately no resume when the
        audition ends (confirmed 2026-08-12): the DJ asked to hear the other
        track, and having the previous one come back unbidden mid-set is
        worse than having to press play.
        """
        self._on_stop()

    def _on_compat_track_activated(self, path: str) -> None:
        """Double-click in the panel: add the track to the visible playlist.

        Only the path is passed on, so the tags are read from the file like
        any other add — the library row that matched it may be older than the
        file, and this is the same route a drop from Finder takes.
        """
        self.add_tracks([{"file_path": path, "display_name": Path(path).name}])

    def compat_panel_min_width(self) -> int:
        """Extra width the window needs while the panel is open, else 0.

        Measured from the panel's own columns rather than assumed — the same
        rule the Convert row's format selectors are sized by.
        """
        if not self.compat_panel_open:
            return 0
        return (
            self._compat_panel.minimum_useful_width()
            + self._playlist_splitter.handleWidth()
        )

    @property
    def compat_panel_open(self) -> bool:
        return self._compat_button.isChecked()

    def set_key_notation(self, notation: str) -> None:
        """Follow the Settings key-notation choice in the compatible list."""
        self._compat_panel.set_key_notation(notation)

    def set_visualizations_enabled(self, enabled: bool) -> None:
        """Show/hide the visuals selector to match the Settings master switch."""
        self._visualizations_enabled = enabled
        self._vis_button.setVisible(enabled)
        self._apply_vis_mode()

    def _apply_vis_mode(self) -> None:
        """Bring the active visual in line with the mode + master switch."""
        self._refresh_backdrop()
        popout = self._visualizations_enabled and self._vis_mode in POPOUT_MODES
        if popout:
            if self._vis_window is None:
                self._vis_window = VisualizerWindow(self._engine, self)
                self._vis_window.set_color(self._waveform_color)
                self._vis_window.closed.connect(self._on_vis_window_closed)
            self._vis_window.set_mode(self._vis_mode)
            self._vis_window.show()
            self._vis_window.raise_()
        elif self._vis_window is not None and self._vis_window.isVisible():
            self._vis_closing = True
            try:
                self._vis_window.close()
            finally:
                self._vis_closing = False

    def _on_vis_window_closed(self) -> None:
        """User dismissed the popout: drop the selector back to Off."""
        if self._vis_closing or self._vis_mode not in POPOUT_MODES:
            return
        self._select_vis_mode("off")

    # ── Backdrop waveform (visualizations) ─────────────────────

    def _on_engine_source_changed(self, pcm, sr: int) -> None:
        """A new track was loaded into the engine; retarget the backdrop."""
        self._backdrop_src = (pcm, sr)
        self._backdrop_env = None  # stale — belongs to the previous track
        self._backdrop_env_path = None
        self._refresh_backdrop()

    def _refresh_backdrop(self) -> None:
        """Show/hide the playlist backdrop to match mode, switch, and track."""
        enabled = self._visualizations_enabled
        if enabled and self._vis_mode in _BACKDROP_VIS_MAP:
            # Visualizer backdrop: frames arrive from the tick timer; the
            # stale envelope/image (if any) clears on the first frame.
            if self._backdrop_renderer is None:
                self._backdrop_renderer = VisRenderer()
            self._backdrop_renderer.set_mode(_BACKDROP_VIS_MAP[self._vis_mode])
            self._backdrop_renderer.set_color(self._waveform_color)
            if self._engine.is_playing():
                self._vis_decay = _VIS_DECAY_FRAMES
                self._vis_tick_timer.start()
            else:
                self._table.clear_backdrop()
            return
        self._vis_tick_timer.stop()
        if not enabled or self._vis_mode != "backdrop" or self._backdrop_src is None:
            self._table.clear_backdrop()
            return
        path = self._current_path()
        if self._backdrop_env is None or self._backdrop_env_path != path:
            pcm, sr = self._backdrop_src
            try:
                self._backdrop_env = timed_envelope(pcm, sr)
            except ValueError:
                self._table.clear_backdrop()
                return
            self._backdrop_env_path = path
        self._table.set_backdrop_envelope(*self._backdrop_env)

    def _on_vis_backdrop_tick(self) -> None:
        """Advance the visualizer backdrop one frame (30 fps while playing)."""
        if self._backdrop_renderer is None:
            self._vis_tick_timer.stop()
            return
        playing = self._engine.is_playing()
        samples = self._engine.recent_mono(FFT_SIZE) if playing else None
        image = self._backdrop_renderer.render(samples, self._engine.sample_rate())
        self._table.set_backdrop_image(image)
        if playing:
            self._vis_decay = _VIS_DECAY_FRAMES
        else:
            # Feed silence briefly so bars fall / fire burns down, then rest.
            self._vis_decay -= 1
            if self._vis_decay <= 0:
                self._vis_tick_timer.stop()

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
        # Refresh the library row so playlists/search see the edited tags.
        if self._search_active:
            # A search row isn't the loaded node's content: refresh its
            # library track directly — never persist the result list.
            self._refresh_library_track(entry)
            # An out-of-list result reused the loaded list's entry object when
            # the paths matched, so the loaded list is already in sync.
        else:
            self._persist_playlist()

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
            entry.album = meta.album or ""
            entry.genre = meta.genre or ""
            entry.bpm = str(int(round(meta.bpm))) if meta.bpm else ""
            entry.key = meta.key or ""
            entry.comment = meta.comment or ""
            entry.year = str(meta.year) if meta.year else ""
            entry.track_number = str(meta.track_number) if meta.track_number else ""
            entry.label = meta.label or ""
            entry.bitrate = str(meta.bitrate) if meta.bitrate else ""
            entry.energy = str(meta.energy) if meta.energy else ""
            if meta.duration:
                entry.duration = self._format_time(int(meta.duration * 1000))
            changed = True
        if changed:
            self._rebuild_table()  # sets _rebuilding, so itemChanged stays quiet

    def _sync_playlist_from_table(self) -> None:
        """Rebuild the internal playlist list from table row order after drag-drop."""
        new_playlist: list[PlaylistEntry] = []
        taken: set[int] = set()
        old_current_path = self._playing_path

        # Rows carry their pre-drag index in UserRole (the drop handler moves
        # the QTableWidgetItems themselves, so the role rides along). Matching
        # on that rather than on the displayed name keeps two copies of one
        # track distinct, and survives the "!" that marks a missing file.
        for row in range(self._table.rowCount()):
            name_item = self._table.item(row, 1)
            if name_item is None:
                continue
            index = name_item.data(Qt.ItemDataRole.UserRole)
            if isinstance(index, int) and 0 <= index < len(self._playlist):
                if index in taken:
                    continue  # a row Qt copied rather than moved
                taken.add(index)
                new_playlist.append(self._playlist[index])

        self._playlist = new_playlist

        # Update current index to follow the playing track
        if old_current_path:
            for i, entry in enumerate(self._playlist):
                if entry.file_path == old_current_path:
                    self._current_index = i
                    break

        self._rebuild_table()
        self._persist_playlist()

    def _update_stats(self) -> None:
        count = len(self._playlist)
        if self._search_active:
            if self._search_capped:
                text = self.tr("{0}+ results").format(_SEARCH_LIMIT)
            else:
                text = (
                    self.tr("{0} result").format(count)
                    if count == 1
                    else self.tr("{0} results").format(count)
                )
        else:
            text = (
                self.tr("{0} track").format(count)
                if count == 1
                else self.tr("{0} tracks").format(count)
            )
        self._stats_label.setText(text)

    # ── Column layout persistence ───────────────────────────────

    def _restore_column_state(self) -> None:
        """Apply the saved playlist column order/widths/visibility, if any.

        The awkward part is what a saved state does NOT contain. Qt accepts a
        nine-column state into this fifteen-column table — it returns True and
        applies the nine — but what happens to the six sections the state has
        never heard of is unspecified, and observably inconsistent: a bare
        QTableWidget has them **un-hidden** by the restore, while this panel's
        header keeps whatever flag it was given. Either way an upgrading user
        must not open the app to six columns nobody asked for.

        So neither behaviour is relied on. `player_column_count` records how
        many sections the saved state has an opinion about, and everything
        beyond that has its default visibility applied *after* the restore —
        which is correct whichever way Qt jumps.

        Worse, and the reason for `_normalize_header`: a header that has
        swallowed a shorter state is left internally inconsistent, and the
        state it *saves* afterwards cannot be restored at all. An upgrading
        user would therefore write a poisoned layout on their first run and
        lose it — along with anything they had done that session — on their
        second. Re-seating the header fixes it, keeping their widths.
        """
        header = self._table.horizontalHeader()
        self._apply_default_column_order()
        # Taken while the header is definitely healthy: fifteen sections, just
        # built, nothing restored into it yet.
        pristine = header.saveState()
        cfg = load_config()
        state = cfg.player_column_state
        migrating = bool(state) and (
            cfg.player_column_defaults_version < self._COLUMN_DEFAULTS_VERSION
        )
        if migrating:
            # The shipped layout changed, and a saved state would hide that
            # from everyone who has ever opened the app. Applied once: the
            # state is dropped, the defaults above stand, and the new version
            # is written back at the end so this never runs again.
            logger.info("Applying the new default player column layout (once)")
            state = ""
        covered = 0
        # Whether what is on screen is the shipped layout rather than a
        # restored one — true for a fresh install, for the migration above, and
        # for a state Qt refused, all of which end up on the defaults.
        self._default_columns_applied = True
        if state:
            restored = False
            try:
                restored = header.restoreState(
                    QByteArray.fromBase64(state.encode("ascii"))
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not restore player column layout: %s", exc)
            if restored:
                covered = cfg.player_column_count
                self._default_columns_applied = False
                if covered < self._table.columnCount():
                    self._normalize_header(pristine)
            else:
                # A refused state has told us nothing, and may have been
                # partly applied on the way to refusing. Put the header back
                # the way it was rather than leaving it half-restored.
                logger.warning("Saved player column layout was refused; using defaults")
                header.restoreState(pristine)
                for col, width in self._default_column_widths.items():
                    self._table.setColumnWidth(col, width)
        for col, _ in self._OPTIONAL_COLUMNS:
            if col >= covered:
                self._table.setColumnHidden(
                    col, col not in self._DEFAULT_SHOWN_OPTIONAL
                )
        # Floor the word-fit columns so a previously-saved (or freshly dragged)
        # narrow width never reopens with the BPM/Key/Year/Duration header word
        # clipped. Wider saved widths are kept; the user can still widen freely.
        for col, min_width in self._word_fit_widths.items():
            if self._table.columnWidth(col) < min_width:
                self._table.setColumnWidth(col, min_width)
        if migrating:
            # Written back now, not at the next column change: a user who never
            # touches the header would otherwise be migrated on every launch,
            # and each one would throw away the layout of the session before.
            self._save_column_state()

    def _apply_default_column_order(self) -> None:
        """Put the sections in the shipped visual order.

        Left to right, so every move lands against an already-settled prefix —
        the same reason _normalize_header applies its order that way. Called
        before any saved state is restored, so it is what a fresh install (or
        a refused state) is left wearing, and what a restore overwrites.
        """
        header = self._table.horizontalHeader()
        for target, col in enumerate(self._DEFAULT_COLUMN_ORDER):
            current = header.visualIndex(col)
            if current != target:
                header.moveSection(current, target)

    # ── Artwork thumbnails ──────────────────────────────────────

    # Enough thumbnails for a long scroll without the cache itself becoming a
    # memory question: a few hundred strips of ~72×24 is a couple of megabytes.
    _ART_CACHE_MAX = 512
    # Breathing room between the visible band and the row's edges.
    _ART_ROW_INSET = 6
    # The cover is scaled to this many times the row's height and only its top
    # 1/scale is kept, so a row shows a wide band off the top of the sleeve
    # rather than a postage stamp of the whole thing. Changing it changes both
    # ends at once: bigger art, and a proportionally shallower slice of it.
    _ART_STRIP_SCALE = 3
    # Gap either side of the band inside its column, so the strip never runs
    # into the next column's text.
    _ART_COLUMN_PAD = 8

    def _art_key(self, path: str) -> tuple[str, float]:
        """Cache key. The mtime is in it so re-tagging a file in another app
        shows the new cover rather than the one we happened to read first."""
        try:
            return (path, Path(path).stat().st_mtime)
        except OSError:
            return (path, 0.0)

    def _text_row_height(self) -> int:
        """The row height the current text size asks for, on its own.

        Deliberately computed from the captured base rather than read back from
        the vertical header: in the Full artwork view the header holds a height
        derived from the art, which is in turn derived from *this* — reading it
        back would feed the art its own output and grow the rows on every pass.
        """
        return round(
            self._base_row_height
            * TEXT_SIZES[self._text_size]
            / TEXT_SIZES[DEFAULT_TEXT_SIZE]
        )

    def _art_strip_height(self) -> int:
        """Height of the band cut from the cover: a text row, less breathing room.

        Note this stays the band's height in every view, including Full — it is
        what the cover is scaled *from* (times _ART_STRIP_SCALE), so keeping it
        tied to the text row alone is what makes the scaled cover the same size
        in all three views, and the column the same width.
        """
        return max(8, self._text_row_height() - self._ART_ROW_INSET)

    def _art_size(self) -> int:
        """Edge the whole cover is scaled to before a band is cut out of it."""
        return self._art_strip_height() * self._ART_STRIP_SCALE

    def _art_paint_height(self) -> int:
        """How much of that cover a row actually shows: all of it, or one band."""
        if self._art_view == "full":
            return self._art_size()
        return self._art_strip_height()

    def _art_crop_height(self) -> int | None:
        """The crop to ask the reader for. None means "keep the whole square"."""
        return None if self._art_view == "full" else self._art_strip_height()

    def _row_height(self) -> int:
        """The row height to apply: the text's, unless Full art needs more.

        Only Full changes it, and only while the column is actually showing —
        a hidden Art column must not leave the playlist wearing three-row rows
        for artwork nobody can see.
        """
        height = self._text_row_height()
        if self._art_view == "full" and self._artwork_showing():
            height = max(height, self._art_size() + self._ART_ROW_INSET)
        return height

    def _apply_row_height(self) -> None:
        """Push the computed row height onto the table.

        Rows do not follow the font on their own — they sit at the vertical
        header's default section size and nothing re-measures them. Scaling it
        explicitly (rather than resizeRowsToContents, which sizes to the
        delegate hint plus the QSS padding and made every row half again as
        tall at the *current* size) keeps Medium pixel-identical to today.
        """
        self._table.verticalHeader().setDefaultSectionSize(self._row_height())
        # A table pinned to N rows for the slicer was sized against the old
        # height, so it now shows the wrong number of them.
        if self._table.maximumHeight() < 16_777_215:
            self._apply_table_height(True)

    def _artwork_showing(self) -> bool:
        return not self._table.isColumnHidden(self._ARTWORK_COLUMN)

    def _apply_art_icon_size(self) -> None:
        """Size the view's icons — and the column — to the band.

        The view's icon size is what actually bounds a decoration, so a strip
        scaled to 72×24 still paints at Qt's 16px default without this; and in
        the band views it is deliberately not square, because the band is three
        rows of cover wide and one row tall. In Full it is square, and the
        column width is unchanged — the cover is scaled the same in all three
        views, so switching between them never reflows the columns.

        The column is only ever widened, never narrowed: a band cut off
        halfway looks like a bug, but a user who has dragged the column wider
        than the art meant it. A hidden section reports a width of 0 whatever
        it is set to, so for a column nobody has opened yet the widening is
        really the default width, which _set_column_visible applies on reveal.
        """
        width, height = self._art_size(), self._art_paint_height()
        self._table.setIconSize(QSize(width, height))
        # The band's width, or the header word's if that is wider — "Art" is
        # three letters and its translations are not (ja アートワーク wants 95px
        # of the band's 80), and a column sized purely from the art clips them.
        column = max(
            width + self._ART_COLUMN_PAD, self._header_fit_width(self._ARTWORK_COLUMN)
        )
        self._default_column_widths[self._ARTWORK_COLUMN] = column
        if self._table.columnWidth(self._ARTWORK_COLUMN) < column:
            self._table.setColumnWidth(self._ARTWORK_COLUMN, column)

    def _schedule_artwork_load(self) -> None:
        """Ask for the visible rows' art, debounced.

        Debounced because the triggers are a scrollbar and a resize, which fire
        continuously: without it a drag down a long playlist would start a
        thread per pixel of travel.
        """
        if not self._artwork_showing():
            return
        self._art_timer.start()

    def _visible_rows(self) -> range:
        """The rows currently on screen, as a range. Empty if the table isn't
        laid out yet — asking Qt before that returns -1 for both ends."""
        viewport = self._table.viewport()
        first = self._table.rowAt(0)
        last = self._table.rowAt(viewport.height() - 1)
        if first < 0:
            return range(0)
        if last < 0:  # the last row is taller than the remaining viewport
            last = self._table.rowCount() - 1
        return range(first, min(last, self._table.rowCount() - 1) + 1)

    def _load_visible_artwork(self) -> None:
        """Read art for whatever is on screen and isn't already known."""
        if not self._artwork_showing() or not self._playlist:
            return
        size = self._art_size()
        if (size, self._art_view) != self._art_size_loaded:
            # A text-size change invalidates every scaled thumbnail and a view
            # change every crop, but neither invalidates the knowledge of which
            # files have no art at all.
            self._art_cache.clear()
            self._art_size_loaded = (size, self._art_view)
        wanted = []
        for row in self._visible_rows():
            if not (0 <= row < len(self._playlist)):
                continue
            path = self._playlist[row].file_path
            key = self._art_key(path)
            if key in self._art_cache or key in self._art_missing:
                continue
            if path not in wanted:
                wanted.append(path)
        if not wanted:
            return
        self._start_artwork_worker(wanted, size)

    def _start_artwork_worker(self, paths: list[str], size: int) -> None:
        """Run one reader at a time; a new request cancels the one in flight.

        Cancelling rather than queueing because the old request is by
        definition for rows the user has already scrolled past.
        """
        self._cancel_artwork_worker()
        worker = ArtworkWorker(paths, size, self._art_crop_height(), self._art_view)
        thread = ArtworkThread(worker)
        self._art_worker = worker
        self._art_thread = thread
        # Same reason as the decode workers: the previous run's deleteLater may
        # still be queued when these attributes are reassigned.
        keep_alive(self._thread_keep, thread, worker)
        worker.loaded.connect(self._on_artwork_loaded)
        worker.empty.connect(self._on_artwork_missing)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread: self._on_artwork_thread_finished(t))
        thread.start()

    def _cancel_artwork_worker(self) -> None:
        """Ask the reader in flight to stop, if there is still one to ask.

        Guarded by isValid: the attribute can outlive the C++ object it names
        — deleteLater has run but keep_alive still holds the wrapper — and
        calling into that is not a no-op, it is a crash.
        """
        worker = self._art_worker
        if worker is not None and shiboken6.isValid(worker):
            worker.cancel()

    def _on_artwork_thread_finished(self, thread) -> None:
        """Drop the references, unless a newer request has already taken them.

        Without the check, the *previous* reader finishing (which is normal —
        it was just cancelled by the new one) would clear the new reader's
        references out from under it.
        """
        if self._art_thread is thread:
            self._art_thread = None
            self._art_worker = None

    def _on_artwork_loaded(self, path: str, image) -> None:
        """A thumbnail arrived: cache it and paint it into every matching row."""
        pixmap = QPixmap.fromImage(image)
        key = self._art_key(path)
        self._art_cache[key] = pixmap
        while len(self._art_cache) > self._ART_CACHE_MAX:
            self._art_cache.pop(next(iter(self._art_cache)))
        self._apply_artwork(path, pixmap)

    def _on_artwork_missing(self, path: str) -> None:
        """Remember that this file has no cover, so scrolling past it again
        doesn't queue the same fruitless tag read."""
        self._art_missing.add(self._art_key(path))

    def _apply_artwork(self, path: str, pixmap: QPixmap) -> None:
        """Set the decoration on every visible row showing this file."""
        self._table.blockSignals(True)
        try:
            for row, entry in enumerate(self._playlist):
                if entry.file_path != path:
                    continue
                item = self._table.item(row, self._ARTWORK_COLUMN)
                if item is not None:
                    item.setData(Qt.ItemDataRole.DecorationRole, pixmap)
        finally:
            self._table.blockSignals(False)

    def _table_stylesheet(self) -> str:
        """The playlist table's inline QSS — the one and only owner of it.

        Both the row padding and the text size live here on purpose. The app
        stylesheet sets a global ``QWidget { font-size: 14px }``, which beats a
        plain ``setFont()`` on the table, so the size has to be QSS; and since
        a second ``setStyleSheet`` would replace this one rather than add to
        it, there is a single sheet built in a single place.
        """
        px = TEXT_SIZES[self._text_size]
        return (
            "QTableWidget { background-color: transparent; border: none;"
            f" font-size: {px}px; }}"
            # On QHeaderView itself, not on ::section. A sub-control rule is
            # honoured when the section is *painted* but never reaches
            # header.font() — and _title_font() (which the column widths are
            # measured from) reads exactly that. Styling the sub-control alone
            # therefore drew a larger header word and kept the old, too-narrow
            # column to put it in.
            f"QHeaderView {{ font-size: {px}px; }}"
            f"QHeaderView::section {{ background-color: {Theme.BG_MEDIUM}; }}"
            "QTableWidget::item { padding: 8px 0px; }"
            # The inline edit field otherwise inherits the global pill-shaped
            # QLineEdit (8px padding + rounded border), which clips the text in
            # a short row. Flatten it to a plain rectangle that fills the cell.
            "QTableWidget QLineEdit {"
            f" border: 1px solid {Theme.NEON_YELLOW}; border-radius: 0px;"
            f" background-color: #1e1e1e; color: {Theme.TEXT_PRIMARY};"
            f" padding: 0px 4px; margin: 0px; font-size: {px}px;"
            f" selection-background-color: {Theme.NEON_YELLOW}; selection-color: {Theme.BG_DARK}; }}"
        )

    def set_text_size(self, size: str) -> None:
        """Set the playlist's text size preset, live. Unknown names are ignored.

        Applied immediately rather than at restart: the theme needs a restart
        because widgets cache palette colours, and nothing here does.
        """
        if size not in TEXT_SIZES or size == self._text_size:
            return
        self._text_size = size
        self._table.setStyleSheet(self._table_stylesheet())
        self._apply_row_height()
        self._remeasure_word_fit_widths()
        # The artwork is scaled from the text row, so every cached thumbnail is
        # now the wrong size; _load_visible_artwork notices and re-reads.
        self._apply_art_icon_size()
        self._schedule_artwork_load()

    def set_artwork_view(self, view: str) -> None:
        """Set which part of the cover the Art column shows, live.

        Unknown names are ignored, so a config from a future build cannot leave
        the column showing nothing.
        """
        if view not in ARTWORK_VIEWS or view == self._art_view:
            return
        self._art_view = view
        # Full needs taller rows and the band views need them back, so the row
        # height is re-applied even though the text size has not moved.
        self._apply_row_height()
        self._apply_art_icon_size()
        # Every cached image is a crop that is no longer the one being asked
        # for; the reload is what actually repaints the column.
        self._schedule_artwork_load()

    def _remeasure_word_fit_widths(self) -> None:
        """Re-measure the columns sized to fit their own header word.

        ensurePolished() first: the width has to be measured with the font the
        header will actually paint with, and the inline sheet has only just
        changed. Columns the user has widened past the new minimum keep their
        width — this only ever raises a floor.
        """
        header = self._table.horizontalHeader()
        header.ensurePolished()
        header_fm = QFontMetrics(header._title_font())
        for col in list(self._word_fit_widths):
            item = self._table.horizontalHeaderItem(col)
            if item is None:
                continue
            width = (
                header_fm.horizontalAdvance(item.text())
                + 2 * SeparatorHeaderView._TEXT_PAD
                + 4
            )
            self._word_fit_widths[col] = width
            self._default_column_widths[col] = width
            if self._table.columnWidth(col) < width:
                self._table.setColumnWidth(col, width)
        self._apply_header_fit_floor(header_fm)

    def _header_fit_width(self, col: int, header_fm: QFontMetrics | None = None) -> int:
        """Width at which column ``col`` shows its whole header word.

        The same measurement the word-fit columns are built from, so the two
        cannot drift apart. Measure with the header's own font, not the
        table's: `_title_font` is what a section is painted with, and QSS
        sets it on the header rather than on the view.
        """
        item = self._table.horizontalHeaderItem(col)
        if item is None:
            return 0
        if header_fm is None:
            header = self._table.horizontalHeader()
            header.ensurePolished()
            header_fm = QFontMetrics(header._title_font())
        return (
            header_fm.horizontalAdvance(item.text())
            + 2 * SeparatorHeaderView._TEXT_PAD
            + 4
        )

    def _apply_header_fit_floor(self, header_fm: QFontMetrics | None = None) -> None:
        """Widen any base default that its own translated header outgrows.

        The base widths were measured against the English labels, so a longer
        translation opened clipped in every language that has one — ru "Номер
        трека" wants 97px of Track #'s 70, and Bitrate, Art and Track # clip in
        six languages between them. Recomputed from `_BASE_COLUMN_WIDTHS` each
        time rather than raised in place, so a text-size change that makes the
        header font *smaller* gives the width back.

        Only ever widens, so English is unchanged, and a visible column the
        user has narrowed below its word is pushed back out — the same
        guarantee `_word_fit_widths` gives BPM and Key. A hidden section
        reports a width of 0 whatever it is set to, so it is left to
        `_set_column_visible`, which applies the default on reveal.
        """
        for col, base in self._BASE_COLUMN_WIDTHS.items():
            fit = self._header_fit_width(col, header_fm)
            self._default_column_widths[col] = max(base, fit)
            if (
                not self._table.isColumnHidden(col)
                and 0 < self._table.columnWidth(col) < fit
            ):
                self._table.setColumnWidth(col, fit)

    def _normalize_header(self, pristine: QByteArray) -> None:
        """Re-seat the header after it restored a state shorter than itself.

        Qt applies such a state — the widths and order really are right
        afterwards — but leaves the section bookkeeping inconsistent, and the
        state saved from that header is then refused by `restoreState`. The
        layout is therefore copied off the header, the header is put back to a
        known-good shape, and the layout is applied again through the ordinary
        setters. Same result on screen, and a header that can save itself.
        """
        columns = range(self._table.columnCount())
        header = self._table.horizontalHeader()
        layout = [
            (header.visualIndex(col), self._table.columnWidth(col),
             self._table.isColumnHidden(col))
            for col in columns
        ]
        header.restoreState(pristine)
        for col, (_, width, hidden) in enumerate(layout):
            self._table.setColumnWidth(col, width)
            self._table.setColumnHidden(col, hidden)
        # Order last, and applied in the order the columns should end up in,
        # so each move lands against an already-settled prefix.
        for col, (visual, _, _) in sorted(enumerate(layout), key=lambda kv: kv[1][0]):
            if header.visualIndex(col) != visual:
                header.moveSection(header.visualIndex(col), visual)

    def _build_column_menu(self) -> QMenu:
        """The header's show/hide menu, built but not shown.

        Separate from showing it so it can be inspected without opening a
        modal — exec() on a menu nothing clicks blocks forever.

        Column labels come from the header itself so they are already
        translated; '#' and Filename are never offered.
        """
        menu = QMenu(self)
        for col in range(self._table.columnCount()):
            if col in self._LOCKED_COLUMNS:
                continue
            item = self._table.horizontalHeaderItem(col)
            action = menu.addAction(item.text() if item else str(col))
            action.setCheckable(True)
            action.setChecked(not self._table.isColumnHidden(col))
            action.setData(col)
            action.toggled.connect(
                lambda shown, c=col: self._set_column_visible(c, shown)
            )
        menu.addSeparator()
        reset = menu.addAction(self.tr("Reset Columns"))
        reset.triggered.connect(self.reset_columns_to_defaults)
        return menu

    def reset_columns_to_defaults(self) -> None:
        """Put the playlist back to the shipped order, open set and widths.

        The way back. A saved layout outranks the defaults — that is what makes
        it a saved layout — so without this the only route to the shipped
        arrangement is a defaults-version bump, i.e. a new build. Which is one
        release too slow for someone who hid a column and wants it back.

        Every column is given a width, not just the ones that were hidden: a
        section that was hidden reports a width of 0 whatever it is set to, so
        the width it comes back at is whatever it last held — which for a
        column restored from an old saved state can itself be 0. (Measured:
        setting the width before or after un-hiding gives the same result, so
        the order of those two is not the trap it looks like.)
        """
        optional = {col for col, _ in self._OPTIONAL_COLUMNS}
        for col in range(self._table.columnCount()):
            self._table.setColumnHidden(
                col, col in optional and col not in self._DEFAULT_SHOWN_OPTIONAL
            )
        for col in range(self._table.columnCount()):
            self._table.setColumnWidth(col, self._default_column_widths.get(col, 100))
        self._apply_default_column_order()
        # Art's width follows the row height and the header word, neither of
        # which _default_column_widths knows about until this has run.
        self._apply_art_icon_size()
        self._table.setColumnWidth(
            self._ARTWORK_COLUMN, self._default_column_widths[self._ARTWORK_COLUMN]
        )
        # Art is back on, and in the Full view that means taller rows again.
        self._apply_row_height()
        self._schedule_artwork_load()
        self._save_column_state()

    def _show_column_menu(self, pos) -> None:
        """Right-click the header: which columns to show."""
        menu = self._build_column_menu()
        menu.exec(self._table.horizontalHeader().mapToGlobal(pos))

    def _set_column_visible(self, col: int, shown: bool) -> None:
        """Show or hide one column and remember the choice."""
        self._table.setColumnHidden(col, not shown)
        if shown and self._table.columnWidth(col) <= 0:
            # A section hidden at zero width would come back invisible.
            self._table.setColumnWidth(col, self._default_column_widths.get(col, 100))
        if col == self._ARTWORK_COLUMN:
            # In the Full view the rows are tall enough to hold a whole cover,
            # which is only right while there is one on screen — so both
            # directions of the toggle re-apply the height.
            self._apply_row_height()
            if shown:
                # Nothing was read while it was hidden — that is the point of
                # it being optional — so the first reveal starts from nothing.
                self._apply_art_icon_size()
                self._schedule_artwork_load()
        self._schedule_column_save()

    def _schedule_column_save(self, *args) -> None:
        """Debounce saves so a drag-resize writes the config once, not per pixel."""
        # Not while searching: column 0 is temporarily widened for its
        # "Playlists" header, and saveState would persist that width onto '#'.
        # A visibility toggle made mid-search would be lost with it, so the
        # request is remembered and flushed when the search ends.
        if self._search_active:
            self._columns_changed_while_searching = True
            return
        self._col_save_timer.start()

    def _save_column_state(self) -> None:
        """Persist the current column order/widths. Re-loads config first so we
        don't clobber settings another panel changed since launch."""
        state = bytes(self._table.horizontalHeader().saveState().toBase64()).decode("ascii")
        count = self._table.columnCount()
        cfg = load_config()
        version = self._COLUMN_DEFAULTS_VERSION
        if (
            cfg.player_column_state == state
            and cfg.player_column_count == count
            and cfg.player_column_defaults_version == version
        ):
            return
        cfg.player_column_state = state
        # Saved together, always: the state alone cannot say how many sections
        # it covers, and that is what tells a later build which columns it is
        # allowed to have an opinion about (see _restore_column_state).
        cfg.player_column_count = count
        # And the generation of defaults this layout was built on top of, so a
        # future change to the shipped order can tell "the user arranged this"
        # from "this is just the old default, carried forward".
        cfg.player_column_defaults_version = version
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
        self._playing_path = entry.file_path
        self._update_now_playing()
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
            self._on_engine_source_changed(pcm, sr)
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
            self._on_engine_source_changed(pcm, sr)
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
        if self._rebuilding:
            return
        # The tree highlight follows the selection regardless of visibility
        # (the sidebar tree is a different widget and may well be on screen).
        self._update_search_highlight()
        if not self.isVisible():
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
        self._table.set_backdrop_position_ms(position)

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
        self._waveform_color = color
        self._slice.set_waveform_color(color)
        self._table.set_backdrop_color(color)
        if self._vis_window is not None:
            self._vis_window.set_color(color)
        if self._backdrop_renderer is not None:
            self._backdrop_renderer.set_color(color)

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
        if playing:
            # (Re)start the visualizer-backdrop timer when playback begins.
            self._refresh_backdrop()
        # Keep the header art up while loaded (playing or paused); drop it once
        # the track is fully stopped (incl. end-of-playlist via engine.stop()).
        if not playing and not self._engine.is_paused():
            self._hide_artwork()
            # Backdrop follows the artwork's lifetime: gone on a full stop.
            self._backdrop_src = None
            self._backdrop_env = None
            self._backdrop_env_path = None
            self._vis_tick_timer.stop()
            self._table.clear_backdrop()

    # ── Seek / Volume ───────────────────────────────────────────

    def _on_seek(self, position: int) -> None:
        self._engine.seek_ms(position)

    def _on_volume_changed(self, value: int) -> None:
        self._volume_pct = value
        self._engine.set_volume(value / 100.0)
        # The audition shares the slider: a preview at a volume the user did
        # not set is the kind of surprise that gets a feature turned off.
        self._compat_panel.set_volume(value / 100.0)

    # ── Slice section ───────────────────────────────────────────

    def _current_path(self) -> str | None:
        """Path of the track loaded in the engine — NOT derived from the
        visible list, which may be a different playlist entirely."""
        return self._playing_path

    # Number of playlist rows kept visible when the slice section is open.
    _ROWS_VISIBLE_WHEN_SLICING = 12

    def slice_time_row_min_width(self) -> int:
        """Min width the slicer's time-info + Mark-buttons row needs to fit."""
        return self._slice.time_row_min_width()

    def _on_slice_view_changed(self, _checked: bool = False) -> None:
        """Swap the seek control and reflow for whichever slice views are open.

        The two toggles are independent, so this recomputes from both rather
        than from the one that fired. The full waveform *is* the seek control
        while it's up, so the plain slider hides only then — with the Loop
        Slicer alone there'd otherwise be nothing left to scrub with. Either
        view open pins the playlist to a fixed visible height so it can't be
        squished, and the panel grows past the viewport so the outer scrollbar
        reveals what's below. Both closed: stretchy playlist, plain slider.
        """
        expanded = self._slice.is_expanded()
        self._seek_row_widget.setVisible(not self._slice.is_waveform_shown())
        self._apply_table_height(self._slice.is_open())
        if not self._slice.is_open():
            # Return to the top so the user isn't left scrolled past the slicer.
            self._scroll.verticalScrollBar().setValue(0)
        # Only the tray's time row needs the wider window minimum.
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
        # Only render if a view is still open on the same track.
        if self._wf_path == self._current_path() and self._slice.is_open():
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

    def _guard_drag(self) -> bool:
        """Veto a drag whose files aren't on disk any more, and say why.

        The case this exists for: a track keeps playing from the PCM cache
        after its file moves (the audio is in RAM), so the list can look
        perfectly healthy right up until you try to *do* something with the
        file. Dragging is that moment — the row gets marked and dimmed here,
        rather than at the next panel switch.
        """
        rows = sorted({idx.row() for idx in self._table.selectionModel().selectedRows()})
        paths = [self._playlist[r].file_path for r in rows if 0 <= r < len(self._playlist)]
        # Deliberately not _is_missing: the memo can be stale, and this is
        # the one moment where being right matters more than being cheap.
        missing = [p for p in paths if not Path(p).is_file()]
        if not missing:
            return True
        self._refresh_missing_marks()
        # Deferred: this runs from the view's mouse-move handler with the
        # button still down, and a modal box opened there fights the drag
        # machinery for the mouse grab. Let the event unwind first.
        QTimer.singleShot(0, lambda: self._warn_files_moved(missing))
        return False

    def _warn_files_moved(self, missing: list[str]) -> None:
        """Tell the user the file moved, and point at the way to fix it."""
        if len(missing) == 1:
            text = self.tr("“{0}” has moved.").format(Path(missing[0]).name)
        else:
            text = self.tr("%n of the selected files have moved.", "", len(missing))
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(self.tr("File Has Moved"))
        box.setText(text)
        box.setInformativeText(
            self.tr(
                "It is no longer at its saved location, so it can't be added"
                " to a playlist or dragged out. A track already playing keeps"
                " playing — it was loaded into memory before the file moved."
            )
            + "\n\n"
            + self.tr("Right-click the track and choose Locate Missing File…")
        )
        box.exec()

    def _now_playing_drag_path(self) -> str | None:
        """Path behind the now-playing line, or None to veto the drag.

        Same veto as `_guard_drag`, and for the same reason: the track can be
        playing out of the PCM cache long after its file moved, so this is the
        one line that can name a file that is no longer there.
        """
        path = self._playing_path
        if not path:
            return None
        if not Path(path).is_file():
            self._refresh_missing_marks()
            # Deferred for the same mouse-grab reason as _guard_drag's.
            QTimer.singleShot(0, lambda: self._warn_files_moved([path]))
            return None
        return path

    def _drag_data(self):
        """Provide (paths, remove-on-move callback) for an outgoing drag.

        The callback is always None: this list is a saved playlist, so dragging
        a track to another panel (or out to Finder) copies it and the playlist
        keeps its row — only an explicit Remove/Delete takes a track out. Every
        Player route in `DRAG_ROUTES` is a Copy for the same reason; returning
        None as well means a destination that proposes MoveAction anyway (Finder
        and other apps decide their own action) still cannot empty a playlist.
        """
        rows = sorted({idx.row() for idx in self._table.selectionModel().selectedRows()})
        paths = [self._playlist[r].file_path for r in rows if 0 <= r < len(self._playlist)]
        if not paths:
            return None
        return paths, None

    # ── Remove / Clear ──────────────────────────────────────────

    def _on_remove_selected(self) -> None:
        # Removing a search result is undefined (remove from which playlist?)
        # — the row lives in the results view, not in a list the user edits.
        if self._search_active:
            return
        rows = sorted({idx.row() for idx in self._table.selectionModel().selectedRows()}, reverse=True)
        if not rows:
            return

        playing_path = self._playing_path

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
                    self._playing_path = None
                    self._update_now_playing()
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
        self._persist_playlist()

    def _on_clear_playlist(self) -> None:
        # Unload to release the audio device and free the decoded buffer.
        self._engine.unload()
        self._slice.set_track(None, 0)
        self._pending_play_path = None
        self._playing_path = None
        self._update_now_playing()
        self._prefetch_queue.clear()
        self._pcm_cache.clear()
        self._playlist.clear()
        self._current_index = -1
        self._hide_artwork()
        self._rebuild_table()
        self._update_stats()
        self._update_transport_state()
        self._persist_playlist()

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
        # Only when the file is actually gone: an always-present "Locate…"
        # would read as an invitation to repoint tracks that are fine.
        locate_action = None
        if self._library is not None and self._is_missing(entry.file_path):
            locate_action = menu.addAction(self.tr("Locate Missing File…"))
            menu.addSeparator()
        open_folder_action = menu.addAction(self.tr("Open File Location"))
        open_metadata_action = menu.addAction(self.tr("Open in Metadata Panel"))
        reload_action = menu.addAction(self.tr("Reload Metadata from File"))
        menu.addSeparator()
        remove_action = menu.addAction(self.tr("Remove from Playlist"))

        chosen = menu.exec(self._table.viewport().mapToGlobal(pos))
        if locate_action is not None and chosen is locate_action:
            self._locate_missing(row)
        elif chosen is open_folder_action:
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
