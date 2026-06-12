"""History panel for viewing and undoing rename sessions."""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.renamer import RenameSession, delete_session, list_sessions, load_session

from ..styles.theme import BackgroundOverlay, Theme, panel_header_row


class HistoryPanel(QWidget):
    """Panel for viewing and managing rename history."""

    undo_session = Signal(RenameSession)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sessions: list[RenameSession] = []
        self._loaded = False
        self._setup_ui()
        self._bg_overlay = BackgroundOverlay("bg_history.png", self)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._loaded:
            self._loaded = True
            self._refresh_sessions()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._bg_overlay.setGeometry(self.rect())

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Theme.PADDING, Theme.PADDING, Theme.PADDING, Theme.PADDING)
        layout.setSpacing(Theme.SPACING)

        # Title + description on one line (description flows to the title's right)
        title = QLabel(self.tr("Rename History"))
        title.setObjectName("sectionTitle")
        title.setStyleSheet(f"font-size: 24px; color: {Theme.NEON_YELLOW};")
        desc = QLabel(self.tr("View recent rename operations. Select a session to undo it."))
        desc.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        layout.addLayout(panel_header_row(title, desc))

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

        layout.addWidget(self._table, 1)

        # Bottom buttons
        button_layout = QHBoxLayout()

        self._count_label = QLabel(self.tr("0 sessions"))
        self._count_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        button_layout.addWidget(self._count_label)

        button_layout.addStretch()

        self._refresh_btn = QPushButton(self.tr("Refresh"))
        self._refresh_btn.clicked.connect(self._refresh_sessions)
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

        self._count_label.setText(self.tr("{0} sessions").format(len(self._sessions)))
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
        """Public method to refresh the panel."""
        self._refresh_sessions()
