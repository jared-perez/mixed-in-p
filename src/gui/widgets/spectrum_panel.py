"""Spectrum panel — drop an audio file and view a Spek-style
linear-frequency spectrogram (time x, frequency y, magnitude as colour);
with Split Screen on, two files side by side.

Decoding + FFT + colour mapping run on a background thread
(``SpectrumWorker``); this widget only paints the finished image plus axes
and a dB colour legend.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QRect, QSize, Qt, QThread, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QImage,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.metadata.tags import read_metadata
from ..styles.theme import BackgroundOverlay, Theme, panel_header_row
from ..workers.spectrum_worker import DYNAMIC_RANGE_DB, _COLORMAP, colorize, SpectrumWorker
from ..workers.thread_keeper import keep_alive, wait_for_threads
from .elided_label import ElidedLabel
from .drop_zone import AUDIO_EXTENSIONS
from .wheel_guard import NoWheelSlider

logger = logging.getLogger(__name__)


def _nice_step(span: float, target_ticks: int) -> float:
    """Return a human-friendly tick step (~target_ticks across *span*)."""
    if span <= 0:
        return 1.0
    raw = span / max(1, target_ticks)
    import math

    mag = 10 ** math.floor(math.log10(raw))
    for mult in (1, 2, 2.5, 5, 10):
        if raw <= mult * mag:
            return mult * mag
    return 10 * mag


def _format_clock(seconds: float) -> str:
    """Format seconds as ``m:ss`` (or ``h:mm:ss`` past an hour)."""
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


class SpectrogramView(QWidget):
    """Paints a spectrogram pixmap with frequency / time axes and a dB legend."""

    # Margins around the plotted image, in device-independent pixels.
    _M_LEFT = 56
    _M_BOTTOM = 28
    _M_TOP = 12
    _M_RIGHT = 76
    _LEGEND_W = 14

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._sr: int = 0
        self._duration_ms: int = 0
        self._dynamic_range: float = DYNAMIC_RANGE_DB
        self._placeholder = self.tr("Drop a single audio file to view its spectrum")
        self.setMinimumHeight(350)
        # Build the legend gradient pixmap once (256 rows tall, loud at top).
        self._legend = self._build_legend_pixmap()

    @staticmethod
    def _build_legend_pixmap() -> QPixmap:
        img = QImage(1, 256, QImage.Format.Format_RGB888)
        for i in range(256):
            r, g, b = (int(c) for c in _COLORMAP[255 - i])  # row 0 = loudest
            img.setPixelColor(0, i, QColor(r, g, b))
        return QPixmap.fromImage(img)

    def set_spectrogram(
        self, image: QImage, sr: int, duration_ms: int, dynamic_range: float
    ) -> None:
        self._pixmap = QPixmap.fromImage(image)
        self._sr = sr
        self._duration_ms = duration_ms
        self._dynamic_range = dynamic_range
        self.update()

    def clear(self, placeholder: str | None = None) -> None:
        self._pixmap = None
        if placeholder is not None:
            self._placeholder = placeholder
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ARG002
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.fillRect(self.rect(), QColor(Theme.BG_DARK))

        plot = QRect(
            self._M_LEFT,
            self._M_TOP,
            max(1, self.width() - self._M_LEFT - self._M_RIGHT),
            max(1, self.height() - self._M_TOP - self._M_BOTTOM),
        )

        if self._pixmap is None:
            p.setPen(QColor(Theme.TEXT_SECONDARY))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._placeholder)
            p.end()
            return

        # Spectrogram image.
        p.drawPixmap(plot, self._pixmap)
        p.setPen(QColor(Theme.CHROME_DARK))
        p.drawRect(plot)

        self._draw_freq_axis(p, plot)
        self._draw_time_axis(p, plot)
        self._draw_legend(p, plot)
        p.end()

    # ----------------------------------------------------------------- axes

    def _draw_freq_axis(self, p: QPainter, plot: QRect) -> None:
        nyquist = self._sr / 2 if self._sr else 0
        if nyquist <= 0:
            return
        font = QFont()
        font.setPixelSize(10)
        p.setFont(font)
        step = _nice_step(nyquist, 6)
        p.setPen(QColor(Theme.TEXT_SECONDARY))
        f = 0.0
        while f <= nyquist + 1:
            y = plot.bottom() - (f / nyquist) * plot.height()
            label = f"{f/1000:.0f}k" if f >= 1000 else f"{int(f)}"
            p.setPen(QColor(Theme.TEXT_SECONDARY))
            p.drawText(QRect(0, int(y) - 8, self._M_LEFT - 6, 16),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)
            p.setPen(QColor(Theme.CHROME_DARK))
            p.drawLine(self._M_LEFT - 4, int(y), self._M_LEFT, int(y))
            f += step

    def _draw_time_axis(self, p: QPainter, plot: QRect) -> None:
        dur_s = self._duration_ms / 1000 if self._duration_ms else 0
        if dur_s <= 0:
            return
        font = QFont()
        font.setPixelSize(10)
        p.setFont(font)
        # ~70px per label: a Split Screen half is too narrow for a fixed 8.
        step = _nice_step(dur_s, max(2, min(8, plot.width() // 70)))
        t = 0.0
        while t <= dur_s + 1e-6:
            x = plot.left() + (t / dur_s) * plot.width()
            p.setPen(QColor(Theme.CHROME_DARK))
            p.drawLine(int(x), plot.bottom(), int(x), plot.bottom() + 4)
            p.setPen(QColor(Theme.TEXT_SECONDARY))
            p.drawText(QRect(int(x) - 30, plot.bottom() + 5, 60, 16),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                       _format_clock(t))
            t += step

    def _draw_legend(self, p: QPainter, plot: QRect) -> None:
        bar = QRect(plot.right() + 18, plot.top(), self._LEGEND_W, plot.height())
        p.drawPixmap(bar, self._legend)
        p.setPen(QColor(Theme.CHROME_DARK))
        p.drawRect(bar)
        font = QFont()
        font.setPixelSize(10)
        p.setFont(font)
        p.setPen(QColor(Theme.TEXT_SECONDARY))
        dr = self._dynamic_range
        # Top = 0 dB (relative to peak), bottom = -dynamic_range.
        for frac, label in ((0.0, "0 dB"), (0.5, f"-{int(dr/2)}"),
                            (1.0, f"-{int(dr)}")):
            y = bar.top() + frac * bar.height()
            p.drawText(QRect(bar.right() + 4, int(y) - 8, self._M_RIGHT - self._LEGEND_W - 22, 16),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)


class _WholeOrHidden(QWidget):
    """Shows its ``inner`` widget at full size, or not at all.

    The info props (Sample rate / Key / BPM) yield their room to the filename.
    Laid out directly, a short row squeezed each label down to a letter or two
    ("S 4 K B") — half a pane in Split Screen is short enough to do it. Here
    the inner row keeps its own size hint and is hidden when that won't fit.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("spectrumPaneInfo")
        # Ignored width: the pane's layout may give it less than its contents
        # need, so it yields the space to the filename.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.inner = QWidget(self)
        self.inner.setObjectName("spectrumPaneInfo")

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return self.inner.sizeHint()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        hint = self.inner.sizeHint()
        self.inner.setGeometry(0, 0, max(hint.width(), self.width()), self.height())
        self.inner.setVisible(self.width() >= hint.width())


class _SpectrumPane(QWidget):
    """One result box: a file's info row, status line and spectrogram.

    The panel holds two of these (left and right) so Split Screen can compare
    files; with the split off only the left one shows. A pane only holds and
    paints its file's state — loading, rendering and the sensitivity belong to
    the panel, so both panes share one worker and one slider.

    Its strings use the ``SpectrumPanel`` context: they lived on the panel
    before the split, and a new context would drop every one of them to
    English in eleven languages.
    """

    # An audio file was dropped onto this pane (absolute path).
    file_dropped = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("spectrumPane")
        self.file_path: str | None = None
        # Cached analysis result so a sensitivity change recolorizes without
        # rerunning the FFT: oriented dB matrix + its peak, plus axis metadata.
        self.db = None
        self.peak: float = 0.0
        self.sr: int = 0
        self.duration_ms: int = 0
        self.error: str | None = None
        # The dynamic range the view was last coloured at, so a pane that was
        # hidden while the slider moved is recoloured once, when it is shown.
        self._colorized_dr: float | None = None

        self.setAcceptDrops(True)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Theme.SPACING)

        # Track info row (hidden until a file loads). Ignored width policy so the
        # row never pins the panel's minimum width — it just clips when narrow.
        self._info_widget = QWidget()
        self._info_widget.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        info_layout = QHBoxLayout(self._info_widget)
        info_layout.setContentsMargins(0, 8, 0, 8)
        info_layout.setSpacing(6)
        self._info_labels: dict[str, QLabel] = {}

        def _add_info_pair(target: QHBoxLayout, key: str, label_text: str) -> None:
            caption = QLabel(f"{label_text}:")
            caption.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-weight: bold;")
            target.addWidget(caption)
            value = QLabel("")
            value.setStyleSheet(f"color: {Theme.TEXT_PRIMARY};")
            self._info_labels[key] = value
            target.addWidget(value)
            target.addSpacing(20)

        # The filename takes its full width first; the secondary props live in
        # their own container that shrinks to zero before it, so they clip off
        # the right when narrow. Only past that does the filename elide — two
        # long names side by side must not pin the window's minimum width.
        file_word = QCoreApplication.translate("SpectrumPanel", "File")
        file_caption = QLabel(f"{file_word}:")
        file_caption.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-weight: bold;")
        file_caption.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        info_layout.addWidget(file_caption)
        file_label = ElidedLabel("")
        file_label.setStyleSheet(f"color: {Theme.TEXT_PRIMARY};")
        file_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        file_label.setMinimumWidth(60)
        self._info_labels["file"] = file_label
        info_layout.addWidget(file_label)
        info_layout.addSpacing(20)

        self._secondary_info = _WholeOrHidden()
        secondary_layout = QHBoxLayout(self._secondary_info.inner)
        secondary_layout.setContentsMargins(0, 0, 0, 0)
        secondary_layout.setSpacing(6)
        _add_info_pair(
            secondary_layout, "samplerate",
            QCoreApplication.translate("SpectrumPanel", "Sample rate"),
        )
        _add_info_pair(
            secondary_layout, "key", QCoreApplication.translate("SpectrumPanel", "Key")
        )
        _add_info_pair(
            secondary_layout, "bpm", QCoreApplication.translate("SpectrumPanel", "BPM")
        )
        secondary_layout.addStretch(1)
        info_layout.addWidget(self._secondary_info, 1)
        self._info_widget.setVisible(False)
        layout.addWidget(self._info_widget)

        # Status line for in-progress / error feedback.
        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        self._status_label.setVisible(False)
        layout.addWidget(self._status_label)

        self.view = SpectrogramView()
        layout.addWidget(self.view, 1)

    # ------------------------------------------------------------ state

    def begin(self, path: str) -> None:
        """Show *path* as loading; the panel starts (or reuses) its render."""
        self.file_path = path
        self.db = None
        self.error = None
        self._colorized_dr = None

        name = Path(path).name
        self._info_labels["file"].setText(name)
        self._info_labels["file"].setToolTip(name)
        try:
            meta = read_metadata(path)
            self._info_labels["bpm"].setText(f"{meta.bpm:.1f}" if meta.bpm else "")
            self._info_labels["key"].setText(meta.key or "")
        except Exception:
            for key in ("bpm", "key"):
                self._info_labels[key].setText("")
        self._info_labels["samplerate"].setText("")
        self._info_widget.setVisible(True)

        analyzing = QCoreApplication.translate("SpectrumPanel", "Analyzing…")
        self.view.clear(analyzing)
        self._status_label.setText(analyzing)
        self._status_label.setVisible(True)

    @property
    def awaiting(self) -> bool:
        """True while this pane wants a render result it doesn't have yet."""
        return self.file_path is not None and self.db is None and self.error is None

    def set_result(self, db, peak: float, sr: int, duration_ms: int, dr: float) -> None:
        self.db = db
        self.peak = peak
        self.sr = sr
        self.duration_ms = duration_ms
        self._colorized_dr = None
        self._info_labels["samplerate"].setText(f"{sr/1000:.1f} kHz" if sr else "")
        self._status_label.setVisible(False)
        self.recolor(dr)

    def copy_result_from(self, other: "_SpectrumPane", dr: float) -> None:
        """Take *other*'s finished render of the same file (no FFT rerun)."""
        self.set_result(other.db, other.peak, other.sr, other.duration_ms, dr)

    def set_error(self, msg: str) -> None:
        self.error = msg
        self.view.clear(QCoreApplication.translate("SpectrumPanel", "Could not analyze this file."))
        self._status_label.setText(
            QCoreApplication.translate("SpectrumPanel", "Error: {0}").format(msg)
        )
        self._status_label.setVisible(True)

    def show_empty(self, placeholder: str) -> None:
        """Set the text an empty pane shows (a loaded pane is left alone)."""
        if self.file_path is None:
            self.view.clear(placeholder)

    def recolor(self, dr: float) -> None:
        """Map the cached dB matrix to colours at *dr*, unless already there.

        A hidden pane is skipped: the slider may tick dozens of times while the
        right pane is folded away, and it is recoloured when it is shown.
        """
        if self.db is None or self.isHidden() or self._colorized_dr == dr:
            return
        image = colorize(self.db, self.peak, dr)
        self.view.set_spectrogram(image, self.sr, self.duration_ms, dr)
        self._colorized_dr = dr

    # ------------------------------------------------------------ drops

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if _audio_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = _audio_paths(event.mimeData())
        if not paths:
            return
        event.acceptProposedAction()
        self.file_dropped.emit(paths[0])


def _audio_paths(mime) -> list[str]:
    """The audio files in a drop, resolved, in the order they were dragged."""
    if not mime.hasUrls():
        return []
    paths = []
    for url in mime.urls():
        path = Path(url.toLocalFile())
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
            paths.append(str(path.resolve()))
    return paths


class SpectrumPanel(QWidget):
    """Panel that renders Spek-style spectrograms: one file, or two side by
    side with Split Screen on."""

    files_dropped = Signal(list)
    # Emitted (with the dynamic-range dB value) when the user releases the
    # sensitivity slider, so MainWindow can persist it.
    sensitivity_changed = Signal(float)
    # Emitted when the user flips Split Screen, so MainWindow can persist it.
    split_toggled = Signal(bool)

    # Sensitivity slider maps 0..100 -> dynamic range in dB. Higher slider
    # value = LARGER range = more quiet detail lifted into bright colours
    # (more sensitive). Right = brighter.
    _SLIDER_MAX = 100
    _DR_MIN = 60.0   # least sensitive (darker, more contrast) — slider far left
    _DR_MAX = 150.0  # most sensitive (brightest) — slider far right

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dynamic_range: float = DYNAMIC_RANGE_DB
        self._split: bool = False

        # Single-flighted background renderer: at most one worker runs; paths
        # requested mid-render queue up and start when the running one finishes.
        # Results go to whichever pane still wants that path, not to the pane
        # that asked — a general drop moves the left pane's file to the right,
        # render in flight and all.
        self._spec_thread: QThread | None = None
        self._spec_worker: SpectrumWorker | None = None
        self._spec_loading: bool = False
        self._spec_current_path: str | None = None
        self._spec_queue: list[str] = []
        # Strong refs to finished-but-not-yet-deleted threads/workers, held until
        # their C++ objects are destroyed so a queued deleteLater can't fire into
        # a garbage-collected wrapper (SIGBUS). See thread_keeper.
        self._thread_keep: list = []

        self.setAcceptDrops(True)
        self._setup_ui()
        self._bg_overlay = BackgroundOverlay("bg_slice.png", self)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._bg_overlay.setGeometry(self.rect())

    # ------------------------------------------------------------------ UI

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Theme.PADDING, Theme.PADDING, Theme.PADDING, Theme.PADDING)
        layout.setSpacing(Theme.SPACING)

        # Title + description on one line (description flows to the title's right)
        title = QLabel(self.tr("Spectrum"))
        title.setObjectName("sectionTitle")
        title.setStyleSheet(f"font-size: 24px; color: {Theme.NEON_YELLOW};")
        desc = ElidedLabel(
            self.tr(
                "Drop a single audio file to see its acoustic spectrum. Frequency runs "
                "bottom (0 Hz) to top (Nyquist); time runs left to right; colour shows "
                "magnitude. Handy for spotting lossy-encode low-pass cutoffs."
            )
        )
        desc.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        layout.addLayout(panel_header_row(title, desc))

        # Sensitivity control: brighten/darken the colour mapping live, in both
        # panes at once. Split Screen sits at the far right of the same row.
        sens_row = QHBoxLayout()
        sens_row.setContentsMargins(0, 0, 0, 0)
        sens_row.setSpacing(8)
        sens_caption = QLabel(self.tr("Sensitivity:"))
        sens_caption.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-weight: bold;")
        sens_row.addWidget(sens_caption)
        self._sens_slider = NoWheelSlider(Qt.Orientation.Horizontal)
        self._sens_slider.setRange(0, self._SLIDER_MAX)
        # 220px when there is room, but it gives way before the window's
        # minimum does: with Split Screen on the same row, a fixed 220 raised
        # the minimum by 35-150px across the languages.
        self._sens_slider.setMinimumWidth(60)
        self._sens_slider.setMaximumWidth(220)
        self._sens_slider.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._sens_slider.setValue(self._dr_to_slider(self._dynamic_range))
        self._sens_slider.valueChanged.connect(self._on_sens_value_changed)
        self._sens_slider.sliderReleased.connect(self._on_sens_released)
        # Stretch 1, like the spacer after it, so the slider takes its 220
        # before the spacer takes the rest.
        sens_row.addWidget(self._sens_slider, 1)
        self._sens_value_label = QLabel(
            self.tr("{0} dB range").format(int(self._dynamic_range))
        )
        self._sens_value_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        sens_row.addWidget(self._sens_value_label)
        sens_row.addStretch(1)

        self._split_btn = QPushButton(self.tr("Split Screen"))
        self._split_btn.setObjectName("splitToggle")
        self._split_btn.setCheckable(True)
        self._split_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._split_btn.clicked.connect(self._on_split_clicked)
        sens_row.addWidget(self._split_btn)

        # The sensitivity row used to sit below the info row; with two panes
        # each carries its own info, so the shared control goes above them.
        layout.addLayout(sens_row)

        # Left and right result boxes. The right one is hidden with the split
        # off but keeps the previous file, so turning the split on shows it.
        self._panes_row = QHBoxLayout()
        self._panes_row.setContentsMargins(0, 0, 0, 0)
        self._panes_row.setSpacing(Theme.PADDING)
        self._left = _SpectrumPane()
        self._right = _SpectrumPane()
        for pane in (self._left, self._right):
            pane.file_dropped.connect(self._on_pane_drop)
            self._panes_row.addWidget(pane, 1)
        layout.addLayout(self._panes_row, 1)

        self._apply_split()

    def _sync_split_tooltip(self) -> None:
        """Say what the next click does."""
        self._split_btn.setToolTip(
            self.tr("Show one spectrum")
            if self._split
            else self.tr("Compare two files side by side")
        )

    def _apply_split(self) -> None:
        """Show or fold the right pane to match ``_split``."""
        self._right.setVisible(self._split)
        self._right.show_empty(self.tr("Drop a second audio file here to compare"))
        self._sync_split_tooltip()
        # Recolour on show: the slider may have moved while it was hidden.
        self._right.recolor(self._dynamic_range)

    @property
    def split(self) -> bool:
        return self._split

    def _on_split_clicked(self, checked: bool) -> None:
        self._split = checked
        self._apply_split()
        self.split_toggled.emit(checked)

    def set_split(self, enabled: bool) -> None:
        """Set Split Screen from outside (e.g. persisted config at startup)."""
        self._split = enabled
        self._split_btn.blockSignals(True)
        self._split_btn.setChecked(enabled)
        self._split_btn.blockSignals(False)
        self._apply_split()

    # ---------------------------------------------------------- drop handling

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if _audio_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = _audio_paths(event.mimeData())
        if not paths:
            return
        event.acceptProposedAction()
        # Load directly — don't emit files_dropped, or the sidebar
        # route would load a second time.
        self.load_files(paths)

    def _on_pane_drop(self, path: str) -> None:
        pane = self.sender()
        # With the split on, a drop onto a box fills that box. With it off the
        # one visible box is the whole panel, so it is an ordinary drop.
        if self._split and isinstance(pane, _SpectrumPane):
            self._load_into(pane, path)
        else:
            self._load_file(path)

    # ---------------------------------------------------------- public API

    def load_files(self, paths: list[str]) -> None:
        """A drop onto the panel or its sidebar button: two files fill both
        boxes (first on the left); one file is handed to ``_load_file``."""
        if not paths:
            return
        if len(paths) >= 2:
            self._load_into(self._left, paths[0])
            self._load_into(self._right, paths[1])
        else:
            self._load_file(paths[0])

    def _load_file(self, path: str) -> None:
        """Show *path* on the left and move the previous file to the right.

        The move happens with the split off too (into the hidden box), so
        turning the split on compares the last two files straight away.
        """
        if path != self._left.file_path and self._left.file_path is not None:
            # Swap the pane widgets rather than copying state across: the left
            # one's render may still be in flight, and results are matched to
            # panes by path, so it lands in the right box by itself.
            self._left, self._right = self._right, self._left
            self._panes_row.removeWidget(self._left)
            self._panes_row.removeWidget(self._right)
            self._panes_row.addWidget(self._left, 1)
            self._panes_row.addWidget(self._right, 1)
            self._left.setVisible(True)
            self._apply_split()
        self._load_into(self._left, path)

    def _load_into(self, pane: _SpectrumPane, path: str) -> None:
        pane.begin(path)
        other = self._right if pane is self._left else self._left
        if other.file_path == path and other.db is not None:
            pane.copy_result_from(other, self._dynamic_range)
            return
        self._start_render(path)

    # ---------------------------------------------------------- sensitivity

    def _slider_to_dr(self, value: int) -> float:
        frac = value / self._SLIDER_MAX
        return self._DR_MIN + frac * (self._DR_MAX - self._DR_MIN)

    def _dr_to_slider(self, dr: float) -> int:
        dr = max(self._DR_MIN, min(self._DR_MAX, dr))
        frac = (dr - self._DR_MIN) / (self._DR_MAX - self._DR_MIN)
        return int(round(frac * self._SLIDER_MAX))

    def _apply_colorize(self) -> None:
        """Re-map both panes' cached dB matrices at the current sensitivity."""
        for pane in (self._left, self._right):
            pane.recolor(self._dynamic_range)

    def _on_sens_value_changed(self, value: int) -> None:
        self._dynamic_range = self._slider_to_dr(value)
        self._sens_value_label.setText(
            self.tr("{0} dB range").format(int(self._dynamic_range))
        )
        self._apply_colorize()

    def _on_sens_released(self) -> None:
        # Persist only on release (not on every tick).
        self.sensitivity_changed.emit(self._dynamic_range)

    def set_dynamic_range(self, dr: float) -> None:
        """Set the sensitivity from outside (e.g. persisted config at startup)."""
        self._dynamic_range = max(self._DR_MIN, min(self._DR_MAX, dr))
        self._sens_slider.blockSignals(True)
        self._sens_slider.setValue(self._dr_to_slider(self._dynamic_range))
        self._sens_slider.blockSignals(False)
        self._sens_value_label.setText(
            self.tr("{0} dB range").format(int(self._dynamic_range))
        )
        self._apply_colorize()

    # ---------------------------------------------------------- renderer

    def _start_render(self, path: str) -> None:
        """Spawn a worker to decode + render off the UI thread (single-flighted)."""
        if self._spec_loading:
            if path != self._spec_current_path and path not in self._spec_queue:
                self._spec_queue.append(path)
            return
        self._spec_loading = True
        self._spec_current_path = path
        thread = QThread()
        worker = SpectrumWorker(path)
        worker.moveToThread(thread)
        self._spec_thread = thread
        self._spec_worker = worker
        # Keep the wrappers alive until C++ destroys them — reassigning the attrs
        # on the next render won't, as the prior deleteLater may still be queued
        # (rapid re-renders → SIGBUS in the deferred-delete destructor).
        keep_alive(self._thread_keep, thread, worker)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_render_ready)
        worker.error.connect(self._on_render_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_render_thread_finished)
        thread.start()

    def _panes_awaiting(self, path: str | None) -> list[_SpectrumPane]:
        return [p for p in (self._left, self._right) if p.awaiting and p.file_path == path]

    @Slot(object, float, int, int)
    def _on_render_ready(self, db, peak, sr, duration_ms) -> None:
        # A pane that moved on to another file mid-render no longer matches,
        # so a stale result is simply dropped.
        for pane in self._panes_awaiting(self._spec_current_path):
            pane.set_result(db, peak, sr, duration_ms, self._dynamic_range)

    @Slot(str)
    def _on_render_error(self, msg: str) -> None:
        logger.warning(f"Spectrum render failed: {msg}")
        for pane in self._panes_awaiting(self._spec_current_path):
            pane.set_error(msg)

    @Slot()
    def _on_render_thread_finished(self) -> None:
        self._spec_loading = False
        self._spec_current_path = None
        # Skip queued paths no pane wants any more (a box refilled mid-wait).
        while self._spec_queue:
            next_path = self._spec_queue.pop(0)
            if self._panes_awaiting(next_path):
                self._start_render(next_path)
                return

    def shutdown_workers(self) -> None:
        """Wait for a render thread still reading a file. See PlayerPanel."""
        wait_for_threads(self._thread_keep)

    def closeEvent(self, event) -> None:
        self.shutdown_workers()
        super().closeEvent(event)
