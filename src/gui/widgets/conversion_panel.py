"""Conversion panel for batch lossless audio format conversion."""

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.conversion.result import LOSSLESS_EXTENSIONS, LOSSY_EXTENSIONS, ConversionResult
from src.utils.config import load_config, save_config

from ..models import TrackStore
from ..styles.theme import BackgroundOverlay, Theme, panel_header_row
from .droppable_table import DroppableTableWidget
from .progress_bar import ProgressPanel


class ConversionPanel(QWidget):
    """Panel for converting audio files between lossless formats."""

    start_conversion = Signal(list, str, int, int, int)  # (file_paths, target_format, bitrate, sample_rate, bit_depth)
    send_to_analyze = Signal(list)  # list of file path strings
    send_to_rename = Signal(list)  # list of file path strings
    send_to_player = Signal(list)  # list of track dicts for player

    def __init__(
        self,
        store: TrackStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._file_paths: list[str] = []  # local file list, independent of TrackStore
        self._converted_outputs: dict[str, str] = {}  # source path -> converted output path
        self._converting: set[str] = set()  # source paths currently mid-conversion
        self._file_info_cache: dict[str, str] = {}
        self._config = load_config()
        self._loading_settings = True
        self._setup_ui()
        self._loading_settings = False
        self._connect_signals()
        self._bg_overlay = BackgroundOverlay("bg_convert.png", self)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._bg_overlay.setGeometry(self.rect())
        self._position_lossy_notice()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Theme.PADDING, Theme.PADDING, Theme.PADDING, Theme.PADDING)
        layout.setSpacing(Theme.SPACING)

        # Title + description on one line (description flows to the title's right)
        title = QLabel(self.tr("Convert"))
        title.setObjectName("sectionTitle")
        title.setStyleSheet(f"font-size: 24px; color: {Theme.NEON_YELLOW};")
        desc = QLabel(self.tr("Convert audio files between formats (WAV, FLAC, AIFF, MP3)."))
        desc.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        layout.addLayout(panel_header_row(title, desc))

        # Target format selector
        format_row = QHBoxLayout()
        format_row.addWidget(QLabel(self.tr("Target Format:")))
        self._format_combo = QComboBox()
        self._format_combo.addItems(["AIFF", "WAV", "FLAC", "MP3"])
        self._format_combo.setCurrentText(self._config.convert_target_format)
        format_row.addWidget(self._format_combo)

        # Sample rate selector (visible for lossless targets)
        self._samplerate_label = QLabel(self.tr("Sample Rate:"))
        self._samplerate_combo = QComboBox()
        for label, hz in [
            (self.tr("96 kHz (DVD)"), 96000),
            (self.tr("48 kHz (DAT)"), 48000),
            (self.tr("44.1 kHz (CD)"), 44100),
            (self.tr("32 kHz"), 32000),
        ]:
            self._samplerate_combo.addItem(label, hz)
        idx = self._samplerate_combo.findData(self._config.convert_sample_rate)
        if idx >= 0:
            self._samplerate_combo.setCurrentIndex(idx)
        format_row.addWidget(self._samplerate_label)
        format_row.addWidget(self._samplerate_combo)

        # Bit depth selector (visible for lossless targets)
        self._bitdepth_label = QLabel(self.tr("Bit Depth:"))
        self._bitdepth_combo = QComboBox()
        for label, bits in [
            (self.tr("32 bit"), 32),
            (self.tr("24 bit (DVD)"), 24),
            (self.tr("16 bit (CD)"), 16),
            (self.tr("8 bit"), 8),
        ]:
            self._bitdepth_combo.addItem(label, bits)
        idx = self._bitdepth_combo.findData(self._config.convert_bit_depth)
        if idx >= 0:
            self._bitdepth_combo.setCurrentIndex(idx)
        format_row.addWidget(self._bitdepth_label)
        format_row.addWidget(self._bitdepth_combo)

        # Bitrate selector (visible only for MP3)
        self._bitrate_label = QLabel(self.tr("Bitrate:"))
        self._bitrate_combo = QComboBox()
        self._bitrate_combo.addItems(["128", "192", "256", "320"])
        self._bitrate_combo.setCurrentText(str(self._config.convert_mp3_bitrate))
        format_row.addWidget(self._bitrate_label)
        format_row.addWidget(self._bitrate_combo)

        format_row.addStretch()
        # Host the format controls in a widget so the window sizer can read their
        # pushed-together width and keep the Convert window from getting narrower
        # than what fits the Target Format / Sample Rate / Bit Depth selectors.
        self._format_row_widget = QWidget()
        self._format_row_widget.setLayout(format_row)
        layout.addWidget(self._format_row_widget)

        # Progress panel (initially hidden)
        self._progress_panel = ProgressPanel(show_activity=True)
        layout.addWidget(self._progress_panel)

        # File table
        table_group = QGroupBox(self.tr("Files"))
        table_layout = QVBoxLayout(table_group)

        self._file_table = DroppableTableWidget(self.tr("Drop audio files here to add them"), bottom_quarter=True)
        self._file_table.setColumnCount(4)
        self._file_table.setHorizontalHeaderLabels([
            self.tr("Filename"),
            self.tr("From"),
            self.tr("To"),
            self.tr("Status"),
        ])
        self._file_table.setAlternatingRowColors(True)
        self._file_table.setSelectionBehavior(DroppableTableWidget.SelectionBehavior.SelectRows)
        self._file_table.setSelectionMode(DroppableTableWidget.SelectionMode.ExtendedSelection)
        self._file_table.verticalHeader().setVisible(False)
        self._file_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._file_table.customContextMenuRequested.connect(self._on_context_menu)

        # Fixed/interactive column widths so the contents don't reflow as the
        # window resizes; a horizontal scrollbar appears when they overflow.
        header = self._file_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._file_table.setColumnWidth(0, 380)  # Filename
        self._file_table.setColumnWidth(2, 70)   # To
        self._file_table.setColumnWidth(3, 120)  # Status

        table_layout.addWidget(self._file_table)
        layout.addWidget(table_group, 1)

        # Bottom row: stats + buttons
        bottom_row = QHBoxLayout()

        self._stats_label = QLabel(self.tr("No files"))
        self._stats_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        bottom_row.addWidget(self._stats_label)

        bottom_row.addStretch()

        self._convert_btn = QPushButton(self.tr("Convert"))
        self._convert_btn.setObjectName("primaryButton")
        self._convert_btn.setMinimumWidth(160)
        self._convert_btn.setEnabled(False)
        self._convert_btn.clicked.connect(self._on_convert_clicked)
        bottom_row.addWidget(self._convert_btn)

        self._send_to_btn = QPushButton(self.tr("Send To"))
        self._send_to_btn.setEnabled(False)
        self._send_to_btn.setToolTip(self.tr("Select at least one file to send."))
        send_to_menu = QMenu(self._send_to_btn)
        self._send_to_analyze_action = send_to_menu.addAction(self.tr("Analyze"))
        self._send_to_rename_action = send_to_menu.addAction(self.tr("Rename"))
        self._send_to_player_action = send_to_menu.addAction(self.tr("Player"))
        self._send_to_btn.setMenu(send_to_menu)
        bottom_row.addWidget(self._send_to_btn)

        layout.addLayout(bottom_row)

        # Transient centered notice shown when a dropped lossy file is rejected.
        # It floats over the panel (not in the layout); auto-hides after 3s or
        # as soon as an allowed file is added.
        self._lossy_notice = QLabel(self.tr("Lossy files not allowed"), self)
        self._lossy_notice.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lossy_notice.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._lossy_notice.setStyleSheet(
            f"color: {Theme.TEXT_PRIMARY}; font-size: 18px; font-weight: bold;"
            " background: transparent;"
        )
        self._lossy_notice.hide()
        self._lossy_notice_timer = QTimer(self)
        self._lossy_notice_timer.setSingleShot(True)
        self._lossy_notice_timer.setInterval(3000)
        self._lossy_notice_timer.timeout.connect(self._hide_lossy_notice)

        # Apply initial visibility based on persisted target format
        self._on_format_changed(self._format_combo.currentText())

    def _connect_signals(self) -> None:
        """Connect internal signals."""
        self._format_combo.currentTextChanged.connect(self._on_format_changed)
        self._format_combo.currentTextChanged.connect(self._save_convert_settings)
        self._samplerate_combo.currentIndexChanged.connect(self._save_convert_settings)
        self._bitdepth_combo.currentIndexChanged.connect(self._save_convert_settings)
        self._bitrate_combo.currentTextChanged.connect(self._save_convert_settings)
        self._file_table.files_dropped.connect(self.add_files)
        self._file_table.itemSelectionChanged.connect(self._on_selection_changed)
        self._send_to_analyze_action.triggered.connect(self._on_send_to_analyze)
        self._send_to_rename_action.triggered.connect(self._on_send_to_rename)
        self._send_to_player_action.triggered.connect(self._on_send_to_player)
        # Drag selected rows onto a sidebar nav button to route them (mirrors Send To).
        self._file_table.enable_drag_out("convert", self._drag_data)

    def _drag_data(self):
        """Provide (effective paths, remove-on-move callback) for an outgoing drag."""
        sources = self._selected_source_paths()
        if not sources:
            return None
        effective = [self._effective_path(s) for s in sources]
        return effective, lambda: self._remove_sources(sources)

    _SUBTYPE_BITS = {
        "PCM_S8": 8,
        "PCM_U8": 8,
        "PCM_16": 16,
        "PCM_24": 24,
        "PCM_32": 32,
        "FLOAT": 32,
        "DOUBLE": 64,
    }

    def _get_from_label(self, file_path: str, src_ext: str) -> str:
        """Build a 'From' label like 'FLAC 44.1k/16' for the given file."""
        cached = self._file_info_cache.get(file_path)
        if cached is not None:
            return cached
        ext_label = src_ext.upper().lstrip(".")
        try:
            import soundfile as sf
            info = sf.info(file_path)
            sr_khz = info.samplerate / 1000.0
            sr_str = f"{sr_khz:.1f}".rstrip("0").rstrip(".") + "k"
            bits = self._SUBTYPE_BITS.get(info.subtype)
            label = f"{ext_label} {sr_str}/{bits}" if bits else f"{ext_label} {sr_str}"
        except Exception:
            label = ext_label
        self._file_info_cache[file_path] = label
        return label

    def add_files(self, paths: list[str]) -> None:
        """Add files to the conversion list."""
        existing = set(self._file_paths)
        added_allowed = 0
        dropped_lossy = 0
        for p in paths:
            ext = Path(p).suffix.lower()
            if ext in LOSSY_EXTENSIONS:
                dropped_lossy += 1
            if p not in existing:
                self._file_paths.append(p)
                existing.add(p)
                if ext in LOSSLESS_EXTENSIONS:
                    added_allowed += 1
        self._refresh_table()
        # An allowed file landing clears the notice; otherwise a rejected lossy
        # drop raises it (3s auto-hide).
        if added_allowed > 0:
            self._hide_lossy_notice()
        elif dropped_lossy > 0:
            self._show_lossy_notice()

    def _position_lossy_notice(self) -> None:
        """Center the transient notice over the panel."""
        self._lossy_notice.adjustSize()
        x = (self.width() - self._lossy_notice.width()) // 2
        y = (self.height() - self._lossy_notice.height()) // 2
        self._lossy_notice.move(max(0, x), max(0, y))

    def _show_lossy_notice(self) -> None:
        """Show the 'lossy not allowed' notice and (re)start its 3s timeout."""
        self._position_lossy_notice()
        self._lossy_notice.show()
        self._lossy_notice.raise_()  # above the faint background overlay
        self._lossy_notice_timer.start()

    def _hide_lossy_notice(self) -> None:
        self._lossy_notice_timer.stop()
        self._lossy_notice.hide()

    def _on_format_changed(self, text: str) -> None:
        """Handle target format change."""
        is_mp3 = text == "MP3"
        self._bitrate_label.setVisible(is_mp3)
        self._bitrate_combo.setVisible(is_mp3)
        self._samplerate_label.setVisible(not is_mp3)
        self._samplerate_combo.setVisible(not is_mp3)
        self._bitdepth_label.setVisible(not is_mp3)
        self._bitdepth_combo.setVisible(not is_mp3)
        self._refresh_table()

    def _save_convert_settings(self, *_args) -> None:
        """Persist current convert panel selections to config."""
        if self._loading_settings:
            return
        # Re-load first so we only write the convert_* fields and don't clobber
        # a setting another panel changed (mirrors player_panel's pattern).
        cfg = load_config()
        cfg.convert_target_format = self._format_combo.currentText()
        cfg.convert_mp3_bitrate = int(self._bitrate_combo.currentText())
        sr = self._samplerate_combo.currentData()
        bd = self._bitdepth_combo.currentData()
        if sr is not None:
            cfg.convert_sample_rate = int(sr)
        if bd is not None:
            cfg.convert_bit_depth = int(bd)
        save_config(cfg)
        self._config = cfg

    def _on_selection_changed(self) -> None:
        """Enable/disable Send To based on table selection."""
        has_selection = len(self._file_table.selectedItems()) > 0
        self._send_to_btn.setEnabled(has_selection)

    def _selected_source_paths(self) -> list[str]:
        """Return source paths for currently selected rows, in display order."""
        selected_rows = sorted({idx.row() for idx in self._file_table.selectedIndexes()})
        lossless_paths = [
            p for p in self._file_paths
            if Path(p).suffix.lower() in LOSSLESS_EXTENSIONS
        ]
        return [lossless_paths[r] for r in selected_rows if r < len(lossless_paths)]

    def _effective_path(self, source_path: str) -> str:
        """Return the converted output path if the source was converted, else the source."""
        return self._converted_outputs.get(source_path, source_path)

    def _remove_sources(self, sources: list[str]) -> None:
        """Drop the given source paths from the local list and supporting caches."""
        to_remove = set(sources)
        self._file_paths = [p for p in self._file_paths if p not in to_remove]
        for p in to_remove:
            self._converted_outputs.pop(p, None)
            self._file_info_cache.pop(p, None)
        self._refresh_table()

    def _on_remove_selected(self) -> None:
        """Remove selected files from the local list."""
        sources = self._selected_source_paths()
        if not sources:
            return
        self._remove_sources(sources)

    def _on_context_menu(self, pos) -> None:
        """Show context menu on table right-click."""
        if not self._file_table.selectionModel().hasSelection():
            return
        menu = QMenu(self)
        open_location_action = menu.addAction(self.tr("Open File Location"))
        menu.addSeparator()
        remove_action = menu.addAction(self.tr("Remove"))
        action = menu.exec(self._file_table.viewport().mapToGlobal(pos))
        if action == open_location_action:
            self._on_open_file_location()
        elif action == remove_action:
            self._on_remove_selected()

    def _on_open_file_location(self) -> None:
        """Reveal the first selected file's containing folder in the OS file manager."""
        sources = self._selected_source_paths()
        if not sources:
            return
        self._reveal_in_explorer(self._effective_path(sources[0]))

    @staticmethod
    def _reveal_in_explorer(file_path: str) -> None:
        """Open the OS file manager to the folder containing the given file."""
        import os
        import sys

        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        path = Path(file_path)
        folder = path.parent if path.parent.exists() else path
        if sys.platform == "win32":
            os.startfile(str(folder))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _refresh_table(self) -> None:
        """Rebuild the file table from the local file list."""
        target_format = self._format_combo.currentText()
        target_ext = {
            "WAV": ".wav",
            "FLAC": ".flac",
            "AIFF": ".aiff",
            "MP3": ".mp3",
        }.get(target_format, ".aiff")
        is_mp3 = target_format == "MP3"

        # Separate lossless from lossy
        lossless_paths: list[str] = []
        lossy_count = 0
        for p in self._file_paths:
            ext = Path(p).suffix.lower()
            if ext in LOSSLESS_EXTENSIONS:
                lossless_paths.append(p)
            elif ext in LOSSY_EXTENSIONS:
                lossy_count += 1

        self._file_table.setRowCount(len(lossless_paths))
        convertible_count = 0

        for row, file_path in enumerate(lossless_paths):
            src_path = Path(file_path)
            src_ext = src_path.suffix.lower()
            normalised_src = ".aiff" if src_ext == ".aif" else src_ext

            # Filename
            name_item = QTableWidgetItem(src_path.name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._file_table.setItem(row, 0, name_item)

            # From
            from_item = QTableWidgetItem(self._get_from_label(file_path, src_ext))
            from_item.setFlags(from_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            from_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._file_table.setItem(row, 1, from_item)

            # To
            to_item = QTableWidgetItem(target_ext.upper().lstrip("."))
            to_item.setFlags(to_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            to_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._file_table.setItem(row, 2, to_item)

            # Status
            if file_path in self._converted_outputs:
                label = QLabel(self.tr("Done"))
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                label.setStyleSheet(
                    f"background-color: {Theme.NEON_GREEN};"
                    " color: #000000;"
                    " font-weight: bold;"
                )
                self._file_table.setCellWidget(row, 3, label)
            elif not is_mp3 and normalised_src == target_ext:
                status_text = self.tr("Same format")
                status_item = QTableWidgetItem(status_text)
                status_item.setForeground(Qt.GlobalColor.darkYellow)
                status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._file_table.setItem(row, 3, status_item)
            else:
                status_text = self.tr("Ready")
                status_item = QTableWidgetItem(status_text)
                status_item.setForeground(Qt.GlobalColor.green)
                convertible_count += 1
                status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._file_table.setItem(row, 3, status_item)

        # Stats
        parts = []
        if lossless_paths:
            parts.append(self.tr("{count} files").format(count=len(lossless_paths)))
        if convertible_count > 0:
            parts.append(self.tr("{count} to convert").format(count=convertible_count))
        if lossy_count > 0:
            parts.append(self.tr("({count} lossy skipped)").format(count=lossy_count))
        self._stats_label.setText(" | ".join(parts) if parts else self.tr("No files"))

        # Enable convert button only if there are convertible files
        self._convert_btn.setEnabled(convertible_count > 0)
        # Send To enablement is driven by selection via _on_selection_changed.
        if not self._file_table.selectedItems():
            self._send_to_btn.setEnabled(False)

    def _on_convert_clicked(self) -> None:
        """Handle convert button click."""
        target_format = self._format_combo.currentText()
        target_ext = {
            "WAV": ".wav",
            "FLAC": ".flac",
            "AIFF": ".aiff",
            "MP3": ".mp3",
        }.get(target_format, ".aiff")
        is_mp3 = target_format == "MP3"

        # Collect only convertible file paths (skip already converted)
        file_paths = []
        for p in self._file_paths:
            ext = Path(p).suffix.lower()
            normalised = ".aiff" if ext == ".aif" else ext
            if ext in LOSSLESS_EXTENSIONS and p not in self._converted_outputs:
                if is_mp3 or normalised != target_ext:
                    file_paths.append(p)

        if file_paths:
            bitrate = int(self._bitrate_combo.currentText())
            sample_rate = int(self._samplerate_combo.currentData() or 44100)
            bit_depth = int(self._bitdepth_combo.currentData() or 16)
            self.start_conversion.emit(
                file_paths, target_format, bitrate, sample_rate, bit_depth
            )

    def _on_send_to_analyze(self) -> None:
        """Send selected rows to Analyze using the converted output path when available."""
        sources = self._selected_source_paths()
        if not sources:
            return
        effective = [self._effective_path(s) for s in sources]
        self.send_to_analyze.emit(effective)
        self._remove_sources(sources)

    def _on_send_to_rename(self) -> None:
        """Send selected rows to Rename using the converted output path when available."""
        sources = self._selected_source_paths()
        if not sources:
            return
        effective = [self._effective_path(s) for s in sources]
        self.send_to_rename.emit(effective)
        self._remove_sources(sources)

    def _on_send_to_player(self) -> None:
        """Send selected rows to Player using the converted output path when available."""
        sources = self._selected_source_paths()
        if not sources:
            return
        tracks = [
            {
                "file_path": self._effective_path(s),
                "display_name": Path(self._effective_path(s)).stem,
            }
            for s in sources
        ]
        self.send_to_player.emit(tracks)
        self._remove_sources(sources)

    def refresh(self) -> None:
        """Refresh the table (called when panel becomes visible)."""
        self._refresh_table()

    @property
    def progress_panel(self) -> ProgressPanel:
        """Get the progress panel widget."""
        return self._progress_panel

    def _lossless_paths(self) -> list[str]:
        """The file list filtered to lossless paths, matching table row order."""
        return [
            p for p in self._file_paths
            if Path(p).suffix.lower() in LOSSLESS_EXTENSIONS
        ]

    def _set_text_status(self, row: int, text: str, color) -> None:
        """Put a plain coloured-text status (e.g. Ready/Converting) in a row.

        Removes any bar-style cell widget first so a row can revert from a
        Done/Error bar back to text."""
        self._file_table.removeCellWidget(row, 3)
        item = QTableWidgetItem(text)
        item.setForeground(color)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._file_table.setItem(row, 3, item)

    def _set_bar_status(self, row: int, text: str, bg: str, tooltip: str | None = None) -> None:
        """Put a filled status bar (Done/Error) in a row."""
        # Drop any underlying text item first, else its centered text (e.g. the
        # yellow "Converting" item) peeks out from behind the bar widget.
        self._file_table.takeItem(row, 3)
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(
            f"background-color: {bg};"
            " color: #000000;"
            " font-weight: bold;"
        )
        if tooltip:
            label.setToolTip(tooltip)
        self._file_table.setCellWidget(row, 3, label)

    def mark_converting(self, file_paths: list[str]) -> None:
        """Flag every row about to be converted with a yellow 'Converting'
        status, shown the moment the batch starts."""
        self._converting = set(file_paths)
        lossless_paths = self._lossless_paths()
        for row in range(self._file_table.rowCount()):
            if row >= len(lossless_paths):
                break
            if lossless_paths[row] in self._converting:
                self._set_text_status(row, self.tr("Converting"), QColor(Theme.NEON_YELLOW))

    def mark_file_result(self, result: ConversionResult | None) -> None:
        """Update a single row as soon as its file finishes, so each flips to
        Done/Error independently rather than all at the end."""
        if result is None:
            return
        lossless_paths = self._lossless_paths()
        for row in range(self._file_table.rowCount()):
            if row >= len(lossless_paths):
                break
            if lossless_paths[row] == result.source_path:
                self._apply_result_to_row(row, result)
                self._converting.discard(result.source_path)
                return

    def _apply_result_to_row(self, row: int, result: ConversionResult) -> None:
        """Render one conversion result into its Status cell."""
        if result.error:
            self._set_bar_status(
                row,
                self.tr("Incomplete") if result.incomplete else self.tr("Error"),
                Theme.ERROR,
                tooltip=result.error,
            )
        elif result.skipped:
            # Nothing was converted; restore the resting "Ready" status (a
            # skipped file was never sent unless something changed under us).
            self._set_text_status(row, self.tr("Ready"), QColor(Qt.GlobalColor.green))
        else:
            self._converted_outputs[result.source_path] = result.output_path
            self._set_bar_status(row, self.tr("Done"), Theme.NEON_GREEN)

    def mark_converted(self, results: list[ConversionResult]) -> None:
        """Final sweep after the batch finishes: apply every result and revert
        any row that never ran (e.g. a cancelled batch) back to 'Ready'."""
        result_map = {r.source_path: r for r in results}
        lossless_paths = self._lossless_paths()

        for row in range(self._file_table.rowCount()):
            name_item = self._file_table.item(row, 0)
            if name_item is None:
                continue

            if row >= len(lossless_paths):
                break

            path = lossless_paths[row]
            result = result_map.get(path)
            if result is not None:
                self._apply_result_to_row(row, result)
            elif path in self._converting:
                # Marked Converting but never completed (cancelled mid-batch).
                self._set_text_status(row, self.tr("Ready"), QColor(Qt.GlobalColor.green))

        self._converting.clear()
