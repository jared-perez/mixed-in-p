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
from PySide6.QtCore import QThread
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

    The socket is fully torn down before returning, rather than handed back
    for the test to hold. A half-disconnected QLocalSocket collected by Python
    at the end of a test leaves a notifier pointing at freed memory, which
    surfaces as a segfault inside the *next* test's event loop — a genuinely
    horrible thing to debug, and it cost a run here to find. The delivery does
    not need the socket alive: the connection is already accepted and the
    bytes are already in the buffer, which is the whole point of the shape
    being reproduced.
    """
    payload = json.dumps(paths).encode("utf-8")
    sock = QLocalSocket()
    sock.connectToServer(inst.name)
    assert sock.waitForConnected(timeout_ms), "test setup: no primary answered"
    sock.write(_HEADER.pack(len(payload)) + payload)
    sock.flush()
    sock.disconnectFromServer()
    if sock.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        sock.waitForDisconnected(timeout_ms)
    sock.close()


def run_off_the_main_thread(fn, qtbot, timeout_ms=5000):
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

    ``qtbot.waitUntil`` does the load-bearing work: it pumps the main event
    loop, which is what lets the primary serve the worker.
    """
    result = {}

    class Worker(QThread):
        def run(self):
            result["value"] = fn()

    thread = Worker()
    thread.start()
    try:
        qtbot.waitUntil(lambda: "value" in result, timeout=timeout_ms)
    finally:
        assert thread.wait(timeout_ms), "the worker thread never finished"
    return result["value"]


def send_off_the_main_thread(inst, paths, qtbot, timeout_ms=5000):
    """``send()``, driven so the primary can serve it. See the note above."""
    return run_off_the_main_thread(lambda: inst.send(paths), qtbot, timeout_ms)


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


def test_the_first_claim_wins_and_the_second_does_not(instances):
    primary = instances()
    assert primary.try_claim() is True
    assert primary.is_primary

    secondary = instances()
    assert secondary.try_claim() is False
    assert not secondary.is_primary


def test_paths_round_trip_to_the_primary(qtbot, instances):
    primary = instances()
    assert primary.try_claim()

    received: list[list[str]] = []
    primary.files_received.connect(received.append)

    secondary = instances()
    assert secondary.try_claim() is False
    assert send_off_the_main_thread(secondary, ["/music/a.mp3", "/music/b.mp3"], qtbot)

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

    # Look away while the whole handoff happens: connect, write, hang up.
    primary._server.newConnection.disconnect()
    hand_off(primary, ["/music/a.mp3", "/music/b.mp3"], qtbot)
    qtbot.wait(50)
    assert not received, "test setup: the primary was not actually looking away"

    primary._on_new_connection()

    assert received == [["/music/a.mp3", "/music/b.mp3"]]


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


class TestWindowsClaimSequencing:
    """The Windows branch's ordering, forced so it runs on any platform.

    The real ``CreateMutexW`` call and the real failures are Windows-only, but
    the *sequencing* is ordinary logic and is where the mistakes live. Testing
    it here means the Windows machine is not the only thing standing between a
    refactor and a regression in the half it cannot see.
    """

    def test_the_mutex_is_taken_before_the_pipe_is_opened(self, instances, monkeypatch):
        """Order matters: the mutex is the claim, listen is only transport.

        Listening first would re-open the hole the mutex exists to close — a
        second launch could bind the same live pipe name on Windows and both
        would consider themselves primary.
        """
        inst = instances()
        order: list[str] = []
        monkeypatch.setattr(inst, "_acquire_mutex", lambda: order.append("mutex") or True)
        monkeypatch.setattr(inst, "_listen", lambda s: order.append("listen") or True)

        assert inst._claim_windows() is True
        assert order == ["mutex", "listen"]

    def test_losing_the_mutex_never_touches_the_pipe(self, instances, monkeypatch):
        """A secondary must not bind anything — that is the whole point."""
        inst = instances()
        listened: list[str] = []
        monkeypatch.setattr(inst, "_acquire_mutex", lambda: False)
        monkeypatch.setattr(inst, "_listen", lambda s: listened.append("listen") or True)

        assert inst._claim_windows() is False
        assert listened == []

    def test_a_claim_that_cannot_be_served_is_given_back(self, instances, monkeypatch):
        """Holding the mutex while unable to listen is the worst failure here.

        Every later launch would lose the mutex, conclude a primary exists,
        fail to connect to it, and refuse to open — a dead primary that
        nothing short of ending the process can dislodge. So the claim is
        released and the next launch gets a clean try.
        """
        inst = instances()
        released: list[str] = []
        monkeypatch.setattr(inst, "_acquire_mutex", lambda: True)
        monkeypatch.setattr(inst, "_release_mutex", lambda: released.append("released"))
        monkeypatch.setattr(inst, "_listen", lambda s: False)

        assert inst._claim_windows() is False
        assert released == ["released"]

    def test_a_served_claim_is_kept(self, instances, monkeypatch):
        """The mirror of the above: the primary holds the mutex for its life."""
        inst = instances()
        released: list[str] = []
        monkeypatch.setattr(inst, "_acquire_mutex", lambda: True)
        monkeypatch.setattr(inst, "_release_mutex", lambda: released.append("released"))
        monkeypatch.setattr(inst, "_listen", lambda s: True)

        assert inst._claim_windows() is True
        assert released == []


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
    """Named pipes are machine-wide; two sessions must not share one.

    Hashed rather than appended raw because a Windows domain account reads
    ``DOMAIN\\user`` and a backslash is a separator in a pipe name.
    """
    name = server_name(app_id)
    assert name.startswith(f"{app_id}-")
    assert "\\" not in name and "/" not in name
    assert server_name(app_id) == name  # stable across calls


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
