"""MainWindow's half of the pipeline: Start -> convert -> analyse.

The window methods are bound onto a stub with only the attributes they read —
the trick test_analysis_write_freeze.py uses. What is under test is the
routing, not a window.

Two of these earn their place. The awaiting-analysis map is keyed on the
*store's* spelling of a path (str(Path.resolve())), because that is what comes
back on an AnalysisResult, while the library keeps the normalized one — on
macOS the two differ for anything under /var, which is where tmp_path lives, so
a set built from the converter's strings would match nothing here and everything
on Linux. And a run is armed only after the busy check: armed before it, a
refused second batch would leave the run waiting for results that never come.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QObject

from src.conversion.result import ConversionResult
from src.gui.convert_pipeline import ConvertPipeline
from src.gui.main_window import MainWindow
from src.gui.models.state import TrackState
from src.gui.models.track_model import TrackStore
from src.library import Library
from src.utils.config import AppConfig


# ------------------------------------------------------------------ the stub


class _ProgressStub:
    def __init__(self):
        self.messages = []

    def start(self, total):
        self.messages.append(("start", total))

    def complete(self, text):
        self.messages.append(("complete", text))

    def cancelled(self):
        self.messages.append(("cancelled",))

    def set_error(self, text):
        self.messages.append(("error", text))

    def set_status(self, text):
        pass


class _PanelStub:
    """The Convert panel, reduced to what the window asks of it."""

    def __init__(self, enabled=True, target=(None, "Pipeline test"),
                 rows=((), ())):
        self.progress_panel = _ProgressStub()
        self._enabled = enabled
        self._target = target
        self._rows = rows
        self.forgotten = []
        self.selected = []
        self.controls_enabled = True
        self.converting = []
        self.marked = []

    def pipeline_enabled(self):
        return self._enabled

    def pipeline_target(self):
        return self._target

    def pipeline_rows(self):
        return [list(self._rows[0]), list(self._rows[1])]

    def forget_rows(self, paths):
        self.forgotten.append(list(paths))

    def select_node(self, node_id):
        self.selected.append(node_id)
        self._target = (node_id, self._target[1])
        return True

    def set_pipeline_controls_enabled(self, on):
        self.controls_enabled = on

    def set_pipeline_enabled(self, on):
        self._enabled = on

    def _effective_path(self, path):
        return path

    def mark_converting(self, paths):
        self.converting.append(list(paths))

    def mark_converted(self, results):
        self.marked.append(list(results))


class _SidebarStub:
    def __init__(self):
        self.busy = {}
        self.page = None
        self.badge = None

    def set_page_busy(self, page, busy):
        self.busy[page] = busy

    def set_current_page(self, page):
        self.page = page

    def set_auto_analyze_badge(self, on):
        self.badge = on


class _AnalysisPanelStub:
    def __init__(self):
        self.progress_panel = _ProgressStub()
        self.auto = None

    def set_analyzing(self, on):
        pass

    def set_auto_analyze(self, on):
        self.auto = on


class _SettingsPanelStub:
    def __init__(self):
        self.auto = None

    def set_auto_analyze(self, on):
        self.auto = on


class _TreeStub:
    def __init__(self):
        self.refreshed = 0

    def refresh(self):
        self.refreshed += 1


class _PlaylistsPanelStub:
    def __init__(self):
        self.tree = _TreeStub()
        self.loaded = 0

    def ensure_loaded(self):
        self.loaded += 1


class _FakeThread:
    """Records what a conversion would have been given; never starts."""

    instances = []

    def __init__(self, file_paths, target_format, bitrate, **kwargs):
        self.file_paths = list(file_paths)
        self.target_format = target_format
        self.kwargs = kwargs
        self.started = False
        _FakeThread.instances.append(self)
        for name in ("conversion_started", "conversion_progress",
                     "conversion_finished", "conversion_error",
                     "conversion_cancelled"):
            setattr(self, name, _Signalish())

    def isRunning(self):
        return self.started

    def start(self):
        self.started = True


class _Signalish:
    def connect(self, slot):
        pass


class WindowStub(QObject):
    """The real methods under test, over a minimal self."""

    _start_conversion = MainWindow._start_conversion
    _on_conversion_finished = MainWindow._on_conversion_finished
    _on_conversion_cancelled = MainWindow._on_conversion_cancelled
    _on_conversion_error = MainWindow._on_conversion_error
    _arm_pipeline = MainWindow._arm_pipeline
    _pipeline_analyse = MainWindow._pipeline_analyse
    _pipeline_analysis_idle = MainWindow._pipeline_analysis_idle
    _finish_pipeline_if_done = MainWindow._finish_pipeline_if_done
    _finish_pipeline_summary = MainWindow._finish_pipeline_summary
    _resolve_pipeline_target = MainWindow._resolve_pipeline_target
    _unique_playlist_name = MainWindow._unique_playlist_name
    _refresh_pipeline_playlists = MainWindow._refresh_pipeline_playlists
    _on_pipeline_toggled = MainWindow._on_pipeline_toggled
    _on_auto_analyze_toggled = MainWindow._on_auto_analyze_toggled

    def __init__(self, store, library, panel):
        super().__init__()
        self._store = store
        self._library = library
        self._config = AppConfig()
        self._pipeline = ConvertPipeline()
        self._conversion_panel = panel
        self._conversion_thread = None
        self._analysis_thread = None
        self._analyzing_track_ids = []
        self._pending_rename_operations = None
        self._sidebar = _SidebarStub()
        self._analysis_panel = _AnalysisPanelStub()
        self._settings_panel = _SettingsPanelStub()
        self._playlists_panel = _PlaylistsPanelStub()
        self.analysed = []
        self.page_changes = []

    def _start_analysis(self, track_ids):
        self.analysed.append(list(track_ids))
        if self._analysis_thread is not None and self._analysis_thread.isRunning():
            return  # mirrors the real early return: they stay PENDING
        for tid in track_ids:
            self._store.update(tid, state=TrackState.ANALYSING)

    def _on_conversion_started(self):
        pass

    def _on_conversion_progress(self, progress):
        pass

    def _on_page_changed(self, page):
        self.page_changes.append(page)

    def _persist_config(self):
        pass


@pytest.fixture
def library():
    lib = Library()
    yield lib
    lib.close()


def _window(library, panel=None, **panel_kw):
    panel = panel or _PanelStub(**panel_kw)
    return WindowStub(TrackStore(), library, panel), panel


def _fake_threads(monkeypatch):
    _FakeThread.instances = []
    monkeypatch.setattr("src.gui.main_window.ConversionThread", _FakeThread)
    return _FakeThread.instances


def _touch(tmp_path, name) -> str:
    p = tmp_path / name
    p.write_bytes(b"")
    return str(p)


# ---------------------------------------------------------- unique_playlist_name


def test_unique_name_is_the_bare_name_when_free(library):
    win, _ = _window(library)
    assert win._unique_playlist_name("Test") == "Test"


def test_unique_name_counts_up(library):
    win, _ = _window(library)
    library.create_playlist("Test")
    assert win._unique_playlist_name("Test") == "Test (1)"
    library.create_playlist("Test (1)")
    assert win._unique_playlist_name("Test") == "Test (2)"


def test_a_nested_namesake_counts(library):
    win, _ = _window(library)
    folder = library.create_folder("Gigs")
    library.create_playlist("Test", parent_id=folder)
    assert win._unique_playlist_name("Test") == "Test (1)"


def test_scratch_never_counts(library):
    win, _ = _window(library)
    from src.library import SCRATCH_NODE_ID

    scratch = library.get_node(SCRATCH_NODE_ID)
    assert scratch is not None
    assert win._unique_playlist_name(scratch.name) == scratch.name


# ------------------------------------------------------------ resolving a target


def test_a_pick_is_used_as_is(library):
    node_id = library.create_playlist("Set")
    win, panel = _window(library, target=(node_id, "Set"))
    assert win._resolve_pipeline_target() == (node_id, "Set")
    assert panel.selected == []  # nothing created


def test_typed_text_creates_once_then_the_combo_picks_it(library):
    win, panel = _window(library, target=(None, "Pipeline test"))
    first = win._resolve_pipeline_target()
    assert first is not None
    node_id, name = first
    assert name == "Pipeline test"
    assert panel.selected == [node_id]
    assert win._playlists_panel.tree.refreshed == 1
    # The panel now reports a pick, so a second Start reuses the playlist.
    assert win._resolve_pipeline_target() == (node_id, "Pipeline test")
    assert [n.name for n in library.get_children(None)] == ["Pipeline test"]


def test_blank_text_resolves_to_nothing(library):
    win, _ = _window(library, target=(None, ""))
    assert win._resolve_pipeline_target() is None


# ------------------------------------------------------------ the playlist feed


def test_the_combo_is_fed_every_playlist_with_folders_spelled_out(library, qtbot):
    from src.gui.models.track_model import TrackStore as _TS
    from src.gui.widgets.conversion_panel import ConversionPanel

    panel = ConversionPanel(_TS())
    qtbot.addWidget(panel)
    win = WindowStub(TrackStore(), library, panel)
    folder = library.create_folder("Gigs")
    nested = library.create_playlist("Friday", parent_id=folder)
    flat = library.create_playlist("Set")
    win._refresh_pipeline_playlists()
    labels = [panel._pipeline_target.itemText(i)
              for i in range(panel._pipeline_target.count())]
    ids = [panel._pipeline_target.itemData(i)
           for i in range(panel._pipeline_target.count())]
    assert "Gigs / Friday" in labels and "Set" in labels
    assert set(ids) == {nested, flat}


# ---------------------------------------------------------------- arming


def test_a_run_is_armed_only_after_the_busy_check(library, monkeypatch, tmp_path):
    threads = _fake_threads(monkeypatch)
    src = _touch(tmp_path, "a.wav")
    win, panel = _window(library, target=(None, "Pipeline test"), rows=([src], []))
    running = _FakeThread([], "FLAC", 320)
    running.started = True
    win._conversion_thread = running
    monkeypatch.setattr("src.gui.main_window.QMessageBox.warning",
                        lambda *a, **k: None)
    win._start_conversion([src], "FLAC")
    assert not win._pipeline.active
    assert len(threads) == 1  # only the one we planted


def test_start_arms_and_hands_the_converter_the_ready_rows(library, monkeypatch, tmp_path):
    threads = _fake_threads(monkeypatch)
    src = _touch(tmp_path, "a.wav")
    same = _touch(tmp_path, "b.flac")
    win, panel = _window(library, target=(None, "Pipeline test"),
                         rows=([src], [same]))
    win._start_conversion([src], "FLAC")
    assert threads[-1].file_paths == [src]
    assert win._pipeline.active
    # The same-format row leaves the Convert table at once, but it joins the
    # converted files in ONE analysis batch when the conversion finishes —
    # not a second batch of its own.
    assert panel.forgotten == [[same]]
    assert win._store.get_by_path(same) is None
    assert panel.controls_enabled is False
    out = _touch(tmp_path, "a.flac")
    win._on_conversion_finished([
        ConversionResult(source_path=src, output_path=out, target_format="FLAC")
    ])
    assert len(win.analysed) == 1 and len(win.analysed[0]) == 2
    assert win._store.get_by_path(same) is not None


def test_a_run_with_nothing_to_convert_skips_the_thread(library, monkeypatch, tmp_path):
    """A zero-file worker emits an error and no `finished`, so it never runs."""
    threads = _fake_threads(monkeypatch)
    same = _touch(tmp_path, "b.flac")
    win, panel = _window(library, target=(None, "Pipeline test"), rows=([], [same]))
    win._start_conversion([], "FLAC")
    assert threads == []
    assert win._store.get_by_path(same) is not None
    assert win.analysed and len(win.analysed[0]) == 1


def test_a_blank_target_starts_nothing(library, monkeypatch, tmp_path):
    threads = _fake_threads(monkeypatch)
    src = _touch(tmp_path, "a.wav")
    win, _ = _window(library, target=(None, ""), rows=([src], []))
    win._start_conversion([src], "FLAC")
    assert threads == []
    assert not win._pipeline.active


def test_the_pipeline_off_converts_as_before(library, monkeypatch, tmp_path):
    threads = _fake_threads(monkeypatch)
    src = _touch(tmp_path, "a.wav")
    win, _ = _window(library, enabled=False, rows=([src], []))
    win._start_conversion([src], "FLAC")
    assert threads[-1].file_paths == [src]
    assert not win._pipeline.active


# ---------------------------------------------------- conversion -> analysis


def test_outputs_reach_the_store_in_the_spelling_results_come_back_in(
    library, monkeypatch, tmp_path
):
    _fake_threads(monkeypatch)
    src = _touch(tmp_path, "a.wav")
    out = _touch(tmp_path, "a.flac")
    win, panel = _window(library, target=(None, "Pipeline test"), rows=([src], []))
    win._start_conversion([src], "FLAC")
    win._on_conversion_finished([
        ConversionResult(source_path=src, output_path=out, target_format="FLAC")
    ])
    track = win._store.get_by_path(out)
    assert track is not None
    # This is the trap: the store resolves, the library normalizes, and on
    # macOS tmp_path differs between the two.
    assert win._pipeline.analysis_batch_paths() == [track.file_path]
    assert win.analysed == [[track.id]]
    assert panel.forgotten[-1] == [src]


def test_a_failed_conversion_is_counted_not_forwarded(library, monkeypatch, tmp_path):
    _fake_threads(monkeypatch)
    a, b = _touch(tmp_path, "a.wav"), _touch(tmp_path, "b.wav")
    out = _touch(tmp_path, "a.flac")
    win, panel = _window(library, target=(None, "Pipeline test"), rows=([a, b], []))
    win._start_conversion([a, b], "FLAC")
    win._on_conversion_finished([
        ConversionResult(source_path=a, output_path=out, target_format="FLAC"),
        ConversionResult(source_path=b, output_path="", target_format="FLAC",
                         error="boom"),
    ])
    assert len(win._pipeline.analysis_batch_paths()) == 1
    assert win._pipeline.summary() == (0, 0, 1)


def test_a_cancelled_conversion_ends_the_run(library, monkeypatch, tmp_path):
    _fake_threads(monkeypatch)
    src = _touch(tmp_path, "a.wav")
    win, panel = _window(library, target=(None, "Pipeline test"), rows=([src], []))
    win._start_conversion([src], "FLAC")
    win._on_conversion_cancelled()
    assert not win._pipeline.active
    assert panel.controls_enabled is True
    assert win.analysed == []


def test_a_conversion_error_ends_the_run(library, monkeypatch, tmp_path):
    _fake_threads(monkeypatch)
    src = _touch(tmp_path, "a.wav")
    win, _ = _window(library, target=(None, "Pipeline test"), rows=([src], []))
    win._start_conversion([src], "FLAC")
    win._on_conversion_error("No files to convert")
    assert not win._pipeline.active


# ------------------------------------------------------------ manual chaining


def test_a_busy_analysis_leaves_the_batch_for_the_idle_hook(library, monkeypatch, tmp_path):
    """_start_analysis returns early while a thread runs; in manual mode
    nothing else would ever start those tracks."""
    _fake_threads(monkeypatch)
    same = _touch(tmp_path, "b.flac")
    win, _ = _window(library, target=(None, "Pipeline test"), rows=([], [same]))
    busy = _FakeThread([], "FLAC", 320)
    busy.started = True
    win._analysis_thread = busy
    win._config.auto_analyze = False

    win._start_conversion([], "FLAC")
    track = win._store.get_by_path(same)
    assert track.state == TrackState.PENDING
    assert win.analysed == [[track.id]]  # asked, and refused

    win._analysis_thread = None
    win._pipeline_analysis_idle()
    assert win.analysed[-1] == [track.id]
    assert track.state == TrackState.ANALYSING


def test_the_idle_hook_only_takes_this_run_s_files(library, monkeypatch, tmp_path):
    _fake_threads(monkeypatch)
    mine = _touch(tmp_path, "b.flac")
    stranger = _touch(tmp_path, "dropped.flac")
    win, _ = _window(library, target=(None, "Pipeline test"), rows=([], [mine]))
    busy = _FakeThread([], "FLAC", 320)
    busy.started = True
    win._analysis_thread = busy
    win._start_conversion([], "FLAC")

    other = win._store.add_from_path(stranger)
    win._store.update(other.id, state=TrackState.PENDING)
    win._analysis_thread = None
    win.analysed = []
    win._pipeline_analysis_idle()
    assert win.analysed == [[win._store.get_by_path(mine).id]]


# ---------------------------------------------------------------- coupling


def test_the_pipeline_going_on_turns_auto_analyze_on(library):
    win, panel = _window(library)
    win._config.auto_analyze = False
    win._on_pipeline_toggled(True)
    assert win._config.auto_analyze is True
    assert win._analysis_panel.auto is True
    assert win._settings_panel.auto is True
    assert win._sidebar.badge is True


def test_the_pipeline_going_off_leaves_auto_analyze_alone(library):
    win, _ = _window(library)
    win._config.auto_analyze = True
    win._on_pipeline_toggled(False)
    assert win._config.auto_analyze is True


def test_auto_analyze_going_off_turns_the_pipeline_off(library):
    win, panel = _window(library)
    win._on_auto_analyze_toggled(False)
    assert panel.pipeline_enabled() is False


def test_auto_analyze_going_on_leaves_the_pipeline_off(library):
    win, panel = _window(library, enabled=False)
    win._on_auto_analyze_toggled(True)
    assert panel.pipeline_enabled() is False
