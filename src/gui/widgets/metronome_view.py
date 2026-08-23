"""The Keyboard panel's third view: a metronome with a BPM counter.

The sound is the clock. :class:`MetronomeEngine` schedules every click by
sample count inside the audio callback, which is the only way to hold a tempo
without drift (see that module's header for the numbers); this file owns the
controls, the stream, and a beat light that merely *polls* the engine's phase
on a coarse 33 ms timer.

The stream is a third concurrent ``sd.OutputStream`` alongside the keyboard's
synth and the Player's engine, which is established practice here — the
audition player documents the same thing. It is opened only when the user
presses Start, and it swallows its own failures the way ``_AudioEngine.start``
does, so a machine with no output device degrades to a silent-but-working
visual rather than an exception.
"""

from __future__ import annotations

import threading
import time

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..styles.theme import Theme
from .loop_player import output_stream_kwargs
from .metronome_engine import (
    BEATS_PER_BAR,
    MetronomeEngine,
    TapTempo,
    clamp_bpm,
)

SAMPLE_RATE = 44100
BLOCK_SIZE = 512

# How far a vertical drag moves the tempo. 4px per BPM was the spike's
# proposal and is about right by hand: a full box-height drag covers ~7 BPM.
_PIXELS_PER_BPM = 4.0
# Shift makes the same gesture two decimals fine, which is the only way to
# reach a value like 174.03 by dragging.
_FINE_STEP = 0.01

# The bend buttons lean the tempo by this much while held.
_BEND = 0.04

# The eye's refresh. Deliberately coarse: the clicks are sample-scheduled, so
# nothing about the sound depends on when this fires.
_VIS_INTERVAL_MS = 33


class BpmScrubBox(QLineEdit):
    """The tempo, to two decimals, draggable up and down.

    Two decimals appear nowhere else in the app (tags store an integer, every
    other display is one decimal), so this box owns its own formatting and
    changes none of those.

    A drag and a click share one gesture, so the press does not commit to
    either: it arms, and only movement past a threshold turns it into a scrub.
    A press released without moving falls through to normal text editing.
    """

    value_changed = Signal(float)

    def __init__(self, bpm: float = 120.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("metroBpmBox")
        self._value = clamp_bpm(bpm)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setToolTip(self.tr("Drag up or down to change the tempo"))
        self._press_y: int | None = None
        self._press_value = 0.0
        self._scrubbing = False
        self.editingFinished.connect(self._commit_text)
        self._render()

    # ── value ───────────────────────────────────────────────────────

    def value(self) -> float:
        return self._value

    def set_value(self, bpm: float) -> None:
        new = round(clamp_bpm(bpm), 2)
        if new == self._value:
            self._render()  # re-format a half-typed box back to two decimals
            return
        self._value = new
        self._render()
        self.value_changed.emit(new)

    def step(self, delta: float) -> None:
        """Nudge by a whole number, keeping the decimals: 120.37 -> 121.37."""
        self.set_value(self._value + delta)

    def _render(self) -> None:
        self.setText(f"{self._value:.2f}")

    def _commit_text(self) -> None:
        """Typed entry. Junk restores the last good value rather than
        clearing the box or leaving it unparseable."""
        try:
            self.set_value(float(self.text().replace(",", ".")))
        except ValueError:
            self._render()

    # ── the drag ────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_y = event.position().toPoint().y()
            self._press_value = self._value
            self._scrubbing = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._press_y is None:
            super().mouseMoveEvent(event)
            return
        moved = self._press_y - event.position().toPoint().y()
        if not self._scrubbing and abs(moved) < 3:
            super().mouseMoveEvent(event)
            return
        self._scrubbing = True
        steps = moved / _PIXELS_PER_BPM
        # Shift makes each step a hundredth instead of a whole BPM, which is
        # the only way to reach a value like 174.03 by dragging.
        delta = steps * _FINE_STEP if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else steps
        self.set_value(self._press_value + delta)

    def mouseReleaseEvent(self, event) -> None:
        was_scrubbing = self._scrubbing
        self._press_y = None
        self._scrubbing = False
        if was_scrubbing:
            # Swallow the release so the click doesn't also place a cursor in
            # the text the user was dragging.
            event.accept()
            return
        super().mouseReleaseEvent(event)


class BeatLight(QWidget):
    """Four dots, one per beat of the bar, lit as the bar goes round.

    A custom-paint widget of the same shape as the hex grid and the circle of
    fifths beside it, so the three views are siblings rather than one odd one.
    """

    _DOT = 14
    _GAP = 10

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._beat = 0
        self._phase = 0.0
        self._running = False
        self.setFixedSize(
            BEATS_PER_BAR * self._DOT + (BEATS_PER_BAR - 1) * self._GAP, self._DOT
        )

    def set_phase(self, beat: int, phase: float, running: bool) -> None:
        if (beat, running) == (self._beat, self._running) and abs(
            phase - self._phase
        ) < 0.01:
            return
        self._beat, self._phase, self._running = beat, phase, running
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(BEATS_PER_BAR):
            x = i * (self._DOT + self._GAP)
            lit = self._running and i == self._beat
            if lit:
                # Fades across the beat, so the eye reads the tempo and not
                # just the position — brightest at the click.
                fade = 1.0 - 0.65 * self._phase
                colour = QColor(Theme.NEON_YELLOW)
                colour.setAlphaF(max(0.35, fade))
            else:
                colour = QColor(Theme.BG_LIGHT)
            painter.setBrush(colour)
            painter.drawEllipse(x, 0, self._DOT, self._DOT)
        painter.end()


class MetronomeView(QWidget):
    """The whole view: tempo controls, transport, and the beat light."""

    def __init__(
        self, parent: QWidget | None = None, stream_factory=None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("metronomeView")
        self._engine = MetronomeEngine(120.0, sr=SAMPLE_RATE)
        self._tap = TapTempo()
        self._stream = None
        self._stream_lock = threading.Lock()
        # Injected in tests so nothing here ever opens a real device.
        self._stream_factory = stream_factory or self._open_stream
        self._setup_ui()
        self._vis_timer = QTimer(self)
        self._vis_timer.setInterval(_VIS_INTERVAL_MS)
        self._vis_timer.timeout.connect(self._tick)

    # ── layout ──────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(Theme.SPACING)

        tempo_row = QHBoxLayout()
        tempo_row.setSpacing(6)
        self._minus_btn = self._step_button("−", self.tr("One BPM slower"))
        self._minus_btn.clicked.connect(lambda: self._bpm_box.step(-1.0))
        tempo_row.addWidget(self._minus_btn)

        self._bpm_box = BpmScrubBox(120.0)
        self._bpm_box.setFixedSize(96, 30)
        self._bpm_box.value_changed.connect(self._engine.set_bpm)
        tempo_row.addWidget(self._bpm_box)

        self._plus_btn = self._step_button("+", self.tr("One BPM faster"))
        self._plus_btn.clicked.connect(lambda: self._bpm_box.step(1.0))
        tempo_row.addWidget(self._plus_btn)

        unit = QLabel("BPM")  # a unit, not prose — never translated
        unit.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 13px;")
        tempo_row.addWidget(unit)
        tempo_row.addSpacing(8)

        self._tap_btn = QPushButton(self.tr("Tap"))
        self._tap_btn.setObjectName("metroTapButton")
        self._tap_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tap_btn.setToolTip(self.tr("Tap along to set the tempo"))
        self._tap_btn.clicked.connect(self._on_tap)
        tempo_row.addWidget(self._tap_btn)
        tempo_row.addStretch(1)
        outer.addLayout(tempo_row)

        bend_row = QHBoxLayout()
        bend_row.setSpacing(6)
        self._slower_btn = self._bend_button(
            "‹", self.tr("Hold to lean the beat back")
        )
        self._faster_btn = self._bend_button(
            "›", self.tr("Hold to push the beat forward")
        )
        self._slower_btn.pressed.connect(lambda: self._engine.set_bend(1 - _BEND))
        self._faster_btn.pressed.connect(lambda: self._engine.set_bend(1 + _BEND))
        for button in (self._slower_btn, self._faster_btn):
            button.released.connect(self._engine.clear_bend)
        bend_row.addWidget(self._slower_btn)
        bend_row.addWidget(self._faster_btn)
        bend_row.addSpacing(12)

        self._start_btn = QPushButton(self.tr("Start"))
        self._start_btn.setObjectName("metroStartButton")
        self._start_btn.setCheckable(True)
        self._start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._start_btn.toggled.connect(self._on_toggled)
        bend_row.addWidget(self._start_btn)
        bend_row.addStretch(1)
        outer.addLayout(bend_row)

        self._light = BeatLight()
        outer.addWidget(self._light, alignment=Qt.AlignmentFlag.AlignLeft)
        outer.addStretch(1)

    def _step_button(self, glyph: str, tip: str) -> QPushButton:
        button = QPushButton(glyph)
        button.setObjectName("metroStepButton")
        button.setFixedSize(24, 24)
        button.setToolTip(tip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        # Hold to repeat, the slice panel's nudge-button precedent.
        button.setAutoRepeat(True)
        button.setAutoRepeatDelay(400)
        button.setAutoRepeatInterval(50)
        return button

    def _bend_button(self, glyph: str, tip: str) -> QPushButton:
        button = QPushButton(glyph)
        button.setObjectName("metroStepButton")
        button.setFixedSize(24, 24)
        button.setToolTip(tip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        # Deliberately NOT auto-repeat: this is a hold, and the pressed and
        # released signals are the whole gesture.
        return button

    # ── transport ───────────────────────────────────────────────────

    @property
    def running(self) -> bool:
        return self._stream is not None or self._vis_timer.isActive()

    def _on_toggled(self, on: bool) -> None:
        self._start_btn.setText(self.tr("Stop") if on else self.tr("Start"))
        if on:
            self.start()
        else:
            self.stop()

    def start(self) -> None:
        self._engine.reset()
        with self._stream_lock:
            if self._stream is None:
                self._stream = self._stream_factory()
        # The timer runs whether or not a device opened: on a machine with no
        # output the light should still keep time rather than looking broken.
        self._vis_timer.start()

    def stop(self) -> None:
        self._vis_timer.stop()
        with self._stream_lock:
            stream = self._stream
            self._stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:  # noqa: BLE001
                pass
        self._engine.clear_bend()
        self._light.set_phase(0, 0.0, False)
        if self._start_btn.isChecked():
            self._start_btn.setChecked(False)

    def set_volume(self, fraction: float) -> None:
        """Follow the Keyboard panel's own volume slider — one slider for the
        panel, not a second one nobody asked for."""
        self._engine.set_gain(fraction)

    # ── the ear and the eye ─────────────────────────────────────────

    def _open_stream(self):
        """Open the click stream, or return None if the machine has none.

        Swallows its exceptions exactly as ``_AudioEngine.start`` does — which
        is also what lets every headless test construct this view.
        """
        try:
            import sounddevice as sd
        except Exception:  # noqa: BLE001
            return None
        for extra in output_stream_kwargs():
            try:
                stream = sd.OutputStream(
                    samplerate=SAMPLE_RATE,
                    blocksize=BLOCK_SIZE,
                    channels=1,
                    dtype="float32",
                    callback=self._callback,
                    **extra,
                )
                stream.start()
                return stream
            except Exception:  # noqa: BLE001
                continue
        return None

    def _callback(self, outdata, frames, time_info, status) -> None:
        mono = outdata[:, 0]
        self._engine.render(mono)

    def _tick(self) -> None:
        if self._stream is None:
            # No device: advance the grid from the wall clock so the light
            # still keeps time. Only ever reached in the degraded case.
            self._engine.render(np.zeros(int(SAMPLE_RATE * _VIS_INTERVAL_MS / 1000)))
        beat, phase = self._engine.phase_snapshot()
        self._light.set_phase(beat, phase, True)

    # ── tap ─────────────────────────────────────────────────────────

    def _on_tap(self) -> None:
        estimate = self._tap.tap(time.perf_counter())
        if estimate is not None:
            # Shown rounded: 0.01 BPM at 128 is 36.6 microseconds of period,
            # which no human tap resolves. The decimals are for typed and
            # dragged input.
            self._bpm_box.set_value(round(estimate, 2))

    # ── lifecycle ───────────────────────────────────────────────────

    def hideEvent(self, event) -> None:
        # Switching away from the view — or off the panel — silences it. The
        # click is not background music.
        self.stop()
        super().hideEvent(event)
