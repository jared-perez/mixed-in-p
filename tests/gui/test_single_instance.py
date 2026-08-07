"""SingleInstance: the handshake that keeps one app one process.

Two objects in one test process stand in for two launches. That is a fair
model of the thing that matters — a second launch must find the first and hand
its files over rather than becoming a second app — but note what it cannot
cover: the real Windows multi-select race spawns genuinely concurrent
processes, and only the Windows machine can test that (plan §8 item 4).
"""

from __future__ import annotations

import itertools
import json
import os

import pytest
from PySide6.QtCore import QEventLoop, QSemaphore, QThread, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from src.gui.single_instance import _HEADER, SingleInstance, server_name

_ids = itertools.count()


def hand_off(inst, paths, qtbot, timeout_ms=3000):
    """Deliver a handoff frame the way a secondary really does, then pump.

    A raw client socket rather than ``SingleInstance.send()``, for two
    reasons. ``send()`` blocks until the primary drains the pipe, and in one
    process the primary is this very thread — so a main-thread ``send()`` is a
    deadlock on Windows dressed up as a test. And writing directly reproduces
    the shape that actually broke in the field: a tiny payload written and
    disconnected at once, so the connection is **already complete** by the
    time the primary services it, with ``readyRead`` fired and gone.

    The write completes without a reader because the payload fits the pipe
    (or socket) buffer, which is exactly why the production bug was silent —
    the sender saw success for a file that was then discarded.

    **The pump before the disconnect is load-bearing, and its absence was a
    Unix assumption.** This used to hang up immediately, on the premise that
    the connection was already accepted and the bytes already buffered. That
    premise is false in one process: accepting is event-loop mediated and the
    primary's loop is *this thread*, which is busy running the test. On Unix
    the listen backlog holds the completed connection until somebody gets
    round to accepting it, so it passed. On Windows a client that connects and
    fully disconnects before the server accepts leaves nothing to accept, and
    seven tests reported an empty inbox.

    It is the mirror image of the production bug this file is mostly about —
    there the server missed an event that had already happened; here the
    client finishes before the server can have an event at all — which is why
    it was easy to write and easy to miss.

    The pump goes *before* the disconnect on purpose, so the server accepts
    while the client is still connected. It must not creep further down: what
    the callers are testing is a connection that is **complete on arrival**,
    and a pump after the hang-up would let the primary service it early and
    quietly delete the teeth. Verified on Windows: with the pre-fix ``_listen``
    ordering restored underneath this helper, three tests still fail.

    The socket is fully torn down before returning, rather than handed back
    for the test to hold. A half-disconnected QLocalSocket collected by Python
    at the end of a test leaves a notifier pointing at freed memory, which
    surfaces as a segfault inside the *next* test's event loop — a genuinely
    horrible thing to debug, and it cost a run here to find.
    """
    payload = json.dumps(paths).encode("utf-8")
    sock = QLocalSocket()
    sock.connectToServer(inst.name)
    assert sock.waitForConnected(timeout_ms), "test setup: no primary answered"
    sock.write(_HEADER.pack(len(payload)) + payload)
    sock.flush()
    qtbot.wait(20)
    sock.disconnectFromServer()
    if sock.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        sock.waitForDisconnected(timeout_ms)
    sock.close()


# After the budget is spent, keep pumping this much longer before giving up.
# Not slack in the deadline — the test still fails — but the difference between
# failing and *abandoning a running thread*. See run_off_the_main_thread.
#
# Only ever reached if something other than the write budget hangs, since a
# write gives up inside bounded_write's budget, which is inside _WAIT_MS. So it
# is the backstop for the unforeseen, and bounded rather than generous: a real
# hang should fail the suite, not stall it.
_GRACE_MS = 10000

# Default ceiling for a pumped wait. Never waited on when things are healthy —
# every wait returns the moment the worker finishes — so it is sized to sit
# above the write budget rather than to be "long enough for a fast machine".
_WAIT_MS = 20000


def _run_the_loop_until_finished(thread, budget_ms) -> bool:
    """Run a **real** event loop until *thread* finishes or the budget expires.

    ``QEventLoop.exec()`` rather than a ``qtbot.wait(10)`` spin, and the
    difference is the point rather than a tidy-up.

    A spin loop calls ``processEvents`` and then sleeps, over and over. A real
    loop blocks *inside* the platform's dispatcher, which on Windows is where
    a pipe's native notifier gets waited on — and servicing an incoming local
    connection is exactly that kind of native event. It is also what the app
    itself runs: ``app.exec()``, not a spin. So a test standing in for the
    primary's event loop should stand in for the real one.

    This is a hypothesis with a measurement behind it, not a style preference.
    Windows reported the handoff failing with **36 of 36 bytes still queued
    after 12 s** — the primary had not read a single byte, under a loop that
    was nominally pumping the whole time. Load-proportional in whether it
    fired, absolute in how it failed: a starved loop should sometimes get
    partway, and this never did. "The connection was never serviced at all"
    fits that shape, and a spin loop is the thing here most able to miss a
    native notification that a real loop would have waited on.

    If it turns out not to be the cause, the fallback is to stop driving
    ``send()`` against a live in-process primary at all and use ``hand_off``,
    which every other test in this file already does — the real cross-process
    path is covered by ``scripts/race_check.py`` either way.
    """
    if thread.isFinished():
        return True

    loop = QEventLoop()
    # Queued, because finished() is emitted on the worker: the post is what
    # wakes the loop out of its native wait. Safe against the worker finishing
    # between the check above and exec() below — the event is already queued by
    # then, so exec() returns immediately rather than waiting out the budget.
    thread.finished.connect(loop.quit)
    guard = QTimer()
    guard.setSingleShot(True)
    guard.timeout.connect(loop.quit)
    guard.start(budget_ms)
    try:
        loop.exec()
    finally:
        guard.stop()
        thread.finished.disconnect(loop.quit)
    return thread.isFinished()


def run_off_the_main_thread(fn, qtbot, timeout_ms=_WAIT_MS):
    """Run a blocking call on a worker thread while the main loop pumps.

    In the app the two sides of a handoff are two processes, each with its own
    event loop. In one process they are not, so any blocking call that needs
    the *other* side to make progress has to be driven from somewhere other
    than the thread that would provide it.

    Worth being precise about why the naive main-thread version passed on
    macOS, so nobody restores it: a Windows named-pipe write completes only
    once the server end reads, while a Unix socket write lands in the kernel
    buffer with no peer involvement at all. The test was asserting Unix
    semantics rather than behaviour — the product call was always fine, as two
    real Windows processes showed.

    **Never stop pumping while the worker is still running, and never join it
    from this thread until it has finished.** This used to spend its budget in
    ``qtbot.waitUntil`` and then, in a ``finally``, call ``thread.wait()`` —
    which does *not* run the event loop. So the instant the worker was late,
    the loop it depends on stopped, and it could no longer finish by
    construction: the join waited for a thread that was waiting for the join to
    stop. On POSIX nothing noticed, because the write needs no reader. On
    Windows a merely-slow run turned into a hard failure plus a worker
    abandoned mid-write, holding the full ``WRITE_TIMEOUT_MS`` — which then
    logged "Timed out handing files" half a minute later, into whichever test
    was unlucky enough to be running by then. Order-dependent, Windows-only,
    and blamed on the wrong test.

    So the wait is one real event loop, and an overrun keeps running it for
    ``_GRACE_MS`` so the worker can unwind before the failure is reported. The
    test still fails; it just fails cleanly and takes its thread with it.

    *qtbot* is still required even though nothing here spins on it: it is what
    guarantees a QApplication exists, without which ``QEventLoop.exec()`` has
    no dispatcher to run.
    """
    result = {}

    class Worker(QThread):
        def run(self):
            result["value"] = fn()

    thread = Worker()
    thread.start()
    in_time = _run_the_loop_until_finished(thread, timeout_ms)
    if not in_time:
        _run_the_loop_until_finished(thread, _GRACE_MS)
    assert thread.wait(1000), "the worker thread never finished"
    assert in_time, f"the worker needed longer than {timeout_ms}ms"
    return result["value"]


# There is deliberately no send_off_the_main_thread helper. Driving send()
# against a live primary in this process is unreliable on Windows whatever the
# loop is — see test_paths_round_trip_to_the_primary for the measurements, and
# scripts/race_check.py for where that path is covered instead.


@pytest.fixture(autouse=True)
def bounded_write(monkeypatch):
    """Stop these tests inheriting the shipped 30-second write budget.

    30000 is right for the product: on Windows a named-pipe write completes
    only once the primary reads, and a cold frozen start measured 5.53 s with
    no event loop running at all, so the budget has to outlast it.

    What has to be bounded is not the duration but the *abandonment*: a worker
    blocked for 30 s outlives the test that started it, so a failure surfaces
    as a stray log line against some unrelated test half a minute later.

    **The number was 3000 for one round, and Windows proved that too tight.**
    It failed ~50% of the time under a loaded full run — cleanly and correctly
    attributed, which was the point of the round, but on the write budget
    rather than on anything real. That is the same mistake the shipped 30000
    exists to avoid, argued in its own comment: overshooting a budget nobody
    waits on is nearly free, undershooting turns a slow machine into a failure.
    In-process the main loop is a test pumping in 10 ms slices while the rest
    of the suite competes for the machine, which is *slower* than the app's
    real case, not faster — so the test wants headroom, not less of it.

    12000 keeps the one property the 3000 was chosen for: it is under the
    harness's own budget, so a genuinely starved loop still fails on the
    test's assertion with the warning attributed here, rather than the harness
    timing out around it and saying something vaguer. A healthy run waits none
    of it — every wait exits the moment the worker finishes.
    """
    monkeypatch.setattr("src.gui.single_instance.WRITE_TIMEOUT_MS", 12000)


@pytest.fixture
def app_id() -> str:
    """A name no other test — or a real running app — can collide with."""
    return f"MixedInPTest-{os.getpid()}-{next(_ids)}"


@pytest.fixture
def instances(qtbot, app_id):
    """Hand out SingleInstance objects and guarantee they are released."""
    made: list[SingleInstance] = []

    def make() -> SingleInstance:
        inst = SingleInstance(app_id)
        made.append(inst)
        return inst

    yield make
    for inst in made:
        inst.close()


class TestTheHarnessItself:
    """The helper every handoff test is driven through, tested on its own.

    Asserted as an *invariant* rather than by timing, because the bug it
    guards against is Windows-only and a timing-based version of this would be
    silently vacuous everywhere else. The invariant — the main loop keeps
    running until the worker is done — is what makes the platform difference
    stop mattering.
    """

    @staticmethod
    def _gated_worker(delay_ms):
        """A call that can only finish if the main event loop keeps running.

        Exactly the dependency a Windows named-pipe write has on the primary's
        loop, reproduced with a semaphore so it holds on every platform.
        """
        gate = QSemaphore(0)
        QTimer.singleShot(delay_ms, gate.release)
        done = []

        def worker():
            gate.tryAcquire(1, 5000)
            done.append(1)
            return "finished"

        return worker, done

    def test_it_pumps_until_the_worker_is_done(self, qtbot):
        worker, _ = self._gated_worker(200)
        assert run_off_the_main_thread(worker, qtbot, timeout_ms=3000) == "finished"

    def test_an_overrun_fails_without_abandoning_the_worker(self, qtbot):
        """The one that matters. A worker left running past its test is how a
        30-second write timeout ends up logged against an innocent test three
        files later — the failure this whole harness note is about.
        """
        worker, done = self._gated_worker(400)

        with pytest.raises(AssertionError, match="needed longer"):
            run_off_the_main_thread(worker, qtbot, timeout_ms=100)

        assert done == [1], "the worker was abandoned rather than unwound"


def test_the_first_claim_wins_and_the_second_does_not(instances):
    primary = instances()
    assert primary.try_claim() is True
    assert primary.is_primary

    secondary = instances()
    assert secondary.try_claim() is False
    assert not secondary.is_primary


def test_paths_round_trip_to_the_primary(qtbot, instances):
    """A loser of the claim delivers its paths to the winner, intact.

    The full two-object flow — claim, lose the claim, deliver — with only the
    transport swapped: ``hand_off`` writes the frame a secondary would, rather
    than calling ``send()``.

    **That swap is deliberate and hard-won. Do not put ``send()`` back here.**
    Driving it against a live primary *in the same process* fails
    intermittently on Windows, and does so in a way no budget fixes: measured
    over eight full-suite runs, six failed with ``36 of 36 bytes still queued``
    — the primary never read a single byte in twelve seconds. Load-sensitive in
    whether it fires, absolute when it does. And it is local to that one
    connection, not the process: a failing run takes exactly the timeout longer
    than a clean one (57 s against 44.6 s), so everything else proceeds at
    normal speed around it. Both a spin loop and a real ``QEventLoop`` produce
    it.

    The real path is not left uncovered, it is covered somewhere better:
    ``scripts/race_check.py`` runs five genuine processes, on both platforms,
    which is the configuration the app actually has — the one-process version
    was always a model of it. ``send()``'s own decisions keep their own tests:
    it returns False with nobody listening, and it retries a connect until its
    deadline.
    """
    primary = instances()
    assert primary.try_claim()

    received: list[list[str]] = []
    primary.files_received.connect(received.append)
    primary.start_delivering()

    secondary = instances()
    assert secondary.try_claim() is False
    hand_off(secondary, ["/music/a.mp3", "/music/b.mp3"], qtbot)

    qtbot.waitUntil(lambda: bool(received), timeout=3000)
    assert received == [["/music/a.mp3", "/music/b.mp3"]]


def test_a_connection_that_completed_before_we_looked_is_still_read(qtbot, instances):
    """The regression test for a payload acknowledged and then silently lost.

    A handoff is tiny and the sender disconnects at once, so the primary
    routinely gets a connection whose data has *already* arrived. On Windows
    ``readyRead`` has fired before ``nextPendingConnection()`` even returns
    the socket, so wiring the signal afterwards means waiting for something
    in the past — and the buffer is then discarded on disconnect. Silent,
    because it fails on the *success* path: across processes the write fits
    the pipe buffer and completes with no reader, so ``send()`` returns True
    for a file that never lands. ~15% of handoffs in a five-way race, and one
    trial where only one file of five arrived.

    **The exact signal ordering is a Windows behaviour and does not reproduce
    on macOS**, where the server-side socket does not exist until it is handed
    over, so its first ``readyRead`` necessarily comes later. Timing alone
    would therefore make this test vacuous here. What is asserted instead is
    the invariant that makes the platform difference stop mattering: a
    connection holding a complete frame is drained **at the moment we take
    it**, not on a later signal.

    Hence the deliberate absence of a ``waitUntil`` before the assertion — the
    delivery must already have happened. Adding one would restore the vacuity.
    The primary is made to look away during the handoff, which is what a
    process still starting its event loop is really doing.
    """
    primary = instances()
    assert primary.try_claim()
    received: list[list[str]] = []
    primary.files_received.connect(received.append)
    primary.start_delivering()

    # Look away while the whole handoff happens: connect, write, hang up.
    primary._server.newConnection.disconnect()
    hand_off(primary, ["/music/a.mp3", "/music/b.mp3"], qtbot)
    qtbot.wait(50)
    assert not received, "test setup: the primary was not actually looking away"

    primary._on_new_connection()

    assert received == [["/music/a.mp3", "/music/b.mp3"]]


class TestListenWiring:
    """``_listen``'s ordering, which is the whole of the fix one level up.

    ``newConnection`` is a one-shot edge too: a connection accepted while
    nothing is attached leaves the signal fired to nobody and the connection
    parked in the pending queue — permanently, because the only thing that
    would collect it is the slot that missed the announcement. The
    socket-level drain cannot help, because there is no socket: nothing ever
    called ``nextPendingConnection()``.

    **The window this closes does not exist on macOS**, where connection
    acceptance is mediated by the event loop, so nothing can arrive between
    two consecutive Python statements. On Windows the pipe listener accepts
    asynchronously, and the gap was wide enough for an entire five-way race:
    every secondary connected, wrote, disconnected and reported success while
    the primary recorded *zero* deliveries — total loss rather than partial.

    So the order is asserted directly, the same way the Windows claim
    sequencing is, rather than pretending a timing test here means anything.
    """

    class SignalStub:
        def __init__(self, order):
            self.order = order
            self.slots = []

        def connect(self, slot):
            self.order.append("wire")
            self.slots.append(slot)

        def disconnect(self, slot):
            self.order.append("unwire")
            self.slots.remove(slot)

    class ServerStub:
        def __init__(self, order, listen_ok=True):
            self.order = order
            self._ok = listen_ok
            self.newConnection = TestListenWiring.SignalStub(order)

        def listen(self, name):
            self.order.append("open")
            return self._ok

        def close(self):
            pass

        def deleteLater(self):
            pass

    def test_the_receiver_is_wired_before_the_door_opens(self, instances, monkeypatch):
        """And the queue is drained once by hand, for anything already through."""
        inst = instances()
        order: list[str] = []
        monkeypatch.setattr(inst, "_on_new_connection", lambda: order.append("drain"))

        assert inst._listen(self.ServerStub(order)) is True
        assert order == ["wire", "open", "drain"]

    def test_a_failed_listen_leaves_nothing_wired(self, instances, monkeypatch):
        """Otherwise the retry loop stacks a second slot on the same signal,
        and every later connection is serviced twice."""
        inst = instances()
        order: list[str] = []
        monkeypatch.setattr(inst, "_on_new_connection", lambda: order.append("drain"))
        server = self.ServerStub(order, listen_ok=False)

        assert inst._listen(server) is False
        assert order == ["wire", "open", "unwire"]
        assert server.newConnection.slots == []
        assert inst._server is None


def test_a_connection_made_before_the_signal_was_wired_is_still_taken(qtbot, instances):
    """The mechanism the drain in ``_listen`` depends on: a connection that is
    already queued can be collected without waiting for another one.

    Honest about its own reach. On macOS this passes whether or not ``_listen``
    wires things in the right order, because acceptance is event-loop mediated
    and the signal cannot be missed — the ordering is covered by
    ``TestListenWiring`` instead. On Windows it is load-bearing: this is the
    shape that failed there, 3 runs of 3, while every secondary reported
    success. Kept for that reason — the other machine is the oracle.
    """
    primary = instances()
    received: list[list[str]] = []
    primary.files_received.connect(received.append)
    primary.start_delivering()

    # Open the door with nobody behind it — the state _listen used to leave.
    server = QLocalServer(primary)
    assert server.listen(primary.name), "test setup: could not listen"
    primary._server = server

    hand_off(primary, ["/music/a.mp3"], qtbot)
    qtbot.wait(50)
    assert not received, "test setup: something serviced the connection early"

    # Now do what _listen does after listen() succeeds.
    server.newConnection.connect(primary._on_new_connection)
    primary._on_new_connection()

    assert received == [["/music/a.mp3"]]


def test_files_handed_over_before_a_receiver_exists_are_replayed(qtbot, instances):
    """The third place this shape hides, and it is upstairs in run_app.

    ``try_claim`` drains the pending queue itself, so a handoff completing
    during the race is read *before* ``MainWindow`` is built and connected —
    roughly 500 ms before. An emission with nothing attached is a file
    silently discarded, which is precisely the fate the two fixes below it
    just rescued the same file from.

    So arrivals are held until ``start_delivering``, and batched: five
    secondaries in one race should raise the window and load Scratch once.
    """
    primary = instances()
    assert primary.try_claim()
    received: list[list[str]] = []

    # Deliberately no receiver yet — this is the window run_app really has.
    hand_off(primary, ["/music/a.mp3"], qtbot)
    hand_off(primary, ["/music/b.mp3"], qtbot)
    qtbot.wait(50)

    primary.files_received.connect(received.append)
    primary.start_delivering()

    assert received == [["/music/a.mp3", "/music/b.mp3"]]


def test_a_bare_relaunch_during_startup_still_raises_the_window(qtbot, instances):
    """An empty handoff is a message too, and an empty list looks like silence.

    "Come to the front" carries no files, so buffering it by list contents
    alone would lose it — the replay would see nothing pending and stay quiet.
    """
    primary = instances()
    assert primary.try_claim()
    received: list[list[str]] = []

    hand_off(primary, [], qtbot)
    qtbot.wait(50)

    primary.files_received.connect(received.append)
    primary.start_delivering()

    assert received == [[]]


def test_an_ordinary_launch_replays_nothing(instances):
    """Nothing arrived, so start_delivering must stay silent."""
    primary = instances()
    assert primary.try_claim()
    received: list[list[str]] = []
    primary.files_received.connect(received.append)

    primary.start_delivering()

    assert received == []


def test_disconnect_takes_a_last_read_before_letting_go(instances, monkeypatch):
    """The other half: a peer can finish and hang up before we service it.

    Dropping on disconnect without reading throws away a payload the sender
    already watched succeed. Asserted as an ordering because the timing that
    provokes it is, again, not reproducible on this platform — but the order
    of these two calls is ordinary logic and is where the mistake would live.
    """
    inst = instances()
    order: list[str] = []
    monkeypatch.setattr(inst, "_on_ready_read", lambda s: order.append("read"))
    monkeypatch.setattr(inst, "_drop", lambda s: order.append("drop"))

    inst._on_disconnected(object())

    assert order == ["read", "drop"]


def test_non_ascii_and_spaces_survive_the_wire(qtbot, instances):
    """The payload is UTF-8 JSON, so the names Windows verified stay intact."""
    primary = instances()
    assert primary.try_claim()
    received: list[list[str]] = []
    primary.files_received.connect(received.append)
    primary.start_delivering()

    paths = ["/music/with spaces.mp3", "/music/café-日本.mp3"]
    hand_off(primary, paths, qtbot)

    qtbot.waitUntil(lambda: bool(received), timeout=3000)
    assert received == [paths]


def test_a_bare_relaunch_still_reaches_the_primary(qtbot, instances):
    """No files, but "come to the front" is still a message worth delivering."""
    primary = instances()
    assert primary.try_claim()
    received: list[list[str]] = []
    primary.files_received.connect(received.append)
    primary.start_delivering()

    hand_off(primary, [], qtbot)

    qtbot.waitUntil(lambda: bool(received), timeout=3000)
    assert received == [[]]


@pytest.mark.skipif(
    os.name != "nt",
    reason="listen() is exclusive on POSIX, so it is a sound claim there",
)
def test_the_claim_does_not_rely_on_listen_being_exclusive(instances, app_id):
    """Windows named pipes allow many servers on one name — so listen() is
    not a claim, and the mutex is what actually decides.

    Measured on Windows 11 / Qt 6.11: with a primary alive and answering, a
    second ``QLocalServer.listen()`` on the same name **succeeds**. A claim
    built on the loser of a listen race retrying its connect is therefore
    dead code there — nobody ever loses. Under a real race that produced five
    processes, five primaries and zero handoffs, five times out of five:
    five ``Library()`` connections to one ``library.db``, all auto-saving
    Scratch over each other.

    The middle assertion is the point of the test. It shows the naive claim
    would have said "you are primary", so ``try_claim`` returning False
    afterwards is the mutex doing real work rather than the pipe happening to
    be busy.
    """
    primary = instances()
    assert primary.try_claim() is True

    naive = QLocalServer()
    assert naive.listen(server_name(app_id)), (
        "test is vacuous: listen() turned out to be exclusive after all, so it "
        "no longer demonstrates why the claim needs a mutex"
    )
    naive.close()

    second = instances()
    assert second.try_claim() is False


def test_connect_retries_until_a_late_primary_appears(qtbot, instances):
    """Losing the claim means a primary exists, not that it can be reached yet.

    On Windows the mutex elects a winner *before* that winner calls
    ``listen()``, so a secondary can reach the pipe a fraction of a
    millisecond before it exists. The connect fails outright rather than
    blocking, so one failure must not be read as "nobody is home" — the
    connect retries until its deadline.

    Simulated by starting the connect first and bringing the server up only
    afterwards: the same ordering, with the gap widened to something a test
    can observe.

    Only the connect is exercised, deliberately. The write is what needs the
    primary to be *reading*, and dragging that in would couple this test to
    the receive path it is not about.
    """
    from PySide6.QtCore import QTimer

    sender = instances()
    primary = instances()

    QTimer.singleShot(150, lambda: primary.try_claim())

    sock = run_off_the_main_thread(
        lambda: sender._connect_to_primary(3000), qtbot
    )
    assert sock is not None, "gave up on a primary that was merely slow to listen"
    sock.close()


class TestClaimSequencing:
    """``try_claim``'s ordering, which is now one flow on both platforms.

    The primitives differ (mutex / flock) and their real failures are hard to
    provoke, but the sequencing around them is ordinary logic and is where the
    mistakes live.
    """

    def test_the_claim_is_taken_before_anything_is_bound(self, instances, monkeypatch):
        """Order matters: the primitive is the claim, listen is transport.

        Binding first is precisely the design that produced five primaries on
        both platforms — on Windows because the pipe name is not exclusive, on
        POSIX because a loser recovering from an apparently-stale socket
        unlinks a live one.
        """
        inst = instances()
        order: list[str] = []
        monkeypatch.setattr(inst, "_acquire_claim", lambda: order.append("claim") or True)
        monkeypatch.setattr(inst, "_listen", lambda s: order.append("listen") or True)

        assert inst.try_claim() is True
        assert order == ["claim", "listen"]

    def test_losing_the_claim_never_touches_the_socket(self, instances, monkeypatch):
        """A secondary must not bind anything — that is the whole point.

        It must also not call removeServer, which is the eviction that made
        the POSIX race fatal. Covered by _listen never running: removeServer
        sits between the claim and the listen.
        """
        inst = instances()
        listened: list[str] = []
        monkeypatch.setattr(inst, "_acquire_claim", lambda: False)
        monkeypatch.setattr(inst, "_listen", lambda s: listened.append("listen") or True)

        assert inst.try_claim() is False
        assert listened == []

    def test_a_claim_that_cannot_be_served_is_given_back(self, instances, monkeypatch):
        """Holding a claim while unable to listen is the worst failure here.

        Every later launch would lose the claim, conclude a primary exists,
        fail to connect to it, and refuse to open — a dead primary that
        nothing short of ending the process can dislodge. So the claim is
        released and the next launch gets a clean try.
        """
        inst = instances()
        released: list[str] = []
        monkeypatch.setattr(inst, "_acquire_claim", lambda: True)
        monkeypatch.setattr(inst, "_release_claim", lambda: released.append("released"))
        monkeypatch.setattr(inst, "_listen", lambda s: False)

        assert inst.try_claim() is False
        assert released == ["released"]

    def test_a_served_claim_is_kept(self, instances, monkeypatch):
        """The mirror of the above: the primary holds it for its whole life."""
        inst = instances()
        released: list[str] = []
        monkeypatch.setattr(inst, "_acquire_claim", lambda: True)
        monkeypatch.setattr(inst, "_release_claim", lambda: released.append("released"))
        monkeypatch.setattr(inst, "_listen", lambda s: True)

        assert inst.try_claim() is True
        assert released == []


@pytest.mark.skipif(os.name == "nt", reason="the eviction is a Unix socket-file bug")
def test_a_primary_that_is_not_answering_yet_cannot_be_evicted(instances):
    """The POSIX five-primaries bug, and the reason the liveness probe is gone.

    On POSIX the bind really is exclusive — a second ``listen()`` on a live
    path fails with ``EEXIST`` — so winning it looks like a claim. The trap is
    what a loser does next. There is a window where a primary has *created*
    its socket file but is not yet accepting, and a connect during it is
    refused exactly as it would be for a file a crashed process left behind.
    Code that probes, sees the refusal and clears the path to recover from the
    stale case instead **unlinks a live primary's socket**, after which its own
    bind succeeds and it becomes a second primary. Each loser evicts the
    previous winner in turn: five processes, five primaries, deterministically.

    Reproduced by making the primary unreachable *without* releasing its
    claim — closing the server is what "bound but not yet accepting" looks
    like from outside. The second instance must still lose.

    The fix is not a better probe. A refused connect cannot distinguish "dead"
    from "not ready yet", and the recovery for one is fatal to the other, so
    the claim is an flock instead and liveness is never guessed at.
    """
    primary = instances()
    assert primary.try_claim() is True
    primary._server.close()

    second = instances()
    assert second.try_claim() is False, (
        "a live primary was evicted by a launch that could not reach it"
    )


def test_send_fails_when_nobody_is_listening(instances):
    """The failure the caller must surface rather than paper over.

    A False here is what stops the app opening a second window onto one
    library.db — the hard rule the whole module exists for.
    """
    lonely = instances()
    assert lonely.send(["/music/a.mp3"], timeout_ms=300) is False


@pytest.mark.skipif(
    os.name == "nt", reason="Windows named pipes die with the process — nothing stales"
)
def test_a_stale_socket_file_does_not_block_the_next_launch(instances, app_id):
    """The Unix crash case: the socket file outlives the process that made it.

    A killed process leaves an entry at the socket path that nothing answers,
    so ``listen()`` fails with an address-in-use error — forever, on every
    later launch. That is the failure ``removeServer`` exists to clear, and
    the reason the Unix half of this module is not dead code on a Mac.

    The stale entry is recreated by taking the real socket path Qt chose and
    leaving an ordinary file there. The middle assertion is the point of the
    test: it proves the leftover genuinely blocks a plain ``listen()``, so a
    passing ``try_claim`` afterwards is the recovery and not a no-op.
    """
    from pathlib import Path

    name = server_name(app_id)
    probe = QLocalServer()
    assert probe.listen(name), "test setup: could not listen on the test name"
    socket_path = Path(probe.fullServerName())
    probe.close()  # Qt unlinks its own socket on an orderly close

    socket_path.touch()
    assert socket_path.exists()

    blocked = QLocalServer()
    assert not blocked.listen(name), (
        "test is vacuous: the leftover at %s did not block listen()" % socket_path
    )

    fresh = instances()
    assert fresh.try_claim() is True


def test_the_name_is_scoped_to_the_user(app_id):
    """Named pipes are machine-wide; two users must not share one.

    Hashed rather than appended raw because a Windows domain account reads
    ``DOMAIN\\user`` and a backslash is a separator in a pipe name.
    """
    name = server_name(app_id)
    assert name.startswith(f"{app_id}-")
    assert "\\" not in name and "/" not in name
    assert server_name(app_id) == name  # stable across calls


@pytest.mark.skipif(os.name != "nt", reason="Terminal Services sessions")
def test_the_name_is_scoped_to_the_session_too(app_id):
    """The user alone was not enough, and this is the regression test.

    Hashing the username separates two *accounts*, but not one account signed
    in twice — console plus Remote Desktop. Both sessions hold their own
    ``Local\\`` mutex and are legitimately primary; the pipe has no per-session
    namespace to inherit, so before this they listened on **one name**, which
    Windows allows. Measured: the handoff went to whichever listened first,
    3 of 3, and the sender was told it succeeded — a file opened on the Remote
    Desktop session landed on the console desktop.
    """
    from src.gui.single_instance import _windows_session_id

    session = _windows_session_id()
    assert session is not None, "ProcessIdToSessionId failed on Windows"
    assert server_name(app_id).endswith(f"-s{session}")


@pytest.mark.skipif(os.name == "nt", reason="the non-Windows answer")
def test_the_session_is_not_folded_in_off_windows(app_id):
    """macOS has no equivalent case: fast user switching is a different user,
    which the username hash already separates."""
    from src.gui.single_instance import _windows_session_id

    assert _windows_session_id() is None
    assert not server_name(app_id).rpartition("-")[2].startswith("s")


def test_closing_the_primary_frees_the_name(qtbot, instances):
    """A second object can become primary once the first lets go.

    This is what makes the two-objects-in-one-process model work at all, and
    in the app it is the shutdown path.
    """
    first = instances()
    assert first.try_claim() is True
    first.close()
    assert not first.is_primary

    second = instances()
    assert second.try_claim() is True
