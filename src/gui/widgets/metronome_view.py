"""The metronome: a BPM counter, a click train, and a beat light.

Hosted by :class:`~src.gui.widgets.metronome_section.MetronomeSection`, a
collapsible section in the Player panel. It was the Keyboard panel's third
view until 2026-08-26; the host supplies a place to sit, the two lifecycle
calls at the bottom, and — since the layout pass that followed the move — a
home on its own header row for the controls that are reached for while the
click runs. Two things are handed up there: Start
(:meth:`MetronomeView.start_button`) and the tempo row
(:meth:`MetronomeView.tempo_row`), the second of which is a container widget
purely because a layout cannot be reparented and a widget can. Everything
about what either *does* stays here; only where they sit is the host's.

That leaves the view itself one row — bend, level, click choice, beat light,
Global Click — so the whole metronome is two rows instead of four. The
condensing was asked for in those terms: this sits above the transport in a
panel whose playlist is fighting it for height, and two of the four rows were
mostly air.

The tempo row holds three ways of answering "what tempo?": type or drag one,
tap one, or take the loaded track's. The last is the Track button, and the
only thing in this file that knows anything about the player — through a
callable handed in at construction, asked at the moment it is wanted, so no
copy of that tempo is kept here to go stale.

Where Start stood, the click's level does: three loudnesses, cycled by one
:class:`ClickVolumeButton`. It is a button rather than the slider it replaced
because three answers do not need a hundred, and it paints its own bars
because a label is one colour and this one has to show which of its symbols
are lit.

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

Leaving silences it, and Global Click — on by default, and remembered in the
user's config — is the exception. That split is why there are two teardowns
rather than one: :meth:`MetronomeView.leave` is the
navigation path and honours the setting, :meth:`MetronomeView.stop` is the
unconditional one. ``KeyboardPanel`` mirrors the pair (``stop_audio`` /
``shutdown_audio``) because the synth has no such setting — a held note that
followed you off the panel would be a stuck note, not a feature — and because
closing the window is the one place no mode gets a vote.
"""

from __future__ import annotations

import threading
import time

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...utils.config import load_config, save_config
from ..styles.theme import Theme
from .loop_player import _BLOCK, UnderrunLog, output_stream_kwargs
from .metronome_engine import (
    BEATS_PER_BAR,
    SHARP,
    SOFT,
    MetronomeEngine,
    TapTempo,
    clamp_bpm,
)

SAMPLE_RATE = 44100
# The Player's roomy block (2048 ≈ 46 ms), NOT the keyboard's 512. The click
# moved here from the Keyboard panel wearing that panel's block size, whose
# 11.6 ms deadline exists for live key-press latency — a budget the waveform
# repaints alone can exceed while a track plays, and a Python callback that
# can't take the GIL in time underruns as a burst of static. A metronome
# doesn't need low latency: output latency is a constant offset on a
# free-running click (nothing syncs it to the track, tap tempo measures
# input timing, and the light polls the engine's own sample clock), so the
# headroom is free.
BLOCK_SIZE = _BLOCK

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

# The three levels the click sounds at, quiet to loud, as engine gains. Even
# 6 dB steps, and the middle one is the 50 the volume slider started at — so
# the default click is exactly as loud as it has always been and what changed
# is that there is now a way off it.
#
# Silence is deliberately NOT a fourth level. It is one of the three *click
# choices* on the row beside this, because "which click" and "how loud" are
# different questions and the answer "none" belongs to the first one: the beat
# light keeps time either way, so a silent metronome is a state of the click
# rather than the bottom of a scale.
CLICK_LEVELS = (0.25, 0.5, 1.0)
DEFAULT_CLICK_LEVEL = 1

# The Start button's own size. It sits up on the section's header row rather
# than in with the small controls, so it is deliberately the biggest thing in
# the metronome — this is the one button anyone reaches for mid-set.
# The height is restated in app.qss.template; see _build_start_button.
_START_HEIGHT = 40
_START_MIN_WIDTH = 140
# What the stylesheet's own padding costs, plus room to breathe. A width
# written as a constant is an English width, so the floor above is only a
# floor: "Start"/"Stop" are measured and the wider of the two wins.
_START_PADDING = 44

# The three settings the click row offers, left to right. Silence is one of
# them rather than a level, because that is the only thing the level was ever
# used for here: the light keeps time either way, so a silent metronome is a
# useful state and not a broken one.
SILENT = "silent"
CLICK_CHOICES = (SILENT, SOFT, SHARP)
DEFAULT_CLICK = SOFT


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


class ClickVolumeButton(QPushButton):
    """How loud the click is: three bars, filled with the accent up to the level.

    A cycling button rather than a slider because there are only three answers
    and none of them is a number anyone would want to name. Clicking walks
    quiet → medium → loud → quiet, so the whole control is one target the
    width of two glyphs, which is what let it fit where the Start button used
    to stand.

    The bars are painted rather than written for the reason a QSS-styled
    ``::down-arrow`` had to be: a ``QPushButton``'s label is one colour, so a
    *text* label could show three symbols but never show which of them are
    lit. Painting also keeps the accent following the palette for free — both
    colours are read at paint time, exactly as :class:`BeatLight` reads its own.
    """

    level_changed = Signal(int)

    _BAR_W = 8
    _BAR_GAP = 5
    _PAD_X = 6
    _BOTTOM = 2
    # Ascending, so the level reads at a glance from the silhouette and not
    # only from the colour — which is the half of it that survives a palette
    # whose accent is a muted gold.
    _BAR_HEIGHTS = (8, 14, 20)

    def __init__(
        self, level: int = DEFAULT_CLICK_LEVEL, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("metroVolumeButton")
        self._level = max(0, min(len(CLICK_LEVELS) - 1, int(level)))
        width = (
            len(self._BAR_HEIGHTS) * self._BAR_W
            + (len(self._BAR_HEIGHTS) - 1) * self._BAR_GAP
            + 2 * self._PAD_X
        )
        self.setFixedSize(width, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # One line and one string: the bars already say which level is on, so
        # the hover only has to say that the thing cycles.
        self.setToolTip(self.tr("Click volume — press to cycle quiet / medium / loud"))
        self.clicked.connect(self._cycle)

    # ── level ───────────────────────────────────────────────────────

    def level(self) -> int:
        """Index into :data:`CLICK_LEVELS`, 0 (quiet) to 2 (loud)."""
        return self._level

    def set_level(self, level: int) -> None:
        new = max(0, min(len(CLICK_LEVELS) - 1, int(level)))
        if new == self._level:
            return
        self._level = new
        self.update()
        self.level_changed.emit(new)

    def gain(self) -> float:
        return CLICK_LEVELS[self._level]

    def _cycle(self) -> None:
        self.set_level((self._level + 1) % len(CLICK_LEVELS))

    # ── paint ───────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        # The stylesheet still owns the box — background, radius, hover — and
        # only the bars are ours, so this draws on top of it rather than
        # instead of it.
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        lit = QColor(Theme.NEON_YELLOW)
        # Unlit is the secondary text colour half-faded rather than a token of
        # its own: it has to sit between the button's fill and the accent in
        # every one of the four palettes, and no single named colour does.
        dim = QColor(Theme.TEXT_SECONDARY)
        dim.setAlphaF(0.45)
        base = self.height() - self._BOTTOM
        for i, bar_h in enumerate(self._BAR_HEIGHTS):
            x = self._PAD_X + i * (self._BAR_W + self._BAR_GAP)
            painter.setBrush(lit if i <= self._level else dim)
            painter.drawRoundedRect(x, base - bar_h, self._BAR_W, bar_h, 2, 2)
        painter.end()


class MetronomeView(QWidget):
    """The whole view: tempo controls, transport, and the beat light."""

    def __init__(
        self, parent: QWidget | None = None, stream_factory=None, track_bpm=None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("metronomeView")
        # Where the Track button's tempo comes from: a callable answering the
        # loaded track's BPM, or None. A *source* rather than a value, so
        # there is one record of that fact and it lives in the player — a
        # copy kept here would go stale the moment a BPM cell was edited, and
        # would be a second thing to keep in step with the track that is
        # actually loaded. Absent (a bare view, or the suite) the button is
        # simply never enabled.
        self._track_bpm_source = track_bpm
        self._engine = MetronomeEngine(120.0, sr=SAMPLE_RATE)
        self._tap = TapTempo()
        self._underruns = UnderrunLog("Metronome click stream")
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
        self._start_btn = self._build_start_button()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(Theme.SPACING)

        # The tempo controls, in a container of their own so the host can put
        # them on its header row beside Start — the same arrangement Start
        # itself already has, and for the same reason: what they *do* is this
        # view's business, where they sit is the section's. It is a widget
        # rather than a layout because only a widget can be reparented, and
        # reparenting is the whole of "adopt this".
        self._tempo_row = QWidget(self)
        self._tempo_row.setObjectName("metronomeTempoRow")
        tempo_row = QHBoxLayout(self._tempo_row)
        tempo_row.setContentsMargins(0, 0, 0, 0)
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

        # On, the click keeps going once you leave — so a tempo can be held
        # while renaming or digging through a playlist. Off, leaving silences
        # it. On by default and remembered across launches: the click is easy
        # to find and stop, and a DJ setting a tempo wants it while they work.
        self._global_btn = QPushButton(self.tr("Global Click"))
        self._global_btn.setObjectName("metroGlobalButton")
        self._global_btn.setCheckable(True)
        self._global_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # Nothing reflects this control — it has one owner and no mirror — so
        # `toggled` is the whole story. A control shown in two places would
        # have to hang this off checkStateSet() instead, or a blockSignals'd
        # reflect would light up wearing the other state's sentence.
        self._global_btn.toggled.connect(self._on_global_toggled)
        # setChecked before the connect would leave the tooltip on the wrong
        # sentence, so the stored value is applied here and the sync runs off
        # the signal like any other change.
        self._global_btn.setChecked(load_config().metronome_global_click)
        self._sync_global_tooltip(self._global_btn.isChecked())

        # Take the tempo from whatever is loaded in the player, in Global
        # Click's old place beside Tap — the two ways of answering "what
        # tempo?" that are not typing one belong next to each other, and this
        # is the one you reach for while a track is up.
        self._track_btn = QPushButton(self.tr("Track"))
        self._track_btn.setObjectName("metroTapButton")  # Tap's twin, and styled as one
        self._track_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._track_btn.clicked.connect(self._on_take_track_tempo)
        tempo_row.addWidget(self._track_btn)
        self.refresh_track_bpm()

        bend_row = QHBoxLayout()
        bend_row.setSpacing(6)

        # How loud, where the transport used to stand. The two swapped places
        # on purpose: Start is the thing you hit mid-set and now sits big on
        # the section's own header row, while the level is set once and then
        # left, so it belongs down here with the other set-and-forget controls.
        self._volume_btn = ClickVolumeButton(DEFAULT_CLICK_LEVEL)
        self._volume_btn.level_changed.connect(lambda _: self._apply_click_choice())
        bend_row.addWidget(self._volume_btn)
        bend_row.addSpacing(12)

        # Which click, in the slider's old place. A level was never what
        # anyone reached for here — the useful answers are "not this one",
        # "the one that sits in a mix" and "the one that sits on top of it" —
        # so the row states those three and the level is a constant. The
        # panel's own slider, up beside the piano, still does not reach the
        # engine: one owner, and it is this row.
        self._click_group = QButtonGroup(self)
        self._click_group.setExclusive(True)
        self._click_buttons: dict[str, QPushButton] = {}
        for choice, glyph, tip in (
            (SILENT, "\u2298", self.tr("Silent — the light keeps time")),
            (SOFT, ")", self.tr("Standard click")),
            (SHARP, "))", self.tr("Higher-pitched click")),
        ):
            button = QPushButton(glyph)
            button.setObjectName("metroClickButton")
            button.setCheckable(True)
            button.setFixedSize(24, 24)
            button.setToolTip(tip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._click_group.addButton(button)
            self._click_buttons[choice] = button
            bend_row.addWidget(button)
        self._click_group.buttonToggled.connect(self._on_click_choice)
        self._click_buttons[DEFAULT_CLICK].setChecked(True)
        bend_row.addSpacing(16)

        # The beat light ends this row rather than owning one below it. It is
        # 14px of dots against a row of 24px buttons, so a row of its own was
        # mostly air — and it belongs beside the click controls anyway: it
        # shows the same beat they sound, and it is what a silent click leaves
        # you with.
        self._light = BeatLight()
        bend_row.addWidget(self._light, alignment=Qt.AlignmentFlag.AlignVCenter)
        bend_row.addSpacing(16)

        # Lean the beat back or push it forward while held — the row's only
        # controls that are *played* rather than set, so they sit next to the
        # light that shows what they are doing to the beat rather than up at
        # the head of the row where they started.
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
        bend_row.addSpacing(16)

        # Global Click ends this row rather than sitting up on the header one.
        # It is not a tempo control at all — it answers "does the click follow
        # me off this panel", which is set once and left, so it belongs down
        # here with the level and the click choice and not beside the two
        # buttons that set a tempo.
        bend_row.addWidget(self._global_btn)
        bend_row.addStretch(1)
        outer.addLayout(bend_row)
        outer.addStretch(1)

    def _build_start_button(self) -> QPushButton:
        """Start/Stop — built here, laid out by the host.

        One of the two things this view does not place (the tempo row is the
        other). It lives on
        :class:`~src.gui.widgets.metronome_section.MetronomeSection`'s header
        row, beside the word that opens the section, because that is where
        the hand goes for it; everything that decides what it *does*
        (the toggle handler, and the ``stop()`` that has to un-check it when
        the click ends by any other route) still lives with the transport it
        drives. So the button is parented to the view — never a stray
        top-level window if nobody adopts it — and ``start_button()`` is how
        the host takes it.
        """
        button = QPushButton(self.tr("Start"), self)
        button.setObjectName("metroStartButton")
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        # Set in Python, not QSS: a stylesheet font-size never reaches
        # widget.font(), and the width below is only honest if it measures
        # what actually paints.
        font = button.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        button.setFont(font)
        fm = QFontMetrics(font)
        # Both labels, because the wider one decides the width — a button that
        # resized between Start and Stop would shove the header row about, and
        # a QPushButton centres rather than elides, so a width short by a few
        # pixels cuts the label at both ends with nothing to show for it.
        widest = max(
            fm.horizontalAdvance(self.tr("Start")), fm.horizontalAdvance(self.tr("Stop"))
        )
        # The height is stated in app.qss.template as well, and has to be: a
        # stylesheet minimum REPLACES the one setFixedSize set, so the global
        # QPushButton rule's min-height reaches this call and 40 renders as 22
        # without the matching rule. This line is what the suite sees, which
        # runs with no stylesheet at all; a test keeps the two numbers equal.
        button.setFixedHeight(_START_HEIGHT)
        button.setFixedWidth(max(_START_MIN_WIDTH, widest + _START_PADDING))
        button.toggled.connect(self._on_toggled)
        return button

    def start_button(self) -> QPushButton:
        """The transport, for the host to put on its header row."""
        return self._start_btn

    def tempo_row(self) -> QWidget:
        """The tempo controls, for the host to put on its header row."""
        return self._tempo_row

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

    @property
    def global_click(self) -> bool:
        """Whether the click survives leaving the view."""
        return self._global_btn.isChecked()

    def _on_global_toggled(self, on: bool) -> None:
        self._sync_global_tooltip(on)
        # Re-loaded first so this never clobbers a field another panel wrote
        # since startup — the player_edit_locked pattern.
        cfg = load_config()
        if cfg.metronome_global_click != on:
            cfg.metronome_global_click = on
            save_config(cfg)

    def _sync_global_tooltip(self, on: bool) -> None:
        # A toggle's tooltip says what the NEXT click will do, in both
        # directions — the label alone cannot convey which way it is pointing.
        self._global_btn.setToolTip(
            self.tr("Stop the click when you leave this view")
            if on
            else self.tr("Keep the click going when you leave this view")
        )

    def leave(self) -> None:
        """Navigating away — to another view, or off the Keyboard panel.

        The one place Global Click means anything. Everything that really
        ends the session — closing the window — calls :meth:`stop` instead,
        because a mode the user set is not a licence to outlive the app.
        """
        if self.global_click:
            return
        self.stop()

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

    def _on_click_choice(self, button: QPushButton, checked: bool) -> None:
        """Apply whichever of the three is now on.

        The group is exclusive, so every switch arrives twice — once for the
        button going off and once for the one coming on. Both halves would
        apply the *same* choice, because Qt has already checked the incoming
        button by the time the outgoing one emits, so this guard buys one
        redundant call rather than correctness. Stated because the obvious
        comment to write here — "acting on the first would set the gain from
        the choice just left" — is not true, and a mutation test refused to
        fail against it.
        """
        if not checked:
            return
        self._apply_click_choice()

    def _apply_click_choice(self) -> None:
        """Push both halves of the answer — which click, and how loud — at the
        engine. One method for the two rows because a gain is only meaningful
        alongside a voice, and either control changing has to re-state both."""
        choice = self.click_choice
        # Silence is a gain of zero rather than a stopped stream: the grid
        # has to keep running, because the beat light is reading it.
        self._engine.set_gain(0.0 if choice == SILENT else self._volume_btn.gain())
        if choice != SILENT:
            self._engine.set_voice(choice)

    @property
    def click_choice(self) -> str:
        """Which of :data:`CLICK_CHOICES` is on — session-only, like the
        Keyboard panel's and the Player's own volume settings."""
        for choice, button in self._click_buttons.items():
            if button.isChecked():
                return choice
        return SILENT

    def set_click_choice(self, choice: str) -> None:
        self._click_buttons[choice].setChecked(True)

    @property
    def volume(self) -> float:
        """The click's level, 0.0-1.0 — three values now, not a hundred, and
        zero when the click choice is Silent."""
        return 0.0 if self.click_choice == SILENT else self._volume_btn.gain()

    @property
    def click_level(self) -> int:
        """Index into :data:`CLICK_LEVELS` — session-only, like the click
        choice beside it and the Player's own volume."""
        return self._volume_btn.level()

    def set_click_level(self, level: int) -> None:
        self._volume_btn.set_level(level)

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

    def _callback(self, outdata, frames, time_info, status) -> None:  # noqa: ARG002
        self._underruns.count(status)
        mono = outdata[:, 0]
        self._engine.render(mono)

    def _tick(self) -> None:
        # The vis timer keeps running through a Global Click leave (leave()
        # returns before stop()), so this reports for as long as the click
        # sounds, whichever panel is showing.
        self._underruns.report()
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

    # ── the loaded track's tempo ────────────────────────────────────

    def track_bpm(self) -> float | None:
        """The loaded track's BPM, asked for fresh every time.

        Never cached. The player already holds this fact, and the tag can
        change under it — an inline edit of the BPM cell rewrites the entry
        without reloading the track — so a copy here would be a second record
        of one fact, which is the shape that rots.
        """
        if self._track_bpm_source is None:
            return None
        bpm = self._track_bpm_source()
        # A tag can say 0, or something unparsable that arrived as None.
        return bpm if bpm and bpm > 0 else None

    def refresh_track_bpm(self) -> None:
        """Re-read the source and say whether there is a tempo to take.

        Cheap and idempotent, so the host may call it from as many triggers
        as it likes: what must not be duplicated is the *record*, not the
        refresh.
        """
        bpm = self.track_bpm()
        self._track_btn.setEnabled(bpm is not None)
        self._track_btn.setToolTip(
            self.tr("Use the loaded track's tempo — {0} BPM").format(f"{bpm:.2f}")
            if bpm is not None
            else self.tr("No track with a BPM tag is loaded")
        )

    def _on_take_track_tempo(self) -> None:
        # Read again rather than trusting the enabled state: the button's
        # state is only as fresh as the last refresh, and the value is what
        # actually matters here.
        bpm = self.track_bpm()
        if bpm is not None:
            # Straight into the box, which drives the engine — so a running
            # click changes tempo under the hand rather than needing a stop.
            self._bpm_box.set_value(bpm)

    # ── lifecycle ───────────────────────────────────────────────────

    def hideEvent(self, event) -> None:
        # Switching away from the view — or off the panel — silences it,
        # unless the user has said otherwise. The click is not background
        # music by default; Global Click is how it becomes that.
        self.leave()
        super().hideEvent(event)
