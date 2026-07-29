"""Relocate dialog: re-point a playlist track at a file that moved.

Opened from a missing row's right-click menu in the Player. Two ways out,
per §1 of the plan doc:

* **Locate…** — a file picker that opens *at the file's last known
  directory*. Cheap, and the fix when one file moved.
* **Find in Folder…** — scans a folder and relinks every missing file in
  the whole library whose fingerprint (or unique filename) turns up in
  it. One trip through this dialog fixes an entire moved collection,
  which is the difference between this and relocating file-by-file.

Deliberately library-wide rather than scoped to the visible playlist: a
drive that moved took every playlist's tracks with it, and the user has
no reason to repeat the scan once per playlist.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.library import Library
from src.library.relocate import (
    BY_FILENAME,
    RelocateResult,
    apply_matches,
    missing_tracks,
)

from ...styles.theme import Theme
from ...workers.relocate_scan_worker import RelocateScanThread

logger = logging.getLogger(__name__)

# Audio types the "Locate…" picker offers. Format codes are data, not UI
# prose, so the extensions stay unwrapped; only the label is translated.
_AUDIO_GLOB = "*.wav *.flac *.aiff *.aif *.aifc *.mp3 *.m4a *.ogg"


class RelocateDialog(QDialog):
    """Ask where a missing track went, and relink it (and its neighbours)."""

    def __init__(
        self,
        library: Library,
        file_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._library = library
        self._file_path = file_path
        self._track = library.get_track_by_path(file_path)
        self._scan_thread: RelocateScanThread | None = None
        self._progress: QProgressDialog | None = None
        # Rows relinked in the database — the caller reloads when non-zero.
        self.relinked = 0
        # Where the clicked track went, when it was relinked here. Set even
        # if the library had no row for it, so a caller holding only the
        # visible list can still repoint its own entry.
        self.new_path: str | None = None

        self.setWindowTitle(self.tr("File Not Found"))
        self.setMinimumWidth(480)
        self._setup_ui()

    # ------------------------------------------------------------------ ui

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(Theme.SPACING)

        name = QLabel(Path(self._file_path).name)
        name.setWordWrap(True)
        name.setStyleSheet(
            f"color: {Theme.WARNING}; font-size: 14px; font-weight: bold;"
        )
        layout.addWidget(name)

        intro = QLabel(
            self.tr("This file is no longer where the playlist expects it:")
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # Selectable: sometimes the answer is to go look at the path itself.
        path_label = QLabel(self._file_path)
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        path_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        layout.addWidget(path_label)

        self._others_label = QLabel()
        self._others_label.setWordWrap(True)
        self._others_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        layout.addWidget(self._others_label)
        self._refresh_others()

        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet(f"color: {Theme.NEON_GREEN};")
        self._status_label.hide()
        layout.addWidget(self._status_label)

        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(Theme.SPACING)
        locate_btn = QPushButton(self.tr("Locate…"))
        locate_btn.clicked.connect(self._on_locate)
        buttons.addWidget(locate_btn)
        folder_btn = QPushButton(self.tr("Find in Folder…"))
        folder_btn.setToolTip(
            self.tr("Scan a folder and relink every missing file found in it")
        )
        folder_btn.clicked.connect(self._on_find_in_folder)
        buttons.addWidget(folder_btn)
        buttons.addStretch(1)
        close_btn = QPushButton(self.tr("Close"))
        close_btn.clicked.connect(self.reject)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

    def _refresh_others(self) -> None:
        """Show how many *other* files are missing — why a scan is worth it."""
        others = max(0, len(self._missing()) - 1)
        if others:
            # %n + the count is Qt's plural form; several target languages
            # have more than two, so this can't be concatenation.
            self._others_label.setText(
                self.tr(
                    "%n other file(s) in your playlists are also missing.",
                    "",
                    others,
                )
            )
            self._others_label.show()
        else:
            self._others_label.hide()

    def _missing(self) -> list:
        return missing_tracks(self._library)

    # -------------------------------------------------------------- locate

    def _on_locate(self) -> None:
        """Pick the file by hand, starting at its last known directory.

        Opening at the old location is the small thing that makes this
        bearable: the file has usually moved a folder or two, not to
        another planet.
        """
        start = Path(self._file_path).parent
        while not start.is_dir() and start != start.parent:
            start = start.parent
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Locate File"),
            str(start),
            self.tr("Audio Files") + f" ({_AUDIO_GLOB})",
        )
        if not chosen:
            return
        self.new_path = chosen
        if self._track is not None:
            try:
                self._library.relink_track(self._track.id, chosen)
            except (ValueError, OSError) as exc:
                logger.warning("Could not relink '%s': %s", self._file_path, exc)
                QMessageBox.warning(
                    self,
                    self.tr("File Not Found"),
                    self.tr("Could not update the playlist:\n{0}").format(exc),
                )
                return
            self.relinked += 1
        self.accept()

    # ---------------------------------------------------------- folder scan

    def _on_find_in_folder(self) -> None:
        missing = self._missing()
        if not missing:
            self._show_status(self.tr("Nothing is missing any more."))
            return
        if self._scan_thread is not None and self._scan_thread.isRunning():
            return
        folder = QFileDialog.getExistingDirectory(
            self, self.tr("Choose a Folder to Search")
        )
        if not folder:
            return

        # Range 0-0 shows a busy bar until the walk reports a total; the
        # scan can't know how many files there are until it has found them.
        self._progress = QProgressDialog(
            self.tr("Searching…"), self.tr("Cancel"), 0, 0, self
        )
        self._progress.setWindowTitle(self.tr("Find in Folder"))
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setMinimumDuration(0)
        self._progress.setAutoClose(False)
        self._progress.setAutoReset(False)

        thread = RelocateScanThread(missing, folder, parent=self)
        self._progress.canceled.connect(thread.cancel)
        thread.progress.connect(self._on_scan_progress)
        thread.completed.connect(self._on_scan_complete)
        thread.failed.connect(self._on_scan_failed)
        thread.finished.connect(self._close_progress)
        self._scan_thread = thread
        thread.start()

    def _on_scan_progress(self, done: int, total: int, name: str) -> None:
        # Held locally: setValue() on a modal QProgressDialog pumps the event
        # loop, so the scan can finish and clear self._progress part-way
        # through this very method.
        progress = self._progress
        if progress is None:
            return
        if total and progress.maximum() != total:
            progress.setMaximum(total)
        progress.setValue(done)
        if name:
            progress.setLabelText(self.tr("Checking {0}").format(name))

    def _close_progress(self) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        self._scan_thread = None

    def _on_scan_complete(self, result: RelocateResult) -> None:
        relinked = apply_matches(self._library, result.matches)
        self.relinked += relinked
        for match in result.matches:
            if match.track.path == self._file_path:
                self.new_path = match.new_path
        if not relinked:
            self._show_status(
                self.tr("No matching files were found in that folder.")
            )
            return
        self._report(result, relinked)
        self.accept()

    def _on_scan_failed(self, error: str) -> None:
        QMessageBox.warning(
            self,
            self.tr("Find in Folder"),
            self.tr("Could not search that folder:\n{0}").format(error),
        )

    def _report(self, result: RelocateResult, relinked: int) -> None:
        """Summarise the scan: what was fixed, how, and what is still gone."""
        lines = [self.tr("%n file(s) were relinked.", "", relinked)]
        guessed = sum(1 for m in result.matches if m.matched_by == BY_FILENAME)
        if guessed:
            # Worth saying out loud: a name match is a guess where the
            # fingerprint match is proof, and a re-encoded file is a
            # different file.
            lines.append(
                self.tr(
                    "%n of them matched by filename rather than by contents"
                    " — check they are the tracks you expect.",
                    "",
                    guessed,
                )
            )
        if result.unmatched:
            lines.append(
                self.tr(
                    "%n file(s) are still missing.", "", len(result.unmatched)
                )
            )
        QMessageBox.information(
            self, self.tr("Find in Folder"), "\n\n".join(lines)
        )

    def _show_status(self, text: str) -> None:
        self._status_label.setText(text)
        self._status_label.show()

    # ------------------------------------------------------------- teardown

    def done(self, result: int) -> None:
        """Close, but never while a scan thread is still running.

        Both accept() and reject() route through here, which matters: the
        success path closes the dialog from the ``completed`` handler, and
        at that moment ``run()`` has returned but the thread object has
        not finished tearing down. Leaving it would be the classic
        "QThread destroyed while thread is still running".
        """
        thread = self._scan_thread
        if thread is not None and thread.isRunning():
            thread.cancel()
            thread.wait()
        super().done(result)
