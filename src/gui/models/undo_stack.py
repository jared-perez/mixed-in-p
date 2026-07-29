"""Session-scoped undo stack for playlist edits (§11).

Playlist edits auto-save: every add, remove, reorder, delete, and reparent
writes to the database the moment it happens, with no dirty state and no
save button. That is the right model for a DJ tool — but it makes destructive
edits irreversible, so ``Cmd/Ctrl+Z`` is the safety net.

The rule this implements, in one line: **undo reverses anything that destroys
or scrambles structure the user built; it never touches file contents.**
Inline tag edits write ID3 frames to the audio file itself and are therefore
excluded — a Cmd+Z that silently rewrote a file's tags would be a nasty
surprise, where one that puts a deleted playlist back is exactly what the
user expects.

Deliberately *not* a QUndoStack: the entries here are closures that restore a
snapshot through :class:`~src.library.Library`, not command objects with a
redo half. Nothing is persisted — the stack dies with the session, which is
what "session-scoped" means. It is also single-direction: there is no redo,
because a redo of "restore the playlist I just deleted" has no natural
meaning once the user has moved on.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)

# How many operations back the user can reach. Deep enough to cover a run of
# mis-drops, shallow enough that the retained snapshots stay small (a
# snapshot holds track rows, not audio).
MAX_DEPTH = 50


class UndoStack(QObject):
    """A stack of labelled inverse operations.

    Each entry is a ``(label, callable)`` pair. Labels ("Remove Tracks",
    "Delete Folder") are internal identifiers and deliberately **not**
    translated: nothing displays them yet — there is no Edit menu and no
    toast surface, and the restored list or tree row is its own feedback.
    Wrap them at the point something shows them.
    """

    # Emitted whenever the stack's depth changes (push, undo, or clear), so
    # an Edit menu or button can track whether undo is available.
    changed = Signal()
    # Emitted after an entry runs, carrying its (untranslated) label. The
    # window uses this to refresh the views the restore touched.
    undone = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._entries: list[tuple[str, Callable[[], None]]] = []
        # Set while an entry runs. Mutating code writes through the same
        # chokepoints that push entries, so without this an undo would push
        # its own inverse and Cmd+Z would toggle between two states forever.
        self._undoing = False

    def push(self, label: str, undo: Callable[[], None]) -> None:
        """Record how to reverse an operation that already happened."""
        if self._undoing:
            return
        self._entries.append((label, undo))
        del self._entries[:-MAX_DEPTH]
        self.changed.emit()

    @property
    def is_undoing(self) -> bool:
        """True while an entry is running (capture points check this)."""
        return self._undoing

    def can_undo(self) -> bool:
        return bool(self._entries)

    def peek_label(self) -> str:
        return self._entries[-1][0] if self._entries else ""

    def undo(self) -> str:
        """Run the newest entry and drop it. Returns its label, or "".

        A failing entry is still discarded: it described a world that no
        longer exists (its playlist was deleted, its file went away), and
        leaving it on the stack would jam every later undo behind it.
        """
        if not self._entries:
            return ""
        label, action = self._entries.pop()
        self._undoing = True
        try:
            action()
        except Exception as exc:  # noqa: BLE001 — never let a stale entry crash the app
            logger.error("Undo of %s failed: %s", label, exc)
        finally:
            # Still guarded while the views resync, so a refresh that runs
            # through a mutation path cannot push an entry of its own.
            self.undone.emit(label)
            self._undoing = False
            self.changed.emit()
        return label

    def clear(self) -> None:
        self._entries.clear()
        self.changed.emit()

    def __len__(self) -> int:
        return len(self._entries)
