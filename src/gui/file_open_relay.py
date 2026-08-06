"""macOS hands files over as events, not as argv — and it does it early.

On Windows and Linux, "Open with Mixed in P" arrives on the command line. On
macOS a bundled ``.app`` is different: LaunchServices launches the app once
and then delivers each file as a ``QFileOpenEvent`` sent to the application
object. This is also why macOS needs no single-instance code for Finder
launches — LaunchServices already routes to the running app — but it does need
this, because Qt sends those events to a place nothing was listening.

**The trap is timing.** On a cold start the event can be delivered before
``MainWindow`` exists: any nested event loop that spins during startup will
deliver it, and there is nothing to hand it to. Dropped, the symptom is that
the *first* Open With silently does nothing while every later one works —
which reads as flakiness and is miserable to diagnose after the fact. So this
buffers until a receiver says it is ready, then replays.

One event carries one file, so opening five files in Finder sends five events.
Buffering coalesces the cold-start batch into a single emission, which keeps
the receiving end from loading Scratch and raising the window five times.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, QObject, Signal

from ..utils.paths import normalize_track_path

logger = logging.getLogger(__name__)


class FileOpenRelay(QObject):
    """Catch ``QFileOpenEvent``s on the application and re-emit them as paths.

    Install it on the ``QApplication`` as early as possible — before
    ``MainWindow`` is built — then connect ``files_opened`` and call
    ``go_live()`` once there is something to receive them.
    """

    files_opened = Signal(list)

    def __init__(self, app: QObject) -> None:
        super().__init__(app)
        self._buffer: list[str] = []
        self._live = False
        # An event filter rather than a QApplication subclass: the events are
        # sent *to* the application object, so filtering it catches them
        # without forcing every caller to construct a bespoke app class.
        app.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.FileOpen:
            path = event.file()
            if not path:
                # Qt populates url() instead for some sources; only a local
                # file is meaningful here (an http:// URL is not ours to open).
                url = event.url()
                path = url.toLocalFile() if url.isLocalFile() else ""
            if path:
                self._deliver(path)
            return True
        return super().eventFilter(obj, event)

    def _deliver(self, path: str) -> None:
        # Normalized here because this is a point where a path enters from the
        # OS, and every such point owes the library one spelling — Qt hands
        # back forward slashes while argv and a folder scan hand back native
        # separators, and library identity is exact-string. Inert on macOS,
        # where this event only fires, but leaving it out would make this the
        # one entry point that spells files differently from all the others.
        # See src/utils/paths.py.
        path = normalize_track_path(path)
        if self._live:
            self.files_opened.emit([path])
        else:
            self._buffer.append(path)

    def go_live(self) -> None:
        """Replay whatever arrived too early, and pass events straight on after.

        Safe to call when nothing was buffered — that is the ordinary launch.
        """
        self._live = True
        if self._buffer:
            pending, self._buffer = self._buffer, []
            logger.info("Replaying %d file(s) opened during startup.", len(pending))
            self.files_opened.emit(pending)
