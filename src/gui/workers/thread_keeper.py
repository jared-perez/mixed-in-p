"""Keep QThread/worker Python wrappers alive until their C++ objects are gone.

When a ``QThread`` or a moved-to-thread worker is torn down via ``deleteLater``,
the C++ destructor calls a virtual (``disconnectNotify``) that shiboken routes
back to the object's Python wrapper. If that wrapper was already
garbage-collected — which happens the instant the last Python reference is
dropped, e.g. reassigning the single attribute that held it *before* the pending
``deleteLater`` has actually run — the callback dereferences freed memory and the
process dies with ``SIGBUS`` (``EXC_BAD_ACCESS``).

The common trigger is rapid restarts of a single-slot worker pipeline (the Player
panel's decode/waveform workers, the Spectrum render worker): the previous run's
``deleteLater`` is still queued when the next run reassigns the slot and drops the
last reference.

:func:`keep_alive` closes that window by holding a strong reference to each
thread/worker group until shiboken reports its C++ object invalid — i.e. only
*after* the deferred delete has destroyed it, when releasing the wrapper is safe.
"""

from __future__ import annotations

import logging

import shiboken6
from PySide6.QtCore import QThread

logger = logging.getLogger(__name__)


def keep_alive(store: list, *objs: object) -> None:
    """Retain ``objs`` in ``store``, then drop any group whose C++ side is gone.

    Call once per thread/worker creation, passing the same ``store`` list (owned
    by the panel) each time. Groups are pruned lazily on later calls: a group is
    released only when *every* object in it has been destroyed on the C++ side
    (``shiboken6.isValid`` is False), so a wrapper is never collected while its
    C++ object — and the pending ``deleteLater`` destructor — still exist.
    """
    store.append(objs)
    store[:] = [
        group for group in store if any(shiboken6.isValid(o) for o in group)
    ]


def wait_for_threads(store: list, timeout_ms: int = 5000) -> bool:
    """Quit and wait for every live ``QThread`` held in ``store``.

    Call from a panel's shutdown path. Returns False if any thread was still
    running when the timeout expired, so a caller can log it.

    There is nothing to *cancel*: a decode or a render is one long blocking
    call, so ``quit()`` only ends the thread's event loop and the wait is for
    the work already in flight. That wait is the point. It buys three things:

    * On Windows an open read handle blocks the file from being renamed or
      deleted (``WinError 32``) — the same lock class the rename worker already
      carries retry logic for. A prefetch still running after the user has
      moved on can collide with a rename of that very file.
    * Destroying a ``QThread`` that is still running is undefined behaviour;
      Qt warns ``QThread: Destroyed while thread is still running`` and the
      process may take the abort.
    * A worker that outlives its panel emits into a deleted receiver.

    Threads whose C++ object is already gone are skipped, so this is safe to
    call twice and safe to call after the deferred deletes have run.
    """
    clean = True
    for group in list(store):
        for obj in group:
            if not isinstance(obj, QThread) or not shiboken6.isValid(obj):
                continue
            if not obj.isRunning():
                continue
            obj.quit()
            if not obj.wait(timeout_ms):
                clean = False
                logger.warning("Worker thread did not finish within %dms", timeout_ms)
    return clean
