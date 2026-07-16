"""Track data models and Qt table model."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    Qt,
    Signal,
)

from .state import TrackState


@dataclass
class TrackItem:
    """A single track in the application."""

    file_path: str
    original_name: str
    display_name: str
    state: TrackState = TrackState.QUEUED
    id: str = field(default_factory=lambda: str(uuid4())[:8])

    # Analysis results (populated after analysis)
    bpm: float | None = None
    bpm_confidence: float | None = None
    key: str | None = None
    key_confidence: float | None = None
    keycode: str | None = None
    key_alternatives: list | None = None  # [{"key", "keycode", "confidence"}, ...]
    energy: int | None = None

    # Metadata from file
    artist: str | None = None
    title: str | None = None

    # Rename preview
    preview_name: str | None = None

    # Error message if state is ERROR
    error_message: str | None = None

    @classmethod
    def from_path(cls, file_path: str) -> "TrackItem":
        """Create a TrackItem from a file path."""
        path = Path(file_path)
        return cls(
            file_path=str(path.resolve()),
            original_name=path.name,
            display_name=path.name,
        )

    @property
    def directory(self) -> str:
        """Get the directory containing this track."""
        return str(Path(self.file_path).parent)

    @property
    def extension(self) -> str:
        """Get the file extension."""
        return Path(self.file_path).suffix.lower()


class TrackStore(QObject):
    """Central store for all tracks with signal notifications."""

    # Signals for state changes
    track_added = Signal(str)  # track_id
    track_removed = Signal(str)  # track_id
    track_updated = Signal(str)  # track_id
    tracks_cleared = Signal()
    batch_update_started = Signal()
    batch_update_finished = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tracks: dict[str, TrackItem] = {}
        self._order: list[str] = []  # Track IDs in order
        self._batch_updating = False

    @property
    def count(self) -> int:
        """Number of tracks in the store."""
        return len(self._tracks)

    def get(self, track_id: str) -> TrackItem | None:
        """Get a track by ID."""
        return self._tracks.get(track_id)

    def get_by_path(self, file_path: str) -> TrackItem | None:
        """Get a track by file path."""
        for track in self._tracks.values():
            if track.file_path == file_path:
                return track
        return None

    def get_all(self) -> list[TrackItem]:
        """Get all tracks in order."""
        return [self._tracks[tid] for tid in self._order if tid in self._tracks]

    def get_by_state(self, state: TrackState) -> list[TrackItem]:
        """Get all tracks with a specific state."""
        return [t for t in self.get_all() if t.state == state]

    def add(self, track: TrackItem) -> None:
        """Add a track to the store."""
        if track.id in self._tracks:
            return

        # Check for duplicate file path
        if self.get_by_path(track.file_path) is not None:
            return

        self._tracks[track.id] = track
        self._order.append(track.id)

        if not self._batch_updating:
            self.track_added.emit(track.id)

    def add_from_path(self, file_path: str) -> TrackItem | None:
        """Create and add a track from a file path.

        Returns the created track, or None if already exists.
        """
        if self.get_by_path(file_path) is not None:
            return None

        track = TrackItem.from_path(file_path)
        self.add(track)
        return track

    def remove(self, track_id: str) -> None:
        """Remove a track from the store."""
        if track_id not in self._tracks:
            return

        del self._tracks[track_id]
        self._order.remove(track_id)

        if not self._batch_updating:
            self.track_removed.emit(track_id)

    def update(self, track_id: str, **kwargs: Any) -> None:
        """Update a track's attributes."""
        track = self._tracks.get(track_id)
        if track is None:
            return

        for key, value in kwargs.items():
            if hasattr(track, key):
                setattr(track, key, value)

        if not self._batch_updating:
            self.track_updated.emit(track_id)

    def clear(self) -> None:
        """Remove all tracks."""
        self._tracks.clear()
        self._order.clear()
        self.tracks_cleared.emit()

    def begin_batch_update(self) -> None:
        """Begin a batch update (suppresses individual signals)."""
        self._batch_updating = True
        self.batch_update_started.emit()

    def end_batch_update(self) -> None:
        """End a batch update (emits batch_update_finished)."""
        self._batch_updating = False
        self.batch_update_finished.emit()


class TrackTableModel(QAbstractTableModel):
    """Qt table model for displaying tracks."""

    COLUMNS = ["Name", "Artist", "BPM", "Key", "Key Code", "Energy", "Status"]
    COLUMN_KEYS = ["display_name", "artist", "bpm", "key", "keycode", "energy", "state"]

    def __init__(self, store: TrackStore, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._connect_store_signals()

    def _connect_store_signals(self) -> None:
        """Connect to store signals for automatic updates."""
        self._store.track_added.connect(self._on_track_added)
        self._store.track_removed.connect(self._on_track_removed)
        self._store.track_updated.connect(self._on_track_updated)
        self._store.tracks_cleared.connect(self._on_tracks_cleared)
        self._store.batch_update_finished.connect(self._on_batch_finished)

    def _on_track_added(self, track_id: str) -> None:
        """Handle track added."""
        index = self._get_row_for_id(track_id)
        if index >= 0:
            self.beginInsertRows(QModelIndex(), index, index)
            self.endInsertRows()

    def _on_track_removed(self, track_id: str) -> None:
        """Handle track removed."""
        # Note: Row already removed from store, so we reset
        self.beginResetModel()
        self.endResetModel()

    def _on_track_updated(self, track_id: str) -> None:
        """Handle track updated."""
        row = self._get_row_for_id(track_id)
        if row >= 0:
            top_left = self.index(row, 0)
            bottom_right = self.index(row, len(self.COLUMNS) - 1)
            self.dataChanged.emit(top_left, bottom_right)

    def _on_tracks_cleared(self) -> None:
        """Handle tracks cleared."""
        self.beginResetModel()
        self.endResetModel()

    def _on_batch_finished(self) -> None:
        """Handle batch update finished."""
        self.beginResetModel()
        self.endResetModel()

    def _get_row_for_id(self, track_id: str) -> int:
        """Get the row index for a track ID."""
        tracks = self._store.get_all()
        for i, track in enumerate(tracks):
            if track.id == track_id:
                return i
        return -1

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Return number of rows."""
        if parent.isValid():
            return 0
        return self._store.count

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Return number of columns."""
        if parent.isValid():
            return 0
        return len(self.COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Return data for a cell."""
        if not index.isValid():
            return None

        tracks = self._store.get_all()
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
            return str(value) if value is not None else ""

        if role == Qt.ItemDataRole.UserRole:
            # Return raw value for sorting/filtering
            return getattr(track, column, None)

        if role == Qt.ItemDataRole.UserRole + 1:
            # Return track ID
            return track.id

        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        """Return header data."""
        if role != Qt.ItemDataRole.DisplayRole:
            return None

        if orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self.COLUMNS):
                return self.COLUMNS[section]

        return None

    def get_track_at_row(self, row: int) -> TrackItem | None:
        """Get the track at a specific row."""
        tracks = self._store.get_all()
        if 0 <= row < len(tracks):
            return tracks[row]
        return None

    def get_track_id_at_row(self, row: int) -> str | None:
        """Get the track ID at a specific row."""
        track = self.get_track_at_row(row)
        return track.id if track else None
