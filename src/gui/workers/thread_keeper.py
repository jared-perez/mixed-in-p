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

import shiboken6


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
