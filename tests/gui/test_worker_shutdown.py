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
