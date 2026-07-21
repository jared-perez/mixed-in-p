"""History panel for viewing and undoing rename sessions."""

import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.analysis.history import load_entries as load_analysis_entries
from src.renamer import RenameSession, delete_session, list_sessions, load_session

from ..styles.theme import BackgroundOverlay, Theme, panel_header_row

_KEYCODE_RE = re.compile(r"(\d{1,2})([AB])", re.IGNORECASE)


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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sessions: list[RenameSession] = []
        self._entries: list[dict] = []
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
        self._table.setHorizontalHeaderLabels(
            [self.tr("Session ID"), self.tr("Date/Time"), self.tr("Files"), self.tr("Description")]
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
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        # Date/Time is user-resizable; defaults wide enough for the full timestamp.
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        # Description grows to fit its filename preview rather than stretching to
        # fill, so long previews push past the edge and become scrollable.
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(False)
        self._table.setColumnWidth(0, 100)
        self._table.setColumnWidth(1, 170)
        self._table.setColumnWidth(2, 60)

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

        self._refresh_btn = QPushButton(self.tr("Refresh"))
        self._refresh_btn.clicked.connect(self.refresh)
        button_layout.addWidget(self._refresh_btn)

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

        # Sorting must be off while the table is populated: with it on, Qt
        # re-sorts after every setItem() and rows move out from under the loop.
        # Re-enabling re-applies the user's current sort column/order.
        self._keys_table.setSortingEnabled(False)
        self._keys_table.setRowCount(len(self._entries))
        for row, entry in enumerate(self._entries):
            bpm = entry.get("bpm")
            bpm_conf = entry.get("bpm_confidence")
            key_conf = entry.get("key_confidence")
            energy = entry.get("energy")
            timestamp = entry.get("timestamp", "")
            name = Path(entry.get("file_path", "")).name
            keycode = entry.get("keycode") or ""
            self._keys_table.setItem(
                row, 0, _item(name, sort_value=name.lower())
            )
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
        self._keys_table.setSortingEnabled(True)

        self._keys_btn.setText(self.tr("{0} Song Keys").format(len(self._entries)))

    def _refresh_sessions(self) -> None:
        """Refresh the sessions list from disk."""
        try:
            self._sessions = list_sessions(limit=50)
        except Exception:
            self._sessions = []

        self._table.setRowCount(len(self._sessions))

        for row, session in enumerate(self._sessions):
            # Session ID
            id_item = QTableWidgetItem(session.session_id)
            id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 0, id_item)

            # Timestamp
            time_item = QTableWidgetItem(session.timestamp[:19].replace("T", " "))
            time_item.setFlags(time_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 1, time_item)

            # File count
            count_item = QTableWidgetItem(str(session.file_count))
            count_item.setFlags(count_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 2, count_item)

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
            self._table.setItem(row, 3, desc_item)

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
        """Get the currently selected session."""
        selected = self._table.selectionModel().selectedRows()
        if not selected:
            return None

        row = selected[0].row()
        if 0 <= row < len(self._sessions):
            return self._sessions[row]
        return None

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
