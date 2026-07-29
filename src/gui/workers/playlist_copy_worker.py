"""Background worker for "Export and Copy Tracks…".

Copying a set is the one export that isn't instant — a two-hour playlist of
lossless files is several GB, which would freeze the UI for tens of seconds
on the main thread. The copying itself lives in
:func:`src.library.playlist_export.copy_playlist_tracks` (Qt-free and
unit-tested); this only moves it onto a thread and reports progress.

Mirrors ``ConversionThread``: a ``QThread`` subclass whose ``run`` drives the
plain function and re-emits its progress as signals.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from src.library.playlist_export import (
    ExportTrack,
    copy_playlist_tracks,
    write_playlist,
)

logger = logging.getLogger(__name__)


@dataclass
class CopyProgress:
    """Progress update from the copy worker."""

    completed: int
    total: int
    current_file: str


class PlaylistCopyThread(QThread):
    """Copy a playlist's audio into a folder, then write the playlist file."""

    progress = Signal(CopyProgress)
    # playlist file path, tracks written, paths that could not be found
    completed = Signal(str, int, list)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        tracks: list[ExportTrack],
        directory: str | Path,
        playlist_name: str,
        *,
        fmt: str = "m3u8",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._tracks = tracks
        self._directory = Path(directory)
        self._playlist_name = playlist_name
        self._fmt = fmt
        self._cancelled = False

    def cancel(self) -> None:
        """Ask the copy to stop; it checks between files."""
        self._cancelled = True

    def run(self) -> None:
        try:
            copied, missing = copy_playlist_tracks(
                self._tracks,
                self._directory,
                on_progress=lambda done, total, name: self.progress.emit(
                    CopyProgress(done, total, name)
                ),
                is_cancelled=lambda: self._cancelled,
            )
            if self._cancelled:
                self.cancelled.emit()
                return
            # Written last, and only on success: a folder with a playlist
            # file in it should always be a complete, playable folder. Paths
            # come out relative because everything now sits right here.
            target = self._directory / f"{self._directory.name}.{self._fmt}"
            count = write_playlist(
                target, copied, fmt=self._fmt, title=self._playlist_name
            )
        except (OSError, ValueError) as exc:
            logger.error("Copy-tracks export failed: %s", exc)
            self.failed.emit(str(exc))
            return
        self.completed.emit(str(target), count, missing)
