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


class ProgressPanel(QFrame):
    """A progress panel with label, progress bar, and cancel button."""

    cancel_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
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

        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        layout.addWidget(self._progress_bar)

        # Current file label
        self._file_label = QLabel("")
        self._file_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 11px;")
        self._file_label.setWordWrap(True)
        layout.addWidget(self._file_label)

    def set_status(self, text: str) -> None:
        """Set the status label text."""
        self._status_label.setText(text)

    def set_progress(self, completed: int, total: int) -> None:
        """Set the progress bar value."""
        if total > 0:
            percentage = int((completed / total) * 100)
            self._progress_bar.setValue(percentage)
            self._progress_bar.setFormat(f"{completed}/{total} ({percentage}%)")
        else:
            self._progress_bar.setValue(0)
            self._progress_bar.setFormat("0/0 (0%)")

    def set_current_file(self, file_path: str) -> None:
        """Set the current file being processed."""
        # Truncate long paths
        max_len = 80
        if len(file_path) > max_len:
            file_path = "..." + file_path[-(max_len - 3) :]
        self._file_label.setText(file_path)

    def reset(self) -> None:
        """Reset the progress panel to initial state."""
        self._status_label.setText(self.tr("Analyzing..."))
        self._status_label.setToolTip("")
        self._progress_bar.setValue(0)
        self._progress_bar.setFormat("0/0 (0%)")
        self._file_label.setText("")

    def start(self, total: int) -> None:
        """Start showing progress for a given total."""
        self.reset()
        self._progress_bar.setMaximum(100)
        self.set_progress(0, total)
        self.show()

    def complete(self, message: str | None = None) -> None:
        """Mark progress as complete."""
        if message is None:
            message = self.tr("Complete")
        self._status_label.setText(message)
        self._status_label.setToolTip("")
        self._status_label.setStyleSheet(f"color: {Theme.NEON_GREEN}; font-weight: bold;")
        self._progress_bar.setValue(100)
        self._file_label.setText("")

    def set_error(self, message: str) -> None:
        """Show an error state. Full message is available on hover (tooltip)."""
        self._status_label.setText(message)
        self._status_label.setToolTip(message)
        self._status_label.setStyleSheet(f"color: {Theme.ERROR}; font-weight: bold;")
