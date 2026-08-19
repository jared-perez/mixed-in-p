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
    QMessageBox,
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
from src.online import matching
from src.online.discogs import DiscogsProvider
from src.online.result import (
    ERROR_AUTH,
    ERROR_NETWORK,
    ERROR_NOT_FOUND,
    ERROR_NO_TOKEN,
    ERROR_RATE_LIMIT,
    ERROR_SERVER,
)
from src.utils.reveal import reveal_in_file_manager
from ..styles.theme import BackgroundOverlay, Theme, panel_header_row
from ..workers import thread_keeper
from ..workers.lookup_worker import LookupJob, LookupThread
from .dialogs.lookup_review import ARTWORK_FIELD, LookupReviewDialog
from .elided_label import ElidedLabel
from .artwork_widget import ArtworkWidget, mime_for_path
from .drop_zone import AUDIO_EXTENSIONS

logger = logging.getLogger(__name__)

# Horizontal room a button needs beyond its text: the stylesheet's
# "padding: 8px 16px", its 1px border, and a little slack. The stylesheet is
# invisible to the native size hint, so a translated label would otherwise be
# cut at both ends — a QPushButton centres rather than elides.
# (Plain "#", not "#:" — lupdate harvests the latter as a note to translators.)
_BUTTON_CHROME = 44

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


def _sniff_mime(data: bytes) -> str:
    """The MIME type of downloaded cover bytes, read from the bytes themselves.

    There is no filename to go on — the URL is a signed, time-limited address —
    and writing "image/jpeg" over a PNG produces a file whose art some players
    refuse to draw.
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return "image/jpeg"


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
        # Online lookup state. Off until MainWindow pushes the setting down —
        # while off the button is hidden, not greyed, so the app looks as
        # offline as it is.
        self._online_enabled = False
        self._discogs_token = ""
        self._fetch_artwork = True
        self._lookup_thread: LookupThread | None = None
        self._review_dialog: LookupReviewDialog | None = None
        self._threads: list = []
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
        desc = ElidedLabel(self.tr("Drop a single audio file to view and edit its metadata tags."))
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

        # Second line: where the file actually is. The filename above is not
        # enough to tell two copies of a track apart, and the panel writes to
        # disk — so the path is worth showing, and worth being able to open.
        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.setSpacing(Theme.SPACING)

        # ElidedLabel, not QLabel: a path's length is not ours to control, and
        # a QLabel simply draws past its own edge. It also manages its own
        # tooltip from here on — full text while cut off, none while it fits.
        self._path_label = ElidedLabel("")
        self._path_label.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: 13px; background: transparent;"
        )
        path_row.addWidget(self._path_label, 1)

        self._reveal_btn = QPushButton(self.tr("Open File Location"))
        self._reveal_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reveal_btn.setToolTip(
            self.tr("Show this file in Finder / File Explorer.")
        )
        self._reveal_btn.setMinimumWidth(
            self._reveal_btn.fontMetrics().horizontalAdvance(self._reveal_btn.text())
            + _BUTTON_CHROME
        )
        self._reveal_btn.clicked.connect(self._on_reveal_clicked)
        path_row.addWidget(self._reveal_btn)

        header_col = QVBoxLayout()
        header_col.setContentsMargins(0, 0, 0, 0)
        # Explicit: a widget's own layout falls back to the Qt default (6px),
        # not Theme.SPACING — and these two lines are one block about one file.
        header_col.setSpacing(2)
        header_col.addLayout(file_row)
        header_col.addLayout(path_row)

        self._file_header_widget = QWidget()
        self._file_header_widget.setLayout(header_col)
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

        # Online lookup. Hidden entirely until the setting is on — see
        # _sync_lookup_button.
        self._lookup_btn = QPushButton(self.tr("Look Up Online…"))
        self._lookup_btn.setToolTip(
            self.tr("Search Discogs for this track's details, and review them.")
        )
        self._lookup_btn.setMinimumWidth(
            self._lookup_btn.fontMetrics().horizontalAdvance(self._lookup_btn.text())
            + _BUTTON_CHROME
        )
        self._lookup_btn.clicked.connect(self._on_lookup_clicked)
        self._lookup_btn.setVisible(False)
        btn_row.addWidget(self._lookup_btn)

        # Says what the lookup is doing, including *why* it paused — a rate
        # limit that reads as a stuck spinner is the thing to avoid.
        self._lookup_status = ElidedLabel("")
        self._lookup_status.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        self._lookup_status.setVisible(False)
        btn_row.addWidget(self._lookup_status, 1)

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
        self._path_label.setText(path)
        # Set here rather than left to the label's own resize handling, which
        # only runs on a resize — otherwise a shorter path inherits the
        # previous file's tooltip until the panel happens to change width.
        self._path_label.setToolTip(path)
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
        self._sync_lookup_button()
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

    # --------------------------------------------------------------- reveal

    def _on_reveal_clicked(self) -> None:
        """Show the loaded file in the OS file manager, selected.

        ``reveal_in_file_manager`` selects the file itself; the ``openUrl``
        variant in three other panels only opens the containing folder, which
        leaves the user hunting for it in a directory of a thousand tracks.
        A miss means the file moved since it was loaded — an explanation, not
        an error.
        """
        if not self._file_path:
            return
        if not reveal_in_file_manager(self._file_path):
            QMessageBox.information(
                self,
                self.tr("Open File Location"),
                self.tr(
                    "This file can't be found — it may have been moved, "
                    "renamed, or deleted."
                ),
            )

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
        self._path_label.setText("")
        self._path_label.setToolTip("")
        self._scroll_area.setVisible(False)
        self._add_field_widget.setVisible(False)
        self._reload_btn.setVisible(False)
        self._eject_btn.setVisible(False)
        self._artwork.setVisible(False)
        self._add_artwork_btn.setVisible(False)
        self._remove_artwork_btn.setVisible(False)
        self._remove_artwork_btn.setEnabled(False)
        self._sync_lookup_button()
        # Restore the bottom spacer so empty state stays pinned to top
        self._bottom_spacer.changeSize(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        self.layout().invalidate()

    # ------------------------------------------------------- online lookup

    def set_online_lookup(
        self, enabled: bool, token: str = "", fetch_artwork: bool = True
    ) -> None:
        """Push the Settings state down. Called by MainWindow, not by the user."""
        self._online_enabled = bool(enabled)
        self._discogs_token = (token or "").strip()
        self._fetch_artwork = bool(fetch_artwork)
        self._sync_lookup_button()

    def _sync_lookup_button(self) -> None:
        """The button exists only when the feature is on and a file is loaded."""
        visible = self._online_enabled and self._file_path is not None
        self._lookup_btn.setVisible(visible)
        if not visible:
            self._lookup_status.setVisible(False)
            self._lookup_status.setText("")

    def _current_query(self):
        """What we know about the loaded file, filename fallback included."""
        values = {key: edit.text().strip() for key, edit in self._field_edits.items()}
        duration = None
        try:
            duration = read_metadata(self._file_path).duration
        except Exception:
            pass
        return matching.build_query(
            artist=values.get("artist"),
            title=values.get("title"),
            album=values.get("album"),
            duration=duration,
            filename_stem=Path(self._file_path).stem,
        )

    def _on_lookup_clicked(self) -> None:
        if self._file_path is None or self._lookup_thread is not None:
            return
        query = self._current_query()
        if not query.is_usable():
            QMessageBox.information(
                self,
                self.tr("Look Up Online"),
                self.tr(
                    "This file has no artist or title to search with, and its "
                    "name doesn't give one either. Fill in the Title field and "
                    "try again."
                ),
            )
            return
        self._start_lookup(
            LookupJob(
                path=self._file_path,
                query=query,
                want_artwork=self._fetch_artwork,
            )
        )

    def _start_lookup(self, job: LookupJob) -> None:
        provider = DiscogsProvider(token=self._discogs_token)
        thread = LookupThread(provider, [job], self)
        thread.result_ready.connect(self._on_lookup_result)
        thread.waiting.connect(self._on_lookup_waiting)
        thread.finished.connect(self._on_lookup_finished)
        # Hold the wrapper until its C++ object is actually gone; reassigning
        # the attribute alone can drop the last reference mid-teardown.
        thread_keeper.keep_alive(self._threads, thread)
        self._lookup_thread = thread
        self._lookup_btn.setEnabled(False)
        self._set_lookup_status(self.tr("Looking up…"))
        thread.start()

    def _set_lookup_status(self, text: str) -> None:
        self._lookup_status.setText(text)
        self._lookup_status.setToolTip(text)
        self._lookup_status.setVisible(bool(text))

    def _on_lookup_waiting(self, seconds: float) -> None:
        self._set_lookup_status(self.tr("Waiting for the Discogs rate limit…"))

    def _on_lookup_finished(self) -> None:
        # Clear the slot only if a newer lookup has not already taken it —
        # a superseded thread finishing is the normal case, and an unguarded
        # clear would wipe the live one's reference.
        thread = self.sender()
        if thread is self._lookup_thread:
            self._lookup_thread = None
        self._lookup_btn.setEnabled(True)

    def _on_lookup_result(self, result) -> None:
        if self._file_path is None or result.path != self._file_path:
            # The user ejected or dropped another file while it ran.
            self._set_lookup_status("")
            return
        if not result.ok:
            self._set_lookup_status("")
            QMessageBox.information(
                self, self.tr("Look Up Online"), self._lookup_error_text(result.error)
            )
            return
        self._set_lookup_status("")
        if self._review_dialog is not None:
            # A candidate switch: the dialog is open and waiting for this.
            self._review_dialog.set_result(result)
            return
        self._show_review_dialog(result)

    def _lookup_error_text(self, kind: str) -> str:
        """One sentence per failure kind — no stack traces, no error codes."""
        if kind == ERROR_NO_TOKEN:
            return self.tr(
                "Add your Discogs token in Settings to look up track details."
            )
        if kind == ERROR_AUTH:
            return self.tr(
                "Discogs rejected that token. Check it in Settings, or generate "
                "a new one."
            )
        if kind == ERROR_RATE_LIMIT:
            return self.tr(
                "Discogs is rate limiting this connection. Wait a minute and "
                "try again."
            )
        if kind == ERROR_NOT_FOUND:
            return self.tr(
                "Nothing on Discogs matched this track. Editing the Artist and "
                "Title fields and trying again usually helps."
            )
        if kind == ERROR_SERVER:
            return self.tr("Discogs is having trouble right now. Try again later.")
        if kind == ERROR_NETWORK:
            return self.tr("Couldn't reach Discogs. Check your internet connection.")
        return self.tr("Couldn't read Discogs' answer. Try again later.")

    def _show_review_dialog(self, result) -> None:
        try:
            current = read_metadata(self._file_path)
        except Exception as exc:
            logger.error("Could not re-read tags before review: %s", exc)
            return
        values = dict(current.to_dict())
        values[ARTWORK_FIELD] = current.artwork
        dialog = LookupReviewDialog(
            file_path=self._file_path,
            current=values,
            result=result,
            allow_artwork=self._fetch_artwork,
            parent=self,
        )
        dialog.candidate_requested.connect(self._on_candidate_requested)
        self._review_dialog = dialog
        try:
            accepted = dialog.exec()
        finally:
            self._review_dialog = None
        if accepted:
            self._apply_lookup_values(dialog.selected_values())

    def _on_candidate_requested(self, candidate) -> None:
        """The user picked a different release; read that one instead."""
        if self._file_path is None or self._lookup_thread is not None:
            return
        self._start_lookup(
            LookupJob(
                path=self._file_path,
                query=self._current_query(),
                candidate=candidate,
                want_artwork=self._fetch_artwork,
            )
        )

    def _apply_lookup_values(self, values: dict) -> None:
        """Write the approved fields through the ordinary tag-writing path.

        Deliberately the same ``tags.py`` calls a manual edit makes, so the
        Windows file-lock rules and the WAV guard apply here for free — and the
        form is rebuilt from disk afterwards rather than from what we believe
        we wrote.
        """
        if not values or self._file_path is None:
            return
        artwork = values.pop(ARTWORK_FIELD, None)
        meta = TrackMetadata()
        fields: list[str] = []
        for key, value in values.items():
            setattr(meta, key, value)
            fields.append(key)
        try:
            if fields:
                write_metadata(self._file_path, meta, fields)
            if artwork:
                write_metadata(
                    self._file_path,
                    TrackMetadata(
                        artwork=bytes(artwork), artwork_mime=_sniff_mime(artwork)
                    ),
                    fields=[ARTWORK_FIELD],
                )
            logger.info(
                "Applied %d online field(s) to %s",
                len(fields) + (1 if artwork else 0),
                Path(self._file_path).name,
            )
        except Exception as exc:
            logger.error("Failed to apply looked-up metadata: %s", exc)
            QMessageBox.warning(
                self,
                self.tr("Look Up Online"),
                self.tr("Couldn't write these tags: {0}").format(exc),
            )
            return
        self._load_file(self._file_path)

    def shutdown_workers(self) -> None:
        """Wait for a lookup in flight before the window goes away.

        A urllib request is one long blocking call, so there is nothing to
        interrupt — but a QThread destroyed while running is undefined
        behaviour, and a worker emitting into a deleted panel is worse.
        """
        if self._lookup_thread is not None:
            self._lookup_thread.cancel()
        thread_keeper.wait_for_threads(self._threads)

    def closeEvent(self, event) -> None:
        self.shutdown_workers()
        super().closeEvent(event)

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
