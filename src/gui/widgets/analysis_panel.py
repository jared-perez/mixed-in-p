"""Analysis panel for real-time results display."""

from PySide6.QtCore import QCoreApplication, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)


class _NoFocusDelegate(QStyledItemDelegate):
    """Delegate that suppresses the focus rectangle on items."""

    def initStyleOption(self, option, index) -> None:
        super().initStyleOption(option, index)
        option.state &= ~QStyle.StateFlag.State_HasFocus

from src.analysis.keycode import render_key

from ..models import TrackState, TrackStore, TrackTableModel
from ..styles.theme import BackgroundOverlay, Theme, panel_header_row
from .droppable_table import DroppableTableView
from .progress_bar import ProgressPanel


class AnalysisTableModel(TrackTableModel):
    """Table model that only shows tracks being analyzed or already analyzed."""

    COLUMNS = [
        QCoreApplication.translate("AnalysisTableModel", "Name"),
        QCoreApplication.translate("AnalysisTableModel", "BPM"),
        QCoreApplication.translate("AnalysisTableModel", "Conf"),
        QCoreApplication.translate("AnalysisTableModel", "Key"),
        QCoreApplication.translate("AnalysisTableModel", "Conf"),
        QCoreApplication.translate("AnalysisTableModel", "Key Code"),
        QCoreApplication.translate("AnalysisTableModel", "Alt Keys"),
        QCoreApplication.translate("AnalysisTableModel", "Energy"),
        QCoreApplication.translate("AnalysisTableModel", "Status"),
    ]
    COLUMN_KEYS = [
        "display_name", "bpm", "bpm_confidence", "key", "key_confidence",
        "keycode", "key_alternatives", "energy", "state",
    ]

    def __init__(self, store: TrackStore, parent=None):
        super().__init__(store, parent)
        self._key_notation = "keycode"

    def set_key_notation(self, notation: str) -> None:
        """Set the display notation for alternative keys and repaint."""
        if notation == self._key_notation:
            return
        self._key_notation = notation
        self.beginResetModel()
        self.endResetModel()

    def _format_alternatives(self, alternatives) -> str:
        """Render runner-up keys compactly in the configured notation."""
        if not alternatives:
            return ""
        parts = []
        for alt in alternatives:
            label = render_key(
                alt.get("key", ""), alt.get("keycode", ""), self._key_notation
            )
            if label:
                parts.append(f"{label} {alt.get('confidence', 0.0):.0%}")
        return "  ".join(parts)

    def _alternatives_tooltip(self, alternatives) -> str:
        """Verbose tooltip for runner-up keys, showing both notations."""
        if not alternatives:
            return ""
        parts = []
        for alt in alternatives:
            key = alt.get("key", "")
            keycode = alt.get("keycode", "")
            label = f"{key} ({keycode})" if key and keycode else key or keycode
            parts.append(f"{label} {alt.get('confidence', 0.0):.0%}")
        return self.tr("Other likely keys: {keys}").format(keys=", ".join(parts))

    def _get_filtered_tracks(self) -> list:
        """Get tracks that are pending, analysing, analysed, or error."""
        valid_states = {
            TrackState.PENDING,
            TrackState.ANALYSING,
            TrackState.ANALYSED,
            TrackState.ERROR,
        }
        return [t for t in self._store.get_all() if t.state in valid_states]

    def flags(self, index):
        # Mark rows draggable so the view will start a drag (needed for the
        # drag-to-sidebar routing — QTableWidget rows get this by default, but a
        # model-backed QTableView does not unless the model advertises it).
        base = super().flags(index)
        if index.isValid():
            base |= Qt.ItemFlag.ItemIsDragEnabled
        return base

    def rowCount(self, parent=None):
        if parent and parent.isValid():
            return 0
        return len(self._get_filtered_tracks())

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        tracks = self._get_filtered_tracks()
        if index.row() >= len(tracks):
            return None

        track = tracks[index.row()]
        column = self.COLUMN_KEYS[index.column()]

        if role == Qt.ItemDataRole.DisplayRole:
            value = getattr(track, column, None)
            if column == "state":
                return value.value.title() if value else ""
            if column == "bpm" and value is not None:
                return f"{value:.1f}"
            if column in ("bpm_confidence", "key_confidence") and value is not None:
                return f"{value:.0%}"
            if column == "key_alternatives":
                return self._format_alternatives(value)
            return str(value) if value is not None else ""

        if role == Qt.ItemDataRole.ToolTipRole and column == "key_alternatives":
            return self._alternatives_tooltip(track.key_alternatives)

        if role == Qt.ItemDataRole.ForegroundRole:
            # Color based on state
            if track.state == TrackState.ERROR:
                from PySide6.QtGui import QColor
                return QColor(Theme.ERROR)
            if track.state == TrackState.ANALYSED:
                from PySide6.QtGui import QColor
                return QColor(Theme.NEON_GREEN)
            if track.state == TrackState.ANALYSING:
                from PySide6.QtGui import QColor
                return QColor(Theme.NEON_YELLOW)

        if role == Qt.ItemDataRole.UserRole:
            return getattr(track, column, None)

        if role == Qt.ItemDataRole.UserRole + 1:
            return track.id

        return None

    def get_track_at_row(self, row: int):
        tracks = self._get_filtered_tracks()
        if 0 <= row < len(tracks):
            return tracks[row]
        return None


class AnalysisPanel(QWidget):
    """Panel for analyzing files with real-time results."""

    files_dropped = Signal(list)  # List of file paths for immediate analysis
    cancel_analysis = Signal()
    send_to_player = Signal(list)  # List of track dicts for player
    send_to_convert = Signal(list)  # List of file path strings
    start_analysis = Signal()  # Manual analyze button clicked
    auto_analyze_toggled = Signal(bool)  # Auto button toggled (syncs with Settings)

    def __init__(
        self,
        store: TrackStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._model = AnalysisTableModel(store)
        self._auto_write_bpm = True
        self._auto_write_key = True
        self._auto_analyze = True
        self._analyzing = False
        self._setup_ui()
        self._connect_signals()
        self._bg_overlay = BackgroundOverlay("bg_analyze.png", self)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._bg_overlay.setGeometry(self.rect())

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Theme.PADDING, Theme.PADDING, Theme.PADDING, Theme.PADDING)
        layout.setSpacing(Theme.SPACING)

        # Title + description on one line (description flows to the title's right)
        title = QLabel(self.tr("Analyze"))
        title.setObjectName("sectionTitle")
        title.setStyleSheet(f"font-size: 24px; color: {Theme.NEON_YELLOW};")
        desc = QLabel(self.tr("Drop files to analyze, unless changed in settings. Results update in real-time."))
        desc.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        header_row = panel_header_row(title, desc)

        # "Auto" toggle pinned to the far right of the header — a second control
        # for the "Auto-analyze when dropping or sending to the Analyze panel"
        # setting. It mirrors (and drives) the Settings checkbox: yellow when on.
        self._auto_btn = QPushButton(self.tr("Auto"))
        self._auto_btn.setObjectName("autoToggle")
        self._auto_btn.setCheckable(True)
        self._auto_btn.setChecked(self._auto_analyze)
        self._auto_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._auto_btn.setToolTip(
            self.tr("Auto-analyze when dropping or sending to the Analyze panel")
        )
        self._auto_btn.clicked.connect(self._on_auto_toggled)
        header_row.addWidget(self._auto_btn, 0, Qt.AlignmentFlag.AlignBottom)

        layout.addLayout(header_row)

        # Progress panel (initially hidden)
        self._progress_panel = ProgressPanel(show_activity=True)
        self._progress_panel.cancel_clicked.connect(self.cancel_analysis.emit)
        layout.addWidget(self._progress_panel)

        # Results table
        self._table = DroppableTableView(self.tr("Drop files here to analyze immediately"), bottom_quarter=True)
        self._table.setModel(self._model)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(DroppableTableView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(DroppableTableView.SelectionMode.ExtendedSelection)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._table.setItemDelegate(_NoFocusDelegate(self._table))

        # Configure column widths. Name is interactive (fixed-but-draggable) so
        # the contents don't reflow as the window resizes; a horizontal scrollbar
        # appears when the columns overflow.
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)  # Name
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)  # BPM
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)  # BPM Conf
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)  # Key
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)  # Key Conf
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)  # Key Code
        # Alt Keys sizes to its contents so the alternatives are never elided
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)  # Energy
        header.setSectionResizeMode(8, QHeaderView.ResizeMode.Fixed)  # Status
        self._table.setColumnWidth(0, 360)  # Name
        self._table.setColumnWidth(1, 80)   # BPM
        self._table.setColumnWidth(2, 75)   # BPM Conf
        self._table.setColumnWidth(3, 80)   # Key
        self._table.setColumnWidth(4, 75)   # Key Conf
        self._table.setColumnWidth(5, 80)   # Key Code
        self._table.setColumnWidth(7, 60)   # Energy
        self._table.setColumnWidth(8, 100)  # Status

        layout.addWidget(self._table, 1)

        # Bottom row with stats
        bottom_row = QHBoxLayout()

        self._stats_label = QLabel("")
        self._stats_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        bottom_row.addWidget(self._stats_label)

        bottom_row.addStretch()

        self._clear_btn = QPushButton(self.tr("Clear Results"))
        self._clear_btn.clicked.connect(self._on_clear_clicked)
        bottom_row.addWidget(self._clear_btn)

        self._analyze_btn = QPushButton(self.tr("Analyze"))
        self._analyze_btn.setObjectName("primaryButton")
        self._analyze_btn.setMinimumWidth(160)
        self._analyze_btn.setEnabled(False)
        self._analyze_btn.clicked.connect(self._on_analyze_clicked)
        bottom_row.addWidget(self._analyze_btn)

        self._send_to_btn = QPushButton(self.tr("Send To"))
        send_to_menu = QMenu(self._send_to_btn)
        self._send_to_convert_action = send_to_menu.addAction(self.tr("Convert"))
        self._send_to_player_action = send_to_menu.addAction(self.tr("Player"))
        self._send_to_btn.setMenu(send_to_menu)
        bottom_row.addWidget(self._send_to_btn)

        layout.addLayout(bottom_row)

        self._update_stats()

    def _connect_signals(self) -> None:
        """Connect internal signals."""
        self._table.files_dropped.connect(self.files_dropped.emit)
        self._store.track_updated.connect(self._update_stats)
        self._store.batch_update_finished.connect(self._update_stats)
        self._send_to_convert_action.triggered.connect(self._on_send_to_convert)
        self._send_to_player_action.triggered.connect(self._send_selected_to_player)
        # Drag selected (sendable) rows onto a sidebar nav button to route them.
        self._table.enable_drag_out("analysis", self._drag_data)

    def _selected_sendable_paths(self) -> tuple[list[str], list[str]]:
        """Return (file_paths, track_ids) for selected rows in a sendable state."""
        paths: list[str] = []
        ids: list[str] = []
        for idx in self._table.selectionModel().selectedRows():
            track = self._model.get_track_at_row(idx.row())
            if track and track.state in self._SENDABLE_STATES:
                paths.append(track.file_path)
                ids.append(track.id)
        return paths, ids

    def _drag_data(self):
        """Provide (paths, remove-on-move callback) for an outgoing drag."""
        paths, ids = self._selected_sendable_paths()
        if not paths:
            return None

        def remove() -> None:
            for tid in ids:
                self._store.remove(tid)

        return paths, remove

    @property
    def auto_write_bpm(self) -> bool:
        """Whether to auto-write BPM to tags after analysis."""
        return self._auto_write_bpm

    def set_auto_write_bpm(self, enabled: bool) -> None:
        """Set the auto-write-BPM flag (driven by the Settings panel)."""
        self._auto_write_bpm = enabled

    @property
    def auto_write_key(self) -> bool:
        """Whether to auto-write the key to tags after analysis."""
        return self._auto_write_key

    def set_auto_write_key(self, enabled: bool) -> None:
        """Set the auto-write-key flag (driven by the Settings panel)."""
        self._auto_write_key = enabled

    def set_key_notation(self, notation: str) -> None:
        """Set the key notation used for the Alt Keys column (from Settings)."""
        self._model.set_key_notation(notation)

    def _update_stats(self, *args) -> None:
        """Update the stats label and Analyze button state."""
        analysed = len(self._store.get_by_state(TrackState.ANALYSED))
        errors = len(self._store.get_by_state(TrackState.ERROR))
        pending = len(self._store.get_by_state(TrackState.PENDING))
        analysing = len(self._store.get_by_state(TrackState.ANALYSING))

        parts = []
        if analysed > 0:
            parts.append(self.tr("{n} analyzed").format(n=analysed))
        if errors > 0:
            parts.append(self.tr("{n} errors").format(n=errors))
        if pending > 0 and analysing == 0:
            parts.append(self.tr("{n} pending").format(n=pending))
        elif analysing > 0:
            parts.append(self.tr("{n} in progress").format(n=pending + analysing))

        self._stats_label.setText(" | ".join(parts) if parts else self.tr("No results yet"))

        # Analyze button: enabled only in manual mode, when tracks are waiting and
        # no batch is currently running. Disabling it during a run means files
        # dropped in while analyzing simply pile up in the queue; the button lights
        # back up when the batch stops so the user can start them when they like.
        self._analyze_btn.setEnabled(
            not self._auto_analyze and pending > 0 and not self._analyzing
        )

    def set_analyzing(self, running: bool) -> None:
        """Mark whether a batch is currently running (drives the Analyze button).

        While running, the manual Analyze button is disabled so newly dropped
        files just queue up; once the batch stops it re-enables if tracks remain.
        """
        self._analyzing = running
        self._update_stats()

    def set_auto_analyze(self, enabled: bool) -> None:
        """Set the auto-analyze flag and sync the Auto toggle + button state.

        Driven by the Settings panel (and at startup), so the Auto button always
        reflects the current setting. setChecked does not fire ``clicked``, so
        this won't re-emit ``auto_analyze_toggled``.
        """
        self._auto_analyze = enabled
        self._auto_btn.setChecked(enabled)
        self._update_stats()

    def _on_auto_toggled(self, checked: bool) -> None:
        """Handle the Auto toggle — update local state and notify the app."""
        self._auto_analyze = checked
        self._update_stats()
        self.auto_analyze_toggled.emit(checked)

    def _on_analyze_clicked(self) -> None:
        """Handle manual Analyze button click."""
        self.start_analysis.emit()

    def _on_remove_selected(self) -> None:
        """Remove selected tracks from the store."""
        rows = self._table.selectionModel().selectedRows()
        track_ids = []
        for idx in rows:
            track = self._model.get_track_at_row(idx.row())
            if track:
                track_ids.append(track.id)
        for tid in track_ids:
            self._store.remove(tid)

    def _on_context_menu(self, pos) -> None:
        """Show context menu on table right-click."""
        if not self._table.selectionModel().hasSelection():
            return
        menu = QMenu(self)
        open_location_action = menu.addAction(self.tr("Open File Location"))
        menu.addSeparator()
        remove_action = menu.addAction(self.tr("Remove"))
        action = menu.exec(self._table.viewport().mapToGlobal(pos))
        if action == open_location_action:
            self._on_open_file_location()
        elif action == remove_action:
            self._on_remove_selected()

    def _on_open_file_location(self) -> None:
        """Reveal the first selected track's containing folder in the OS file manager."""
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        track = self._model.get_track_at_row(rows[0].row())
        if track:
            self._reveal_in_explorer(track.file_path)

    @staticmethod
    def _reveal_in_explorer(file_path: str) -> None:
        """Open the OS file manager to the folder containing the given file."""
        import os
        import sys
        from pathlib import Path

        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        path = Path(file_path)
        folder = path.parent if path.parent.exists() else path
        if sys.platform == "win32":
            os.startfile(str(folder))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    _SENDABLE_STATES = {TrackState.ANALYSED, TrackState.PENDING}

    def _on_send_to_convert(self) -> None:
        """Gather selected tracks and emit send_to_convert signal."""
        file_paths, track_ids = self._selected_sendable_paths()
        if file_paths:
            self.send_to_convert.emit(file_paths)
            for tid in track_ids:
                self._store.remove(tid)

    def _send_selected_to_player(self) -> None:
        """Gather selected tracks and emit send_to_player signal."""
        from src.metadata.tags import read_metadata

        rows = self._table.selectionModel().selectedRows()
        tracks: list[dict] = []
        track_ids: list[str] = []
        for idx in rows:
            track = self._model.get_track_at_row(idx.row())
            if track and track.state in self._SENDABLE_STATES:
                # Prefer the value literally stored in the file's key tag (which may
                # be Key Code, classic, or whatever the user wrote) over the analyzer's
                # detected classic key.
                file_key = ""
                try:
                    meta = read_metadata(track.file_path)
                    if meta.key:
                        file_key = meta.key
                except Exception:
                    pass
                tracks.append({
                    "file_path": track.file_path,
                    "display_name": track.display_name,
                    "bpm": f"{track.bpm:.1f}" if track.bpm else "",
                    "key": file_key or (track.key or ""),
                })
                track_ids.append(track.id)
        if tracks:
            self.send_to_player.emit(tracks)
            for tid in track_ids:
                self._store.remove(tid)

    def _on_clear_clicked(self) -> None:
        """Clear all analyzed tracks."""
        # Remove tracks that are analysed or error
        for state in (TrackState.ANALYSED, TrackState.ERROR):
            for track in self._store.get_by_state(state):
                self._store.remove(track.id)

    @property
    def progress_panel(self) -> ProgressPanel:
        """Get the progress panel widget."""
        return self._progress_panel

    def refresh_table(self) -> None:
        """Force a refresh of the table model."""
        self._model.beginResetModel()
        self._model.endResetModel()
