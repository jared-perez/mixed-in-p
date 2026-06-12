"""Artwork display widget — shows embedded cover art with image drag-and-drop."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QPixmap,
)
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from ..styles.theme import Theme

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}

_MIME_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


class ArtworkWidget(QFrame):
    """Displays embedded cover art and accepts image-file drops to replace it."""

    artwork_changed = Signal(object, object)  # (bytes | None, str | None)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("artworkWidget")
        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.Shape.NoFrame)

        self._data: bytes | None = None
        self._mime: str | None = None
        self._source_pixmap: QPixmap | None = None

        self._apply_style(active=False)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Theme.PADDING, Theme.PADDING, Theme.PADDING, Theme.PADDING)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setMinimumSize(120, 120)
        self._image_label.setText(
            self.tr("No artwork\n\nDrop an image here\nor click “Add Artwork…”")
        )
        self._image_label.setStyleSheet(
            f"color: {Theme.TEXT_DISABLED}; font-size: 12px;"
        )
        layout.addWidget(self._image_label, 1)

    def _apply_style(self, active: bool) -> None:
        if active:
            self.setStyleSheet(
                f"#artworkWidget {{"
                f"  background-color: transparent;"
                f"  border: 2px solid {Theme.NEON_YELLOW};"
                f"  border-radius: {Theme.BORDER_RADIUS}px;"
                f"}}"
            )
        else:
            self.setStyleSheet(
                "#artworkWidget {"
                "  background-color: transparent;"
                "  border: none;"
                "}"
            )

    # --------------------------------------------------------------- public API

    def set_artwork(self, data: bytes | None, mime: str | None, *, emit: bool = True) -> None:
        """Set the displayed artwork. Pass (None, None) to clear."""
        self._data = data
        self._mime = mime
        if data:
            pix = QPixmap()
            if pix.loadFromData(data):
                self._source_pixmap = pix
                self._render_pixmap()
            else:
                self._source_pixmap = None
                self._show_placeholder()
        else:
            self._source_pixmap = None
            self._show_placeholder()
        if emit:
            self.artwork_changed.emit(data, mime)

    def clear_artwork(self, *, emit: bool = True) -> None:
        self.set_artwork(None, None, emit=emit)

    def current(self) -> tuple[bytes | None, str | None]:
        return self._data, self._mime

    def has_artwork(self) -> bool:
        return self._data is not None

    # ------------------------------------------------------------------ rendering

    def _show_placeholder(self) -> None:
        self._image_label.setPixmap(QPixmap())
        self._image_label.setText(
            self.tr("No artwork\n\nDrop an image here\nor click “Add Artwork…”")
        )

    def _render_pixmap(self) -> None:
        if self._source_pixmap is None or self._source_pixmap.isNull():
            self._show_placeholder()
            return
        target = self._image_label.size()
        if target.width() < 1 or target.height() < 1:
            return
        scaled = self._source_pixmap.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image_label.setText("")
        self._image_label.setPixmap(scaled)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._source_pixmap is not None:
            self._render_pixmap()

    # --------------------------------------------------------------- drop handling

    def _has_droppable_image(self, event) -> bool:
        if not event.mimeData().hasUrls():
            return False
        for url in event.mimeData().urls():
            if Path(url.toLocalFile()).suffix.lower() in IMAGE_EXTENSIONS:
                return True
        return False

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._has_droppable_image(event):
            event.acceptProposedAction()
            self._apply_style(active=True)
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        if self._has_droppable_image(event):
            event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._apply_style(active=False)

    def dropEvent(self, event: QDropEvent) -> None:
        self._apply_style(active=False)
        if not event.mimeData().hasUrls():
            return
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            suffix = path.suffix.lower()
            if path.is_file() and suffix in IMAGE_EXTENSIONS:
                try:
                    data = path.read_bytes()
                except OSError:
                    return
                mime = _MIME_BY_SUFFIX.get(suffix, "image/jpeg")
                event.acceptProposedAction()
                self.set_artwork(data, mime, emit=True)
                return


def mime_for_path(path: str | Path) -> str:
    """Infer image mime type from file suffix."""
    return _MIME_BY_SUFFIX.get(Path(path).suffix.lower(), "image/jpeg")
