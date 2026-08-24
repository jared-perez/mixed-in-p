"""The Analyze panel's session write-freeze.

Freezing holds everything analysis would write to the user's files — the
BPM/key tags, the energy/key comment, and auto-rename on *both* the finished
and the cancelled path — while leaving the results themselves alone: the row
still updates, the table still shows it, the history JSON still records it.

The freeze is session state and touches no setting, which is the whole point:
"restore what was switched on" needs nothing restoring, because nothing was
switched off. The tests below assert that too — a freeze that quietly wrote to
AppConfig would pass every behavioural test here and strand a user's settings
on a crash.

The window-level tests drive the real ``MainWindow`` methods against a stub,
the trick ``test_open_files.py`` uses: what is under test is the gating, not a
window.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QObject

from src.analysis import history as analysis_history
from src.analysis.result import AnalysisResult
from src.gui.convert_pipeline import ConvertPipeline
from src.gui.main_window import MainWindow
from src.gui.models.state import TrackState
from src.gui.models.track_model import TrackStore
from src.gui.widgets.analysis_panel import AnalysisPanel
from src.metadata import read_metadata
from src.utils.config import AppConfig


# ── The toggle itself ───────────────────────────────────────────


@pytest.fixture
def panel(qtbot):
    p = AnalysisPanel(TrackStore())
    qtbot.addWidget(p)
    return p


class TestTheToggle:
    def test_a_session_always_starts_unfrozen(self, panel):
        """Session-scoped by definition: there is nowhere for it to persist."""
        assert panel.writes_frozen is False
        assert panel._freeze_btn.isChecked() is False

    def test_clicking_it_freezes_and_announces(self, panel, qtbot):
        with qtbot.waitSignal(panel.write_freeze_toggled) as sig:
            panel._freeze_btn.click()

        assert sig.args == [True]
        assert panel.writes_frozen is True

    def test_clicking_again_thaws(self, panel, qtbot):
        panel._freeze_btn.click()
        with qtbot.waitSignal(panel.write_freeze_toggled) as sig:
            panel._freeze_btn.click()

        assert sig.args == [False]
        assert panel.writes_frozen is False

    def test_the_tooltip_says_what_the_next_click_does(self, panel):
        """A checked button alone doesn't convey which way it is pointing."""
        off = panel._freeze_btn.toolTip()
        panel._freeze_btn.click()
        on = panel._freeze_btn.toolTip()

        assert off and on and off != on
        assert "Stop" in off
        assert "again" in on

    def test_it_reads_differently_from_the_Auto_toggle(self, panel):
        """Frozen must not look like one more thing switched on: separate
        objectName, so the stylesheet can fill it a different colour."""
        assert panel._freeze_btn.objectName() == "freezeToggle"
        assert panel._auto_btn.objectName() == "autoToggle"

    def test_it_is_styled_as_a_warning_rather_than_an_accent(self):
        from src.gui.app import load_stylesheet
        from src.gui.styles.theme import Theme

        qss = load_stylesheet()
        checked = qss.split("QPushButton#freezeToggle:checked {")[1].split("}")[0]
        assert Theme.WARNING in checked
        assert Theme.NEON_YELLOW not in checked


# ── The gates in MainWindow ─────────────────────────────────────


@pytest.fixture
def flac_file(tmp_path):
    """A real FLAC — it can actually hold BPM and key, so "were the tags
    written?" is answered from the file rather than from a mock."""
    sf = pytest.importorskip("soundfile")
    path = tmp_path / "track.flac"
    sf.write(str(path), np.zeros(4410, dtype=np.float32), 44100, format="FLAC")
    return str(path)


class PanelStub(QObject):
    """The bits of AnalysisPanel the write path reads."""

    def __init__(self):
        super().__init__()
        self.auto_write_bpm = True
        self.auto_write_key = True
        self.refreshed = 0
        self.analyzing = None
        self.progress_panel = _ProgressStub()

    def refresh_table(self):
        self.refreshed += 1

    def set_analyzing(self, running):
        self.analyzing = running


class _SidebarStub:
    """The end-of-batch handlers stop the Analyze nav glyph spinning."""

    def __init__(self):
        self.busy: dict[str, bool] = {}

    def set_page_busy(self, page_id, busy):
        self.busy[page_id] = busy


class _ProgressStub:
    def __init__(self):
        self.messages = []

    def complete(self, text):
        self.messages.append(text)

    def cancelled(self):
        self.messages.append("cancelled")


class _ConversionPanelStub:
    """Only what the pipeline's summary line touches."""

    def __init__(self):
        self.progress_panel = _ProgressStub()


class WindowStub(QObject):
    """The real gating methods, run against a minimal self."""

    _update_track_from_result = MainWindow._update_track_from_result
    _on_analysis_finished = MainWindow._on_analysis_finished
    _on_analysis_cancelled = MainWindow._on_analysis_cancelled
    _on_write_freeze_toggled = MainWindow._on_write_freeze_toggled
    _pipeline_analysis_idle = MainWindow._pipeline_analysis_idle
    _finish_pipeline_if_done = MainWindow._finish_pipeline_if_done
    _finish_pipeline_summary = MainWindow._finish_pipeline_summary

    def __init__(self, store):
        super().__init__()
        self._store = store
        self._config = AppConfig()
        self._config.key_in_comment_enabled = True  # exercise the comment write too
        self._analysis_panel = PanelStub()
        self._sidebar = _SidebarStub()
        self._analysis_writes_frozen = False
        self._analyzing_track_ids = []
        self._analysis_thread = None
        self._pending_rename_operations = []
        # The analysis end paths now consult the pipeline; an unarmed one is
        # inert, which is what every test in this file wants.
        self._pipeline = ConvertPipeline()
        self._conversion_panel = _ConversionPanelStub()
        self.renamed = []

    def _auto_rename_after_analysis(self, results):
        self.renamed.append(results)

    def _start_pending_analysis(self):
        pass

    def _persist_config(self):  # pragma: no cover — must never run
        raise AssertionError("the write-freeze must not touch stored settings")


@pytest.fixture
def window(flac_file):
    store = TrackStore()
    store.add_from_path(flac_file)
    return WindowStub(store)


def result_for(path, energy=7):
    return AnalysisResult(
        file_path=path,
        bpm=128.0,
        bpm_confidence=0.9,
        key="Am",
        key_confidence=0.8,
        keycode="8A",
        energy=energy,
    )


class TestTagWrites:
    def test_frozen_leaves_the_file_alone(self, window, flac_file):
        window._analysis_writes_frozen = True
        window._update_track_from_result(result_for(flac_file))

        tags = read_metadata(flac_file)
        assert not tags.bpm
        assert not tags.key
        assert not tags.comment

    def test_unfrozen_writes_them(self, window, flac_file):
        """The control: without it, the test above passes against a FLAC that
        was never going to keep a tag anyway."""
        window._update_track_from_result(result_for(flac_file))

        tags = read_metadata(flac_file)
        assert tags.bpm == 128.0
        assert tags.key == "8A"
        assert "8A" in (tags.comment or "")

    def test_the_result_still_lands_while_frozen(self, window, flac_file):
        """A freeze pauses writing, not analysing — the user still gets the
        readout they asked for."""
        window._analysis_writes_frozen = True
        window._update_track_from_result(result_for(flac_file))

        track = window._store.get_by_path(flac_file)
        assert track.state == TrackState.ANALYSED
        assert track.bpm == 128.0
        assert track.keycode == "8A"
        assert track.energy == 7

    def test_the_history_json_still_records_it_while_frozen(self, window, flac_file):
        """Not a write to the user's files — it is the app's own log, and the
        Analyze history would otherwise have a hole in it."""
        window._analysis_writes_frozen = True
        window._update_track_from_result(result_for(flac_file))

        entries = analysis_history.load_entries()
        assert [e["file_path"] for e in entries] == [flac_file]

    def test_thawing_mid_session_writes_the_next_run(self, window, flac_file):
        window._analysis_writes_frozen = True
        window._update_track_from_result(result_for(flac_file))
        assert not read_metadata(flac_file).bpm

        window._on_write_freeze_toggled(False)
        window._update_track_from_result(result_for(flac_file))

        assert read_metadata(flac_file).bpm == 128.0

    def test_an_error_result_is_unaffected_by_the_freeze(self, window, flac_file):
        """It never reached the write block in the first place."""
        window._analysis_writes_frozen = True
        window._update_track_from_result(
            AnalysisResult(
                file_path=flac_file, bpm=0.0, bpm_confidence=0.0, key="",
                key_confidence=0.0, keycode="", error="broken",
            )
        )

        track = window._store.get_by_path(flac_file)
        assert track.state == TrackState.ERROR


class TestAutoRenameGates:
    def test_frozen_skips_the_rename_on_a_normal_finish(self, window, flac_file):
        window._analysis_writes_frozen = True
        window._on_analysis_finished([result_for(flac_file)])

        assert window.renamed == []

    def test_unfrozen_still_renames_on_a_normal_finish(self, window, flac_file):
        window._on_analysis_finished([result_for(flac_file)])

        assert len(window.renamed) == 1

    def test_frozen_skips_the_rename_after_a_cancel(self, window, flac_file):
        """A cancel's follow-through renames the files that did complete — so
        it is a write path, and the freeze has to cover it too. This gate was
        added separately from the one above and is the easy one to miss.
        """
        track = window._store.get_by_path(flac_file)
        window._store.update(track.id, state=TrackState.ANALYSED, bpm=128.0, keycode="8A")
        window._analyzing_track_ids = [track.id]
        window._analysis_writes_frozen = True

        window._on_analysis_cancelled()

        assert window.renamed == []

    def test_unfrozen_still_renames_after_a_cancel(self, window, flac_file):
        track = window._store.get_by_path(flac_file)
        window._store.update(track.id, state=TrackState.ANALYSED, bpm=128.0, keycode="8A")
        window._analyzing_track_ids = [track.id]

        window._on_analysis_cancelled()

        assert len(window.renamed) == 1

    def test_a_cancel_while_frozen_still_requeues_the_unfinished(self, window, flac_file):
        """The freeze must not disturb what the cancel path does to state."""
        track = window._store.get_by_path(flac_file)
        window._store.update(track.id, state=TrackState.ANALYSING)
        window._analyzing_track_ids = [track.id]
        window._analysis_writes_frozen = True

        window._on_analysis_cancelled()

        assert window._store.get(track.id).state == TrackState.PENDING


class TestItIsSessionOnly:
    def test_toggling_persists_nothing(self, window):
        """WindowStub._persist_config raises. Belt and braces: the config on
        disk is unchanged too."""
        from src.utils.config import load_config

        before = load_config()
        window._on_write_freeze_toggled(True)
        window._on_write_freeze_toggled(False)

        assert load_config() == before

    def test_the_flag_is_the_only_state(self, window):
        window._on_write_freeze_toggled(True)
        assert window._analysis_writes_frozen is True
        window._on_write_freeze_toggled(False)
        assert window._analysis_writes_frozen is False
