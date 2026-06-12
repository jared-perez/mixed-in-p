"""Drag and drop zone widget for adding audio files."""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from ..styles.theme import Theme

# Supported audio file extensions
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".aiff", ".aif", ".m4a", ".ogg"}


class DropZone(QFrame):
    """A drag-and-drop zone for adding audio files."""

    files_dropped = Signal(list)  # List of file paths

    def __init__(
        self,
        label_text: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self._label_text = (
            label_text if label_text is not None else self.tr("Drag and drop audio files here")
        )
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._label = QLabel(self._label_text)
        self._label.setObjectName("dropZoneLabel")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label)

        self._hint_label = QLabel(self.tr("MP3, WAV, FLAC, AIFF, M4A, OGG"))
        self._hint_label.setStyleSheet(f"color: {Theme.TEXT_DISABLED}; font-size: 11px;")
        self._hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._hint_label)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Handle drag enter - check if files are audio."""
        if event.mimeData().hasUrls():
            # Check if any URL is an audio file or directory
            for url in event.mimeData().urls():
                path = Path(url.toLocalFile())
                if path.is_dir() or path.suffix.lower() in AUDIO_EXTENSIONS:
                    event.acceptProposedAction()
                    self.setObjectName("dropZoneActive")
                    self.style().unpolish(self)
                    self.style().polish(self)
                    return
        event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        """Handle drag leave - reset visual state."""
        self.setObjectName("dropZone")
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent) -> None:
        """Handle drop - collect audio files."""
        self.setObjectName("dropZone")
        self.style().unpolish(self)
        self.style().polish(self)

        if not event.mimeData().hasUrls():
            return

        audio_files: list[str] = []

        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
                audio_files.append(str(path.resolve()))
            elif path.is_dir():
                # Recursively find audio files in directory
                audio_files.extend(self._find_audio_files(path))

        if audio_files:
            event.acceptProposedAction()
            self.files_dropped.emit(audio_files)

    def _find_audio_files(self, directory: Path) -> list[str]:
        """Find all audio files in a directory recursively."""
        audio_files: list[str] = []
        try:
            for path in directory.rglob("*"):
                if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
                    audio_files.append(str(path.resolve()))
        except PermissionError:
            pass
        return sorted(audio_files)

    def set_label_text(self, text: str) -> None:
        """Update the label text."""
        self._label.setText(text)
