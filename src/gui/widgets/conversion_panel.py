"""Conversion panel for batch lossless audio format conversion."""

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyle,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .fitted_combo import FittedComboBox

from src.conversion.result import (
    FORMAT_EXTENSION,
    LOSSLESS_EXTENSIONS,
    LOSSY_EXTENSIONS,
    ConversionResult,
    is_quality_downgrade,
    is_same_format,
    raises_quality,
    read_audio_quality,
)
from src.utils.config import load_config, save_config
from src.utils.paths import normalize_track_path

from ..models import TrackStore
from ..styles.theme import BackgroundOverlay, Theme, panel_header_row
from .elided_label import ElidedLabel
from .droppable_table import DroppableTableWidget
from .progress_bar import ProgressPanel


class ConversionPanel(QWidget):
    """Panel for converting audio files between lossless formats."""

    # (file_paths, target_format, bitrate, sample_rate, bit_depth, output_dir).
    # sample_rate/bit_depth are `object`, not `int`: None is the "Keep source"
    # selection and a Signal(int) would quietly deliver it as 0. output_dir is
    # a plain str because its own "unset" is "" — the empty string reaches the
    # engine as None, i.e. "write beside the source".
    start_conversion = Signal(list, str, int, object, object, str)
    cancel_conversion = Signal()
    send_to_analyze = Signal(list)  # list of file path strings
    send_to_rename = Signal(list)  # list of file path strings
    send_to_player = Signal(list)  # list of track dicts for player
    pipeline_toggled = Signal(bool)  # the `|` toggle; MainWindow owns the coupling

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
        # source path -> (sample rate, bit depth); (None, None) if unreadable.
        # Feeds both the "From" label and the same-format downgrade test, so one
        # sf.info() per file covers both.
        self._quality_cache: dict[str, tuple[int | None, int | None]] = {}
        self._convertible_count = 0  # READY rows, as of the last _refresh_table
        self._config = load_config()
        # The folder last picked, remembered even while the Source toggle is on
        # so switching back to it costs one click. load_config has already
        # forgotten one that no longer exists, and forced the mode on with it.
        self._output_dir: str = self._config.convert_output_dir
        self._use_source_dir: bool = self._config.convert_use_source_dir
        self._loading_settings = True
        self._setup_ui()
        self._loading_settings = False
        self._connect_signals()
        self._bg_overlay = BackgroundOverlay("bg_convert.png", self)

    def format_row_min_width(self) -> int:
        """Panel width the format selectors need, including the panel's padding.

        The window minimum for Convert was a constant, so a translation that
        widened these controls pushed the row past the window and the labels
        were squeezed rather than the window grown — 'Frequenza di
        campionamento:' clipped by 25px once "Keep source" widened the combos.

        Measured over the lossless controls whichever are currently showing:
        hidden widgets contribute nothing to a layout's own hint, so asking the
        row would shrink the minimum the moment MP3 hid the rate and depth, and
        the window would jump about as the target format changed. The bitrate
        pair is excluded because it is narrower and never shares the row.

        The destination's two buttons are in here because they share that row
        and cannot shrink — the *path* is the one thing left out, on purpose:
        that elides, so it is what gives way as the window narrows.
        """
        row = self._format_row_widget.layout()
        widgets = (
            self._format_label,
            self._format_combo,
            self._samplerate_label,
            self._samplerate_combo,
            self._bitdepth_label,
            self._bitdepth_combo,
            self._dest_choose_btn,
            self._dest_source_toggle,
        )
        margins = row.contentsMargins()
        # A size *hint* ignores setFixedWidth — the icon buttons hint at 54 and
        # are laid out at 34 — so cap each one at the width it is allowed.
        return (
            sum(min(w.sizeHint().width(), w.maximumWidth()) for w in widgets)
            + row.spacing() * (len(widgets) - 1)
            + margins.left()
            + margins.right()
            + Theme.PADDING * 2  # the panel's own contents margins
        )

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
        desc = ElidedLabel(self.tr("Convert audio files between formats (WAV, FLAC, AIFF, MP3)."))
        desc.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        layout.addLayout(panel_header_row(title, desc))

        # Target format selector
        format_row = QHBoxLayout()
        # Explicit, for two reasons. A layout that is handed to a widget takes
        # the Qt style default (6px) rather than this panel's 8, and — the one
        # that bit — an unset spacing reads back as **-1**, so the window
        # minimum below was computing `-1 * gaps` and understating the row by
        # 60-odd pixels. It fitted anyway until the row filled up.
        format_row.setSpacing(Theme.SPACING)
        self._format_label = QLabel(self.tr("Target Format:"))
        format_row.addWidget(self._format_label)
        self._format_combo = FittedComboBox()
        self._format_combo.setObjectName("compactCombo")
        self._format_combo.addItems(["AIFF", "WAV", "FLAC", "MP3"])
        self._format_combo.setCurrentText(self._config.convert_target_format)
        format_row.addWidget(self._format_combo)

        # Sample rate selector (visible for lossless targets)
        self._samplerate_label = QLabel(self.tr("Sample Rate:"))
        self._samplerate_combo = FittedComboBox()
        self._samplerate_combo.setObjectName("compactCombo")
        # "Keep source" (None) leaves the axis alone, the way the CLI does with
        # the flag omitted. It is the only setting that suits a mixed batch,
        # and the only one available to a source below the lowest rate here.
        for label, hz in [
            (self.tr("Keep source"), None),
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
        self._bitdepth_combo = FittedComboBox()
        self._bitdepth_combo.setObjectName("compactCombo")
        for label, bits in [
            (self.tr("Keep source"), None),
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
        self._bitrate_combo = FittedComboBox()
        self._bitrate_combo.setObjectName("compactCombo")
        self._bitrate_combo.addItems(["128", "192", "256", "320"])
        self._bitrate_combo.setCurrentText(str(self._config.convert_mp3_bitrate))
        format_row.addWidget(self._bitrate_label)
        format_row.addWidget(self._bitrate_combo)

        # Where the converted files are written — last on the row, after
        # whichever quality selectors the target format is showing.
        #
        # No text label of its own, unlike every other control here: the folder
        # icon and the destination printed beside it already say what it is,
        # and the row cannot afford the decoration. Measured, in the languages
        # that make this row expensive — a "Save To:" ahead of the button costs
        # 62px in English and ~138 in French, and it was the difference between
        # the default message fitting at the default window size and being
        # elided in ten of the twelve languages. The slicer's folder button is
        # icon-only for the same reason.
        self._dest_choose_btn = QPushButton()
        self._dest_choose_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
        self._dest_choose_btn.setFixedWidth(34)
        self._dest_choose_btn.setToolTip(self.tr("Choose the folder converted files are saved to"))
        format_row.addWidget(self._dest_choose_btn)
        # The mode, as a toggle rather than the clear button this started as: a
        # ✕ only appears once a folder is already set, so the way back to the
        # default was invisible exactly when someone wanted to know it existed,
        # and "clear" is not what it means. Lit is the resting state.
        #
        # Text, not an icon — on macOS SP_DirHomeIcon draws the same folder as
        # the picker beside it, and no standard icon says "beside the source".
        # One word keeps it affordable in every language. autoToggle is the
        # app's toggle style (the Analyze panel's Auto), reused the way
        # history_panel reuses it.
        self._dest_source_toggle = QPushButton(self.tr("Source"))
        self._dest_source_toggle.setObjectName("autoToggle")
        self._dest_source_toggle.setCheckable(True)
        format_row.addWidget(self._dest_source_toggle)
        # A path is arbitrarily long and belongs to the user, not to us, so it
        # elides instead of pushing the window wider — from the *left*, so what
        # survives is the deepest folder rather than the root. Sharing the row
        # leaves it around 150px at the default window size, and in that much
        # room the other modes spend the whole budget on the part every path on
        # the machine has in common: middle gives "/var/fol… masters", right
        # gives "/var/folders/nh/m4f…". This gives "…44.1k 16bit masters" and
        # grows back into the full path as the window widens. ElidedLabel
        # raises its own tooltip with the full path whenever it is cut.
        # It takes the row's leftover width, which is why there is no stretch
        # after it: the stretch *is* this label.
        self._dest_path_label = ElidedLabel("", mode=Qt.TextElideMode.ElideLeft)
        self._dest_path_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        format_row.addWidget(self._dest_path_label, 1)

        # Host the format controls in a widget so the window sizer can read their
        # pushed-together width and keep the Convert window from getting narrower
        # than what fits the Target Format / Sample Rate / Bit Depth selectors.
        self._format_row_widget = QWidget()
        self._format_row_widget.setLayout(format_row)
        layout.addWidget(self._format_row_widget)
        self._sync_destination()

        # Progress panel (initially hidden)
        self._progress_panel = ProgressPanel(show_activity=True)
        self._progress_panel.cancel_clicked.connect(self.cancel_conversion.emit)
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

        # The pipeline: Convert -> Analyze -> into a playlist, in one press.
        # `|` is a glyph, not a word — deliberately not tr()'d — and the
        # tooltip carries the meaning, saying what the NEXT click does.
        self._pipeline_toggle = QPushButton("|")
        self._pipeline_toggle.setObjectName("pipelineToggle")
        self._pipeline_toggle.setCheckable(True)
        bottom_row.addWidget(self._pipeline_toggle)

        # Editable: picking an item targets that playlist, typing a name
        # creates one. The default completer would silently turn a typed name
        # into a pick, and the two have to stay distinguishable, so it is off.
        self._pipeline_target = FittedComboBox()
        self._pipeline_target.setEditable(True)
        self._pipeline_target.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._pipeline_target.setCompleter(None)
        self._pipeline_target.setMinimumWidth(160)
        self._pipeline_target.lineEdit().setPlaceholderText(self.tr("Playlist name"))
        bottom_row.addWidget(self._pipeline_target)

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

        bottom_row.setSpacing(Theme.SPACING)  # or spacing() reads back -1
        layout.addLayout(bottom_row)
        self._bottom_row = bottom_row

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

        # Restore the pipeline's toggle and target. _loading_settings is still
        # on here, so neither write straight back to disk.
        self._pipeline_toggle.setChecked(self._config.convert_pipeline_enabled)
        self.restore_pipeline_target(self._config.convert_pipeline_playlist)
        self._sync_pipeline_controls()

    def _connect_signals(self) -> None:
        """Connect internal signals."""
        self._format_combo.currentTextChanged.connect(self._on_format_changed)
        self._format_combo.currentTextChanged.connect(self._save_convert_settings)
        self._samplerate_combo.currentIndexChanged.connect(self._save_convert_settings)
        self._bitdepth_combo.currentIndexChanged.connect(self._save_convert_settings)
        # Rate/depth decide whether a same-format row is a downgrade, so they
        # change Ready/Same format the same way the target format does.
        self._samplerate_combo.currentIndexChanged.connect(self._refresh_table)
        self._bitdepth_combo.currentIndexChanged.connect(self._refresh_table)
        self._bitrate_combo.currentTextChanged.connect(self._save_convert_settings)
        self._pipeline_toggle.toggled.connect(self._on_pipeline_toggled)
        self._pipeline_target.currentIndexChanged.connect(self._on_pipeline_target_changed)
        self._pipeline_target.editTextChanged.connect(self._on_pipeline_target_changed)
        self._dest_choose_btn.clicked.connect(self._on_choose_output_dir)
        self._dest_source_toggle.toggled.connect(self._on_source_toggled)
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

    def _quality(self, file_path: str) -> tuple[int | None, int | None]:
        """The file's (sample rate, bit depth), read once and cached."""
        cached = self._quality_cache.get(file_path)
        if cached is None:
            cached = read_audio_quality(file_path)
            self._quality_cache[file_path] = cached
        return cached

    def _get_from_label(self, file_path: str, src_ext: str) -> str:
        """Build a 'From' label like 'FLAC 44.1k/16' for the given file."""
        ext_label = src_ext.upper().lstrip(".")
        rate, bits = self._quality(file_path)
        if rate is None:
            return ext_label
        sr_str = f"{rate / 1000.0:.1f}".rstrip("0").rstrip(".") + "k"
        return f"{ext_label} {sr_str}/{bits}" if bits else f"{ext_label} {sr_str}"

    def _target_ext(self) -> str:
        """Extension for the currently selected target format."""
        return FORMAT_EXTENSION.get(self._format_combo.currentText(), ".aiff")

    # Row verdicts. READY is the only one that converts; the other two each
    # need their own status text, because "there is nothing to lower" and
    # "that would be an upsample" call for opposite corrections.
    READY = "ready"
    SAME_FORMAT = "same_format"
    UPSAMPLE = "upsample"

    def _verdict(self, file_path: str, target_ext: str, is_mp3: bool) -> str:
        """What the current settings would do to this file.

        Quality only ever goes down. Into its own format that means a strict
        downgrade — a 96 kHz/24-bit FLAC to 44.1 kHz/16-bit FLAC for older
        players; matching settings would just rewrite it. Into another format,
        equal settings are the whole point, so only a raise is refused. MP3 is
        exempt: the rate/depth selectors don't apply to it.

        Ignores whether the file was already converted; callers handle that.
        """
        if is_mp3:
            return self.READY
        rate, bits = self._quality(file_path)
        sample_rate = self._samplerate_combo.currentData()
        bit_depth = self._bitdepth_combo.currentData()
        if is_same_format(file_path, target_ext):
            if is_quality_downgrade(rate, bits, target_ext, sample_rate, bit_depth):
                return self.READY
            return self.SAME_FORMAT
        if raises_quality(rate, bits, target_ext, sample_rate, bit_depth):
            return self.UPSAMPLE
        return self.READY

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
        # None is a real choice here ("Keep source"), so it is stored, not
        # treated as "nothing selected".
        sr = self._samplerate_combo.currentData()
        bd = self._bitdepth_combo.currentData()
        cfg.convert_sample_rate = None if sr is None else int(sr)
        cfg.convert_bit_depth = None if bd is None else int(bd)
        cfg.convert_output_dir = self._output_dir
        cfg.convert_use_source_dir = self._use_source_dir
        cfg.convert_pipeline_enabled = self._pipeline_toggle.isChecked()
        cfg.convert_pipeline_playlist = self._pipeline_target.currentText().strip()
        save_config(cfg)
        self._config = cfg

    # --------------------------------------------------------------- pipeline

    def _sync_pipeline_controls(self) -> None:
        """Reflect the toggle in the Convert button's label, tooltip and
        enablement, and in whether the target field is offered at all."""
        on = self._pipeline_toggle.isChecked()
        self._pipeline_toggle.setToolTip(
            self.tr("Turn off the pipeline — Convert goes back to converting only.")
            if on
            else self.tr(
                "Turn on the pipeline: Convert → Analyze → add to the playlist named here."
            )
        )
        self._pipeline_target.setEnabled(on)
        if on:
            self._convert_btn.setText(self.tr("Start"))
            self._convert_btn.setToolTip(self.tr("Send the tracks through the pipeline"))
        else:
            self._convert_btn.setText(self.tr("Convert"))
            self._convert_btn.setToolTip("")
        self._sync_convert_enabled()

    def _sync_convert_enabled(self) -> None:
        """Convert needs a convertible row; Start needs a forwardable one and
        somewhere to put it."""
        if self._pipeline_toggle.isChecked():
            to_convert, passthrough = self.pipeline_rows()
            enabled = bool(to_convert or passthrough) and bool(
                self._pipeline_target.currentText().strip()
            )
        else:
            enabled = self._convertible_count > 0
        self._convert_btn.setEnabled(enabled)

    def _on_pipeline_toggled(self, checked: bool) -> None:
        self._sync_pipeline_controls()
        self._save_convert_settings()
        self.pipeline_toggled.emit(checked)

    def _on_pipeline_target_changed(self, *_args) -> None:
        self._sync_convert_enabled()
        self._save_convert_settings()

    def restore_pipeline_target(self, name: str) -> None:
        """Point the field at a remembered playlist.

        Called twice: once in __init__ (when the list is still empty, so the
        name can only be typed back) and again by MainWindow once it has fed
        the real playlists in, which is the pass that can resolve it.

        A name that still matches a playlist is *selected*, so the next Start
        reuses it. Only a name that matches nothing is set as edit text, which
        reads as "create". Setting the text alone would make a new numbered
        playlist on every launch.
        """
        if not name:
            return
        index = self._pipeline_target.findText(name, Qt.MatchFlag.MatchExactly)
        if index >= 0:
            self._pipeline_target.setCurrentIndex(index)
        else:
            self._pipeline_target.setCurrentIndex(-1)
            self._pipeline_target.setEditText(name)

    def pipeline_enabled(self) -> bool:
        return self._pipeline_toggle.isChecked()

    def set_pipeline_enabled(self, enabled: bool) -> None:
        """Reflect the toggle without re-entering the handler that saves.

        MainWindow calls this when auto-analyze goes off, which switches the
        pipeline off with it — a reflect, never an act.
        """
        if self._pipeline_toggle.isChecked() == enabled:
            return
        self._pipeline_toggle.blockSignals(True)
        self._pipeline_toggle.setChecked(enabled)
        self._pipeline_toggle.blockSignals(False)
        self._sync_pipeline_controls()
        self._save_convert_settings()

    def pipeline_target(self) -> tuple[int | None, str]:
        """(node id, text) for the target. The id is set only when an existing
        playlist was picked from the list — typed text that happens to equal a
        listed name still reads as "create", which is why the completer is off.
        """
        text = self._pipeline_target.currentText().strip()
        index = self._pipeline_target.currentIndex()
        if index >= 0 and self._pipeline_target.itemText(index) == text:
            node_id = self._pipeline_target.itemData(index)
            if node_id is not None:
                return int(node_id), text
        return None, text

    def set_playlists(self, rows: list[tuple[int, str]]) -> None:
        """Fill the target list with (node_id, label) in tree order.

        The panel never opens the library itself; MainWindow feeds it at
        startup and on every nodes_changed. A refill keeps whatever the user
        had — the same playlist if it survived, the same typed text if not.
        """
        picked_id, text = self.pipeline_target()
        blocked = self._pipeline_target.blockSignals(True)
        self._pipeline_target.clear()
        for node_id, label in rows:
            self._pipeline_target.addItem(label, node_id)
        if picked_id is not None and self.select_node(picked_id):
            pass
        else:
            self._pipeline_target.setCurrentIndex(-1)
            self._pipeline_target.setEditText(text)
        self._pipeline_target.blockSignals(blocked)
        self._sync_convert_enabled()

    def select_node(self, node_id: int) -> bool:
        """Point the field at a playlist by id. True when it was in the list.

        Called after the pipeline creates a playlist, so the next Start reuses
        it instead of making a second one with the same name.
        """
        for i in range(self._pipeline_target.count()):
            if self._pipeline_target.itemData(i) == node_id:
                self._pipeline_target.setCurrentIndex(i)
                return True
        return False

    def pipeline_rows(self) -> tuple[list[str], list[str]]:
        """(to convert, forwarded as-is) for a Start press.

        Start takes every lossless row that is not blocked, because the user's
        model is "these tracks, into that playlist, analysed" — a batch that
        already happens to be in the target format would otherwise leave the
        button dead and the pipeline unusable. A refused upsample stays in the
        table; it is the one thing the pipeline cannot honour.
        """
        target_ext = self._target_ext()
        is_mp3 = self._format_combo.currentText() == "MP3"
        to_convert: list[str] = []
        passthrough: list[str] = []
        for path in self._lossless_paths():
            if path in self._converted_outputs:
                passthrough.append(path)
                continue
            verdict = self._verdict(path, target_ext, is_mp3)
            if verdict == self.READY:
                to_convert.append(path)
            elif verdict == self.SAME_FORMAT:
                passthrough.append(path)
        return to_convert, passthrough

    def forget_rows(self, sources: list[str]) -> None:
        """Drop rows the pipeline has handed on to Analyze, as Send To does."""
        self._remove_sources(sources)

    def set_pipeline_controls_enabled(self, enabled: bool) -> None:
        """Lock the two controls while a conversion runs — the batch in flight
        is already armed one way or the other."""
        self._pipeline_toggle.setEnabled(enabled)
        self._pipeline_target.setEnabled(enabled and self._pipeline_toggle.isChecked())

    def bottom_row_min_width(self) -> int:
        """Panel width the bottom row needs, including the panel's padding.

        Measured the way format_row_min_width is: a size *hint* ignores
        setFixedWidth, so each contributor is capped at the width it is
        allowed, and the row's own spacing is read back only because
        _setup_ui sets it (an unset QLayout answers -1 and the sum would
        subtract where it means to add). The stats label is left out — it is
        the one thing here that may shrink.
        """
        widgets = (
            self._pipeline_toggle,
            self._pipeline_target,
            self._convert_btn,
            self._send_to_btn,
        )
        margins = self._bottom_row.contentsMargins()
        return (
            sum(min(w.sizeHint().width(), w.maximumWidth()) for w in widgets)
            + self._bottom_row.spacing() * (len(widgets) - 1)
            + margins.left()
            + margins.right()
            + Theme.PADDING * 2  # the panel's own contents margins
        )

    # ------------------------------------------------------------ destination

    def output_dir(self) -> str:
        """The folder a conversion would write to — "" for beside the source.

        The mode decides, not the remembered path: a folder stays in
        _output_dir while the toggle is on precisely so it can be switched back
        to, and reading that field directly would send files to a folder the
        user can see the app is not using.
        """
        return "" if self._use_source_dir else self._output_dir

    def _sync_destination(self) -> None:
        """Reflect the destination in the toggle, the text and both tooltips."""
        custom = not self._use_source_dir and bool(self._output_dir)
        # Which end gives way depends on the value, not the widget. A path is
        # cut from the left so the chosen folder survives; the resting message
        # is a sentence and reads from the start like any other.
        self._dest_path_label.set_elide_mode(
            Qt.TextElideMode.ElideLeft if custom else Qt.TextElideMode.ElideRight
        )
        self._dest_path_label.setText(
            self._output_dir if custom else self.tr("Same folder as source")
        )
        # Set here rather than left to the label's own resize handling: picking
        # a folder changes the text without changing the width, so no resize
        # need follow, and the label would keep the previous path's tooltip.
        self._dest_path_label.setToolTip(self.output_dir())

        # Reflecting the state, not acting on it: an unguarded setChecked here
        # re-enters _on_source_toggled, and the branch that asks for a folder
        # then raises a *modal file dialog* from inside a state refresh — which
        # in a test with no one to click it is a hung suite, and in the app is a
        # dialog nobody asked for.
        self._dest_source_toggle.blockSignals(True)
        self._dest_source_toggle.setChecked(self._use_source_dir)
        self._dest_source_toggle.blockSignals(False)
        # What the *next* click does, in both directions, the way every other
        # toggle in the app states it — a lit button alone does not say what
        # turning it off would mean.
        self._dest_source_toggle.setToolTip(
            self.tr("Save converted files to a folder instead")
            if self._use_source_dir
            else self.tr("Save converted files next to the originals")
        )

        # The label is the row's give — squeeze the window far enough and it
        # elides away to nothing — so the destination is reachable from the
        # button too, which cannot shrink. Composed, not a second translatable
        # string.
        choose_tip = self.tr("Choose the folder converted files are saved to")
        self._dest_choose_btn.setToolTip(
            f"{choose_tip}\n{self._output_dir}" if custom else choose_tip
        )

    def _set_destination(self, path: str, use_source: bool) -> None:
        self._output_dir = path
        self._use_source_dir = use_source
        self._sync_destination()
        self._save_convert_settings()

    def _on_choose_output_dir(self) -> str:
        """Pick the folder converted files are written to.

        Choosing one turns the Source toggle off by itself: the user has just
        named a destination, and leaving the toggle lit would ignore it.
        Returns the chosen folder, or "" if the dialog was cancelled — the
        toggle needs to know, because a cancel there must leave it as it was.
        """
        folder = QFileDialog.getExistingDirectory(
            self,
            self.tr("Choose Output Folder"),
            self._output_dir,
        )
        if not folder:
            return ""
        # A dialog result is a path arriving from the OS, and on Windows it
        # comes back with forward slashes. The converted files' paths are
        # built from this and can end up in the library via Send To, where
        # identity is exact-string — so it is spelled the app's one way here,
        # at the point it arrives, like every other such entry point.
        folder = normalize_track_path(folder)
        self._set_destination(folder, use_source=False)
        return folder

    def _on_source_toggled(self, checked: bool) -> None:
        """Switch between writing beside each source and writing to a folder.

        Turning it off restores the folder last picked rather than doing
        nothing, which is the whole reason the path is remembered while the
        toggle is on. With nothing to restore — or with a folder that has gone
        away since — it asks for one, and a cancelled dialog leaves the toggle
        exactly as it was rather than stranding the panel in an "off" state
        with no destination behind it.
        """
        if checked:
            self._set_destination(self._output_dir, use_source=True)
            return
        if self._output_dir and Path(self._output_dir).is_dir():
            self._set_destination(self._output_dir, use_source=False)
            return
        if not self._on_choose_output_dir():
            # Back to lit, keeping whatever folder was remembered. The toggle
            # itself is re-checked by _sync_destination, which does not re-enter
            # this slot.
            self._set_destination(self._output_dir, use_source=True)

    def _output_dir_is_writable(self) -> bool:
        """True if the chosen folder exists (or can be made) and takes a file.

        Checked once before a batch rather than per file: a folder deleted or
        unmounted since it was picked would otherwise fail every row with a
        libsndfile message that never names the real problem.
        """
        destination = self.output_dir()
        if not destination:
            return True  # each file's own folder — it's where the source is
        target = Path(destination)
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".mixedinp-write-test"
            probe.touch()
            probe.unlink()
            return True
        except OSError as exc:
            QMessageBox.warning(
                self,
                self.tr("Output Folder Unavailable"),
                self.tr("Can't save converted files to {folder}.\n\n{error}").format(
                    folder=destination, error=exc
                ),
            )
            return False

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
            self._quality_cache.pop(p, None)
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
        target_ext = self._target_ext()
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

            # Filename — once converted, show the output's name (new extension) so
            # the user can see the result and knows that's what a drag / Send To
            # will move to another panel.
            display_name = Path(self._converted_outputs.get(file_path, file_path)).name
            name_item = QTableWidgetItem(display_name)
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
            else:
                # A row that won't convert says which way to move the
                # selectors, since the status alone can't.
                verdict = self._verdict(file_path, target_ext, is_mp3)
                if verdict == self.SAME_FORMAT:
                    status_text = self.tr("Same format")
                    colour = Qt.GlobalColor.darkYellow
                    tooltip = self.tr(
                        "Choose a lower sample rate or bit depth to convert this file."
                    )
                elif verdict == self.UPSAMPLE:
                    status_text = self.tr("Would upsample")
                    colour = Qt.GlobalColor.darkYellow
                    tooltip = self.tr(
                        "Choose a sample rate and bit depth no higher than this file's."
                    )
                else:
                    status_text = self.tr("Ready")
                    colour = Qt.GlobalColor.green
                    tooltip = ""
                    convertible_count += 1
                status_item = QTableWidgetItem(status_text)
                status_item.setForeground(colour)
                status_item.setToolTip(tooltip)
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

        # Enable convert button only if there are convertible files. With the
        # pipeline on the test is a different one (see _sync_convert_enabled),
        # so the count is remembered rather than applied here.
        self._convertible_count = convertible_count
        self._sync_convert_enabled()
        # Send To enablement is driven by selection via _on_selection_changed.
        if not self._file_table.selectedItems():
            self._send_to_btn.setEnabled(False)

    def _on_convert_clicked(self) -> None:
        """Handle convert button click."""
        target_format = self._format_combo.currentText()
        target_ext = self._target_ext()
        is_mp3 = target_format == "MP3"
        pipeline = self._pipeline_toggle.isChecked()

        # Collect only convertible file paths (skip already converted). Shares
        # _verdict with the table so what runs matches what says "Ready".
        file_paths = [
            p for p in self._file_paths
            if Path(p).suffix.lower() in LOSSLESS_EXTENSIONS
            and p not in self._converted_outputs
            and self._verdict(p, target_ext, is_mp3) == self.READY
        ]

        # A pipeline run with nothing to convert is still a run — its rows go
        # straight to Analyze — so it emits with an empty list and MainWindow
        # takes the no-conversion branch.
        if file_paths or pipeline:
            if file_paths and not self._output_dir_is_writable():
                return
            bitrate = int(self._bitrate_combo.currentText())
            # Passed through as-is: None means "Keep source" all the way down
            # to the writer, so no `or` default here.
            self.start_conversion.emit(
                file_paths,
                target_format,
                bitrate,
                self._samplerate_combo.currentData(),
                self._bitdepth_combo.currentData(),
                self.output_dir(),
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
            # Update the Filename cell in place so it shows the new extension the
            # moment this file finishes (rather than only on the next rebuild).
            name_item = self._file_table.item(row, 0)
            if name_item is not None:
                name_item.setText(Path(result.output_path).name)
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
