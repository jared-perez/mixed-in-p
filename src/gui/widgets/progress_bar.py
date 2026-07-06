"""Progress bar widget with cancel button."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..styles.theme import Theme
from .vis_activity_waveform import VisActivityWaveform


class ProgressPanel(QFrame):
    """A progress panel with label, progress bar, and cancel button."""

    cancel_clicked = Signal()

    def __init__(self, show_activity: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Opt-in per host panel: Analyze/Convert show a moving waveform in place
        # of the progress bar as richer "something is happening" feedback (always
        # on, independent of the visualizations setting); Rename keeps the plain
        # bar. The waveform colour still follows the waveform-colour setting.
        self._show_activity = show_activity
        self._setup_ui()
        self.hide()  # Hidden by default

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Theme.PADDING, Theme.PADDING, Theme.PADDING, Theme.PADDING)
        layout.setSpacing(Theme.SPACING)

        # Top row: label and cancel button
        top_row = QHBoxLayout()

        self._status_label = QLabel(self.tr("Analyzing..."))
        self._status_label.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-weight: bold;")
        top_row.addWidget(self._status_label)

        top_row.addStretch()

        self._cancel_btn = QPushButton(self.tr("Cancel"))
        self._cancel_btn.setObjectName("dangerButton")
        self._cancel_btn.clicked.connect(self.cancel_clicked.emit)
        self._cancel_btn.setMinimumWidth(80)
        top_row.addWidget(self._cancel_btn)

        layout.addLayout(top_row)

        # Animated activity waveform (moving progress feedback), above the bar.
        self._activity = VisActivityWaveform()
        self._activity.hide()
        layout.addWidget(self._activity)

        # Progress bar. When the waveform is the progress indicator it's hidden
        # for good — the filling waveform replaces it.
        self._progress_bar = QProgressBar()
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        if self._show_activity:
            self._progress_bar.hide()
        layout.addWidget(self._progress_bar)

        # Detail line below the bar/waveform: shows the current file during a
        # run, and error text after one (so an error appears after the top
        # info line rather than replacing it).
        self._file_label = QLabel("")
        self._file_label.setWordWrap(True)
        self._reset_file_label_style()
        layout.addWidget(self._file_label)

    def _reset_file_label_style(self) -> None:
        """Style the detail line as a muted current-file caption."""
        self._file_label.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: 11px;"
        )
        self._file_label.setToolTip("")

    def set_status(self, text: str) -> None:
        """Set the status label text."""
        self._status_label.setText(text)

    def set_progress(self, completed: int, total: int) -> None:
        """Set the progress bar value."""
        if total > 0:
            percentage = int((completed / total) * 100)
            self._progress_bar.setValue(percentage)
            self._progress_bar.setFormat(f"{completed}/{total} ({percentage}%)")
            self._activity.set_fraction(completed / total)
        else:
            self._progress_bar.setValue(0)
            self._progress_bar.setFormat("0/0 (0%)")
            self._activity.set_fraction(0.0)

    def set_current_file(self, file_path: str) -> None:
        """Set the current file being processed."""
        # Truncate long paths
        max_len = 80
        if len(file_path) > max_len:
            file_path = "..." + file_path[-(max_len - 3) :]
        self._reset_file_label_style()
        self._file_label.setText(file_path)

    def reset(self) -> None:
        """Reset the progress panel to initial state."""
        self._status_label.setText(self.tr("Analyzing..."))
        self._status_label.setToolTip("")
        self._status_label.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-weight: bold;")
        self._progress_bar.setValue(0)
        self._progress_bar.setFormat("0/0 (0%)")
        self._reset_file_label_style()
        self._file_label.setText("")

    def start(self, total: int) -> None:
        """Start showing progress for a given total."""
        self.reset()
        self._progress_bar.setMaximum(100)
        self.set_progress(0, total)
        if self._show_activity:
            self._activity.show()
            self._activity.start()
        self.show()

    def complete(self, message: str | None = None) -> None:
        """Mark progress as complete."""
        if message is None:
            message = self.tr("Complete")
        self._status_label.setText(message)
        self._status_label.setToolTip("")
        self._status_label.setStyleSheet(f"color: {Theme.NEON_GREEN}; font-weight: bold;")
        self._progress_bar.setValue(100)
        self._reset_file_label_style()
        self._file_label.setText("")
        # Freeze the wave fully lit rather than yanking it away mid-look.
        self._activity.set_fraction(1.0)
        self._activity.stop()
        self._activity.update()

    def set_error(self, message: str) -> None:
        """Show an error state. Full message is available on hover (tooltip).

        With the waveform as the indicator there is no progress bar, so the error
        is shown on the detail line *below* the waveform — after the top info line
        ("Complete: …") rather than replacing it. With the plain bar (Rename) it
        falls back to the top status label, as before.
        """
        self._activity.stop()
        if self._show_activity:
            self._file_label.setStyleSheet(f"color: {Theme.ERROR}; font-weight: bold;")
            self._file_label.setToolTip(message)
            self._file_label.setText(message)
            return
        self._status_label.setText(message)
        self._status_label.setToolTip(message)
        self._status_label.setStyleSheet(f"color: {Theme.ERROR}; font-weight: bold;")

    def set_activity_color(self, color: str) -> None:
        """Set the activity waveform color (#RRGGBB)."""
        self._activity.set_color(color)
