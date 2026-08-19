"""Background worker for online metadata lookups.

Second network path in the app, and it keeps the contract the first one
(``update_worker.py``) set: manual trigger only, a QThread, a timeout, and
every failure collapsed to one of a small set of codes the UI has a sentence
for. Nothing here runs at startup.

One thread handles both shapes of request, because they are the same work with
a different starting point:

* a **lookup** — search for the file, then read the best release;
* a **fetch** — read one release the user picked from the candidate switcher,
  skipping the search.

A job carrying a candidate is the second; a job without one is the first.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from PySide6.QtCore import QThread, Signal

from src.online.result import (
    ERROR_NOT_FOUND,
    Candidate,
    LookupFailed,
    ProposedTags,
    TrackQuery,
)

logger = logging.getLogger(__name__)


@dataclass
class LookupJob:
    """One file to look up.

    ``candidate`` set means "read this release" rather than "find the file";
    ``want_artwork`` pulls the cover down with the same run, so the review
    dialog can show it without a third async path.
    """

    path: str
    query: TrackQuery
    candidate: Candidate | None = None
    want_artwork: bool = False


@dataclass
class LookupResult:
    """What one job produced. Exactly one of ``proposed`` / ``error`` is set.

    ``candidates`` is the whole ranked list, so the dialog's switcher can offer
    the alternatives without searching again — the freshness rule is about not
    *persisting* fetched content, and this list dies with the dialog.
    """

    path: str
    query: TrackQuery = field(default_factory=TrackQuery)
    candidates: list[Candidate] = field(default_factory=list)
    chosen: Candidate | None = None
    proposed: ProposedTags | None = None
    artwork: bytes = b""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.proposed is not None and not self.error


class LookupThread(QThread):
    """Runs a queue of lookups off the UI thread, one file at a time.

    Emits ``result_ready`` per file (success or failure — a failed file is a
    result with an ``error``, not a dropped one) and ``progress`` for the queue
    UI. ``waiting`` carries the seconds the provider is pausing for, so the
    panel can say "waiting for rate limit" instead of showing a stuck spinner.
    """

    result_ready = Signal(object)   # LookupResult
    progress = Signal(int, int)     # done, total
    waiting = Signal(float)         # seconds the rate limiter is pausing for
    cancelled = Signal()

    def __init__(self, provider, jobs: list[LookupJob], parent=None) -> None:
        super().__init__(parent)
        self._provider = provider
        self._jobs = list(jobs)
        self._cancelled = False

    def cancel(self) -> None:
        """Ask the run to stop after the request in flight.

        A urllib call is one long blocking call with nothing to interrupt, so
        the in-flight file is waited out and its result *discarded* — a file
        abandoned partway has nothing worth keeping.
        """
        self._cancelled = True

    def run(self) -> None:
        # Give the provider a way to report a pause. Attached here rather than
        # at construction so the panel that builds the provider needn't know
        # about signals — and emitting from this thread is safe, Qt queues it.
        self._provider.on_wait = self.waiting.emit
        total = len(self._jobs)
        for index, job in enumerate(self._jobs):
            if self._cancelled:
                break
            result = self._run_job(job)
            # Checked again after the work: a cancel that landed during the
            # request must not deliver its result, and must not let the queue
            # fall through to `finished` reporting a run that was stopped.
            if self._cancelled:
                break
            self.result_ready.emit(result)
            self.progress.emit(index + 1, total)
        if self._cancelled:
            self.cancelled.emit()

    def _run_job(self, job: LookupJob) -> LookupResult:
        result = LookupResult(path=job.path, query=job.query)
        try:
            candidates = (
                [job.candidate] if job.candidate else self._provider.search(job.query)
            )
            result.candidates = candidates
            if not candidates:
                result.error = ERROR_NOT_FOUND
                return result
            chosen = candidates[0]
            result.chosen = chosen
            result.proposed = self._provider.fetch(chosen, job.query)
            if job.want_artwork and result.proposed.artwork_url:
                result.artwork = self._fetch_artwork(result.proposed.artwork_url)
        except LookupFailed as exc:
            logger.info("Lookup failed for %s: %s", job.path, exc.kind)
            result.error = exc.kind
            result.proposed = None
        except Exception as exc:  # a provider bug must not take the thread down
            logger.exception("Unexpected lookup failure for %s: %s", job.path, exc)
            result.error = "network"
            result.proposed = None
        return result

    def _fetch_artwork(self, url: str) -> bytes:
        """Cover bytes, or nothing.

        Art failing is not the lookup failing: the tag values are the point,
        and a dialog with a missing preview is far better than a file reported
        as un-lookupable because an image server had a moment.
        """
        try:
            return self._provider.fetch_artwork(url)
        except Exception:
            logger.debug("Artwork unavailable: %s", url)
            return b""
