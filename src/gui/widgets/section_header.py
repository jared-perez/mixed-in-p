"""The Player panel's disclosure header — one look, two owners.

The panel stacks independent collapsible sections (Waveform, Zoomed Wave and
Loop Slicer in :mod:`slice_section`, the metronome in :mod:`metronome_section`),
and they have to read as one family: same arrow, same accent word, same bar
height. Sizing a
disclosure header is also fiddly enough to be worth writing once — a
``QPushButton`` *centres* rather than elides, so a width short by a few pixels
cuts the label at both ends with nothing to show it happened, and the native
size hint cannot see the stylesheet padding that would cause it.

The arrows are text rather than icons on purpose: they carry no glyph asset,
they follow the palette's accent colour for free, and they are not translated.
"""

from __future__ import annotations

from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QPushButton

from ..styles.theme import Theme

ARROW_CLOSED = "▸"
ARROW_OPEN = "▾"


def header_button(label: str) -> QPushButton:
    """A borderless accent-text disclosure toggle sized to its own label."""
    btn = QPushButton(f"{ARROW_CLOSED}  {label}")
    btn.setCheckable(True)
    btn.setProperty("headerLabel", label)
    btn.setStyleSheet(
        f"text-align: left; font-weight: bold; color: {Theme.ACCENT_TEXT};"
        " padding: 0px; border: none;"
    )
    # Derived from the button's own font, not its parent's: a style is free to
    # give QPushButton a different default from a plain QWidget's, and the
    # width below is only honest if it measures what actually paints. Bump the
    # point size a couple of steps so the headers read clearly.
    font = btn.font()
    font.setBold(True)
    font.setPointSize(font.pointSize() + 2)
    btn.setFont(font)
    fm = QFontMetrics(font)
    # Size from font metrics, not sizeHint — see the module docstring. Width
    # the *wider* arrow so the label neither shifts nor clips when it opens.
    arrow_w = max(fm.horizontalAdvance(ARROW_CLOSED), fm.horizontalAdvance(ARROW_OPEN))
    btn.setFixedWidth(arrow_w + fm.horizontalAdvance(f"  {label}") + 8)
    # Shrink the bar to just the text height (+1px) so it stops hogging
    # vertical space; the default button padding made it far too tall.
    btn.setFixedHeight(fm.height() + 1)
    return btn


def sync_header_arrow(btn: QPushButton, open_: bool) -> None:
    """Point the arrow the way the section now is."""
    arrow = ARROW_OPEN if open_ else ARROW_CLOSED
    btn.setText(f"{arrow}  {btn.property('headerLabel')}")

