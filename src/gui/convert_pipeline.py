"""State for one Convert -> Analyze -> playlist run.

Qt-free on purpose: every event this needs already arrives at a MainWindow
method, so what is worth isolating is the bookkeeping — which paths are still
awaited, which one just landed, whether the run is over. MainWindow owns one
instance and does all the I/O.

Two spellings of one path travel through a run. The TrackStore keys on
str(Path.resolve()) and an AnalysisResult comes back in that spelling, while
the library keys on normalize_track_path. On macOS the two differ for
anything under /var, so awaiting_analysis maps store spelling -> library
spelling and never assumes they are equal.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PipelineRun:
    """One armed run. Created by arm(), discarded when the run ends."""

    node_id: int
    playlist_name: str
    awaiting_convert: set[str] = field(default_factory=set)
    passthrough: list[str] = field(default_factory=list)
    awaiting_analysis: dict[str, str] = field(default_factory=dict)
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
        to_convert: list[str],
        passthrough: list[str],
    ) -> None:
        """Start a run targeting `node_id`.

        `to_convert` are sources handed to the converter; `passthrough` are
        rows that need no conversion and go straight to analysis.
        """
        self.run = PipelineRun(
            node_id=node_id,
            playlist_name=playlist_name,
            awaiting_convert=set(to_convert),
            passthrough=list(passthrough),
        )

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

    def conversion_cancelled(self) -> None:
        """A cancelled conversion ends the run: nothing is forwarded."""
        self.run = None

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
        """True when a run exists and nothing is awaited on either side."""
        run = self.run
        if run is None:
            return False
        return not run.awaiting_convert and not run.passthrough and not run.awaiting_analysis

    def summary(self) -> tuple[int, int, int]:
        """(added, skipped duplicates, errors) for the run."""
        run = self.run
        if run is None:
            return (0, 0, 0)
        return (len(run.added), run.skipped_dupes, len(run.errors))

    def end(self) -> None:
        self.run = None
