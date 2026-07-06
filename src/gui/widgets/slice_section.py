"""Collapsible slice section for the Player panel.

A lazily-built, collapsed-by-default expander that turns the player's loaded
track into a slicer: a full-track waveform (which doubles as the seek control
while open), a zoomed scrubber, draggable start/end markers, length/nudge
controls, an A-B loop toggle, and slice export.

It owns no audio device — it drives the player's single :class:`PlayerEngine`
(loop bounds, seek, mark-from-position). Nothing is decoded or shown until the
user first expands it. Once built, the waveform is kept across collapse/expand
so reopening is instant; it is dumped only when the track changes or is removed,
so a casual listener never pays for waveform RAM for a track they don't slice.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from src.conversion.result import FORMAT_EXTENSION
from ..styles.theme import Theme
from .player_engine import PlayerEngine
from .slice_export import export_slice, format_time_ms, parse_time_ms
from .toggle_switch import ToggleSwitch
from .waveform_canvas import WaveformCanvas, ZoomedWaveformCanvas

logger = logging.getLogger(__name__)


class SliceSection(QWidget):
    """Collapsible slicer that operates on the player's currently-loaded track."""

    # Tell the panel to swap the seek control and, on first open, supply a waveform.
    expanded_changed = Signal(bool)
    request_waveform = Signal()
    # User moved the playhead on the waveform — panel forwards to engine.seek_ms.
    seek_requested = Signal(int)

    def __init__(self, engine: PlayerEngine, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._file_path: str | None = None
        self._duration_ms: int = 0
        self._show_hours: bool = False
        self._custom_save_dir: str | None = None
        self._expanded: bool = False
        self._waveform_loaded: bool = False

        self._setup_ui()

        # Buttons/checkbox must not capture focus, so Space stays play/pause and
        # the panel's S/Q/E key routing isn't swallowed by a focused control.
        for btn in self.findChildren(QAbstractButton):
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._set_body_visible(False)
        self._header_btn.setEnabled(False)

    # ------------------------------------------------------------------ UI

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Theme.SPACING)

        # The section itself is transparent (shows the player's grey). The full
        # waveform sits on that grey; only the zoomed detail + controls go in the
        # near-black tray below, so the slice tools read as a distinct work area.
        # All rules are id/type-scoped so they never touch the buttons' styling.
        self.setObjectName("sliceSection")
        self.setStyleSheet(
            "#sliceSection { background: transparent; }"
            f"#sliceTray {{ background-color: {Theme.TRAY_BG}; border-radius: 6px; }}"
            "#sliceTray QLabel { background-color: transparent; }"
        )

        # Header toggle
        self._header_btn = QPushButton(self.tr("▸  Waveform Loop Slicer"))
        self._header_btn.setCheckable(True)
        self._header_btn.setStyleSheet(
            f"text-align: left; font-weight: bold; color: {Theme.ACCENT_TEXT};"
            " padding: 0px; border: none;"
        )
        # Shrink the bar to just the text height (+1px) so it stops hogging
        # vertical space; the default button padding made it far too tall.
        # Bump the point size a couple steps so the header reads clearly.
        _header_font = self._header_btn.font()
        _header_font.setBold(True)
        _header_font.setPointSize(_header_font.pointSize() + 2)
        self._header_btn.setFont(_header_font)
        self._header_btn.setFixedHeight(QFontMetrics(_header_font).height() + 1)
        self._header_btn.toggled.connect(self._on_toggle)
        layout.addWidget(self._header_btn)

        # Full-track waveform — on the player grey, above the dark tray. Also the
        # seek control while expanded.
        self._waveform = WaveformCanvas()
        layout.addWidget(self._waveform)
        # Aliases so the ported handlers read naturally.
        self._range_slider = self._waveform
        self._seek_slider = self._waveform

        # Collapsible dark tray: zoomed detail + all slice controls.
        self._body = QWidget()
        self._body.setObjectName("sliceTray")
        body = QVBoxLayout(self._body)
        body.setContentsMargins(10, 10, 10, 10)
        body.setSpacing(Theme.SPACING)

        # Zoomed scrubber — ±0.5 s detail, scrubbable while paused only.
        self._zoom_waveform = ZoomedWaveformCanvas()
        body.addWidget(self._zoom_waveform)

        section_label_style = (
            f"font-size: 24px; color: {Theme.TEXT_SECONDARY}; font-weight: bold;"
        )
        # Type-scope the rule so the button's width caps don't leak onto its
        # QToolTip (a bare max-width: 20px clipped the tooltip to one letter).
        nudge_style = (
            "QPushButton { font-weight: bold; padding: 0px 4px;"
            " min-width: 20px; max-width: 20px; }"
        )
        _SECTION_LABEL_WIDTH = 120

        # Time row: start edit | Mark | position | Mark | end edit
        time_row = QHBoxLayout()
        time_row.setContentsMargins(0, 8, 0, 8)
        # Force a uniform gap. With the default (-1) spacing, macOS's QMacStyle
        # supplies asymmetric HIG spacing per control pair (PushButton→LineEdit
        # is wider than LineEdit→PushButton), which left each box's "<" nudge
        # sitting farther from it than its ">" nudge.
        time_row.setSpacing(Theme.SPACING)

        self._start_edit = QLineEdit("0:00:000")
        self._start_edit.setFixedWidth(100)
        self._start_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._start_edit.setToolTip(self.tr("Slice start time (m:ss:mmm) — type to set"))

        self._position_label = QLabel("0:00:000")
        self._position_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._position_label.setStyleSheet(f"color: {Theme.ACCENT_TEXT}; font-size: 14px;")

        self._end_edit = QLineEdit("0:00:000")
        self._end_edit.setFixedWidth(100)
        self._end_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._end_edit.setToolTip(self.tr("Slice end time (m:ss:mmm) — type to set"))

        self._mark_start_btn = QPushButton(self.tr("Mark"))
        self._mark_start_btn.setToolTip(self.tr("Mark start at playhead (Q)"))
        self._mark_start_btn.setStyleSheet(
            f"background-color: {Theme.NEON_GREEN}; color: #000; font-weight: bold;"
            " padding-left: 2px; padding-right: 2px;"
        )

        self._mark_end_btn = QPushButton(self.tr("Mark"))
        self._mark_end_btn.setToolTip(self.tr("Mark end at playhead (E)"))
        self._mark_end_btn.setStyleSheet(
            f"background-color: {Theme.ERROR}; color: #fff; font-weight: bold;"
            " padding-left: 2px; padding-right: 2px;"
        )

        # Size the pair to the wider of the two translated labels (60px floor)
        # so they stay equal width and never clip in longer-text languages.
        _mark_w = max(60,
                      self._mark_start_btn.sizeHint().width(),
                      self._mark_end_btn.sizeHint().width())
        self._mark_start_btn.setMinimumWidth(_mark_w)
        self._mark_end_btn.setMinimumWidth(_mark_w)

        self._start_dec_btn = self._nudge_button(nudge_style, "<")
        self._start_dec_btn.setToolTip(self.tr("Nudge start marker back 10 ms"))
        self._start_inc_btn = self._nudge_button(nudge_style, ">")
        self._start_inc_btn.setToolTip(self.tr("Nudge start marker forward 10 ms"))
        self._end_dec_btn = self._nudge_button(nudge_style, "<")
        self._end_dec_btn.setToolTip(self.tr("Nudge end marker back 10 ms"))
        self._end_inc_btn = self._nudge_button(nudge_style, ">")
        self._end_inc_btn.setToolTip(self.tr("Nudge end marker forward 10 ms"))

        time_row.addStretch(1)
        time_row.addWidget(self._start_dec_btn)
        time_row.addWidget(self._start_edit)
        time_row.addWidget(self._start_inc_btn)
        time_row.addStretch(1)
        time_row.addWidget(self._mark_start_btn)
        time_row.addStretch(1)
        time_row.addWidget(self._position_label)
        time_row.addStretch(1)
        time_row.addWidget(self._mark_end_btn)
        time_row.addStretch(1)
        time_row.addWidget(self._end_dec_btn)
        time_row.addWidget(self._end_edit)
        time_row.addWidget(self._end_inc_btn)
        time_row.addStretch(1)
        # Host the time row in a widget so its pushed-together width (stretches
        # collapse to zero in a minimumSizeHint) can be queried by the window
        # sizer to set the player's minimum width while the slicer is open.
        self._time_row_widget = QWidget()
        self._time_row_widget.setLayout(time_row)
        body.addWidget(self._time_row_widget)

        # Length row
        length_row = QHBoxLayout()
        length_row.setContentsMargins(0, 8, 0, 8)
        length_row.setSpacing(Theme.SPACING)  # symmetric nudge gaps (see time_row)
        length_section_label = QLabel(self.tr("Length"))
        length_section_label.setStyleSheet(section_label_style)
        length_section_label.setFixedWidth(_SECTION_LABEL_WIDTH)
        self._length_dec_btn = self._nudge_button(nudge_style, "<")
        self._length_dec_btn.setToolTip(self.tr("Shorten slice by 10 ms"))
        self._length_edit = QLineEdit("0:00:000")
        self._length_edit.setFixedWidth(100)
        self._length_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._length_edit.setToolTip(self.tr("Slice length (m:ss:mmm) — type to set; moves the end marker"))
        self._length_inc_btn = self._nudge_button(nudge_style, ">")
        self._length_inc_btn.setToolTip(self.tr("Lengthen slice by 10 ms"))
        length_row.addWidget(length_section_label)
        length_row.addStretch(1)
        length_row.addWidget(self._length_dec_btn)
        length_row.addWidget(self._length_edit)
        length_row.addWidget(self._length_inc_btn)
        length_row.addStretch(1)
        length_row.addSpacing(_SECTION_LABEL_WIDTH)
        body.addLayout(length_row)

        # Controls row: "< Start" jump + Loop checkbox. Play/Stop come from the
        # player's own transport — looping just changes how the engine plays.
        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(0, 8, 0, 8)
        controls_row.addStretch()
        self._goto_start_btn = QPushButton(self.tr("< Start"))
        self._goto_start_btn.setMinimumWidth(70)
        self._goto_start_btn.setStyleSheet("padding-left: 2px; padding-right: 2px;")
        self._goto_start_btn.setToolTip(self.tr("Jump playhead to start marker (S)"))
        controls_row.addWidget(self._goto_start_btn)
        loop_label = QLabel(self.tr("Loop"))
        loop_label.setStyleSheet(f"color: {Theme.TEXT_PRIMARY};")
        controls_row.addSpacing(12)
        controls_row.addWidget(loop_label)
        self._loop_checkbox = ToggleSwitch()
        self._loop_checkbox.setToolTip(self.tr("Loop playback between the start and end markers (L)"))
        controls_row.addWidget(self._loop_checkbox)
        controls_row.addStretch()
        body.addLayout(controls_row)

        # Save row
        save_row = QHBoxLayout()
        save_label = QLabel(self.tr("Save Slice As:"))
        save_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        save_row.addWidget(save_label)
        self._filename_edit = QLineEdit()
        self._filename_edit.setMinimumWidth(200)
        self._filename_edit.setPlaceholderText(self.tr("output filename"))
        save_row.addWidget(self._filename_edit)
        self._format_combo = QComboBox()
        self._format_combo.addItems(["AIFF", "WAV", "FLAC", "MP3"])
        self._format_combo.setMinimumWidth(100)
        save_row.addWidget(self._format_combo)
        self._folder_btn = QPushButton()
        self._folder_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
        self._folder_btn.setFixedWidth(34)
        self._folder_btn.setToolTip(self.tr("Choose save folder"))
        save_row.addWidget(self._folder_btn)
        self._location_label = QLabel("")
        self._location_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 11px;")
        self._location_label.setMaximumWidth(250)
        save_row.addWidget(self._location_label)
        save_row.addStretch()
        self._slice_btn = QPushButton(self.tr("Slice"))
        self._slice_btn.setObjectName("primaryButton")
        self._slice_btn.setMinimumWidth(80)
        save_row.addWidget(self._slice_btn)
        body.addLayout(save_row)

        # Status
        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"color: {Theme.NEON_GREEN};")
        self._status_label.setVisible(False)
        body.addWidget(self._status_label)

        layout.addWidget(self._body)

        # Wiring
        self._range_slider.startValueChanged.connect(self._on_start_slider_changed)
        self._range_slider.endValueChanged.connect(self._on_end_slider_changed)
        self._seek_slider.sliderMoved.connect(self._on_seek)
        self._zoom_waveform.sliderMoved.connect(self._on_seek)
        self._start_edit.editingFinished.connect(self._on_start_edit_finished)
        self._end_edit.editingFinished.connect(self._on_end_edit_finished)
        self._length_edit.editingFinished.connect(self._on_length_edit_finished)
        self._mark_start_btn.clicked.connect(self.on_mark_start)
        self._mark_end_btn.clicked.connect(self.on_mark_end)
        self._goto_start_btn.clicked.connect(self.on_goto_start)
        self._loop_checkbox.toggled.connect(self._on_loop_toggled)
        self._slice_btn.clicked.connect(self._on_slice_clicked)
        self._folder_btn.clicked.connect(self._on_choose_folder)
        self._start_dec_btn.clicked.connect(lambda: self._nudge_start(-10))
        self._start_inc_btn.clicked.connect(lambda: self._nudge_start(10))
        self._end_dec_btn.clicked.connect(lambda: self._nudge_end(-10))
        self._end_inc_btn.clicked.connect(lambda: self._nudge_end(10))
        self._length_dec_btn.clicked.connect(lambda: self._nudge_length(-10))
        self._length_inc_btn.clicked.connect(lambda: self._nudge_length(10))

    @staticmethod
    def _nudge_button(style: str, text: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setStyleSheet(style)
        btn.setAutoRepeat(True)
        btn.setAutoRepeatInterval(50)
        btn.setAutoRepeatDelay(400)
        return btn

    def _set_body_visible(self, visible: bool) -> None:
        # The full waveform now lives outside the tray, so toggle it too.
        self._waveform.setVisible(visible)
        self._body.setVisible(visible)
        self._header_btn.setText(
            self.tr("▾  Waveform Loop Slicer") if visible else self.tr("▸  Waveform Loop Slicer")
        )

    # ------------------------------------------------------------ public API

    def is_expanded(self) -> bool:
        return self._expanded

    def time_row_min_width(self) -> int:
        """Width needed to show the time-info + Mark-buttons row pushed together.

        Used by the window sizer as the player's minimum width while the slicer
        is expanded, so those controls never clip.
        """
        return self._time_row_widget.minimumSizeHint().width()

    def set_track(self, file_path: str | None, duration_ms: int) -> None:
        """Point the section at the player's current track (or clear it)."""
        if file_path is None:
            # Track unloaded — collapse, free, disable.
            if self._expanded:
                self._header_btn.setChecked(False)  # triggers _on_toggle(False)
            self._file_path = None
            self._duration_ms = 0
            self._waveform_loaded = False
            self._header_btn.setEnabled(False)
            self.free_waveform()
            return

        self._header_btn.setEnabled(True)
        new_track = file_path != self._file_path
        self._file_path = file_path
        self._duration_ms = max(0, duration_ms)
        self._show_hours = self._duration_ms >= 3_600_000
        self._custom_save_dir = None
        self._status_label.setVisible(False)

        # A new track invalidates the old waveform — dump it (clear() also resets
        # the canvas duration/markers, so the range-reset below must come after).
        if new_track:
            self.free_waveform()

        # Reset markers to span the whole track.
        for w in (self._range_slider, self._zoom_waveform):
            w.setRange(0, self._duration_ms)
            w.setStartValue(0)
            w.setEndValue(self._duration_ms)
        self._range_slider.setSliderValue(0)
        self._start_edit.setText(format_time_ms(0, self._show_hours))
        self._end_edit.setText(format_time_ms(self._duration_ms, self._show_hours))
        self._update_length_display()

        # Default output filename + format from the source.
        stem = Path(file_path).stem
        self._filename_edit.setText(f"{stem}_slice")
        src_ext = Path(file_path).suffix.lower()
        ext_to_format = {v: k for k, v in FORMAT_EXTENSION.items()}
        ext_to_format[".aif"] = "AIFF"
        idx = self._format_combo.findText(ext_to_format.get(src_ext, "AIFF"))
        if idx >= 0:
            self._format_combo.setCurrentIndex(idx)
        self._location_label.setText("")

        # If we're open on a new track, build its waveform now; if closed, it
        # builds on the next expand.
        if new_track and self._expanded:
            self.request_waveform.emit()

    def set_waveform(self, coarse_min, coarse_max, detail_min, detail_max, bins_per_sec) -> None:
        """Install the min/max arrays the panel built from the cached PCM."""
        self._waveform.set_waveform(coarse_min, coarse_max)
        self._zoom_waveform.set_waveform(detail_min, detail_max, bins_per_sec)
        self._waveform_loaded = True

    def set_waveform_color(self, color: str) -> None:
        """Recolor the full-length waveform (the zoomed scrubber is unaffected)."""
        self._waveform.set_waveform_color(color)

    def set_position(self, position_ms: int) -> None:
        """Move the playhead (called on every engine position tick)."""
        self._position_label.setText(format_time_ms(position_ms, self._show_hours))
        if not self._seek_slider.isSliderDown():
            self._seek_slider.setSliderValue(position_ms)
        self._zoom_waveform.setPosition(position_ms)

    def set_playing(self, playing: bool) -> None:
        """Zoom scrubbing is paused-only — disable it during playback."""
        self._zoom_waveform.set_scrub_enabled(not playing)

    def free_waveform(self) -> None:
        """Dump the waveform arrays. Called on track change / removal, not on
        collapse — the waveform is kept while the same track stays loaded."""
        self._waveform.clear()
        self._zoom_waveform.clear()
        self._waveform_loaded = False

    # ----------------------------------------------------------- key actions

    def on_mark_start(self) -> None:
        if self._file_path is None:
            return
        pos = self._engine.current_ms()
        if pos >= self._range_slider.endValue():
            self._range_slider.setEndValue(self._duration_ms)
        self._range_slider.setStartValue(pos)

    def on_mark_end(self) -> None:
        if self._file_path is None:
            return
        pos = self._engine.current_ms()
        if pos <= self._range_slider.startValue():
            return
        self._range_slider.setEndValue(pos)

    def on_goto_start(self) -> None:
        self.seek_requested.emit(self._range_slider.startValue())

    def on_preview_start(self) -> None:
        """S held: seek to start marker and play."""
        if self._file_path is None:
            return
        self._engine.seek_ms(self._range_slider.startValue())
        self._engine.play()

    def on_preview_end(self) -> None:
        """S released: pause and return to the start marker."""
        if self._file_path is None:
            return
        self._engine.pause()
        self._engine.seek_ms(self._range_slider.startValue())

    def toggle_loop(self) -> None:
        """L pressed: flip the loop switch (drives _on_loop_toggled)."""
        if self._file_path is None:
            return
        self._loop_checkbox.toggle()

    # ------------------------------------------------------------- toggling

    def _on_toggle(self, checked: bool) -> None:
        self._expanded = checked
        self._set_body_visible(checked)
        if checked:
            self.expanded_changed.emit(True)
            # Build only if we don't already hold this track's waveform. Kept
            # across collapse/expand so reopening is instant.
            if not self._waveform_loaded and self._file_path is not None:
                self.request_waveform.emit()
        else:
            # Stop looping on collapse, but KEEP the waveform — it's dumped only
            # when the track changes (see set_track), not when the user hides it.
            if self._loop_checkbox.isChecked():
                self._loop_checkbox.setChecked(False)  # -> _on_loop_toggled(False)
            else:
                self._engine.set_loop_enabled(False)
            self.expanded_changed.emit(False)

    # --------------------------------------------------------- marker/length

    def _on_start_slider_changed(self, value: int) -> None:
        self._start_edit.setText(format_time_ms(value, self._show_hours))
        self._zoom_waveform.setStartValue(value)
        self._update_length_display()
        self._sync_loop_bounds()

    def _on_end_slider_changed(self, value: int) -> None:
        self._end_edit.setText(format_time_ms(value, self._show_hours))
        self._zoom_waveform.setEndValue(value)
        self._update_length_display()
        self._sync_loop_bounds()

    def _sync_loop_bounds(self) -> None:
        if self._loop_checkbox.isChecked():
            self._engine.set_loop_bounds(
                self._range_slider.startValue(), self._range_slider.endValue()
            )

    def _on_start_edit_finished(self) -> None:
        ms = parse_time_ms(self._start_edit.text())
        if ms is not None:
            self._range_slider.setStartValue(max(0, min(ms, self._duration_ms)))

    def _on_end_edit_finished(self) -> None:
        ms = parse_time_ms(self._end_edit.text())
        if ms is not None:
            self._range_slider.setEndValue(max(0, min(ms, self._duration_ms)))

    def _nudge_start(self, delta: int) -> None:
        val = max(0, min(self._range_slider.startValue() + delta, self._duration_ms))
        self._range_slider.setStartValue(val)

    def _nudge_end(self, delta: int) -> None:
        val = max(0, min(self._range_slider.endValue() + delta, self._duration_ms))
        self._range_slider.setEndValue(val)

    def _update_length_display(self) -> None:
        length_ms = self._range_slider.endValue() - self._range_slider.startValue()
        self._length_edit.setText(format_time_ms(length_ms, self._show_hours))

    def _on_length_edit_finished(self) -> None:
        length_ms = parse_time_ms(self._length_edit.text())
        if length_ms is None:
            return
        start = self._range_slider.startValue()
        length_ms = max(1, min(length_ms, self._duration_ms - start))
        self._range_slider.setEndValue(start + length_ms)

    def _nudge_length(self, delta: int) -> None:
        start = self._range_slider.startValue()
        current_length = self._range_slider.endValue() - start
        new_length = max(1, min(current_length + delta, self._duration_ms - start))
        self._range_slider.setEndValue(start + new_length)

    # ------------------------------------------------------------- transport

    def _on_seek(self, position: int) -> None:
        self.seek_requested.emit(position)

    def _on_loop_toggled(self, checked: bool) -> None:
        if checked:
            self._engine.set_loop_bounds(
                self._range_slider.startValue(), self._range_slider.endValue()
            )
        self._engine.set_loop_enabled(checked)

    # ------------------------------------------------------------- folder/save

    def _on_choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, self.tr("Choose Save Folder"))
        if folder:
            self._custom_save_dir = folder
            self._location_label.setText(folder)

    def _on_slice_clicked(self) -> None:
        if self._file_path is None:
            return
        start_ms = self._range_slider.startValue()
        end_ms = self._range_slider.endValue()
        try:
            output_path = export_slice(
                self._file_path,
                start_ms,
                end_ms,
                self._format_combo.currentText(),
                out_dir=self._custom_save_dir,
                filename=self._filename_edit.text(),
            )
            self._show_status(self.tr("Saved: {0}").format(output_path.name))
        except ValueError as e:
            self._show_status(str(e), error=True)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Slice failed: {e}")
            self._show_status(self.tr("Error: {0}").format(e), error=True)

    def _show_status(self, text: str, error: bool = False) -> None:
        color = Theme.ERROR if error else Theme.NEON_GREEN
        self._status_label.setStyleSheet(f"color: {color};")
        self._status_label.setText(text)
        self._status_label.setVisible(True)
