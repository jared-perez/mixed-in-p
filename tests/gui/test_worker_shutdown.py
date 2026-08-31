"""Panels wait for their reader threads instead of outliving them.

A decode or a render is one long blocking read with nothing to cancel, so the
panels' shutdown path can only wait for the work in flight — and it has to,
because on Windows the open handle blocks the file from being renamed or
deleted (``WinError 32``). That surfaced as an order-dependent failure in the
full suite: a decode thread from an earlier test still holding a fixture's
``.wav`` when ``tmp_path`` teardown tried to unlink it.

Destroying a running QThread is also undefined behaviour, which is what the
``QThread: Destroyed while thread is still running`` line in the old test
output was reporting.
"""

import threading

import pytest
import shiboken6
from PySide6.QtCore import QObject, QThread, Signal, Slot

from src.gui.widgets.player_panel import PlayerPanel
from src.gui.workers.thread_keeper import keep_alive, wait_for_threads
from src.library import Library


class SlowWorker(QObject):
    """Stands in for a decode: blocks, ignores its thread's event loop."""

    done = Signal()

    def __init__(self, release: threading.Event) -> None:
        super().__init__()
        self._release = release
        self.started = threading.Event()

    @Slot()
    def run(self) -> None:
        self.started.set()
        self._release.wait(timeout=5)
        self.done.emit()


@pytest.fixture
def slow_thread():
    """A started thread parked inside a blocking call, plus its release latch."""
    release = threading.Event()
    store: list = []
    thread = QThread()
    worker = SlowWorker(release)
    worker.moveToThread(thread)
    keep_alive(store, thread, worker)
    thread.started.connect(worker.run)
    worker.done.connect(thread.quit)
    thread.start()
    assert worker.started.wait(timeout=5), "worker never got going"
    yield store, thread, release
    release.set()
    thread.quit()
    thread.wait(5000)


class TestWaitForThreads:
    def test_it_waits_for_a_blocked_thread(self, slow_thread):
        store, thread, release = slow_thread
        assert thread.isRunning()

        # quit() alone cannot end a thread parked in a blocking call, so the
        # release is what lets it finish — the point is that the call does not
        # return until it has.
        threading.Timer(0.05, release.set).start()
        assert wait_for_threads(store) is True
        assert not thread.isRunning()

    def test_it_reports_a_thread_that_would_not_stop(self, slow_thread):
        store, thread, _release = slow_thread

        assert wait_for_threads(store, timeout_ms=50) is False

    def test_a_finished_thread_is_a_no_op(self, slow_thread):
        store, thread, release = slow_thread
        release.set()
        thread.quit()
        thread.wait(5000)

        # Safe to call twice, and after the C++ side is gone.
        assert wait_for_threads(store) is True
        assert wait_for_threads(store) is True


class TestReaderHandles:
    """`add_tracks` leaves a file open, and `wait_for_readers` closes it.

    This is the half of the Windows flake that `closeEvent` could never
    reach: the tests that failed there delete the file *mid-test*, a line or
    two after adding it, while the prefetch this pins is still in flight. The
    WinError 32 itself cannot be reproduced on POSIX — an open handle does not
    block an unlink here — so what is pinned is the mechanism underneath it.
    """

    @staticmethod
    def running(panel):
        return [
            o
            for group in panel._thread_keep
            for o in group
            if isinstance(o, QThread) and shiboken6.isValid(o) and o.isRunning()
        ]

    def test_adding_tracks_starts_a_reader(self, qtbot, tmp_path):
        panel = PlayerPanel()
        qtbot.addWidget(panel)
        panel.set_library(Library(tmp_path / "library.db"))
        track = tmp_path / "a.wav"
        track.write_bytes(b"audio-a.wav")

        panel.add_tracks([{"file_path": str(track), "display_name": "a.wav"}])

        # Whether it is still *running* by now is a race — that it was started
        # is not, and that is what leaves the handle open.
        assert panel._thread_keep, "no prefetch was started"

    def test_wait_for_readers_leaves_nothing_running(self, qtbot, tmp_path):
        panel = PlayerPanel()
        qtbot.addWidget(panel)
        panel.set_library(Library(tmp_path / "library.db"))
        track = tmp_path / "a.wav"
        track.write_bytes(b"audio-a.wav")
        panel.add_tracks([{"file_path": str(track), "display_name": "a.wav"}])

        assert panel.wait_for_readers() is True
        assert self.running(panel) == []

    def test_only_the_prefetched_track_is_held(self, qtbot, tmp_path):
        """Why a test deleting the *second* of two files never flaked.

        Only one track is ever warmed — the selection, else row 0 — so the
        rest of the playlist is untouched on disk.
        """
        panel = PlayerPanel()
        qtbot.addWidget(panel)
        panel.set_library(Library(tmp_path / "library.db"))
        tracks = []
        for name in ("a.wav", "b.wav"):
            f = tmp_path / name
            f.write_bytes(b"audio-" + name.encode())
            tracks.append({"file_path": str(f), "display_name": name})

        panel.add_tracks(tracks)

        # Read before the event loop spins, so _on_decode_thread_finished has
        # not cleared it yet.
        assert panel._decode_current_path == str(tmp_path / "a.wav")


class TestPlayerPanelShutdown:
    def test_closing_the_panel_joins_its_reader_threads(self, qtbot, tmp_path):
        library = Library(tmp_path / "library.db")
        panel = PlayerPanel()
        qtbot.addWidget(panel)
        panel.set_library(library)

        release = threading.Event()
        thread = QThread()
        worker = SlowWorker(release)
        worker.moveToThread(thread)
        keep_alive(panel._thread_keep, thread, worker)
        thread.started.connect(worker.run)
        worker.done.connect(thread.quit)
        thread.start()
        assert worker.started.wait(timeout=5)

        threading.Timer(0.05, release.set).start()
        panel.close()

        assert not thread.isRunning()
        library.close()

    def test_closing_the_panel_releases_the_audio_device(self, qtbot, monkeypatch):
        """Stopping is not enough, and that is the whole bug.

        `PlayerEngine.stop()` rewinds but deliberately keeps the stream open
        and primed, so a resume is instant — right while the app runs, wrong
        at the end of it. A PortAudio stream left open outlives the
        interpreter and its CoreAudio thread then calls back into torn-down
        Python state: SIGSEGV in `ffi_closure_SYSV_inner`, no traceback, and
        it lands after the last line of output rather than at the fault.

        Asserted as an invariant (the close path releases) rather than by
        opening a real device: a test that plays needs audio hardware, and
        what broke was the wiring rather than the closing.
        """
        panel = PlayerPanel()
        qtbot.addWidget(panel)
        released = []
        monkeypatch.setattr(panel._engine, "unload", lambda: released.append(True))

        panel.close()

        assert released == [True]

    def test_a_decode_landing_after_the_close_does_not_reopen_it(
        self, qtbot, monkeypatch, tmp_path
    ):
        """The other half, and either alone leaves a stream open.

        A decode in flight arrives on a *queued* signal, so `_on_decoded` can
        run after `closeEvent` has already released the device — and it would
        then open a fresh one that nothing will ever close. Measured: of four
        streams the suite leaked, two were opened after their panel's close.
        """
        import numpy as np

        panel = PlayerPanel()
        qtbot.addWidget(panel)
        played = []
        monkeypatch.setattr(panel._engine, "play", lambda: played.append(True))
        path = str(tmp_path / "late.wav")
        panel._pending_play_path = path

        panel.close()
        panel._on_decoded(path, np.zeros((256, 1), dtype="float32"), 44100)

        assert played == []
