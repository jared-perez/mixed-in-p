"""SingleInstance: the handshake that keeps one app one process.

Two objects in one test process stand in for two launches. That is a fair
model of the thing that matters — a second launch must find the first and hand
its files over rather than becoming a second app — but note what it cannot
cover: the real Windows multi-select race spawns genuinely concurrent
processes, and only the Windows machine can test that (plan §8 item 4).
"""

from __future__ import annotations

import itertools
import os

import pytest
from PySide6.QtCore import QThread
from PySide6.QtNetwork import QLocalServer

from src.gui.single_instance import SingleInstance, server_name

_ids = itertools.count()


def send_off_the_main_thread(inst, paths, qtbot, timeout_ms=5000):
    """Run ``send()`` on a worker thread so the primary's loop can serve it.

    In the app these are two processes, each with its own event loop. In one
    process a blocking ``send()`` from the main thread deadlocks on Windows: a
    named-pipe write completes only once the server end *reads* it, and here
    the server end is this very thread, which is busy blocking on the write.

    It is worth being precise about why the naive version passed on macOS, so
    nobody restores it: on a Unix socket the write lands in the kernel buffer
    with no peer involvement at all, so ``bytesToWrite()`` reaches zero
    without anyone reading. The test was asserting Unix semantics, not
    behaviour — the product call was always fine, as two real Windows
    processes showed.

    ``qtbot.waitUntil`` is doing the load-bearing work here: it pumps the main
    event loop, which is what lets the primary accept the connection and drain
    the pipe while the worker writes into it.
    """
    result = {}

    class Sender(QThread):
        def run(self):
            result["ok"] = inst.send(paths)

    thread = Sender()
    thread.start()
    try:
        qtbot.waitUntil(lambda: "ok" in result, timeout=timeout_ms)
    finally:
        assert thread.wait(timeout_ms), "the sending thread never finished"
    return result["ok"]


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


def test_non_ascii_and_spaces_survive_the_wire(qtbot, instances):
    """The payload is UTF-8 JSON, so the names Windows verified stay intact."""
    primary = instances()
    assert primary.try_claim()
    received: list[list[str]] = []
    primary.files_received.connect(received.append)

    paths = ["/music/with spaces.mp3", "/music/café-日本.mp3"]
    secondary = instances()
    secondary.try_claim()
    assert send_off_the_main_thread(secondary, paths, qtbot)

    qtbot.waitUntil(lambda: bool(received), timeout=3000)
    assert received == [paths]


def test_a_bare_relaunch_still_reaches_the_primary(qtbot, instances):
    """No files, but "come to the front" is still a message worth delivering."""
    primary = instances()
    assert primary.try_claim()
    received: list[list[str]] = []
    primary.files_received.connect(received.append)

    secondary = instances()
    secondary.try_claim()
    assert send_off_the_main_thread(secondary, [], qtbot)

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


def test_send_waits_for_a_primary_that_is_still_coming_up(qtbot, instances):
    """Losing the claim means a primary exists, not that it can be reached yet.

    On Windows the mutex elects a winner *before* that winner calls
    ``listen()``, so a secondary can reach the pipe a fraction of a
    millisecond before it exists. The connect fails outright rather than
    blocking, so one failure must not be read as "nobody is home" — ``send``
    retries until its deadline.

    Simulated by starting the send first and bringing the server up only
    afterwards, which is the same ordering with the gap widened to something
    a test can observe.
    """
    from PySide6.QtCore import QTimer

    sender = instances()
    primary = instances()
    received: list[list[str]] = []

    def bring_up():
        assert primary.try_claim() is True
        primary.files_received.connect(received.append)

    QTimer.singleShot(150, bring_up)

    assert send_off_the_main_thread(sender, ["/music/late.mp3"], qtbot) is True
    qtbot.waitUntil(lambda: bool(received), timeout=3000)
    assert received == [["/music/late.mp3"]]


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
