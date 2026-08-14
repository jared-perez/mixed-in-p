"""Background reader for the playlist's artwork thumbnails.

Reading embedded art is a full tag parse per file — the same cost the player
header already pays on every track change — so a column of it cannot be built
on the main thread: a hundred-row playlist would freeze the window for as long
as a hundred tag reads take.

Only the rows actually on screen are ever read (the panel asks for a range and
re-asks as the view scrolls), and the result comes back as a **QImage**, not a
QPixmap: QPixmap may only be touched on the GUI thread, while QImage is a plain
buffer and can be decoded and scaled here, off it. The panel turns it into a
pixmap, which is cheap.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

from PySide6.QtCore import QObject, QSize, Qt, QThread, Signal
from PySide6.QtGui import QImage

logger = logging.getLogger(__name__)


class ArtworkWorker(QObject):
    """Read and scale embedded art for a list of paths, one signal per hit."""

    # path, scaled square thumbnail
    loaded = Signal(str, QImage)
    # path — the file has no art, or none we can read. Emitted so the panel can
    # remember the answer; without it every scroll past a coverless track would
    # queue the same fruitless tag parse again.
    empty = Signal(str)
    finished = Signal()

    def __init__(self, paths: Sequence[str], size: int, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._paths = list(paths)
        self._size = size
        self._cancelled = False

    def cancel(self) -> None:
        """Ask the run to stop. Checked between files — a single tag read is
        short, so there is nothing finer to interrupt."""
        self._cancelled = True

    def run(self) -> None:
        for path in self._paths:
            if self._cancelled:
                break
            image = self._thumbnail(path)
            if self._cancelled:
                break
            if image is None:
                self.empty.emit(path)
            else:
                self.loaded.emit(path, image)
        self.finished.emit()

    def _thumbnail(self, path: str) -> QImage | None:
        try:
            from src.metadata.tags import read_metadata

            data = read_metadata(path).artwork
        except Exception as exc:  # noqa: BLE001 — an unreadable tag is not fatal
            logger.debug("No artwork read for %s: %s", Path(path).name, exc)
            return None
        if not data:
            return None
        image = QImage()
        if not image.loadFromData(data):
            return None
        return image.scaled(
            QSize(self._size, self._size),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )


class ArtworkThread(QThread):
    """The thread the worker runs on. Owns nothing but the run loop."""

    def __init__(self, worker: ArtworkWorker, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._worker = worker
        worker.moveToThread(self)

    def run(self) -> None:
        self._worker.run()
