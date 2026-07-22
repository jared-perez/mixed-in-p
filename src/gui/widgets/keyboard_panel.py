"""Keyboard panel — 3-octave piano with key-code labels and chord playback."""

from __future__ import annotations

import threading

import numpy as np
import sounddevice as sd

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from src.analysis.keycode import KEYCODE_TO_KEY, render_key

from ..styles.theme import Theme, panel_header_row
from .circle_of_fifths_grid import CircleOfFifthsGrid
from .hex_key_grid import HexKeyGrid
from .key_info_box import KeyInfoBox
from .linear_key_strip import LinearKeyStrip
from .loop_player import output_stream_kwargs

# ---------------------------------------------------------------------------
# Audio constants
# ---------------------------------------------------------------------------
SAMPLE_RATE = 44100
BLOCK_SIZE = 512
CHANNELS = 1

ATTACK = 0.01
DECAY = 0.05
SUSTAIN_LEVEL = 0.7
RELEASE = 0.15
HARMONICS = [1.0, 0.5, 0.25]

# ---------------------------------------------------------------------------
# Piano key dimensions
# ---------------------------------------------------------------------------
WHITE_KEY_WIDTH = 40
WHITE_KEY_HEIGHT = 180
BLACK_KEY_WIDTH = 26
BLACK_KEY_HEIGHT = 110

# Piano key colours are intentionally theme-independent: a piano keyboard is
# white-and-black in every theme. The on-key label colours (drawn in
# paintEvent: dark on white keys, light on black keys) and the pressed-key blue
# follow these fixed key colours, not the palette's text/accent tokens.
WHITE_KEY_COLOR = QColor("#FFFFFF")
WHITE_KEY_PRESSED = QColor("#A0C4FF")
BLACK_KEY_COLOR = QColor("#000000")
BLACK_KEY_PRESSED = QColor("#2244AA")
KEY_OUTLINE = QColor("#333333")

DEFAULT_OCTAVE = 3
DEFAULT_VOLUME = 0.5

# ---------------------------------------------------------------------------
# Note / Key Code mappings
# ---------------------------------------------------------------------------
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _midi_to_freq(midi_note: int) -> float:
    return 440.0 * (2.0 ** ((midi_note - 69) / 12.0))


def _note_to_midi(name: str, octave: int) -> int:
    return NOTE_NAMES.index(name) + (octave + 1) * 12


KEYCODE_MAJOR = {
    "C": "8B", "C#": "3B", "D": "10B", "D#": "5B", "E": "12B",
    "F": "7B", "F#": "2B", "G": "9B", "G#": "4B", "A": "11B",
    "A#": "6B", "B": "1B",
}

KEYCODE_MINOR = {
    "C": "5A", "C#": "12A", "D": "7A", "D#": "2A", "E": "9A",
    "F": "4A", "F#": "11A", "G": "6A", "G#": "1A", "A": "8A",
    "A#": "3A", "B": "10A",
}

# Reverse lookups: key code -> note name (root of the chord)
INV_KEYCODE_MAJOR = {v: k for k, v in KEYCODE_MAJOR.items()}
INV_KEYCODE_MINOR = {v: k for k, v in KEYCODE_MINOR.items()}

MAJOR_CHORD_INTERVALS = [0, 4, 7]
MINOR_CHORD_INTERVALS = [0, 3, 7]

# QWERTY → (note_name, octave_offset)
QWERTY_MAP = {
    Qt.Key.Key_A: ("C", 0),
    Qt.Key.Key_S: ("D", 0),
    Qt.Key.Key_D: ("E", 0),
    Qt.Key.Key_F: ("F", 0),
    Qt.Key.Key_G: ("G", 0),
    Qt.Key.Key_H: ("A", 0),
    Qt.Key.Key_J: ("B", 0),
    Qt.Key.Key_K: ("C", 1),
    Qt.Key.Key_L: ("D", 1),
    Qt.Key.Key_Semicolon: ("E", 1),
    Qt.Key.Key_W: ("C#", 0),
    Qt.Key.Key_E: ("D#", 0),
    Qt.Key.Key_T: ("F#", 0),
    Qt.Key.Key_Y: ("G#", 0),
    Qt.Key.Key_U: ("A#", 0),
    Qt.Key.Key_O: ("C#", 1),
    Qt.Key.Key_P: ("D#", 1),
}

# Piano key layout sequences
WHITE_KEYS_SEQUENCE: list[tuple[str, int]] = []
for _oct in range(3):
    for _note in ["C", "D", "E", "F", "G", "A", "B"]:
        WHITE_KEYS_SEQUENCE.append((_note, _oct))
WHITE_KEYS_SEQUENCE.append(("C", 3))
WHITE_KEYS_SEQUENCE.append(("D", 3))

# Total piano width — used to line the header indicator and volume control up
# with the keyboard's right edge instead of the panel's right edge.
_PIANO_WIDTH = len(WHITE_KEYS_SEQUENCE) * WHITE_KEY_WIDTH

BLACK_KEYS_SEQUENCE: list[tuple[int, str, int]] = []
for _oct in range(3):
    _base = _oct * 7
    BLACK_KEYS_SEQUENCE.append((_base + 0, "C#", _oct))
    BLACK_KEYS_SEQUENCE.append((_base + 1, "D#", _oct))
    BLACK_KEYS_SEQUENCE.append((_base + 3, "F#", _oct))
    BLACK_KEYS_SEQUENCE.append((_base + 4, "G#", _oct))
    BLACK_KEYS_SEQUENCE.append((_base + 5, "A#", _oct))
BLACK_KEYS_SEQUENCE.append((21, "C#", 3))


# ---------------------------------------------------------------------------
# Audio engine (sounddevice callback)
# ---------------------------------------------------------------------------
class _Voice:
    __slots__ = ("freq", "phase", "envelope", "stage", "active")

    def __init__(self, freq: float) -> None:
        self.freq = freq
        self.phase = 0.0
        self.envelope = 0.0
        self.stage = "attack"
        self.active = True

    def restart(self) -> None:
        self.stage = "attack"
        self.active = True


class _AudioEngine:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._voices: dict[float, _Voice] = {}
        self._volume = DEFAULT_VOLUME
        self._stream: sd.OutputStream | None = None
        self._attack_rate = 1.0 / max(1, int(ATTACK * SAMPLE_RATE))
        self._decay_rate = (1.0 - SUSTAIN_LEVEL) / max(1, int(DECAY * SAMPLE_RATE))
        self._release_rate = SUSTAIN_LEVEL / max(1, int(RELEASE * SAMPLE_RATE))
        total = sum(HARMONICS)
        self._harmonics = [h / total for h in HARMONICS]

    def start(self) -> None:
        if self._stream is not None:
            return
        # Prefer the low-latency host API (WASAPI on Windows) so notes sound
        # promptly instead of ~190 ms late on the default MME host API. Falls
        # back to PortAudio's default device if that fails. See
        # output_stream_kwargs() — no-op off Windows.
        for extra in output_stream_kwargs():
            try:
                self._stream = sd.OutputStream(
                    samplerate=SAMPLE_RATE,
                    blocksize=BLOCK_SIZE,
                    channels=CHANNELS,
                    dtype="float32",
                    callback=self._callback,
                    **extra,
                )
                self._stream.start()
                return
            except Exception:  # noqa: BLE001
                self._stream = None

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        with self._lock:
            self._voices.clear()

    @property
    def volume(self) -> float:
        return self._volume

    @volume.setter
    def volume(self, val: float) -> None:
        self._volume = max(0.0, min(1.0, val))

    def note_on(self, freq: float) -> None:
        with self._lock:
            if freq in self._voices:
                self._voices[freq].restart()
            else:
                self._voices[freq] = _Voice(freq)

    def note_off(self, freq: float) -> None:
        with self._lock:
            voice = self._voices.get(freq)
            if voice and voice.stage != "off":
                voice.stage = "release"

    def _callback(self, outdata, frames, time_info, status) -> None:  # noqa: ARG002
        with self._lock:
            voices = list(self._voices.values())

        if not voices:
            outdata[:] = 0.0
            return

        buf = np.zeros(frames, dtype=np.float32)
        finished: list[float] = []

        for voice in voices:
            if not voice.active:
                finished.append(voice.freq)
                continue

            signal = np.zeros(frames, dtype=np.float64)
            for i, amp in enumerate(self._harmonics):
                harmonic_num = i + 1
                phase_inc = voice.freq * harmonic_num / SAMPLE_RATE
                phases = voice.phase * harmonic_num + np.cumsum(
                    np.full(frames, phase_inc)
                )
                signal += amp * np.sin(2.0 * np.pi * phases)

            voice.phase += voice.freq * frames / SAMPLE_RATE
            voice.phase %= 1.0

            env = np.empty(frames, dtype=np.float64)
            level = voice.envelope
            stage = voice.stage

            for s in range(frames):
                if stage == "attack":
                    level += self._attack_rate
                    if level >= 1.0:
                        level = 1.0
                        stage = "decay"
                elif stage == "decay":
                    level -= self._decay_rate
                    if level <= SUSTAIN_LEVEL:
                        level = SUSTAIN_LEVEL
                        stage = "sustain"
                elif stage == "release":
                    level -= self._release_rate
                    if level <= 0.0:
                        level = 0.0
                        stage = "off"
                env[s] = level

            voice.envelope = level
            voice.stage = stage

            if stage == "off":
                voice.active = False
                finished.append(voice.freq)

            buf += (signal * env).astype(np.float32)

        if finished:
            with self._lock:
                for freq in finished:
                    v = self._voices.get(freq)
                    if v and not v.active:
                        del self._voices[freq]

        outdata[:, 0] = buf * self._volume


# ---------------------------------------------------------------------------
# Piano canvas (custom-painted keyboard)
# ---------------------------------------------------------------------------
class _PianoCanvas(QWidget):
    """Custom-painted 3-octave piano keyboard with key-code labels."""

    # Emitted when a chord starts / stops because of mouse or keyboard input
    # on the piano itself. Strip-driven plays (via play_from_strip) do NOT
    # emit these — the strip manages its own highlight directly.
    chord_started = Signal(str)  # key code, e.g. "5A"
    chord_ended = Signal(str)

    def __init__(self, engine: _AudioEngine, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._octave = DEFAULT_OCTAVE
        self._chord_mode = "minor"
        self._notation = "keycode"
        self._active_chords: dict[tuple, list[float]] = {}
        self._pressed_keys: set[int] = set()
        self._pressed_white: set[int] = set()  # indices of pressed white keys
        self._pressed_black: set[int] = set()  # indices of pressed black keys
        # (visual_idx, key_id, is_black, keycode_at_press)
        self._mouse_info: tuple[int, tuple, bool, str] | None = None
        # Track key code per held QWERTY key, so chord_mode flips
        # mid-press don't corrupt the released code.
        self._kb_codes: dict[int, str] = {}

        n_white = len(WHITE_KEYS_SEQUENCE)
        self.setFixedSize(n_white * WHITE_KEY_WIDTH, WHITE_KEY_HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    @property
    def chord_mode(self) -> str:
        return self._chord_mode

    @chord_mode.setter
    def chord_mode(self, mode: str) -> None:
        self._chord_mode = mode
        self.update()

    def shift_octave(self, delta: int) -> None:
        """Shift the base octave, clamped to the playable range (0-6)."""
        self._octave = max(0, min(6, self._octave + delta))

    def set_notation(self, notation: str) -> None:
        """Set the key notation used for the labels painted on the keys."""
        self._notation = notation
        self.update()

    def _label(self, code: str) -> str:
        """Render a key-code as the key label in the current notation."""
        return render_key(KEYCODE_TO_KEY.get(code, code), code, self._notation)

    # --- Painting ---

    def paintEvent(self, event) -> None:  # noqa: ARG002
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        keycode = KEYCODE_MAJOR if self._chord_mode == "major" else KEYCODE_MINOR
        outline_pen = QPen(KEY_OUTLINE, 1)

        # White keys
        white_font = QFont()
        white_font.setFamilies(["Helvetica Neue", "Arial"])
        white_font.setPointSize(9)
        white_font.setBold(True)
        p.setFont(white_font)
        for i, (note, oct_off) in enumerate(WHITE_KEYS_SEQUENCE):
            x0 = i * WHITE_KEY_WIDTH
            color = WHITE_KEY_PRESSED if i in self._pressed_white else WHITE_KEY_COLOR
            p.fillRect(x0, 0, WHITE_KEY_WIDTH, WHITE_KEY_HEIGHT, color)
            p.setPen(outline_pen)
            p.drawRect(x0, 0, WHITE_KEY_WIDTH, WHITE_KEY_HEIGHT)
            p.setPen(QColor("#333333"))
            p.drawText(
                x0, WHITE_KEY_HEIGHT - 30, WHITE_KEY_WIDTH, 20,
                Qt.AlignmentFlag.AlignCenter, self._label(keycode[note]),
            )

        # Black keys
        black_font = QFont()
        black_font.setFamilies(["Helvetica Neue", "Arial"])
        black_font.setPointSize(8)
        black_font.setBold(True)
        p.setFont(black_font)
        for bi, (white_idx, note, oct_off) in enumerate(BLACK_KEYS_SEQUENCE):
            x_center = (white_idx + 1) * WHITE_KEY_WIDTH
            x0 = x_center - BLACK_KEY_WIDTH // 2
            color = BLACK_KEY_PRESSED if bi in self._pressed_black else BLACK_KEY_COLOR
            p.fillRect(x0, 0, BLACK_KEY_WIDTH, BLACK_KEY_HEIGHT, color)
            p.setPen(outline_pen)
            p.drawRect(x0, 0, BLACK_KEY_WIDTH, BLACK_KEY_HEIGHT)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(
                x0, BLACK_KEY_HEIGHT - 26, BLACK_KEY_WIDTH, 20,
                Qt.AlignmentFlag.AlignCenter, self._label(keycode[note]),
            )
        p.end()

    # --- Chord helpers ---

    def _keycode(self, note_name: str) -> str:
        mapping = KEYCODE_MAJOR if self._chord_mode == "major" else KEYCODE_MINOR
        return mapping[note_name]

    def _get_intervals(self) -> list[int]:
        return MAJOR_CHORD_INTERVALS if self._chord_mode == "major" else MINOR_CHORD_INTERVALS

    def _chord_freqs(self, note_name: str, oct_offset: int) -> list[float]:
        root_midi = _note_to_midi(note_name, self._octave + oct_offset)
        return [_midi_to_freq(root_midi + iv) for iv in self._get_intervals()]

    def _play_chord(self, note_name: str, oct_offset: int, key_id: tuple) -> None:
        freqs = self._chord_freqs(note_name, oct_offset)
        self._active_chords[key_id] = freqs
        for f in freqs:
            self._engine.note_on(f)

    def _stop_chord(self, key_id: tuple) -> None:
        freqs = self._active_chords.pop(key_id, [])
        for f in freqs:
            self._engine.note_off(f)

    # --- Hit testing ---

    def _hit_test(self, x: int, y: int):
        # Check black keys first (they overlap white keys)
        for bi, (white_idx, note, oct_off) in enumerate(BLACK_KEYS_SEQUENCE):
            x_center = (white_idx + 1) * WHITE_KEY_WIDTH
            x0 = x_center - BLACK_KEY_WIDTH // 2
            x1 = x0 + BLACK_KEY_WIDTH
            if x0 <= x <= x1 and 0 <= y <= BLACK_KEY_HEIGHT:
                return bi, note, oct_off, True
        # Then white keys
        for i, (note, oct_off) in enumerate(WHITE_KEYS_SEQUENCE):
            x0 = i * WHITE_KEY_WIDTH
            x1 = x0 + WHITE_KEY_WIDTH
            if x0 <= x <= x1 and 0 <= y <= WHITE_KEY_HEIGHT:
                return i, note, oct_off, False
        return None

    # --- Mouse events ---

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        hit = self._hit_test(int(pos.x()), int(pos.y()))
        if hit is None:
            return
        idx, note, oct_off, is_black = hit
        key_id = ("mouse", idx, is_black)
        self._play_chord(note, oct_off, key_id)
        if is_black:
            self._pressed_black.add(idx)
        else:
            self._pressed_white.add(idx)
        code = self._keycode(note)
        self._mouse_info = (idx, key_id, is_black, code)
        self.update()
        self.chord_started.emit(code)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._mouse_info is None:
            return
        idx, key_id, is_black, code = self._mouse_info
        self._stop_chord(key_id)
        if is_black:
            self._pressed_black.discard(idx)
        else:
            self._pressed_white.discard(idx)
        self._mouse_info = None
        self.update()
        self.chord_ended.emit(code)

    # --- Keyboard events ---

    def keyPressEvent(self, event) -> None:
        key = event.key()

        # Z/X octave shifting is handled by panel-level shortcuts so it works
        # regardless of which child widget (piano, strip) currently has focus.
        if event.isAutoRepeat() or key in self._pressed_keys:
            return
        self._pressed_keys.add(key)

        mapping = QWERTY_MAP.get(key)
        if mapping is None:
            return
        note, oct_off = mapping
        key_id = ("kb", key)
        self._play_chord(note, oct_off, key_id)
        self._highlight_note(note, oct_off, pressed=True)
        code = self._keycode(note)
        self._kb_codes[key] = code
        self.update()
        self.chord_started.emit(code)

    def keyReleaseEvent(self, event) -> None:
        key = event.key()
        if event.isAutoRepeat():
            return
        self._pressed_keys.discard(key)

        mapping = QWERTY_MAP.get(key)
        if mapping is None:
            return
        note, oct_off = mapping
        key_id = ("kb", key)
        self._stop_chord(key_id)
        self._highlight_note(note, oct_off, pressed=False)
        code = self._kb_codes.pop(key, self._keycode(note))
        self.update()
        self.chord_ended.emit(code)

    # --- Strip-driven playback (no signal emission, strip manages its own state) ---

    def play_from_strip(self, note_name: str, key_id: tuple) -> None:
        """Play a chord triggered by a click on the key strip.

        Uses the current octave (no offset) and highlights the matching piano key.
        """
        self._play_chord(note_name, 0, key_id)
        self._highlight_note(note_name, 0, pressed=True)
        self.update()

    def stop_from_strip(self, note_name: str, key_id: tuple) -> None:
        self._stop_chord(key_id)
        self._highlight_note(note_name, 0, pressed=False)
        self.update()

    def _highlight_note(self, note_name: str, oct_offset: int, pressed: bool) -> None:
        # Find the visual key index for this note+octave
        for i, (n, o) in enumerate(WHITE_KEYS_SEQUENCE):
            if n == note_name and o == oct_offset:
                if pressed:
                    self._pressed_white.add(i)
                else:
                    self._pressed_white.discard(i)
                return
        for bi, (white_idx, n, o) in enumerate(BLACK_KEYS_SEQUENCE):
            if n == note_name and o == oct_offset:
                if pressed:
                    self._pressed_black.add(bi)
                else:
                    self._pressed_black.discard(bi)
                return


# ---------------------------------------------------------------------------
# KeyboardPanel — the top-level panel widget
# ---------------------------------------------------------------------------
class KeyboardPanel(QWidget):
    """Piano keyboard panel for playing chords and comparing musical keys."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._engine = _AudioEngine()
        self._engine.start()
        # segment_number -> (keycode, note_name) for active strip-driven chords
        self._active_strip_keys: dict[int, tuple[str, str]] = {}
        self._notation = "keycode"
        self._setup_ui()

    def _setup_ui(self) -> None:
        # The whole panel scrolls so users can scroll past the header/help text
        # and see the keyboard and key strip together on a short window.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)

        layout = QVBoxLayout(content)
        # Trim the left margin so the piano (and strip) sit ~6px from the panel
        # edge — more of the keyboard stays visible when the window is narrow.
        layout.setContentsMargins(6, Theme.PADDING, Theme.PADDING, Theme.PADDING)
        layout.setSpacing(Theme.SPACING)

        # Title + description on one line (description flows to the title's right)
        title = QLabel(self.tr("Keyboard"))
        title.setObjectName("sectionTitle")
        title.setStyleSheet(f"font-size: 24px; color: {Theme.NEON_YELLOW};")
        desc = QLabel(self.tr("Play chords to compare musical keys. Click keys or use QWERTY shortcuts (A-J, K-L-;). Z/X to shift octave."))
        desc.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 13px;")
        # Current key-notation indicator. Reflects the Settings notation;
        # updated live. Its right edge lines up with the keyboard's right edge
        # (see the piano-width wrapper below), not the panel's right edge.
        self._notation_label = QLabel()
        # Dark orange matching the linear strip's bottom row (key code 12) when lit.
        self._notation_label.setStyleSheet(
            "color: #ff8f00; font-size: 14px; font-weight: bold;"
        )
        self._notation_label.setToolTip(self.tr("Notation can be changed in settings"))
        header = panel_header_row(title, desc)
        header.addWidget(
            self._notation_label,
            0,
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
        )
        layout.addLayout(self._keyboard_width_row(header))
        self._update_notation_label()

        # Control bar
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(8)

        self._minor_btn = QPushButton(self.tr("Minor Chord"))
        self._major_btn = QPushButton(self.tr("Major Chord"))

        for btn in (self._minor_btn, self._major_btn):
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(32)

        self._minor_btn.setChecked(True)
        self._update_mode_styles()

        self._minor_btn.clicked.connect(lambda: self._set_mode("minor"))
        self._major_btn.clicked.connect(lambda: self._set_mode("major"))

        ctrl_layout.addWidget(self._minor_btn)
        ctrl_layout.addWidget(self._major_btn)
        ctrl_layout.addStretch()

        # Volume
        vol_label = QLabel("\u266b")
        vol_label.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-size: 16px;")
        ctrl_layout.addWidget(vol_label)

        self._vol_slider = QSlider(Qt.Orientation.Horizontal)
        self._vol_slider.setRange(0, 100)
        self._vol_slider.setValue(int(DEFAULT_VOLUME * 100))
        self._vol_slider.setFixedWidth(130)
        self._vol_slider.valueChanged.connect(self._on_volume_change)
        ctrl_layout.addWidget(self._vol_slider)

        layout.addLayout(self._keyboard_width_row(ctrl_layout))

        # Piano canvas — pinned to the left edge rather than centred, so
        # narrowing the window reveals more of it instead of clipping it behind
        # a wide left gap. (The content's left margin is trimmed to 6px below.)
        piano_row = QHBoxLayout()
        piano_row.setContentsMargins(0, 0, 0, 0)
        self._canvas = _PianoCanvas(self._engine)
        piano_row.addWidget(self._canvas)
        piano_row.addStretch(1)
        layout.addLayout(piano_row)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {Theme.BG_LIGHTER};")
        layout.addWidget(sep)

        # Strip + Hex grid row
        ref_row = QHBoxLayout()
        ref_row.setSpacing(10)

        # Left: linear key strip (renders at full height; the whole page scrolls)
        self._strip = LinearKeyStrip()
        ref_row.addWidget(self._strip, alignment=Qt.AlignmentFlag.AlignTop)

        ref_row.addStretch(1)

        # Right: harmonic reference grid (Circle of Fifths or hex honeycomb,
        # chosen by a dropdown) with the key-info box below it. The grid is
        # left-aligned (rather than centred in the wider info-box column) so it
        # sits ~1/3 closer to the strip, cutting the old hard gap.
        right_col = QVBoxLayout()
        right_col.setSpacing(12)

        # View switcher: Hex Grid (default) / Circle of Fifths.
        view_row = QHBoxLayout()
        view_row.setSpacing(8)
        view_label = QLabel(self.tr("View"))
        view_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 13px;")
        view_row.addWidget(view_label)
        self._view_combo = QComboBox()
        self._view_combo.addItem(self.tr("Hex Grid"))
        self._view_combo.addItem(self.tr("Circle of Fifths"))
        self._view_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        # Slim it down vertically so the switcher row takes less space; keep
        # horizontal padding + a min width so "Circle of Fifths" isn't clipped.
        self._view_combo.setFixedHeight(26)
        self._view_combo.setMinimumWidth(150)
        self._view_combo.setStyleSheet(
            "QComboBox { padding: 1px 8px; }"
        )
        view_row.addWidget(self._view_combo)
        view_row.addStretch(1)
        right_col.addLayout(view_row)

        # Both grids sit left-aligned in a fixed-width holder (no visible frame,
        # so no backdrop) whose width is the wider grid's. Fixing the width keeps
        # the column from reflowing — and sliding right — when the narrower
        # Circle of Fifths replaces the wider hex grid. The combo toggles which
        # grid is visible; both are highlighted in lockstep even while hidden, so
        # the visible one is always current on switch. Hex grid shows by default.
        self._circle = CircleOfFifthsGrid()
        self._hex = HexKeyGrid()
        grid_holder = QWidget()
        grid_layout = QVBoxLayout(grid_holder)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        top_left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        grid_layout.addWidget(self._hex, alignment=top_left)
        grid_layout.addWidget(self._circle, alignment=top_left)
        grid_holder.setFixedWidth(max(self._hex.width(), self._circle.width()))
        self._circle.setVisible(False)
        self._view_combo.currentIndexChanged.connect(self._on_view_changed)
        right_col.addWidget(grid_holder, alignment=Qt.AlignmentFlag.AlignLeft)

        self._info_box = KeyInfoBox()
        # Fixed-width box (every value in its own fixed slot), centred under the
        # grid. It's a little wider than the grid, so the grid re-centres within
        # this column — a one-time shift, never a per-note one.
        right_col.addWidget(self._info_box, alignment=Qt.AlignmentFlag.AlignHCenter)
        # Absorb the remaining height so the box hugs the grid instead of stretching.
        right_col.addStretch(1)
        ref_row.addLayout(right_col)

        layout.addLayout(ref_row, 1)

        # Piano -> hex + strip: light the matching key while a chord is held.
        self._canvas.chord_started.connect(self._strip.add_highlight)
        self._canvas.chord_ended.connect(self._strip.remove_highlight)
        self._canvas.chord_started.connect(self._hex.add_highlight)
        self._canvas.chord_ended.connect(self._hex.remove_highlight)
        self._canvas.chord_started.connect(self._circle.add_highlight)
        self._canvas.chord_ended.connect(self._circle.remove_highlight)
        # Piano -> info box: summarise the last key pressed.
        self._canvas.chord_started.connect(self._on_chord_started)
        # Grid / strip -> piano: play the matching chord and light everything.
        self._strip.segment_pressed.connect(self._on_segment_pressed)
        self._strip.segment_released.connect(self._on_segment_released)
        self._hex.segment_pressed.connect(self._on_segment_pressed)
        self._hex.segment_released.connect(self._on_segment_released)
        self._circle.segment_pressed.connect(self._on_segment_pressed)
        self._circle.segment_released.connect(self._on_segment_released)

        # Z/X octave shift, scoped to this panel so it works whether focus is on
        # the piano, the key strip, or anywhere else in the panel.
        for keyseq, delta in ((Qt.Key.Key_Z, -1), (Qt.Key.Key_X, 1)):
            sc = QShortcut(QKeySequence(keyseq), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(lambda d=delta: self._canvas.shift_octave(d))

    def _set_mode(self, mode: str) -> None:
        self._minor_btn.setChecked(mode == "minor")
        self._major_btn.setChecked(mode == "major")
        self._update_mode_styles()
        self._canvas.chord_mode = mode

    def _update_mode_styles(self) -> None:
        active_ss = (
            f"QPushButton {{ background: {Theme.BG_LIGHTER}; color: {Theme.TEXT_PRIMARY};"
            f" border: none; border-bottom: 3px solid {Theme.INFO};"
            f" font-weight: bold; padding: 4px 16px; font-size: 13px; }}"
        )
        inactive_ss = (
            f"QPushButton {{ background: transparent; color: {Theme.TEXT_SECONDARY};"
            f" border: none; border-bottom: 3px solid transparent;"
            f" padding: 4px 16px; font-size: 13px; }}"
            f" QPushButton:hover {{ color: {Theme.TEXT_PRIMARY}; }}"
        )
        self._minor_btn.setStyleSheet(active_ss if self._minor_btn.isChecked() else inactive_ss)
        self._major_btn.setStyleSheet(active_ss if self._major_btn.isChecked() else inactive_ss)

    def _on_view_changed(self, index: int) -> None:
        """Toggle the visible reference grid (0 = Hex, 1 = Circle of Fifths)."""
        show_hex = index == 0
        self._hex.setVisible(show_hex)
        self._circle.setVisible(not show_hex)

    def _on_volume_change(self, value: int) -> None:
        self._engine.volume = value / 100.0

    def _on_chord_started(self, code: str) -> None:
        """Piano / QWERTY press — summarise it in the info box."""
        self._info_box.update_for_number(int(code[:-1]))

    def _on_segment_pressed(self, number: int) -> None:
        """A hex or strip segment was pressed — play the chord, light everything."""
        mode = self._canvas.chord_mode
        letter = "A" if mode == "minor" else "B"
        code = f"{number}{letter}"
        inv = INV_KEYCODE_MINOR if mode == "minor" else INV_KEYCODE_MAJOR
        note = inv.get(code)
        if note is None:
            return
        self._active_strip_keys[number] = (code, note)
        self._canvas.play_from_strip(note, ("strip", number))
        self._strip.add_highlight(code)
        self._hex.add_highlight(code)
        self._circle.add_highlight(code)
        self._info_box.update_for_number(number)

    def _on_segment_released(self, number: int) -> None:
        entry = self._active_strip_keys.pop(number, None)
        if entry is None:
            return
        code, note = entry
        self._canvas.stop_from_strip(note, ("strip", number))
        self._strip.remove_highlight(code)
        self._hex.remove_highlight(code)
        self._circle.remove_highlight(code)

    # --- Public API ---

    @staticmethod
    def _keyboard_width_row(inner: "QHBoxLayout") -> "QHBoxLayout":
        """Wrap a row so it spans only the keyboard's width (left-aligned).

        Hosting the row in a piano-width box with a trailing stretch makes its
        right edge line up with the keyboard's right edge instead of snapping to
        the panel's right edge, while items inside keep their own alignment.
        """
        box = QWidget()
        box.setFixedWidth(_PIANO_WIDTH)
        # No inset, so items span the full keyboard width — a right-aligned item
        # lands exactly on the keyboard's right edge.
        inner.setContentsMargins(0, 0, 0, 0)
        box.setLayout(inner)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(box)
        row.addStretch(1)
        return row

    def set_key_notation(self, notation: str) -> None:
        """Set the notation used for the piano key labels and the 1-12 numbers."""
        self._canvas.set_notation(notation)
        self._hex.set_key_notation(notation)
        self._circle.set_key_notation(notation)
        self._strip.set_key_notation(notation)
        self._info_box.set_key_notation(notation)
        self._notation = notation
        self._update_notation_label()

    def _update_notation_label(self) -> None:
        """Refresh the top-right indicator with the current notation's name."""
        self._notation_label.setText(
            {
                "keycode": self.tr("👑 Key Codes"),
                "traditional": self.tr("Traditional Key Notation"),
                "open_key": self.tr("Traktor Open Key"),
            }.get(self._notation, self.tr("👑 Key Codes"))
        )

    def stop_audio(self) -> None:
        """Stop all audio (called when navigating away)."""
        self._engine.stop()

    def _ensure_audio(self) -> None:
        """Restart audio engine if stopped."""
        self._engine.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._ensure_audio()
        self._canvas.setFocus()
