"""Spectrum panel Split Screen: two result boxes, one renderer, one slider."""

import numpy as np
import pytest
import soundfile as sf

from src.gui.widgets.spectrum_panel import SpectrumPanel
from src.utils.config import AppConfig, load_config, save_config


def _wav(path, freq):
    sr = 22050
    t = np.arange(sr // 2) / sr
    sf.write(str(path), (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32), sr)
    return str(path.resolve())


@pytest.fixture
def files(tmp_path):
    return [_wav(tmp_path / f"{n}.wav", f) for n, f in (("a", 440), ("b", 880), ("c", 220))]


@pytest.fixture
def panel(qtbot):
    p = SpectrumPanel()
    qtbot.addWidget(p)
    p.show()
    yield p
    p.shutdown_workers()


def _rendered(pane, path):
    return pane.file_path == path and pane.db is not None


def test_toggle_shows_right_box_and_says_what_next_click_does(panel, qtbot):
    assert panel._right.isHidden()
    off_tip = panel._split_btn.toolTip()
    with qtbot.waitSignal(panel.split_toggled) as sig:
        panel._split_btn.click()
    assert sig.args == [True]
    assert not panel._right.isHidden()
    assert panel._split_btn.toolTip() != off_tip
    panel._split_btn.click()
    assert panel._right.isHidden()
    assert panel._split_btn.toolTip() == off_tip


def test_set_split_reflects_without_emitting(panel, qtbot):
    with qtbot.assertNotEmitted(panel.split_toggled):
        panel.set_split(True)
    assert panel._split_btn.isChecked()
    assert not panel._right.isHidden()


def test_new_file_goes_left_and_previous_moves_right(panel, qtbot, files):
    a, b, c = files
    panel.set_split(True)
    panel._load_file(a)
    qtbot.waitUntil(lambda: _rendered(panel._left, a), timeout=10000)
    panel._load_file(b)
    qtbot.waitUntil(lambda: _rendered(panel._left, b), timeout=10000)
    assert _rendered(panel._right, a)
    panel._load_file(c)
    qtbot.waitUntil(lambda: _rendered(panel._left, c), timeout=10000)
    assert _rendered(panel._right, b)


def test_previous_file_is_kept_while_split_is_off(panel, qtbot, files):
    a, b, _ = files
    panel._load_file(a)
    panel._load_file(b)  # a is still rendering: its result must follow it right
    qtbot.waitUntil(
        lambda: _rendered(panel._left, b) and _rendered(panel._right, a), timeout=10000
    )
    assert panel._right.isHidden()
    panel._split_btn.click()
    assert not panel._right.isHidden()
    assert panel._right.file_path == a


def test_drop_on_a_box_fills_only_that_box(panel, qtbot, files):
    a, b, c = files
    panel.set_split(True)
    panel.load_files([a, b])
    qtbot.waitUntil(
        lambda: _rendered(panel._left, a) and _rendered(panel._right, b), timeout=10000
    )
    panel._right.file_dropped.emit(c)
    qtbot.waitUntil(lambda: _rendered(panel._right, c), timeout=10000)
    assert _rendered(panel._left, a)


def test_drop_on_the_box_with_split_off_is_an_ordinary_drop(panel, qtbot, files):
    a, b, _ = files
    panel._load_file(a)
    panel._left.file_dropped.emit(b)
    assert panel._left.file_path == b
    assert panel._right.file_path == a


def test_sensitivity_recolours_both_boxes(panel, qtbot, files):
    a, b, _ = files
    panel.set_split(True)
    panel.load_files([a, b])
    qtbot.waitUntil(
        lambda: _rendered(panel._left, a) and _rendered(panel._right, b), timeout=10000
    )
    panel._sens_slider.setValue(0)
    assert panel._left._colorized_dr == panel._DR_MIN
    assert panel._right._colorized_dr == panel._DR_MIN


def test_hidden_box_is_recoloured_when_shown(panel, qtbot, files):
    a, b, _ = files
    panel._load_file(a)
    panel._load_file(b)
    qtbot.waitUntil(
        lambda: _rendered(panel._left, b) and _rendered(panel._right, a), timeout=10000
    )
    panel._sens_slider.setValue(0)
    assert panel._right._colorized_dr != panel._DR_MIN
    panel.set_split(True)
    assert panel._right._colorized_dr == panel._DR_MIN


def test_same_file_in_both_boxes_reuses_the_render(panel, qtbot, files):
    a, _, _ = files
    panel.set_split(True)
    panel._load_file(a)
    qtbot.waitUntil(lambda: _rendered(panel._left, a), timeout=10000)
    panel._right.file_dropped.emit(a)
    assert _rendered(panel._right, a)  # at once: no second render


def test_split_setting_round_trips():
    save_config(AppConfig(spectrum_split=True))
    assert load_config().spectrum_split is True
