"""One app, one process — and a way to hand files to the one that exists.

"Open with Mixed in P" must reach the *running* app. The OS gives us no help
here: it simply launches the executable again with the file appended to argv,
so without this module a second window would open on a second ``Library()``
connection to one ``library.db``, both auto-saving Scratch over each other.
That is the worst outcome available, which is why the rule is absolute — a
failed handoff fails visibly and never falls back to a second instance.

There are two separable jobs here, and conflating them is a bug:

* **The claim** — deciding, exactly once, which process is the primary.
* **The transport** — how everyone else hands it their files.

The transport is a ``QLocalServer`` on both platforms: a named pipe on
Windows, a Unix domain socket elsewhere. **The claim cannot be, because
``listen()`` is only exclusive on one of them.**

On macOS and Linux a bound socket path *is* exclusive: a second ``listen()``
on a live name fails, so winning the bind is a genuine claim. The only
complication is the opposite one — the socket file outlives the process that
made it, so after a crash ``listen()`` fails forever and every later launch
misroutes. ``removeServer()`` clears that, and ``_claim_posix`` only reaches
for it after a connect has failed, a listen has failed, *and* a second connect
has failed too, which between them rule out a live primary. Removing it on the
first failed probe would let a momentarily unresponsive primary be evicted,
which manufactures the very outcome this module prevents.

**On Windows a named pipe permits many server instances of one name, so a
second ``listen()`` on a live name SUCCEEDS.** Measured on Windows 11 with Qt
6.11: with a primary demonstrably alive and answering, a second ``listen()``
returned true. A claim built on "the loser of the listen race retries the
connect" is therefore dead code there — nobody ever loses. Probing first
narrows the hole to the gap between "my probe found nobody" and "my pipe is
up" (measured at ~0.3 ms), but does not close it: five launches forced to
contend produced **five primaries, zero handoffs, five times out of five**.
Low probability, worst possible consequence.

So on Windows the claim is a **named mutex**, which is exclusive by contract.
It has the property this module already depends on elsewhere: the kernel
object dies with the process, so there is no stale-lock story to mirror the
stale-socket one. ``listen()`` is demoted to what it should always have been —
how the winner receives files.

One consequence for the loser: having lost the mutex it must connect to a
primary that may not have called ``listen()`` yet (~0.25 ms behind). So
``send`` retries the connect until its deadline rather than concluding from a
single failure that nobody is home.

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
import sys
import time

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger(__name__)

APP_ID = "MixedInP"

_WINDOWS = sys.platform == "win32"

# Wait this long for a connect (retries included), and for bytes to reach the
# pipe. Generous on purpose — see the module note. If Windows testing shows a
# busy primary being missed, this is the number to raise.
CONNECT_TIMEOUT_MS = 2000
WRITE_TIMEOUT_MS = 2000

# Gap between connect attempts while waiting for a just-elected primary to
# finish calling listen(). Short: the wait being measured is sub-millisecond.
_CONNECT_BACKOFF_MS = 20
# One connect attempt's own timeout. Kept small so a retry loop stays
# responsive; the overall budget is CONNECT_TIMEOUT_MS.
_CONNECT_ATTEMPT_MS = 200

# POSIX only: how many times to re-probe after losing a listen() race before
# concluding the socket file is stale rather than live.
_LISTEN_RETRIES = 3
_LISTEN_BACKOFF_MS = 50

# A frame longer than this is garbage or hostile, not a file list; drop the
# connection rather than allocate for it.
_MAX_PAYLOAD = 1 << 20

_HEADER = struct.Struct(">I")

# Windows: CreateMutexW succeeded but the named object was already there.
_ERROR_ALREADY_EXISTS = 183


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

    The object owns its server (and, on Windows, its mutex) for its lifetime;
    ``close()`` releases both, and is what lets a test run two of these in one
    process.
    """

    #: Emitted on the primary with the paths a secondary handed over. The list
    #: may be empty — a bare relaunch (double-clicking the app while it runs)
    #: carries no files but still means "come to the front".
    files_received = Signal(list)

    def __init__(self, app_id: str = APP_ID, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._name = server_name(app_id)
        self._server: QLocalServer | None = None
        self._mutex = None  # Windows HANDLE, held for the process's lifetime
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

        The two platforms genuinely need different primitives here; the
        asymmetry is deliberate, not an accident of history. See the module
        docstring for the measurement that forced it.
        """
        if _WINDOWS:
            return self._claim_windows()
        return self._claim_posix()

    def _new_server(self) -> QLocalServer:
        server = QLocalServer(self)
        # Unix only: keep the socket file readable by this user alone. A no-op
        # on Windows, where the pipe's default ACL already scopes to the session.
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        return server

    def _claim_windows(self) -> bool:
        """The mutex decides; the pipe is only how the winner is reached."""
        if not self._acquire_mutex():
            return False

        server = self._new_server()
        if self._listen(server):
            return True

        # We hold the claim but cannot serve it. A stale pipe cannot exist on
        # Windows, so this is not the Unix case — it is unexpected. Give the
        # mutex back rather than sit on a claim we cannot honour, so the next
        # launch gets a clean try instead of inheriting a dead primary.
        logger.warning("Won the instance mutex but could not listen on '%s'.", self._name)
        self._release_mutex()
        server.deleteLater()
        return False

    def _claim_posix(self) -> bool:
        """Winning the socket bind *is* the claim; the risk is a stale file."""
        if self._probe():
            return False

        server = self._new_server()
        if self._listen(server):
            return True

        # listen() failed. Either a socket file was left behind by a process
        # that died, or another launch claimed the name in the moment since
        # the probe. Tell them apart by asking again rather than by guessing:
        # removeServer on a live primary's socket would be the bug.
        for _ in range(_LISTEN_RETRIES):
            if self._probe():
                return False
            QLocalServer.removeServer(self._name)
            if self._listen(server):
                return True
            QThread.msleep(_LISTEN_BACKOFF_MS)

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
        """True if something is listening on our name right now.

        POSIX only. On Windows this question cannot decide the claim — a live
        answer proves a primary exists, but silence proves nothing, because a
        rival may be microseconds from binding the same name successfully.
        """
        # Unparented on purpose: Python then owns it and destroys it when this
        # returns, which is deterministic. Parenting to self would defer the
        # delete to an event loop that a probe at startup has not started yet.
        sock = QLocalSocket()
        sock.connectToServer(self._name)
        alive = sock.waitForConnected(CONNECT_TIMEOUT_MS)
        sock.close()
        return alive

    # ── The Windows claim primitive ─────────────────────────────

    def _acquire_mutex(self) -> bool:
        """Create the named mutex, or discover someone else already has it.

        ``CreateMutexW`` + ``ERROR_ALREADY_EXISTS`` is the standard Windows
        idiom and the only thing here that is exclusive by contract. Reached
        through ``ctypes`` rather than a new dependency: it is one call.

        ``bInitialOwner`` is false on purpose. We care only whether the named
        *object* exists, never about thread ownership — the object lives while
        any handle is open, and every handle closes when its process ends,
        including one that crashed. That is what makes the Windows side free
        of the stale-claim problem the Unix side has to handle.

        A failure to create the object at all returns False, which makes this
        launch a secondary. That is the safe direction: the worst case is a
        visible "already running" message, never two apps on one database.
        """
        import ctypes
        from ctypes import wintypes

        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateMutexW.argtypes = [
                wintypes.LPVOID,
                wintypes.BOOL,
                wintypes.LPCWSTR,
            ]
            kernel32.CreateMutexW.restype = wintypes.HANDLE
            # "Local\" scopes the object to this login session, matching the
            # per-session pipe and the per-user name.
            handle = kernel32.CreateMutexW(None, False, f"Local\\{self._name}")
            err = ctypes.get_last_error()
        except Exception:
            logger.exception("Could not create the single-instance mutex.")
            return False

        if not handle:
            logger.warning("CreateMutexW returned no handle (error %d).", err)
            return False
        if err == _ERROR_ALREADY_EXISTS:
            ctypes.WinDLL("kernel32").CloseHandle(handle)
            return False

        self._mutex = handle
        return True

    def _release_mutex(self) -> None:
        if self._mutex is None:
            return
        try:
            import ctypes

            ctypes.WinDLL("kernel32").CloseHandle(self._mutex)
        except Exception:
            logger.exception("Could not release the single-instance mutex.")
        finally:
            self._mutex = None

    # ── Secondary → primary ─────────────────────────────────────

    def send(self, paths: list[str], timeout_ms: int = CONNECT_TIMEOUT_MS) -> bool:
        """Hand *paths* to the primary. False if the handoff did not complete.

        A False here is not a cue to open a window anyway — the caller must
        say so and exit. Note the confirmation is that the bytes reached the
        pipe, not that the primary has acted on them: there is no ack, because
        the failure that actually happens is "nothing is listening", and that
        one is caught by the connect.

        **Blocking, and it needs the primary's event loop to be running.** On
        Windows a named-pipe write completes only once the server end reads
        it, so this cannot be called from the same thread that would do the
        reading. In the app that is never a question — the two sides are two
        processes. In a test they are not, which is why the tests drive this
        from a worker thread while the main loop pumps.
        """
        sock = self._connect_to_primary(timeout_ms)
        if sock is None:
            return False

        try:
            payload = json.dumps(list(paths)).encode("utf-8")
            sock.write(_HEADER.pack(len(payload)) + payload)
            # Loop rather than a single wait: waitForBytesWritten reports "no
            # progress", which is indistinguishable from "already finished".
            while sock.bytesToWrite() > 0:
                if not sock.waitForBytesWritten(WRITE_TIMEOUT_MS):
                    logger.warning("Timed out handing files to the primary instance.")
                    return False

            sock.disconnectFromServer()
            if sock.state() != QLocalSocket.LocalSocketState.UnconnectedState:
                sock.waitForDisconnected(timeout_ms)
            return True
        finally:
            # close() rather than abort(), and no deleteLater: an aborted
            # socket left for a later event loop to collect is what turned
            # three timed-out sends into an interpreter abort in an unrelated
            # test. Unparented, so Python destroys it here and now.
            sock.close()

    def _connect_to_primary(self, timeout_ms: int) -> QLocalSocket | None:
        """Connect, retrying until *timeout_ms* is spent. None if nobody came.

        The retry is not defensive padding — it is required by the Windows
        claim. Losing the mutex means a primary was elected, but that winner
        is a fraction of a millisecond behind us and may not have reached
        ``listen()`` yet, so its pipe does not exist and the first connect
        fails outright rather than blocking. One failure is not an answer.

        The whole loop is still bounded by *timeout_ms*, so the genuinely
        empty case — nothing running at all — still fails inside its budget
        instead of hanging a process the user cannot see.
        """
        deadline = time.monotonic() + timeout_ms / 1000.0
        attempt = 0
        while True:
            # Unparented: the caller may be on a worker thread, and a QObject
            # cannot take a parent that lives in another one.
            sock = QLocalSocket()
            sock.connectToServer(self._name)
            if sock.waitForConnected(min(_CONNECT_ATTEMPT_MS, timeout_ms)):
                return sock
            sock.close()
            attempt += 1
            if time.monotonic() >= deadline:
                logger.warning(
                    "No primary instance answered on '%s' after %d attempt(s).",
                    self._name,
                    attempt,
                )
                return None
            QThread.msleep(_CONNECT_BACKOFF_MS)

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
        """Release the server and the claim so another object can take them.

        The primary holds both for the whole session, so in the app this only
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
        self._release_mutex()
