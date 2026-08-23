"""``scripts/vis_sheet.py`` renders something for every mode.

The tool is judged by eye, so what a test can usefully say about it is only
that it still runs: it decodes a file, feeds the real renderer the block the
hosts feed, keeps the frames asked for, and lays them out 1:1. If a mode is
added and the tool stops covering it, this is what says so.
"""

import importlib.util

import numpy as np
import pytest

from src.gui.widgets.vis_canvas import RENDER_MODES

SCRIPT = "scripts/vis_sheet.py"


@pytest.fixture(scope="module")
def sine(tmp_path_factory):
    """Two seconds of a 60 Hz tone pulsed 4x a second — a kick stand-in."""
    soundfile = pytest.importorskip("soundfile")
    sr = 44100
    t = np.arange(2 * sr) / sr
    env = np.exp(-((t * 8) % 1.0) * 12)
    path = tmp_path_factory.mktemp("vis-sheet") / "tone.wav"
    soundfile.write(str(path), (np.sin(2 * np.pi * 60 * t) * env).astype(np.float32), sr)
    return str(path)


@pytest.fixture(scope="module")
def vis_sheet(tmp_path_factory):
    """Import the script by path.

    It redirects HOME at import (it must not touch the developer's real
    config), so point that at a throwaway directory first and let pytest put
    the old value back — the module writes os.environ directly and monkeypatch
    would otherwise have nothing recorded to restore.
    """
    home = tmp_path_factory.mktemp("vis-sheet-home")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("HOME", str(home))
        patch.setenv("APPDATA", str(home))
        patch.setenv("VIS_SHEET_HOME", str(home))
        spec = importlib.util.spec_from_file_location("vis_sheet_under_test", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module


@pytest.mark.parametrize("mode", sorted(RENDER_MODES))
def test_every_mode_renders_frames(qapp, vis_sheet, sine, mode, tmp_path):
    args = vis_sheet.build_parser().parse_args(
        ["--mode", mode, "--track", sine, "--bpm", "120", "--fps", "60",
         "--seconds", "0.06", "--size", "608x256"]
    )
    run = vis_sheet.Run(args)
    run.go()
    assert len(run.render_ms) == 3
    assert run.frames  # something was captured for the sheet

    sheet = vis_sheet.contact_sheet(run.frames, 2)
    assert sheet.width() > 0 and sheet.height() > 0
    # Tiles are pasted 1:1, so the sheet is at least as wide as one frame.
    assert sheet.width() >= run.frames[0][1].width()


def test_frames_are_selected_by_beat(qapp, vis_sheet, sine):
    """--at picks the frame nearest that beat, not that second."""
    args = vis_sheet.build_parser().parse_args(
        ["--mode", "wormhole", "--track", sine, "--bpm", "120", "--fps", "60",
         "--seconds", "1.5", "--at", "1.0,2.0", "--size", "608x256"]
    )
    run = vis_sheet.Run(args)
    run.go()
    assert [beat for beat, _img, _label in run.frames] == [1.0, 2.0]
    # 120 BPM: beat 2 is one second in, i.e. frame 60 of a 60 fps run.
    assert "beat 2.0" in run.frames[1][2]
