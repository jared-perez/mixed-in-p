"""Cancellation semantics for the analysis pipeline.

The bug these cover: AnalysisWorker checked its cancel flag only at the *top*
of the per-file loop, so the last file of a batch — and therefore the only file
of a single-file batch — could never be cancelled. The flag was set while
analyze_file was blocked inside librosa, the loop then ended normally, and the
run reported ``finished`` with a full set of results. The user saw a Cancel
button that did nothing and an analysis that completed anyway.

The worker is driven synchronously here rather than on a QThread: its signals
are connected from the calling thread, so running it in-thread keeps those
connections direct. Emitting across threads would queue them behind an event
loop that a non-GUI test does not run, and every assertion would see no signals
at all rather than the wrong ones.
"""

import pytest

import src.analysis.analyzer as analyzer_mod
from src.analysis.cancellation import AnalysisCancelled, check_cancelled
from src.analysis.result import AnalysisResult
from src.gui.workers.analysis_worker import AnalysisWorker


def _result(path: str) -> AnalysisResult:
    return AnalysisResult(
        file_path=path, bpm=128.0, bpm_confidence=0.9,
        key="Am", key_confidence=0.8, keycode="8A",
    )


class FakeAnalyze:
    """analyze_file stand-in that can request cancellation mid-file.

    ``cancel_during`` names the files during whose analysis the user is taken
    to have pressed Cancel; the predicate is then polled exactly as the real
    stage boundaries inside analyze_file poll it.
    """

    def __init__(self, worker: AnalysisWorker, cancel_during: set[str]) -> None:
        self._worker = worker
        self._cancel_during = cancel_during
        self.calls: list[str] = []

    def __call__(self, file_path, min_bpm=85.0, max_bpm=175.0, should_cancel=None):
        self.calls.append(file_path)
        if file_path in self._cancel_during:
            self._worker.cancel()
        check_cancelled(should_cancel)
        return _result(file_path)


def _collect(worker: AnalysisWorker) -> list[tuple]:
    """Record the worker's terminal signal and the results it delivered."""
    events: list[tuple] = []
    worker.finished.connect(
        lambda r: events.append(("finished", tuple(x.file_path for x in r)))
    )
    worker.cancelled.connect(lambda: events.append(("cancelled", ())))
    return events


def _drive(paths: list[str], cancel_during: set[str], monkeypatch):
    worker = AnalysisWorker(paths)
    fake = FakeAnalyze(worker, cancel_during)
    monkeypatch.setattr(analyzer_mod, "analyze_file", fake)
    events = _collect(worker)
    worker.run()
    return events, fake


def test_single_file_cancel_is_honoured(monkeypatch):
    """The reported bug: one file, cancelled mid-analysis, must not 'complete'.

    Before the fix this emitted finished with one result — the flag was set but
    never looked at again after the loop's opening check.
    """
    events, fake = _drive(["/only.wav"], {"/only.wav"}, monkeypatch)

    assert events == [("cancelled", ())]
    assert fake.calls == ["/only.wav"]


def test_cancel_during_last_file_of_a_batch(monkeypatch):
    """Same defect, generalised: it was never about the count but the *last*
    file. A two-file batch cancelled during file 2 also reported complete."""
    events, fake = _drive(["/a.wav", "/b.wav"], {"/b.wav"}, monkeypatch)

    assert events == [("cancelled", ())]
    assert fake.calls == ["/a.wav", "/b.wav"]


def test_cancel_stops_before_the_next_file(monkeypatch):
    """A cancelled batch must not keep chewing through its queue."""
    events, fake = _drive(["/a.wav", "/b.wav", "/c.wav"], {"/a.wav"}, monkeypatch)

    assert events == [("cancelled", ())]
    assert fake.calls == ["/a.wav"], "started a file after cancelling"


def test_uncancelled_batch_still_finishes(monkeypatch):
    """Guard against the fix swallowing ordinary completions."""
    events, fake = _drive(["/a.wav", "/b.wav"], set(), monkeypatch)

    assert events == [("finished", ("/a.wav", "/b.wav"))]


def test_cancelled_file_contributes_no_result(monkeypatch):
    """A file abandoned partway through has nothing worth keeping.

    Files that finished before the cancel keep their results; the in-flight one
    must not appear as an analysed track.
    """
    worker = AnalysisWorker(["/a.wav", "/b.wav"])
    fake = FakeAnalyze(worker, {"/b.wav"})
    monkeypatch.setattr(analyzer_mod, "analyze_file", fake)

    delivered: list[str] = []
    worker.progress.connect(
        lambda p: delivered.append(p.result.file_path) if p.result else None
    )
    worker.run()

    assert delivered == ["/a.wav"]


def test_cancellation_is_not_reported_as_an_error(monkeypatch):
    """analyze_file's broad ``except Exception`` must re-raise AnalysisCancelled.

    Swallowing it would turn a cancelled run into an error *result*, i.e. the
    user presses Cancel and the file is reported broken.
    """
    def boom(*a, **kw):
        raise AnalysisCancelled()

    monkeypatch.setattr(analyzer_mod, "detect_bpm", boom)
    with pytest.raises(AnalysisCancelled):
        analyzer_mod.analyze_file("/x.wav", should_cancel=lambda: False)


def test_worker_reports_cancelled_not_error(monkeypatch):
    """The same guarantee at the worker level: AnalysisCancelled escaping
    analyze_file becomes the cancelled signal, never an error result."""
    worker = AnalysisWorker(["/x.wav"])
    monkeypatch.setattr(
        analyzer_mod, "analyze_file",
        lambda *a, **kw: (_ for _ in ()).throw(AnalysisCancelled()),
    )
    events = _collect(worker)
    errored: list[str] = []
    worker.progress.connect(
        lambda p: errored.append(p.result.error) if p.result and p.result.error else None
    )
    worker.run()

    assert events == [("cancelled", ())]
    assert errored == []


def test_check_cancelled_predicate():
    """The predicate is only consulted when supplied."""
    check_cancelled(None)  # no predicate: never cancels
    check_cancelled(lambda: False)
    with pytest.raises(AnalysisCancelled):
        check_cancelled(lambda: True)


def test_analyze_file_skips_key_stage_when_cancelled_early(monkeypatch):
    """The checkpoint in front of the key stage is the one that pays.

    The key stage is ~97% of a warm file's analysis (nearly all of it a single
    uninterruptible HPSS call), so a cancel landing before it must skip that
    work rather than run it and throw the result away.
    """
    called: list[str] = []

    monkeypatch.setattr(
        analyzer_mod, "detect_bpm",
        lambda *a, **kw: (called.append("bpm"), (128.0, 0.9))[1],
    )
    monkeypatch.setattr(
        analyzer_mod, "detect_key_with_alternatives",
        lambda *a, **kw: (called.append("key"), ("Am", 0.8, []))[1],
    )

    with pytest.raises(AnalysisCancelled):
        analyzer_mod.analyze_file("/x.wav", should_cancel=lambda: "bpm" in called)

    assert called == ["bpm"], "key stage ran despite an earlier cancel"
