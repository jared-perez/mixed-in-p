"""Background worker for batch audio conversion."""

import logging
from dataclasses import dataclass

from PySide6.QtCore import QObject, QThread, Signal

from src.conversion.result import ConversionResult

logger = logging.getLogger(__name__)


@dataclass
class ConversionProgress:
    """Progress update from conversion worker."""

    completed: int
    total: int
    current_file: str
    result: ConversionResult | None = None


class ConversionWorker(QObject):
    """Worker that converts files in a background thread."""

    started = Signal()
    progress = Signal(ConversionProgress)
    finished = Signal(list)  # list[ConversionResult]
    error = Signal(str)

    def __init__(
        self,
        file_paths: list[str],
        target_format: str,
        bitrate: int = 320,
        sample_rate: int | None = None,
        bit_depth: int | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._file_paths = file_paths
        self._target_format = target_format
        self._bitrate = bitrate
        self._sample_rate = sample_rate
        self._bit_depth = bit_depth
        self._cancelled = False

    def cancel(self) -> None:
        """Request cancellation."""
        self._cancelled = True

    def run(self) -> None:
        """Execute the conversion operations."""
        from src.conversion.converter import convert_file

        self.started.emit()

        total = len(self._file_paths)
        if total == 0:
            self.error.emit("No files to convert")
            return

        logger.info(f"Starting conversion: {total} files -> {self._target_format}")
        results: list[ConversionResult] = []

        for i, file_path in enumerate(self._file_paths):
            if self._cancelled:
                logger.info("Conversion cancelled")
                break

            result = convert_file(
                file_path,
                self._target_format,
                bitrate=self._bitrate,
                sample_rate=self._sample_rate,
                bit_depth=self._bit_depth,
            )
            results.append(result)

            self.progress.emit(
                ConversionProgress(
                    completed=i + 1,
                    total=total,
                    current_file=result.output_path or file_path,
                    result=result,
                )
            )

        self.finished.emit(results)


class ConversionThread(QThread):
    """Thread that manages the conversion worker."""

    conversion_started = Signal()
    conversion_progress = Signal(ConversionProgress)
    conversion_finished = Signal(list)
    conversion_error = Signal(str)

    def __init__(
        self,
        file_paths: list[str],
        target_format: str,
        bitrate: int = 320,
        sample_rate: int | None = None,
        bit_depth: int | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._file_paths = file_paths
        self._target_format = target_format
        self._bitrate = bitrate
        self._sample_rate = sample_rate
        self._bit_depth = bit_depth
        self._worker: ConversionWorker | None = None

    def cancel(self) -> None:
        """Cancel the conversion."""
        if self._worker is not None:
            self._worker.cancel()

    def run(self) -> None:
        """Run the conversion in this thread."""
        self._worker = ConversionWorker(
            self._file_paths,
            self._target_format,
            self._bitrate,
            sample_rate=self._sample_rate,
            bit_depth=self._bit_depth,
        )

        self._worker.started.connect(self.conversion_started.emit)
        self._worker.progress.connect(self.conversion_progress.emit)
        self._worker.finished.connect(self.conversion_finished.emit)
        self._worker.error.connect(self.conversion_error.emit)

        self._worker.run()
