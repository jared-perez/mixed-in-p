"""Background worker for "Find in Folder…" (the missing-file relocate scan).

Scanning a drive is the slow half of relocating: the walk itself is cheap,
but a folder with thousands of audio files means thousands of ``stat``
calls and a 64 KB read for every size that some missing track wants. On a
spinning external drive — exactly where a relocated set tends to live —
that is seconds, not milliseconds.

The matching lives in :mod:`src.library.relocate` (Qt-free and unit
tested); this only moves it onto a thread. Mirrors ``PlaylistCopyThread``:
a ``QThread`` subclass whose ``run`` drives the plain function and
re-emits its progress as signals. The database is *not* touched here —
the scan returns matches and the main thread applies them, so no second
connection is needed for a handful of fast UPDATEs.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

from PySide6.QtCore import QObject, QThread, Signal

from src.library.library import Track
from src.library.relocate import RelocateResult, find_matches

logger = logging.getLogger(__name__)


class RelocateScanThread(QThread):
    """Scan a folder for the files behind a set of missing tracks."""

    #: files examined, files total, current filename
    progress = Signal(int, int, str)
    #: a RelocateResult, ready to apply
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        missing: Sequence[Track],
        folder: str | Path,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._missing = list(missing)
        self._folder = Path(folder)
        self._cancelled = False

    def cancel(self) -> None:
        """Ask the scan to stop; it checks between files."""
        self._cancelled = True

    def run(self) -> None:
        try:
            result: RelocateResult = find_matches(
                self._missing,
                self._folder,
                on_progress=lambda done, total, name: self.progress.emit(
                    done, total, name
                ),
                is_cancelled=lambda: self._cancelled,
            )
        except OSError as exc:
            logger.error("Relocate scan failed: %s", exc)
            self.failed.emit(str(exc))
            return
        # Checked after the fact as well as inside: a cancel that lands
        # mid-walk still returns partial matches, and applying half a scan
        # the user just backed out of is not what cancel means.
        if self._cancelled:
            self.cancelled.emit()
            return
        self.completed.emit(result)
