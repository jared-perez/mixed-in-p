"""State for one rename -> convert -> analyze -> playlist run.

Qt-free on purpose: every event this needs already arrives at a MainWindow
method, so what is worth isolating is the bookkeeping — which paths are still
awaited, which one just landed, whether the run is over. MainWindow owns one
instance and does all the I/O.

The step order is fixed; the toggles only choose which of the three steps a
run performs. A run is armed with the steps it will do, starts at whichever
panel the user pressed, and always ends by filing the files into a playlist —
so with Analyze off the tracks are added directly, un-analysed, which is what
awaiting_add is for.

Two spellings of one path travel through a run. The TrackStore keys on
str(Path.resolve()) and an AnalysisResult comes back in that spelling, while
the library keys on normalize_track_path. On macOS the two differ for
anything under /var, so awaiting_analysis maps store spelling -> library
spelling and never assumes they are equal. The direct-add path never meets the
store, so it carries library spellings only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

STEP_RENAME = "rename"
STEP_CONVERT = "convert"
STEP_ANALYZE = "analyze"

# The one order steps ever run in. Toggles pick members, never the sequence.
STEP_ORDER = (STEP_RENAME, STEP_CONVERT, STEP_ANALYZE)


@dataclass
class PipelineRun:
    """One armed run. Created by arm(), discarded when the run ends."""

    node_id: int
    playlist_name: str
    # The steps this run performs, start step included. A snapshot: flipping a
    # toggle mid-run must not re-route the batch already in flight.
    steps: frozenset[str] = field(default_factory=frozenset)
    # A list, not a set, because the rename step's own results only name the
    # rows that moved — the order of everything else has to come from here.
    awaiting_rename: list[str] = field(default_factory=list)
    awaiting_convert: set[str] = field(default_factory=set)
    passthrough: list[str] = field(default_factory=list)
    awaiting_analysis: dict[str, str] = field(default_factory=dict)
    awaiting_add: set[str] = field(default_factory=set)
    added: list[str] = field(default_factory=list)
    skipped_dupes: int = 0
    errors: list[str] = field(default_factory=list)


class ConvertPipeline:
    """The pipeline's memory of a run in flight."""

    def __init__(self) -> None:
        self.run: PipelineRun | None = None

    @property
    def active(self) -> bool:
        return self.run is not None

    def arm(
        self,
        node_id: int,
        playlist_name: str,
        to_convert: list[str] | None = None,
        passthrough: list[str] | None = None,
        steps: frozenset[str] | set[str] | None = None,
        to_rename: list[str] | None = None,
    ) -> None:
        """Start a run targeting `node_id`.

        `to_convert` are sources handed to the converter; `passthrough` are
        rows that need no conversion and go straight to the next step.
        `to_rename` are the files handed to the rename worker — held so a run
        that has only started renaming does not read as finished.
        `steps` is which of rename/convert/analyze this run performs; it
        defaults to convert+analyze, which is what every caller predating the
        step toggles meant.
        """
        self.run = PipelineRun(
            node_id=node_id,
            playlist_name=playlist_name,
            steps=frozenset(steps if steps is not None else {STEP_CONVERT, STEP_ANALYZE}),
            awaiting_rename=list(dict.fromkeys(to_rename or [])),
            awaiting_convert=set(to_convert or []),
            passthrough=list(passthrough or []),
        )

    def has_step(self, step: str) -> bool:
        """True when the armed run performs `step`."""
        return bool(self.run and step in self.run.steps)

    def next_step(self, after: str | None = None) -> str | None:
        """The step this run runs next, or None for "straight to the playlist".

        `after` is the step just finished (None to ask for the first one).
        This is the whole of "flow through the later enabled steps only".
        """
        run = self.run
        if run is None:
            return None
        start = 0 if after is None else STEP_ORDER.index(after) + 1
        for step in STEP_ORDER[start:]:
            if step in run.steps:
                return step
        return None

    def rename_done(self, renamed: dict[str, str]) -> list[str]:
        """Retire the rename step; return the paths to carry onward.

        `renamed` maps original path -> new path, and names only the rows that
        actually moved: a row the rename left alone (or failed on) is absent
        and travels under its own name, because that is where the file still
        is. The result is one path per armed file, in the order they were
        armed, so the next panel receives the queue in the order the user saw
        it. Draining twice yields nothing, the way take_passthrough does.
        """
        run = self.run
        if run is None:
            return []
        paths = [renamed.get(path, path) for path in run.awaiting_rename]
        run.awaiting_rename = []
        return paths

    def conversion_done(self, results) -> list[str]:
        """Record a finished conversion batch; return the paths to analyse.

        Only a result with neither error nor skipped has a usable output_path
        (it is "" on every other return in converter.py), so an errored or
        skipped source is counted and dropped rather than followed by an
        empty path. Results for files this run never armed are ignored.
        """
        run = self.run
        if run is None:
            return []

        outputs: list[str] = []
        for result in results:
            if result.source_path not in run.awaiting_convert:
                continue
            run.awaiting_convert.discard(result.source_path)
            if result.error or result.skipped or not result.output_path:
                run.errors.append(result.source_path)
                continue
            outputs.append(result.output_path)

        # Anything armed but absent from the results never came back.
        for missing in run.awaiting_convert:
            run.errors.append(missing)
        run.awaiting_convert.clear()

        return self.take_passthrough() + outputs

    def take_passthrough(self) -> list[str]:
        """Return and clear the forwarded-as-is sources.

        A run with nothing to convert never goes near the ConversionThread
        (a zero-file worker emits error and no finished), so its caller drains
        the passthrough here instead of through conversion_done.
        """
        run = self.run
        if run is None:
            return []
        paths = run.passthrough
        run.passthrough = []
        return paths

    def abort(self) -> None:
        """Drop the run mid-flight: nothing further is forwarded or filed."""
        self.run = None

    def conversion_cancelled(self) -> None:
        """A cancelled conversion ends the run: nothing is forwarded."""
        self.abort()

    def await_analysis(self, pairs: dict[str, str]) -> None:
        """Register files handed to Analyze: store spelling -> library spelling."""
        if self.run is not None:
            self.run.awaiting_analysis.update(pairs)

    def analysis_batch_paths(self) -> list[str]:
        """The store spellings still waiting to be analysed."""
        if self.run is None:
            return []
        return list(self.run.awaiting_analysis)

    def track_analysed(self, path: str, error: str | None) -> str | None:
        """Retire one analysed file; return the library path to add, or None.

        None for a path this run is not awaiting (a file the user dropped into
        Analyze alongside the batch must not land in the playlist) and for a
        file that failed to analyse.
        """
        run = self.run
        if run is None:
            return None
        library_path = run.awaiting_analysis.pop(path, None)
        if library_path is None:
            return None
        if error:
            run.errors.append(library_path)
            return None
        return library_path

    def await_direct_add(self, paths: list[str]) -> list[str]:
        """Register files to file into the playlist un-analysed; return them.

        The path Analyze-off runs take. Deliberately *not* a drain-once list
        like passthrough: each add commits asynchronously and retires itself
        through direct_add_done, so the run stays unfinished until the last
        one lands. Paths are library spellings — nothing on this leg meets the
        TrackStore, so there is no second spelling to map. Returns the paths
        actually registered, deduplicated, so the caller adds each file once.
        """
        run = self.run
        if run is None:
            return []
        fresh = [p for p in dict.fromkeys(paths) if p not in run.awaiting_add]
        run.awaiting_add.update(fresh)
        return fresh

    def direct_add_done(self, path: str) -> bool:
        """Retire one directly-added file; False if this run never awaited it.

        False for a second retirement of the same path, exactly as
        track_analysed returns None — the callers record added/skipped
        themselves, so a double retire must not double-count.
        """
        run = self.run
        if run is None:
            return False
        if path not in run.awaiting_add:
            return False
        run.awaiting_add.discard(path)
        return True

    def record_added(self, path: str) -> None:
        if self.run is not None:
            self.run.added.append(path)

    def record_skipped(self, count: int = 1) -> None:
        if self.run is not None:
            self.run.skipped_dupes += count

    def analysis_idle(self) -> bool:
        """True when a batch ended with pipeline files still unanalysed.

        The caller starts a batch for analysis_batch_paths(). _start_analysis
        returns early while a thread is running and leaves its tracks PENDING;
        in auto mode _start_pending_analysis picks them up, in manual mode
        nothing does — this is what does.
        """
        return bool(self.run and self.run.awaiting_analysis)

    def finished(self) -> bool:
        """True when a run exists and no step still owes it a file."""
        run = self.run
        if run is None:
            return False
        return not (
            run.awaiting_rename
            or run.awaiting_convert
            or run.passthrough
            or run.awaiting_analysis
            or run.awaiting_add
        )

    def summary(self) -> tuple[int, int, int]:
        """(added, skipped duplicates, errors) for the run."""
        run = self.run
        if run is None:
            return (0, 0, 0)
        return (len(run.added), run.skipped_dupes, len(run.errors))

    def end(self) -> None:
        self.run = None
