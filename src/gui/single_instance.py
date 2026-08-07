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
Windows, a Unix domain socket elsewhere. **The claim cannot be a QLocalServer
on either platform**, and both halves of that were learned the hard way, by
launching five processes at once and counting the primaries.

**Windows: a named pipe permits many server instances of one name**, so a
second ``listen()`` on a *live* name succeeds. Measured on Windows 11 with Qt
6.11, with a primary demonstrably alive and answering. A claim built on the
loser of a listen race retrying is dead code there — nobody ever loses. Five
launches forced to contend: **five primaries, zero handoffs, 5 of 5.**

**POSIX: the bind really is exclusive — and that is not enough.** A second
``listen()`` on a live path fails with ``EEXIST``, so winning the bind looks
like a genuine claim. The trap is what a loser does next. There is a window in
which a primary has *created* its socket file but is not yet accepting, and a
connect during it is refused exactly as it would be for a file left behind by
a crash. Code that probes, sees a refusal, and clears the path to recover from
the stale case will instead **unlink a live primary's socket** — after which
its own bind succeeds and it becomes a second primary. Each loser evicts the
previous winner in turn. Measured on macOS: **five primaries, 5 of 5,
deterministically.** The bug is not the probe being too slow; it is that a
refused connect cannot distinguish "dead" from "not ready yet", and the
recovery for one is fatal to the other.

So on both platforms the claim is an OS primitive that is exclusive *by
contract* and that the kernel releases when the process ends, however it ends:
a **named mutex** on Windows, an **flock** on POSIX. No probing, no guessing
about liveness, and nothing another process can take away. ``listen()`` is
demoted to what it should always have been — how the winner receives files.

That also makes the stale-socket problem trivial rather than delicate.
Holding the claim proves no other process is primary, so a socket file at our
path can only be one a dead process left; ``removeServer`` is called there and
nowhere else, and cannot evict anybody.

One consequence for the loser: having lost the claim it must connect to a
primary that may not have called ``listen()`` yet. So ``send`` retries the
connect until its deadline rather than concluding from a single failure that
nobody is home.

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

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThread, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from ..utils.app_dirs import get_app_data_dir

logger = logging.getLogger(__name__)

APP_ID = "MixedInP"

_WINDOWS = sys.platform == "win32"

# How long to keep trying to reach the primary. Only ever spent when we have
# already lost the claim, so a primary demonstrably exists and is merely slow
# to call listen() — measured in fractions of a millisecond.
CONNECT_TIMEOUT_MS = 2000

# How long to wait for the bytes to land. Much larger than the connect budget,
# and the asymmetry is the point.
#
# A named-pipe write completes only once the server end *reads*, and the
# primary does not read anything between claiming the instance and reaching
# app.exec() — the whole of MainWindow construction, measured at 1.08 s warm on
# Windows. Five cold starts at once (which is exactly what a five-file
# multi-select is) import PySide6, librosa and numpy simultaneously from a cold
# file cache, and that is the slowest this phase ever gets. At 2 s the margin
# was under a second and a cold first run really did blow it.
#
# Overshooting costs almost nothing: the waiter is a process the user never
# sees, and a primary that has actually died fails the write with an error
# rather than a timeout, so this bound is only reached by one that is alive and
# busy. Undershooting costs a visible "those files weren't opened" dialog for
# files that would have arrived. Prefer the invisible cost.
WRITE_TIMEOUT_MS = 30000

# Gap between connect attempts while waiting for a just-elected primary to
# finish calling listen(). Short: the wait being measured is sub-millisecond.
_CONNECT_BACKOFF_MS = 20
# One connect attempt's own timeout. Kept small so a retry loop stays
# responsive; the overall budget is CONNECT_TIMEOUT_MS.
_CONNECT_ATTEMPT_MS = 200

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
        self._lock_fd: int | None = None  # POSIX flock fd, likewise
        self._buffers: dict[QLocalSocket, bytearray] = {}
        self._pending: list[str] = []
        self._pending_any = False
        self._delivering = False

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

        One flow, with one platform-specific primitive inside it. Both
        primitives have the property the claim actually needs: exclusive by
        contract, and released by the kernel when the process ends, so a crash
        leaves nothing behind to clean up or misread.
        """
        if not self._acquire_claim():
            return False

        # Holding the claim means no other process can be primary, and that
        # is the *only* thing that makes this safe. A socket file at our path
        # now can only be one a dead process left behind, so clearing it
        # cannot evict anybody. Called from nowhere else, for that reason.
        # A no-op on Windows, where a pipe dies with its process.
        QLocalServer.removeServer(self._name)

        server = self._new_server()
        if self._listen(server):
            return True

        # We hold a claim we cannot serve. Sitting on it would be the worst
        # failure available: every later launch would lose the claim, conclude
        # a primary exists, fail to reach it, and refuse to open — a dead
        # primary nothing can dislodge. Give it back instead.
        logger.warning("Won the instance claim but could not listen on '%s'.", self._name)
        self._release_claim()
        server.deleteLater()
        return False

    def _acquire_claim(self) -> bool:
        return self._acquire_mutex() if _WINDOWS else self._acquire_lock_file()

    def _release_claim(self) -> None:
        if _WINDOWS:
            self._release_mutex()
        else:
            self._release_lock_file()

    def _new_server(self) -> QLocalServer:
        server = QLocalServer(self)
        # Unix only: keep the socket file readable by this user alone. A no-op
        # on Windows, where the pipe's default ACL already scopes to the session.
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        return server

    def _listen(self, server: QLocalServer) -> bool:
        """Open the door, with somebody already standing at it.

        The receiver is wired **before** ``listen()`` rather than after, and
        then the queue is drained once by hand. Both halves are needed, and
        for the same reason the socket-level drain is: ``newConnection`` is a
        one-shot edge, so a connection accepted while nothing is attached
        leaves the signal fired to nobody and the connection sitting in the
        pending queue — where it stays, because the only thing that would
        collect it is the slot that missed the announcement.

        The window between ``listen()`` returning and the next statement
        reads as impossibly small, and on macOS it is. On Windows it was wide
        enough for an entire five-way race to pass through: every secondary
        connected, wrote, disconnected and reported success, and the primary
        recorded *zero* deliveries.
        """
        server.newConnection.connect(self._on_new_connection)
        if not server.listen(self._name):
            server.newConnection.disconnect(self._on_new_connection)
            return False
        self._server = server
        self._on_new_connection()
        return True

    # ── The claim primitives ────────────────────────────────────

    def _acquire_lock_file(self) -> bool:
        """POSIX: take an exclusive ``flock``, or find that somebody has it.

        ``flock`` is the counterpart of the Windows mutex and was chosen for
        the same property: the kernel drops it when the process ends, however
        it ends, so a crash leaves no stale claim to misread. It also works
        between two objects in one process, because the lock belongs to the
        open file description rather than the process — which POSIX record
        locks (``lockf``) do not, and which the tests depend on.

        The lock lives in the app data directory rather than beside the
        socket in ``/tmp``: a temp cleaner deleting the file out from under a
        held lock would let the next launch create a fresh one and win it,
        which is two primaries again by a slower route.
        """
        import fcntl

        try:
            path = str(get_app_data_dir() / f"{self._name}.lock")
            fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        except OSError:
            logger.exception("Could not open the single-instance lock file.")
            return False

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False

        self._lock_fd = fd
        return True

    def _release_lock_file(self) -> None:
        if self._lock_fd is None:
            return
        try:
            import fcntl

            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
        except OSError:
            logger.exception("Could not release the single-instance lock.")
        finally:
            os.close(self._lock_fd)
            self._lock_fd = None

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
                    # A failed wait is not proof of a failed write. The primary
                    # reads the frame and closes at once, so the peer can be
                    # gone by the time this returns — reporting False then
                    # tells the user a handoff failed for a file that actually
                    # opened, which per rule 4 is a visible error message about
                    # nothing. Believe the byte count, not the wait.
                    if sock.bytesToWrite() == 0:
                        break
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

    def start_delivering(self) -> None:
        """Emit from now on, and replay whatever arrived before a receiver did.

        Call once, on the primary, after connecting ``files_received``.
        Nothing is emitted until this runs — a handoff can complete during
        the claim itself, which is long before the window that answers it
        exists. Safe to call when nothing was buffered; that is the ordinary
        launch.
        """
        self._delivering = True
        if self._pending_any:
            pending, self._pending = self._pending, []
            self._pending_any = False
            logger.info("Replaying %d file(s) handed over during startup.", len(pending))
            self.files_received.emit(pending)

    # ── Primary side ────────────────────────────────────────────

    def _on_new_connection(self) -> None:
        if self._server is None:
            return
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            if sock is None:
                break
            self._buffers[sock] = bytearray()
            sock.readyRead.connect(lambda s=sock: self._on_ready_read(s))
            sock.disconnected.connect(lambda s=sock: self._on_disconnected(s))
            # Read what is already here before waiting for a signal to say so.
            #
            # A handoff is tiny and the sender writes it and disconnects at
            # once, so a connection routinely arrives *already complete*: the
            # bytes are sitting in the socket and readyRead has already fired
            # before this slot ever ran. It will not fire again — nothing more
            # is coming — so waiting for it means waiting forever, and the
            # payload is discarded when the socket disconnects.
            #
            # That failure is silent on the success path, which is what makes
            # it nasty: across processes the payload fits the pipe buffer, so
            # the sender's write completes and send() returns True for a file
            # that never arrives. Measured at ~15% of handoffs during a
            # five-way race, where secondaries connect while the winner is
            # still starting its event loop.
            self._on_ready_read(sock)

    def _on_disconnected(self, sock: QLocalSocket) -> None:
        """Take a last read before letting the socket go.

        The peer can write everything and hang up before this side services
        the connection at all, so dropping on disconnect without reading
        throws away a payload the sender already saw succeed. Anything still
        incomplete after this really is a truncated frame, and is dropped.
        """
        self._on_ready_read(sock)
        self._drop(sock)

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
        self._deliver([p for p in paths if isinstance(p, str)])

    def _deliver(self, paths: list[str]) -> None:
        """Emit *paths*, or hold them until somebody is listening.

        The third place the same "the event already happened" shape shows up,
        and the one no amount of Windows testing would have found yet, because
        it is upstairs in ``run_app``::

            instance.try_claim()                            # can deliver here
            window = MainWindow()                           # ~500 ms
            instance.files_received.connect(window.open_files)

        ``try_claim`` now drains the pending queue itself, so a handoff that
        arrives during the race is read *before* the window exists — and an
        emission with nothing connected to it is a file silently discarded.
        That is the same fate the signal-wiring fixes below just rescued it
        from, two levels down.

        So this holds early arrivals and ``start_delivering`` replays them,
        exactly as ``FileOpenRelay`` does for the macOS event that can beat
        the window into existence. Batching them into one emission is also
        deliberate: five secondaries during one race should raise the window
        and load Scratch once, not five times.
        """
        if self._delivering:
            self.files_received.emit(paths)
            return
        self._pending.extend(paths)
        # Tracked separately from the list because a bare relaunch carries no
        # files and would otherwise be indistinguishable from nothing having
        # happened — and "come to the front" is still a message.
        self._pending_any = True

    def _drop(self, sock: QLocalSocket) -> None:
        """Finish with *sock*. Idempotent, and it has to be.

        A complete frame drops the socket from ``_on_ready_read``, and the
        disconnect that follows drops it again. The buffer is the record of
        whether we still own it: past the first call the C++ object is already
        queued for deletion, and touching it then is how a double-drop turns
        into a crash rather than a no-op.

        ``deleteLater`` rather than an immediate delete because this is often
        reached from inside the socket's own signal handler, which is the case
        deferred deletion exists for.
        """
        if self._buffers.pop(sock, None) is None:
            return
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

        # Run the deletions we just asked for, rather than leaving them to an
        # event loop that may never come round again.
        #
        # Connection sockets are children of the server, so a pending delete
        # on a socket plus a pending delete on the server is a trap: whichever
        # destroys the server first takes its children with it, and the
        # socket's own delete then lands on freed memory. Flushing here runs
        # them in the order they were posted — sockets first, then their
        # parent — which is the order that is safe. Only DeferredDelete is
        # sent, so nothing else about the caller's state moves.
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        # Unix leaves the socket file behind even on an orderly close.
        QLocalServer.removeServer(self._name)
        self._release_claim()
