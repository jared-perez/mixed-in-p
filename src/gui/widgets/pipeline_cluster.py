"""The header's pipeline controls: three mini step toggles and the target.

The step toggles mirror the ones in the Rename, Convert and Analyze panels, so
the whole shape of a run is readable — and changeable — from wherever you
happen to be standing. MainWindow owns the state and reflects it into both
places; this widget only ever *asks*, through step_toggled.

The target playlist lives here rather than in Convert because it belongs to
the run, not to a step: a run that skips Convert entirely still ends in a
playlist. It shows while any step is on and collapses when none are, so a user
who has never turned the pipeline on never sees a field asking them to name
something.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QWidget

from ..convert_pipeline import STEP_ORDER
from .fitted_combo import FittedComboBox
from .pipeline_toggle import PipelineToggle

# The pipeline's playlist field. Stated rather than measured: it holds user
# data of no fixed length, so there is no width that fits every name, and a box
# that resized itself as playlists were renamed read as a glitch. Wide enough
# for the "Playlist name" placeholder in all eleven languages — rendered and
# looked at, not calculated.
PIPELINE_TARGET_WIDTH = 174


class PipelineCluster(QWidget):
    """Three mini step toggles plus the run's target playlist."""

    #: (step id, on) — a request, not a fact. MainWindow decides and reflects.
    step_toggled = Signal(str, bool)
    #: The target playlist changed (picked or typed).
    target_changed = Signal()
    #: The cluster got wider or narrower (the target field came or went). The
    #: header competes for that width, so it has to be told — a visibility
    #: change has no resize behind it to notice.
    shape_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # A bare QWidget container paints BG_DARK from the global QSS rule, so
        # it needs a name to hang a transparent background on.
        self.setObjectName("pipelineHeaderCluster")
        self._toggles: dict[str, PipelineToggle] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # A layout handed to a widget takes the Qt style default (6px) rather
        # than Theme.SPACING unless it is told, and this one is measured.
        layout.setSpacing(6)

        for step in STEP_ORDER:
            toggle = PipelineToggle.for_step(step, PipelineToggle.SIZE_MINI, self)
            toggle.toggled.connect(
                lambda on, step=step: self.step_toggled.emit(step, on)
            )
            layout.addWidget(toggle, alignment=Qt.AlignmentFlag.AlignVCenter)
            self._toggles[step] = toggle

        # Editable: picking an item targets that playlist, typing a name
        # creates one. The default completer would silently turn a typed name
        # into a pick, and the two have to stay distinguishable, so it is off.
        self._target = FittedComboBox()
        self._target.setObjectName("pipelineTarget")
        self._target.setEditable(True)
        self._target.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._target.setCompleter(None)
        # A stated width, and the items are stopped from driving it. An
        # editable combo sizes itself to its WIDEST ITEM by default, so the box
        # grew with whoever had the longest playlist name and changed size
        # whenever a playlist was renamed. A field you type into wants to stay
        # put; the popup is where the full names are read, and FittedComboBox
        # floors that at the box's own width.
        #
        # AdjustToContents, not the default AdjustToContentsOnFirstShow: the
        # hint is what the popup is floored at below, and "on first show" locks
        # it at whatever the list held when the widget was first shown — which
        # is nothing, because MainWindow feeds the playlists in afterwards.
        self._target.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._target.setFixedWidth(PIPELINE_TARGET_WIDTH)
        # The box is capped; the LIST must not be.
        self._target.set_popup_fits_contents(True)
        self._target.lineEdit().setPlaceholderText(self.tr("Playlist name"))
        self._target.setToolTip(
            self.tr("The playlist every pipeline run files its tracks into")
        )
        # Both carry a payload (an index, a string) that target_changed does
        # not take — connecting emit directly raises inside the event loop,
        # where it surfaces as a stray TypeError rather than a failed connect.
        self._target.currentIndexChanged.connect(lambda _i: self.target_changed.emit())
        self._target.editTextChanged.connect(lambda _t: self.target_changed.emit())
        layout.addWidget(self._target, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._sync_target_visible()

    # ----------------------------------------------------------- step toggles

    def step_enabled(self, step: str) -> bool:
        return self._toggles[step].isChecked()

    def any_step_enabled(self) -> bool:
        return any(t.isChecked() for t in self._toggles.values())

    def set_step_enabled(self, step: str, enabled: bool) -> None:
        """Reflect a step's state. Never acts — blocked so it cannot echo.

        The reflect-vs-act rule, and the reason there is one owner: without the
        block this would re-enter step_toggled, which MainWindow answers by
        reflecting again, and the two mirrors would write config at each other.
        """
        toggle = self._toggles[step]
        if toggle.isChecked() != enabled:
            blocked = toggle.blockSignals(True)
            toggle.setChecked(enabled)
            toggle.blockSignals(blocked)
        self._sync_target_visible()

    def set_controls_enabled(self, enabled: bool) -> None:
        """Lock the cluster while a run is in flight — it is already armed."""
        for toggle in self._toggles.values():
            toggle.setEnabled(enabled)
        self._target.setEnabled(enabled)

    def _sync_target_visible(self) -> None:
        """The target shows exactly when the pipeline has anything to do."""
        wanted = self.any_step_enabled()
        # isHidden(), not isVisible(): a widget in a window nobody has shown
        # yet is not visible, and this runs during startup.
        if (not self._target.isHidden()) == wanted:
            return
        self._target.setVisible(wanted)
        self.shape_changed.emit()

    # ------------------------------------------------------------ the target

    def pipeline_target(self) -> tuple[int | None, str]:
        """(node id, text) for the target.

        The id is set only when an existing playlist was picked from the list —
        typed text that happens to equal a listed name still reads as "create",
        which is why the completer is off.
        """
        text = self._target.currentText().strip()
        index = self._target.currentIndex()
        if index >= 0 and self._target.itemText(index) == text:
            node_id = self._target.itemData(index)
            if node_id is not None:
                return int(node_id), text
        return None, text

    def set_playlists(self, rows: list[tuple[int, str]]) -> None:
        """Fill the target list with (node_id, label) in tree order.

        The cluster never opens the library itself; MainWindow feeds it at
        startup and on every nodes_changed. A refill keeps whatever the user
        had — the same playlist if it survived, the same typed text if not.
        """
        picked_id, text = self.pipeline_target()
        blocked = self._target.blockSignals(True)
        self._target.clear()
        for node_id, label in rows:
            self._target.addItem(label, node_id)
        if picked_id is None or not self.select_node(picked_id):
            self._target.setCurrentIndex(-1)
            self._target.setEditText(text)
        self._target.blockSignals(blocked)

    def select_node(self, node_id: int) -> bool:
        """Point the field at a playlist by id. True when it was in the list.

        Called after a run creates a playlist, so the next Start reuses it
        instead of making a second one with the same name.
        """
        for i in range(self._target.count()):
            if self._target.itemData(i) == node_id:
                self._target.setCurrentIndex(i)
                return True
        return False

    def restore_pipeline_target(self, name: str) -> None:
        """Point the field at a remembered playlist.

        Called twice: once at startup (when the list is still empty, so the
        name can only be typed back) and again once MainWindow has fed the real
        playlists in, which is the pass that can resolve it.

        A name that still matches a playlist is *selected*, so the next Start
        reuses it. Only a name that matches nothing is set as edit text, which
        reads as "create". Setting the text alone would make a new numbered
        playlist on every launch.
        """
        if not name:
            return
        index = self._target.findText(name, Qt.MatchFlag.MatchExactly)
        if index >= 0:
            self._target.setCurrentIndex(index)
        else:
            self._target.setCurrentIndex(-1)
            self._target.setEditText(name)

    # ------------------------------------------------------------- measuring

    def width_hint(self) -> int:
        """What the cluster needs *as it is now*, target field included or not.

        The header's subtitle threshold is computed from this, so the choice
        matters: reserving room for the target whether or not it is showing
        would cost every user 80-odd pixels of subtitle for a feature that
        ships off. The cost of measuring the live shape instead is that the
        threshold moves when a step is toggled — which is why shape_changed
        exists, and why the subtitle giving way at that moment reads as the bar
        getting busier rather than as a glitch.

        isHidden(), not isVisible(): nothing in a window that has not been
        shown yet is visible, and this is asked during startup.
        """
        layout = self.layout()
        margins = layout.contentsMargins()
        widgets = [w for w in (*self._toggles.values(), self._target) if not w.isHidden()]
        if not widgets:
            return margins.left() + margins.right()
        return (
            sum(w.sizeHint().width() for w in widgets)
            + layout.spacing() * (len(widgets) - 1)
            + margins.left()
            + margins.right()
        )
