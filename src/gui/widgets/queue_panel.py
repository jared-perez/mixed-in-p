"""Queue panel for staging files before analysis."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..models import TrackState, TrackStore, TrackTableModel
from ..styles.theme import Theme, panel_header_row
from .droppable_table import DroppableTableView


class QueuePanel(QWidget):
    """Panel for queuing and staging files before analysis."""

    send_to_analysis = Signal(list)  # List of track IDs
    files_dropped = Signal(list)  # List of file paths

    def __init__(
        self,
        store: TrackStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._model = TrackTableModel(store)
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Theme.PADDING, Theme.PADDING, Theme.PADDING, Theme.PADDING)
        layout.setSpacing(Theme.SPACING)

        # Title + description on one line (description flows to the title's right)
        title = QLabel(self.tr("Queue"))
        title.setObjectName("sectionTitle")
        title.setStyleSheet(f"font-size: 24px; color: {Theme.NEON_YELLOW};")
        desc = QLabel(self.tr("Add files here to queue them for analysis. Use the buttons below to send them to analysis."))
        desc.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        layout.addLayout(panel_header_row(title, desc))

        # Queue table
        self._table = DroppableTableView(self.tr("Drop audio files here to add to queue"))
        self._table.setModel(self._model)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(DroppableTableView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(DroppableTableView.SelectionMode.ExtendedSelection)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)

        # Configure column widths
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Name
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # Artist
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)  # BPM
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)  # Key
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)  # Key Code
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)  # Energy
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)  # Status
        self._table.setColumnWidth(2, 60)
        self._table.setColumnWidth(3, 60)
        self._table.setColumnWidth(4, 70)
        self._table.setColumnWidth(5, 55)
        self._table.setColumnWidth(6, 100)

        layout.addWidget(self._table, 1)

        # Bottom buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(Theme.SPACING)

        self._count_label = QLabel(self.tr("0 files in queue"))
        self._count_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        button_layout.addWidget(self._count_label)

        button_layout.addStretch()

        self._clear_btn = QPushButton(self.tr("Clear Queue"))
        self._clear_btn.clicked.connect(self._on_clear_clicked)
        button_layout.addWidget(self._clear_btn)

        self._send_selected_btn = QPushButton(self.tr("Analyze Selected"))
        self._send_selected_btn.clicked.connect(self._on_send_selected_clicked)
        button_layout.addWidget(self._send_selected_btn)

        self._send_all_btn = QPushButton(self.tr("Analyze All"))
        self._send_all_btn.setObjectName("primaryButton")
        self._send_all_btn.clicked.connect(self._on_send_all_clicked)
        button_layout.addWidget(self._send_all_btn)

        layout.addLayout(button_layout)

    def _connect_signals(self) -> None:
        """Connect internal signals."""
        self._table.files_dropped.connect(self.files_dropped.emit)
        self._store.track_added.connect(self._update_count)
        self._store.track_removed.connect(self._update_count)
        self._store.tracks_cleared.connect(self._update_count)
        self._store.batch_update_finished.connect(self._update_count)

    def _update_count(self, *args) -> None:
        """Update the file count label."""
        queued = len(self._store.get_by_state(TrackState.QUEUED))
        total = self._store.count
        if queued == total:
            self._count_label.setText(self.tr("{total} files in queue").format(total=total))
        else:
            self._count_label.setText(
                self.tr("{queued} queued / {total} total files").format(queued=queued, total=total)
            )

    def _on_clear_clicked(self) -> None:
        """Clear all queued tracks."""
        # Only remove QUEUED tracks
        queued_tracks = self._store.get_by_state(TrackState.QUEUED)
        for track in queued_tracks:
            self._store.remove(track.id)

    def _on_send_selected_clicked(self) -> None:
        """Send selected tracks to analysis."""
        selected_ids: list[str] = []
        for index in self._table.selectionModel().selectedRows():
            track_id = self._model.get_track_id_at_row(index.row())
            if track_id:
                track = self._store.get(track_id)
                if track and track.state == TrackState.QUEUED:
                    selected_ids.append(track_id)

        if selected_ids:
            self.send_to_analysis.emit(selected_ids)

    def _on_send_all_clicked(self) -> None:
        """Send all queued tracks to analysis."""
        queued = self._store.get_by_state(TrackState.QUEUED)
        track_ids = [t.id for t in queued]
        if track_ids:
            self.send_to_analysis.emit(track_ids)

    def select_all(self) -> None:
        """Select all rows in the table."""
        self._table.selectAll()

    def clear_selection(self) -> None:
        """Clear the table selection."""
        self._table.clearSelection()
