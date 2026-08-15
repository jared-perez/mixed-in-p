"""Click-gated audition for the Compatible Tracks panel.

The gesture (decided 2026-08-12, and deliberately not hover-to-play): a
click on a row's play icon starts that track, sound continues only while
the cursor stays on the icon, moving off stops everything, and a further
click while it plays skips 30 s on. The main player is stopped when an
audition starts and never resumes on its own — the DJ asked to hear this
track, not to have the last one come back.

Two pieces, kept apart from the panel that drives them:

* a second :class:`PlayerEngine` — its own `sounddevice` output stream, the
  same territory the keyboard panel already occupies with its concurrent
  stream — fed one window at a time rather than a whole file;
* a single-slot reader thread, because a window decode is a blocking call
  with nothing to cancel. What "cancel" means here is *discard the result*:
  the offset rides along with it, so a window that lands after the user has
  moved on is dropped rather than played into a silent panel.

Hover on a row warms the first window (cheap, and thrown away if unused),
so the click that follows usually plays from memory.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Signal

from ..workers.audition_worker import WINDOW_MS, AuditionWindowWorker
from ..workers.thread_keeper import keep_alive, wait_for_threads
from .player_engine import PlayerEngine

logger = logging.getLogger(__name__)

# How far a second click jumps. Half a window, so the skip lands inside
# audio the listener has not heard yet without stranding the rest of it.
SKIP_MS = 30_000


class AuditionPlayer(QObject):
    """Plays 35-second windows of a track while the cursor holds the icon."""

    # An audition began (path) — the main player stops on this.
    started = Signal(str)
    # All audition sound has ended, for any reason.
    stopped = Signal()
    # A click is waiting on a decode (path or ""), so the icon can say so.
    busy_changed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._engine = PlayerEngine(self)
        self._engine.finished.connect(self._on_window_finished)
        # What the user is listening to, and where in the file it started.
        self._path: str | None = None
        self._offset_ms = 0
        # A window already in hand: (path, offset_ms) -> (pcm, sr). Exactly
        # one, because the point of a window is that it is cheap to re-read.
        self._cached: tuple[tuple[str, int], object, int] | None = None
        # The request in flight, and whether its result should be played on
        # arrival (a click) or merely kept (a hover warm-up).
        self._pending: tuple[str, int] | None = None
        self._play_on_arrival = False
        self._thread: QThread | None = None
        self._worker: AuditionWindowWorker | None = None
        self._thread_keep: list = []

    # ── State ───────────────────────────────────────────────────

    def is_playing(self) -> bool:
        return self._path is not None and self._engine.is_playing()

    @property
    def current_path(self) -> str | None:
        """The track being auditioned, or waiting on a decode to be."""
        return self._path

    def set_volume(self, volume: float) -> None:
        self._engine.set_volume(volume)

    # ── The gesture ─────────────────────────────────────────────

    def warm(self, path: str) -> None:
        """Row hover: decode the opening window, but do not play it.

        Free to call on every hover — an already-cached or already-requested
        window is a no-op, and a warm-up never interrupts a live audition.
        """
        if self.is_playing() or self._path is not None:
            return
        if self._have(path, 0) or self._pending == (path, 0):
            return
        self._request(path, 0, play=False)

    def click(self, path: str) -> None:
        """Icon click: start this track, or skip 30 s if it is already going.

        Clicking a *different* row while one is auditioning starts the new
        one from the top — the gesture is "play this", not "add to a queue".
        """
        if self._path == path and self._engine.is_playing():
            self.skip_forward()
            return
        self._path = path
        self._offset_ms = 0
        self._play_window(path, 0)

    def skip_forward(self) -> None:
        """Jump on by :data:`SKIP_MS`; past the end of the file, stop."""
        if self._path is None:
            return
        self._offset_ms += SKIP_MS
        self._play_window(self._path, self._offset_ms)

    def stop(self) -> None:
        """End the audition and forget what it was — the mouse left, or the
        panel closed, or the seed changed. Idempotent."""
        was_active = self._path is not None
        self._path = None
        self._offset_ms = 0
        self._pending = None
        self._play_on_arrival = False
        self._engine.stop()
        self._engine.unload()
        self.busy_changed.emit("")
        if was_active:
            self.stopped.emit()

    # ── Windows ─────────────────────────────────────────────────

    def _play_window(self, path: str, offset_ms: int) -> None:
        cached = self._take(path, offset_ms)
        if cached is not None:
            self._start_engine(path, *cached)
            return
        self.busy_changed.emit(path)
        self._request(path, offset_ms, play=True)

    def _start_engine(self, path: str, pcm, sr: int) -> None:
        self.busy_changed.emit("")
        self._engine.load(pcm, sr)
        # started is what stops the main player, so it is emitted before the
        # audition's own output opens — two streams playing at once, even for
        # a block, is the one thing this gesture must never do.
        self.started.emit(path)
        self._engine.play()

    def _have(self, path: str, offset_ms: int) -> bool:
        return self._cached is not None and self._cached[0] == (path, offset_ms)

    def _take(self, path: str, offset_ms: int):
        if not self._have(path, offset_ms):
            return None
        _, pcm, sr = self._cached
        return pcm, sr

    def _on_window_finished(self) -> None:
        """The window ran out. Roll straight into the next one, so holding
        the icon plays on rather than stopping dead at 35 seconds."""
        if self._path is None:
            return
        self._offset_ms += WINDOW_MS
        self._play_window(self._path, self._offset_ms)

    # ── Reader thread ───────────────────────────────────────────

    def _request(self, path: str, offset_ms: int, *, play: bool) -> None:
        self._pending = (path, offset_ms)
        self._play_on_arrival = play
        # One reader at a time: a second window started while the first is
        # still decoding would fight it for the GIL, which is the documented
        # cause of dropouts in the main player.
        if self._thread is not None and self._thread.isRunning():
            return
        self._start_thread(path, offset_ms)

    def _start_thread(self, path: str, offset_ms: int) -> None:
        thread = QThread()
        worker = AuditionWindowWorker(path, offset_ms)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.ready.connect(self._on_window_ready)
        worker.empty.connect(self._on_window_empty)
        worker.error.connect(self._on_window_error)
        for signal in (worker.ready, worker.empty, worker.error):
            signal.connect(lambda *_: thread.quit())
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_thread_finished)
        self._thread = thread
        self._worker = worker
        keep_alive(self._thread_keep, thread, worker)
        thread.start()

    def _on_thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        # A request made while the previous window was still decoding waited
        # for this moment rather than starting a second reader.
        if self._pending is not None:
            path, offset = self._pending
            self._start_thread(path, offset)

    def _on_window_ready(self, path: str, offset_ms: int, pcm, sr: int) -> None:
        if self._pending == (path, offset_ms):
            self._pending = None
        self._cached = ((path, offset_ms), pcm, sr)
        # Anything else means the user moved on while this was decoding: keep
        # the window (the next click may want it) but do not make a sound.
        if self._play_on_arrival and self._path == path and self._offset_ms == offset_ms:
            self._play_on_arrival = False
            self._start_engine(path, pcm, sr)

    def _on_window_empty(self, path: str, offset_ms: int) -> None:
        """Skipped past the end of the file — stop, don't wrap or hang."""
        if self._pending == (path, offset_ms):
            self._pending = None
        if self._path == path:
            self.stop()

    def _on_window_error(self, path: str, _message: str) -> None:
        if self._pending is not None and self._pending[0] == path:
            self._pending = None
        if self._path == path:
            self.stop()

    # ── Shutdown ────────────────────────────────────────────────

    def shutdown_workers(self) -> None:
        """Stop the sound and wait for the reader — a panel that starts
        threads must join them before it goes away (house rule)."""
        self.stop()
        self._engine.unload()
        if not wait_for_threads(self._thread_keep):
            logger.warning("Audition reader still running at shutdown")
