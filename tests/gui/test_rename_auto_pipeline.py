"""Starting a pipeline run from a panel's own button.

A run starts wherever the user presses Start Pipeline and flows through the
*later* enabled steps only, always ending in the target playlist. What is worth
testing is the routing and the guards, not the pipeline behind them: a rename
that changes nothing must not go through _start_rename (it returns silently at
zero renames and the run would wait for a thread that never started), a run
reaching its Convert step must get past the re-arm guard that exists to refuse
a *second* run, and a run with Analyze off must still file its tracks.

Structure, never pixels: the suite runs with no application stylesheet.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QMessageBox

from src.gui.convert_pipeline import STEP_ANALYZE, STEP_CONVERT, STEP_RENAME
from src.gui.main_window import MainWindow
from src.gui.models.state import TrackState
from src.utils.config import AppConfig, save_config


def _wav(path, samplerate: int = 44100, subtype: str = "PCM_16") -> str:
    """A 0.1s tone — long enough for librosa, short enough for a suite."""
    sf = pytest.importorskip("soundfile")
    import numpy as np

    t = np.linspace(0, 0.1, int(samplerate * 0.1), endpoint=False)
    sf.write(str(path), (0.2 * np.sin(2 * np.pi * 440 * t)).astype("float32"),
             samplerate, subtype=subtype)
    return str(path)


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


@pytest.fixture
def popups(monkeypatch):
    """Catch the guard popups. An unclicked modal hangs the whole suite."""
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(
        MainWindow, "_warn_pipeline",
        lambda self, title, body: seen.append((title, body)),
    )
    return seen


def _queue(win, paths):
    """Put files in the Rename panel — QUEUED is that panel's working set."""
    for p in paths:
        win._store.add_from_path(p)
    win._rename_panel.refresh()


def _playlist(win, name):
    return next(n for n in win._library.get_children(None) if n.name == name)


# --------------------------------------------------------------- the guards


def test_a_start_with_no_files_says_so(window, popups):
    win = window(pipeline_rename_enabled=True, pipeline_playlist="Friday set")
    win._start_pipeline_from(STEP_RENAME)
    assert popups and popups[0][0] == "No Files"
    assert not win._pipeline.active


def test_a_start_with_no_target_says_so(window, popups, tmp_path):
    win = window(pipeline_rename_enabled=True, pipeline_playlist="")
    _queue(win, [_wav(tmp_path / "a.wav")])
    win._start_pipeline_from(STEP_RENAME)
    assert popups and "playlist" in popups[0][1]
    assert not win._pipeline.active


def test_a_start_during_the_analysis_tail_says_so(window, popups, tmp_path):
    win = window(pipeline_rename_enabled=True, pipeline_playlist="Friday set")
    _queue(win, [_wav(tmp_path / "a.wav")])
    win._pipeline.arm(1, "Elsewhere", passthrough=["/x.wav"])
    win._pipeline.await_analysis({"/x.wav": "/x.wav"})
    before = dict(win._pipeline.run.awaiting_analysis)

    win._start_pipeline_from(STEP_RENAME)

    assert popups and "still finishing" in popups[0][1]
    # The bug this guards is the orphaning: an unguarded second start replaces
    # ConvertPipeline.run wholesale and the first run's tracks never land.
    assert win._pipeline.run.awaiting_analysis == before
    assert win._pipeline.run.playlist_name == "Elsewhere"


def test_a_conversion_in_flight_blocks_a_start(window, popups, tmp_path):
    win = window(pipeline_rename_enabled=True, pipeline_playlist="Friday set")
    _queue(win, [_wav(tmp_path / "a.wav")])

    class _Running:
        def isRunning(self):
            return True

    win._conversion_thread = _Running()
    try:
        win._start_pipeline_from(STEP_RENAME)
        assert popups and "conversion is already running" in popups[0][1]
        assert not win._pipeline.active
    finally:
        win._conversion_thread = None


# ------------------------------------------------ the no-adjustments question


def test_a_rename_with_nothing_to_change_asks_first(window, monkeypatch, tmp_path):
    win = window(pipeline_rename_enabled=True, pipeline_playlist="Friday set")
    _queue(win, [_wav(tmp_path / "a.wav")])
    asked = []
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.No,
    )
    win._start_pipeline_from(STEP_RENAME)
    assert asked and "unchanged" in asked[0]
    assert not win._pipeline.active  # No means no


def test_saying_yes_sends_the_files_on_unrenamed(window, monkeypatch, tmp_path):
    """And never through _start_rename, which returns silently at zero renames
    — the run would then wait for a thread that never started."""
    win = window(pipeline_rename_enabled=True, pipeline_playlist="Friday set")
    _queue(win, [_wav(tmp_path / "a.wav")])
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    started = []
    monkeypatch.setattr(MainWindow, "_start_rename",
                        lambda self, p, o: started.append(True))
    forwarded = []
    monkeypatch.setattr(MainWindow, "_pipeline_advance",
                        lambda self, step, paths: forwarded.append((step, paths)))

    win._start_pipeline_from(STEP_RENAME)

    assert started == []
    assert forwarded and forwarded[0][0] == STEP_RENAME
    assert forwarded[0][1] == [str(tmp_path / "a.wav")]


def test_a_configured_rename_is_not_questioned(window, monkeypatch, tmp_path):
    win = window(pipeline_rename_enabled=True, pipeline_playlist="Friday set")
    _queue(win, [_wav(tmp_path / "a.wav")])
    win._rename_panel._prepend_edit.setText("128 - ")
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(1))
    monkeypatch.setattr(MainWindow, "_start_rename", lambda self, p, o: None)
    win._start_pipeline_from(STEP_RENAME)
    assert asked == []


# ------------------------------------------------------------- step routing


def test_the_run_records_only_the_enabled_steps(window, monkeypatch, tmp_path):
    win = window(pipeline_rename_enabled=True, pipeline_analyze_enabled=True,
                 pipeline_playlist="Friday set")
    _queue(win, [_wav(tmp_path / "a.wav")])
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(MainWindow, "_pipeline_advance", lambda self, s, p: None)

    win._start_pipeline_from(STEP_RENAME)

    assert win._pipeline.run.steps == {STEP_RENAME, STEP_ANALYZE}
    # Convert is off, so rename hands straight to analyze.
    assert win._pipeline.next_step(STEP_RENAME) == STEP_ANALYZE


def test_a_toggle_flipped_mid_run_does_not_reroute_it(window, monkeypatch, tmp_path):
    """The steps are a snapshot taken at arming."""
    win = window(pipeline_rename_enabled=True, pipeline_playlist="Friday set")
    _queue(win, [_wav(tmp_path / "a.wav")])
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(MainWindow, "_pipeline_advance", lambda self, s, p: None)
    win._start_pipeline_from(STEP_RENAME)

    win._on_pipeline_step_toggled(STEP_CONVERT, True)
    assert win._pipeline.run.steps == {STEP_RENAME}
    assert win._pipeline.next_step(STEP_RENAME) is None


# -------------------------------------------------------- rename -> playlist


def test_rename_only_files_the_tracks_un_analysed(window, monkeypatch, qtbot, tmp_path):
    """No convert, no analyze: the direct-add leg, which is the whole reason
    the playlist is not itself a step."""
    win = window(pipeline_rename_enabled=True, pipeline_playlist="Friday set")
    paths = [_wav(tmp_path / f"{n}.wav") for n in ("a", "b")]
    _queue(win, paths)
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)

    win._start_pipeline_from(STEP_RENAME)
    qtbot.waitUntil(lambda: not win._pipeline.active, timeout=10000)

    members = win._library.get_items(_playlist(win, "Friday set").id)
    assert sorted(m.path for m in members) == sorted(paths)


def test_a_real_rename_forwards_the_new_names(window, monkeypatch, qtbot, tmp_path):
    win = window(pipeline_rename_enabled=True, pipeline_playlist="Friday set")
    _queue(win, [_wav(tmp_path / "a.wav")])
    win._rename_panel._prepend_edit.setText("128 - ")
    assert win._rename_panel.has_rename_changes()

    win._start_pipeline_from(STEP_RENAME)
    qtbot.waitUntil(lambda: not win._pipeline.active, timeout=10000)

    members = win._library.get_items(_playlist(win, "Friday set").id)
    assert [p.name for p in map(__import__("pathlib").Path,
                                (m.path for m in members))] == ["128 - a.wav"]


# ------------------------------------------------------- rename -> convert


def test_the_convert_leg_gets_past_the_re_arm_guard(window, monkeypatch, tmp_path):
    """A continuation presses the panel's own button, so it arrives at
    _start_conversion looking exactly like a second Start."""
    win = window(pipeline_rename_enabled=True, pipeline_convert_enabled=True,
                 pipeline_playlist="Friday set")
    paths = [_wav(tmp_path / "a.wav")]
    _queue(win, paths)
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    warned = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warned.append(a[2] if len(a) > 2 else ""))

    win._start_pipeline_from(STEP_RENAME)

    assert warned == []  # not refused for being its own run
    assert win._current_page == "convert"
    assert win._conversion_panel._file_paths == []  # forwarded onward already


def test_the_convert_leg_says_so_when_lossy_files_cannot_travel(
    window, monkeypatch, tmp_path
):
    win = window(pipeline_rename_enabled=True, pipeline_convert_enabled=True,
                 pipeline_playlist="Friday set")
    _queue(win, [_wav(tmp_path / "a.wav"), str(tmp_path / "b.mp3")])
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(type(win._conversion_panel), "press_convert",
                        lambda self: None)

    win._start_pipeline_from(STEP_RENAME)

    assert "Lossy files stayed in Convert" in win._conversion_panel._lossy_notice.text()


def test_a_lossless_only_batch_gets_no_notice(window, monkeypatch, tmp_path):
    win = window(pipeline_rename_enabled=True, pipeline_convert_enabled=True,
                 pipeline_playlist="Friday set")
    _queue(win, [_wav(tmp_path / "a.wav")])
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(type(win._conversion_panel), "press_convert",
                        lambda self: None)
    win._start_pipeline_from(STEP_RENAME)
    assert win._conversion_panel._lossy_notice.isHidden()


def test_the_convert_leg_presses_the_panels_own_button(window, monkeypatch, tmp_path):
    """Never a second arming path: everything the pipeline guarantees lives
    behind _on_convert_clicked."""
    win = window(pipeline_rename_enabled=True, pipeline_convert_enabled=True,
                 pipeline_playlist="Friday set")
    _queue(win, [_wav(tmp_path / "a.wav")])
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    seen = []
    monkeypatch.setattr(type(win._conversion_panel), "_on_convert_clicked",
                        lambda self: seen.append(True))
    win._start_pipeline_from(STEP_RENAME)
    assert seen == [True]


# ------------------------------------------------------------- start at Analyze


def test_an_analyze_start_analyses_and_files(window, qtbot, tmp_path):
    win = window(pipeline_analyze_enabled=True, pipeline_playlist="Friday set")
    paths = [_wav(tmp_path / f"{n}.wav") for n in ("a", "b")]
    for p in paths:
        track = win._store.add_from_path(p)
        win._store.update(track.id, state=TrackState.PENDING)

    win._start_pipeline_from(STEP_ANALYZE)
    qtbot.waitUntil(lambda: not win._pipeline.active, timeout=60000)

    members = win._library.get_items(_playlist(win, "Friday set").id)
    assert len(members) == 2


def test_an_already_analysed_row_is_filed_without_re_analysing(
    window, monkeypatch, qtbot, tmp_path
):
    """Six seconds a file to find what it already found."""
    win = window(pipeline_analyze_enabled=True, pipeline_playlist="Friday set")
    path = _wav(tmp_path / "a.wav")
    track = win._store.add_from_path(path)
    win._store.update(track.id, state=TrackState.ANALYSED)
    analysed = []
    monkeypatch.setattr(MainWindow, "_start_analysis",
                        lambda self, ids: analysed.append(list(ids)))

    win._start_pipeline_from(STEP_ANALYZE)
    qtbot.waitUntil(lambda: not win._pipeline.active, timeout=10000)

    assert analysed == []
    members = win._library.get_items(_playlist(win, "Friday set").id)
    assert [m.path for m in members] == [path]
