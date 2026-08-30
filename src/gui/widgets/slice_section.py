"""Collapsible slice section for the Player panel.

Three lazily-built, collapsed-by-default views behind a row of header toggles:

- **Waveform** — the full-track waveform, which doubles as the seek control
  while it is shown (click or drag anywhere on it to move playback) and carries
  the draggable start/end markers.
- **Zoomed Wave** — the ±0.5 s scrubber around the playhead.
- **Loop Slicer** — every slice *control*: typed and nudged marker times,
  Mark-at-playhead, length, the A-B loop toggle, and slice export.

All three are independent: any one alone, any pair, all three (the full working
slicer), or none. Marker *dragging* lives on the full waveform, so the Slicer on
its own sets markers by Mark/nudge/typing. The zoomed canvas and the controls
share one dark tray — it is showing whenever either half is, so opening both
still reads as a single work area rather than two stacked boxes.

The zoomed wave was split out of the Loop Slicer because it is the half people
want while they are *listening*: with the controls closed, the zoomed view and
the metronome below it both fit on screen without scrolling.

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

from . import section_header
from .fitted_combo import FittedComboBox

from src.conversion.result import FORMAT_EXTENSION
from ..styles.theme import Theme
from .player_engine import PlayerEngine
from .slice_export import export_slice, format_time_ms, parse_time_ms
from .toggle_switch import ToggleSwitch
from .waveform_canvas import WaveformCanvas, ZoomedWaveformCanvas

logger = logging.getLogger(__name__)

# Gap between the header toggles. Wider than Theme.SPACING on purpose: accent
# words a normal gap apart read as one phrase rather than as separate buttons.
_HEADER_GAP = 24


class SliceSection(QWidget):
    """Collapsible slicer that operates on the player's currently-loaded track."""

    # Slice controls opened/closed — drives the window sizer's minimum width
    # (the time row is what needs it) and the panel's S/Q/E/L key routing.
    expanded_changed = Signal(bool)
    # Full-track waveform shown/hidden — the panel hides its own seek slider
    # while it is up, since the waveform is then the seek control.
    waveform_shown_changed = Signal(bool)
    # Zoomed scrubber shown/hidden — the panel reflows around it like the others.
    zoom_shown_changed = Signal(bool)
    # A canvas opened without a waveform in hand — panel supplies one.
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
        self._waveform_shown: bool = False
        self._zoom_shown: bool = False
        self._waveform_loaded: bool = False

        self._setup_ui()

        # Buttons/checkbox must not capture focus, so Space stays play/pause and
        # the panel's S/Q/E key routing isn't swallowed by a focused control.
        for btn in self.findChildren(QAbstractButton):
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._set_waveform_visible(False)
        self._set_zoom_visible(False)
        self._set_body_visible(False)
        for btn in self._header_buttons():
            btn.setEnabled(False)

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
            # The controls container is a bare QWidget, and the global
            # QWidget rule in app.qss.template would otherwise paint BG_DARK
            # over the tray it sits in.
            "#sliceControls { background: transparent; }"
        )

        # Header toggles — three independent views, side by side.
        self._waveform_btn = self._header_button(self.tr("Waveform"))
        self._waveform_btn.toggled.connect(self._on_waveform_toggle)
        self._zoom_btn = self._header_button(self.tr("Zoomed Wave"))
        self._zoom_btn.toggled.connect(self._on_zoom_toggle)
        self._slicer_btn = self._header_button(self.tr("Loop Slicer"))
        self._slicer_btn.toggled.connect(self._on_toggle)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(_HEADER_GAP)
        for btn in self._header_buttons():
            header_row.addWidget(btn)
        header_row.addStretch(1)
        layout.addLayout(header_row)

        # Full-track waveform — the seek control while shown. Parented here so
        # a bare SliceSection stays self-contained, but in the app the Player
        # reparents it into its pinned footer (see waveform_widget): the seek
        # control belongs at the bottom edge with the transport, where it
        # cannot scroll off screen.
        self._waveform = WaveformCanvas()
        layout.addWidget(self._waveform)
        # Aliases so the ported handlers read naturally.
        self._range_slider = self._waveform
        self._seek_slider = self._waveform

        # The dark tray, shared by the two views that live in it. It is showing
        # whenever either half is (see _sync_tray_visible), so the pair reads as
        # one work area instead of two boxes with a gap between them.
        self._body = QWidget()
        self._body.setObjectName("sliceTray")
        body = QVBoxLayout(self._body)
        body.setContentsMargins(10, 10, 10, 10)
        body.setSpacing(Theme.SPACING)

        # Zoomed scrubber — ±0.5 s detail, scrubbable while paused only.
        self._zoom_waveform = ZoomedWaveformCanvas()
        body.addWidget(self._zoom_waveform)

        # Everything the Loop Slicer toggle owns, in its own container so it can
        # hide independently of the zoomed canvas above it.
        self._controls = QWidget()
        self._controls.setObjectName("sliceControls")
        controls_layout = QVBoxLayout(self._controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        # Explicit: these rows used to be children of the tray's layout and
        # inherited its spacing; a layout handed to a widget falls back to the
        # Qt style default (6px) instead.
        controls_layout.setSpacing(Theme.SPACING)

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
        controls_layout.addWidget(self._time_row_widget)

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
        controls_layout.addLayout(length_row)

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
        controls_layout.addLayout(controls_row)

        # Save row
        save_row = QHBoxLayout()
        save_label = QLabel(self.tr("Save Slice As:"))
        save_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        save_row.addWidget(save_label)
        self._filename_edit = QLineEdit()
        self._filename_edit.setMinimumWidth(200)
        self._filename_edit.setPlaceholderText(self.tr("output filename"))
        save_row.addWidget(self._filename_edit)
        self._format_combo = FittedComboBox()
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
        controls_layout.addLayout(save_row)

        # Status
        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"color: {Theme.NEON_GREEN};")
        self._status_label.setVisible(False)
        controls_layout.addWidget(self._status_label)

        body.addWidget(self._controls)
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

    # Disclosure arrows. Kept out of the translatable strings — they are
    # punctuation, not words, and doubling every header string to carry them
    # doubles the translation work for nothing. The look itself lives in
    # section_header, shared with the metronome section stacked below this
    # one — three disclosure toggles that must read as one family.
    _ARROW_CLOSED = section_header.ARROW_CLOSED
    _ARROW_OPEN = section_header.ARROW_OPEN

    _header_button = staticmethod(section_header.header_button)
    _sync_header_arrow = staticmethod(section_header.sync_header_arrow)

    def _header_buttons(self) -> tuple[QPushButton, QPushButton, QPushButton]:
        """The three toggles, in the left-to-right order they are laid out."""
        return (self._waveform_btn, self._zoom_btn, self._slicer_btn)

    @staticmethod
    def _nudge_button(style: str, text: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setStyleSheet(style)
        btn.setAutoRepeat(True)
        btn.setAutoRepeatInterval(50)
        btn.setAutoRepeatDelay(400)
        return btn

    def _set_waveform_visible(self, visible: bool) -> None:
        """Show/hide the full-track waveform (its own view, not the tray's)."""
        self._waveform.setVisible(visible)
        self._sync_header_arrow(self._waveform_btn, visible)
        self._waveform_btn.setToolTip(
            self.tr("Hide the full-track waveform")
            if visible
            else self.tr("Show the full-track waveform — click it to move playback")
        )

    def _set_zoom_visible(self, visible: bool) -> None:
        """Show/hide the zoomed scrubber (the tray's upper half)."""
        self._zoom_waveform.setVisible(visible)
        self._sync_tray_visible()
        self._sync_header_arrow(self._zoom_btn, visible)
        self._zoom_btn.setToolTip(
            self.tr("Hide the zoomed waveform")
            if visible
            else self.tr("Show the zoomed waveform around the playhead")
        )

    def _set_body_visible(self, visible: bool) -> None:
        """Show/hide the slice controls (the tray's lower half)."""
        self._controls.setVisible(visible)
        self._sync_tray_visible()
        self._sync_header_arrow(self._slicer_btn, visible)
        self._slicer_btn.setToolTip(
            self.tr("Hide the slice controls")
            if visible
            else self.tr("Show the slice controls — markers, length, loop and export")
        )

    def _sync_tray_visible(self) -> None:
        """The tray carries whichever of its two halves are open, and hides
        with the last of them — an empty rounded box is not a view."""
        self._body.setVisible(self._zoom_shown or self._expanded)

    # ------------------------------------------------------------ public API

    def waveform_widget(self) -> WaveformCanvas:
        """The full-track canvas, for the Player to seat in its pinned footer.

        Hands over the *widget* only: visibility, marks, seeking and the lazy
        waveform build stay this section's job, and all of it keeps working
        wherever the canvas is parented.
        """
        return self._waveform

    def is_expanded(self) -> bool:
        """True while the slice controls are open — the S/Q/E/L keys' owner."""
        return self._expanded

    def is_waveform_shown(self) -> bool:
        """True while the full-track waveform is up — it is then the seek control."""
        return self._waveform_shown

    def is_zoom_shown(self) -> bool:
        """True while the zoomed scrubber is up."""
        return self._zoom_shown

    def is_open(self) -> bool:
        """True while any of the three views is up, i.e. the section wants room."""
        return self._expanded or self._waveform_shown or self._zoom_shown

    def needs_waveform(self) -> bool:
        """True while a view that *draws* the waveform is up.

        Narrower than :meth:`is_open` on purpose: the slice controls set their
        markers by Mark/nudge/typing, so opening them alone paints no samples
        and must not pay for a decode.
        """
        return self._waveform_shown or self._zoom_shown

    def first_screen_height(self) -> int:
        """Height that has to be on screen for an opened view to look opened.

        The header row plus the top of the topmost view showing *in the scroll
        content* — the tray's zoomed canvas, else the controls' time row.
        Everything below that (the length row, Save Slice As) is allowed to
        want scrolling; the first canvas is not, because a view you have to go
        looking for reads as a button that did nothing. The full waveform is
        not counted: it is drawn in the Player's pinned footer, which pays for
        it out of the viewport before this budget is even computed. The player
        reserves this out of its viewport before deciding how tall the
        playlist may be.
        """
        h = self._waveform_btn.height()
        if self._zoom_shown:
            # The zoomed canvas sits inside the tray, below its top margin.
            h += Theme.SPACING + self._body.layout().contentsMargins().top()
            h += self._zoom_waveform.minimumHeight()
        elif self._expanded:
            # Controls alone: the time row is what the tray opens with.
            h += Theme.SPACING + self._body.layout().contentsMargins().top()
            h += self._time_row_widget.sizeHint().height()
        return h

    def header_row_min_width(self) -> int:
        """Width the three disclosure toggles need side by side.

        Always showing, so the window sizer floors the Player's minimum with it
        whatever is expanded. Measured, never a constant: the labels are
        translated, and three of them are enough to overrun the 600px window
        minimum in French and Russian where two never came close. Each button is
        fixed-width from its own font metrics, so this is exact rather than a
        layout hint.
        """
        return sum(b.width() for b in self._header_buttons()) + 2 * _HEADER_GAP

    def time_row_min_width(self) -> int:
        """Width needed to show the time-info + Mark-buttons row pushed together.

        Used by the window sizer as the player's minimum width while the slicer
        is expanded, so those controls never clip.
        """
        return self._time_row_widget.minimumSizeHint().width()

    def set_track(self, file_path: str | None, duration_ms: int) -> None:
        """Point the section at the player's current track (or clear it)."""
        if file_path is None:
            # Track unloaded — collapse every view, free, disable.
            for btn in self._header_buttons():
                btn.setChecked(False)  # each fires its own toggle handler
            self._file_path = None
            self._duration_ms = 0
            self._waveform_loaded = False
            for btn in self._header_buttons():
                btn.setEnabled(False)
            self.free_waveform()
            return

        for btn in self._header_buttons():
            btn.setEnabled(True)
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

        # If a canvas is open on a new track, build its waveform now; otherwise
        # it builds on the next expand of one that draws samples.
        if new_track and self.needs_waveform():
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

    def _on_waveform_toggle(self, checked: bool) -> None:
        self._waveform_shown = checked
        self._set_waveform_visible(checked)
        self.waveform_shown_changed.emit(checked)
        if checked:
            self._request_waveform_if_needed()

    def _on_zoom_toggle(self, checked: bool) -> None:
        self._zoom_shown = checked
        self._set_zoom_visible(checked)
        self.zoom_shown_changed.emit(checked)
        if checked:
            self._request_waveform_if_needed()

    def _request_waveform_if_needed(self) -> None:
        """Build only if we don't already hold this track's waveform. Kept
        across collapse/expand so reopening is instant, and shared by both
        canvases — one build feeds the full waveform and the zoomed one alike."""
        if not self._waveform_loaded and self._file_path is not None:
            self.request_waveform.emit()

    def _on_toggle(self, checked: bool) -> None:
        # No waveform request here: the controls draw no samples of their own
        # (see needs_waveform), so opening them alone must not force a decode.
        self._expanded = checked
        self._set_body_visible(checked)
        if checked:
            self.expanded_changed.emit(True)
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
