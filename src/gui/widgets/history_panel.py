"""History panel for viewing and undoing rename sessions."""

import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.analysis.history import load_entries as load_analysis_entries
from src.renamer import RenameSession, delete_session, list_sessions, load_session
from src.utils.config import DEFAULT_HISTORY_DISPLAY_LIMIT, HISTORY_DISPLAY_LIMITS
from src.utils.export import write_csv

from ..styles.theme import BackgroundOverlay, Theme, panel_header_row

_KEYCODE_RE = re.compile(r"(\d{1,2})([AB])", re.IGNORECASE)

# Rename Sessions table column order. Named so the display order can change
# without hunting down bare indices — _get_selected_session in particular reads
# the session id back off the _SESS_ID cell.
_SESS_DATE, _SESS_FILES, _SESS_DESC, _SESS_ID = range(4)

# Index of the backing self._entries record, stashed on each keys-table row so
# export can walk rows in the user's current sort order and still emit the
# underlying values rather than re-parsing formatted cell text. UserRole itself
# is taken by _SortableItem's sort value, hence +1.
_ENTRY_INDEX_ROLE = Qt.ItemDataRole.UserRole + 1

# Key detections at or below this confidence are tinted for review.
#
# Flagging on key_confidence alone is deliberate: the detector already folds the
# runner-up margin into that score, weighted more heavily than anything else
# (see _confidence in src/analysis/key_detector.py, where separation carries
# 0.45 of the blend). Re-deriving a margin from key_alternatives here would
# double-count a signal the number already carries.
#
# A low score has two causes and both warrant a second look: weak tonal material
# (low fit strength) or a near-tie between candidate keys (low separation).
#
# 0.25 was chosen from a real 50-track library, not from the formula. That
# library's key_confidence runs low and smooth (median ~44%, no bimodal split),
# so this detector has no natural "confident vs unsure" gap to snap to — the
# threshold instead picks the worst minority worth re-checking. 0.25 flags ~26%
# (the bottom quartile; the library's p25 was 23%). Raising it climbs fast:
# ~0.35 flags 40%, ~0.50 flags 64%, at which point the tint marks the majority
# and stops meaning "check this". Retune against your own distribution.
LOW_KEY_CONFIDENCE = 0.25

# Separate from LOW_KEY_CONFIDENCE on purpose: BPM confidence is a different
# detector with a different distribution, so the two thresholds must move
# independently. On a real 50-track library BPM confidence was bimodal — most
# tracks 80-100%, a distinct low tail below ~40% — with a sparse valley between.
# A low BPM score often means the half/double-time ambiguity (see _refine_bpm in
# bpm_detector.py, which halves confidence when no in-range metrical level had
# autocorrelation support), i.e. the tempo may be doubled or halved. 0.70 flags
# ~32% on that library — the whole low cluster plus the valley floor.
LOW_BPM_CONFIDENCE = 0.70


class _SortableItem(QTableWidgetItem):
    """Table item that sorts on a value held separately from its display text.

    A cell showing "128.0" or "91%" or "10A" must not sort as that string, but
    QTableWidgetItem treats EditRole and DisplayRole as the *same* storage, so
    a typed sort value written to EditRole would replace what the cell shows.
    The sort value lives in UserRole instead and is compared here.

    Items with no sort value (or whose values aren't mutually comparable) fall
    back to comparing display text.

    NB: the fallback compares text directly rather than delegating with
    super().__lt__(other) — under PySide6 that re-enters this override instead
    of reaching the C++ base, recursing until the interpreter segfaults.
    """

    def __lt__(self, other: QTableWidgetItem) -> bool:
        mine = self.data(Qt.ItemDataRole.UserRole)
        theirs = other.data(Qt.ItemDataRole.UserRole)
        if mine is not None and theirs is not None:
            try:
                return mine < theirs
            except TypeError:
                pass
        return self.text() < other.text()


def _keycode_sort_key(keycode: str) -> str:
    """Zero-pad a key code so it sorts 1A, 1B, 2A, … instead of 10A, 1A, 2A.

    Compared as plain text "10A" sorts before "1A", because "0" < "A". Padding
    the number to two digits restores numeric order, which also keeps each
    number's A/B pair (relative minor/major) adjacent — so sorting by this
    column groups harmonically compatible tracks together.

    Unrecognized values (including "") are returned unchanged so they still
    sort deterministically rather than raising.
    """
    match = _KEYCODE_RE.fullmatch(keycode.strip())
    if not match:
        return keycode
    return f"{int(match.group(1)):02d}{match.group(2).upper()}"


class HistoryPanel(QWidget):
    """Panel for viewing rename history and recent key analysis results."""

    undo_session = Signal(RenameSession)
    # Emitted when the user picks a new row count, for the window to persist.
    history_limit_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sessions: list[RenameSession] = []
        self._entries: list[dict] = []
        self._display_limit = DEFAULT_HISTORY_DISPLAY_LIMIT
        self._loaded = False
        self._setup_ui()
        self._bg_overlay = BackgroundOverlay("bg_history.png", self)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._loaded:
            self._loaded = True
            self.refresh()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._bg_overlay.setGeometry(self.rect())

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Theme.PADDING, Theme.PADDING, Theme.PADDING, Theme.PADDING)
        layout.setSpacing(Theme.SPACING)

        # Title + description on one line (description flows to the title's right)
        self._title_label = QLabel(self.tr("Rename History"))
        self._title_label.setObjectName("sectionTitle")
        self._title_label.setStyleSheet(f"font-size: 24px; color: {Theme.NEON_YELLOW};")
        self._desc_label = QLabel(
            self.tr("View recent rename operations. Select a session to undo it.")
        )
        self._desc_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        layout.addLayout(panel_header_row(self._title_label, self._desc_label))

        # Sessions table
        self._table = QTableWidget()
        self._table.setObjectName("historyTable")
        self._table.setColumnCount(4)
        # Session ID is last: GUI users undo by selecting a row, so the id is
        # only a handle for the CLI ("mixed-in-p rename --undo <id>") and for
        # finding session_<id>.json on disk. Kept available, but pushed right of
        # the Description so it sits out of the way.
        self._table.setHorizontalHeaderLabels(
            [self.tr("Date/Time"), self.tr("Files"), self.tr("Description"), self.tr("Session ID")]
        )
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        # Show cell text in full (no "..." truncation); content that overflows a
        # column is revealed by scrolling the table horizontally, pixel-smooth.
        self._table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self._table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        header = self._table.horizontalHeader()
        # Date/Time is user-resizable; defaults wide enough for the full timestamp.
        header.setSectionResizeMode(_SESS_DATE, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(_SESS_FILES, QHeaderView.ResizeMode.Fixed)
        # Description grows to fit its filename preview rather than stretching to
        # fill, so long previews push past the edge and become scrollable — which
        # is also what carries Session ID off the right edge.
        header.setSectionResizeMode(_SESS_DESC, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_SESS_ID, QHeaderView.ResizeMode.Fixed)
        header.setStretchLastSection(False)
        self._table.setColumnWidth(_SESS_DATE, 170)
        self._table.setColumnWidth(_SESS_FILES, 60)
        self._table.setColumnWidth(_SESS_ID, 100)

        # Song keys table: recently analyzed tracks with their detection results
        self._keys_table = QTableWidget()
        self._keys_table.setObjectName("historyTable")
        self._keys_table.setColumnCount(9)
        self._keys_table.setHorizontalHeaderLabels([
            self.tr("Name"),
            self.tr("BPM"),
            self.tr("Conf"),
            self.tr("Key"),
            self.tr("Conf"),
            self.tr("Key Code"),
            self.tr("Alt Keys"),
            self.tr("Energy"),
            self.tr("Date/Time"),
        ])
        self._keys_table.setAlternatingRowColors(True)
        self._keys_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._keys_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._keys_table.verticalHeader().setVisible(False)
        self._keys_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self._keys_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        keys_header = self._keys_table.horizontalHeader()
        keys_header.setStretchLastSection(False)
        keys_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)  # Name
        for col in (1, 2, 3, 4, 5, 7):
            keys_header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
        # Alt Keys grows to fit the full alternatives text (never elided)
        keys_header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        keys_header.setSectionResizeMode(8, QHeaderView.ResizeMode.Interactive)  # Date/Time
        self._keys_table.setColumnWidth(0, 320)  # Name
        self._keys_table.setColumnWidth(1, 70)   # BPM
        self._keys_table.setColumnWidth(2, 65)   # BPM Conf
        self._keys_table.setColumnWidth(3, 70)   # Key
        self._keys_table.setColumnWidth(4, 65)   # Key Conf
        self._keys_table.setColumnWidth(5, 80)   # Key Code
        self._keys_table.setColumnWidth(7, 65)   # Energy
        self._keys_table.setColumnWidth(8, 170)  # Date/Time

        # Click a header to sort. Cells carry a typed sort value (see _item and
        # _SortableItem) because comparing the *display* string would order
        # "91%" before "9%", "100.0" before "91.5", and "10A" before "1A".
        # Default to Date/Time descending so the initial order still matches the
        # newest-first order load_entries() returns.
        self._keys_table.setSortingEnabled(True)
        self._keys_table.sortByColumn(8, Qt.SortOrder.DescendingOrder)

        # Stack the two views; the toggle buttons below switch between them
        self._stack = QStackedWidget()
        self._stack.addWidget(self._table)
        self._stack.addWidget(self._keys_table)
        layout.addWidget(self._stack, 1)

        # Bottom buttons
        button_layout = QHBoxLayout()

        # View toggles (styled like the Analyze panel's Auto toggle: the
        # active view's button fills neon yellow)
        self._sessions_btn = QPushButton(self.tr("{0} Rename Sessions").format(0))
        self._sessions_btn.setObjectName("autoToggle")
        self._sessions_btn.setCheckable(True)
        self._sessions_btn.setChecked(True)
        self._sessions_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        button_layout.addWidget(self._sessions_btn)

        self._keys_btn = QPushButton(self.tr("{0} Song Keys").format(0))
        self._keys_btn.setObjectName("autoToggle")
        self._keys_btn.setCheckable(True)
        self._keys_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        button_layout.addWidget(self._keys_btn)

        view_group = QButtonGroup(self)
        view_group.setExclusive(True)
        view_group.addButton(self._sessions_btn)
        view_group.addButton(self._keys_btn)
        self._sessions_btn.clicked.connect(lambda: self._set_view("sessions"))
        self._keys_btn.clicked.connect(lambda: self._set_view("keys"))

        button_layout.addStretch()

        # Row-count cap for whichever view is showing. A display limit only —
        # see set_history_limit. The label uses "Show" as the field name; the
        # counts themselves are numeric data and stay unwrapped.
        self._show_label = QLabel(self.tr("Show"))
        button_layout.addWidget(self._show_label)
        # A menu button, not a QComboBox: on macOS the combo's editable text
        # field fought the QSS padding and clipped "1000" behind the arrow. A
        # QToolButton auto-sizes to its label and pops a plain menu — the same
        # pattern as the header "Add" button.
        self._limit_btn = QToolButton()
        self._limit_btn.setObjectName("historyLimit")
        self._limit_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._limit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        limit_menu = QMenu(self._limit_btn)
        self._limit_actions: dict[int, object] = {}
        for value in HISTORY_DISPLAY_LIMITS:
            action = limit_menu.addAction(
                str(value), lambda v=value: self._on_limit_selected(v)
            )
            action.setCheckable(True)
            self._limit_actions[value] = action
        self._limit_btn.setMenu(limit_menu)
        self._sync_limit_button()
        button_layout.addWidget(self._limit_btn)

        self._export_btn = QPushButton(self.tr("Export CSV"))
        self._export_btn.setToolTip(
            self.tr("Export the table below to a spreadsheet-friendly CSV file.")
        )
        self._export_btn.clicked.connect(self._on_export_clicked)
        button_layout.addWidget(self._export_btn)

        # No manual Refresh button: MainWindow calls refresh() every time the
        # History page is shown, and Delete/limit changes refresh themselves, so
        # the view is never stale in normal use.
        self._delete_btn = QPushButton(self.tr("Delete"))
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        self._delete_btn.setEnabled(False)
        button_layout.addWidget(self._delete_btn)

        self._undo_btn = QPushButton(self.tr("Undo Selected"))
        self._undo_btn.setObjectName("primaryButton")
        self._undo_btn.clicked.connect(self._on_undo_clicked)
        self._undo_btn.setEnabled(False)
        button_layout.addWidget(self._undo_btn)

        layout.addLayout(button_layout)

        # Connect selection change
        self._table.selectionModel().selectionChanged.connect(self._on_selection_changed)

    def set_history_limit(self, limit: int) -> None:
        """Set how many rows each view shows, from persisted config.

        A *display* cap, not a retention cap: analysis entries are kept up to
        analysis.history.MAX_ENTRIES and session files are never deleted, so a
        larger limit surfaces rows that were stored all along. Unknown values
        fall back to the first option. Does not emit history_limit_changed —
        this is loading state, not a user edit.
        """
        if limit not in HISTORY_DISPLAY_LIMITS:
            limit = DEFAULT_HISTORY_DISPLAY_LIMIT
        self._display_limit = limit
        self._sync_limit_button()
        if self._loaded:
            self.refresh()

    def _sync_limit_button(self) -> None:
        """Point the menu button's label and checkmark at the current limit."""
        self._limit_btn.setText(str(self._display_limit))
        for value, action in self._limit_actions.items():
            action.setChecked(value == self._display_limit)

    def _on_limit_selected(self, limit: int) -> None:
        """User picked a new row count from the menu: apply, persist, redraw."""
        if limit == self._display_limit:
            return
        self._display_limit = limit
        self._sync_limit_button()
        self.history_limit_changed.emit(limit)
        self.refresh()

    def _set_view(self, view: str) -> None:
        """Switch between the rename-sessions and song-keys views."""
        keys = view == "keys"
        self._stack.setCurrentWidget(self._keys_table if keys else self._table)
        # Undo/Delete act on rename sessions only
        self._undo_btn.setVisible(not keys)
        self._delete_btn.setVisible(not keys)
        if keys:
            self._title_label.setText(self.tr("Key History"))
            self._desc_label.setText(
                self.tr("Recently analyzed tracks and their detected keys.")
            )
        else:
            self._title_label.setText(self.tr("Rename History"))
            self._desc_label.setText(
                self.tr("View recent rename operations. Select a session to undo it.")
            )

    @staticmethod
    def _format_alternatives(alternatives) -> str:
        """Render alternative keys with both notations, e.g. 'Fm (4A) 27%'."""
        parts = []
        for alt in alternatives or []:
            key = alt.get("key", "")
            keycode = alt.get("keycode", "")
            label = f"{key} ({keycode})" if key and keycode else key or keycode
            if label:
                parts.append(f"{label} {alt.get('confidence', 0.0):.0%}")
        return ", ".join(parts)

    def _refresh_keys(self) -> None:
        """Refresh the song-keys table from the analysis history file."""
        try:
            self._entries = load_analysis_entries()
        except Exception:
            self._entries = []

        # Show only the configured number of rows. self._entries stays the full
        # loaded list so export and the entry-index role still resolve; the
        # slice is a prefix, so a row's index maps into both alike.
        visible = self._entries[: self._display_limit]

        def _item(
            text: str, center: bool = False, sort_value: object | None = None
        ) -> QTableWidgetItem:
            item = _SortableItem(text)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if center:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            # Columns whose display text doesn't sort correctly (numbers
            # formatted as strings, key codes) pass the underlying value here;
            # _SortableItem compares it instead of the text.
            if sort_value is not None:
                item.setData(Qt.ItemDataRole.UserRole, sort_value)
            return item

        # Resolved once rather than per row.
        low_confidence_hint = self.tr(
            "Low confidence — this key is worth double-checking."
        )
        low_bpm_hint = self.tr(
            "Low confidence — the tempo may be half or double time."
        )

        # Sorting must be off while the table is populated: with it on, Qt
        # re-sorts after every setItem() and rows move out from under the loop.
        # Re-enabling re-applies the user's current sort column/order.
        self._keys_table.setSortingEnabled(False)
        self._keys_table.setRowCount(len(visible))
        for row, entry in enumerate(visible):
            bpm = entry.get("bpm")
            bpm_conf = entry.get("bpm_confidence")
            key_conf = entry.get("key_confidence")
            energy = entry.get("energy")
            timestamp = entry.get("timestamp", "")
            name = Path(entry.get("file_path", "")).name
            keycode = entry.get("keycode") or ""
            name_item = _item(name, sort_value=name.lower())
            name_item.setData(_ENTRY_INDEX_ROLE, row)
            self._keys_table.setItem(row, 0, name_item)
            self._keys_table.setItem(
                row,
                1,
                _item(f"{bpm:.1f}" if bpm else "", sort_value=float(bpm or -1.0)),
            )
            self._keys_table.setItem(
                row,
                2,
                _item(
                    f"{bpm_conf:.0%}" if bpm_conf is not None else "",
                    sort_value=float(bpm_conf if bpm_conf is not None else -1.0),
                ),
            )
            self._keys_table.setItem(row, 3, _item(entry.get("key") or ""))
            self._keys_table.setItem(
                row,
                4,
                _item(
                    f"{key_conf:.0%}" if key_conf is not None else "",
                    sort_value=float(key_conf if key_conf is not None else -1.0),
                ),
            )
            self._keys_table.setItem(
                row, 5, _item(keycode, sort_value=_keycode_sort_key(keycode))
            )
            self._keys_table.setItem(
                row, 6, _item(self._format_alternatives(entry.get("key_alternatives")))
            )
            self._keys_table.setItem(
                row,
                7,
                _item(
                    str(energy) if energy is not None else "",
                    center=True,
                    sort_value=int(energy if energy is not None else -1),
                ),
            )
            # Timestamps need no sort value: the "YYYY-MM-DD HH:MM:SS" display
            # form already sorts chronologically as text.
            self._keys_table.setItem(row, 8, _item(timestamp[:19].replace("T", " ")))

            # Tint the key-related cells when the detection is shaky. Only those
            # three: BPM and energy are unaffected by an uncertain key, and
            # colouring the whole row would overstate what's in doubt. Entries
            # with no confidence at all carry no detection to second-guess, so
            # they are left alone rather than flagged.
            if key_conf is not None and key_conf <= LOW_KEY_CONFIDENCE:
                for col in (3, 4, 5):  # Key, Key Conf, Key Code
                    cell = self._keys_table.item(row, col)
                    cell.setForeground(QColor(Theme.WARNING))
                    cell.setToolTip(low_confidence_hint)

            # Independently, tint the BPM cells on a shaky tempo. A row can have
            # either flag, both, or neither — an uncertain tempo says nothing
            # about the key, and vice versa.
            if bpm_conf is not None and bpm_conf <= LOW_BPM_CONFIDENCE:
                for col in (1, 2):  # BPM, BPM Conf
                    cell = self._keys_table.item(row, col)
                    cell.setForeground(QColor(Theme.WARNING))
                    cell.setToolTip(low_bpm_hint)
        self._keys_table.setSortingEnabled(True)

        # Count reflects what's shown, matching the table (may be capped by the
        # display limit below the number actually retained on disk).
        self._keys_btn.setText(self.tr("{0} Song Keys").format(len(visible)))

    def _refresh_sessions(self) -> None:
        """Refresh the sessions list from disk."""
        try:
            self._sessions = list_sessions(limit=self._display_limit)
        except Exception:
            self._sessions = []

        self._table.setRowCount(len(self._sessions))

        for row, session in enumerate(self._sessions):
            # Timestamp
            time_item = QTableWidgetItem(session.timestamp[:19].replace("T", " "))
            time_item.setFlags(time_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, _SESS_DATE, time_item)

            # File count
            count_item = QTableWidgetItem(str(session.file_count))
            count_item.setFlags(count_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, _SESS_FILES, count_item)

            # Session ID. The id is also stashed on the item so selection can be
            # resolved by identity rather than by row position — see
            # _get_selected_session.
            id_item = QTableWidgetItem(session.session_id)
            id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            id_item.setData(Qt.ItemDataRole.UserRole, session.session_id)
            self._table.setItem(row, _SESS_ID, id_item)

            # Description. The stored description is the English data string
            # "Renamed N files" (written by the rename worker / CLI and persisted
            # to disk), so localize the count-based form here from the structured
            # file_count rather than showing the raw English, and append a preview
            # of the first few original filenames so sessions are recognizable.
            # Any non-standard description is shown verbatim.
            if session.description.startswith("Renamed "):
                # records[:10] is safe for sessions with fewer than 10 files.
                names = [Path(r.original_path).name for r in session.records[:10]]
                # Filenames are data; the trailing ", …" marks "and more" and is
                # added only when the session has more files than the preview shows.
                preview = ", ".join(names)
                if session.file_count > len(names):
                    preview += ", …"
                description = self.tr("Renamed {0} files: {1}").format(
                    session.file_count, preview
                )
            else:
                description = session.description or self.tr("No description")
            desc_item = QTableWidgetItem(description)
            desc_item.setFlags(desc_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, _SESS_DESC, desc_item)

        self._sessions_btn.setText(
            self.tr("{0} Rename Sessions").format(len(self._sessions))
        )
        self._update_buttons()

    def _on_selection_changed(self) -> None:
        """Handle table selection change."""
        self._update_buttons()

    def _update_buttons(self) -> None:
        """Update button enabled states."""
        has_selection = len(self._table.selectionModel().selectedRows()) > 0
        self._undo_btn.setEnabled(has_selection)
        self._delete_btn.setEnabled(has_selection)

    def _get_selected_session(self) -> RenameSession | None:
        """Get the currently selected session.

        Resolved by session id carried on the row's own item, NOT by indexing
        self._sessions with the row number: sorting the table reorders the
        items while self._sessions keeps its original order, so a row index
        would point at the wrong session — and Undo/Delete would act on a
        session the user never selected.
        """
        selected = self._table.selectionModel().selectedRows()
        if not selected:
            return None

        item = self._table.item(selected[0].row(), _SESS_ID)
        if item is None:
            return None

        session_id = item.data(Qt.ItemDataRole.UserRole)
        return next(
            (s for s in self._sessions if s.session_id == session_id), None
        )

    # ---- CSV export -------------------------------------------------------

    def _showing_keys(self) -> bool:
        """True when the Song Keys view is the visible one."""
        return self._stack.currentWidget() is self._keys_table

    def _keys_export_rows(self) -> tuple[list[str], list[list]]:
        """Key History as (headers, rows), in the table's current sort order.

        Values are taken from the backing entries rather than the formatted
        cells, so confidences export as decimals (0.91) that a spreadsheet can
        compute with, not as the display string "91%".

        Alternative keys are the one lossy column: a list of {key, keycode,
        confidence} records flattened to text, because CSV rows cannot nest.
        """
        headers = [
            "File Name", "File Path", "BPM", "BPM Confidence", "Key",
            "Key Confidence", "Key Code", "Alternative Keys", "Energy",
            "Analyzed At",
        ]
        rows = []
        for row in range(self._keys_table.rowCount()):
            item = self._keys_table.item(row, 0)
            index = None if item is None else item.data(_ENTRY_INDEX_ROLE)
            if index is None or not 0 <= index < len(self._entries):
                continue
            entry = self._entries[index]
            rows.append([
                Path(entry.get("file_path", "")).name,
                entry.get("file_path", ""),
                entry.get("bpm"),
                entry.get("bpm_confidence"),
                entry.get("key", ""),
                entry.get("key_confidence"),
                entry.get("keycode", ""),
                self._format_alternatives(entry.get("key_alternatives")),
                entry.get("energy"),
                entry.get("timestamp", ""),
            ])
        return headers, rows

    def _sessions_export_rows(self) -> tuple[list[str], list[list]]:
        """Rename History as (headers, rows) — one row per renamed file.

        A session owns a list of records, which CSV cannot nest, so the session
        columns repeat across that session's file rows.
        """
        headers = [
            "Session ID", "Session Timestamp", "Original Path", "New Path",
            "Renamed At",
        ]
        rows = []
        for row in range(self._table.rowCount()):
            item = self._table.item(row, _SESS_ID)
            session_id = None if item is None else item.data(Qt.ItemDataRole.UserRole)
            session = next(
                (s for s in self._sessions if s.session_id == session_id), None
            )
            if session is None:
                continue
            for record in session.records:
                rows.append([
                    session.session_id,
                    session.timestamp,
                    record.original_path,
                    record.new_path,
                    record.timestamp,
                ])
        return headers, rows

    def _on_export_clicked(self) -> None:
        """Export the visible table to CSV."""
        keys = self._showing_keys()
        headers, rows = (
            self._keys_export_rows() if keys else self._sessions_export_rows()
        )

        if not rows:
            QMessageBox.information(
                self,
                self.tr("Export CSV"),
                self.tr("There is nothing to export yet."),
            )
            return

        # Filename is data, not UI prose — left untranslated so exported files
        # sort together regardless of the language the app is running in.
        default_name = "{0}-{1}.csv".format(
            "key-history" if keys else "rename-history",
            datetime.now().strftime("%Y-%m-%d"),
        )
        # Filter string is not wrapped: file-glob filters are config, not prose.
        path, _ = QFileDialog.getSaveFileName(
            self, self.tr("Export CSV"), default_name, "CSV (*.csv)"
        )
        if not path:
            return

        try:
            write_csv(path, headers, rows)
        except OSError as exc:
            QMessageBox.warning(
                self,
                self.tr("Export failed"),
                self.tr("Could not write the file:\n{0}").format(exc),
            )
            return

        QMessageBox.information(
            self,
            self.tr("Export complete"),
            self.tr("Exported {0} rows to:\n{1}").format(len(rows), path),
        )

    def _on_undo_clicked(self) -> None:
        """Handle undo button click."""
        session = self._get_selected_session()
        if session:
            self.undo_session.emit(session)

    def _on_delete_clicked(self) -> None:
        """Handle delete button click."""
        session = self._get_selected_session()
        if session:
            try:
                delete_session(session.session_id)
                self._refresh_sessions()
            except Exception:
                pass

    def refresh(self) -> None:
        """Public method to refresh both history views."""
        self._refresh_sessions()
        self._refresh_keys()
