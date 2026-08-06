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
from PySide6.QtNetwork import QLocalServer

from src.gui.single_instance import SingleInstance, server_name

_ids = itertools.count()


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
    assert secondary.send(["/music/a.mp3", "/music/b.mp3"]) is True

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
    assert secondary.send(paths) is True

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
    assert secondary.send([]) is True

    qtbot.waitUntil(lambda: bool(received), timeout=3000)
    assert received == [[]]


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
