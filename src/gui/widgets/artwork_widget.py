"""Artwork display widget — shows embedded cover art with image drag-and-drop."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import (
    QFontMetrics,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QMenu,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..styles.theme import Theme
from .artwork_lightbox import ArtworkLightbox

# The gap between the cover and the edge of its column. Deliberately small:
# this column *is* the cover, and every pixel of margin here is a pixel the
# tabs beside it do not get.
_ART_MARGIN = 4

# Tall enough that a wrapped hint never runs out of room to be measured in.
_UNBOUNDED = 10_000

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
        # The width the panel gave us, kept rather than read back off the
        # laid-out widget. See set_column_width.
        self._column_width = 0
        # At most one enlargement at a time. Cleared from the box's own
        # `destroyed`, never by comparing against it: WA_DeleteOnClose means
        # the Python wrapper outlives the C++ object, and asking a dead one
        # whether it is the current one is the `already deleted` crash.
        self._lightbox: ArtworkLightbox | None = None

        self._apply_style(active=False)
        self._setup_ui()
        # Split from execution so a test can ask what the cover offers without
        # showing a menu: QMenu.exec cannot be monkeypatched out (PySide6
        # resolves it through C++), so a handler that builds and runs in one
        # call hangs the whole suite with no output.
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        # A hair of breathing room, not a frame. The cover sits in a column
        # whose whole width is the cover — Theme.PADDING on each side spent
        # ~30px of the panel on nothing, in the one place the Discogs tab
        # next door most wants the room.
        layout.setContentsMargins(_ART_MARGIN, _ART_MARGIN, _ART_MARGIN, _ART_MARGIN)

        # Held rather than re-tr()'d at each use: this column's height is
        # measured from it, and a string that differed between the measurement
        # and the label would size the box for text nobody sees.
        self._placeholder = self.tr(
            "No artwork\n\nDrop an image here\nor click “Add Artwork…”"
        )
        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setMinimumSize(120, 120)
        # The placeholder is four translated lines in a column narrower than
        # three of them: fr wants 220px and ja 240px against ~140 available,
        # and a QLabel does not elide — it draws past its own edge and the
        # sentence is simply cut. Wrapping is what lets the column be sized
        # for the cover rather than for the longest translation of a hint.
        self._image_label.setWordWrap(True)
        # Ignored, so the *pixmap* cannot dictate the column width. A QLabel
        # holding a pixmap reports that pixmap as its size hint, and the
        # pixmap is scaled from the label's own width — a size derived from a
        # width that is then read back off it. It settled at 132px inside a
        # 225px column and never grew, which is where the margin everyone
        # could see came from.
        self._image_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self._image_label.setText(self._placeholder)
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

    # ------------------------------------------------------- looking at it

    def build_context_menu(self) -> tuple[QMenu, dict]:
        """The cover's own menu, and its actions by name.

        Remove used to be a button in the row under the panel. It is a rare,
        destructive action on one thing, which is what a context menu is for —
        and giving it back its slot in the row is what leaves Add Artwork room
        to be a full label in every language.
        """
        menu = QMenu(self)
        actions = {"remove": menu.addAction(self.tr("Remove Artwork"))}
        actions["remove"].setEnabled(self.has_artwork())
        return menu, actions

    def _on_context_menu(self, pos) -> None:
        menu, actions = self.build_context_menu()
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is not None and chosen is actions["remove"]:
            self.clear_artwork(emit=True)

    def open_lightbox(self) -> ArtworkLightbox | None:
        """Show the cover at size over the window, if there is one.

        Parented to the *window*, not to this widget, which is what makes
        "click anywhere to close" true: an overlay the size of a 150px column
        could only be dismissed by clicking the very thing it covers.
        """
        if self._source_pixmap is None or self._source_pixmap.isNull():
            return None
        window = self.window()
        if window is None:
            return None
        if self._lightbox is not None:
            return self._lightbox
        box = ArtworkLightbox(self._source_pixmap, window)
        box.destroyed.connect(self._forget_lightbox)
        self._lightbox = box
        box.show_over_parent()
        return box

    def _forget_lightbox(self) -> None:
        self._lightbox = None

    def mouseReleaseEvent(self, event) -> None:
        # On release, not press: a press that leaves the widget is a drag or a
        # miss, and neither is a request to look at the cover.
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.open_lightbox()
        super().mouseReleaseEvent(event)

    def current(self) -> tuple[bytes | None, str | None]:
        return self._data, self._mime

    def has_artwork(self) -> bool:
        return self._data is not None

    # ------------------------------------------------------------------ rendering

    def _show_placeholder(self) -> None:
        self._image_label.setPixmap(QPixmap())
        self._image_label.setText(self._placeholder)
        # Nothing to enlarge and nothing to remove: an affordance over an
        # empty box is an offer the widget cannot honour.
        self.setToolTip("")
        self.unsetCursor()

    def _inner_side(self) -> int:
        """The square the cover is drawn into, in the column's own terms."""
        margins = self.layout().contentsMargins()
        side = self._column_width or self.width()
        return side - margins.left() - margins.right()

    def _render_pixmap(self) -> None:
        """Scale the cover to the width the panel *gave* this column.

        Never to the laid-out size. A QLabel holding a pixmap reports that
        pixmap as its size hint, so scaling to the label — or to this widget,
        whose height the label's hint decides — feeds the calculation its own
        output: it settled at 120px inside a 150px column and could not grow,
        the same shape as the playlist's artwork-row bug. ``_column_width`` is
        an input, so there is no loop to converge.
        """
        if self._source_pixmap is None or self._source_pixmap.isNull():
            self._show_placeholder()
            return
        target_w = target_h = self._inner_side()
        if target_w < 1 or target_h < 1:
            return
        scaled = self._source_pixmap.scaled(
            target_w,
            target_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image_label.setText("")
        self._image_label.setPixmap(scaled)
        self.setToolTip(self.tr("Click to enlarge. Right-click for more."))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_column_width(self, width: int) -> None:
        """Fix this column's size, squared off at the width the panel chose.

        Both dimensions are *given*, never read back. A size hint would not
        survive the trip: word wrap on the empty-state label makes this widget
        report ``hasHeightForWidth``, and a parent layout then asks
        ``heightForWidth`` and ignores ``sizeHint().height()`` entirely —
        which is why the box sat at the label's 120px minimum with a 142px
        cover drawn into it while every hint in the chain said 150.

        The height is that square, floored by what the empty-state hint needs
        once wrapped: it is four translated lines, and fr and ja each take two
        lines for the last one. Measured with the font rather than asked of
        the label, because the label holds a *cover* whenever there is one and
        would answer for the picture instead of the sentence.
        """
        self._column_width = int(width)
        margins = self.layout().contentsMargins()
        inner = max(1, self._inner_side())
        wrapped = QFontMetrics(self._image_label.font()).boundingRect(
            QRect(0, 0, inner, _UNBOUNDED),
            int(Qt.TextFlag.TextWordWrap) | int(Qt.AlignmentFlag.AlignCenter),
            self._placeholder,
        )
        self.setFixedSize(
            self._column_width,
            max(inner, wrapped.height()) + margins.top() + margins.bottom(),
        )
        self._render_pixmap()

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
