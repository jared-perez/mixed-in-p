"""Review what an online lookup found, field by field, before anything is written.

**No auto-accept, ever.** The top candidate is pre-selected and its values are
shown beside the file's current ones, but a value is written only where the
user ticked it. A wrong pre-selection teaches people to distrust the whole
feature, so a weak match says so in words rather than quietly filling the form.

Two deliberate defaults:

* **A field that already has a value starts unticked**; an empty one starts
  ticked. The decided rule was "never overwrite a filled field automatically"
  (asked about genre, applied here to every field, because a rule that holds
  for one field and not its neighbours is a rule nobody can predict). *Select
  All* is one click for the re-tag case.
* **Album art is a field like any other** — previewed here, written only if
  ticked, and offered only when the setting that fetches it is on.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QT_TRANSLATE_NOOP, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.metadata.tags import stores_tags
from src.online import discogs, matching
from src.online.result import Candidate

from ...lookup_flow import ARTWORK_FIELD
from ...styles.theme import Theme
from ..elided_label import ElidedLabel

logger = logging.getLogger(__name__)

# Room a button needs beyond its text: the stylesheet's "padding: 8px 16px",
# its border and a little slack. The native size hint cannot see stylesheet
# padding, and a QPushButton centres rather than elides — so a translated
# label would be cut at both ends without this.
# (Plain "#", not "#:" — lupdate harvests the latter as a note to translators.)
_BUTTON_CHROME = 44

# Display order and labels for the diff rows. Same field keys as
# ``TrackMetadata`` / the Metadata panel, so a value crosses from here to the
# tag writer with no translation table in between.
# Marked here (QT_TRANSLATE_NOOP returns the string unchanged) and translated
# at the display site with self.tr(label), the same shape metadata_panel.py
# uses for its field list.
_FIELD_ORDER = [
    ("title", QT_TRANSLATE_NOOP("LookupReviewDialog", "Title")),
    ("artist", QT_TRANSLATE_NOOP("LookupReviewDialog", "Artist")),
    ("album", QT_TRANSLATE_NOOP("LookupReviewDialog", "Album")),
    ("label", QT_TRANSLATE_NOOP("LookupReviewDialog", "Label")),
    ("genre", QT_TRANSLATE_NOOP("LookupReviewDialog", "Genre")),
    ("year", QT_TRANSLATE_NOOP("LookupReviewDialog", "Year")),
    ("track_number", QT_TRANSLATE_NOOP("LookupReviewDialog", "Track #")),
]

# Edge of the cover previews, in px. Big enough to tell two sleeves apart,
# small enough that two of them plus the fields fit without scrolling.
_ART_EDGE = 96

# Result code for "stop reviewing the rest", offered only in a batch run.
# QDialog's own Accepted (1) and Rejected (0) mean apply-this-one and skip-it,
# so a third verb needs a third code rather than an overloaded Cancel.
STOP_RESULT = 2


class LookupReviewDialog(QDialog):
    """The per-file diff: current tags on the left, the release's on the right.

    The dialog does not write anything. It reports which fields the user
    approved (:meth:`selected_values`) and lets the panel that owns the file do
    the writing, through the same ``tags.py`` path a manual edit takes — which
    is what makes the Windows file-lock rules and the WAV guard apply for free.

    Switching candidate needs another request, which must not happen on the UI
    thread: the dialog emits :attr:`candidate_requested` and waits for the
    caller to hand back a new result via :meth:`set_result`.
    """

    candidate_requested = Signal(object)  # Candidate

    def __init__(
        self,
        file_path: str,
        current: dict[str, object],
        result,
        allow_artwork: bool = True,
        parent: QWidget | None = None,
        position: tuple[int, int] | None = None,
    ) -> None:
        super().__init__(parent)
        self._file_path = file_path
        self._current = dict(current)
        self._allow_artwork = allow_artwork
        # (n, total) while reviewing a batch; None for a single file. Batch
        # mode is what turns Cancel into Skip and adds Stop — with several
        # files queued, "cancel" is ambiguous between this one and the rest.
        self._position = position
        self._result = result
        # The proposal actually on screen. Not `result.proposed`: the track
        # picker re-derives it for a different row of the release, and the
        # result belongs to the caller — mutating theirs to show ours would
        # make the override invisible from the outside and permanent from the
        # inside.
        self._proposed = getattr(result, "proposed", None)
        self._checks: dict[str, QCheckBox] = {}
        self._proposed_labels: dict[str, QLabel] = {}
        self._loading = False

        self.setWindowTitle(self.tr("Review Metadata"))
        self.setMinimumWidth(640)
        self._setup_ui()
        self._apply_result()

    # ------------------------------------------------------------------ ui

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            Theme.PADDING, Theme.PADDING, Theme.PADDING, Theme.PADDING
        )
        layout.setSpacing(Theme.SPACING)

        heading = QLabel(self.tr("Tick the values you want to write to this file."))
        heading.setWordWrap(True)
        layout.addWidget(heading)

        if self._position is not None:
            index, total = self._position
            counter = QLabel(self.tr("File {0} of {1}").format(index, total))
            counter.setStyleSheet(f"color: {Theme.NEON_YELLOW};")
            layout.addWidget(counter)

        self._file_label = ElidedLabel(self._file_path, mode=Qt.TextElideMode.ElideLeft)
        self._file_label.setToolTip(self._file_path)
        self._file_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        layout.addWidget(self._file_label)

        # Candidate switcher — the alternatives the search found, so a wrong
        # top match is one dropdown away from the right one. It reads as a
        # verb, not as a field name: this is the escape hatch for every wrong
        # match in the feature, and "Release:" made it look like a readout.
        # No compactCombo here — that object name is the Convert format row's
        # answer to a row genuinely short of width, and this row (one label
        # plus one stretching combo) has none of that pressure. All it would
        # buy is a smaller arrow, i.e. less of the only affordance the control
        # has.
        release_row = QHBoxLayout()
        release_row.setSpacing(Theme.SPACING)
        release_hint = self.tr(
            "Not the right pressing? Pick another release the search found."
        )
        self._release_label = QLabel(self.tr("Select release"))
        release_label = self._release_label
        release_label.setToolTip(release_hint)
        release_row.addWidget(release_label)
        self._candidate_combo = QComboBox()
        self._candidate_combo.setToolTip(release_hint)
        self._candidate_combo.currentIndexChanged.connect(self._on_candidate_changed)
        release_row.addWidget(self._candidate_combo, 1)
        layout.addLayout(release_row)

        # Which row of that release the file is. The release switcher answers
        # "which record is this"; this answers "which track on it", and until
        # now nothing did — `pick_track` chose among twenty rows of a
        # compilation, or five mixes of one title on a 12", with no way to say
        # it chose wrong. Hidden for a release with nothing to choose between.
        self._track_row = QWidget()
        self._track_row.setObjectName("lookupTrackRow")
        self._track_row.setStyleSheet("#lookupTrackRow { background: transparent; }")
        track_layout = QHBoxLayout(self._track_row)
        track_layout.setContentsMargins(0, 0, 0, 0)
        track_layout.setSpacing(Theme.SPACING)
        track_hint = self.tr(
            "Wrong track from this release? Pick the right row of the tracklist."
        )
        track_label = QLabel(self.tr("Select track"))
        track_label.setToolTip(track_hint)
        track_layout.addWidget(track_label)
        self._track_combo = QComboBox()
        self._track_combo.setToolTip(track_hint)
        self._track_combo.currentIndexChanged.connect(self._on_track_changed)
        track_layout.addWidget(self._track_combo, 1)
        self._track_row.setVisible(False)
        layout.addWidget(self._track_row)

        # Line the two combos up. Release sits above Track and their labels are
        # different lengths in every language, so without this the second
        # dropdown starts a few dozen pixels left of the first and the pair
        # reads as unfinished. Measured from the labels' own size hints, never
        # a constant: "Veröffentlichung wählen" is twice the width of "Titel
        # wählen", and both are twice "Select release".
        label_column = max(
            release_label.sizeHint().width(), track_label.sizeHint().width()
        )
        release_label.setMinimumWidth(label_column)
        track_label.setMinimumWidth(label_column)

        self._warning = QLabel("")
        self._warning.setWordWrap(True)
        self._warning.setStyleSheet(f"color: {Theme.NEON_YELLOW};")
        self._warning.setVisible(False)
        layout.addWidget(self._warning)

        # The diff itself.
        self._grid_host = QWidget()
        self._grid_host.setObjectName("lookupDiffHost")
        # A bare QWidget container would paint the global BG_DARK over the
        # dialog's own background.
        self._grid_host.setStyleSheet("#lookupDiffHost { background: transparent; }")
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        # A layout given to a widget takes the Qt style default (6px), not
        # Theme.SPACING — set it, because this grid's widths get measured.
        self._grid.setSpacing(Theme.SPACING)
        self._grid.setColumnStretch(1, 1)
        self._grid.setColumnStretch(3, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self._grid_host)
        layout.addWidget(scroll, 1)

        # Artwork: current beside proposed, with its own tick.
        self._art_row = QWidget()
        self._art_row.setObjectName("lookupArtRow")
        self._art_row.setStyleSheet("#lookupArtRow { background: transparent; }")
        art_layout = QHBoxLayout(self._art_row)
        art_layout.setContentsMargins(0, 0, 0, 0)
        art_layout.setSpacing(Theme.SPACING)
        self._art_check = QCheckBox(self.tr("Album Art"))
        art_layout.addWidget(self._art_check)
        self._art_current = QLabel()
        self._art_current.setFixedSize(_ART_EDGE, _ART_EDGE)
        self._art_proposed = QLabel()
        self._art_proposed.setFixedSize(_ART_EDGE, _ART_EDGE)
        art_layout.addWidget(self._art_current)
        art_layout.addWidget(QLabel("→"))
        art_layout.addWidget(self._art_proposed)
        art_layout.addStretch()
        self._art_row.setVisible(False)
        layout.addWidget(self._art_row)

        # WAV holds no tags at all. The lookup is still worth running (reading
        # the values is useful), so this says so rather than blocking.
        self._tagless_label = QLabel(
            self.tr("WAV files can't store tags — these values won't be saved.")
        )
        self._tagless_label.setWordWrap(True)
        self._tagless_label.setStyleSheet(f"color: {Theme.NEON_YELLOW};")
        self._tagless_label.setVisible(not stores_tags(self._file_path))
        layout.addWidget(self._tagless_label)

        # Attribution for the data we display, on its own line. It shared the
        # button row until Russian, where five buttons and a credit together
        # are wider than the dialog — and a QPushButton neither shrinks below
        # its text nor elides, so the row simply overlapped itself.
        credit = QLabel(discogs.ATTRIBUTION)
        credit.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        layout.addWidget(credit)

        buttons = QHBoxLayout()
        buttons.setSpacing(Theme.SPACING)
        buttons.addStretch()

        self._all_btn = self._make_button(self.tr("Select All"), self._select_all)
        self._none_btn = self._make_button(self.tr("Select None"), self._select_none)
        self._stop_btn = None
        if self._position is None:
            self._cancel_btn = self._make_button(self.tr("Cancel"), self.reject)
        else:
            # Skip leaves this file alone and moves on; Stop abandons the rest
            # of the queue. Two escape hatches because a batch really does have
            # two things to escape.
            self._cancel_btn = self._make_button(self.tr("Skip"), self.reject)
            self._stop_btn = self._make_button(
                self.tr("Stop"), lambda: self.done(STOP_RESULT)
            )
        self._apply_btn = self._make_button(self.tr("Apply"), self.accept)
        self._apply_btn.setStyleSheet(
            f"background-color: {Theme.NEON_YELLOW}; color: #000000; font-weight: bold;"
        )
        self._apply_btn.setDefault(True)
        row = [b for b in (self._all_btn, self._none_btn, self._stop_btn,
                           self._cancel_btn, self._apply_btn) if b is not None]
        for btn in row:
            buttons.addWidget(btn)
        layout.addLayout(buttons)
        self._fit_to_buttons(row, layout)

    def _fit_to_buttons(self, row: list[QPushButton], layout) -> None:
        """Widen the dialog if its own buttons need more room than the default.

        A width written as a constant is an English width: "Select None" is
        11 characters and "Снять выделение" is 15, and the row grows again in
        batch mode where there are five buttons rather than four. So the
        minimum is measured from the buttons actually present — each already
        sized from *its* font metrics plus the stylesheet padding the native
        size hint cannot see.
        """
        margins = layout.contentsMargins()
        needed = (
            sum(b.minimumWidth() for b in row)
            + Theme.SPACING * max(0, len(row) - 1)
            + margins.left()
            + margins.right()
        )
        self.setMinimumWidth(max(self.minimumWidth(), needed))

    def _make_button(self, text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setMinimumWidth(
            button.fontMetrics().horizontalAdvance(text) + _BUTTON_CHROME
        )
        button.clicked.connect(slot)
        return button

    # -------------------------------------------------------------- results

    def set_result(self, result) -> None:
        """Show a new result — used when the user switched candidate."""
        self._result = result
        self._proposed = getattr(result, "proposed", None)
        self._apply_result()

    def _apply_result(self) -> None:
        self._loading = True
        try:
            self._fill_candidates()
            self._fill_tracks()
            self._fill_rows()
            self._fill_artwork()
            self._fill_warning()
        finally:
            self._loading = False

    def _fill_candidates(self) -> None:
        combo = self._candidate_combo
        combo.blockSignals(True)
        combo.clear()
        for candidate in self._result.candidates:
            combo.addItem(candidate.label_line() or self.tr("Unknown release"),
                          candidate)
        chosen = self._result.chosen
        if chosen is not None:
            for index in range(combo.count()):
                if combo.itemData(index) is chosen:
                    combo.setCurrentIndex(index)
                    break
        combo.setEnabled(combo.count() > 1)
        combo.blockSignals(False)

    def _fill_tracks(self) -> None:
        """Offer the release's rows, with the automatic choice pre-selected.

        The list is the candidate's own ``tracklist``, which is exactly what
        ``pick_track`` ran against — headings and index tracks already
        dropped. Offering an unfiltered list instead would put the ordinals
        out of step with the numbers the rows carry, so a heading two lines up
        would silently shift every track number written after it.
        """
        combo = self._track_combo
        chosen = self._result.chosen
        entries = list(getattr(chosen, "tracklist", ()) or ())
        combo.blockSignals(True)
        combo.clear()
        for entry in entries:
            combo.addItem(entry.label_line() or self.tr("Unknown track"), entry)
        picked = getattr(chosen, "track", None)
        if picked is not None:
            for index in range(combo.count()):
                if combo.itemData(index) is picked:
                    combo.setCurrentIndex(index)
                    break
        combo.blockSignals(False)
        # One row is not a choice, and a dropdown that cannot be changed reads
        # as a control that is broken.
        self._track_row.setVisible(len(entries) > 1)

    def _on_track_changed(self, index: int) -> None:
        """Re-read the proposal off another row. No request, no re-rank.

        Only the diff is rebuilt, not the whole result: the release is still
        the release, so its artwork, its candidates and the weak-match warning
        that `pick_track`'s score drove all stand. What must be redone is the
        diff itself — every tick is per-field, and the values on both sides of
        three of those rows have just moved.
        """
        if self._loading or index < 0 or self._proposed is None:
            return
        entry = self._track_combo.itemData(index)
        if entry is None:
            return
        release_artist = getattr(self._result.chosen, "artist", "")
        self._proposed = self._proposed.with_track(entry, release_artist)
        self._fill_rows()

    def _fill_rows(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._checks.clear()
        self._proposed_labels.clear()

        header_current = QLabel(self.tr("Current"))
        header_proposed = QLabel(self.tr("From Discogs"))
        for label in (header_current, header_proposed):
            label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        self._grid.addWidget(header_current, 0, 1)
        self._grid.addWidget(header_proposed, 0, 3)

        proposed = self._proposed.as_fields() if self._proposed else {}
        row = 1
        for key, label in _FIELD_ORDER:
            if key not in proposed:
                continue
            new_value = str(proposed[key])
            old_value = _as_text(self._current.get(key))
            if old_value == new_value:
                # An unchanged field is not a change to review.
                continue
            check = QCheckBox(self.tr(label))
            # A filled field starts unticked: never overwrite silently.
            check.setChecked(not old_value)
            self._checks[key] = check
            current_label = ElidedLabel(old_value or self.tr("(empty)"))
            current_label.setToolTip(old_value)
            current_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
            proposed_label = ElidedLabel(new_value)
            proposed_label.setToolTip(new_value)
            self._proposed_labels[key] = proposed_label

            self._grid.addWidget(check, row, 0)
            self._grid.addWidget(current_label, row, 1)
            self._grid.addWidget(QLabel("→"), row, 2)
            self._grid.addWidget(proposed_label, row, 3)
            row += 1

        if row == 1:
            nothing = QLabel(self.tr("Every field already matches this release."))
            nothing.setWordWrap(True)
            self._grid.addWidget(nothing, 1, 0, 1, 4)
        self._grid.setRowStretch(row, 1)
        self._sync_apply_enabled()

    def _fill_artwork(self) -> None:
        art = getattr(self._result, "artwork", b"")
        if not self._allow_artwork or not art:
            self._art_row.setVisible(False)
            return
        proposed = QPixmap()
        if not proposed.loadFromData(art):
            self._art_row.setVisible(False)
            return
        self._art_proposed.setPixmap(_scaled(proposed))
        current = self._current.get(ARTWORK_FIELD)
        current_pixmap = QPixmap()
        if isinstance(current, (bytes, bytearray)) and current:
            current_pixmap.loadFromData(bytes(current))
        if current_pixmap.isNull():
            self._art_current.setText(self.tr("(none)"))
            self._art_check.setChecked(True)
        else:
            self._art_current.setPixmap(_scaled(current_pixmap))
            self._art_check.setChecked(False)  # never replace art silently
        self._art_row.setVisible(True)

    def _fill_warning(self) -> None:
        chosen = self._result.chosen
        weak = chosen is not None and chosen.score < matching.MATCH_FLOOR
        if weak:
            self._warning.setText(
                self.tr(
                    "No confident match — check the release before applying."
                )
            )
        self._warning.setVisible(weak)

    # -------------------------------------------------------------- actions

    def _on_candidate_changed(self, index: int) -> None:
        if self._loading or index < 0:
            return
        candidate = self._candidate_combo.itemData(index)
        if isinstance(candidate, Candidate) and candidate is not self._result.chosen:
            self.candidate_requested.emit(candidate)

    def _art_offered(self) -> bool:
        """Whether the art row is part of this dialog.

        ``isHidden()``, never ``isVisible()``: the latter answers "is this on
        screen", which is False for every widget here once ``exec()`` has
        returned — and ``selected_values`` is read exactly then. Keying the
        approved art off visibility meant approved art was never written.
        """
        return not self._art_row.isHidden()

    def _select_all(self) -> None:
        for check in self._checks.values():
            check.setChecked(True)
        if self._art_offered():
            self._art_check.setChecked(True)

    def _select_none(self) -> None:
        for check in self._checks.values():
            check.setChecked(False)
        self._art_check.setChecked(False)

    def _sync_apply_enabled(self) -> None:
        self._apply_btn.setEnabled(bool(self._checks) or self._art_offered())

    def selected_values(self) -> dict[str, object]:
        """The approved values, by tag-field name.

        Includes ``artwork`` (raw bytes) when the art row was ticked. An empty
        dict means the user approved nothing, which the caller treats as a
        cancel — there is no such thing as writing zero fields.
        """
        proposed = self._proposed.as_fields() if self._proposed else {}
        values: dict[str, object] = {
            key: proposed[key]
            for key, check in self._checks.items()
            if check.isChecked() and key in proposed
        }
        if self._art_offered() and self._art_check.isChecked():
            values[ARTWORK_FIELD] = getattr(self._result, "artwork", b"")
        return values


def _scaled(pixmap: QPixmap) -> QPixmap:
    return pixmap.scaled(
        _ART_EDGE,
        _ART_EDGE,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _as_text(value: object) -> str:
    """A current tag value as the string the diff compares against."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()
