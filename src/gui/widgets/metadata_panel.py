"""Metadata editor panel — drop a single audio file, view/edit tags inline."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QT_TRANSLATE_NOOP, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent

from src.metadata.tags import (
    TrackMetadata,
    read_metadata,
    write_metadata,
    write_comment,
    delete_metadata_fields,
)
from ..styles.theme import BackgroundOverlay, Theme, panel_header_row
from .artwork_widget import ArtworkWidget, mime_for_path
from .drop_zone import AUDIO_EXTENSIONS

logger = logging.getLogger(__name__)

# Fields displayed in the editor and their display labels.
# Labels are marked for translation extraction here (QT_TRANSLATE_NOOP returns
# the string unchanged); they are translated at display time via self.tr(label).
FIELD_ORDER = [
    ("title", QT_TRANSLATE_NOOP("MetadataPanel", "Title")),
    ("artist", QT_TRANSLATE_NOOP("MetadataPanel", "Artist")),
    ("album", QT_TRANSLATE_NOOP("MetadataPanel", "Album")),
    ("label", QT_TRANSLATE_NOOP("MetadataPanel", "Label")),
    ("genre", QT_TRANSLATE_NOOP("MetadataPanel", "Genre")),
    ("bpm", QT_TRANSLATE_NOOP("MetadataPanel", "BPM")),
    ("key", QT_TRANSLATE_NOOP("MetadataPanel", "Key")),
    ("year", QT_TRANSLATE_NOOP("MetadataPanel", "Year")),
    ("track_number", QT_TRANSLATE_NOOP("MetadataPanel", "Track #")),
    ("comment", QT_TRANSLATE_NOOP("MetadataPanel", "Comment")),
]

FIELD_LABELS = dict(FIELD_ORDER)

# Left margin applied to the form rows. A small indent keeps labels visually
# tucked in slightly while still extending the field column nearly to the artwork.
_FORM_LEFT_MARGIN = 8


def _format_audio_props(path: str) -> str:
    """Return a short 'Sample Rate: 44.1 kHz   Bit Depth: 16-bit' summary."""
    try:
        from mutagen import File
        audio = File(path)
        info = getattr(audio, "info", None) if audio is not None else None
        if info is None:
            return ""
        sample_rate = getattr(info, "sample_rate", None)
        bit_depth = (
            getattr(info, "bits_per_sample", None)
            or getattr(info, "sample_size", None)
        )
        sr_text = f"{sample_rate / 1000:g} kHz" if sample_rate else "—"
        bd_text = f"{int(bit_depth)}-bit" if bit_depth else "—"
        return f"Sample Rate: {sr_text}    Bit Depth: {bd_text}"
    except Exception:
        return ""


class MetadataPanel(QWidget):
    """Panel for viewing and editing audio file metadata tags."""

    files_dropped = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._file_path: str | None = None
        self._field_edits: dict[str, QLineEdit] = {}
        self._saving = False  # guard against re-entrant saves
        self.setAcceptDrops(True)
        self._setup_ui()
        self._bg_overlay = BackgroundOverlay("bg_metadata.png", self)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._bg_overlay.setGeometry(self.rect())

    # ------------------------------------------------------------------ UI

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            Theme.PADDING, Theme.PADDING, Theme.PADDING, Theme.PADDING
        )
        layout.setSpacing(Theme.SPACING)

        # Static title — always visible, yellow like other panels. Description
        # sits on the same line, flowing to the title's right.
        title = QLabel(self.tr("Metadata Editor"))
        title.setObjectName("sectionTitle")
        title.setStyleSheet(f"font-size: 24px; color: {Theme.NEON_YELLOW};")
        desc = QLabel(self.tr("Drop a single audio file to view and edit its metadata tags."))
        desc.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        layout.addLayout(panel_header_row(title, desc))

        # File header row: filename (yellow) | Sample Rate / Bit Depth (secondary)
        file_row = QHBoxLayout()
        file_row.setContentsMargins(0, 0, 0, 0)
        file_row.setSpacing(Theme.PADDING)

        # The filename can be long; let it shrink and clip at the panel edge
        # rather than forcing the window wider than the Metadata minimum. The
        # info label keeps its natural width so the props stay readable.
        self._file_label = QLabel("")
        self._file_label.setStyleSheet(
            f"color: {Theme.NEON_YELLOW}; font-size: 15px; background: transparent;"
        )
        self._file_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        file_row.addWidget(self._file_label, 1)

        self._info_label = QLabel("")
        self._info_label.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: 14px; background: transparent;"
        )
        file_row.addWidget(self._info_label)

        file_row.addStretch()

        self._file_header_widget = QWidget()
        self._file_header_widget.setLayout(file_row)
        # Transparent so the panel's background shows through instead of the dark
        # #1a1a1a fill the global QWidget QSS rule would otherwise paint here.
        self._file_header_widget.setObjectName("fileHeader")
        self._file_header_widget.setStyleSheet("#fileHeader { background: transparent; }")
        self._file_header_widget.setVisible(False)
        layout.addWidget(self._file_header_widget)

        # Body: horizontal split — text fields on left (2/3), artwork on right (1/3)
        body = QHBoxLayout()
        body.setSpacing(Theme.PADDING)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._form_container = QWidget()
        self._form_layout = QFormLayout(self._form_container)
        self._form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        # macOS defaults QFormLayout to FieldsStayAtSizeHint, which leaves
        # QLineEdits at their tiny preferred width. Force them to fill the column.
        self._form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._form_layout.setSpacing(10)
        self._form_layout.setContentsMargins(_FORM_LEFT_MARGIN, 10, 0, 0)
        scroll.setWidget(self._form_container)
        self._scroll_area = scroll
        self._scroll_area.setVisible(False)
        body.addWidget(self._scroll_area, 3)

        self._artwork = ArtworkWidget()
        self._artwork.artwork_changed.connect(self._on_artwork_changed)
        self._artwork.setVisible(False)
        body.addWidget(self._artwork, 1)

        layout.addLayout(body, 1)

        # Single row for Add field combo (under form) + Add Artwork / Remove (under artwork)
        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(_FORM_LEFT_MARGIN, 0, 0, 0)
        controls_row.setSpacing(Theme.SPACING)

        self._add_combo = QComboBox()
        self._add_combo.addItem(self.tr("Add field..."))
        self._add_combo.setMinimumWidth(160)
        controls_row.addWidget(self._add_combo)
        controls_row.addStretch()

        self._add_artwork_btn = QPushButton(self.tr("Add Artwork…"))
        self._add_artwork_btn.clicked.connect(self._on_add_artwork_clicked)
        self._add_artwork_btn.setVisible(False)
        controls_row.addWidget(self._add_artwork_btn)

        self._remove_artwork_btn = QPushButton(self.tr("Remove"))
        self._remove_artwork_btn.clicked.connect(self._on_remove_artwork_clicked)
        self._remove_artwork_btn.setVisible(False)
        self._remove_artwork_btn.setEnabled(False)
        controls_row.addWidget(self._remove_artwork_btn)

        self._controls_row_widget = QWidget()
        self._controls_row_widget.setLayout(controls_row)
        self._controls_row_widget.setVisible(False)
        layout.addWidget(self._controls_row_widget)
        # Backwards-compat alias used by existing show/hide code paths
        self._add_field_widget = self._controls_row_widget

        # Eject button row (full-width)
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(_FORM_LEFT_MARGIN, 0, 0, 0)
        btn_row.addStretch()
        # Reload re-reads the file's tags from disk and rebuilds the form —
        # used to pick up changes written elsewhere (e.g. the Player playlist).
        self._reload_btn = QPushButton(self.tr("Reload"))
        self._reload_btn.setMinimumWidth(120)
        self._reload_btn.clicked.connect(self._on_reload)
        self._reload_btn.setVisible(False)
        btn_row.addWidget(self._reload_btn)
        self._eject_btn = QPushButton(self.tr("Eject"))
        self._eject_btn.setMinimumWidth(120)
        self._eject_btn.clicked.connect(self._clear)
        self._eject_btn.setVisible(False)
        self._eject_btn.setStyleSheet(
            f"background-color: {Theme.NEON_YELLOW}; color: #000000; font-weight: bold;"
        )
        btn_row.addWidget(self._eject_btn)
        layout.addLayout(btn_row)

        # Spacer that keeps content pinned to the top in the empty state;
        # hidden when the body is shown so it doesn't steal space.
        self._bottom_spacer = QSpacerItem(
            0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding
        )
        layout.addSpacerItem(self._bottom_spacer)

    # ---------------------------------------------------------- drop handling

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if Path(url.toLocalFile()).suffix.lower() in AUDIO_EXTENSIONS:
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        pass

    def dropEvent(self, event: QDropEvent) -> None:
        if not event.mimeData().hasUrls():
            return
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
                event.acceptProposedAction()
                self._load_file(str(path.resolve()))
                return

    def _load_file(self, path: str) -> None:
        """Load metadata from *path* and populate the form."""
        self._file_path = path
        self._file_label.setText(Path(path).name)
        self._info_label.setText(_format_audio_props(path))
        self._file_header_widget.setVisible(True)

        try:
            meta = read_metadata(path)
        except Exception as e:
            logger.error("Failed to read metadata: %s", e)
            self._file_label.setText(self.tr("Error: {0}").format(e))
            self._info_label.setText("")
            return

        self._populate_form(meta)
        # Programmatic load — don't fire artwork_changed (would re-save the same bytes).
        self._artwork.set_artwork(meta.artwork, meta.artwork_mime, emit=False)
        self._remove_artwork_btn.setEnabled(meta.artwork is not None)

    # ------------------------------------------------------------- form build

    def _populate_form(self, meta: TrackMetadata) -> None:
        """Build (or rebuild) form rows for all populated fields."""
        # Tear down old rows
        self._disconnect_fields()
        self._field_edits.clear()
        while self._form_layout.rowCount():
            self._form_layout.removeRow(0)

        meta_dict = meta.to_dict()

        # Show rows for fields that have values
        shown_fields: set[str] = set()
        for field_key, label in FIELD_ORDER:
            value = meta_dict.get(field_key)
            if value is not None:
                self._add_field_row(field_key, label, str(value))
                shown_fields.add(field_key)

        # Populate the "Add field" combo with remaining fields
        self._add_combo.blockSignals(True)
        self._add_combo.clear()
        self._add_combo.addItem(self.tr("Add field..."))
        for field_key, label in FIELD_ORDER:
            if field_key not in shown_fields:
                self._add_combo.addItem(self.tr(label), field_key)
        self._add_combo.blockSignals(False)

        # Reconnect combo
        try:
            self._add_combo.currentIndexChanged.disconnect()
        except RuntimeError:
            pass
        self._add_combo.currentIndexChanged.connect(self._on_add_field_selected)

        # Show editor widgets and collapse the bottom spacer
        self._scroll_area.setVisible(True)
        self._add_field_widget.setVisible(True)
        self._reload_btn.setVisible(True)
        self._eject_btn.setVisible(True)
        self._artwork.setVisible(True)
        self._add_artwork_btn.setVisible(True)
        self._remove_artwork_btn.setVisible(True)
        self._bottom_spacer.changeSize(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

    def _add_field_row(self, field_key: str, label: str, value: str = "") -> None:
        edit = QLineEdit(value)
        edit.setObjectName(f"metaField_{field_key}")
        edit.editingFinished.connect(self._on_editing_finished)
        self._field_edits[field_key] = edit
        row_label = QLabel(self.tr(label))
        row_label.setMinimumWidth(80)
        self._form_layout.addRow(row_label, edit)

    def _disconnect_fields(self) -> None:
        for edit in self._field_edits.values():
            try:
                edit.editingFinished.disconnect(self._on_editing_finished)
            except RuntimeError:
                pass

    # --------------------------------------------------------- add-field combo

    def _on_add_field_selected(self, index: int) -> None:
        if index <= 0:
            return
        field_key = self._add_combo.itemData(index)
        if field_key and field_key not in self._field_edits:
            label = FIELD_LABELS.get(field_key, field_key)
            self._add_field_row(field_key, label, "")
            # Remove from combo
            self._add_combo.blockSignals(True)
            self._add_combo.removeItem(index)
            self._add_combo.setCurrentIndex(0)
            self._add_combo.blockSignals(False)
            # Focus the new field
            self._field_edits[field_key].setFocus()

    # ------------------------------------------------------------ auto-save

    def _on_editing_finished(self) -> None:
        """Auto-save when a field loses focus."""
        self._save_metadata()

    # --------------------------------------------------------------- save

    def _save_metadata(self) -> None:
        if self._file_path is None or self._saving:
            return
        self._saving = True
        try:
            self._do_save()
        finally:
            self._saving = False

    def _do_save(self) -> None:
        meta = TrackMetadata()
        fields_to_write: list[str] = []
        fields_to_delete: list[str] = []

        for field_key, edit in self._field_edits.items():
            text = edit.text().strip()
            if not text:
                fields_to_delete.append(field_key)
                continue
            if field_key == "bpm":
                try:
                    meta.bpm = float(text)
                    fields_to_write.append("bpm")
                except ValueError:
                    pass
            elif field_key == "year":
                try:
                    meta.year = int(text)
                    fields_to_write.append("year")
                except ValueError:
                    pass
            elif field_key == "track_number":
                try:
                    meta.track_number = int(text)
                    fields_to_write.append("track_number")
                except ValueError:
                    pass
            elif field_key == "comment":
                meta.comment = text
                fields_to_write.append("comment")
            else:
                setattr(meta, field_key, text)
                fields_to_write.append(field_key)

        if not fields_to_write and not fields_to_delete:
            return

        try:
            # Delete cleared fields from the file
            if fields_to_delete:
                delete_metadata_fields(self._file_path, fields_to_delete)
                logger.info("Deleted tags %s from %s", fields_to_delete, Path(self._file_path).name)

            # write_metadata handles artist/title/album/genre/year/track_number/bpm/key
            standard_fields = [f for f in fields_to_write if f != "comment"]
            if standard_fields:
                write_metadata(self._file_path, meta, standard_fields)

            # Comment needs special handling — write via mutagen directly
            if "comment" in fields_to_write and meta.comment is not None:
                self._write_comment(self._file_path, meta.comment)

            logger.info("Metadata saved for %s", Path(self._file_path).name)
        except Exception as e:
            logger.error("Failed to save metadata: %s", e)

    @staticmethod
    def _write_comment(file_path: str, comment: str) -> None:
        """Write a comment tag to *file_path* (delegates to the shared helper)."""
        write_comment(file_path, comment)

    # --------------------------------------------------------------- reload

    def _on_reload(self) -> None:
        """Re-read tags from disk and rebuild the form.

        Discards any in-progress edit in the focused field (auto-save already
        persisted committed fields). Used to pick up changes written from
        another panel — confirming the "stale until reloaded" model.
        """
        if self._file_path is not None:
            self._load_file(self._file_path)

    # --------------------------------------------------------------- clear

    def _clear(self) -> None:
        """Reset panel to drop state."""
        self._file_path = None
        self._disconnect_fields()
        self._field_edits.clear()
        while self._form_layout.rowCount():
            self._form_layout.removeRow(0)

        self._artwork.clear_artwork(emit=False)
        self._file_header_widget.setVisible(False)
        self._info_label.setText("")
        self._scroll_area.setVisible(False)
        self._add_field_widget.setVisible(False)
        self._reload_btn.setVisible(False)
        self._eject_btn.setVisible(False)
        self._artwork.setVisible(False)
        self._add_artwork_btn.setVisible(False)
        self._remove_artwork_btn.setVisible(False)
        self._remove_artwork_btn.setEnabled(False)
        # Restore the bottom spacer so empty state stays pinned to top
        self._bottom_spacer.changeSize(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        self.layout().invalidate()

    # ----------------------------------------------------------- artwork actions

    def _on_add_artwork_clicked(self) -> None:
        if self._file_path is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Select cover art"),
            "",
            "Images (*.jpg *.jpeg *.png)",
        )
        if not path:
            return
        try:
            data = Path(path).read_bytes()
        except OSError as e:
            logger.error("Could not read image %s: %s", path, e)
            return
        mime = mime_for_path(path)
        self._artwork.set_artwork(data, mime, emit=True)

    def _on_remove_artwork_clicked(self) -> None:
        if self._file_path is None:
            return
        self._artwork.clear_artwork(emit=True)

    def _on_artwork_changed(self, data, mime) -> None:
        """Persist artwork changes triggered by drop, Add Artwork, or Remove."""
        if self._file_path is None or self._saving:
            return
        self._saving = True
        try:
            if data:
                meta = TrackMetadata(artwork=bytes(data), artwork_mime=str(mime) if mime else None)
                write_metadata(self._file_path, meta, fields=["artwork"])
                logger.info("Wrote artwork (%d bytes) to %s", len(data), Path(self._file_path).name)
                self._remove_artwork_btn.setEnabled(True)
            else:
                delete_metadata_fields(self._file_path, ["artwork"])
                logger.info("Removed artwork from %s", Path(self._file_path).name)
                self._remove_artwork_btn.setEnabled(False)
        except Exception as e:
            logger.error("Failed to save artwork: %s", e)
        finally:
            self._saving = False
