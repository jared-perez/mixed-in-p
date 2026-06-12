"""Background worker for batch file renaming."""

import errno
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

logger = logging.getLogger(__name__)


def _friendly_error(exc: BaseException) -> str:
    """Translate cryptic filesystem errors into actionable user-facing messages.

    Falls back to str(exc) for anything not specifically handled.
    """
    if isinstance(exc, OSError) and exc.errno == errno.EROFS:
        return (
            "Cannot write to this drive — the filesystem is mounted read-only. "
            "On macOS this often means an NTFS-formatted drive, which requires "
            "third-party software (e.g. Mounty, Paragon NTFS) to write to."
        )
    return str(exc)

from src.renamer import (
    RenameOperation,
    RenamePreview,
    RenameSession,
    create_session,
    operations_to_dict,
    preview_rename,
    save_session,
    undo_session,
)


@dataclass
class RenameProgress:
    """Progress update from rename worker."""

    completed: int
    total: int
    current_file: str
    success: bool = True
    error: str | None = None


class RenameWorker(QObject):
    """Worker that renames files in a background thread."""

    started = Signal()
    progress = Signal(RenameProgress)
    finished = Signal(RenameSession)  # The saved session for undo
    error = Signal(str)

    def __init__(
        self,
        previews: list[RenamePreview],
        operations: list[RenameOperation],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._previews = previews
        self._operations = operations
        self._session: RenameSession | None = None

    def run(self) -> None:
        """Execute the rename operations."""
        self.started.emit()

        # Filter to only renames that actually change the name
        renames_to_do = [
            (p.original_path, p.new_path)
            for p in self._previews
            if p.original_name != p.new_name and not p.will_conflict
        ]

        if not renames_to_do:
            # Nothing to rename
            logger.warning("No files to rename")
            self.error.emit("No files to rename")
            return

        total = len(renames_to_do)
        logger.info(f"Starting rename operation: {total} files to rename")
        successful_renames: list[tuple[str, str]] = []
        errors: list[str] = []

        for i, (old_path, new_path) in enumerate(renames_to_do):
            try:
                # Perform the rename (retry briefly for transient Windows file locks)
                logger.debug(f"Renaming: {Path(old_path).name} -> {Path(new_path).name}")
                old_file = Path(old_path)
                logger.debug(f"  Old path exists: {old_file.exists()}")
                logger.debug(f"  Old path: {old_path}")
                logger.debug(f"  New path: {new_path}")

                last_err: Exception | None = None
                for attempt in range(3):
                    try:
                        old_file.rename(new_path)
                        last_err = None
                        break
                    except PermissionError as e:
                        last_err = e
                        if attempt < 2:
                            logger.debug(f"  PermissionError on attempt {attempt + 1}, retrying...")
                            time.sleep(0.3)
                if last_err is not None:
                    raise last_err

                successful_renames.append((old_path, new_path))
                logger.info(f"Successfully renamed: {Path(old_path).name} -> {Path(new_path).name}")

                self.progress.emit(
                    RenameProgress(
                        completed=i + 1,
                        total=total,
                        current_file=Path(new_path).name,
                        success=True,
                    )
                )
            except Exception as e:
                friendly = _friendly_error(e)
                error_msg = f"{Path(old_path).name}: {friendly}"
                errors.append(error_msg)
                logger.error(f"Rename failed: {error_msg}")
                logger.error(f"Error type: {type(e).__name__}")
                self.progress.emit(
                    RenameProgress(
                        completed=i + 1,
                        total=total,
                        current_file=Path(old_path).name,
                        success=False,
                        error=friendly,
                    )
                )

        # Create and save session for undo
        if successful_renames:
            self._session = create_session(
                successful_renames,
                operations_to_dict(self._operations),
                description=f"Renamed {len(successful_renames)} files",
            )
            save_session(self._session)
            self.finished.emit(self._session)
        elif errors:
            self.error.emit(f"All renames failed: {errors[0]}")


class RenameThread(QThread):
    """Thread that manages the rename worker."""

    rename_started = Signal()
    rename_progress = Signal(RenameProgress)
    rename_finished = Signal(RenameSession)
    rename_error = Signal(str)

    def __init__(
        self,
        previews: list[RenamePreview],
        operations: list[RenameOperation],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._previews = previews
        self._operations = operations

    def run(self) -> None:
        """Run the rename in this thread."""
        worker = RenameWorker(self._previews, self._operations)

        worker.started.connect(self.rename_started.emit)
        worker.progress.connect(self.rename_progress.emit)
        worker.finished.connect(self.rename_finished.emit)
        worker.error.connect(self.rename_error.emit)

        worker.run()


class UndoWorker(QObject):
    """Worker that undoes a rename session."""

    started = Signal()
    progress = Signal(RenameProgress)
    finished = Signal(int, int)  # (success_count, error_count)
    error = Signal(str)

    def __init__(
        self,
        session: RenameSession,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session

    def run(self) -> None:
        """Execute the undo operation."""
        self.started.emit()

        try:
            results = undo_session(self._session)

            success_count = sum(1 for _, _, success, _ in results if success)
            error_count = len(results) - success_count

            total = len(results)
            for i, (old_path, new_path, success, err) in enumerate(results):
                self.progress.emit(
                    RenameProgress(
                        completed=i + 1,
                        total=total,
                        current_file=Path(new_path).name,
                        success=success,
                        error=err,
                    )
                )

            self.finished.emit(success_count, error_count)
        except Exception as e:
            self.error.emit(str(e))


class UndoThread(QThread):
    """Thread that manages the undo worker."""

    undo_started = Signal()
    undo_progress = Signal(RenameProgress)
    undo_finished = Signal(int, int)
    undo_error = Signal(str)

    def __init__(
        self,
        session: RenameSession,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session

    def run(self) -> None:
        """Run the undo in this thread."""
        worker = UndoWorker(self._session)

        worker.started.connect(self.undo_started.emit)
        worker.progress.connect(self.undo_progress.emit)
        worker.finished.connect(self.undo_finished.emit)
        worker.error.connect(self.undo_error.emit)

        worker.run()
