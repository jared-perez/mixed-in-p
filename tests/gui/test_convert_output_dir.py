"""Convert writes beside the source unless the user names a folder.

The engine has taken an ``output_dir`` all along (the CLI's ``-o``); only the
panel had no way to say one. The destination is a mode plus a remembered
folder: the Source toggle decides which is in force, and the folder survives
the toggle so switching back is one click rather than a second trip through the
file dialog.

These cover the round trip — pick a folder, it is shown, persisted, passed down
to ``convert_file``, and can be given back — plus the ways a stored folder goes
bad: deleted between sessions, deleted mid-session, and unwritable at the
moment Convert is pressed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from src.gui.models.track_model import TrackStore
from src.gui.widgets.conversion_panel import ConversionPanel
from src.utils.config import AppConfig, load_config, save_config


def _write(path, samplerate: int = 44100, subtype: str = "PCM_16") -> str:
    sf = pytest.importorskip("soundfile")
    import numpy as np

    t = np.linspace(0, 0.1, int(samplerate * 0.1), endpoint=False)
    sf.write(str(path), (0.2 * np.sin(2 * np.pi * 440 * t)).astype("float32"),
             samplerate, subtype=subtype)
    return str(path)


def _panel(qtbot, **cfg) -> ConversionPanel:
    # Settings must be on disk before the widget reads them in __init__.
    save_config(AppConfig(convert_target_format="AIFF", **cfg))
    widget = ConversionPanel(TrackStore())
    qtbot.addWidget(widget)
    return widget


def _no_dialog(panel, monkeypatch, returns: str = "") -> list:
    """Stand in for the folder picker, recording that it was raised."""
    calls = []

    def fake(*args, **kwargs):
        calls.append(args)
        return returns

    monkeypatch.setattr(
        "src.gui.widgets.conversion_panel.QFileDialog.getExistingDirectory", fake
    )
    return calls


@pytest.fixture
def panel(qtbot):
    return _panel(qtbot)


@pytest.fixture
def wav(tmp_path):
    return _write(tmp_path / "source" / "tone.wav")


@pytest.fixture(autouse=True)
def _source_dir(tmp_path):
    (tmp_path / "source").mkdir(exist_ok=True)


@pytest.fixture
def dest(tmp_path):
    d = tmp_path / "converted"
    d.mkdir()
    return d


class TestTheDefault:
    def test_it_starts_beside_the_source_with_the_toggle_lit(self, panel):
        assert panel.output_dir() == ""
        assert panel._dest_source_toggle.isChecked()

    def test_the_empty_string_reaches_the_signal(self, panel, wav, qtbot):
        panel.add_files([wav])

        with qtbot.waitSignal(panel.start_conversion, timeout=1000) as sig:
            panel._convert_btn.click()

        assert sig.args[5] == ""


class TestChoosingAFolder:
    def test_it_is_shown_persisted_and_emitted(self, panel, wav, dest, qtbot):
        panel._set_destination(str(dest), use_source=False)
        panel.add_files([wav])

        assert panel._dest_path_label.text() == str(dest)
        cfg = load_config()
        assert (cfg.convert_output_dir, cfg.convert_use_source_dir) == (str(dest), False)

        with qtbot.waitSignal(panel.start_conversion, timeout=1000) as sig:
            panel._convert_btn.click()

        assert sig.args[5] == str(dest)

    def test_it_survives_a_restart(self, qtbot, dest):
        first = _panel(qtbot)
        first._set_destination(str(dest), use_source=False)

        rebuilt = ConversionPanel(TrackStore())
        qtbot.addWidget(rebuilt)

        assert rebuilt.output_dir() == str(dest)
        assert not rebuilt._dest_source_toggle.isChecked()

    def test_picking_one_turns_the_toggle_off_by_itself(self, panel, dest, monkeypatch):
        """The user has just named a destination — leaving Source lit would
        ignore it."""
        _no_dialog(panel, monkeypatch, returns=str(dest))
        assert panel._dest_source_toggle.isChecked()

        panel._dest_choose_btn.click()

        assert not panel._dest_source_toggle.isChecked()
        assert panel.output_dir() == str(dest)

    def test_cancelling_the_dialog_changes_nothing(self, panel, dest, monkeypatch):
        panel._set_destination(str(dest), use_source=False)
        _no_dialog(panel, monkeypatch, returns="")  # what Cancel returns

        panel._dest_choose_btn.click()

        assert panel.output_dir() == str(dest)

    def test_the_chosen_path_is_normalized(self, panel, dest, monkeypatch):
        """A dialog result is a path from the OS — on Windows with forward
        slashes, where every other entry point produces backslashes. The output
        paths are built from it and can reach the library through Send To."""
        _no_dialog(panel, monkeypatch, returns=str(dest) + "/")

        panel._dest_choose_btn.click()

        assert panel.output_dir() == str(dest.resolve())


class TestTheSourceToggle:
    def test_switching_on_writes_beside_the_source_again(self, panel, dest):
        panel._set_destination(str(dest), use_source=False)

        panel._dest_source_toggle.setChecked(True)

        assert panel.output_dir() == ""
        assert panel._dest_path_label.text() == "Same folder as source"

    def test_switching_off_restores_the_folder_without_a_dialog(
        self, panel, dest, monkeypatch
    ):
        """The whole reason the path is remembered while the toggle is on."""
        panel._set_destination(str(dest), use_source=False)
        panel._dest_source_toggle.setChecked(True)
        calls = _no_dialog(panel, monkeypatch, returns="")

        panel._dest_source_toggle.setChecked(False)

        assert panel.output_dir() == str(dest)
        assert calls == []

    def test_the_remembered_folder_survives_a_restart_while_lit(self, qtbot, dest):
        """Persisted even though it is not the destination — otherwise the
        one-click way back is gone by the next launch."""
        first = _panel(qtbot)
        first._set_destination(str(dest), use_source=False)
        first._dest_source_toggle.setChecked(True)

        rebuilt = ConversionPanel(TrackStore())
        qtbot.addWidget(rebuilt)
        assert rebuilt.output_dir() == ""

        rebuilt._dest_source_toggle.setChecked(False)
        assert rebuilt.output_dir() == str(dest)

    def test_switching_off_with_nothing_remembered_asks_for_a_folder(
        self, panel, dest, monkeypatch
    ):
        """"Off" has no meaning without a destination behind it."""
        calls = _no_dialog(panel, monkeypatch, returns=str(dest))

        panel._dest_source_toggle.setChecked(False)

        assert len(calls) == 1
        assert panel.output_dir() == str(dest)

    def test_cancelling_that_dialog_leaves_the_toggle_lit(
        self, panel, monkeypatch
    ):
        """Rather than stranding the panel switched off with nowhere to write."""
        _no_dialog(panel, monkeypatch, returns="")

        panel._dest_source_toggle.setChecked(False)

        assert panel._dest_source_toggle.isChecked()
        assert panel.output_dir() == ""
        assert load_config().convert_use_source_dir

    def test_a_remembered_folder_deleted_since_is_re_asked_for(
        self, panel, dest, monkeypatch
    ):
        """Restoring it would switch the panel to a folder that isn't there."""
        panel._set_destination(str(dest), use_source=False)
        panel._dest_source_toggle.setChecked(True)
        dest.rmdir()
        calls = _no_dialog(panel, monkeypatch, returns="")

        panel._dest_source_toggle.setChecked(False)

        assert len(calls) == 1
        assert panel._dest_source_toggle.isChecked()

    def test_its_tooltip_says_what_the_next_click_does(self, panel, dest):
        lit = panel._dest_source_toggle.toolTip()
        panel._set_destination(str(dest), use_source=False)

        assert panel._dest_source_toggle.toolTip() != lit
        assert lit == "Save converted files to a folder instead"
        assert panel._dest_source_toggle.toolTip() == (
            "Save converted files next to the originals"
        )


class TestTheWindowDoesNotRevertIt:
    """`MainWindow._persist_config` re-reads the fields the panels own before
    writing its startup snapshot back on close. A new field that belongs with
    one already on that list has to be added to it, or closing the window
    reverts half a value — here, the folder without the mode, which would put
    the panel back on a destination the user had switched away from."""

    def test_closing_the_window_keeps_both_halves(self, qtbot, dest):
        from src.gui.main_window import MainWindow

        class WindowStub:
            _persist_config = MainWindow._persist_config

            def __init__(self, config):
                self._config = config

        # The window's snapshot is from launch: the shipped default.
        startup = AppConfig()
        # ...and the panel has since written both, mid-session.
        save_config(AppConfig(convert_output_dir=str(dest), convert_use_source_dir=False))

        WindowStub(startup)._persist_config()

        saved = load_config()
        assert saved.convert_output_dir == str(dest)
        assert not saved.convert_use_source_dir


class TestWhatTheRowShows:
    def test_the_full_path_is_on_hover_without_waiting_for_a_resize(
        self, panel, tmp_path
    ):
        """The label elides, and it shares the row with the format selectors,
        so it can be cut down to nothing — the full path has to stay reachable.
        ElidedLabel only re-checks on resize, and picking a folder changes the
        text at an unchanged width, so the panel sets this itself."""
        deep = tmp_path.joinpath(*[f"a-rather-long-folder-name-{n}" for n in range(8)])
        deep.mkdir(parents=True)
        panel._dest_path_label.resize(200, 20)
        panel._set_destination(str(deep), use_source=False)

        assert panel._dest_path_label.toolTip() == str(deep)

    def test_the_button_carries_the_path_too(self, panel, dest):
        """The label is the row's give and can elide away entirely; the button
        cannot shrink, so the destination stays reachable from it."""
        panel._set_destination(str(dest), use_source=False)

        assert str(dest) in panel._dest_choose_btn.toolTip()

    def test_a_remembered_folder_is_not_advertised_while_lit(self, panel, dest):
        """It is not where files are going, and saying so would be a lie."""
        panel._set_destination(str(dest), use_source=False)
        panel._dest_source_toggle.setChecked(True)

        assert panel._dest_path_label.text() == "Same folder as source"
        assert panel._dest_path_label.toolTip() == ""
        assert str(dest) not in panel._dest_choose_btn.toolTip()

    def test_a_path_elides_from_the_left_and_a_message_from_the_right(
        self, panel, dest
    ):
        """Different values want different ends. Cutting a path's tail throws
        away the folder actually chosen and leaves every candidate looking
        alike down the root; a sentence reads from the start."""
        panel._set_destination(str(dest), use_source=False)
        assert panel._dest_path_label._mode == Qt.TextElideMode.ElideLeft

        panel._dest_source_toggle.setChecked(True)
        assert panel._dest_path_label._mode == Qt.TextElideMode.ElideRight


class TestAFolderThatWentAway:
    """A path is stored across sessions; the folder it names is not."""

    def test_a_deleted_folder_reads_as_the_default(self, tmp_path):
        gone = tmp_path / "removed"
        gone.mkdir()
        save_config(AppConfig(convert_output_dir=str(gone), convert_use_source_dir=False))
        gone.rmdir()

        cfg = load_config()
        assert cfg.convert_output_dir == ""
        assert cfg.convert_use_source_dir  # not left "off" with nowhere to write

    def test_the_panel_opens_on_the_default_after_that(self, qtbot, tmp_path):
        gone = tmp_path / "removed"
        gone.mkdir()
        save_config(AppConfig(convert_output_dir=str(gone), convert_use_source_dir=False))
        gone.rmdir()

        panel = ConversionPanel(TrackStore())
        qtbot.addWidget(panel)

        assert panel.output_dir() == ""
        assert panel._dest_source_toggle.isChecked()

    def test_a_folder_removed_this_session_is_recreated(self, panel, wav, dest, qtbot):
        """Gone since it was picked, but its parent is still there — remaking it
        beats refusing a batch over a folder we can restore."""
        panel._set_destination(str(dest), use_source=False)
        panel.add_files([wav])
        dest.rmdir()

        with qtbot.waitSignal(panel.start_conversion, timeout=1000):
            panel._convert_btn.click()

        assert dest.is_dir()

    def test_an_unusable_folder_warns_and_converts_nothing(
        self, panel, wav, tmp_path, monkeypatch
    ):
        """A file where a folder should be: mkdir raises, so the batch must not
        start — every row would otherwise fail with a libsndfile message that
        never names the real problem."""
        blocker = tmp_path / "not-a-folder"
        blocker.write_text("")
        panel._set_destination(str(blocker / "inside"), use_source=False)
        panel.add_files([wav])

        warnings = []
        monkeypatch.setattr(
            "src.gui.widgets.conversion_panel.QMessageBox.warning",
            lambda *args, **kwargs: warnings.append(args),
        )
        emitted = []
        panel.start_conversion.connect(lambda *args: emitted.append(args))
        panel._convert_btn.click()

        assert emitted == []
        assert len(warnings) == 1

    def test_the_probe_file_is_cleaned_up(self, panel, dest):
        """The writability check must not leave anything in the user's folder."""
        panel._set_destination(str(dest), use_source=False)

        assert panel._output_dir_is_writable()
        assert list(dest.iterdir()) == []

    def test_a_remembered_folder_is_not_probed_while_lit(self, panel, tmp_path):
        """The mode decides, so an unusable remembered folder must not block a
        batch that is going beside the sources anyway."""
        blocker = tmp_path / "not-a-folder"
        blocker.write_text("")
        panel._set_destination(str(blocker / "inside"), use_source=True)

        assert panel._output_dir_is_writable()


class TestItReachesTheEngine:
    """The panel's choice is only real if convert_file receives it."""

    def test_the_worker_writes_into_the_chosen_folder(self, wav, dest):
        from src.gui.workers.conversion_worker import ConversionWorker

        worker = ConversionWorker([wav], "AIFF", output_dir=str(dest))

        results = []
        worker.finished.connect(results.append)
        worker.run()

        output = Path(results[0][0].output_path)
        assert output.parent == dest
        assert output.exists()
        assert Path(wav).exists()  # the source is converted, not moved

    def test_no_folder_still_writes_beside_the_source(self, wav):
        from src.gui.workers.conversion_worker import ConversionWorker

        worker = ConversionWorker([wav], "AIFF", output_dir="")

        results = []
        worker.finished.connect(results.append)
        worker.run()

        assert Path(results[0][0].output_path).parent == Path(wav).parent
