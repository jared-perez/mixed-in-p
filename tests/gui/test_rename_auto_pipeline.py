"""Auto Pipeline: the Rename panel's third Send To action.

It adds the queued rows to Convert and presses the same Start the user would,
so what is worth testing is the seam, not the pipeline behind it: the action's
readiness is *pulled* on every menu open, the gesture degrades to a plain Send
To when readiness has moved since the menu was drawn, and the run goes through
press_convert rather than a second arming path.

Never open the menu. QMenu.exec is unpatchable from Python (PySide6 resolves it
through C++), so a test that shows one hangs the suite with no output —
aboutToShow is emitted by hand and actions are triggered as objects.

Structure, never pixels: the suite runs with no application stylesheet.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QMessageBox

from src.gui.main_window import MainWindow
from src.gui.models.state import TrackState
from src.gui.models.track_model import TrackStore
from src.gui.widgets.rename_panel import RenamePanel
from src.utils.config import AppConfig, save_config

NOT_SET_UP = "Set pipeline settings in the Convert panel first."
CONVERTING = "A conversion is already running."
TAIL = "The last pipeline run is still finishing."


def _wav(path, samplerate: int = 44100, subtype: str = "PCM_16") -> str:
    """A 0.1s tone — long enough for librosa, short enough for a suite."""
    sf = pytest.importorskip("soundfile")
    import numpy as np

    t = np.linspace(0, 0.1, int(samplerate * 0.1), endpoint=False)
    sf.write(str(path), (0.2 * np.sin(2 * np.pi * 440 * t)).astype("float32"),
             samplerate, subtype=subtype)
    return str(path)


# --------------------------------------------------------------- the panel


@pytest.fixture
def panel(qtbot):
    widget = RenamePanel(TrackStore())
    qtbot.addWidget(widget)
    return widget


def test_the_action_sits_after_analyze_in_the_send_to_menu(panel):
    labels = [a.text() for a in panel._send_to_menu.actions()]
    assert labels == ["Convert", "Analyze", "Auto Pipeline"]


def test_the_menu_shows_action_tooltips(panel):
    """Off by default in Qt, which would leave the greyed action mute."""
    assert panel._send_to_menu.toolTipsVisible()


def test_the_action_starts_disabled_and_says_why(panel):
    """Nobody has answered the query yet — a panel with no MainWindow behind
    it must not offer a run it cannot start."""
    assert not panel._send_to_pipeline_action.isEnabled()
    assert panel._send_to_pipeline_action.toolTip() == NOT_SET_UP


def test_the_setter_greys_the_action_and_shows_the_reason(panel):
    panel.set_auto_pipeline_ready(False, CONVERTING)
    assert not panel._send_to_pipeline_action.isEnabled()
    assert panel._send_to_pipeline_action.toolTip() == CONVERTING


def test_the_setter_enables_and_names_the_target(panel):
    panel.set_auto_pipeline_ready(True, "Friday set")
    action = panel._send_to_pipeline_action
    assert action.isEnabled()
    assert '"Friday set"' in action.toolTip()


def test_opening_the_menu_asks_for_the_state(panel, qtbot):
    with qtbot.waitSignal(panel.auto_pipeline_state_query, timeout=100):
        panel._send_to_menu.aboutToShow.emit()


def test_the_action_sends_every_queued_row_and_empties_the_store(panel, tmp_path, qtbot):
    store = panel._store
    paths = [str(tmp_path / f"{n}.wav") for n in ("a", "b")]
    for p in paths:
        store.add_from_path(p)
    # An analysed row belongs to the Analyze panel, not to this queue.
    other = store.add_from_path(str(tmp_path / "c.wav"))
    store.update(other.id, state=TrackState.ANALYSED)

    panel.set_auto_pipeline_ready(True, "Friday set")
    with qtbot.waitSignal(panel.send_to_auto_pipeline, timeout=100) as blocker:
        panel._send_to_pipeline_action.trigger()

    assert sorted(blocker.args[0]) == sorted(paths)
    assert store.get_by_state(TrackState.QUEUED) == []
    assert store.get_by_path(str(tmp_path / "c.wav")) is not None


# ---------------------------------------------------------- the whole window


def _window(qtbot, **cfg):
    """A real MainWindow over a throwaway config (never patch load_config)."""
    cfg.setdefault("convert_target_format", "WAV")
    cfg.setdefault("convert_sample_rate", 44100)
    cfg.setdefault("convert_bit_depth", 16)
    save_config(AppConfig(**cfg))
    win = MainWindow()
    qtbot.addWidget(win)
    return win


@pytest.fixture
def window(qtbot):
    made = []

    def build(**cfg):
        win = _window(qtbot, **cfg)
        made.append(win)
        return win

    yield build
    for win in made:
        win._player_panel.shutdown_workers()


def _queue(win, paths):
    for p in paths:
        win._store.add_from_path(p)


def _ask(win):
    """Drive the pull the way opening the menu does."""
    win._rename_panel._send_to_menu.aboutToShow.emit()
    return win._rename_panel._send_to_pipeline_action


def test_the_query_greys_the_action_when_the_pipeline_is_off(window):
    win = window(pipeline_convert_enabled=False,
                 pipeline_playlist="Friday set")
    action = _ask(win)
    assert not action.isEnabled()
    assert action.toolTip() == NOT_SET_UP


def test_the_query_greys_the_action_when_the_target_is_blank(window):
    win = window(pipeline_convert_enabled=True, pipeline_playlist="")
    action = _ask(win)
    assert not action.isEnabled()
    assert action.toolTip() == NOT_SET_UP


def test_the_query_enables_the_action_when_the_pipeline_is_set_up(window):
    win = window(pipeline_convert_enabled=True,
                 pipeline_playlist="Friday set")
    action = _ask(win)
    assert action.isEnabled()
    assert '"Friday set"' in action.toolTip()


def test_the_query_reports_an_analysis_tail(window):
    win = window(pipeline_convert_enabled=True,
                 pipeline_playlist="Friday set")
    win._pipeline.arm(1, "Friday set", ["/x.wav"], [])
    assert win._pipeline.active
    action = _ask(win)
    assert not action.isEnabled()
    assert action.toolTip() == TAIL


def test_a_conversion_in_flight_greys_the_action(window, monkeypatch):
    win = window(pipeline_convert_enabled=True,
                 pipeline_playlist="Friday set")

    class _Running:
        def isRunning(self):
            return True

    win._conversion_thread = _Running()
    try:
        action = _ask(win)
        assert not action.isEnabled()
        assert action.toolTip() == CONVERTING
    finally:
        win._conversion_thread = None


def test_the_gesture_converts_analyses_and_files_the_tracks(window, qtbot, tmp_path):
    """End to end on an all-passthrough batch: WAVs into a WAV pipeline, so
    there is no conversion thread and the run goes straight to analysis."""
    win = window(pipeline_convert_enabled=True,
                 pipeline_playlist="Friday set")
    paths = [_wav(tmp_path / f"{n}.wav") for n in ("a", "b")]
    _queue(win, paths)

    action = _ask(win)
    assert action.isEnabled()
    action.trigger()

    # The Rename panel has handed its rows on — a Send To is a panel move.
    assert win._store.get_by_state(TrackState.QUEUED) == []
    assert win._pipeline.active

    qtbot.waitUntil(lambda: not win._pipeline.active, timeout=60000)

    node = next(n for n in win._library.get_children(None) if n.name == "Friday set")
    members = win._library.get_items(node.id)
    assert len(members) == 2


def test_a_run_that_is_no_longer_ready_falls_back_to_send_to_convert(window, tmp_path):
    """State can move between the menu opening and the click. The files land
    in Convert either way, and the panel says why nothing started."""
    win = window(pipeline_convert_enabled=True,
                 pipeline_playlist="Friday set")
    paths = [str(tmp_path / "a.wav")]
    win._pipeline.arm(1, "Elsewhere", ["/x.wav"], [])

    # A disabled QAction swallows trigger(), so drive the slot the signal
    # would have reached.
    win._send_rename_to_auto_pipeline(paths)

    assert win._conversion_panel._file_paths == paths
    assert win._current_page == "convert"
    assert win._pipeline.run is not None
    assert win._pipeline.run.playlist_name == "Elsewhere"  # untouched
    assert win._conversion_panel._lossy_notice.text() == TAIL


def test_lossy_files_get_a_word_because_the_pipeline_will_not_take_them(
    window, tmp_path, monkeypatch
):
    win = window(pipeline_convert_enabled=True,
                 pipeline_playlist="Friday set")
    pressed = []
    monkeypatch.setattr(type(win._conversion_panel), "press_convert",
                        lambda self: pressed.append(True))
    paths = [_wav(tmp_path / "a.wav"), str(tmp_path / "b.mp3")]

    win._send_rename_to_auto_pipeline(paths)

    assert pressed == [True]
    assert "Lossy files stayed in Convert" in win._conversion_panel._lossy_notice.text()


def test_a_lossless_only_batch_gets_no_notice(window, tmp_path, monkeypatch):
    win = window(pipeline_convert_enabled=True,
                 pipeline_playlist="Friday set")
    monkeypatch.setattr(type(win._conversion_panel), "press_convert",
                        lambda self: None)
    win._send_rename_to_auto_pipeline([_wav(tmp_path / "a.wav")])
    assert win._conversion_panel._lossy_notice.isHidden()


def test_the_gesture_presses_the_panels_own_button(window, tmp_path, monkeypatch):
    """Never a second arming path: everything the pipeline guarantees lives
    behind _on_convert_clicked."""
    win = window(pipeline_convert_enabled=True,
                 pipeline_playlist="Friday set")
    seen = []
    monkeypatch.setattr(type(win._conversion_panel), "_on_convert_clicked",
                        lambda self: seen.append(True))
    win._send_rename_to_auto_pipeline([_wav(tmp_path / "a.wav")])
    assert seen == [True]


# ------------------------------------------------- W4: the re-arm guard


def test_starting_again_during_the_analysis_tail_leaves_the_first_run_intact(
    window, tmp_path, monkeypatch
):
    """Conversion done, analyses still landing: Start is enabled again, and
    arming a second run would replace ConvertPipeline.run wholesale — the
    first run's tracks would finish analysing and never reach the playlist."""
    win = window(pipeline_convert_enabled=True,
                 pipeline_playlist="Friday set")
    win._pipeline.arm(1, "Friday set", [], ["/a.wav"])
    win._pipeline.await_analysis({"/a.wav": "/a.wav"})
    before = dict(win._pipeline.run.awaiting_analysis)
    assert before

    warned = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warned.append(a[2] if len(a) > 2 else ""))

    win._start_conversion([str(tmp_path / "b.wav")], "WAV")

    # The bug this guards is the orphaning, so assert that first: an
    # unguarded second Start replaces ConvertPipeline.run wholesale.
    assert win._pipeline.run.awaiting_analysis == before
    assert win._pipeline.run.playlist_name == "Friday set"
    assert warned and "still finishing" in warned[0]
