"""Rename panel for batch file renaming with preview."""

from pathlib import Path

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSpinBox,
    QStyledItemDelegate,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.analysis.result import AnalysisResult
from src.renamer import (
    AddPrefix,
    AddSuffix,
    RenameOperation,
    RenamePreview,
    Replace,
    TrimEnd,
    TrimStart,
    has_changes,
    has_conflicts,
    preview_rename,
)

from ..models import TrackState, TrackStore
from ..styles.theme import BackgroundOverlay, Theme, panel_header_row
from .droppable_table import DroppableTableWidget


class _SelectableTextDelegate(QStyledItemDelegate):
    """Cell delegate that opens a read-only, text-selectable editor.

    Double-clicking a preview cell pops a frameless QLineEdit pre-selecting the
    cell text, so the user can copy the whole name or drag to grab just part of
    it (e.g. to paste into the Prepend/Append box). The editor is read-only and
    ``setModelData`` is a no-op, so the preview text can never be edited — the
    cell only becomes selectable, not writable.
    """

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setReadOnly(True)
        editor.setFrame(False)
        editor.setStyleSheet(
            f"QLineEdit {{ background: {Theme.BG_MEDIUM}; color: {Theme.TEXT_PRIMARY};"
            f" selection-background-color: {Theme.NEON_YELLOW};"
            " selection-color: #000000; padding: 0px; }"
        )
        return editor

    def setEditorData(self, editor, index):
        super().setEditorData(editor, index)
        # Pre-select everything so a bare double-click + Ctrl+C copies the whole
        # name; the user can still click to place a cursor and drag a sub-range.
        editor.selectAll()

    def setModelData(self, editor, model, index):
        # Read-only: never write the (possibly re-selected) text back to the cell.
        pass


class RenamePanel(QWidget):
    """Panel for configuring and applying batch renames."""

    # Vertical item padding applied to the preview table (see the
    # #renamePreviewTable rule in app.qss.template). The green "Changed" tag is
    # a cell widget, which the table insets by this many px top and bottom, so
    # the tag is sized to (row height - 2*this) to fill the row and stay
    # centered. Keep this equal to the QSS value.
    _STATUS_ITEM_PAD_V = 2

    apply_rename = Signal(list, list)  # (previews, operations)
    undo_last = Signal()
    files_dropped = Signal(list)             # str paths → _add_files
    analyze_and_rename = Signal(list, list)  # (track_ids, operations) → full pipeline
    send_to_convert = Signal(list)           # list of file path strings

    def __init__(
        self,
        store: TrackStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._previews: list[RenamePreview] = []
        self._operations: list[RenameOperation] = []
        # Paths successfully renamed in the most recent batch — these get
        # auto-removed when the user adds new files to the panel.
        self._renamed_paths: set[str] = set()
        # Snapshot of QUEUED paths after the last refresh, used to detect
        # newly-added files when a store batch update completes.
        self._last_queued_paths: set[str] = set()
        self._setup_ui()
        self._connect_signals()
        self._bg_overlay = BackgroundOverlay("bg_rename.png", self)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._bg_overlay.setGeometry(self.rect())

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Theme.PADDING, Theme.PADDING, Theme.PADDING, Theme.PADDING)
        layout.setSpacing(Theme.SPACING)

        # Title + description on one line (description flows to the title's right)
        title = QLabel(self.tr("Rename"))
        title.setObjectName("sectionTitle")
        title.setStyleSheet(f"font-size: 24px; color: {Theme.NEON_YELLOW};")
        desc = QLabel(self.tr("Trim characters from beginning and end of ALL filenames below. Add text to the start (Prepend) or end (Append) of ALL the filenames."))
        desc.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        layout.addLayout(panel_header_row(title, desc))

        # Operations section
        ops_group = QGroupBox(self.tr("Operations"))
        ops_layout = QVBoxLayout(ops_group)

        # Trim controls row
        trim_row = QHBoxLayout()

        # Trim start
        trim_row.addWidget(QLabel(self.tr("Trim Start:")))
        self._trim_start_spin = QSpinBox()
        self._trim_start_spin.setRange(0, 100)
        self._trim_start_spin.setValue(0)
        self._trim_start_spin.setSuffix(self.tr(" chars"))
        self._trim_start_spin.setToolTip(self.tr("Remove characters from the beginning of the filename"))
        self._trim_start_spin.setMaximumWidth(120)
        trim_row.addWidget(self._trim_start_spin)

        trim_row.addSpacing(20)

        # Trim end
        trim_row.addWidget(QLabel(self.tr("Trim End:")))
        self._trim_end_spin = QSpinBox()
        self._trim_end_spin.setRange(0, 100)
        self._trim_end_spin.setValue(0)
        self._trim_end_spin.setSuffix(self.tr(" chars"))
        self._trim_end_spin.setToolTip(self.tr("Remove characters from the end of the filename (before extension)"))
        self._trim_end_spin.setMaximumWidth(120)
        trim_row.addWidget(self._trim_end_spin)

        trim_row.addSpacing(20)
        self._clear_ops_btn = QPushButton(self.tr("Clear"))
        # Size to the translated label (with a floor) so it never clips in
        # longer-text languages, matching the Prepend/Append pair below.
        self._clear_ops_btn.setMinimumWidth(
            max(70, self._clear_ops_btn.sizeHint().width())
        )
        trim_row.addWidget(self._clear_ops_btn)

        trim_row.addStretch()
        self._remove_underscores = False
        self._remove_underscores_btn = QPushButton(self.tr("Remove Underscores"))
        self._remove_underscores_btn.setCheckable(True)
        self._remove_underscores_btn.setMinimumWidth(
            self._remove_underscores_btn.sizeHint().width()
        )
        trim_row.addWidget(self._remove_underscores_btn)
        # Host the trim controls in a widget so the window sizer can read their
        # pushed-together width and keep the Rename window from getting narrower
        # than what shows Trim Start/Trim End/Clear/Remove Underscores legibly.
        self._trim_row_widget = QWidget()
        self._trim_row_widget.setLayout(trim_row)
        ops_layout.addWidget(self._trim_row_widget)

        # Prepend/Append text row
        prepend_row = QHBoxLayout()

        # Mode toggle: Prepend (default) vs Append. Only one active at a time.
        self._append_mode = False
        self._prepend_btn = QPushButton(self.tr("Prepend Text"))
        self._prepend_btn.setCheckable(True)
        self._prepend_btn.setChecked(True)
        self._append_btn = QPushButton(self.tr("Append Text"))
        self._append_btn.setCheckable(True)
        # Size the pair to the wider of the two translated labels (with a floor)
        # so they stay equal width and never clip in longer-text languages.
        _btn_w = max(140,
                     self._prepend_btn.sizeHint().width(),
                     self._append_btn.sizeHint().width())
        self._prepend_btn.setMinimumWidth(_btn_w)
        self._append_btn.setMinimumWidth(_btn_w)
        prepend_row.addWidget(self._prepend_btn)
        prepend_row.addWidget(self._append_btn)

        self._prepend_edit = QLineEdit()
        self._prepend_edit.setMaxLength(200)
        # Widen the input ~20% past its default hint (the trailing stretch
        # otherwise pins it to the default sizeHint width).
        self._prepend_edit.setMinimumWidth(int(self._prepend_edit.sizeHint().width() * 1.2))
        prepend_row.addWidget(self._prepend_edit)
        prepend_row.addStretch()
        ops_layout.addLayout(prepend_row)

        self._update_add_mode_buttons()

        layout.addWidget(ops_group)

        # Preview table
        preview_group = QGroupBox(self.tr("Preview"))
        preview_layout = QVBoxLayout(preview_group)

        self._preview_table = DroppableTableWidget(self.tr("Drop audio files here to add them"), bottom_quarter=True)
        # Named so app.qss can trim its vertical item padding (lets the green
        # "Changed" tag fill the compact row without growing it).
        self._preview_table.setObjectName("renamePreviewTable")
        self._preview_table.setColumnCount(3)
        self._preview_table.setHorizontalHeaderLabels([self.tr("Original"), self.tr("Preview"), self.tr("Status")])
        self._preview_table.setAlternatingRowColors(True)
        self._preview_table.setSelectionBehavior(DroppableTableWidget.SelectionBehavior.SelectRows)
        self._preview_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        # Accept external file drops AND let the user drag selected rows onto a
        # sidebar nav button to route them (mirrors Send To). The mixin's self-drag
        # guard keeps a drag dropped back on this table from re-adding the files.
        self._preview_table.enable_drag_out("rename", self._drag_data)
        self._preview_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._preview_table.verticalHeader().setVisible(False)

        # Let the user select/copy text inside the Original and Preview cells.
        # Because drag-out is enabled (setDragEnabled), the built-in DoubleClicked
        # edit trigger never fires — the drag machinery swallows the gesture. So
        # we keep triggers off and open the read-only editor ourselves from the
        # doubleClicked signal (see _on_cell_double_clicked). Single-click still
        # selects the row and press-drag still drags rows out to the sidebar.
        self._preview_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._select_delegate = _SelectableTextDelegate(self._preview_table)
        self._preview_table.setItemDelegateForColumn(0, self._select_delegate)
        self._preview_table.setItemDelegateForColumn(1, self._select_delegate)
        # With drag-out on, neither the DoubleClicked trigger nor the
        # doubleClicked signal fires (the view's drag handling eats the second
        # click), so we intercept the raw double-click on the viewport — which
        # arrives before that machinery — and open the editor ourselves.
        self._preview_table.viewport().installEventFilter(self)

        # Fixed column widths so the table contents don't reflow as the window
        # is resized; a horizontal scrollbar appears when the columns overflow.
        header = self._preview_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._preview_table.setColumnWidth(0, 360)  # Original
        self._preview_table.setColumnWidth(1, 360)  # Preview
        self._preview_table.setColumnWidth(2, 120)  # Status

        preview_layout.addWidget(self._preview_table)
        layout.addWidget(preview_group, 1)

        # Bottom row with stats and buttons
        bottom_row = QHBoxLayout()

        self._stats_label = QLabel(self.tr("No files to rename"))
        self._stats_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        bottom_row.addWidget(self._stats_label)

        bottom_row.addStretch()

        self._undo_btn = QPushButton(self.tr("Undo Last"))
        self._undo_btn.clicked.connect(self.undo_last.emit)
        self._undo_btn.setEnabled(False)
        bottom_row.addWidget(self._undo_btn)

        self._remove_btn = QPushButton(self.tr("Remove All"))
        self._remove_btn.setEnabled(False)
        self._remove_btn.clicked.connect(self._on_remove_all)
        bottom_row.addWidget(self._remove_btn)

        self._apply_btn = QPushButton(self.tr("Apply Rename"))
        self._apply_btn.setObjectName("primaryButton")
        self._apply_btn.setMinimumWidth(160)
        self._apply_btn.clicked.connect(self._on_apply_clicked)
        self._apply_btn.setEnabled(False)
        bottom_row.addWidget(self._apply_btn)

        self._send_to_btn = QPushButton(self.tr("Send To"))
        self._send_to_btn.setEnabled(False)
        send_to_menu = QMenu(self._send_to_btn)
        self._send_to_convert_action = send_to_menu.addAction(self.tr("Convert"))
        self._send_to_analyze_action = send_to_menu.addAction(self.tr("Analyze"))
        self._send_to_btn.setMenu(send_to_menu)
        bottom_row.addWidget(self._send_to_btn)

        layout.addLayout(bottom_row)

    def _connect_signals(self) -> None:
        """Connect internal signals."""
        self._trim_start_spin.valueChanged.connect(self._on_operation_changed)
        self._trim_end_spin.valueChanged.connect(self._on_operation_changed)
        self._prepend_edit.textChanged.connect(self._on_prepend_changed)
        self._prepend_btn.clicked.connect(lambda: self._set_add_mode(append=False))
        self._append_btn.clicked.connect(lambda: self._set_add_mode(append=True))
        self._store.track_updated.connect(self._on_store_changed)
        self._store.track_removed.connect(self._on_store_changed)
        self._store.batch_update_finished.connect(self._on_batch_finished)
        self._store.track_added.connect(self._on_track_added)
        self._preview_table.files_dropped.connect(self.files_dropped.emit)
        self._preview_table.customContextMenuRequested.connect(self._on_context_menu)
        self._send_to_convert_action.triggered.connect(self._on_send_to_convert)
        self._send_to_analyze_action.triggered.connect(self._on_analyze_clicked)
        self._clear_ops_btn.clicked.connect(self._clear_operations)
        self._remove_underscores_btn.clicked.connect(self._on_remove_underscores)
        self._preview_table.itemSelectionChanged.connect(self._on_selection_changed)

        # Delete/Backspace remove selected rows. WidgetShortcut keeps the
        # binding scoped to the table — won't fire when other widgets have focus.
        for key in (QKeySequence.StandardKey.Delete, QKeySequence(Qt.Key.Key_Backspace)):
            sc = QShortcut(key, self._preview_table)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(self._remove_selected)

    def _on_operation_changed(self, value: int) -> None:
        """Handle operation spinbox changes."""
        self._update_preview()

    def _on_prepend_changed(self, text: str) -> None:
        self._update_preview()

    def _set_add_mode(self, append: bool) -> None:
        """Switch between prepend and append modes (mutually exclusive)."""
        self._append_mode = append
        self._update_add_mode_buttons()
        self._update_preview()

    def _update_add_mode_buttons(self) -> None:
        """Reflect the active add mode: active button yellow, other grayed out.

        Also updates the placeholder hint and keeps the checked state in sync
        so a click on the already-active button can't toggle it off.
        """
        self._prepend_btn.setChecked(not self._append_mode)
        self._append_btn.setChecked(self._append_mode)

        active_style = f"background-color: {Theme.NEON_YELLOW}; color: #000000; font-weight: bold;"
        inactive_style = "color: #777777;"
        self._prepend_btn.setStyleSheet(inactive_style if self._append_mode else active_style)
        self._append_btn.setStyleSheet(active_style if self._append_mode else inactive_style)

        if self._append_mode:
            self._prepend_edit.setPlaceholderText(self.tr("Text to add at end of filename"))
        else:
            self._prepend_edit.setPlaceholderText(self.tr("Text to add at start of filename"))

    def _on_store_changed(self, *args) -> None:
        """Handle store changes — refresh preview immediately."""
        self._update_preview()

    def _build_operations(self) -> list[RenameOperation]:
        """Build list of rename operations from current settings."""
        operations: list[RenameOperation] = []

        trim_start = self._trim_start_spin.value()
        if trim_start > 0:
            operations.append(TrimStart(trim_start))

        trim_end = self._trim_end_spin.value()
        if trim_end > 0:
            operations.append(TrimEnd(trim_end))

        add_text = self._prepend_edit.text()
        if add_text:
            if self._append_mode:
                operations.append(AddSuffix(add_text))
            else:
                operations.append(AddPrefix(add_text))

        if self._remove_underscores:
            operations.append(Replace("_", " "))

        return operations

    def _update_preview(self) -> None:
        """Update the preview table with current operations."""
        self._operations = self._build_operations()

        # Show only QUEUED tracks (staging area for files waiting to be analyzed)
        all_tracks = self._store.get_by_state(TrackState.QUEUED)
        if not all_tracks:
            self._preview_table.setRowCount(0)
            self._stats_label.setText(self.tr("No files"))
            self._apply_btn.setEnabled(False)
            self._send_to_btn.setEnabled(False)
            self._last_queued_paths = set()
            return

        # Build file paths and analysis results dict
        file_paths = [t.file_path for t in all_tracks]
        analysis_dict: dict[str, AnalysisResult] = {}
        for track in all_tracks:
            analysis_dict[track.file_path] = AnalysisResult(
                file_path=track.file_path,
                bpm=track.bpm or 0.0,
                bpm_confidence=track.bpm_confidence or 0.0,
                key=track.key or "",
                key_confidence=track.key_confidence or 0.0,
                keycode=track.keycode or "",
            )

        # Generate previews
        self._previews = preview_rename(file_paths, self._operations, analysis_dict)

        # Update table
        self._preview_table.setRowCount(len(self._previews))
        changes_count = 0
        conflicts_count = 0

        for row, preview in enumerate(self._previews):
            # Original name. Left editable so the read-only selection editor
            # (_SelectableTextDelegate) can open on double-click; it never
            # writes changes back, so the preview stays authoritative.
            orig_item = QTableWidgetItem(preview.original_name)
            self._preview_table.setItem(row, 0, orig_item)

            # New name (also selectable/copyable via the same delegate).
            new_item = QTableWidgetItem(preview.new_name)
            if preview.will_conflict:
                new_item.setForeground(Qt.GlobalColor.red)
            elif preview.original_name != preview.new_name:
                new_item.setForeground(Qt.GlobalColor.green)
            self._preview_table.setItem(row, 1, new_item)

            # Status — blank during preview, except conflicts
            if preview.will_conflict:
                status = self.tr("Conflict")
                conflicts_count += 1
            elif preview.original_name != preview.new_name:
                status = ""
                changes_count += 1
            else:
                status = ""
            status_item = QTableWidgetItem(status)
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if preview.will_conflict:
                status_item.setForeground(Qt.GlobalColor.red)
            # Drop any "Changed" badge widget from a previous rename — setItem
            # doesn't replace cell widgets, only the underlying item.
            self._preview_table.removeCellWidget(row, 2)
            self._preview_table.setItem(row, 2, status_item)

        # Update stats
        parts = [self.tr("{0} files").format(len(self._previews))]
        if changes_count > 0:
            parts.append(self.tr("{0} to rename").format(changes_count))
        if conflicts_count > 0:
            parts.append(self.tr("{0} conflicts").format(conflicts_count))

        self._stats_label.setText(" | ".join(parts))

        # Enable apply button only if there are changes and no conflicts
        can_apply = changes_count > 0 and conflicts_count == 0
        self._apply_btn.setEnabled(can_apply)

        # Enable send-to button when there are queued tracks
        queued_count = len(self._store.get_by_state(TrackState.QUEUED))
        self._send_to_btn.setEnabled(queued_count > 0)

        # Snapshot current QUEUED paths for change detection on next batch.
        self._last_queued_paths = {t.file_path for t in all_tracks}

        # Re-apply "Changed" badges (they're cell widgets, so _update_preview
        # has to put them back every refresh — setItem above doesn't carry them).
        self._apply_renamed_badges()

    def _on_analyze_clicked(self) -> None:
        """Handle analyze action — emit signal to start full pipeline.

        User rename ops (trim/prepend) are intentionally NOT sent here; they
        apply only when the user clicks "Apply Rename" explicitly.  The
        post-analysis rename is controlled solely by Settings (BPM/Key format).
        """
        queued = self._store.get_by_state(TrackState.QUEUED)
        track_ids = [t.id for t in queued]
        if track_ids:
            self.analyze_and_rename.emit(track_ids, [])

    def _on_send_to_convert(self) -> None:
        """Send all queued files to the Convert panel."""
        queued = self._store.get_by_state(TrackState.QUEUED)
        file_paths = [t.file_path for t in queued]
        if file_paths:
            self.send_to_convert.emit(file_paths)
            for track in queued:
                self._store.remove(track.id)

    def _on_apply_clicked(self) -> None:
        """Handle apply button click."""
        if self._previews and self._operations:
            self.apply_rename.emit(self._previews, self._operations)

    def set_undo_enabled(self, enabled: bool) -> None:
        """Enable or disable the undo button."""
        self._undo_btn.setEnabled(enabled)

    def _on_remove_underscores(self) -> None:
        """Toggle underscore removal."""
        self._remove_underscores = self._remove_underscores_btn.isChecked()
        if self._remove_underscores:
            self._remove_underscores_btn.setStyleSheet(
                f"background-color: {Theme.NEON_YELLOW}; color: #000000;"
            )
        else:
            self._remove_underscores_btn.setStyleSheet("")
        self._update_preview()

    def _clear_operations(self) -> None:
        """Reset trim and prepend fields to defaults."""
        self._trim_start_spin.setValue(0)
        self._trim_end_spin.setValue(0)
        self._prepend_edit.clear()
        self._append_mode = False
        self._update_add_mode_buttons()
        self._remove_underscores = False
        self._remove_underscores_btn.setChecked(False)
        self._remove_underscores_btn.setStyleSheet("")

    def refresh(self) -> None:
        """Refresh the preview."""
        self._update_preview()

    def mark_renamed(self, session) -> None:
        """Record renamed paths after a rename completes.

        The row highlight and "Changed" pill are (re)applied by
        _apply_renamed_badges on every preview refresh, so they survive the
        operation-clearing cascade that runs right after this call. This is
        the sole completion feedback now that the rename progress bar is gone.
        """
        self._renamed_paths.update(r.new_path for r in session.records)
        self._apply_renamed_badges()

    def _apply_renamed_badges(self) -> None:
        """Highlight freshly-renamed rows and drop a 'Changed' pill in Status.

        Rename is near-instant, so instead of a progress bar the completed
        rows carry a soft green (success) row tint and a rounded pill badge —
        the same green the app uses elsewhere for "done".
        """
        if not self._renamed_paths:
            return
        row_tint = QColor(Theme.NEON_GREEN)
        row_tint.setAlpha(38)  # faint wash so zebra striping still reads through
        for row in range(min(self._preview_table.rowCount(), len(self._previews))):
            preview = self._previews[row]
            if preview.original_path not in self._renamed_paths:
                continue
            for col in range(self._preview_table.columnCount()):
                item = self._preview_table.item(row, col)
                if item is not None:
                    item.setBackground(row_tint)
            # Size the tag to fill the existing (compact) row: the table insets
            # cell widgets by _STATUS_ITEM_PAD_V top+bottom, so tag height is
            # (row height - 2*inset) to fill that region and stay centered. The
            # row height itself is left untouched — no growing rows.
            tag_h = self._preview_table.rowHeight(row) - 2 * self._STATUS_ITEM_PAD_V
            self._preview_table.setCellWidget(row, 2, self._make_changed_pill(tag_h))

    def _make_changed_pill(self, height: int) -> QWidget:
        """Build a rounded, vertically-centered green 'Changed' tag.

        The label is used directly as the cell widget. Its height is FIXED to
        the region the table's reduced item padding leaves after insetting the
        widget (``row height - 2*_STATUS_ITEM_PAD_V``, passed in as ``height``).
        Sizing it to exactly that region makes the green tag fill the compact
        row and sit centered (an oversized tag overflows downward and reads as
        "too low"; an undersized one floats). Only horizontal padding is used,
        so the text can't be vertically clipped; the small item inset is what
        shows the green row tint around the tag.
        """
        tag = QLabel(self.tr("Changed"))
        tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tag.setFixedHeight(max(20, height))
        tag.setStyleSheet(
            "QLabel {"
            f" background-color: {Theme.NEON_GREEN};"
            " color: #000000;"
            " font-weight: 700;"
            " font-size: 13px;"
            " border-radius: 6px;"
            " padding: 0px 12px;"
            "}"
        )
        return tag

    def _on_selection_changed(self) -> None:
        """Enable/disable Remove All based on whether files exist."""
        self._remove_btn.setEnabled(self._preview_table.rowCount() > 0)

    def _on_remove_all(self) -> None:
        """Remove all files from the rename panel."""
        queued_tracks = self._store.get_by_state(TrackState.QUEUED)
        if not queued_tracks:
            return

        self._renamed_paths.clear()
        for track in queued_tracks:
            self._store.remove(track.id)

    def _on_track_added(self, track_id: str) -> None:
        """Auto-clear previously-renamed files when a single new track arrives.

        Handles non-batched adds. Batched adds (drag-drop, Add Files button)
        suppress per-track signals; those go through _on_batch_finished instead.
        """
        if not self._renamed_paths:
            return
        track = self._store.get(track_id)
        if track is None or track.state != TrackState.QUEUED:
            return
        paths_to_remove = self._renamed_paths - {track.file_path}
        self._renamed_paths.clear()
        if not paths_to_remove:
            return
        for t in self._store.get_by_state(TrackState.QUEUED):
            if t.id != track_id and t.file_path in paths_to_remove:
                self._store.remove(t.id)

    def _on_batch_finished(self) -> None:
        """Run after the store finishes a batch update.

        When genuinely new QUEUED files arrive, drop any previously-renamed
        rows (their "Changed" highlight is stale once the user moves on).
        """
        current_paths = {t.file_path for t in self._store.get_by_state(TrackState.QUEUED)}
        new_paths = current_paths - self._last_queued_paths - self._renamed_paths
        if new_paths:
            if self._renamed_paths:
                to_remove = self._renamed_paths - new_paths
                self._renamed_paths.clear()
                for t in list(self._store.get_by_state(TrackState.QUEUED)):
                    if t.file_path in to_remove:
                        self._store.remove(t.id)
        self._update_preview()

    def _on_context_menu(self, pos) -> None:
        """Show a right-click menu (copy original name / remove) over selected rows."""
        rows = self._selected_rows()
        if not rows:
            return
        menu = QMenu(self._preview_table)

        # Copy the Original-column text so it can be pasted into the
        # Prepend/Append box. Plural label when several rows are selected
        # (names are copied one per line).
        copy_label = self.tr("Copy text") if len(rows) == 1 else self.tr("Copy {0} names").format(len(rows))
        copy_action = menu.addAction(copy_label)
        copy_action.triggered.connect(self._copy_selected_original)

        menu.addSeparator()

        label = self.tr("Remove from list") if len(rows) == 1 else self.tr("Remove {0} from list").format(len(rows))
        action = menu.addAction(label)
        action.triggered.connect(self._remove_selected)
        menu.exec(self._preview_table.viewport().mapToGlobal(pos))

    def eventFilter(self, obj, event) -> bool:
        """Open the read-only selection editor on a double-click in a text cell.

        Installed on the preview table's viewport (see _setup_ui): catching the
        double-click here bypasses the drag-out machinery that otherwise
        suppresses editing. Only the Original/Preview columns are selectable.
        """
        if (
            obj is self._preview_table.viewport()
            and event.type() == QEvent.Type.MouseButtonDblClick
            and event.button() == Qt.MouseButton.LeftButton
        ):
            index = self._preview_table.indexAt(event.position().toPoint())
            if index.isValid() and index.column() in (0, 1):
                self._preview_table.edit(index)
                return True
        return super().eventFilter(obj, event)

    def _copy_selected_original(self) -> None:
        """Copy the Original-column names of the selected rows to the clipboard."""
        rows = self._selected_rows()
        names = [
            self._previews[r].original_name
            for r in rows
            if 0 <= r < len(self._previews)
        ]
        if names:
            QGuiApplication.clipboard().setText("\n".join(names))

    def _selected_rows(self) -> list[int]:
        return sorted({idx.row() for idx in self._preview_table.selectedIndexes()})

    def _remove_selected(self) -> None:
        """Remove the tracks behind the currently selected rows."""
        rows = self._selected_rows()
        paths = [self._previews[r].original_path for r in rows if 0 <= r < len(self._previews)]
        self._remove_paths(paths)

    def _remove_paths(self, paths: list[str]) -> None:
        """Remove the tracks for the given original paths from the store."""
        if not paths:
            return
        self._store.begin_batch_update()
        try:
            for path in paths:
                track = self._store.get_by_path(path)
                if track is not None:
                    self._store.remove(track.id)
                self._renamed_paths.discard(path)
        finally:
            self._store.end_batch_update()

    def _drag_data(self):
        """Provide (paths, remove-on-move callback) for an outgoing drag."""
        rows = self._selected_rows()
        paths = [self._previews[r].original_path for r in rows if 0 <= r < len(self._previews)]
        if not paths:
            return None
        return paths, lambda: self._remove_paths(paths)
