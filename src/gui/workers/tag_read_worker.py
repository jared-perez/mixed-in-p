"""Background reader for the playlist's metadata tags.

The Player fills a row's Artist/Title/BPM/Key/Comment/Year/Duration from the
library when it can, and from the file's own tags when it cannot. That second
path is a full mutagen parse per file, and it is not cheap where it matters
most: measured on a FAT32 USB stick, a cold ``read_metadata`` is ~21 ms against
~1 ms warm, so a 99-track playlist whose rows are missing a BPM spent one and a
half seconds with the window frozen before anything appeared.

So the read happens here instead, and the rows go up blank-but-visible first.
Same files, same tags, same "only ever fill a blank" rule — the only thing that
changed is which thread waits for the disk.

Results come back in **batches** rather than one signal per file: a queued
cross-thread signal per row would have the panel patching cells (and Qt
repainting them) 99 times for a list it could redraw once. The batch size is
small enough that the first rows still appear almost immediately.

Like :class:`~src.gui.workers.artwork_worker.ArtworkWorker`, ``run()`` is a
plain loop and not an event loop, so ``quit()`` means nothing to it — a caller
that wants it to stop early must call :meth:`cancel`, which is checked between
files.
"""

from __future__ import annotations

import logging
from typing import Sequence

from PySide6.QtCore import QObject, QThread, Signal

logger = logging.getLogger(__name__)

# How many files are read before the batch is handed back. Chosen so the first
# rows land fast (8 cold files off the slowest medium measured is ~170 ms)
# while a long playlist still costs a handful of patches rather than one per
# row. Nothing depends on the exact number.
_BATCH = 8


class TagReadWorker(QObject):
    """Read tags for a list of paths off the GUI thread, in batches."""

    # list[tuple[str, TrackMetadata | None]] — one entry per file *attempted*,
    # with None for one that could not be read.
    #
    # The failures have to be reported, not dropped. A row stays marked as
    # unread until its answer arrives, and an unread row wears a placeholder;
    # a file that is missing, unreadable or not really audio would otherwise
    # sit there promising an answer that was never coming.
    batch = Signal(object)
    finished = Signal()

    def __init__(self, paths: Sequence[str], parent: QObject | None = None) -> None:
        super().__init__(parent)
        # De-duplicated by the caller; kept as a plain list so the order it
        # chose (what is on screen first) survives.
        self._paths = list(paths)
        self._cancelled = False

    def cancel(self) -> None:
        """Ask the run to stop. Checked between files — a single tag read is
        short, so there is nothing finer to interrupt."""
        self._cancelled = True

    def run(self) -> None:
        # Imported here rather than at module scope so merely importing this
        # worker does not pull mutagen in. Safe because our only caller,
        # PlayerPanel, imports `read_metadata` at ITS module scope — so the
        # GUI thread has completed the import before any reader thread can
        # start. Two threads reaching a lazy import of mutagen (->
        # charset_normalizer) together aborts the interpreter outright.
        from src.metadata.tags import read_metadata

        pending: list[tuple[str, object]] = []
        for path in self._paths:
            if self._cancelled:
                break
            try:
                pending.append((path, read_metadata(path)))
            except Exception as exc:  # noqa: BLE001
                # Unreadable, missing, or a format mutagen will not open. The
                # row keeps whatever the library gave it — but it is still
                # reported, so it stops being *pending*.
                logger.debug("Tag read failed for %s: %s", path, exc)
                pending.append((path, None))
            if len(pending) >= _BATCH:
                self.batch.emit(pending)
                pending = []
        # Whatever is left, including on a cancel: these files were read, and
        # throwing the answers away would mean reading them again.
        if pending:
            self.batch.emit(pending)
        self.finished.emit()


class TagReadThread(QThread):
    """The thread the worker runs on. Owns nothing but the run loop."""

    def __init__(self, worker: TagReadWorker, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._worker = worker
        worker.moveToThread(self)

    def run(self) -> None:
        self._worker.run()
