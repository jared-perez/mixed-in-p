"""Spectrum panel — drop a single audio file and view a Spek-style
linear-frequency spectrogram (time x, frequency y, magnitude as colour).

Decoding + FFT + colour mapping run on a background thread
(``SpectrumWorker``); this widget only paints the finished image plus axes
and a dB colour legend.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QRect, Qt, QThread, Signal, Slot
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
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from src.metadata.tags import read_metadata
from ..styles.theme import BackgroundOverlay, Theme, panel_header_row
from ..workers.spectrum_worker import DYNAMIC_RANGE_DB, _COLORMAP, colorize, SpectrumWorker
from ..workers.thread_keeper import keep_alive
from .drop_zone import AUDIO_EXTENSIONS

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
        step = _nice_step(dur_s, 8)
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


class SpectrumPanel(QWidget):
    """Panel that renders a Spek-style spectrogram for one dropped audio file."""

    files_dropped = Signal(list)
    # Emitted (with the dynamic-range dB value) when the user releases the
    # sensitivity slider, so MainWindow can persist it.
    sensitivity_changed = Signal(float)

    # Sensitivity slider maps 0..100 -> dynamic range in dB. Higher slider
    # value = LARGER range = more quiet detail lifted into bright colours
    # (more sensitive). Right = brighter.
    _SLIDER_MAX = 100
    _DR_MIN = 60.0   # least sensitive (darker, more contrast) — slider far left
    _DR_MAX = 150.0  # most sensitive (brightest) — slider far right

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._file_path: str | None = None

        # Cached analysis result so changing sensitivity recolorizes instantly
        # (no FFT rerun): oriented dB matrix + its peak, plus axis metadata.
        self._db = None
        self._peak: float = 0.0
        self._sr: int = 0
        self._duration_ms: int = 0
        self._dynamic_range: float = DYNAMIC_RANGE_DB

        # Single-flighted background renderer: at most one worker runs; a
        # request that arrives mid-render is stashed and started when the
        # running one finishes.
        self._spec_thread: QThread | None = None
        self._spec_worker: SpectrumWorker | None = None
        self._spec_loading: bool = False
        self._spec_current_path: str | None = None
        self._spec_pending_path: str | None = None
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
        desc = QLabel(
            self.tr(
                "Drop a single audio file to see its acoustic spectrum. Frequency runs "
                "bottom (0 Hz) to top (Nyquist); time runs left to right; colour shows "
                "magnitude. Handy for spotting lossy-encode low-pass cutoffs."
            )
        )
        desc.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        layout.addLayout(panel_header_row(title, desc))

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

        # Filename is pinned at its full width (Minimum policy so it never
        # compresses). The secondary props live in their own collapsible
        # container that shrinks to zero first, so a long filename is never
        # squeezed or covered — the props just clip off the right when narrow.
        file_caption = QLabel(f"{self.tr('File')}:")
        file_caption.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-weight: bold;")
        file_caption.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        info_layout.addWidget(file_caption)
        self._info_labels["file"] = QLabel("")
        self._info_labels["file"].setStyleSheet(f"color: {Theme.TEXT_PRIMARY};")
        self._info_labels["file"].setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred
        )
        info_layout.addWidget(self._info_labels["file"])
        info_layout.addSpacing(20)

        self._secondary_info = QWidget()
        # Ignored width: the outer layout may give it less than its contents
        # need, so it yields the space to the filename and clips its own props.
        self._secondary_info.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        secondary_layout = QHBoxLayout(self._secondary_info)
        secondary_layout.setContentsMargins(0, 0, 0, 0)
        secondary_layout.setSpacing(6)
        _add_info_pair(secondary_layout, "samplerate", self.tr("Sample rate"))
        _add_info_pair(secondary_layout, "key", self.tr("Key"))
        _add_info_pair(secondary_layout, "bpm", self.tr("BPM"))
        secondary_layout.addStretch(1)

        # Stretch the secondary container into the space to the right of the
        # filename: it shows the props when wide and clips them off the right
        # edge when narrow, without ever encroaching on the filename.
        info_layout.addWidget(self._secondary_info, 1)
        self._info_widget.setVisible(False)
        layout.addWidget(self._info_widget)

        # Status line for in-progress / error feedback.
        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        self._status_label.setVisible(False)
        layout.addWidget(self._status_label)

        # Sensitivity control: brighten/darken the colour mapping live.
        sens_row = QHBoxLayout()
        sens_row.setContentsMargins(0, 0, 0, 0)
        sens_row.setSpacing(8)
        sens_caption = QLabel(self.tr("Sensitivity:"))
        sens_caption.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-weight: bold;")
        sens_row.addWidget(sens_caption)
        self._sens_slider = QSlider(Qt.Orientation.Horizontal)
        self._sens_slider.setRange(0, self._SLIDER_MAX)
        self._sens_slider.setFixedWidth(220)
        self._sens_slider.setValue(self._dr_to_slider(self._dynamic_range))
        self._sens_slider.valueChanged.connect(self._on_sens_value_changed)
        self._sens_slider.sliderReleased.connect(self._on_sens_released)
        sens_row.addWidget(self._sens_slider)
        self._sens_value_label = QLabel(
            self.tr("{0} dB range").format(int(self._dynamic_range))
        )
        self._sens_value_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        sens_row.addWidget(self._sens_value_label)
        sens_row.addStretch(1)
        layout.addLayout(sens_row)

        # The spectrogram view fills the remaining space.
        self._view = SpectrogramView()
        layout.addWidget(self._view, 1)

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

    def dropEvent(self, event: QDropEvent) -> None:
        if not event.mimeData().hasUrls():
            return
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
                event.acceptProposedAction()
                # Load directly — don't emit files_dropped, or the sidebar
                # route would _load_file a second time.
                self._load_file(str(path.resolve()))
                return

    # ---------------------------------------------------------- public API

    def _load_file(self, path: str) -> None:
        """Load a single audio file and render its spectrogram."""
        self._file_path = path

        self._info_labels["file"].setText(Path(path).name)
        try:
            meta = read_metadata(path)
            self._info_labels["bpm"].setText(f"{meta.bpm:.1f}" if meta.bpm else "")
            self._info_labels["key"].setText(meta.key or "")
        except Exception:
            for key in ("bpm", "key"):
                self._info_labels[key].setText("")
        self._info_labels["samplerate"].setText("")
        self._info_widget.setVisible(True)

        # Drop the previous file's cached data so a slider move mid-decode
        # doesn't recolorize a stale spectrogram.
        self._db = None
        self._view.clear(self.tr("Analyzing…"))
        self._status_label.setText(self.tr("Analyzing…"))
        self._status_label.setVisible(True)
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
        """Re-map the cached dB matrix to colours at the current sensitivity."""
        if self._db is None:
            return
        image = colorize(self._db, self._peak, self._dynamic_range)
        self._view.set_spectrogram(image, self._sr, self._duration_ms, self._dynamic_range)

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
            self._spec_pending_path = path
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

    @Slot(object, float, int, int)
    def _on_render_ready(self, db, peak, sr, duration_ms) -> None:
        # Discard stale results if a different file was loaded mid-render.
        if self._spec_current_path != self._file_path:
            return
        self._db = db
        self._peak = peak
        self._sr = sr
        self._duration_ms = duration_ms
        self._apply_colorize()
        self._info_labels["samplerate"].setText(f"{sr/1000:.1f} kHz" if sr else "")
        self._status_label.setVisible(False)

    @Slot(str)
    def _on_render_error(self, msg: str) -> None:
        logger.warning(f"Spectrum render failed: {msg}")
        if self._spec_current_path == self._file_path:
            self._view.clear(self.tr("Could not analyze this file."))
            self._status_label.setText(self.tr("Error: {0}").format(msg))
            self._status_label.setVisible(True)

    @Slot()
    def _on_render_thread_finished(self) -> None:
        self._spec_loading = False
        self._spec_current_path = None
        next_path = self._spec_pending_path
        self._spec_pending_path = None
        if next_path is not None:
            self._start_render(next_path)
