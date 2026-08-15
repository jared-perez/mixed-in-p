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

from PySide6.QtCore import QCoreApplication, QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.analysis.keycode import render_key
from src.library import CompatibleMatch, Library
from src.library.compatibility import TEMPO_DOUBLE, TEMPO_HALF
from src.utils.config import load_config

from ..styles.theme import Theme
from .elided_label import ElidedLabel

logger = logging.getLogger(__name__)

# Column layout. The track column takes whatever is left, so only the three
# narrow ones are measured.
COL_KEY = 0
COL_BPM = 1
COL_ENERGY = 2
COL_TRACK = 3

# Breathing room around the widest value each narrow column can hold, on top
# of whichever is wider — the sample or the (translated) header word. Kept
# tight on purpose: every pixel here comes out of the track name, which is the
# column the user is actually reading.
_CELL_PAD = 10

# Never narrower than this, whatever the fonts say — below it the track names
# are unreadable and the splitter is just eating the playlist.
_MIN_PANEL_WIDTH = 220


class CompatibleTracksPanel(QWidget):
    """The right-hand half of the Player's playlist area, when open."""

    #: A row was double-clicked — the file path, for the Player to append to
    #: the list it is showing (decided: double-click adds to the loaded
    #: playlist, drag-out covers every other destination).
    track_activated = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("compatiblePanel")
        self._library: Library | None = None
        self._seed_path: str | None = None
        self._matches: list[CompatibleMatch] = []
        self._key_notation = load_config().key_notation
        self._setup_ui()
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

        self._table = QTableWidget()
        self._table.setObjectName("compatibleTable")
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(
            [self.tr("Key"), self.tr("BPM"), self.tr("Energy"), self.tr("Track")]
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
        """Re-run the query and repaint. Safe to call at any time."""
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
            key = render_key(track.key or "", track.keycode or "", self._key_notation)
            self._set_cell(row, COL_KEY, key)
            self._set_cell(row, COL_BPM, *_bpm_text(match))
            energy = "" if track.energy is None else str(track.energy)
            self._set_cell(row, COL_ENERGY, energy)
            self._set_cell(row, COL_TRACK, _display_name(track), track.path)

    def _set_cell(self, row: int, col: int, text: str, tooltip: str = "") -> None:
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        if tooltip:
            item.setToolTip(tooltip)
        self._table.setItem(row, col, item)

    # ── Interaction ─────────────────────────────────────────────

    def _on_double_clicked(self, index) -> None:
        row = index.row()
        if 0 <= row < len(self._matches):
            self.track_activated.emit(self._matches[row].track.path)

    # ── Metrics ─────────────────────────────────────────────────

    def minimum_useful_width(self) -> int:
        """Width below which the panel stops being worth the space it takes.

        Measured from the columns it actually built (translated header words
        included) rather than assumed — the mistake the Convert row's constant
        made, and the reason the window minimum can grow when this opens.
        """
        fixed = sum(self._narrow_widths.values())
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
