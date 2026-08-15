"""Compatible Tracks — what else in the library mixes with the playing track.

Rekordbox's matching panel, offline: the seed is whatever the Player has
loaded, the pool is the whole library, and the answer is a ranked list from
`Library.compatible_tracks` (key relation first, then tempo, then energy).

The panel is deliberately thin. It holds no state of its own beyond the seed
path and the last result: every refresh re-runs the query, which is
milliseconds even against a large library, so there is nothing to keep in
sync and nothing to invalidate.

Two things the empty states carry that a blank table could not: a seed with
no readable key is a prompt to analyse it, not a "no matches" — and a track
that never made it into the library can't be a seed at all (decided
2026-08-12: the seed must be a library track).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QCoreApplication, QMimeData, QPointF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDrag, QFontMetrics, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.analysis.keycode import render_key
from src.library import CompatibleMatch, Library
from src.library.compatibility import (
    KEY_ADJACENT,
    KEY_RELATIVE,
    KEY_SAME,
    TEMPO_DOUBLE,
    TEMPO_HALF,
)
from src.utils.config import load_config

from ..styles.theme import Theme
from .audition_player import AuditionPlayer
from .droppable_table import blank_drag_pixmap
from .elided_label import ElidedLabel

logger = logging.getLogger(__name__)

# Column layout. The track column takes whatever is left, so only the audition
# column and the three narrow ones are measured.
COL_AUDITION = 0
COL_KEY = 1
COL_BPM = 2
COL_ENERGY = 3
COL_TRACK = 4

# The audition column: wide enough for the play glyph and a comfortable click
# target, narrow enough that it reads as a gutter rather than a column.
_AUDITION_COL_WIDTH = 26

# Breathing room around the widest value each narrow column can hold, on top
# of whichever is wider — the sample or the (translated) header word. Kept
# tight on purpose: every pixel here comes out of the track name, which is the
# column the user is actually reading.
_CELL_PAD = 10

# Never narrower than this, whatever the fonts say — below it the track names
# are unreadable and the splitter is just eating the playlist.
_MIN_PANEL_WIDTH = 220

# What the Key column's colour says about the match. The list is already in
# this order, so the tint is a reminder rather than the only way to tell: the
# same key is the primary accent, the relative major/minor the secondary, and
# a ±1 neighbour is left in the ordinary text colour rather than dimmed —
# adjacent is a good mix, not a poor one.
_KEY_TIER_COLOURS = {
    KEY_SAME: Theme.NEON_YELLOW,
    KEY_RELATIVE: Theme.NEON_GREEN,
    KEY_ADJACENT: Theme.TEXT_PRIMARY,
}


class CompatibleTracksPanel(QWidget):
    """The right-hand half of the Player's playlist area, when open."""

    # A row was double-clicked — the file path, for the Player to append to
    # the list it is showing (decided: double-click adds to the loaded
    # playlist, drag-out covers every other destination).
    track_activated = Signal(str)
    # An audition started (path). The Player stops its own engine on this —
    # two streams playing at once is the one thing the gesture must not do.
    audition_started = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("compatiblePanel")
        self._library: Library | None = None
        self._seed_path: str | None = None
        self._matches: list[CompatibleMatch] = []
        self._key_notation = load_config().key_notation
        self._audition = AuditionPlayer(self)
        self._setup_ui()
        self._audition.started.connect(self.audition_started)
        self._audition.started.connect(self._on_audition_state)
        self._audition.stopped.connect(self._on_audition_state)
        self._audition.busy_changed.connect(self._on_audition_busy)
        self.refresh()

    # ── Construction ────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Theme.SPACING, 0, 0, 0)
        layout.setSpacing(4)

        # Uncontrolled length (it carries a track name), so never a bare
        # QLabel — see CLAUDE.md.
        self._seed_label = ElidedLabel("")
        self._seed_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 13px;")
        layout.addWidget(self._seed_label)

        self._table = _AuditionTable()
        self._table.setObjectName("compatibleTable")
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(
            ["", self.tr("Key"), self.tr("BPM"), self.tr("Energy"), self.tr("Track")]
        )
        self._table.verticalHeader().setVisible(False)
        # The order IS the ranking, so nothing here reorders or edits.
        self._table.setSortingEnabled(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(False)
        self._table.setStyleSheet(
            "QTableWidget { background-color: transparent; border: none; }"
            "QTableWidget::item { padding: 4px 5px; }"
        )
        self._table.doubleClicked.connect(self._on_double_clicked)

        header = self._table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionsMovable(False)
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        # ensurePolished so the QSS font is resolved onto the header before it
        # is measured — without it the widths come out short (the same trap
        # the playlist's word-fit columns hit).
        header.ensurePolished()
        fm = QFontMetrics(header.font())
        self._narrow_widths: dict[int, int] = {}
        # The BPM sample carries the half-time marker, because that is the
        # widest thing the cell can hold — without it "64 ×2" rendered as
        # "64…" in a column measured for "174.5".
        for col, sample in (
            (COL_KEY, "10A"),
            (COL_BPM, "174.5 ×2"),
            (COL_ENERGY, "10"),
        ):
            # The header word is measured with sectionSizeHint, NOT with font
            # metrics: this is a plain QHeaderView, so the *style* draws the
            # label and adds the stylesheet's section padding and bold weight,
            # neither of which reaches header.font(). Measuring by hand here
            # clipped "Energy" to "Energ" under the real stylesheet — the same
            # trap the Analyze header hit (CLAUDE.md).
            width = max(
                header.sectionSizeHint(col),
                fm.horizontalAdvance(sample) + _CELL_PAD,
            )
            self._narrow_widths[col] = width
            self._table.setColumnWidth(col, self._narrow_widths[col])
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)

        # The audition gutter: fixed, unlabelled, and painted by a delegate —
        # the QSS `QTableView::item` rule means anything drawn from the model
        # (a DecorationRole icon, a background brush) is overpainted by the
        # style, so the glyph has to be drawn here to appear at all.
        self._table.setColumnWidth(COL_AUDITION, _AUDITION_COL_WIDTH)
        header.setSectionResizeMode(COL_AUDITION, QHeaderView.ResizeMode.Fixed)
        self._audition_delegate = _AuditionDelegate(self._table)
        self._table.setItemDelegateForColumn(COL_AUDITION, self._audition_delegate)
        self._table.drag_paths = self._selected_paths
        self._table.icon_clicked.connect(self._on_audition_clicked)
        self._table.icon_hover_changed.connect(self._on_icon_hover)
        self._table.row_hover_changed.connect(self._on_row_hover)
        layout.addWidget(self._table, 1)

        # Shown instead of the table whenever there is nothing to list — the
        # reason matters more than the emptiness (analyse it / play something).
        self._message_label = QLabel("")
        self._message_label.setWordWrap(True)
        self._message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message_label.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: 13px;"
        )
        self._message_label.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self._message_label, 1)

        self.setMinimumWidth(self.minimum_useful_width())

    # ── Wiring ──────────────────────────────────────────────────

    def set_library(self, library: Library) -> None:
        """Attach the playlist library the query runs against."""
        self._library = library
        self.refresh()

    def set_key_notation(self, notation: str) -> None:
        """Follow the Settings key-notation choice (codes / traditional / open)."""
        if notation == self._key_notation:
            return
        self._key_notation = notation
        self.refresh()

    def set_seed_path(self, path: str | None) -> None:
        """Match against this track from now on; None clears the panel.

        Called from the Player whenever the loaded track changes — cheap
        enough to call unconditionally, since an unchanged path is a no-op.
        """
        if path == self._seed_path:
            return
        self._seed_path = path
        self.refresh()

    @property
    def seed_path(self) -> str | None:
        return self._seed_path

    @property
    def matches(self) -> list[CompatibleMatch]:
        """The ranked result currently on show (empty when a message is)."""
        return list(self._matches)

    # ── Query + render ──────────────────────────────────────────

    def refresh(self) -> None:
        """Re-run the query and repaint. Safe to call at any time.

        Any audition ends here: the row it belonged to is about to be
        replaced, and sound outliving the list it came from is exactly the
        kind of thing that leaves a DJ hunting for a stop button.
        """
        self.stop_audition()
        self._matches = []
        seed = None
        if self._library is not None and self._seed_path:
            seed = self._library.get_track_by_path(self._seed_path)
        message = self._seed_message(seed)
        if message is None:
            self._matches = self._library.compatible_tracks(seed.id)
            if not self._matches:
                message = self.tr("Nothing in your library mixes with this track.")
        self._show_message(message)
        self._fill_table()
        self._update_header(seed, message is not None)

    def _seed_message(self, seed) -> str | None:
        """The reason there is no result to show, or None if there is one."""
        if self._library is None or not self._seed_path:
            return self.tr("Play a track to see what mixes with it.")
        if seed is None:
            return self.tr("This track isn't in your library yet.")
        if not seed.keycode:
            return self.tr("No key for this track — analyse it first.")
        return None

    def _show_message(self, message: str | None) -> None:
        self._message_label.setText(message or "")
        self._message_label.setVisible(message is not None)
        self._table.setVisible(message is None)

    def _update_header(self, seed, empty: bool) -> None:
        if seed is None:
            self._seed_label.setText("")
            return
        name = _display_name(seed)
        if empty:
            self._seed_label.setText(self.tr("Compatible with {0}").format(name))
            return
        # "Compatible with Artist – Title · 12 tracks": one line, elided at the
        # name, so the count stays readable at any panel width.
        # Singular/plural spelled out rather than a %n plural: an English
        # source string is what every untranslated language falls back to, and
        # "5 track(s)" is not English. Same branch the Player's stats line uses.
        n = len(self._matches)
        count = (
            self.tr("{0} track").format(n) if n == 1 else self.tr("{0} tracks").format(n)
        )
        self._seed_label.setText(
            self.tr("Compatible with {0} · {1}").format(name, count)
        )

    def _fill_table(self) -> None:
        self._table.setRowCount(len(self._matches))
        for row, match in enumerate(self._matches):
            track = match.track
            self._set_cell(row, COL_AUDITION, "", self._audition_tooltip())
            key = render_key(track.key or "", track.keycode or "", self._key_notation)
            self._set_cell(
                row, COL_KEY, key, tooltip=_key_tooltip(match), colour=match.key_relation
            )
            self._set_cell(row, COL_BPM, *_bpm_text(match))
            energy = "" if track.energy is None else str(track.energy)
            self._set_cell(row, COL_ENERGY, energy)
            self._set_cell(row, COL_TRACK, _display_name(track), track.path)

    def _set_cell(
        self, row: int, col: int, text: str, tooltip: str = "", colour: str = ""
    ) -> None:
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        if tooltip:
            item.setToolTip(tooltip)
        if colour in _KEY_TIER_COLOURS:
            # ForegroundRole, not a background brush: the stylesheet's
            # `QTableView::item` rule makes Qt paint item *backgrounds* itself
            # and ignore the model's brush, but the text colour still comes
            # through — the same way the playlist marks its playing row.
            item.setForeground(QColor(_KEY_TIER_COLOURS[colour]))
        self._table.setItem(row, col, item)

    # ── Interaction ─────────────────────────────────────────────

    def _on_double_clicked(self, index) -> None:
        # The gutter is the audition control, where a double click is two
        # clicks of the gesture (start, then skip on) — not a request to add
        # the track to the playlist.
        if index.column() == COL_AUDITION:
            return
        row = index.row()
        if 0 <= row < len(self._matches):
            self.track_activated.emit(self._matches[row].track.path)

    def _selected_paths(self) -> list[str]:
        """Paths for the rows a drag is starting from."""
        rows = sorted({index.row() for index in self._table.selectedIndexes()})
        return [
            self._matches[row].track.path
            for row in rows
            if 0 <= row < len(self._matches)
        ]

    def _audition_tooltip(self) -> str:
        return self.tr("Click to preview — hold the pointer here to keep playing")

    # ── Audition ────────────────────────────────────────────────

    def _on_audition_clicked(self, row: int) -> None:
        """Icon click: start this track, or skip 30 s if it is already going."""
        if 0 <= row < len(self._matches):
            self._audition.click(self._matches[row].track.path)

    def _on_icon_hover(self, row: int) -> None:
        """The gesture's sustain: sound lasts only while the icon is held.

        Any move off the icon — onto another cell, another row, or out of the
        table — stops everything. The main player stays stopped (confirmed
        2026-08-12); it is not resumed here or anywhere else.
        """
        self._audition_delegate.set_hovered_row(row)
        self._table.viewport().update()
        if row < 0 or not self._is_audition_row(row):
            self._audition.stop()

    def _on_row_hover(self, row: int) -> None:
        """Row hover warms the first window so the click plays from memory."""
        if 0 <= row < len(self._matches) and not self._audition.is_playing():
            self._audition.warm(self._matches[row].track.path)

    def _is_audition_row(self, row: int) -> bool:
        """Is *row* the one currently being auditioned?"""
        current = self._audition.current_path
        return (
            current is not None
            and 0 <= row < len(self._matches)
            and self._matches[row].track.path == current
        )

    def _on_audition_state(self, *_args) -> None:
        self._audition_delegate.set_playing_row(self._row_for_path(self._audition.current_path))
        self._table.viewport().update()

    def _on_audition_busy(self, path: str) -> None:
        self._audition_delegate.set_busy_row(self._row_for_path(path or None))
        self._table.viewport().update()

    def _row_for_path(self, path: str | None) -> int:
        if not path:
            return -1
        for row, match in enumerate(self._matches):
            if match.track.path == path:
                return row
        return -1

    def stop_audition(self) -> None:
        """End any audition — the panel closed, the seed changed, the list
        was rebuilt. Safe when nothing is playing."""
        self._audition.stop()

    def set_volume(self, volume: float) -> None:
        """Follow the Player's volume slider, so a preview is not a surprise."""
        self._audition.set_volume(volume)

    def shutdown_workers(self) -> None:
        """Join the audition reader — house rule for a panel that starts
        threads, and the difference between a clean quit and a QThread
        destroyed while running."""
        self._audition.shutdown_workers()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.shutdown_workers()
        super().closeEvent(event)

    # ── Metrics ─────────────────────────────────────────────────

    def minimum_useful_width(self) -> int:
        """Width below which the panel stops being worth the space it takes.

        Measured from the columns it actually built (translated header words
        included) rather than assumed — the mistake the Convert row's constant
        made, and the reason the window minimum can grow when this opens.
        """
        fixed = sum(self._narrow_widths.values()) + _AUDITION_COL_WIDTH
        # Enough of the track column to read an artist and the start of a
        # title. Measured off the average character rather than a string of
        # 'M's, which is the widest glyph in the font and overstated the
        # column by about a third.
        track = QFontMetrics(self._table.font()).averageCharWidth() * 20
        margins = self.layout().contentsMargins()
        return max(
            _MIN_PANEL_WIDTH,
            fixed + track + margins.left() + margins.right() + 2,
        )

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        return QSize(self.minimum_useful_width() + 60, super().sizeHint().height())


class _AuditionTable(QTableWidget):
    """The panel's table, with the mouse state the audition gesture needs.

    Three things a plain table does not report: which row the pointer is over
    (to warm a window), whether it is over the audition gutter specifically
    (the sustain — sound lasts exactly as long as this is true), and a click
    in that gutter. Hover needs `setMouseTracking`, and the viewport needs it
    too: the table's own tracking flag does not reach the widget that actually
    receives the moves.
    """

    icon_clicked = Signal(int)
    # Row whose audition icon is under the pointer, -1 for none.
    icon_hover_changed = Signal(int)
    # Row under the pointer at all, -1 for none.
    row_hover_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self._hover_row = -1
        self._icon_row = -1
        # Set by the panel — the paths a drag out of here should carry.
        self.drag_paths = lambda: []
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)

    def startDrag(self, supported_actions) -> None:  # noqa: N802 (Qt override)
        """Drag matches out to a playlist, the tree, or Finder.

        Deliberately **Copy only, and with no source-panel marker**. This list
        is a query result: there is nothing here to move out of, and a drop
        handler that read a Move would try to remove the row it came from. No
        marker means every handler treats it as it treats a drop from Finder —
        an add — which is exactly the intent.
        """
        paths = self.drag_paths()
        if not paths:
            return
        mime = drag_mime(paths)
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(blank_drag_pixmap())
        drag.exec(Qt.DropAction.CopyAction)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        pos = event.position().toPoint()
        row = self.rowAt(pos.y())
        col = self.columnAt(pos.x())
        self._set_hover(row, row if (row >= 0 and col == COL_AUDITION) else -1)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._set_hover(-1, -1)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        pos = event.position().toPoint()
        row = self.rowAt(pos.y())
        if row >= 0 and self.columnAt(pos.x()) == COL_AUDITION:
            # Make sure the sustain state agrees with the click: a press can
            # arrive without a preceding move (a click after the list was
            # rebuilt under a stationary pointer), and a click that the panel
            # then reads as "not on the icon" would stop itself instantly.
            self._set_hover(row, row)
            self.icon_clicked.emit(row)
            return
        super().mousePressEvent(event)

    def _set_hover(self, row: int, icon_row: int) -> None:
        if row != self._hover_row:
            self._hover_row = row
            self.row_hover_changed.emit(row)
        if icon_row != self._icon_row:
            self._icon_row = icon_row
            self.icon_hover_changed.emit(icon_row)


class _AuditionDelegate(QStyledItemDelegate):
    """Draws the audition gutter: a play glyph per row, brighter under the
    pointer, neon while that row is playing, hollow while it waits on a decode.

    Painted here rather than set as a DecorationRole icon because the QSS
    styles `QTableView::item`, and once a stylesheet styles items Qt draws
    them itself and ignores what the model returns — the trap that made an
    Analyze-panel row tint invisible while every data-level test passed. Test
    this by sampling a render, not by asking the model.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hovered_row = -1
        self._playing_row = -1
        self._busy_row = -1

    def set_hovered_row(self, row: int) -> None:
        self._hovered_row = row

    def set_playing_row(self, row: int) -> None:
        self._playing_row = row

    def set_busy_row(self, row: int) -> None:
        self._busy_row = row

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        row = index.row()
        if row == self._playing_row:
            colour = QColor(Theme.NEON_YELLOW)
        elif row == self._hovered_row:
            colour = QColor(Theme.TEXT_PRIMARY)
        else:
            # Dim, but drawn on every row: an icon that only exists on hover
            # is an icon nobody finds.
            colour = QColor(Theme.TEXT_DISABLED)
        rect = option.rect
        size = min(rect.height() - 8, 12)
        if size <= 2:
            return
        cx = rect.center().x()
        cy = rect.center().y()
        half = size / 2.0
        triangle = QPolygonF(
            [
                QPointF(cx - half * 0.7, cy - half),
                QPointF(cx - half * 0.7, cy + half),
                QPointF(cx + half * 0.9, cy),
            ]
        )
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if row == self._busy_row:
            # Waiting on a window: outline only, so the icon says "asked for,
            # not yet playing" instead of pretending sound has started.
            painter.setPen(QPen(colour, 1.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(colour)
        painter.drawPolygon(triangle)
        painter.restore()


def drag_mime(paths: list[str]) -> QMimeData:
    """The payload a drag out of the panel carries: file URLs, nothing else.

    Split out so what leaves the panel can be asserted without running a
    drag loop — and so the absence of a source-panel marker is visible as a
    decision rather than as an omission.
    """
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
    return mime


def _key_tooltip(match: CompatibleMatch) -> str:
    """What the key colour means, in one line."""
    return {
        KEY_SAME: QCoreApplication.translate("CompatibleTracksPanel", "Same key"),
        KEY_RELATIVE: QCoreApplication.translate(
            "CompatibleTracksPanel", "Relative major/minor"
        ),
        KEY_ADJACENT: QCoreApplication.translate(
            "CompatibleTracksPanel", "One step around the wheel"
        ),
    }.get(match.key_relation, "")


def _display_name(track) -> str:
    """Artist – Title, falling back to the filename for an untagged file."""
    artist = (track.artist or "").strip()
    title = (track.title or "").strip()
    if artist and title:
        return f"{artist} – {title}"
    return title or artist or track.filename


def _bpm_text(match: CompatibleMatch) -> tuple[str, str]:
    """(cell text, tooltip) for a match's tempo.

    A half- or double-time match is real but needs saying so: 64 under a 128
    seed is shown as "64 ×2" rather than looking like a query bug.
    """
    bpm = match.track.bpm
    if not bpm:
        return "", ""
    text = f"{bpm:g}"
    if match.tempo_relation == TEMPO_HALF:
        return f"{text} ×2", QCoreApplication.translate(
            "CompatibleTracksPanel", "Half-time — mixes at double this tempo"
        )
    if match.tempo_relation == TEMPO_DOUBLE:
        return f"{text} ÷2", QCoreApplication.translate(
            "CompatibleTracksPanel", "Double-time — mixes at half this tempo"
        )
    return text, ""
