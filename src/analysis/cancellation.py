"""Cooperative cancellation for the analysis pipeline.

Analysis is a chain of long, uninterruptible librosa calls, so a cancel can
only be honoured *between* them. Callers pass a ``should_cancel`` predicate
down the chain; each stage boundary calls :func:`check_cancelled`, which
raises :class:`AnalysisCancelled` to unwind the whole file.

Cancellation is deliberately NOT an error: it must not be swallowed by the
broad ``except Exception`` handlers that turn a failed analysis into an error
result, or a cancelled run would be reported to the user as a failed one.
Every such handler re-raises :class:`AnalysisCancelled` first.
"""

from typing import Callable

ShouldCancel = Callable[[], bool]


class AnalysisCancelled(Exception):
    """Raised at a stage boundary when the caller has requested cancellation."""


def check_cancelled(should_cancel: ShouldCancel | None) -> None:
    """Raise :class:`AnalysisCancelled` if the caller has asked us to stop."""
    if should_cancel is not None and should_cancel():
        raise AnalysisCancelled()
