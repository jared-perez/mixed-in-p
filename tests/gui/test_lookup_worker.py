"""The lookup worker: one file at a time, failures as results, cancel discards.

Driven by a stub provider rather than DiscogsProvider — what is under test here
is the thread's contract with the panel, not the HTTP client (which has its own
tests, also with no network).
"""

from __future__ import annotations

import pytest

from src.gui.workers.lookup_worker import LookupJob, LookupResult, LookupThread
from src.online.result import (
    ERROR_NETWORK,
    ERROR_NOT_FOUND,
    Candidate,
    LookupFailed,
    ProposedTags,
    TrackQuery,
)

QUERY = TrackQuery(artist="Underworld", title="Born Slippy")


class StubProvider:
    """Records what it was asked for and answers with whatever it was given."""

    def __init__(self, candidates=None, proposed=None, error=None, artwork=b"IMG"):
        self.candidates = candidates if candidates is not None else [Candidate(
            release_id=1, artist="Underworld", album="Born Slippy", score=0.9
        )]
        self.proposed = proposed or ProposedTags(title="Born Slippy", provider="discogs")
        self.error = error
        self.artwork = artwork
        self.searches: list[TrackQuery] = []
        self.fetches: list[Candidate] = []
        self.artwork_urls: list[str] = []
        self.on_wait = None

    def search(self, query, limit=25):
        if self.error:
            raise self.error
        self.searches.append(query)
        return list(self.candidates)

    def fetch(self, candidate, query):
        self.fetches.append(candidate)
        return self.proposed

    def fetch_artwork(self, url):
        self.artwork_urls.append(url)
        if isinstance(self.artwork, BaseException):
            raise self.artwork
        return self.artwork


def _run(qtbot, provider, jobs) -> list[LookupResult]:
    """Run a queue to completion and return what it emitted."""
    thread = LookupThread(provider, jobs)
    results: list[LookupResult] = []
    thread.result_ready.connect(results.append)
    with qtbot.waitSignal(thread.finished, timeout=5000):
        thread.start()
    return results


def test_a_lookup_searches_then_reads_the_best_release(qtbot):
    provider = StubProvider()
    results = _run(qtbot, provider, [LookupJob(path="/a.mp3", query=QUERY)])
    assert len(results) == 1
    assert results[0].ok
    assert results[0].proposed.title == "Born Slippy"
    assert provider.searches and provider.fetches


def test_a_job_carrying_a_candidate_skips_the_search(qtbot):
    # This is the candidate switcher: the user already chose the release, so
    # searching again would spend a request to learn nothing.
    provider = StubProvider()
    chosen = Candidate(release_id=42, album="Dubnobasswithmyheadman")
    results = _run(
        qtbot, provider, [LookupJob(path="/a.mp3", query=QUERY, candidate=chosen)]
    )
    assert provider.searches == []
    assert provider.fetches == [chosen]
    assert results[0].chosen is chosen


def test_a_search_with_no_results_is_reported_not_dropped(qtbot):
    provider = StubProvider(candidates=[])
    results = _run(qtbot, provider, [LookupJob(path="/a.mp3", query=QUERY)])
    assert len(results) == 1
    assert results[0].error == ERROR_NOT_FOUND
    assert not results[0].ok


def test_a_provider_failure_arrives_as_a_result_with_a_kind(qtbot):
    provider = StubProvider(error=LookupFailed(ERROR_NETWORK, "offline"))
    results = _run(qtbot, provider, [LookupJob(path="/a.mp3", query=QUERY)])
    assert results[0].error == ERROR_NETWORK
    assert results[0].proposed is None


def test_an_unexpected_provider_bug_does_not_take_the_thread_down(qtbot):
    provider = StubProvider(error=ValueError("provider bug"))
    results = _run(qtbot, provider, [LookupJob(path="/a.mp3", query=QUERY)])
    assert len(results) == 1 and results[0].error


def test_artwork_comes_with_the_result_only_when_asked_for(qtbot):
    provider = StubProvider(
        proposed=ProposedTags(title="x", artwork_url="https://img/1.jpg")
    )
    without = _run(qtbot, provider, [LookupJob(path="/a.mp3", query=QUERY)])
    assert without[0].artwork == b"" and provider.artwork_urls == []

    with_art = _run(
        qtbot,
        provider,
        [LookupJob(path="/a.mp3", query=QUERY, want_artwork=True)],
    )
    assert with_art[0].artwork == b"IMG"


def test_a_cover_that_fails_to_download_does_not_fail_the_lookup(qtbot):
    # The tag values are the point; a missing preview is far better than a file
    # reported as un-lookupable because an image server had a moment.
    provider = StubProvider(
        proposed=ProposedTags(title="x", artwork_url="https://img/1.jpg"),
        artwork=OSError("image server down"),
    )
    results = _run(
        qtbot, provider, [LookupJob(path="/a.mp3", query=QUERY, want_artwork=True)]
    )
    assert results[0].ok and results[0].artwork == b""


def test_progress_counts_the_queue(qtbot):
    provider = StubProvider()
    thread = LookupThread(
        provider,
        [LookupJob(path=f"/{i}.mp3", query=QUERY) for i in range(3)],
    )
    seen: list[tuple[int, int]] = []
    thread.progress.connect(lambda done, total: seen.append((done, total)))
    with qtbot.waitSignal(thread.finished, timeout=5000):
        thread.start()
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_a_cancel_stops_the_queue_and_reports_it(qtbot):
    # Cancelled before it starts: nothing is emitted, and the run says it was
    # cancelled rather than falling through to a silent finish.
    provider = StubProvider()
    thread = LookupThread(
        provider, [LookupJob(path=f"/{i}.mp3", query=QUERY) for i in range(3)]
    )
    results: list[LookupResult] = []
    cancelled: list[bool] = []
    thread.result_ready.connect(results.append)
    thread.cancelled.connect(lambda: cancelled.append(True))
    thread.cancel()
    with qtbot.waitSignal(thread.finished, timeout=5000):
        thread.start()
    assert results == []
    assert cancelled == [True]


def test_a_cancel_during_the_request_discards_that_files_result(qtbot):
    # A cancel flag checked only *between* items can never cancel the last one
    # — which includes the only one, i.e. every single-file lookup this panel
    # runs. The in-flight result is discarded, not delivered late.
    class SlowProvider(StubProvider):
        def __init__(self, thread_box):
            super().__init__()
            self._box = thread_box

        def search(self, query, limit=25):
            self._box[0].cancel()  # the user hits Cancel mid-request
            return super().search(query, limit)

    box: list[LookupThread] = [None]
    provider = SlowProvider(box)
    thread = LookupThread(provider, [LookupJob(path="/a.mp3", query=QUERY)])
    box[0] = thread
    results: list[LookupResult] = []
    cancelled: list[bool] = []
    thread.result_ready.connect(results.append)
    thread.cancelled.connect(lambda: cancelled.append(True))
    with qtbot.waitSignal(thread.finished, timeout=5000):
        thread.start()
    assert results == []
    assert cancelled == [True]


def test_the_provider_reports_a_pause_through_the_threads_signal(qtbot):
    # The rate-limit pause has to reach the UI, or it reads as a stuck spinner.
    provider = StubProvider()
    thread = LookupThread(provider, [LookupJob(path="/a.mp3", query=QUERY)])
    seen: list[float] = []
    thread.waiting.connect(seen.append)
    with qtbot.waitSignal(thread.finished, timeout=5000):
        thread.start()
    assert provider.on_wait is not None
    provider.on_wait(5.0)
    qtbot.wait(10)
    assert seen == [5.0]
