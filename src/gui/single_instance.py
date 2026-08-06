"""One app, one process — and a way to hand files to the one that exists.

"Open with Mixed in P" must reach the *running* app. The OS gives us no help
here: it simply launches the executable again with the file appended to argv,
so without this module a second window would open on a second ``Library()``
connection to one ``library.db``, both auto-saving Scratch over each other.
That is the worst outcome available, which is why the rule is absolute — a
failed handoff fails visibly and never falls back to a second instance.

The mechanism is a ``QLocalServer``: a named pipe on Windows, a Unix domain
socket elsewhere. The first process to ``listen()`` is the primary; every
later launch connects to it, writes its file list and exits before building a
window (or opening the database).

**The cleanup story differs by platform, and both halves are needed here.**

- On **macOS/Linux** the socket *file* outlives the process that made it, so
  after a crash ``listen()`` fails with an address-in-use error forever and
  every later launch misroutes. ``removeServer()`` clears it.
- On **Windows** a named pipe dies with its process, so there is no stale-pipe
  problem at all — its risks are races instead. Two launches milliseconds
  apart (selecting five files and choosing "Open with" is an ordinary way to
  produce several) can both find nobody home and both try to ``listen()``.
  One wins; **the loser must go back and connect**, not assume it is primary.

``try_claim`` therefore probes before removing anything: it only calls
``removeServer`` after a connect has failed *and* a ``listen`` has failed
*and* a second connect has failed too, which between them rule out a live
primary. Removing eagerly on a failed probe would let a momentarily
unresponsive primary be evicted, which is the one way to end up with the two
processes this module exists to prevent.

Timeouts are deliberately generous. The primary may be mid-decode when a
secondary knocks, and the secondary is a process the user never sees — a
second of latency there costs nothing, while concluding "nobody is home" too
early costs the guarantee.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import logging
import os
import struct

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger(__name__)

APP_ID = "MixedInP"

# Wait this long for a connect, and for bytes to reach the pipe. Generous on
# purpose (see the module note). If Windows testing shows a busy primary being
# missed, this is the number to raise.
CONNECT_TIMEOUT_MS = 2000
WRITE_TIMEOUT_MS = 2000

# How many times to re-probe after losing a listen() race before giving up.
_RACE_RETRIES = 3
_RACE_BACKOFF_MS = 50

# A frame longer than this is garbage or hostile, not a file list; drop the
# connection rather than allocate for it.
_MAX_PAYLOAD = 1 << 20

_HEADER = struct.Struct(">I")


def server_name(app_id: str = APP_ID) -> str:
    """The pipe/socket name for *app_id*, scoped to the current user.

    The user is folded in because named pipes are visible across a whole
    Windows machine: on a shared PC or a Remote Desktop host, two people
    signed in at once would otherwise collide on one name and each other's
    files would land in the wrong session.

    It is *hashed* rather than appended raw because a username is not a safe
    name fragment — a Windows domain account reads ``DOMAIN\\user``, and the
    backslash is a path separator in a pipe name — while on Unix the socket
    lives at a filesystem path with a length limit worth staying well under.
    """
    try:
        user = getpass.getuser()
    except Exception:
        # getuser() consults the environment and the password database; both
        # can be absent in a stripped-down or service context.
        user = str(os.getuid()) if hasattr(os, "getuid") else "unknown"
    digest = hashlib.sha256(user.encode("utf-8", "replace")).hexdigest()[:12]
    return f"{app_id}-{digest}"


class SingleInstance(QObject):
    """Claim the role of primary, or hand files to whoever already has it.

    Usage is a two-step at startup::

        inst = SingleInstance()
        if not inst.try_claim():
            ok = inst.send(paths)   # secondary: hand off and exit
            ...
        inst.files_received.connect(window.open_files)   # primary: stay

    The object owns its server for its lifetime; ``close()`` releases it, and
    is what lets a test run two of these in one process.
    """

    #: Emitted on the primary with the paths a secondary handed over. The list
    #: may be empty — a bare relaunch (double-clicking the app while it runs)
    #: carries no files but still means "come to the front".
    files_received = Signal(list)

    def __init__(self, app_id: str = APP_ID, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._name = server_name(app_id)
        self._server: QLocalServer | None = None
        self._buffers: dict[QLocalSocket, bytearray] = {}

    @property
    def name(self) -> str:
        """The pipe/socket name in use (useful in logs and tests)."""
        return self._name

    @property
    def is_primary(self) -> bool:
        return self._server is not None

    # ── Claiming ────────────────────────────────────────────────

    def try_claim(self) -> bool:
        """True if we are now the primary; False if another instance lives.

        False does **not** distinguish "another instance answered" from "could
        not claim and could not connect" — see ``send``, which is the call
        that finds out, and whose failure is the one the caller must surface.
        """
        if self._probe():
            return False

        server = QLocalServer(self)
        # Unix only: keep the socket file readable by this user alone. A no-op
        # on Windows, where the pipe's default ACL already scopes to the session.
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)

        if self._listen(server):
            return True

        # listen() failed. Either a socket file was left behind by a process
        # that died (Unix), or another launch claimed the name in the moment
        # since the probe (both platforms). Tell them apart by asking again
        # rather than by guessing.
        for _ in range(_RACE_RETRIES):
            if self._probe():
                return False
            QLocalServer.removeServer(self._name)
            if self._listen(server):
                return True
            QThread.msleep(_RACE_BACKOFF_MS)

        logger.warning(
            "Could not claim or reach the single-instance server '%s'.", self._name
        )
        server.deleteLater()
        return False

    def _listen(self, server: QLocalServer) -> bool:
        if not server.listen(self._name):
            return False
        self._server = server
        server.newConnection.connect(self._on_new_connection)
        return True

    def _probe(self) -> bool:
        """True if something is listening on our name right now."""
        sock = QLocalSocket()
        sock.connectToServer(self._name)
        alive = sock.waitForConnected(CONNECT_TIMEOUT_MS)
        sock.abort()
        return alive

    # ── Secondary → primary ─────────────────────────────────────

    def send(self, paths: list[str], timeout_ms: int = CONNECT_TIMEOUT_MS) -> bool:
        """Hand *paths* to the primary. False if the handoff did not complete.

        A False here is not a cue to open a window anyway — the caller must
        say so and exit. Note the confirmation is that the bytes reached the
        pipe, not that the primary has acted on them: there is no ack, because
        the failure that actually happens is "nothing is listening", and that
        one is caught by the connect.
        """
        sock = QLocalSocket()
        sock.connectToServer(self._name)
        if not sock.waitForConnected(timeout_ms):
            logger.warning("No primary instance answered on '%s'.", self._name)
            return False

        payload = json.dumps(list(paths)).encode("utf-8")
        sock.write(_HEADER.pack(len(payload)) + payload)
        # Loop rather than a single wait: waitForBytesWritten reports "no
        # progress", which is indistinguishable from "already finished".
        while sock.bytesToWrite() > 0:
            if not sock.waitForBytesWritten(WRITE_TIMEOUT_MS):
                logger.warning("Timed out handing files to the primary instance.")
                sock.abort()
                return False

        sock.disconnectFromServer()
        if sock.state() != QLocalSocket.LocalSocketState.UnconnectedState:
            sock.waitForDisconnected(timeout_ms)
        return True

    # ── Primary side ────────────────────────────────────────────

    def _on_new_connection(self) -> None:
        assert self._server is not None
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            if sock is None:
                break
            self._buffers[sock] = bytearray()
            sock.readyRead.connect(lambda s=sock: self._on_ready_read(s))
            sock.disconnected.connect(lambda s=sock: self._drop(s))

    def _on_ready_read(self, sock: QLocalSocket) -> None:
        buf = self._buffers.get(sock)
        if buf is None:
            return
        buf += bytes(sock.readAll().data())

        if len(buf) < _HEADER.size:
            return
        (size,) = _HEADER.unpack_from(buf, 0)
        if size > _MAX_PAYLOAD:
            logger.warning("Oversized handoff frame (%d bytes); dropping.", size)
            self._drop(sock)
            return
        if len(buf) < _HEADER.size + size:
            return  # still arriving

        payload = bytes(buf[_HEADER.size : _HEADER.size + size])
        self._drop(sock)

        try:
            paths = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            logger.warning("Unreadable handoff frame; ignoring.")
            return
        if not isinstance(paths, list):
            return
        self.files_received.emit([p for p in paths if isinstance(p, str)])

    def _drop(self, sock: QLocalSocket) -> None:
        self._buffers.pop(sock, None)
        sock.close()
        sock.deleteLater()

    # ── Teardown ────────────────────────────────────────────────

    def close(self) -> None:
        """Release the server so another object can claim the name.

        The primary holds it for the whole session, so in the app this only
        runs at shutdown — but a test that wants a *second* SingleInstance to
        become primary needs it, and so does anything that claims and then
        decides not to proceed.
        """
        for sock in list(self._buffers):
            self._drop(sock)
        if self._server is not None:
            self._server.close()
            self._server.deleteLater()
            self._server = None
        # Unix leaves the socket file behind even on an orderly close.
        QLocalServer.removeServer(self._name)
