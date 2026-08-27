"""The Player panel's metronome, behind a disclosure header.

A sibling of :mod:`slice_section` rather than a third toggle inside it: the
slice views act on the loaded track and this does not, and — the part that
decides the layout — a disclosure control's body belongs directly under its own
header. Sharing one header row would have put the metronome's controls below
the slice tray, so opening it with the slicer already open would have dropped
the body a canvas-and-a-half away from the word that opened it.

It lived in the Keyboard panel's view switcher until 2026-08-26, three clicks
deep behind a dropdown, which is the wrong place for a thing you set once and
then leave running while you work. Everything about the metronome itself —
the sample-scheduled grid, the click voices, Global Click — stayed exactly
where it was; only its host moved.

The header row carries the Start button as well as the word, which is the one
thing the section lays out that it does not own: :class:`MetronomeView` builds
it and drives it, and this places it. Being up here is the point — Start is
the control the hand goes for once the tempo is set, so it is the biggest
thing in the section and the only one not buried in the tray. It hides with
the body, so a collapsed metronome reads exactly like the two sections beside
it.

Collapsing silences it, and it does so through :meth:`MetronomeView.hideEvent`
rather than through anything here: hiding the body IS the stop signal, and
routing it that way means the Global Click setting is honoured by one code
path instead of two that have to be kept in step.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QVBoxLayout, QWidget

from . import section_header
from ..styles.theme import Theme
from .metronome_view import MetronomeView

# Space between the section's word and its Start button. Wider than the row's
# own spacing so the button reads as a control on the header rather than as a
# second word of the label.
_START_GAP = 12


class MetronomeSection(QWidget):
    """Collapsible metronome: a header toggle and the view it opens."""

    # Opened/closed — the panel reflows the playlist's height budget around it
    # and the window sizer applies its minimum width.
    expanded_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None, stream_factory=None) -> None:
        super().__init__(parent)
        self.setObjectName("metronomeSection")
        # A bare QWidget paints the global BG_DARK over the player's grey.
        self.setStyleSheet(
            "#metronomeSection { background: transparent; }"
            f"#metronomeTray {{ background-color: {Theme.TRAY_BG}; border-radius: 6px; }}"
        )
        self._expanded = False
        self._setup_ui(stream_factory)
        # Never capture focus, so Space stays play/pause and the panel's slice
        # keys are not swallowed — the same rule the slice section follows.
        # The BPM box is deliberately left out: it is a text field and typing
        # into it is the point.
        for btn in self.findChildren(QAbstractButton):
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._set_body_visible(False)

    def _setup_ui(self, stream_factory) -> None:
        # Built first: the header row below adopts its Start button.
        self._view = MetronomeView(stream_factory=stream_factory)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Theme.SPACING)

        self._header_btn = section_header.header_button(self.tr("Metronome"))
        self._header_btn.toggled.connect(self._on_toggled)
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        # Explicitly, because a layout handed to nothing takes the Qt style's
        # 6px rather than Theme.SPACING and this row is measured below.
        header_row.setSpacing(Theme.SPACING)
        header_row.addWidget(
            self._header_btn, alignment=Qt.AlignmentFlag.AlignVCenter
        )
        header_row.addSpacing(_START_GAP)
        # The view builds Start and drives it; the header row is only where it
        # sits. Adopting it here reparents it off the view, which is the point:
        # it has to stay put while the body under it opens and closes.
        self._start_btn = self._view.start_button()
        # Deliberately NOT aligned. A QWidgetItem carrying a vertical
        # alignment clamps its own height to its sizeHint — and this button's
        # hint is the stylesheet's padding, ~22px, not the 40 it was fixed to.
        # So it took its width and lost its height, inside a row that was
        # correctly 40px tall. The word beside it keeps its AlignVCenter,
        # which is what makes the pair read as one row.
        header_row.addWidget(self._start_btn)
        header_row.addStretch(1)
        layout.addLayout(header_row)

        # In the same near-black tray the slice controls use, so the two
        # opened sections read as the same kind of work area.
        self._body = QWidget()
        self._body.setObjectName("metronomeTray")
        body = QVBoxLayout(self._body)
        body.setContentsMargins(10, 10, 10, 10)
        body.setSpacing(Theme.SPACING)
        body.addWidget(self._view)
        layout.addWidget(self._body)

    # ── the disclosure ──────────────────────────────────────────────

    def _on_toggled(self, checked: bool) -> None:
        self._expanded = checked
        self._set_body_visible(checked)
        self.expanded_changed.emit(checked)

    def _set_body_visible(self, visible: bool) -> None:
        # Hiding the body is what stops the click — see the module docstring.
        self._body.setVisible(visible)
        # Start goes with it, even though it no longer lives inside it. A
        # collapsed section shows nothing but its own word, the same as the
        # two beside it — and a Start button reachable while the body is shut
        # could open the stream against a hidden view, which is a second way
        # into a state the Global Click rule already owns.
        self._start_btn.setVisible(visible)
        section_header.sync_header_arrow(self._header_btn, visible)
        self._header_btn.setToolTip(
            self.tr("Hide the metronome")
            if visible
            else self.tr("Show the metronome — tap a tempo and click along")
        )

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        self._header_btn.setChecked(expanded)

    # ── what the panel needs to know ────────────────────────────────

    @property
    def view(self) -> MetronomeView:
        return self._view

    def first_screen_height(self) -> int:
        """Height that has to be on screen for an opened section to look open.

        The header plus the whole body — unlike the slice tray, whose marker
        rows are allowed to want scrolling, this body is three short rows and
        there is nothing in it worth putting below the fold.
        """
        h = self._header_btn.height()
        if self._expanded:
            # The header row grows to whichever is taller once Start is on it.
            h = max(h, self._start_size().height())
            h += Theme.SPACING + self._body.sizeHint().height()
        return h

    def _start_size(self) -> QSize:
        """What the Start button really occupies, from hint and minimum both.

        Neither alone is honest in both worlds. The view fixes the size in
        Python, which the *suite* sees (it runs with no stylesheet) and the
        app does not — a stylesheet minimum replaces the one setFixedSize set,
        so under the real QSS the height comes back from the rule instead.
        Taking the larger of the two is right in either, and it is a hint
        rather than a laid-out height on purpose: this runs to decide the
        geometry it would otherwise be reading back.
        """
        hint = self._start_btn.sizeHint()
        return QSize(
            max(hint.width(), self._start_btn.minimumWidth()),
            max(hint.height(), self._start_btn.minimumHeight()),
        )

    def row_min_width(self) -> int:
        """Width the widest control row needs, for the window minimum.

        Measured rather than written down: every label in here is translated,
        and a constant is an English width.
        """
        header_row = (
            self._header_btn.width()
            + Theme.SPACING
            + _START_GAP
            + self._start_size().width()
        )
        return max(self._view.sizeHint().width() + 20, header_row)  # tray margins

    # ── audio lifecycle ─────────────────────────────────────────────

    def leave(self) -> None:
        """Navigating off the Player panel. Honours Global Click."""
        self._view.leave()

    def stop(self) -> None:
        """Unconditional — the close path, where no mode gets a vote."""
        self._view.stop()
