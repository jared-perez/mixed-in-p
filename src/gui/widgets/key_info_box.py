"""Key info box — harmonic summary of the last key pressed in the Keyboard panel.

Sits centred below the hex grid. Driven by the key-code number (1-12) of the
last key played (from the piano, QWERTY, hex grid, or linear strip): whichever
chord mode was used, it always shows both the minor (``NA``) and major (``NB``)
of that number, the three harmonically-compatible neighbours, and a label for
the currently-selected notation.

Each value is rendered "selected notation followed by traditional", e.g. Key
Codes -> ``8A  Am``, Open Key -> ``1m  Am``; when traditional notation is
selected it collapses to just the traditional name (``Am``). All formatting is
delegated to ``src.analysis.keycode`` so this widget owns no key tables.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QSizePolicy,
    QWidget,
)

from src.analysis.keycode import keycode_to_key, keycode_to_open_key, render_key

from ..styles.theme import Theme


def _compatible_numbers(n: int) -> list[int]:
    """Adjacent key-code numbers (prev, self, next), wrapping 1-12, in order."""
    prev = ((n - 2) % 12) + 1
    nxt = (n % 12) + 1
    return [prev, n, nxt]


class KeyInfoBox(QFrame):
    """Horizontal harmonic summary of the last key pressed."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._number: int | None = None
        self._notation = "keycode"

        self.setObjectName("keyInfoBox")
        self.setStyleSheet(
            f"#keyInfoBox {{ background: {Theme.BG_DARK};"
            f" border-radius: {Theme.BORDER_RADIUS}px; }}"
        )

        caption_ss = (
            f"color: {Theme.TEXT_SECONDARY}; font-size: 9px;"
            " font-weight: bold; letter-spacing: 1px;"
        )
        # The global "QWidget { font-size: 14px }" rule overrides a QFont point
        # size, so the rendered value size must be set in the labels' own
        # stylesheet (below); the QFont here only drives the fixed-slot width
        # measurement and must match that family/pixel size to size the slots.
        _VALUE_PX = 28
        value_font = QFont("Helvetica Neue")
        value_font.setPixelSize(_VALUE_PX)
        value_font.setBold(True)
        # No left padding so each chip's first character lines up under the value
        # column above it (the values have no padding).
        chip_ss = f"color: {Theme.TEXT_PRIMARY}; font-size: 20px;"

        # Value / chip widgets.
        self._notation_value = QLabel()
        self._minor_value = QLabel()
        self._major_value = QLabel()
        for v in (self._notation_value, self._minor_value, self._major_value):
            v.setFont(value_font)
            v.setStyleSheet(
                f"color: {Theme.TEXT_PRIMARY}; font-size: {_VALUE_PX}px;"
                " font-weight: bold;"
            )
        self._compat_labels: list[QLabel] = []
        for _ in range(3):
            chip = QLabel()
            chip.setStyleSheet(chip_ss)
            self._compat_labels.append(chip)

        # Every value sits in a fixed-width slot (its widest content over all
        # numbers × notations) so it always starts at the same x and nothing
        # shifts as keys change.
        value_ss = f"font-size: {_VALUE_PX}px; font-weight: bold;"
        self._notation_value.setFixedWidth(self._max_notation_width(value_ss))
        self._minor_value.setFixedWidth(self._max_value_width(value_ss, "A"))
        self._major_value.setFixedWidth(self._max_value_width(value_ss, "B"))
        chip_w = self._max_chip_width(chip_ss)
        for chip in self._compat_labels:
            chip.setFixedWidth(chip_w)

        # Keep each slot's width reserved even while hidden (empty state), so the
        # columns — and the box's overall width — never change.
        for w in (
            self._notation_value,
            self._minor_value,
            self._major_value,
            *self._compat_labels,
        ):
            sp = w.sizePolicy()
            sp.setRetainSizeWhenHidden(True)
            w.setSizePolicy(sp)

        # Empty-state hint, spanning the value row.
        self._placeholder = QLabel(self.tr("Press a key to see harmonic info…"))
        self._placeholder.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")

        grid = QGridLayout(self)
        # Top padding tightened so the doubled values fit without pushing the
        # COMPATIBLE WITH row down; captions sit tight above the values.
        grid.setContentsMargins(12, 2, 12, 8)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(4)

        top = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        bottom = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom

        # Row 0: notation/minor/major labels, pinned to the top over their values.
        for col, text in (
            (0, self.tr("NOTATION")),
            (1, self.tr("MINOR")),
            (2, self.tr("MAJOR")),
        ):
            lbl = QLabel(text)
            lbl.setStyleSheet(caption_ss)
            grid.addWidget(lbl, 0, col, top)

        # Row 1: notation/minor/major values, each in its own fixed-width column.
        grid.addWidget(self._notation_value, 1, 0, bottom)
        grid.addWidget(self._minor_value, 1, 1, bottom)
        grid.addWidget(self._major_value, 1, 2, bottom)
        grid.addWidget(self._placeholder, 1, 0, 1, 3, bottom)

        # Row 2: "compatible with" label + chips in their own nested grid, so the
        # label hugs its chips (tight, like a caption over its value) while the
        # main grid's vertical spacing still separates this from the row above.
        compat_box = QWidget()
        compat_grid = QGridLayout(compat_box)
        compat_grid.setContentsMargins(0, 0, 0, 0)
        compat_grid.setHorizontalSpacing(16)
        compat_grid.setVerticalSpacing(2)
        compat_lbl = QLabel(self.tr("COMPATIBLE WITH"))
        compat_lbl.setStyleSheet(caption_ss)
        compat_grid.addWidget(compat_lbl, 0, 0, 1, 3, top)
        for i, chip in enumerate(self._compat_labels):
            compat_grid.addWidget(chip, 1, i, bottom)
        grid.addWidget(compat_box, 2, 0, 1, 3)

        # Fixed width = deterministic sum of the fixed slots + spacing/margins.
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._render()
        self.setFixedWidth(self.sizeHint().width())

    # --- Slot-width measurement (global max over all numbers × notations) ---

    def _max_notation_width(self, value_ss: str) -> int:
        # Measure with the labels' own stylesheet font-size, not setFont: the
        # global "QWidget { font-size: 14px }" rule overrides a QFont, so a
        # setFont-only probe would size slots for 14px and clip the real text.
        probe = QLabel()
        probe.setStyleSheet(value_ss)
        best = 0
        for notation in ("keycode", "traditional", "open_key"):
            self._notation = notation
            for n in range(1, 13):
                probe.setText(self._notation_text(n))
                best = max(best, probe.sizeHint().width())
        self._notation = "keycode"
        return best

    def _max_value_width(self, value_ss: str, letter: str) -> int:
        probe = QLabel()
        probe.setStyleSheet(value_ss)
        best = 0
        for notation in ("keycode", "traditional", "open_key"):
            self._notation = notation
            for n in range(1, 13):
                probe.setText(self._value(f"{n}{letter}"))
                best = max(best, probe.sizeHint().width())
        self._notation = "keycode"
        return best

    def _max_chip_width(self, chip_ss: str) -> int:
        probe = QLabel()
        probe.setStyleSheet(chip_ss)
        best = 0
        for notation in ("keycode", "traditional", "open_key"):
            self._notation = notation
            for n in range(1, 13):
                for c in _compatible_numbers(n):
                    probe.setText(self._compat_text(c))
                    best = max(best, probe.sizeHint().width())
        self._notation = "keycode"
        return best

    # --- Public API ---

    def set_key_notation(self, notation: str) -> None:
        """Switch the notation used to render the box, then re-render."""
        if notation == self._notation:
            return
        self._notation = notation
        self._render()

    def update_for_number(self, number: int) -> None:
        """Set the last-pressed key-code number (1-12) and re-render."""
        if not 1 <= number <= 12:
            return
        self._number = number
        self._render()

    # --- Rendering ---

    def _value(self, code: str) -> str:
        """'selected notation  traditional' for a code, or just traditional."""
        trad = keycode_to_key(code)
        if self._notation == "traditional":
            return trad
        return f"{render_key(trad, code, self._notation)}  {trad}"

    def _notation_text(self, number: int) -> str:
        """The pressed key as 'minor / major' in the selected notation only."""
        a = render_key(keycode_to_key(f"{number}A"), f"{number}A", self._notation)
        b = render_key(keycode_to_key(f"{number}B"), f"{number}B", self._notation)
        return f"{a} / {b}"

    def _compat_num(self, c: int) -> str:
        """Leading number for a compatible chip, in the selected notation."""
        if self._notation == "traditional":
            return ""
        if self._notation == "open_key":
            return keycode_to_open_key(f"{c}A")[:-1]
        return str(c)

    def _compat_text(self, c: int) -> str:
        min_t = keycode_to_key(f"{c}A")
        maj_t = keycode_to_key(f"{c}B")
        num = self._compat_num(c)
        return f"{num} - {min_t} / {maj_t}" if num else f"{min_t} / {maj_t}"

    def _render(self) -> None:
        if self._number is None:
            self._placeholder.setVisible(True)
            self._notation_value.setVisible(False)
            self._minor_value.setVisible(False)
            self._major_value.setVisible(False)
            for chip in self._compat_labels:
                chip.setVisible(False)
            return

        self._placeholder.setVisible(False)
        self._notation_value.setVisible(True)
        self._minor_value.setVisible(True)
        self._major_value.setVisible(True)
        self._notation_value.setText(self._notation_text(self._number))
        self._minor_value.setText(self._value(f"{self._number}A"))
        self._major_value.setText(self._value(f"{self._number}B"))
        for chip, c in zip(self._compat_labels, _compatible_numbers(self._number)):
            chip.setText(self._compat_text(c))
            chip.setVisible(True)
