"""Background worker for audio file analysis."""

from dataclasses import dataclass

from PySide6.QtCore import QObject, QThread, Signal

from src.analysis.result import AnalysisResult


@dataclass
class AnalysisProgress:
    """Progress update from analysis worker."""

    completed: int
    total: int
    current_file: str
    result: AnalysisResult | None = None


class AnalysisWorker(QObject):
    """Worker that runs audio analysis in a background thread."""

    # Signals
    started = Signal()
    progress = Signal(AnalysisProgress)
    finished = Signal(list)  # List of AnalysisResult
    error = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        file_paths: list[str],
        min_bpm: float = 85.0,
        max_bpm: float = 175.0,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._file_paths = file_paths
        self._min_bpm = min_bpm
        self._max_bpm = max_bpm
        self._cancelled = False
        self._results: list[AnalysisResult] = []

    def cancel(self) -> None:
        """Request cancellation of the analysis."""
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation was requested."""
        return self._cancelled

    def run(self) -> None:
        """Run the analysis on all files."""
        from src.analysis.analyzer import analyze_file

        self.started.emit()
        self._results = []

        total = len(self._file_paths)
        for i, file_path in enumerate(self._file_paths):
            if self._cancelled:
                self.cancelled.emit()
                return

            # Emit progress before analysis
            self.progress.emit(
                AnalysisProgress(
                    completed=i,
                    total=total,
                    current_file=file_path,
                    result=None,
                )
            )

            try:
                result = analyze_file(
                    file_path,
                    min_bpm=self._min_bpm,
                    max_bpm=self._max_bpm,
                )
                self._results.append(result)

                # Emit progress with result
                self.progress.emit(
                    AnalysisProgress(
                        completed=i + 1,
                        total=total,
                        current_file=file_path,
                        result=result,
                    )
                )
            except Exception as e:
                # Create error result
                error_result = AnalysisResult(
                    file_path=file_path,
                    bpm=0.0,
                    bpm_confidence=0.0,
                    key="",
                    key_confidence=0.0,
                    keycode="",
                    error=str(e),
                )
                self._results.append(error_result)

                self.progress.emit(
                    AnalysisProgress(
                        completed=i + 1,
                        total=total,
                        current_file=file_path,
                        result=error_result,
                    )
                )

        self.finished.emit(self._results)


class AnalysisThread(QThread):
    """Thread that manages the analysis worker."""

    # Forward signals from worker
    analysis_started = Signal()
    analysis_progress = Signal(AnalysisProgress)
    analysis_finished = Signal(list)
    analysis_error = Signal(str)
    analysis_cancelled = Signal()

    def __init__(
        self,
        file_paths: list[str],
        min_bpm: float = 85.0,
        max_bpm: float = 175.0,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._file_paths = file_paths
        self._min_bpm = min_bpm
        self._max_bpm = max_bpm
        self._worker: AnalysisWorker | None = None

    def run(self) -> None:
        """Run the analysis in this thread."""
        self._worker = AnalysisWorker(
            self._file_paths,
            min_bpm=self._min_bpm,
            max_bpm=self._max_bpm,
        )

        # Connect worker signals
        self._worker.started.connect(self.analysis_started.emit)
        self._worker.progress.connect(self.analysis_progress.emit)
        self._worker.finished.connect(self.analysis_finished.emit)
        self._worker.error.connect(self.analysis_error.emit)
        self._worker.cancelled.connect(self.analysis_cancelled.emit)

        # Run the worker
        self._worker.run()

    def cancel(self) -> None:
        """Request cancellation of the analysis."""
        if self._worker:
            self._worker.cancel()

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation was requested."""
        return self._worker.is_cancelled if self._worker else False
